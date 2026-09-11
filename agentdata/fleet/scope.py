"""Which file did the operator just drop? (#166)

The page never learns a path. A browser gives a dropped `File` its name, size and bytes and nothing
else, and that is not an oversight to work around -- it is the rule in every embedder the desk has
to run in (Edge, PyCharm's JCEF window, VS Code's Simple Browser). So the page does not ask for a
path: it computes **git's own blob hash** of the bytes and sends that, and this module finds the
file in the checkout that has it.

    sha1("blob " + len(bytes) + "\\0" + bytes)

That is the object name git itself would give the content, so a copy of a tracked file -- dropped
from a search result, a Downloads folder, anywhere -- resolves to the checkout's own path, and a
file that merely *shares a name* with one does not. The name narrows the candidates and the content
decides, which is what keeps a drop a handful of reads rather than a hash of the whole tree.

**Candidates are git's own listing, never a walk.** `git ls-files` and `git ls-files --others
--exclude-standard` are tracked and untracked-but-not-ignored. An ignored file therefore cannot
resolve *by construction*: `.env`, `secrets.json` and everything else in `.gitignore` is not in the
candidate set at all, so there is no rule to relax and no path to get wrong.

**Nothing but a hash leaves the browser** until the operator clicks *attach a copy*, which is the
one action that uploads bytes -- and it lands in `.agent/in/<KEY>/` under the five rules
`handoff.py` owns, exactly as the Downloads tray's attach does.
"""
from __future__ import annotations
import hashlib
import os
import time
from typing import Any

from .. import proc
from .. import textio
from . import events as E
from . import handoff as H

# The weaker claim, and it says so wherever it is shown -- the way adoption labels its two. A file
# too large to hash in a browser tab without freezing it is matched on its name and its size, which
# is evidence, not proof.
BY_HASH, BY_NAME = "fingerprint", "name"
RESOLVED, AMBIGUOUS, UNMATCHED = "resolved", "ambiguous", "unmatched"
SCOPE_COLUMNS = ("path", "why", "by", "at", "how")
# A folder drop is the same trick over its files. Bounded because a drag of `node_modules` is a
# mistake that should be refused quickly rather than hashed for a minute.
MAX_FILES = 200


class ScopeError(Exception):
    def __init__(self, msg: str, hint: str = "", code: str = ""):
        super().__init__(msg)
        self.msg = msg
        self.hint = hint
        self.code = code


def blob_sha(data: bytes) -> str:
    """Git's object name for this content. The page computes the same thing in JavaScript."""
    h = hashlib.sha1()          # noqa: S324 - git's object name is SHA-1; this is not a credential
    h.update(b"blob %d\0" % len(data))
    h.update(data)
    return h.hexdigest()


def _git(repo_path: str, *args: str) -> list[str]:
    """One `git` read in the checkout. Never raises: no git, no candidates."""
    try:
        code, out, _err, _elapsed = proc.run(["git", "--no-optional-locks", *args],
                                             cwd=repo_path, timeout=30)
    except (proc.ProcError, OSError):
        return []
    if code != 0:
        return []
    return [line.strip() for line in (out or "").splitlines() if line.strip()]


def candidates(repo_path: str) -> list[str]:
    """Every file git would call part of this checkout, and nothing it ignores.

    Tracked *and* untracked-but-not-ignored, because a file the operator has just created and not
    yet committed is exactly the file they are most likely to be dropping.
    """
    seen: list[str] = []
    for args in (("ls-files",), ("ls-files", "--others", "--exclude-standard")):
        for rel in _git(repo_path, *args):
            if rel not in seen:
                seen.append(rel)
    return seen


def _hash_file(path: str) -> str:
    try:
        with open(textio.longpath(path), "rb") as handle:
            return blob_sha(handle.read())
    except OSError:
        return ""


