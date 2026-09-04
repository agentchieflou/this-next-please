#!/usr/bin/env bash
# Git Bash / bash smoke test: every command a user types, from the shell they type it in.
#
# The bash floor is 4.4 (the laptop's MINGW64), so nothing here may use a later feature:
# no ${var@Q}, no EPOCHSECONDS, no `wait -n`, no `${var,,}` beyond what 4.4 has.
# shellcheck --shell=bash runs over this file in CI.
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
fails=0

note() { printf '\n=== %s\n' "$1"; }
ok() { printf '  ok: %s\n' "$1"; }
fail() { printf '  FAIL: %s\n' "$1"; fails=$((fails + 1)); }

note "ad-update --check exits 0"
if ad-update --check >/dev/null 2>&1; then ok "ad-update --check"; else fail "ad-update --check did not exit 0"; fi

note "ad-doctor: exit code, TOON stdout, a hint on every fail row"
doctor_out="$(ad-doctor --quiet 2>/dev/null)"
doctor_rc=$?
if printf '%s' "$doctor_out" | python "$HERE/check_doctor.py" --exit-code "$doctor_rc" --shell bash; then
    ok "doctor contract"
else
    fail "doctor contract"
fi

note "the module form works"
python -m agentdata --help >/dev/null || fail "python -m agentdata --help"
python -m agentdata update --check >/dev/null || fail "python -m agentdata update --check"
ad-help >/dev/null 2>&1 || fail "ad-help"

note "every ad-* console script answers --version"
# read from the installed distribution, never a hard-coded list: a command that forgets its
# [project.scripts] entry has to show up as a missing row somewhere
cmds="$(python -c "
import importlib.metadata as md
print(' '.join(sorted(ep.name for ep in md.distribution('agentdata').entry_points
                      if ep.group == 'console_scripts' and ep.name.startswith('ad-'))))
")"
# shellcheck disable=SC2086  # deliberate word splitting: $cmds is a space-separated list of names
for cmd in $cmds; do
    "$cmd" --version >/dev/null 2>&1 || fail "$cmd --version"
done
ok "checked: $cmds"

note "the bash completion script is valid bash"
if ad-setup --print-completion bash | bash -n; then ok "completion parses"; else fail "completion does not parse"; fi

note "piped stdout carries no ANSI and equals AGENTDATA_COLOR=never"
piped="$(ad-doctor --quiet 2>/dev/null)"
forced="$(AGENTDATA_COLOR=never ad-doctor --quiet 2>/dev/null)"
case "$piped" in
    *$'\033'*) fail "ANSI escapes in piped stdout" ;;
    *) ok "no ANSI when piped" ;;
esac
if [ "$piped" = "$forced" ]; then ok "piped == AGENTDATA_COLOR=never"; else fail "piped differs from AGENTDATA_COLOR=never"; fi

note "Git Bash writes UTF-8 without a BOM"
ad-doctor --quiet > doctor-bash.toon 2>/dev/null
if python -c "
import sys
raw = open('doctor-bash.toon','rb').read()
sys.exit(1 if raw.startswith(b'\xef\xbb\xbf') else 0)
"; then ok "no BOM"; else fail "BOM in redirected output"; fi
python -m agentdata.toon --validate doctor-bash.toon || fail "redirected output is not TOON"
rm -f doctor-bash.toon

printf '\n'
if [ "$fails" -ne 0 ]; then
    printf 'smoke.sh: %s check(s) failed\n' "$fails"
    exit 1
fi
printf 'smoke.sh: all checks passed\n'
