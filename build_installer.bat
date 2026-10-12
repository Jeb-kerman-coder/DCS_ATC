@echo off
setlocal
cd /d "%~dp0"

echo ============================================================
echo  DCS ATC - build exe + installer   (run on Windows, 64-bit)
echo  Needs: Python 3.10-3.12 on PATH, internet (first run), and
echo         Inno Setup 6  https://jrsoftware.org/isinfo.php
echo ============================================================

if not exist ".build-venv\Scripts\python.exe" (
    echo Creating build environment...
    python -m venv .build-venv || goto :fail
)

call ".build-venv\Scripts\activate.bat"

python -m pip install --upgrade pip || goto :fail
python -m pip install -r requirements.txt pyinstaller huggingface_hub || goto :fail

echo.
echo Fetching voice + speech models (skipped if already present)...
python fetch_models.py || goto :fail

echo.
echo Building the exe (this takes several minutes)...
pyinstaller DCS_ATC.spec --noconfirm --clean || goto :fail

set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%LocalAppData%\Programs\Inno Setup 6\ISCC.exe"

if not exist "%ISCC%" (
    echo.
    echo The exe is built in dist\DCS ATC\ but Inno Setup 6 was not found.
    echo Install it, then run this file again to make the installer.
    goto :end
)

echo.
echo Building the installer...
set "ISCC_ARGS="
if defined APP_VERSION set "ISCC_ARGS=/DAppVersion=%APP_VERSION%"
"%ISCC%" %ISCC_ARGS% installer\DCS_ATC.iss || goto :fail

echo.
echo DONE:  installer_output\DCS_ATC_Setup.exe
echo (the exe itself is in dist\DCS ATC\DCS ATC.exe)
goto :end

:fail
echo.
echo BUILD FAILED - see the messages above.
if not defined CI pause
exit /b 1

:end
if not defined CI pause
endlocal
