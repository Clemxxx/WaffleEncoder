@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>&1
if %ERRORLEVEL%==0 (
    set PY=py -3
) else (
    set PY=python
)

%PY% -m pip install --user --upgrade pyinstaller tkinterdnd2
if errorlevel 1 goto :err

if exist build rmdir /s /q build
if exist dist  rmdir /s /q dist
if exist WaffleEncoder.spec del /q WaffleEncoder.spec

set BUNDLE_FFMPEG=
if exist "%~dp0ffmpeg.exe" (
    echo Bundling ffmpeg.exe from project folder into the build.
    set BUNDLE_FFMPEG=--add-binary "%~dp0ffmpeg.exe;."
) else (
    echo No ffmpeg.exe in project folder - the exe will rely on FFMPEG_BIN / PATH at runtime.
    echo To bundle, copy your ffmpeg.exe into this folder and rerun build.bat.
)

%PY% -m PyInstaller ^
  --noconfirm ^
  --onefile ^
  --windowed ^
  --name WaffleEncoder ^
  --collect-all tkinterdnd2 ^
  %BUNDLE_FFMPEG% ^
  main.py
if errorlevel 1 goto :err

echo.
echo Build complete. The exe is in: dist\WaffleEncoder.exe
pause
exit /b 0

:err
echo.
echo Build failed. See errors above.
pause
exit /b 1
