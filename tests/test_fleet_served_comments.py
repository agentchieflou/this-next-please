"""The desk's scripts and stylesheets: types in the source, reasoning beside it, nothing on the wire (#523).

Decision 18 on #429, the operator's words: *"For performance's sake, app.js shouldn't have comments.
It should have a tagalong file that covers documentation. We will eventually be having a hyper
optimization path to target sub 200ms load times everywhere, so raising the cap isn't an option."*
Decision 19: the JSDoc types stay in the source, where `tsc` checks the code against them, and the
server strips every comment from what it serves.

So, for every `.js` and `.css` under `agentdata/fleet/static/` (what `serve._static` serves, any file
there by its path; `vendor/` aside, three.js as it shipped):
* the source carries no prose: a comment is a JSDoc block of type tags and nothing else
  (`@typedef`, `@param`, `@returns`, `@property`, `@type`), never a sentence;
* its reasoning is in `<file>.md` beside it, which the server refuses to serve;
* what goes out is the source without any comment at all (`agentdata/fleet/strip.py`), and it is the
  same program (acorn) or the same stylesheet (css-tree) as the source.

A comment is found by tokenizing, never by a pattern over the text: `"//"` in a URL string, a `/*`
inside a regular expression or a template literal, and `url(/*x*/)` in a stylesheet are code.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import urllib.error
import urllib.request

import pytest

from agentdata.fleet import serve as S
from agentdata.fleet.strip import css_comments, js_comments, strip_css, strip_js

STATIC = S.STATIC
#: Someone else's files, served as they shipped: three.js keeps its licence header.
THIRD_PARTY = ("vendor",)


def served() -> list[str]:
    """Every script and stylesheet `serve._static` would answer for, by its path under `static/`."""
    out = []
    for root, _dirs, files in os.walk(STATIC):
        rel_root = os.path.relpath(root, STATIC)
        if rel_root.split(os.sep)[0] in THIRD_PARTY:
            continue
        for n in files:
            if n.endswith((".js", ".css")):
                out.append(os.path.normpath(os.path.join(rel_root, n)).replace(os.sep, "/"))
    return sorted(out)


def _source(rel: str) -> str:
    return open(os.path.join(STATIC, rel), encoding="utf-8").read()


_TAG = re.compile(r"@(typedef|param|returns?|property|type|template|callback)\b")
_NAMED = {"typedef", "param", "property"}
_NAME = re.compile(r"\[[^\]\n]*\]|[A-Za-z_$][\w$.]*")


def is_type_doc(text: str) -> bool:
    """`/** @param {X} name  @returns {Y} */`: JSDoc that is type tags, their types and their names,
    and not one word more. A sentence -- a description, a tag's explanation -- is prose, and prose
    lives in the tagalong."""
    if not (text.startswith("/**") and text.endswith("*/")) or text == "/**/":
        return False
    lines = text[3:-2].split("\n")
    body = " ".join([lines[0]] + [re.sub(r"^\s*\*(?!/)", "", ln) for ln in lines[1:]])
    i, n, tags = 0, len(body), 0
    while True:
        while i < n and body[i].isspace():
            i += 1
        if i == n:
            return tags > 0
        m = _TAG.match(body, i)
        if not m:
            return False
        i = m.end()
        while i < n and body[i].isspace():
            i += 1
        if i >= n or body[i] != "{":
            return False
        depth = 0
        for j in range(i, n):
            depth += {"{": 1, "}": -1}.get(body[j], 0)
            if depth == 0:
                break
        else:
            return False
        i = j + 1
        if m.group(1) in _NAMED:
            while i < n and body[i].isspace():
                i += 1
            name = _NAME.match(body, i)
            if not name:
                return False
            i = name.end()
        tags += 1


def prose_in(rel: str, src: str) -> list[str]:
    """The comments `rel` may not carry, each with its line number."""
    spans = css_comments(src) if rel.endswith(".css") else js_comments(src)
    return [f"{rel}:{src.count(chr(10), 0, s) + 1}: {src[s:e][:60]!r}" for s, e in spans
            if rel.endswith(".css") or not is_type_doc(src[s:e])]


# ---- the scanner and the stripper, on the cases a pattern gets wrong

def test_the_comment_scanner_steps_over_strings_regexes_and_templates():
    def found(src):
        return [src[s:e] for s, e in js_comments(src)]

    assert found('var u = "http://x/*y*/"; // one') == ["// one"]
    assert found("var u = 'a // b'; /* two */") == ["/* two */"]
    assert found(r'var s = "a \" // still a string";') == []
    assert found("var r = /\\/\\/[/*]/g; x = a / b / c; // three") == ["// three"]
    assert found("if (x) return /[/*]/.test(y); // four") == ["// four"]
    assert found("var t = `a // ${b /* five */ + `c /* ${d} */`} */`;") == ["/* five */"]
    assert found("var t = `${ {a: 1}.a }` // six") == ["// six"]
    assert found("x = a++ / 2; // seven") == ["// seven"]
    assert found("x = y.return / 2 // eight") == ["// eight"]
    assert found("x = (a) / 2 /* nine */ / 3") == ["/* nine */"]
    assert found("}\n/re*/.test(s) // ten") == ["// ten"]
    for broken in ("x = '", "/* never closed", "var t = `", "x = /abc"):
        with pytest.raises(ValueError):
            js_comments(broken)


def test_the_comment_scanner_steps_over_css_strings_and_urls():
    def found(src):
        return [src[s:e] for s, e in css_comments(src)]

    assert found('a { content: "/* not */"; } /* one */') == ["/* one */"]
    assert found("a { background: url(data:x/*y*/z); } /* two */") == ["/* two */"]
    assert found("a { background: url( '/*q*/' ); }") == []
    assert found("a { background: URL(/*u*/); }") == []
    assert found(r'a { content: "\"/*"; } b::after { content: "*/" }') == []
    assert found("a { --x: 1/*three*/; }") == ["/*three*/"]


def test_the_stripper_leaves_the_program_and_takes_only_the_comments():
    """The golden cases: a comment alone on its lines goes with them (and one blank line of two
    stays), one at the end of a line goes with the spaces before it, and one inside a line leaves a
    space in a script -- a line break if it held one, which is what automatic semicolon insertion
    reads -- and nothing in a stylesheet."""
    js = ('"use strict";\n\n/**\n * @typedef {Object} A\n */\n\n/** @param {A} a */\nfunction f(a) {\n'
          '  var u = "http://x"; // why\n  var t = `// ${a /* in */ + 1}`;\n'
          '  var c = /** @type {HTMLElement} */ (q("c"));\n  return a/**/+b\n    /* two\n  lines */ ;\n}\n'
          'x = y /*\n*/ z\n')
    assert strip_js(js) == ('"use strict";\n\nfunction f(a) {\n'
                            '  var u = "http://x";\n  var t = `// ${a  + 1}`;\n'
                            '  var c =  (q("c"));\n  return a +b\n    \n ;\n}\n'
                            'x = y \n z\n')
    css = ('/* the file */\n\n.a/**/.b { color: red; } /* end */\n'
           '.c { background: url(x/*y*/.png); /* mid */ margin: 0; }\n\n/* one */\n\n.d {}\n')
    assert strip_css(css) == ('\n.a.b { color: red; }\n'
                              '.c { background: url(x/*y*/.png);  margin: 0; }\n\n.d {}\n')


def test_a_type_doc_is_the_one_comment_a_source_may_carry():
    assert is_type_doc("/** @type {HTMLElement} */")
    assert is_type_doc("/** @param {Row} row  @param {number} [index]  @returns {Pane | null} */")
    assert is_type_doc("/**\n * @typedef {Object} Pane\n * @property {HTMLElement} el\n"
                       " * @property {{a: {b: number}}} [row]\n */")
    assert not is_type_doc("/** @param {Row} row  the agent's row */")
    assert not is_type_doc("/** The desk.\n * @typedef {Object} Desk\n */")
    assert not is_type_doc("/* @type {X} */")
    assert not is_type_doc("/** @type {X} and why */")
    assert not is_type_doc("/** @see {X} */")
    assert not is_type_doc("// @type {X}")
    assert len(prose_in("x.js", "var a = 1; // why\n/** @type {A} */\nvar b;\n/** b */")) == 2


# ---- the source

def test_a_desk_source_carries_types_but_no_prose():
    """The source's comments are JSDoc type tags for `tsc`, and nothing else: the reasoning is in the
    file's tagalong `<file>.md`, and a stylesheet carries none at all."""
    names = served()
    assert "app.js" in names and "app.css" in names and "ink/layer.js" in names, names
    for asset in S.ASSETS + S.INK_LAYER_MODULES:
        assert asset in names or asset.startswith(THIRD_PARTY), asset
    found = []
    for rel in names:
        found += prose_in(rel, _source(rel))
    assert not found, (f"{len(found)} prose comments in the desk's source; the reasoning goes in the "
                       f"file's tagalong <file>.md (#523):\n" + "\n".join(found[:20]))


