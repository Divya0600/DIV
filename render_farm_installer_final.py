#!/usr/bin/env python3
"""
Render Farm Installer - Final Version
Professional PySide6 GUI with everything pre-bundled by PyInstaller
No runtime installation needed - everything is included in the executable
"""

import sys
import os
import shutil
import subprocess
import time
import threading
import logging
from pathlib import Path

# Import PySide6 directly - it will be bundled by PyInstaller
try:
    from PySide6.QtWidgets import (
        QApplication, QWizard, QWizardPage, QLabel, QVBoxLayout,
        QRadioButton, QGroupBox, QProgressBar, QHBoxLayout, QPushButton,
        QMessageBox, QTextEdit, QScrollArea
    )
    from PySide6.QtGui import QPixmap, QIcon, QFont, QPalette, QColor
    from PySide6.QtCore import Qt, QTimer, QThread, Signal
    
except ImportError as e:
    print(f"PySide6 import failed: {e}")
    print("This executable was not built correctly with PyInstaller")
    sys.exit(1)

# Setup logging
def setup_logging():
    """Setup logging for debugging"""
    log_file = Path("C:/Temp/install.log")
    log_file.parent.mkdir(exist_ok=True)
    
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler()
        ]
    )
    return logging.getLogger(__name__)

logger = setup_logging()

