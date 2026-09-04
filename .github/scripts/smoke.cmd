@echo off
REM cmd.exe smoke test. cmd is not a shell anyone should script this project in, but people type
REM commands into it, so the console scripts and the module form have to work there.
REM
REM No delayed expansion tricks and no `&&` chains that hide an exit code: every check sets ERR and
REM the file exits non-zero at the end, so one failure does not mask the rest.
setlocal
set ERR=0
set HERE=%~dp0

echo.
echo === ad-update --check exits 0
ad-update --check >nul 2>&1
if errorlevel 1 (echo   FAIL: ad-update --check & set ERR=1) else (echo   ok: ad-update --check)

echo.
echo === ad-doctor: exit code, TOON stdout, a hint on every fail row
ad-doctor --quiet > "%TEMP%\doctor.toon" 2>nul
set DOCTOR_RC=%ERRORLEVEL%
type "%TEMP%\doctor.toon" | python "%HERE%check_doctor.py" --exit-code %DOCTOR_RC% --shell cmd
if errorlevel 1 (echo   FAIL: doctor contract & set ERR=1) else (echo   ok: doctor contract)

echo.
echo === the module form works
python -m agentdata --help >nul 2>&1
if errorlevel 1 (echo   FAIL: python -m agentdata --help & set ERR=1)
python -m agentdata update --check >nul 2>&1
if errorlevel 1 (echo   FAIL: python -m agentdata update --check & set ERR=1)
ad-help >nul 2>&1
if errorlevel 1 (echo   FAIL: ad-help & set ERR=1)
echo   ok: module form

echo.
echo === every ad-* console script answers --version
REM the list comes from the installed distribution, never hard-coded here
python -c "import importlib.metadata as md; print(' '.join(sorted(ep.name for ep in md.distribution('agentdata').entry_points if ep.group=='console_scripts' and ep.name.startswith('ad-'))))" > "%TEMP%\cmds.txt"
set /p CMDS=<"%TEMP%\cmds.txt"
for %%c in (%CMDS%) do (
    %%c --version >nul 2>&1
    if errorlevel 1 (echo   FAIL: %%c --version & set ERR=1)
)
echo   ok: %CMDS%

echo.
echo === redirected output is TOON with no ANSI
python -m agentdata.toon --validate "%TEMP%\doctor.toon"
if errorlevel 1 (echo   FAIL: redirected stdout is not TOON & set ERR=1) else (echo   ok: TOON)

del /q "%TEMP%\doctor.toon" "%TEMP%\cmds.txt" 2>nul

echo.
if "%ERR%"=="1" (
    echo smoke.cmd: checks failed
    exit /b 1
)
echo smoke.cmd: all checks passed
exit /b 0
