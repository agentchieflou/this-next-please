"""WebGL, measured by the shell that will draw it (#247, slice A of the ink epic #246).

`docs/desk-engines.md` says WebGL is not used "until these rows say all four shells run it", and
three of its four columns said *not yet measured*. This is the measurement. `/probe` on the desk
opens a WebGL context, loads the vendored three.js, draws a fixed stroke scene for three seconds
and posts what it saw; this module keeps it in `~/.agentdata/fleet/probes.json`, one record per
shell, so nobody copies a renderer string out of a dev console by hand.

**The page sends facts and this module decides.** The renderer string, the context it got, the
frame intervals: raw. Whether that is hardware is `classify()`, here, once -- so the server's
answer to the page, `ad-fleet probe`, `ad-fleet engines` and the tests all share one function, and
a pattern added later reclassifies every record already on disk. That is why the file stores the
facts and never the verdict.

**A software renderer is a fallback, not a pass.** SwiftShader, llvmpipe and Microsoft's Basic
Render Driver all answer `getContext("webgl2")` and draw correctly -- at five to ten frames a second.
A desk drawn at that rate is worse than the plain one, so they count as *falls back*, the same as
no WebGL at all. The rule for the rest of the epic follows from it: **only a shell whose probe says
`hardware` gets the ink layer; every other answer gets the plain fallback.**
"""
from __future__ import annotations
import json
import math
import os
import re
import threading

from .. import textio
from . import events as E
from .registry import fleet_dir

PROBES_FILE = "probes.json"
SCHEMA = 1

#: The four shells `docs/desk-engines.md` has a column for, and that column's heading exactly --
#: a test holds the two together. `chromium` is the headless one CI drives; the other three are the
#: operator's, measured on the laptop with `ad-fleet probe --open <shell>`.
COLUMNS = {
    "chromium": "Chromium 141",
    "edge": "Edge (current)",
    "pycharm": "JCEF (PyCharm 2026.1)",
    "vscode": "Simple Browser (VS Code)",
}

#: Software rasterisers, as the *unmasked* renderer string names them, lower-cased substring first
#: and the name to print second. The masked `RENDERER` is `WebKit WebGL` everywhere and says
#: nothing. Through ANGLE they arrive wrapped -- `ANGLE (Google, Vulkan 1.3.0 (SwiftShader Device
#: (Subzero) ...), SwiftShader driver)`, `ANGLE (Microsoft, Microsoft Basic Render Driver Direct3D11
#: ...)`, `ANGLE (Mesa, llvmpipe (LLVM 15.0.7, 256 bits), OpenGL 4.5)` -- which is why this is a
#: substring match and not a lookup.
SOFTWARE = (
    ("swiftshader", "SwiftShader"),
    ("llvmpipe", "llvmpipe"),
    ("lavapipe", "lavapipe"),
    ("softpipe", "softpipe"),
    ("microsoft basic render", "Microsoft Basic Render Driver"),
    ("apple software renderer", "Apple Software Renderer"),
    ("mesa offscreen", "Mesa OffScreen"),
    ("software rasterizer", "software rasterizer"),
)

#: The rule the rest of the epic reads, in the words `ad-fleet probe` and `ad-fleet engines` print.
RULE = "hardware WebGL works; a software renderer or no WebGL gets the plain fallback"

#: `hardware` is the only class that means *works*. `unknown` is a context that drew but would not
#: name its renderer: not proven hardware, so it falls back with the other two. `incomplete` is a
#: probe that did not finish -- hidden while it drew, its context lost, too few frames to have
#: measured anything: it says nothing about the shell either way, so it is *not yet measured* and
#: never replaces a measurement that did finish.
CLASSES = ("hardware", "software", "none", "unknown", "incomplete")
CONTEXTS = ("webgl2", "webgl1", "none")

#: A shell's name is the `w=` a desk window already carries (`pycharm`, `vscode`) or the `shell=`
#: the CLI put on the URL. It is a key in a file, so it is a short lower-case word and nothing else.
SHELL = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
MAX_INTERVALS = 2000                 # three seconds at 240 Hz is 720; this is a ceiling, not a goal
#: Fewer frames than this is not a measurement. A software rasteriser manages fifteen-odd in three
#: seconds; a window hidden after its first frame manages none, and its p50 is `null`.
MIN_FRAMES = 5
MAX_FRAME_MS = 60_000.0
TEXT_CAP = 400

_LOCK = threading.Lock()


class ProbeError(Exception):
    def __init__(self, msg: str, hint: str = "", code: str = "probe_refused"):
        super().__init__(msg)
        self.msg = msg
        self.hint = hint
        self.code = code


# ------------------------------------------------------------------------------ the one rule


