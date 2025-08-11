#!/usr/bin/env python3
"""
Render Farm Server Windows Service
Runs server.py as a Windows service with auto-restart capability
"""

import sys
import os
import time
import logging
import subprocess
import win32serviceutil
import win32service
import win32event
import servicemanager
from pathlib import Path

class RenderFarmServerService(win32serviceutil.ServiceFramework):
    _svc_name_ = "RenderFarmServer"
    _svc_display_name_ = "Render Farm Server"
    _svc_description_ = "Distributed rendering server that manages job queues and worker coordination"
    _svc_start_type_ = win32service.SERVICE_AUTO_START

    def __init__(self, args):
        win32serviceutil.ServiceFramework.__init__(self, args)
        self.hWaitStop = win32event.CreateEvent(None, 0, 0, None)
        self.running = True
        self.server_process = None
        
        # Setup logging
        self.setup_logging()
        
        # Get service directory
        self.service_dir = Path(__file__).parent.parent  # Go up one level to farm directory
        self.server_script = self.service_dir / "server.py"
        self.config_file = self.service_dir / "server_config.json"
        
    def setup_logging(self):
        """Setup logging for the service"""
        log_dir = Path("C:/RenderFarm/logs")
        log_dir.mkdir(parents=True, exist_ok=True)
        
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_dir / "server_service.log"),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger("RenderFarmServerService")

    def SvcStop(self):
        """Stop the service"""
        self.logger.info("Stopping Render Farm Server Service...")
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        
        # Stop the server process
        if self.server_process:
            try:
                self.server_process.terminate()
                self.server_process.wait(timeout=10)
                self.logger.info("Server process terminated gracefully")
            except subprocess.TimeoutExpired:
                self.server_process.kill()
                self.logger.warning("Server process was killed forcefully")
            except Exception as e:
                self.logger.error(f"Error stopping server process: {e}")
        
        self.running = False
        win32event.SetEvent(self.hWaitStop)

    def SvcDoRun(self):
        """Main service loop"""
        self.logger.info("Starting Render Farm Server Service...")
        servicemanager.LogMsg(
            servicemanager.EVENTLOG_INFORMATION_TYPE,
            servicemanager.PYS_SERVICE_STARTED,
            (self._svc_name_, '')
        )
        
        # Main service loop with auto-restart
        while self.running:
            try:
                self.start_server()
                
                # Monitor the server process
                while self.running and self.server_process and self.server_process.poll() is None:
                    # Check if we should stop
                    if win32event.WaitForSingleObject(self.hWaitStop, 5000) == win32event.WAIT_OBJECT_0:
                        self.running = False
                        break
                
                # If we reach here and still running, the server crashed
                if self.running:
                    self.logger.error("Server process crashed, restarting in 10 seconds...")
                    time.sleep(10)
                    
            except Exception as e:
                self.logger.error(f"Error in service loop: {e}")
                if self.running:
                    self.logger.info("Restarting in 30 seconds...")
                    time.sleep(30)

    def start_server(self):
        """Start the server process"""
        try:
            self.logger.info(f"Starting server: {self.server_script}")
            
            # Start server.py as subprocess with environment variables for Unicode support
            env = os.environ.copy()
            env['PYTHONIOENCODING'] = 'utf-8'
            env['PYTHONUNBUFFERED'] = '1'
            
            # ============= FOUNDRY LICENSE FIX =============
            # Add Foundry/Nuke license environment variables for service context
            foundry_license_paths = [
                "C:\\ProgramData\\The Foundry\\RLM",
                "C:\\Program Files\\The Foundry\\RLM",
                "C:\\Users\\Public\\Documents\\TheFoundry\\RLM",
                f"C:\\Users\\{os.environ.get('USERNAME', 'Public')}\\Documents\\TheFoundry\\RLM"
            ]
            
            # Set RLM_LICENSE environment variable
            existing_rlm = env.get('RLM_LICENSE', '')
            if not existing_rlm:
                for path in foundry_license_paths:
                    if os.path.exists(path):
                        env['RLM_LICENSE'] = path
                        self.logger.info(f"Set RLM_LICENSE to: {path}")
                        break
            
            # Set additional Foundry environment variables
            env['FOUNDRY_LICENSE_FILE'] = env.get('FOUNDRY_LICENSE_FILE', env.get('RLM_LICENSE', ''))
            env['RLM_PATH'] = env.get('RLM_PATH', env.get('RLM_LICENSE', ''))
            env['NUKE_USE_FNPOPEN'] = '1'
            
            self.logger.info("Foundry license environment configured")
            # ============= END LICENSE FIX =============
            
            # Use python.exe directly to avoid service manager conflicts
            python_exe = sys.executable
            if 'pythonservice.exe' in python_exe.lower():
                # If we're in a service context, find the regular python.exe
                python_dir = os.path.dirname(python_exe)
                python_exe = os.path.join(python_dir, 'python.exe')
            
            # Add config file parameter
            cmd = [python_exe, str(self.server_script), "--config", str(self.config_file)]
            
            self.server_process = subprocess.Popen(
                cmd,
                cwd=str(self.service_dir),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding='utf-8',
                errors='replace',
                bufsize=1,
                universal_newlines=True,
                env=env,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            
            self.logger.info(f"Server started with PID: {self.server_process.pid}")
            
            # Log first few lines of server output to verify it's working
            import threading
            def log_output():
                try:
                    for line in self.server_process.stdout:
                        if line and line.strip():
                            try:
                                # Handle any remaining encoding issues gracefully
                                clean_line = line.strip()
                                self.logger.info(f"Server: {clean_line}")
                            except UnicodeDecodeError as decode_error:
                                # Log the error but continue reading
                                self.logger.warning(f"Unicode decode error in server output: {decode_error}")
                                continue
                except Exception as e:
                    self.logger.error(f"Error reading server output: {e}")
            
            output_thread = threading.Thread(target=log_output, daemon=True)
            output_thread.start()
            
        except Exception as e:
            self.logger.error(f"Failed to start server: {e}")
            raise

if __name__ == '__main__':
    if len(sys.argv) == 1:
        servicemanager.Initialize()
        servicemanager.PrepareToHostSingle(RenderFarmServerService)
        servicemanager.StartServiceCtrlDispatcher()
    else:
        win32serviceutil.HandleCommandLine(RenderFarmServerService)