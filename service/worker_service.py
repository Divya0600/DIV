#!/usr/bin/env python3
"""
Render Farm Worker Windows Service
Runs worker_node.py as a Windows service with auto-restart capability
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
import json
import socket
from pathlib import Path
import requests

class RenderFarmWorkerService(win32serviceutil.ServiceFramework):
    _svc_name_ = "RenderFarmWorker"
    _svc_display_name_ = "Render Farm Worker"
    _svc_description_ = "Distributed rendering worker that processes render jobs from the server"
    _svc_start_type_ = win32service.SERVICE_AUTO_START

    def __init__(self, args):
        win32serviceutil.ServiceFramework.__init__(self, args)
        self.hWaitStop = win32event.CreateEvent(None, 0, 0, None)
        self.running = True
        self.worker_process = None
        
        # Setup logging
        self.setup_logging()
        
        # Get service directory and configuration
        self.service_dir = Path("C:/ProgramData/Microsoft/RFS")  # Fixed path
        self.worker_script = self.service_dir / "worker.py"
        
        # Use consolidated worker config file
        possible_config_paths = [
            self.service_dir / "worker_config.json",
            Path("C:/Render/worker_config.json"),
            Path.cwd() / "worker_config.json"
        ]
        
        self.config_file = None
        for config_path in possible_config_paths:
            if config_path.exists():
                self.config_file = config_path
                break
        
        # If no config found, use the first path as default
        if self.config_file is None:
            self.config_file = possible_config_paths[0]
        
        # Load configuration
        self.load_config()
        
    def setup_logging(self):
        """Setup logging for the service"""
        log_dir = Path("C:/Render/logs")
        log_dir.mkdir(parents=True, exist_ok=True)
        
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_dir / "worker_service.log"),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger("RenderFarmWorkerService")

    def load_config(self):
        """Load worker service configuration - CONFIG FILE REQUIRED"""        
        self.logger.info(f"Loading config from: {self.config_file}")
        
        if not self.config_file.exists():
            self.logger.error(f"REQUIRED config file not found: {self.config_file}")
            self.logger.error("Worker service cannot start without proper configuration")
            raise FileNotFoundError(f"Required config file missing: {self.config_file}")
        
        try:
            with open(self.config_file, 'r') as f:
                loaded_config = json.load(f)
                
            # Handle nested server URL configuration
            server_config = loaded_config.get('server', {})
            if server_config and 'url' in server_config:
                loaded_config['server_url'] = server_config['url']
            
            # Validate required fields
            if 'server_url' not in loaded_config:
                if 'server' not in loaded_config or 'url' not in loaded_config['server']:
                    raise ValueError("Missing required 'server.url' in config file")
            
            self.config = loaded_config
            self.logger.info(f"+ Config loaded successfully")
            self.logger.info(f"+ Server URL: {self.config.get('server_url')}")
            self.logger.info(f"+ Worker ID: {self.config.get('worker', {}).get('id', 'auto_hostname')}")
                
        except json.JSONDecodeError as e:
            self.logger.error(f"Invalid JSON in config file: {e}")
            raise
        except Exception as e:
            self.logger.error(f"Error loading config: {e}")
            raise
    

    def SvcStop(self):
        """Stop the service"""
        self.logger.info("Stopping Render Farm Worker Service...")
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        
        # Stop the worker process
        if self.worker_process:
            try:
                self.worker_process.terminate()
                self.worker_process.wait(timeout=10)
                self.logger.info("Worker process terminated gracefully")
            except subprocess.TimeoutExpired:
                self.worker_process.kill()
                self.logger.warning("Worker process was killed forcefully")
            except Exception as e:
                self.logger.error(f"Error stopping worker process: {e}")
        
        self.running = False
        win32event.SetEvent(self.hWaitStop)

    def SvcDoRun(self):
        """Main service loop"""
        self.logger.info("Starting Render Farm Worker Service...")
        servicemanager.LogMsg(
            servicemanager.EVENTLOG_INFORMATION_TYPE,
            servicemanager.PYS_SERVICE_STARTED,
            (self._svc_name_, '')
        )
        
        restart_count = 0
        max_restarts = self.config.get("service_settings", {}).get("max_restart_attempts", 5)
        
        # Main service loop with auto-restart
        while self.running:
            try:
                self.start_worker()
                restart_count = 0  # Reset counter on successful start
                
                # Monitor the worker process
                while self.running and self.worker_process and self.worker_process.poll() is None:
                    # Check if we should stop
                    if win32event.WaitForSingleObject(self.hWaitStop, 5000) == win32event.WAIT_OBJECT_0:
                        self.running = False
                        break
                
                # If we reach here and still running, the worker crashed
                if self.running:
                    restart_count += 1
                    if restart_count <= max_restarts:
                        delay = self.config.get("service_settings", {}).get("auto_restart_delay", 10)
                        self.logger.error(f"Worker process crashed (attempt {restart_count}/{max_restarts}), restarting in {delay} seconds...")
                        time.sleep(delay)
                    else:
                        self.logger.error(f"Maximum restart attempts ({max_restarts}) reached. Stopping service.")
                        self.running = False
                    
            except Exception as e:
                self.logger.error(f"Error in service loop: {e}")
                if self.running:
                    self.logger.info("Restarting in 30 seconds...")
                    time.sleep(30)

    def ensure_dependencies(self):
        """Verify required Python packages are available (offline mode)"""
        try:
            # For offline installations, dependencies should already be bundled
            # Just verify they can be imported instead of installing
            required_modules = ['requests', 'psutil', 'aiofiles']
            missing_modules = []
            
            for module in required_modules:
                try:
                    __import__(module)
                    self.logger.debug(f"+ {module} available")
                except ImportError:
                    missing_modules.append(module)
                    self.logger.warning(f"✗ {module} not available")
            
            if missing_modules:
                self.logger.warning(f"Missing modules: {missing_modules}")
                self.logger.info("Running in offline mode - dependencies should be pre-bundled")
            else:
                self.logger.info("All dependencies verified - ready for offline operation")
                
        except Exception as e:
            self.logger.error(f"Dependency verification failed: {e}")
            # Don't raise - continue anyway for offline operations

    def start_worker(self):
        """Start the worker process"""
        try:
            # Ensure dependencies are installed
            self.ensure_dependencies()
            
            server_url = self.config["server_url"]  # Required field, no fallback
            worker_id = self.config.get("worker", {}).get("id", "auto_hostname")
            
            # Handle auto_hostname special case
            if worker_id == "auto_hostname":
                import socket
                worker_id = f"worker_{socket.gethostname()}"
                self.logger.info(f"Resolved auto_hostname to: {worker_id}")
            
            self.logger.info(f"Starting worker: {self.worker_script}")
            self.logger.info(f"Server URL: {server_url}")
            self.logger.info(f"Worker ID: {worker_id}")
            
            # Start worker_node.py as subprocess with environment for Unicode support
            env = os.environ.copy()
            env['PYTHONIOENCODING'] = 'utf-8'
            env['PYTHONUNBUFFERED'] = '1'
            
            # ============= FOUNDRY LICENSE FIX =============
            # Add Foundry/Nuke license environment variables for service context
            # These paths are common Foundry license locations
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
            
            # Allow Nuke to run without GUI in service context
            env['NUKE_USE_FNPOPEN'] = '1'
            env['FOUNDRY_ASSET_PLUGIN_PATH'] = ''
            
            self.logger.info("Foundry license environment configured")
            # ============= END LICENSE FIX =============
            
            # Use python.exe directly to avoid service manager conflicts
            python_exe = sys.executable
            if 'pythonservice.exe' in python_exe.lower():
                # If we're in a service context, find the regular python.exe
                python_dir = os.path.dirname(python_exe)
                python_exe = os.path.join(python_dir, 'python.exe')
            
            # Current worker.py only accepts --config parameter
            cmd = [
                python_exe, 
                str(self.worker_script),
                "--config", str(self.config_file)
            ]
            
            self.worker_process = subprocess.Popen(
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
            
            self.logger.info(f"Worker started with PID: {self.worker_process.pid}")
            
            # Log worker output to help with debugging
            import threading
            def log_output():
                try:
                    for line in self.worker_process.stdout:
                        if line and line.strip():
                            try:
                                # Handle any remaining encoding issues gracefully
                                clean_line = line.strip()
                                self.logger.info(f"Worker: {clean_line}")
                            except UnicodeDecodeError as decode_error:
                                # Log the error but continue reading
                                self.logger.warning(f"Unicode decode error in worker output: {decode_error}")
                                continue
                except Exception as e:
                    self.logger.error(f"Error reading worker output: {e}")
            
            output_thread = threading.Thread(target=log_output, daemon=True)
            output_thread.start()
            
        except Exception as e:
            self.logger.error(f"Failed to start worker: {e}")
            raise

def run_worker_directly():
    """Run the worker process directly without service wrapper"""
    service = RenderFarmWorkerService([])
    try:
        service.setup_logging()
        service.load_config()
        service.running = True
        service.logger.info("Starting worker in console mode...")
        service.start_worker()
        
        while service.running and service.worker_process and service.worker_process.poll() is None:
            time.sleep(1)
            
    except KeyboardInterrupt:
        service.logger.info("Received keyboard interrupt, stopping...")
        if service.worker_process:
            service.worker_process.terminate()
            try:
                service.worker_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                service.worker_process.kill()
    except Exception as e:
        service.logger.error(f"Error running worker: {e}")
    finally:
        service.running = False
        if service.worker_process and service.worker_process.poll() is None:
            service.worker_process.terminate()

if __name__ == '__main__':
    if len(sys.argv) == 1:
        # No arguments - run in console mode for debugging
        run_worker_directly()
    elif sys.argv[1] in ['install', 'remove', 'update', 'start', 'stop', 'restart']:
        # Service management commands
        win32serviceutil.HandleCommandLine(RenderFarmWorkerService)
    else:
        print("Usage:")
        print("  worker_service.py              - Run in console mode")
        print("  worker_service.py install      - Install the service")
        print("  worker_service.py remove       - Remove the service")
        print("  worker_service.py start        - Start the service")
        print("  worker_service.py stop         - Stop the service")
        print("  worker_service.py restart      - Restart the service")