class InstallationWorker(QThread):
    """Background thread for actual installation work"""
    progress_updated = Signal(int)
    status_updated = Signal(str)
    installation_complete = Signal(bool, str)
    
    def __init__(self, install_type):
        super().__init__()
        self.install_type = install_type
        # Changed install path here:
        self.install_path = "C:\\ProgramData\\Microsoft\\RFS"
    
    def run(self):
        """Run the installation process"""
        try:
            logger.info(f"Starting installation: {self.install_type}")
            
            # Step 1: Create primary installation directory
            self.status_updated.emit("Creating installation directory...")
            logger.info(f"Creating directory: {self.install_path}")
            os.makedirs(self.install_path, exist_ok=True)
            self.progress_updated.emit(20)
            time.sleep(0.5)
            
            # Step 2: Copy files to primary install folder
            self.status_updated.emit("Copying render farm files...")
            logger.info("Copying files to main install folder...")
            self.copy_render_farm_files()
            self.progress_updated.emit(40)
            time.sleep(0.5)
            
            # Step 3: Copy worker_config.json to C:\Render only
            self.status_updated.emit("Copying worker_config.json .")
            self.copy_worker_config_to_render()
            self.progress_updated.emit(50)
            time.sleep(0.5)
            
            # Step 4: Install service (this is where it was hanging)
            self.status_updated.emit(f"Installing {self.install_type} service...")
            logger.info(f"Installing {self.install_type} service...")
            if self.install_type == "server":
                self.install_server_service()
            else:
                self.install_worker_service()
            self.progress_updated.emit(80)
            time.sleep(0.5)
            
            # Step 5: Verify installation
            self.status_updated.emit("Verifying installation...")
            self.verify_installation()
            self.progress_updated.emit(90)
            time.sleep(0.5)
            
            # Step 6: Complete
            self.status_updated.emit("Installation completed successfully!")
            logger.info("Installation completed successfully!")
            self.progress_updated.emit(100)
            time.sleep(1)
            
            self.installation_complete.emit(True, "Installation completed successfully!")
            
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Installation failed: {error_msg}")
            self.installation_complete.emit(False, error_msg)
    
    def copy_render_farm_files(self):
        """Copy all necessary files to installation directory"""
        if getattr(sys, 'frozen', False):
            # Running as PyInstaller executable - files are in temp directory
            base_dir = Path(sys._MEIPASS)
        else:
            # Running as script
            base_dir = Path(__file__).parent
        
        install_dir = Path(self.install_path)
        
        # Files to copy
        files_to_copy = [
            'server.py',
            'worker.py', 
            'redis_job_manager.py',
            'server_config.json',
            'worker_config.json',
            'web_config.json',
            'server_install.bat',
            'worker_install.bat',
            'logo.ico'
        ]
        
        # Copy individual files
        for file_name in files_to_copy:
            src_file = base_dir / file_name
            if src_file.exists():
                shutil.copy2(src_file, install_dir / file_name)
            else:
                logger.warning(f"Warning: {file_name} not found in bundle")
        
        # Copy directories
        dirs_to_copy = ['web', 'service', 'packages', 'renderers']  # Added renderers
        for dir_name in dirs_to_copy:
            src_dir = base_dir / dir_name
            dest_dir = install_dir / dir_name
            if src_dir.exists():
                if dest_dir.exists():
                    shutil.rmtree(dest_dir)
                shutil.copytree(src_dir, dest_dir, dirs_exist_ok=True)
                logger.info(f"Copied {dir_name} directory")
            else:
                logger.warning(f"Warning: Required {dir_name} directory not found in bundle")
                if dir_name == 'renderers':
                    raise Exception("Critical: Renderers directory not found. Installation cannot proceed.")
    
    def copy_worker_config_to_render(self):
        """Copy worker_config.json to C:\Render folder only"""
        secondary_dir = Path("C:/Render")
        secondary_dir.mkdir(exist_ok=True)
        
        src = Path(self.install_path) / 'worker_config.json'
        dest = secondary_dir / 'worker_config.json'
        
        if src.exists():
            shutil.copy2(src, dest)
            logger.info(f"Copied worker_config.json to {secondary_dir}")
        else:
            logger.warning(f"worker_config.json not found at {src}")
    
    def install_server_service(self):
        """Install the server service"""
        install_script = Path(self.install_path) / 'server_install.bat'
        if install_script.exists():
            logger.info(f"Running server installation script: {install_script}")
            result = subprocess.run([str(install_script)], 
                                  cwd=self.install_path,
                                  capture_output=True, 
                                  text=True, 
                                  shell=True,
                                  timeout=60)  # 60 second timeout
            logger.info(f"Server install script output: {result.stdout}")
            if result.stderr:
                logger.warning(f"Server install script stderr: {result.stderr}")
            if result.returncode != 0:
                raise Exception(f"Server installation failed (code {result.returncode}): {result.stderr}")
        else:
            raise Exception(f"Server installation script not found: {install_script}")
    
    def verify_installation(self):
        """Verify all required files are present after installation"""
        install_dir = Path(self.install_path)
        
        # List of required files and directories
        required_files = [
            'server.py',
            'worker.py',
            'redis_job_manager.py',
            'server_config.json',
            'worker_config.json',
            'web_config.json'
        ]
        
        required_dirs = [
            'web',
            'service',
            'packages',
            'renderers'  # Critical: renderers directory must exist
        ]
        
        # Verify files
        missing_files = []
        for file in required_files:
            if not (install_dir / file).exists():
                missing_files.append(file)
                
        # Verify directories
        missing_dirs = []
        for dir_name in required_dirs:
            if not (install_dir / dir_name).exists():
                missing_dirs.append(dir_name)
                
        # Special check for renderers
        if 'renderers' in missing_dirs:
            logger.error("Critical: Renderers directory is missing!")
            raise Exception("Renderers directory not found. Installation is incomplete.")
            
        # Verify renderer modules
        renderer_dir = install_dir / 'renderers'
        required_renderers = ['nuke_renderer.py', 'silhouette_renderer.py']
        missing_renderers = []
        
        if renderer_dir.exists():
            for renderer in required_renderers:
                if not (renderer_dir / renderer).exists():
                    missing_renderers.append(renderer)
        
        # Log verification results
        if missing_files or missing_dirs or missing_renderers:
            error_msg = "Installation verification failed!\n"
            if missing_files:
                error_msg += f"\nMissing files: {', '.join(missing_files)}"
            if missing_dirs:
                error_msg += f"\nMissing directories: {', '.join(missing_dirs)}"
            if missing_renderers:
                error_msg += f"\nMissing renderer modules: {', '.join(missing_renderers)}"
            logger.error(error_msg)
            raise Exception(error_msg)
        else:
            logger.info("Installation verification completed successfully")
    
    def install_worker_service(self):
        """Install the worker service"""
        install_script = Path(self.install_path) / 'worker_install.bat'
        if install_script.exists():
            logger.info(f"Running worker installation script: {install_script}")
            result = subprocess.run([str(install_script)], 
                                  cwd=self.install_path,
                                  capture_output=True, 
                                  text=True, 
                                  shell=True,
                                  timeout=60)  # 60 second timeout
            logger.info(f"Worker install script output: {result.stdout}")
            if result.stderr:
                logger.warning(f"Worker install script stderr: {result.stderr}")
            if result.returncode != 0:
                raise Exception(f"Worker installation failed (code {result.returncode}): {result.stderr}")
        else:
            raise Exception(f"Worker installation script not found: {install_script}")

