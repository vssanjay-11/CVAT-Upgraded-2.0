@echo off
setlocal enabledelayedexpansion

echo =================================================================
echo         CVAT Desktop Application - Build & Package Wizard
echo =================================================================
echo.

cd /d "%~dp0"

:: Step 1: Check Python
echo [*] Checking Python installation...
python --version >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [!] Error: Python is not found in PATH. Please install Python 3.10+.
    pause
    exit /b 1
)

:: Step 2: Check PyInstaller
echo [*] Checking PyInstaller...
python -m pip show pyinstaller >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [*] Installing PyInstaller...
    python -m pip install pyinstaller
)

:: Step 3: Build cvat-ui static bundle with Webpack if needed
echo [*] Building cvat-ui production assets...
if not exist "cvat-ui\dist\index.html" (
    echo [*] cvat-ui dist not found. Running webpack build...
    call corepack yarn workspace cvat-ui run build
    if !ERRORLEVEL! NEQ 0 (
        echo [!] Warning: yarn build failed or webpack exited with error. Checking dist folder...
    )
) else (
    echo [*] cvat-ui dist exists. Rebuilding latest assets...
    call corepack yarn workspace cvat-ui run build
)

:: Step 4: Run PyInstaller with buildappv1_cvat.spec
echo.
echo [*] Compiling executable with PyInstaller using buildappv1_cvat.spec...
python -m PyInstaller buildappv1_cvat.spec --noconfirm --clean

if %ERRORLEVEL% NEQ 0 (
    echo [!] Error: PyInstaller build failed.
    pause
    exit /b 1
)

:: Step 5: Verify executable output
if exist "dist\CVAT_App.exe" (
    echo.
    echo =================================================================
    echo [SUCCESS] CVAT Standalone Executable created successfully!
    echo Location: %cd%\dist\CVAT_App.exe
    echo =================================================================
    echo [*] Creating portable distribution zip archive with application code and executable...
    python -c "import zipfile, os, pathlib; root=pathlib.Path('.'); zf=zipfile.ZipFile('dist/CVAT_App_Portable.zip', 'w', zipfile.ZIP_DEFLATED); zf.write('dist/CVAT_App.exe', arcname='CVAT_App.exe'); zf.write('cvat_app_launcher.py', arcname='cvat_app_launcher.py'); zf.write('buildappv1_cvat.spec', arcname='buildappv1_cvat.spec'); [zf.write(os.path.join(r, f), arcname=os.path.relpath(os.path.join(r, f), '.')) for r, _, files in os.walk('cvat-ui/dist') for f in files] if os.path.exists('cvat-ui/dist') else None; zf.close(); print('[*] Zip archive successfully generated at dist/CVAT_App_Portable.zip')"
    if exist "dist\CVAT_App_Portable.zip" (
        echo [*] Portable Archive: %cd%\dist\CVAT_App_Portable.zip
    )
) else (
    echo [!] Error: Expected executable not found at dist\CVAT_App.exe.
)

echo.
echo Press any key to exit...
pause >nul
