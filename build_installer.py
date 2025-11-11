#!/usr/bin/env python3
"""
Build script to create standalone installer executable
Creates a professional installer that can be distributed
"""

import os
import sys
import shutil
import subprocess
from pathlib import Path
import platform

def create_installer_spec():
    """Create PyInstaller spec file for the installer"""
    spec_content = '''# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['render_farm_installer_final.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('server.py', '.'),
        ('worker.py', '.'),
        ('redis_job_manager.py', '.'),
        ('server_config.json', '.'),
        ('worker_config.json', '.'),
        ('web_config.json', '.'),
        ('server_install.bat', '.'),
        ('worker_install.bat', '.'),
        ('logo.ico', '.'),
        ('web', 'web'),
        ('service', 'service'),
        ('packages', 'packages'),
        ('renderers', 'renderers'),  # Include renderers folder
        ('hook-renderers.py', '.'),  # Include renderer hook file
    ],
    hiddenimports=[
        'PySide6.QtWidgets',
        'PySide6.QtGui', 
        'PySide6.QtCore',
        'shiboken6',
        'json',
        'threading',
        'subprocess',
        'shutil',
        'platform',
        'requests',
        'redis',
        'psutil',
        'pathlib',
        'logging',
        'datetime',
        'uuid',
        'time',
        'sys',
        'os'
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='RenderFarmSetup',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='installer_icon.ico' if os.path.exists('installer_icon.ico') else None,
    version='version_info.txt' if os.path.exists('version_info.txt') else None,
)
'''
    
    with open('installer.spec', 'w') as f:
        f.write(spec_content)
    
    print("Created PyInstaller spec file")

def create_version_info():
    """Create version info for Windows executable"""
    if platform.system() != "Windows":
        return
    
    version_content = '''# UTF-8
#
# For more details about fixed file info 'ffi' see:
# http://msdn.microsoft.com/en-us/library/ms646997.aspx
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=(2,0,0,0),
    prodvers=(2,0,0,0),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
    ),
  kids=[
    StringFileInfo(
      [
      StringTable(
        u'040904B0',
        [StringStruct(u'CompanyName', u'ARONFX'),
        StringStruct(u'FileDescription', u'Render Farm Setup'),
        StringStruct(u'FileVersion', u'2.0.0.0'),
        StringStruct(u'InternalName', u'RenderFarmSetup'),
        StringStruct(u'LegalCopyright', u'Copyright (c) 2024 ARONFX'),
        StringStruct(u'OriginalFilename', u'RenderFarmSetup.exe'),
        StringStruct(u'ProductName', u'Professional VFX Render Farm'),
        StringStruct(u'ProductVersion', u'2.0.0.0')])
      ]), 
    VarFileInfo([VarStruct(u'Translation', [1033, 1200])])
  ]
)
'''
    
    with open('version_info.txt', 'w', encoding='utf-8') as f:
        f.write(version_content)
    
    print("Created version info file")

def create_installer_icon():
    """Create a simple installer icon"""
    # Check if logo.ico exists and copy it to installer_icon.ico
    if os.path.exists('logo.ico'):
        shutil.copy2('logo.ico', 'installer_icon.ico')
        print("Using logo.ico as installer icon")
    else:
        print("Using default application icon")

def check_dependencies():
    """Check if required dependencies are installed"""
    required_packages = ['pyinstaller']
    
    missing_packages = []
    
    for package in required_packages:
        try:
            __import__(package)
            print(f"{package} is installed")
        except ImportError:
            missing_packages.append(package)
            print(f"{package} is missing")
    
    if missing_packages:
        print(f"\\nInstalling missing packages: {', '.join(missing_packages)}")
        for package in missing_packages:
            try:
                subprocess.run([sys.executable, '-m', 'pip', 'install', package], 
                             check=True)
                print(f"Installed {package}")
            except subprocess.CalledProcessError:
                print(f"Failed to install {package}")
                return False
    
    return True