def resolve(repo_path: str, files: list[dict], *, max_bytes: int = 64 * 1024 * 1024) -> list[dict]:
    """Match each dropped file to a path in the checkout.

    `files` is `[{name, size, sha}]` -- `sha` empty when the page declined to hash it, which it does
    above `fleet.scope.max_hash_mb` rather than freeze a tab on a two-gigabyte PBIX.

    Only candidates whose *basename* matches are hashed, so a drop costs a handful of reads rather
    than a hash of the whole tree.
    """
    listing = candidates(repo_path)
    by_name: dict[str, list[str]] = {}
    for rel in listing:
        by_name.setdefault(os.path.basename(rel).lower(), []).append(rel)

    out = []
    for item in files:
        name = str(item.get("name") or "")
        sha = str(item.get("sha") or "").strip().lower()
        size = int(item.get("size") or 0)
        same_name = by_name.get(os.path.basename(name).lower(), [])

        if not same_name:
            out.append({"name": name, "status": UNMATCHED, "paths": [], "how": "",
                        "why": "no file of that name is tracked or untracked here"})
            continue

        if not sha:
            # Name-only: the weaker claim, labelled as one. A single same-named candidate whose
            # size also matches is worth offering; anything else is a pick or a miss.
            sized = [rel for rel in same_name
                     if _size_of(repo_path, rel) == size] if size else same_name
            if len(sized) == 1:
                out.append({"name": name, "status": RESOLVED, "paths": sized, "how": BY_NAME,
                            "why": "matched on the name and size; too large to fingerprint"})
            elif sized:
                out.append({"name": name, "status": AMBIGUOUS, "paths": sized, "how": BY_NAME,
                            "why": f"{len(sized)} files of that name and size"})
            else:
                out.append({"name": name, "status": UNMATCHED, "paths": [], "how": "",
                            "why": "a file of that name is here, but it is a different size"})
            continue

        hits = [rel for rel in same_name
                if _hash_file(os.path.join(repo_path, rel)) == sha]
        if len(hits) == 1:
            out.append({"name": name, "status": RESOLVED, "paths": hits, "how": BY_HASH,
                        "why": "the checkout has this exact content"})
        elif hits:
            # The same bytes in two places is a genuine question, not something to guess at.
            out.append({"name": name, "status": AMBIGUOUS, "paths": hits, "how": BY_HASH,
                        "why": f"the same content is at {len(hits)} paths"})
        else:
            out.append({"name": name, "status": UNMATCHED, "paths": [], "how": "",
                        "why": "a file of that name is here, but its content is different"})
    return out


def _size_of(repo_path: str, rel: str) -> int:
    try:
        return os.path.getsize(textio.longpath(os.path.join(repo_path, rel)))
    except OSError:
        return -1


# ----------------------------------------------------------------------------------- scope.toon


def scope_path(repo_path: str, ticket: str) -> str:
    return os.path.join(H.in_dir(repo_path, ticket), H.SCOPE)


def read_scope(repo_path: str, ticket: str) -> list[dict]:
    """The rows already given, so a second drop of the same file is not a second row."""
    try:
        body = textio.read_text(scope_path(repo_path, ticket))
    except OSError:
        return []
    rows = []
    for line in body.splitlines():
        line = line.strip()
        if not line or line.endswith(":") or line.startswith("meta"):
            continue
        cells = _split_toon_row(line)
        if len(cells) == len(SCOPE_COLUMNS):
            rows.append(dict(zip(SCOPE_COLUMNS, cells)))
    return rows


def _split_toon_row(line: str) -> list[str]:
    """TOON's own quoting, read back: commas inside double quotes belong to the cell."""
    cells, cell, quoted = [], [], False
    for ch in line:
        if ch == '"':
            quoted = not quoted
        elif ch == "," and not quoted:
            cells.append("".join(cell).strip())
            cell = []
        else:
            cell.append(ch)
    cells.append("".join(cell).strip())
    return cells


