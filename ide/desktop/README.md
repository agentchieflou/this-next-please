# agentdata fleet — the desktop window (a spike)

The desk in a window of its own, drawn by WebView2 (Edge's engine), with no browser tab and no
address bar. It is the instrument [#354](https://github.com/agentchieflou/this-next-please/issues/354)
uses to measure a native host against Edge `--app` on the laptop, and only that measurement decides
whether a desktop host ever becomes the default.

**It is a spike.** An unsigned, unpackaged Python script, run only by its own command: it is not in
the wheel, no `ad-fleet` verb or flag launches it, and nothing in CI imports pywebview.

**It is a shell.** Like the IDE shells it holds no rule logic
([What a shell must do](../../docs/fleet-ide.md#what-a-shell-must-do-100)): `current_desk` finds a
current desk or starts one, as `ad-fleet open` does, and the window hosts the page as `w=desktop`.
The page is the UI.

## Before it runs on a managed laptop

Whether an unsigned Python GUI (pywebview, with pythonnet) may run on a managed laptop is for the
owner of that machine's IT policy to decide, not for this script or for any agent. #354 asks that
question first. On "no", do not run it: the desktop column reads "not run: policy".

## Install

pywebview needs pythonnet, which pip installs with it, and the WebView2 Runtime, which Windows 11
already has. Neither goes into the wheel or into the environment `ad-fleet` runs from. They go into
a venv of their own, next to the installed `agentdata`:

```powershell
ad-update --check          # `python`: the interpreter that owns the installed agentdata
& "<that python>" -m venv --system-site-packages "$HOME\.fleet-window"
& "$HOME\.fleet-window\Scripts\python" -m pip install pywebview
& "$HOME\.fleet-window\Scripts\python" -c "import agentdata, webview; print(agentdata.__file__)"
```

The last line proves that the venv sees both, and that the `agentdata` it runs is the one `ad-update`
keeps current. If `import agentdata` fails there, the one `ad-update` keeps lives in a venv of its
own: install pywebview into that venv instead, which still leaves the wheel without it.

## Run

The script is one file that imports only the installed `agentdata`. Run it from a checkout of this
repository, or from a copy of `ide/desktop/fleet_window.py` saved anywhere:

```powershell
& "$HOME\.fleet-window\Scripts\python" ide\desktop\fleet_window.py           # the desk, as w=desktop
& "$HOME\.fleet-window\Scripts\python" ide\desktop\fleet_window.py --probe   # the WebGL probe, as shell desktop
```

- It starts a current desk first when none is up, then opens a window titled `fleet`.
- It prints one line, `fleet window: time.time() at start = <seconds> (desk: <how>)`. The time is
  taken before `agentdata` loads. #354 reads the cold start from it to `origin_ms + first_paint_ms`
  of the cold-open load record (#351), so multiply it by 1000 first.
- Closing the window saves its place and size to `desktop.json` in the fleet directory
  (`~/.agentdata/fleet`, or `$AGENTDATA_FLEET_DIR` when that is set), and the next start reopens it
  there. A window closed while minimised keeps the place saved before it. Delete the file to start
  centred again.
- Without pywebview it prints `hint: pip install pywebview …` and exits 2
  ([refusals](../../docs/refusals.md)).
- `ad-fleet open --all` leaves the `desktop` window to this script and lists it under `skipped`: a
  browser tab under that name would share the window's record on the desk.

## What it is not

It has no exe, no installer, no signing, no `WHERE` entry and no probe column (a host gets a column
only after #354 has probed it). It never becomes the default without #354's GO. Taking it out is
deleting `ide/desktop/`, its tests in `tests/test_fleet_shells.py`, and `desktop` in `IDE_WINDOWS`
(`agentdata/fleet/opener.py`).
