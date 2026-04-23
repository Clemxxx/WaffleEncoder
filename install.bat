@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>&1
if %ERRORLEVEL%==0 (
    set PY=py -3
) else (
    where python >nul 2>&1
    if %ERRORLEVEL%==0 (
        set PY=python
    ) else (
        echo Python is not installed or not on PATH.
        echo Install Python 3.10+ from https://www.python.org/downloads/ and retick "Add python.exe to PATH".
        pause
        exit /b 1
    )
)

echo WaffleEncoder has no runtime dependencies beyond Python's tkinter.
echo Nothing to install.
echo.
echo Run the app with:   run.bat
echo Build the exe with: build.bat
pause
exit /b 0