def software_name(renderer: str) -> str:
    """The software rasteriser this renderer string names, or `""` when it names none."""
    low = str(renderer or "").lower()
    for needle, name in SOFTWARE:
        if needle in low:
            return name
    return ""


def classify(record: dict) -> str:
    """`hardware`, `software`, `none`, `unknown` or `incomplete`, from the facts the page sent.

    * `none`: no WebGL context, or one that never put the scene on the canvas (`drawn` false).
    * `incomplete`: the window was hidden while it drew, or it drew and then stopped -- an `error`
      after the first frame, or fewer than `MIN_FRAMES` frames. Checked before `hardware`, because
      a GPU string on a probe that lost its context a second in is not evidence of anything (#261).
    * `software`: the renderer string names a software rasteriser, or the browser refused a context
      with `failIfMajorPerformanceCaveat` -- its own way of saying the same thing.
    * `unknown`: a context that drew but would not name its renderer.
    * `hardware`: everything else. The only class that *works*.
    """
    if str(record.get("webgl") or "none") not in ("webgl2", "webgl1"):
        return "none"
    if record.get("hidden") is True:
        return "incomplete"
    if record.get("drawn") is False:
        return "none"
    if software_name(record.get("renderer", "")) or record.get("caveat") is True:
        return "software"
    if str(record.get("error") or "").strip() or int(record.get("frames") or 0) < MIN_FRAMES:
        return "incomplete"
    if not str(record.get("renderer") or "").strip():
        return "unknown"
    return "hardware"


def verdict(record: dict | None) -> str:
    """The cell `docs/desk-engines.md` takes for this record, in that table's own vocabulary."""
    if not record:
        return "not yet measured"
    cls = classify(record)
    if cls == "hardware":
        return "works"
    if cls == "software":
        why = software_name(record.get("renderer", "")) or "major performance caveat"
        return f"falls back — software ({why})"
    if cls == "none":
        return "falls back — no WebGL"
    if cls == "incomplete":
        why = str(record.get("error") or "").strip() or f"{record.get('frames') or 0} frames"
        return f"not yet measured — the probe did not finish ({why})"
    return "falls back — renderer unknown"


def works(record: dict | None) -> bool:
    """The gate the rest of the epic reads: does this shell get the ink layer?"""
    return bool(record) and classify(record) == "hardware"


# ------------------------------------------------------------------------------ the numbers


def percentile(values: list[float], q: float) -> float | None:
    """Nearest-rank: the smallest value with at least `q`% of the samples at or below it.

    Nearest-rank rather than interpolated because a software renderer gives twenty-odd frames in
    three seconds, and an interpolated p95 of twenty samples is a number no frame ever took.
    """
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(q / 100.0 * len(ordered)))
    return ordered[min(rank, len(ordered)) - 1]


def _ms(value) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(out) or out < 0 or out > MAX_FRAME_MS:
        return None
    return round(out, 1)


def _text(value, cap: int = TEXT_CAP) -> str:
    return str(value or "").replace("\r", " ").replace("\n", " ").strip()[:cap]


def shell_name(value) -> str:
    name = str(value or "").strip().lower()
    if not SHELL.match(name):
        raise ProbeError(f"not a shell name: {str(value)[:40]!r}",
                         "a short lower-case word, like the `w=` a desk window carries "
                         "(pycharm, vscode, edge, browser)", code="probe_shell")
    return name


def normalize(body: dict) -> dict:
    """The record to keep, from what the page posted. Refuses a shape it cannot read.

    Only facts go in. The frame intervals are reduced to their count, p50 and p95 here, once, so
    the file stays a few hundred bytes per shell and every reader agrees on the arithmetic.
    """
    if not isinstance(body, dict):
        raise ProbeError("the probe must be a JSON object", code="probe_shape")
    shell = shell_name(body.get("shell"))
    context = str(body.get("webgl") or "").strip().lower()
    if context not in CONTEXTS:
        raise ProbeError(f"webgl must be one of {', '.join(CONTEXTS)}, not {context[:20]!r}",
                         "the page sends what getContext() answered", code="probe_shape")
    raw = body.get("intervals")
    if raw is None:
        raw = []
    if not isinstance(raw, list):
        raise ProbeError("intervals must be a list of milliseconds", code="probe_shape")
    intervals = [v for v in (_ms(x) for x in raw[:MAX_INTERVALS]) if v is not None]
    p50, p95 = percentile(intervals, 50), percentile(intervals, 95)
    return {
        "shell": shell,
        "at": E.stamp(),
        "ua": _text(body.get("ua")),
        "webgl": context,
        "renderer": _text(body.get("renderer")),
        "vendor": _text(body.get("vendor")),
        "caveat": body.get("caveat") is True,
        "three": _text(body.get("three"), 16),
        "frames": len(intervals),
        "p50_ms": p50,
        "p95_ms": p95,
        "first_stroke_ms": _ms(body.get("first_stroke_ms")),
        "load_ms": _ms(body.get("load_ms")),
        "drawn": body.get("drawn") is True,
        "hidden": body.get("hidden") is True,
        "error": _text(body.get("error")),
    }


