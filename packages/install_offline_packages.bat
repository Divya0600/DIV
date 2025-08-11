@echo off
echo Installing required packages from offline bundle...
echo.

REM Save the parent directory (where the main files are)
set "PARENT_DIR=%~dp0.."

REM Change to the directory containing this script (offline_packages)
cd /d "%~dp0"

REM Install required packages from offline directory
echo Installing packages...
echo Current directory: %CD%
echo Available wheel files:
dir *.whl

REM Install only the essential packages we need, with force reinstall
echo Installing Redis client (for job management)...
pip install --no-index --find-links . --upgrade redis
if %errorlevel% neq 0 (
    echo ERROR: redis package not found in offline packages!
    echo Please download redis wheel file to packages directory
)

echo Installing requests (for HTTP communication)...
pip install --no-index --find-links . --upgrade requests

echo Installing psutil (for system monitoring)...  
pip install --no-index --find-links . --upgrade psutil

echo Installing pywin32 (essential for Windows services)...
REM pywin32 needs special handling - install the wheel file directly
for %%f in (pywin32*.whl) do (
    echo Installing %%f directly...
    pip install --force-reinstall "%%f"
    if %errorlevel% equ 0 (
        echo pywin32 installed successfully
        goto :pywin32_success
    )
)
echo ERROR: No pywin32 wheel file found or installation failed!
echo Please ensure pywin32*.whl file is in the packages directory
:pywin32_success

echo Installing aiofiles (for async file operations)...
pip install --no-index --find-links . --upgrade aiofiles
if %errorlevel% neq 0 (
    echo ERROR: aiofiles package not found in offline packages!
    echo Please download aiofiles wheel file to packages directory
)

echo Checking if packages were installed correctly...
python -c "import redis; print('redis: OK')" 2>nul || echo "redis: ERROR - Missing package!"
python -c "import requests; print('requests: OK')" 2>nul || echo "requests: WARNING"
python -c "import psutil; print('psutil: OK')" 2>nul || echo "psutil: WARNING"  
python -c "import win32serviceutil; print('pywin32: OK')" 2>nul || echo "pywin32: WARNING - May need manual installation"
python -c "import aiofiles; print('aiofiles: OK')" 2>nul || echo "aiofiles: ERROR - Missing package!"

REM ============================================================
REM Copy offline web UI assets (React/ReactDOM/Babel/Tailwind)
REM ============================================================
echo.
echo Installing offline web UI assets (React, ReactDOM, Babel, Tailwind CSS)...

REM Determine project root (one level up from packages dir)
set "PROJECT_ROOT=%~dp0.."
set "WEB_VENDOR_DIR=%PROJECT_ROOT%\web\vendor"
set "ASSETS_SRC=%~dp0web_assets"

if not exist "%ASSETS_SRC%" (
  echo Assets source folder not found: %ASSETS_SRC%
  echo Create this folder and place the required files:
  echo   - react.production.min.js
  echo   - react-dom.production.min.js
  echo   - babel.min.js
  echo   - tailwind.min.css
  goto :assets_done
)

if not exist "%WEB_VENDOR_DIR%" (
  mkdir "%WEB_VENDOR_DIR%" >nul 2>&1
)

set COPY_COUNT=0
for %%F in (react.production.min.js react-dom.production.min.js babel.min.js tailwind.min.css) do (
  if exist "%ASSETS_SRC%\%%F" (
    copy /Y "%ASSETS_SRC%\%%F" "%WEB_VENDOR_DIR%\%%F" >nul
    if %errorlevel%==0 (
      set /a COPY_COUNT+=1
      echo Copied: %%F
    ) else (
      echo Failed to copy: %%F
    )
  ) else (
    echo Missing asset: %%F (place it in %ASSETS_SRC%)
  )
)

if %COPY_COUNT% GTR 0 (
  echo Offline web assets installed to: %WEB_VENDOR_DIR%
) else (
  echo No web assets were copied. See packages\web_assets\PLACE_FILES_HERE.txt for instructions.
)

:assets_done

echo.
echo ===============================================
echo INSTALLATION SUMMARY:
echo ===============================================
python -c "import redis; print('[OK] redis: Available')" 2>nul || echo "[ERROR] redis: NOT AVAILABLE"
python -c "import requests; print('[OK] requests: Available')" 2>nul || echo "[ERROR] requests: NOT AVAILABLE"
python -c "import psutil; print('[OK] psutil: Available')" 2>nul || echo "[ERROR] psutil: NOT AVAILABLE"
python -c "import win32serviceutil; print('[OK] pywin32: Available')" 2>nul || echo "[ERROR] pywin32: NOT AVAILABLE"
python -c "import aiofiles; print('[OK] aiofiles: Available')" 2>nul || echo "[ERROR] aiofiles: NOT AVAILABLE"
echo ===============================================

echo.
echo If all packages show [OK], your render farm application is ready to run offline!
echo If any show [ERROR], please check the wheel files in this directory.
echo.
