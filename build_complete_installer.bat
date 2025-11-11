@echo off
echo ========================================
echo  RENDER FARM - COMPLETE INSTALLER BUILD
echo ========================================
echo.

REM Change to script directory
cd /d "%~dp0"

echo Building complete installer with bundled PySide6 GUI...
python build_installer.py

echo.
echo ========================================
echo  BUILD COMPLETE!
echo ========================================
echo.
echo Your professional installer is ready:
echo   📁 RenderFarmInstaller\RenderFarmSetup.exe
echo.
echo This installer includes:
echo   ✅ Professional PySide6 GUI (bundled by PyInstaller)
echo   ✅ Complete render farm setup
echo   ✅ Windows service installation
echo   ✅ Everything self-contained in one EXE
echo.
echo Ready to distribute! No external dependencies needed!
pause