def test_every_served_script_and_stylesheet_has_its_tagalong_md():
    """`<file>.md` beside each, headed by the file's own path, and no tagalong without its file."""
    names = served()
    missing = [rel for rel in names if not os.path.isfile(os.path.join(STATIC, rel + ".md"))]
    assert not missing, f"no tagalong .md for: {missing}"
    for rel in names:
        head = open(os.path.join(STATIC, rel + ".md"), encoding="utf-8").readline()
        assert head.strip() == f"# `{rel}`", (rel, head)
    orphans = []
    for root, _dirs, files in os.walk(STATIC):
        for n in files:
            if n.endswith(".md"):
                rel = os.path.relpath(os.path.join(root, n), STATIC).replace(os.sep, "/")
                if rel[:-3] not in names:
                    orphans.append(rel)
    assert not orphans, f"a tagalong whose file is gone: {orphans}"


# ---- what is served

def test_the_server_sends_every_script_and_stylesheet_without_a_comment():
    """Over HTTP, as a page gets it: no comment in the bytes, the length they are, and the tagalong
    refused. Every served file strips without the tokenizer giving up on it."""
    for rel in served():
        src = _source(rel)
        out = (strip_js if rel.endswith(".js") else strip_css)(src)
        assert S.static_body(rel) == out.encode("utf-8"), rel
        assert (js_comments if rel.endswith(".js") else css_comments)(out) == [], rel
        assert len(out) < len(src) or not (js_comments if rel.endswith(".js") else css_comments)(src)

    server, token = S.build(0)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        for rel in ("app.js", "app.css", "ink/layer.js", "skins/glass/skin.css"):
            asked = urllib.request.Request(f"http://127.0.0.1:{port}/static/{rel}?t={token}",
                                           headers={"Accept-Encoding": "identity"})
            with urllib.request.urlopen(asked, timeout=10) as r:
                body = r.read()
                assert int(r.headers["Content-Length"]) == len(body), rel
            text = body.decode("utf-8")
            assert (js_comments if rel.endswith(".js") else css_comments)(text) == [], rel
            if rel.endswith(".js"):
                assert "@typedef" not in text and "@type {" not in text, rel
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/static/vendor/three/three.module.min.js"
                                    f"?t={token}", timeout=10) as r:
            assert r.read() == open(os.path.join(STATIC, "vendor", "three", "three.module.min.js"),
                                    "rb").read(), "three.js goes out as it shipped"
        for rel in ("app.js.md", "app.css.md", "ink/layer.js.md"):
            assert os.path.isfile(os.path.join(STATIC, rel)), rel
            with pytest.raises(urllib.error.HTTPError) as refused:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/static/{rel}?t={token}", timeout=10)
            assert refused.value.code == 404, rel
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()


