#!/usr/bin/env python3
"""Launch Job Search Agent as a desktop application."""

import threading
import time
import os
import sys

# Ensure we're running from the right directory
os.chdir(os.path.dirname(os.path.abspath(__file__)))

# Import the server
from app import HTTPServer, Handler, PORT, RESUMES_DIR, DATA_FILE, save_data

import webview

def start_server():
    os.makedirs(RESUMES_DIR, exist_ok=True)
    if not os.path.exists(DATA_FILE):
        save_data({"resumes": []})
    server = HTTPServer(("127.0.0.1", PORT), Handler)
    server.serve_forever()

if __name__ == "__main__":
    # Start server in background thread
    server_thread = threading.Thread(target=start_server, daemon=True)
    server_thread.start()

    # Give server a moment to start
    time.sleep(0.5)

    # Open native window
    webview.create_window(
        "Job Search Agent",
        f"http://127.0.0.1:{PORT}/static/index.html",
        width=1200,
        height=800,
        min_size=(900, 600),
    )
    webview.start()