class InstallWizard(QWizard):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Render Farm Setup v2.0")
        self.setWizardStyle(QWizard.ModernStyle)
        
        # Try to set icon
        if getattr(sys, 'frozen', False):
            icon_path = Path(sys._MEIPASS) / 'logo.ico'
        else:
            icon_path = Path(__file__).parent / 'logo.ico'
        
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))
        
        self.resize(600, 450)
        
        # Dark mode professional stylesheet
        self.setStyleSheet("""
            QWizard {
                background-color: #2b2b2b;
                color: #ffffff;
                font-family: 'Segoe UI', Arial, sans-serif;
            }
            QWizardPage {
                background-color: #2b2b2b;
                color: #ffffff;
            }
            QLabel {
                color: #ffffff;
                font-size: 12px;
            }
            QGroupBox {
                font-size: 12px;
                font-weight: bold;
                border: 2px solid #555555;
                border-radius: 5px;
                margin-top: 10px;
                padding-top: 10px;
                color: #ffffff;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
                color: #ffffff;
            }
            QRadioButton {
                font-size: 11px;
                spacing: 5px;
                color: #ffffff;
            }
            QRadioButton::indicator {
                width: 13px;
                height: 13px;
                border: 2px solid #555555;
                border-radius: 6px;
                background-color: #333333;
            }
            QRadioButton::indicator:checked {
                background-color: #0078d4;
                border: 2px solid #0078d4;
            }
            QProgressBar {
                border: 1px solid #555555;
                border-radius: 5px;
                text-align: center;
                font-size: 11px;
                background-color: #333333;
                color: #ffffff;
            }
            QProgressBar::chunk {
                background-color: #0078d4;
                border-radius: 4px;
            }
            QPushButton {
                background-color: #0078d4;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-size: 11px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #106ebe;
            }
            QPushButton:pressed {
                background-color: #005a9e;
            }
            QPushButton:disabled {
                background-color: #555555;
                color: #999999;
            }
        """)

        self.addPage(self.create_welcome_page())
        self.addPage(self.create_install_type_page())
        self.addPage(self.create_progress_page())
        self.addPage(self.create_finish_page())

    def create_welcome_page(self):
        page = QWizardPage()
        page.setTitle("Welcome to Render Farm Setup")
        page.setSubTitle("This wizard will guide you through the installation of Professional VFX Render Farm.")
        
        layout = QVBoxLayout()
        
        # Welcome message
        welcome_text = QLabel("""
Welcome to the Render Farm Setup Wizard.

This installer will set up either a Render Farm Server or Worker on your machine.

• Server: Install on your main control machine for job management
• Worker: Install on dedicated render machines for processing jobs

Click Next to continue.
        """)
        welcome_text.setWordWrap(True)
        welcome_text.setFont(QFont('Segoe UI', 10))
        
        layout.addWidget(welcome_text)
        page.setLayout(layout)
        return page

    def create_install_type_page(self):
        page = QWizardPage()
        page.setTitle("Choose Installation Type")
        page.setSubTitle("Select which component you want to install.")

        self.server_btn = QRadioButton("Render Farm Server")
        self.worker_btn = QRadioButton("Render Farm Worker")
        self.server_btn.setChecked(True)

        # Add descriptions
        server_desc = QLabel("• Manages render jobs and coordinates workers\n• Includes web interface for job management\n• Install on main control machine")
        server_desc.setFont(QFont('Segoe UI', 9))
        server_desc.setStyleSheet("color: #666666; margin-left: 20px;")
        
        worker_desc = QLabel("• Processes render jobs from server\n• High-performance rendering node\n• Install on dedicated render machines")
        worker_desc.setFont(QFont('Segoe UI', 9))
        worker_desc.setStyleSheet("color: #666666; margin-left: 20px;")

        group = QGroupBox("Select installation type:")
        vbox = QVBoxLayout()
        vbox.addWidget(self.server_btn)
        vbox.addWidget(server_desc)
        vbox.addSpacing(15)
        vbox.addWidget(self.worker_btn)
        vbox.addWidget(worker_desc)
        group.setLayout(vbox)

        layout = QVBoxLayout()
        layout.addWidget(group)
        layout.addStretch()
        page.setLayout(layout)
        return page

    def create_progress_page(self):
        page = QWizardPage()
        page.setTitle("Installing")
        page.setSubTitle("Please wait while the installation completes...")

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        
        self.status_label = QLabel("Preparing installation...")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setFont(QFont('Segoe UI', 10))

        layout = QVBoxLayout()
        layout.addStretch()
        layout.addWidget(self.status_label)
        layout.addWidget(self.progress)
        layout.addStretch()
        page.setLayout(layout)

        page.initializePage = self.start_installation
        return page

    def create_finish_page(self):
        page = QWizardPage()
        page.setTitle("Installation Complete")
        page.setSubTitle("The Render Farm has been installed successfully.")
        
        layout = QVBoxLayout()
        
        success_text = QLabel(f"""
Installation completed successfully!

The Render Farm service has been installed and configured.


You can now close this installer.
        """)
        success_text.setWordWrap(True)
        success_text.setFont(QFont('Segoe UI', 10))
        
        layout.addWidget(success_text)
        page.setLayout(layout)
        return page

    def start_installation(self):
        """Start the installation process"""
        install_type = "server" if self.server_btn.isChecked() else "worker"
        
        # Create and start worker thread
        self.install_worker = InstallationWorker(install_type)
        self.install_worker.progress_updated.connect(self.progress.setValue)
        self.install_worker.status_updated.connect(self.status_label.setText)
        self.install_worker.installation_complete.connect(self.on_installation_complete)
        self.install_worker.start()
    
    def on_installation_complete(self, success, message):
        """Handle installation completion"""
        # Clean up the worker thread
        if hasattr(self, 'install_worker'):
            self.install_worker.quit()
            self.install_worker.wait(3000)  # Wait max 3 seconds
        
        if success:
            logger.info("Installation completed successfully")
            # Auto-advance to finish page after short delay
            QTimer.singleShot(1500, self.next)
        else:
            logger.error(f"Installation failed: {message}")
            # Show error message with log file location
            msg = QMessageBox(self)
            msg.setIcon(QMessageBox.Critical)
            msg.setWindowTitle("Installation Error")
            msg.setText(f"Installation failed:\n\n{message}\n\nCheck log file")
            msg.setStandardButtons(QMessageBox.Ok)
            msg.exec()

def main():
    """Main entry point"""
    print("=" * 50)
    print("  Render Farm Installer v2.0 (Dark Theme)")
    print("=" * 50)
    app = QApplication(sys.argv)
    wizard = InstallWizard()
    wizard.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
