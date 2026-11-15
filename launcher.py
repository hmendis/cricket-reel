"""Entry point for the packaged desktop app (PyInstaller). For development use start.bat instead."""
import sys

from app.desktop import main

if __name__ == "__main__":
    sys.exit(main())
