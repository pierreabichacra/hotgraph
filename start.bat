@echo off
setlocal
cd /d "%~dp0"

rem The "py" launcher ships with every python.org install (even when PATH was
rem left alone) and skips the Microsoft Store "python" stub.
where py >nul 2>&1
if %errorlevel%==0 (
    py -3 start.py %*
) else (
    python start.py %*
)

if errorlevel 1 (
    echo.
    echo HotGraph stopped with an error - see the messages above.
    pause
)
endlocal