def build_installer():
    """Build the installer executable"""
    print("=== Building Render Farm Installer ===\\n")
    
    # Check dependencies
    print("1. Checking dependencies...")
    if not check_dependencies():
        print("ERROR: Dependency check failed")
        return False
    
    # Create build files
    print("\\n2. Creating build configuration...")
    create_installer_spec()
    create_version_info()
    create_installer_icon()
    
    # Clean previous builds
    print("\\n3. Cleaning previous builds...")
    build_dirs = ['build', 'dist', '__pycache__']
    for dir_name in build_dirs:
        if os.path.exists(dir_name):
            shutil.rmtree(dir_name)
            print(f"Cleaned {dir_name}")
    
    # Build with PyInstaller
    print("\\n4. Building installer executable...")
    try:
        subprocess.run([
            sys.executable, '-m', 'PyInstaller',
            '--clean',
            '--noconfirm',
            'installer.spec'
        ], check=True)
        
        print("Build completed successfully")
        
        # Check output
        if platform.system() == "Windows":
            installer_path = Path('dist') / 'RenderFarmSetup.exe'
        else:
            installer_path = Path('dist') / 'RenderFarmSetup'
        
        if installer_path.exists():
            file_size = installer_path.stat().st_size / 1024 / 1024  # MB
            print(f"Installer created: {installer_path}")
            print(f"   Size: {file_size:.1f} MB")
            
            # Create distribution folder
            dist_folder = Path('RenderFarmInstaller')
            if dist_folder.exists():
                shutil.rmtree(dist_folder)
            
            dist_folder.mkdir()
            
            # Copy installer
            final_installer = dist_folder / installer_path.name
            shutil.copy2(installer_path, final_installer)
            
            # Create README for distribution
            readme_content = f"""# Render Farm Installer v2.0

## Professional VFX Render Farm Setup

This installer will set up either a Render Farm Server or Worker on your machine.

### System Requirements:
- Windows 10/11
- Python 3.7+ (will be checked during installation)
- 4GB RAM minimum
- Network connectivity for worker-server communication

### Installation Types:

**Server Installation:**
- Install on your main control machine
- Provides job queue management and web interface
- Coordinates all worker machines
- Includes worker deployment tools

**Worker Installation:**
- Install on dedicated render machines
- Processes render jobs from the server
- Optimized for high-performance rendering
- Automatic job discovery and execution

### Quick Start:

1. Run `{installer_path.name}`
2. Choose "Server" or "Worker" installation
3. Configure installation path and settings
4. Let the installer handle dependencies and setup
5. Launch the application when complete

### Network Setup:

For multi-machine setups:
1. Install Server on main machine first
2. Note the server IP address
3. Install Workers on render machines
4. Provide server IP during worker installation

### Support:
- Documentation: See installed files
- Issues: Contact ARONFX support

---
Generated by Render Farm Build System v2.0
"""
            
            readme_file = dist_folder / 'README.txt'
            with open(readme_file, 'w') as f:
                f.write(readme_content)
            
            print(f" Distribution package created: {dist_folder}")
            print(f"\\n Ready for distribution!")
            print(f"   Installer: {final_installer}")
            print(f"   Package: {dist_folder}")
            
            return True
        else:
            print(" Installer executable not found")
            return False
        
    except subprocess.CalledProcessError as e:
        print(f"Build failed: {e}")
        return False
    
    finally:
        # Clean up temporary files
        temp_files = ['installer.spec', 'version_info.txt']
        for temp_file in temp_files:
            if os.path.exists(temp_file):
                os.remove(temp_file)

def create_development_installer():
    """Create a simple development installer script"""
    dev_installer_content = '''#!/usr/bin/env python3
"""
Development Installer - Run directly with Python
For development and testing purposes
"""

import sys
import os

# Add current directory to path so we can import setup_installer
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import and run the installer
from render_farm_installer import main

if __name__ == "__main__":
    print(" Render Farm Development Installer")
    print("=" * 50)
    main()
'''
    
    with open('run_installer.py', 'w', encoding='utf-8') as f:
        f.write(dev_installer_content)
    
    print("Created development installer script")

def main():
    """Main build process"""
    print("  Render Farm Installer Build System")
    print("=" * 50)
    
    # Check if we're in the right directory
    if not os.path.exists('render_farm_installer_final.py'):
        print("render_farm_installer_final.py not found!")
        print("   Make sure you're running this from the RenderFarm directory")
        return
    
    # Create development installer first
    create_development_installer()
    
    # Automatically build standalone executable
    print("\\nBuilding standalone executable installer...")
    choice = "2"  # Always build standalone executable
    
    # Build standalone executable
    success = build_installer()
    if success:
        print("\\n BUILD SUCCESSFUL!")
        print("\\n Installer created: ./RenderFarmInstaller/RenderFarmSetup.exe")
        print("\\n Ready to distribute!")
    else:
        print("\\n BUILD FAILED!")
        print("\\n   Check error messages above and try again.")

if __name__ == "__main__":
    main()