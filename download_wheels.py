#!/usr/bin/env python3
"""
Download PySide6 wheels for offline installation
Run this on a machine with internet to prepare the offline installer
"""

import subprocess
import sys
import os
from pathlib import Path

def download_wheels():
    """Download all required wheels for offline installation"""
    
    # Create wheels directory
    wheels_dir = Path("wheels")
    wheels_dir.mkdir(exist_ok=True)
    
    print("Downloading PySide6 and dependencies...")
    
    # Required packages
    packages = [
        "PySide6>=6.5.0",
        "shiboken6",
    ]
    
    try:
        for package in packages:
            print(f"Downloading {package}...")
            result = subprocess.run([
                sys.executable, "-m", "pip", "download",
                package,
                "--dest", str(wheels_dir),
                "--only-binary=:all:"
            ], check=True)
            
        print(f"\n✅ All wheels downloaded to: {wheels_dir.absolute()}")
        
        # List downloaded files
        wheel_files = list(wheels_dir.glob("*.whl"))
        print(f"\nDownloaded {len(wheel_files)} wheel files:")
        for wheel in wheel_files:
            print(f"  - {wheel.name}")
        
        return True
        
    except subprocess.CalledProcessError as e:
        print(f"❌ Failed to download wheels: {e}")
        return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

def main():
    print("=" * 50)
    print("  PySide6 Wheel Downloader")
    print("=" * 50)
    print("This will download PySide6 wheels for offline installation")
    print()
    
    if download_wheels():
        print("\n🚀 Ready! You can now build the offline installer.")
        print("\nNext steps:")
        print("1. Run build_installer.py")
        print("2. The installer will include offline PySide6 installation")
    else:
        print("\n❌ Download failed. Check your internet connection and try again.")

if __name__ == "__main__":
    main()