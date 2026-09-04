# Captured failure transcripts

Each file is one `(argv, exit code, stdout, stderr)` that a real tool produced, replayed by the
tests so a diagnosis is checked against the text a user actually saw rather than against a guess.

**Provenance matters, so every file records it in `source`:**

- `photographed` — transcribed from the failure photographed in PyCharm's MINGW64 terminal on
  2026-09-03 and quoted verbatim in issue #66. This is what `ad-update` printed; the pip/gh text
  behind it was truncated by the bug being fixed, so the streams here are reconstructed from the
  documented pip behaviour that produces exactly that output.
- `synthesized` — written to pin one diagnosis signature. Real in shape, not captured.
- `captured` — a genuine `2>&1 | tee` from a laptop, with the shell recorded.

The reconstructed ones should be replaced with `captured` transcripts the next time the failure is
reproduced on the laptop (issue #66, first acceptance criterion): run the install line from pwsh and
again from Git Bash, tee both, and drop them in here.
