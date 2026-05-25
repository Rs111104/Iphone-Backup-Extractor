#!/usr/bin/env python
"""
Main entry point for iBackupX
Can be run as: python main.py
"""
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from ibackupx.cli import main

if __name__ == '__main__':
    main()