#: The parsers the proof below uses, exactly, fetched by `npx` as the type check's compiler is.
ACORN, CSS_TREE = "acorn@8.15.0", "css-tree@3.1.0"
_SAME = r"""
const fs = require("fs"), acorn = require("acorn"), csstree = require("css-tree");
const pairs = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const bare = (n) => JSON.stringify(n, (k, v) => (k === "start" || k === "end") ? undefined : v);
function program(t, type) { return acorn.parse(t, { ecmaVersion: "latest", sourceType: type, allowHashBang: true }); }
function js(a, b) {
  for (const type of ["script", "module"]) {
    let pa; try { pa = program(a, type); } catch (e) { continue; }
    return bare(pa) === bare(program(b, type));
  }
  throw new Error("parses as neither a script nor a module");
}
function tokens(t) {
  const out = [];
  csstree.tokenize(t, (type, s, e) => {
    if (type === csstree.tokenTypes.Comment) return;
    const v = type === csstree.tokenTypes.WhiteSpace ? " " : t.slice(s, e);
    if (v === " " && out[out.length - 1] === " ") return;
    out.push(v);
  });
  while (out[0] === " ") out.shift();
  while (out[out.length - 1] === " ") out.pop();
  return out.join("\u0000");
}
const differ = pairs.filter(([rel, a, b]) => rel.endsWith(".js") ? !js(a, b) : tokens(a) !== tokens(b));
console.log(JSON.stringify({ checked: pairs.length, differ: differ.map((p) => p[0]) }));
"""


