"""
Fovea - macOS Desktop App

Launches the FastAPI backend in a background thread and opens
a native macOS webview window. Looks and feels like a real app,
not a browser tab.
"""

import sys
import os
import threading
import time
import signal
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(name)s] %(message)s')
log = logging.getLogger("fovea")

# Ensure we're running from the right directory
if getattr(sys, '_MEIPASS', None):
    # PyInstaller bundle
    os.chdir(sys._MEIPASS)
elif '__file__' in dir():
    os.chdir(os.path.dirname(os.path.abspath(__file__)))


def find_free_port():
    """Find an available port."""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('', 0))
        return s.getsockname()[1]


def start_server(port: int):
    """Start the FastAPI server in the current thread."""
    import uvicorn
    from main import app

    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


def wait_for_server(port: int, timeout: float = 15.0):
    """Wait until the server is ready."""
    import urllib.request
    start = time.time()
    while time.time() - start < timeout:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/volumes", timeout=1)
            return True
        except Exception:
            time.sleep(0.2)
    return False


def _set_macos_app_identity():
    """Make Python process show as 'Fovea' in Dock instead of 'Python'."""
    try:
        import AppKit
        # Set app name in menubar
        app = AppKit.NSApplication.sharedApplication()
        # Load icon if available
        icon_paths = [
            os.path.join(os.path.dirname(__file__), '..', 'Resources', 'fovea.icns'),
            os.path.join(os.path.dirname(__file__), 'fovea.icns'),
        ]
        for p in icon_paths:
            if os.path.exists(p):
                icon = AppKit.NSImage.alloc().initWithContentsOfFile_(os.path.abspath(p))
                if icon:
                    app.setApplicationIconImage_(icon)
                break
    except Exception:
        pass  # Not critical


def run_desktop():
    """Main entry point for the desktop app."""
    try:
        import webview
    except ImportError:
        log.error("pywebview not installed. Install it: pip install pywebview")
        log.info("Falling back to browser mode...")
        run_browser_fallback()
        return

    # Set macOS identity before creating window
    _set_macos_app_identity()

    port = find_free_port()
    log.info(f"Starting Fovea on port {port}...")

    # Start server in background thread
    server_thread = threading.Thread(target=start_server, args=(port,), daemon=True)
    server_thread.start()

    if not wait_for_server(port):
        log.error("Server failed to start")
        return

    log.info("Server ready, opening window...")

    # Create native window
    window = webview.create_window(
        title="Fovea",
        url=f"http://127.0.0.1:{port}",
        width=1280,
        height=820,
        min_size=(900, 600),
        confirm_close=False,
    )

    # Start webview (blocks until window is closed)
    webview.start(
        gui='cocoa',
        debug=False,
    )

    log.info("Window closed, shutting down...")
    os._exit(0)


def run_browser_fallback():
    """Fallback: start server and open in default browser."""
    import webbrowser

    port = 8080
    log.info(f"Starting Fovea on http://localhost:{port}")

    server_thread = threading.Thread(target=start_server, args=(port,), daemon=True)
    server_thread.start()

    if wait_for_server(port):
        webbrowser.open(f"http://localhost:{port}")
        log.info("Opened in browser. Press Ctrl+C to stop.")
        try:
            signal.pause()
        except (KeyboardInterrupt, AttributeError):
            while True:
                time.sleep(1)


if __name__ == "__main__":
    run_desktop()
