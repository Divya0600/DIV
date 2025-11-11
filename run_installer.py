#!/usr/bin/env python3
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