def add(repo_name: str, repo_path: str, ticket: str, paths: list[str], *, why: str = "",
        how: str = BY_HASH, by: str = "operator", queued: bool = False,
        now: float | None = None) -> dict:
    """Append to `.agent/in/<KEY>/scope.toon` and return the `scope.added` event.

    Under `handoff.py`'s five rules, because this is the same directory and the same exception: a
    click or a start, inside `.agent/in/<KEY>/`, always an event, and the `inputs` line asked of
    `ad-state` rather than written behind its back.
    """
    from .. import toon

    wanted = [textio.norm_path(p).lstrip("/") for p in paths if str(p or "").strip()]
    if not wanted:
        raise ScopeError("no files to scope", "drop a file on the tile, or pick one of the matches",
                         code="scope_empty")
    for rel in wanted:
        _refuse_unscopable(rel)

    existing = read_scope(repo_path, ticket)
    have = {row["path"] for row in existing}
    fresh = [rel for rel in wanted if rel not in have]
    stamp = time.strftime("%Y-%m-%dT%H:%M", time.localtime(now if now is not None else time.time()))
    rows = [[rel, why or "dropped on the tile", by, stamp, how] for rel in fresh]

    if rows:
        folder = H.in_dir(repo_path, ticket)
        dest = scope_path(repo_path, ticket)
        root = textio.norm_path(os.path.join(repo_path, *H.IN_DIR.split("/")))
        if not textio.norm_path(dest).startswith(root + "/"):
            raise ScopeError(f"refusing to write outside {H.IN_DIR}",
                             "the destination is computed from the repository root",
                             code="handoff_outside")
        all_rows = [[r["path"], r["why"], r["by"], r["at"], r["how"]] for r in existing] + rows
        try:
            os.makedirs(textio.longpath(folder), exist_ok=True)
            textio.write_text(dest, toon.table("scope", list(SCOPE_COLUMNS), all_rows) + "\n")
        except OSError as e:
            raise ScopeError(f"could not write the scope into {H.IN_DIR}: {e.strerror or e}",
                             "check the disk and the repository's permissions", code="scope_unwritable") from None
        H.ask_ad_state(repo_path, textio.norm_path(os.path.join(H.IN_DIR, H.key_for(ticket), H.SCOPE)))

    data: dict[str, Any] = {"paths": fresh, "how": how, "by": by, "queued": queued,
                            "already": [rel for rel in wanted if rel in have],
                            "dir": H.rel_in_dir(ticket)}
    event = E.event(repo_name, H.SCOPE_KIND, data, ticket=ticket or "")
    try:
        E.append(repo_name, [event])
    except OSError:
        pass          # the stream is held by the agent; the rows stand, the card will show them
    return event


def owner_of(path: str, registry=None):
    """Which registered checkout contains this absolute path, if any. (#167)

    The shells post *paths*, because an IDE has one and the page never will, and the decision about
    which checkout a path belongs to is the server's -- a shell that decided it would be a shell
    with a rule in it, which `tests/test_fleet_shells.py` exists to prevent.

    Longest match wins, so a worktree nested inside its main checkout is its own project rather
    than its parent's. Real paths on both sides: a symlinked route to a checkout is that checkout.
    """
    from .registry import Registry, RegistryError

    try:
        repos = list((registry or Registry()).sorted())
    except RegistryError:
        return None
    try:
        here = textio.norm_path(os.path.realpath(os.path.abspath(path)))
    except OSError:
        here = textio.norm_path(os.path.abspath(path))
    best = None
    for repo in repos:
        try:
            root = textio.norm_path(os.path.realpath(repo.path))
        except OSError:
            root = textio.norm_path(repo.path)
        if here == root or here.lower().startswith(root.lower() + "/"):
            if best is None or len(root) > len(textio.norm_path(os.path.realpath(best.path))):
                best = repo
    return best


def relative_to(repo_path: str, path: str) -> str:
    """The repository-relative spelling a scope row records."""
    try:
        root = os.path.realpath(repo_path)
        here = os.path.realpath(os.path.abspath(path))
    except OSError:
        root, here = repo_path, os.path.abspath(path)
    return textio.norm_path(os.path.relpath(here, root))


def group_by_checkout(paths: list[str], registry=None) -> tuple[dict, list[str]]:
    """Map absolute paths onto the checkouts that own them. Returns `(by_repo, orphans)`."""
    by_repo: dict = {}
    orphans: list[str] = []
    for path in paths:
        repo = owner_of(path, registry=registry)
        if repo is None:
            orphans.append(textio.norm_path(path))
            continue
        by_repo.setdefault(repo.name, {"repo": repo, "paths": []})
        by_repo[repo.name]["paths"].append(relative_to(repo.path, path))
    return by_repo, orphans


def _refuse_unscopable(rel: str) -> None:
    """What may never be scoped, whichever channel asked.

    `.agent/out/` is the agent's own output and pointing it back at itself is a loop; the names the
    catalogue refuses are refused here for the same reason it refuses them.
    """
    lowered = rel.lower()
    if lowered.startswith(".agent/out/") or "/.agent/out/" in lowered:
        raise ScopeError(f"{rel} is the agent's own output",
                         "scope what it should read, not what it wrote", code="scope_refused")
    base = os.path.basename(lowered)
    if base.startswith(".env") or "secret" in base or base == "localsettings.json":
        raise ScopeError(f"{rel} looks like it holds a credential",
                         "nothing credential-shaped is handed to an agent, by any route",
                         code="scope_refused")
