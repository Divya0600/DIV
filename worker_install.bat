@echo off
REM Worker Installation Script
REM Installs and manages the Render Farm Worker service

echo ========================================
echo RENDER FARM WORKER INSTALLATION
echo ========================================

REM Check if running as administrator
fsutil dirty query %systemdrive% >nul 2>&1
if %errorLevel% == 0 (
    echo [OK] Running as Administrator
) else (
    echo [ERROR] This script must be run as Administrator
    echo Please right-click and select "Run as administrator"
    pause
    exit /b 1
)

REM Check if Python is installed
echo [INFO] Checking Python installation...
python --version >nul 2>&1
if %errorLevel% == 0 (
    python --version
    echo [OK] Python is installed
) else (
    echo [ERROR] Python is not installed or not in PATH
    echo Please install Python and ensure it's added to PATH
    pause
    exit /b 1
)

REM Check if required files exist in C:\Render
echo [INFO] Verifying required files 
if not exist "C:\ProgramData\Microsoft\RFS\service\worker_service.py" (
    echo [ERROR] Required files not found 
    echo Please ensure all files are properly extracted
    pause
    exit /b 1
)

echo [OK] Required files found 

REM Create logs directory if it doesn't exist
if not exist "C:\Render\logs" (
    mkdir "C:\Render\logs"
    echo [INFO] Created logs directory
)

REM Change to the installation directory
cd /d "C:\ProgramData\Microsoft\RFS"

REM Stop existing service if running
echo [INFO] Stopping existing service if running...
sc stop RenderFarmWorker >nul 2>&1

REM Install the service
echo [INFO] Installing Render Farm Worker service...
python service\worker_service.py install
set INSTALL_ERROR=%errorLevel%

if %INSTALL_ERROR% == 0 (
    echo [OK] Worker service installed successfully
    
    echo [INFO] Starting Render Farm Worker service...
    sc start RenderFarmWorker
    
    if %errorLevel% == 0 (
        echo [OK] Worker service started successfully
    ) else (
        echo [WARNING] Service installed but failed to start
        echo [INFO] Check logs for details
    )
) else (
    echo [ERROR] Failed to install service (Error Code: %INSTALL_ERROR%)
    echo [INFO] This may be normal if the service was already installed
    
    echo [INFO] Attempting to start the service...
    sc start RenderFarmWorker
    
    if %errorLevel% == 0 (
        echo [OK] Worker service started successfully
    ) else (
        echo [ERROR] Failed to start service
        echo [INFO] Check logs for details
    )
)

echo.
echo ========================================
echo INSTALLATION COMPLETE
echo ========================================
echo Service Name:  RenderFarmWorker
echo.

REM Exit with appropriate error code
exit /b %INSTALL_ERROR%