@pytest.mark.network
@pytest.mark.real_home
def test_every_served_file_is_its_source_without_the_comments(tmp_path):
    """The proof the stripper is safe on the files it serves: each script, stripped, parses to the
    same program as its source (acorn; positions aside, and acorn keeps no parentheses), and each
    stylesheet to the same tokens but for comments and how long a run of whitespace is (css-tree).
    `npx` fetches the two pinned parsers the first time, as the type check fetches its compiler."""
    if os.environ.get("AGENTDATA_OFFLINE"):
        pytest.skip(f"AGENTDATA_OFFLINE is set, and npx may have to fetch {ACORN} and {CSS_TREE}")
    npx = shutil.which("npx")
    if not npx:
        pytest.skip("no npx on this machine: the proof needs Node")
    pairs = [[rel, _source(rel), S.static_body(rel).decode("utf-8")] for rel in served()]
    manifest = tmp_path / "pairs.json"
    manifest.write_text(json.dumps(pairs), encoding="utf-8")
    script = tmp_path / "same.js"
    script.write_text(_SAME, encoding="utf-8")
    # Both packages land in one npx directory; the script finds them next to acorn's own bin.
    run = f'NODE_PATH="$(dirname "$(dirname "$(command -v acorn)")")" node "{script}" "{manifest}"'
    p = subprocess.run([npx, "--yes", "-p", ACORN, "-p", CSS_TREE, "-c", run], cwd=tmp_path,
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=240, stdin=subprocess.DEVNULL)
    out = (p.stdout or "") + (p.stderr or "")
    if p.returncode != 0 and re.search(r"npm (ERR|error)|command not found|not recognized", out):
        # npx never got as far as the script (no registry, no proxy, no POSIX shell for `-c`):
        # a machine without the tool, not a stripper that changed a program.
        pytest.skip(f"{ACORN} and {CSS_TREE} could not be fetched or run: {out.strip()[-300:]}")
    assert p.returncode == 0, out[-2000:]
    result = json.loads(out.strip().splitlines()[-1])
    assert result == {"checked": len(pairs), "differ": []}, result
