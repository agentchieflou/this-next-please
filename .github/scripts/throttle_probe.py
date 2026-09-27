"""#307 calibration probe: does CDP Emulation.setCPUThrottlingRate slow a CPU-bound loop, per OS?

Prints one JSON object per line. Not a test; a temporary CI step on a probe branch.
"""
import json
import os
import platform
import statistics
import sys
import time

from playwright.sync_api import sync_playwright

LOOP = """(n) => { const t0 = performance.now(); let x = 0;
  for (let i = 0; i < n; i++) x += i % 7;
  return x > 0 ? performance.now() - t0 : -1; }"""

# Busy for `ms` of wall time; returns how much of it the loop actually ran (gaps > 0.3 ms between
# consecutive clock reads are time the thread was not running) and how many such gaps.
DUTY = """(ms) => { const t0 = performance.now(); let last = t0, lost = 0, gaps = 0, big = 0;
  while (true) { const t = performance.now(); const d = t - last;
    if (d > 0.3) { lost += d; gaps++; big = Math.max(big, d); }
    last = t; if (t - t0 > ms) break; }
  const wall = last - t0; return { wall, ran: wall - lost, gaps, biggest_gap: big }; }"""

ANIM = """<canvas id=c width=800 height=600></canvas><script>
const g = document.getElementById('c').getContext('2d'); let k = 0;
(function f() { k++; g.fillStyle = `hsl(${k % 360},60%,50%)`; g.fillRect(0, 0, 800, 600); requestAnimationFrame(f); })();
</script>"""


def emit(**row):
    print(json.dumps(row), flush=True)


def cpu_name():
    if sys.platform == "win32":
        import winreg
        k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
        return winreg.QueryValueEx(k, "ProcessorNameString")[0].strip()
    if sys.platform == "darwin":
        import subprocess
        return subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True, text=True).stdout.strip()
    try:
        return next(l.split(":", 1)[1].strip() for l in open("/proc/cpuinfo") if l.startswith("model name"))
    except Exception:  # noqa: BLE001
        return platform.processor()


def timer_resolution_ms():
    if sys.platform != "win32":
        return None
    import ctypes
    lo, hi, cur = ctypes.c_ulong(), ctypes.c_ulong(), ctypes.c_ulong()
    ctypes.WinDLL("ntdll").NtQueryTimerResolution(ctypes.byref(lo), ctypes.byref(hi), ctypes.byref(cur))
    return {"coarsest": lo.value / 1e4, "finest": hi.value / 1e4, "current": cur.value / 1e4}


def main():
    exe = os.environ.get("AGENTDATA_CHROMIUM") or None
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=exe)
        emit(os=platform.platform(), cpu=cpu_name(), cpus=os.cpu_count(), browser=browser.version,
             timer_ms=timer_resolution_ms())
        def open_page(rate):
            page = browser.new_context().new_page()
            page.goto("about:blank")
            if rate > 1:
                page.context.new_cdp_session(page).send("Emulation.setCPUThrottlingRate", {"rate": rate})
            return page

        # Only one throttled page at a time, as in the test: on Windows each throttled renderer
        # runs a throttling thread of its own that busy-waits.
        plain = open_page(1)
        n0 = 2_000_000
        ms0 = min(plain.evaluate(LOOP, n0) for _ in range(5))
        per_ms = n0 / ms0
        emit(calibrate={"iterations": n0, "ms": round(ms0, 2), "iterations_per_ms": round(per_ms)})

        def round_(label):
            for rate in (2, 4, 8):
                tab = open_page(rate)
                for target in (15, 60, 250):
                    n = int(per_ms * target)
                    runs = {1: [], rate: []}
                    for _ in range(7):
                        runs[1].append(plain.evaluate(LOOP, n))
                        runs[rate].append(tab.evaluate(LOOP, n))
                    base = min(runs[1])
                    emit(phase=label, rate=rate, target_ms=target, iterations=n, min_rate1=round(base, 1),
                         median_rate1=round(statistics.median(runs[1]), 1),
                         median_throttled=round(statistics.median(runs[rate]), 1),
                         ratio=round(statistics.median(runs[rate]) / base, 2))
                for r, pg in ((1, plain), (rate, tab)):
                    d = pg.evaluate(DUTY, 300)
                    emit(phase=label, duty_rate=r, **{k: round(v, 2) for k, v in d.items()},
                         duty=round(d["ran"] / d["wall"], 3))
                tab.context.close()
            # the test's own loop (FIXED_LOOP, 2e7 iterations) at rate 4
            tab = open_page(4)
            runs = {1: [], 4: []}
            for _ in range(7):
                runs[1].append(plain.evaluate(LOOP, 20_000_000))
                runs[4].append(tab.evaluate(LOOP, 20_000_000))
            emit(phase=label, fixed_loop_2e7={r: [round(x, 1) for x in v] for r, v in runs.items()},
                 ratio=round(statistics.median(runs[4]) / min(runs[1]), 2))
            tab.context.close()

        round_("idle")
        anim = browser.new_context().new_page()
        anim.set_content(ANIM)
        time.sleep(0.5)
        emit(timer_ms_with_animation=timer_resolution_ms())
        round_("animating page open")
        anim.close()
        browser.close()


if __name__ == "__main__":
    main()
