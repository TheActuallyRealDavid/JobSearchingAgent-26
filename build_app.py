#!/usr/bin/env python3
"""Build Job Search Agent as a macOS .app bundle."""

import subprocess
import sys
import os

os.chdir(os.path.dirname(os.path.abspath(__file__)))

pyinstaller = os.path.expanduser("~/Library/Python/3.9/bin/pyinstaller")

cmd = [
    pyinstaller,
    "--name", "Job Search Agent",
    "--windowed",           # .app bundle, no terminal window
    "--onedir",             # faster startup than --onefile
    "--noconfirm",          # overwrite previous build
    "--add-data", "static:static",
    "--hidden-import", "webview",
    "--hidden-import", "pdfplumber",
    "--hidden-import", "pdfminer",
    "--hidden-import", "pdfminer.high_level",
    "--hidden-import", "pdfminer.layout",
    "--hidden-import", "pdfminer.pdfinterp",
    "--hidden-import", "pdfminer.converter",
    "--hidden-import", "pdfminer.pdfpage",
    "--hidden-import", "pdfminer.pdfdocument",
    "--hidden-import", "pdfminer.pdfparser",
    "--hidden-import", "pdfminer.psparser",
    "--hidden-import", "pdfminer.pdftypes",
    "--hidden-import", "pdfminer.utils",
    "--collect-all", "pdfplumber",
    "--collect-all", "webview",
    "launch.py",
]

print("Building .app bundle...")
subprocess.run(cmd, check=True)

print("\n✅ Build complete!")
print("Your app is at: dist/Job Search Agent.app")
print("You can drag it to /Applications or your Dock.")