# ---------------------------------------------------------------------------------- the file


def probes_file() -> str:
    return os.path.join(fleet_dir(), PROBES_FILE)


def _read() -> dict:
    try:
        data = json.loads(textio.read_text(probes_file()))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _records(data: dict, key: str) -> dict[str, dict]:
    got = data.get(key)
    if not isinstance(got, dict):
        return {}
    return {str(k): v for k, v in got.items() if isinstance(v, dict)}


def load() -> dict[str, dict]:
    """Every shell's newest record, keyed by shell. A missing or unreadable file is no records:
    it is a measurement cache, and `ad-fleet probe --open` makes a new one in three seconds."""
    return _records(_read(), "probes")


def attempts() -> dict[str, dict]:
    """Every shell's newest *post*, finished or not -- what `ad-fleet probe --open` waits for, so a
    probe that arrived and did not finish is reported as that rather than as silence."""
    return _records(_read(), "attempts")


def record(body: dict) -> dict:
    """Keep one probe, replacing that shell's last one and leaving every other shell's alone.

    Except that a probe which did not finish never replaces one that did (#261): a tool window
    hidden a second after the CLI asked it to measure is not news about its GPU, and writing it over
    last week's *works* would turn the ink layer off for a reason nobody could see. It is kept as
    the shell's latest attempt, answered -- the page shows what happened -- and `kept` says which
    record stands.
    """
    rec = normalize(body)
    cls = classify(rec)
    with _LOCK:
        data = _read()
        probes, tries = _records(data, "probes"), _records(data, "attempts")
        old = probes.get(rec["shell"])
        kept = bool(cls == "incomplete" and old and classify(old) != "incomplete")
        if not kept:
            probes[rec["shell"]] = rec
        tries[rec["shell"]] = rec
        textio.write_json(probes_file(), {"schema": SCHEMA, "probes": probes, "attempts": tries})
    out = {"shell": rec["shell"], "record": rec, "class": cls, "verdict": verdict(rec),
           "software": software_name(rec["renderer"]), "file": textio.norm_path(probes_file()),
           "kept": kept}
    if kept:
        out["kept_at"] = old.get("at", "")
        out["kept_verdict"] = verdict(old)
    return out


# ---------------------------------------------------------------------------------- the rows


PROBE_COLUMNS = ["shell", "at", "webgl", "class", "renderer", "p50_ms", "p95_ms",
                 "first_stroke_ms", "frames", "three", "error", "ua"]

ENGINE_COLUMNS = ["shell", "column", "webgl", "context", "renderer", "p50_ms", "p95_ms",
                  "first_stroke_ms", "at", "error"]


def _order(probes: dict[str, dict]) -> list[str]:
    return list(COLUMNS) + sorted(k for k in probes if k not in COLUMNS)


def probe_rows(probes: dict[str, dict] | None = None) -> list[list]:
    """One row per shell that has been probed: the facts, and the class they add up to."""
    probes = load() if probes is None else probes
    rows = []
    for shell in _order(probes):
        rec = probes.get(shell)
        if not rec:
            continue
        rows.append([shell, rec.get("at", ""), rec.get("webgl", ""), classify(rec),
                     rec.get("renderer", ""), rec.get("p50_ms"), rec.get("p95_ms"),
                     rec.get("first_stroke_ms"), rec.get("frames", 0), rec.get("three", ""),
                     rec.get("error", ""), rec.get("ua", "")])
    return rows


def engine_rows(probes: dict[str, dict] | None = None) -> list[list]:
    """The WebGL row of `docs/desk-engines.md`, one line per column: the four shells it names
    whether or not they have been probed (*not yet measured* is a true answer), then any other
    shell that has been."""
    probes = load() if probes is None else probes
    rows = []
    for shell in _order(probes):
        rec = probes.get(shell)
        if not rec and shell not in COLUMNS:
            continue
        rec = rec or {}
        rows.append([shell, COLUMNS.get(shell, ""), verdict(rec or None), rec.get("webgl", ""),
                     rec.get("renderer", ""), rec.get("p50_ms"), rec.get("p95_ms"),
                     rec.get("first_stroke_ms"), rec.get("at", ""), rec.get("error", "")])
    return rows
