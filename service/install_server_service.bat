@echo off
echo Installing Render Farm Server Service...
echo.

REM Force elevation if not running as administrator
>nul 2>&1 "%SYSTEMROOT%\system32\cacls.exe" "%SYSTEMROOT%\system32\config\system"
if '%errorlevel%' NEQ '0' (
    echo Requesting administrator privileges...
    goto UACPrompt
) else ( goto gotAdmin )

:UACPrompt
    echo Set UAC = CreateObject^("Shell.Application"^) > "%temp%\getadmin.vbs"
    echo UAC.ShellExecute "%~s0", "", "", "runas", 1 >> "%temp%\getadmin.vbs"
    "%temp%\getadmin.vbs"
    del "%temp%\getadmin.vbs"
    exit /B

:gotAdmin
    pushd "%CD%"
    CD /D "%~dp0"

REM Install required Python packages from offline bundle
echo Installing required packages from offline bundle...
if exist "packages\install_offline_packages.bat" goto install_offline
goto install_online

:install_offline
echo Found offline packages, installing...
call "packages\install_offline_packages.bat"
if %errorLevel% neq 0 (
    echo ERROR: Failed to install required packages from offline bundle
    pause
    exit /b 1
)
REM Make sure we're back in the main directory after package installation
cd /d "%~dp0"
goto packages_done

:install_online
echo Installing pywin32 from internet (fallback)...
pip install pywin32
if %errorLevel% neq 0 (
    echo ERROR: Failed to install pywin32
    pause
    exit /b 1
)
goto packages_done

:packages_done

REM Install the service
echo Installing Render Farm Server Service...
echo Current directory: %CD%
echo Looking for server_service.py...
dir server_service.py
if not exist server_service.py (
    echo ERROR: server_service.py not found in current directory
    echo Available Python files:
    dir *.py
    pause
    exit /b 1
)
python server_service.py install
if %errorLevel% neq 0 (
    echo ERROR: Failed to install service
    pause
    exit /b 1
)

REM Start the service
echo Starting Render Farm Server Service...
python server_service.py start
if %errorLevel% neq 0 (
    echo ERROR: Failed to start service
    pause
    exit /b 1
)

echo.
echo Render Farm Server Service installed and started successfully!
echo.
echo Service Details:
echo - Name: RenderFarmServer
echo - Display Name: Render Farm Server Service
echo - Status: Running
echo - Auto-start: Yes
echo - Logs: C:\RenderFarm\logs\server_service.log
echo.
echo You can manage the service using:
echo - Services.msc (Windows Services Manager)
echo - python server_service.py stop/start/restart
echo.
pause