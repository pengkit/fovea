"""
Fovea - First Launch Setup Server

Uses ONLY Python stdlib (no pip dependencies).
Shows a visual setup page while installing dependencies.
Auto-redirects to the main app when done.
"""

import http.server
import json
import os
import subprocess
import sys
import threading
import time
import socket

FOVEA_HOME = os.path.join(os.path.expanduser("~"), "Library", "Application Support", "Fovea")
VENV_DIR = os.path.join(FOVEA_HOME, "venv")
STATUS_FILE = os.path.join(FOVEA_HOME, "setup_status.json")
LOG_FILE = os.path.join(FOVEA_HOME, "fovea.log")

# The port the main app will run on (passed as argv)
MAIN_APP_PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
SETUP_PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 9999


def find_python():
    for p in ["/opt/homebrew/bin/python3", "/usr/local/bin/python3"]:
        if os.path.exists(p):
            try:
                ver = subprocess.check_output([p, "-c", "import sys; print(sys.version_info.minor)"], text=True).strip()
                if int(ver) >= 11:
                    return p
            except Exception:
                pass
    return sys.executable


def update_status(step, message, progress, done=False, error=None):
    with open(STATUS_FILE, "w") as f:
        json.dump({
            "step": step,
            "message": message,
            "progress": progress,
            "done": done,
            "error": error,
            "main_port": MAIN_APP_PORT,
        }, f)


def run_setup():
    """Run the full setup in a background thread."""
    python = find_python()

    try:
        # Step 1: Create venv
        update_status(1, f"Creating Python environment...", 10)
        subprocess.run([python, "-m", "venv", VENV_DIR],
                       capture_output=True, timeout=60)

        pip = os.path.join(VENV_DIR, "bin", "pip")
        if not os.path.exists(pip):
            update_status(1, "Failed to create environment", 10, error="venv creation failed")
            return

        # Step 2: Upgrade pip
        update_status(2, "Updating package manager...", 20)
        subprocess.run([pip, "install", "-q", "--upgrade", "pip"],
                       capture_output=True, timeout=120)

        # Step 3: Core dependencies
        update_status(3, "Installing core (FastAPI, Pillow)...", 35)
        result = subprocess.run(
            [pip, "install", "-q", "fastapi", "uvicorn", "pillow", "httpx"],
            capture_output=True, text=True, timeout=300,
        )
        if result.returncode != 0:
            update_status(3, "Core install failed", 35, error=result.stderr[:200])
            return

        # Step 4: Native window
        update_status(4, "Installing native window (pywebview)...", 50)
        subprocess.run(
            [pip, "install", "-q", "pywebview"],
            capture_output=True, timeout=300,
        )

        # Step 5: RAW support
        update_status(5, "Installing RAW file support...", 65)
        subprocess.run(
            [pip, "install", "-q", "rawpy"],
            capture_output=True, timeout=300,
        )

        # Step 6: Photos library support
        update_status(6, "Installing Photos library support...", 75)
        subprocess.run(
            [pip, "install", "-q", "osxphotos"],
            capture_output=True, timeout=300,
        )

        # Step 7: AI (optional, but install basic opencv)
        update_status(7, "Installing image analysis tools...", 88)
        subprocess.run(
            [pip, "install", "-q", "opencv-python"],
            capture_output=True, timeout=300,
        )

        # Done
        update_status(8, "Setup complete! Launching Fovea...", 100, done=True)

    except Exception as e:
        update_status(0, f"Error: {e}", 0, error=str(e))


SETUP_HTML = """<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>Fovea - Setup</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  font-family: -apple-system, BlinkMacSystemFont, "SF Pro", sans-serif;
  background: #f5f5f7;
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  color: #1d1d1f;
}
.container {
  background: white;
  border-radius: 20px;
  padding: 48px;
  width: 480px;
  box-shadow: 0 4px 24px rgba(0,0,0,0.08);
  text-align: center;
}
.icon {
  width: 80px; height: 80px;
  margin: 0 auto 24px;
  background: linear-gradient(135deg, #6366f1, #818cf8);
  border-radius: 18px;
  display: flex;
  align-items: center;
  justify-content: center;
}
.icon svg { width: 40px; height: 40px; }
h1 { font-size: 24px; font-weight: 700; margin-bottom: 8px; }
.subtitle { font-size: 14px; color: #86868b; margin-bottom: 32px; }
.progress-track {
  width: 100%;
  height: 6px;
  background: #e8e8ed;
  border-radius: 3px;
  overflow: hidden;
  margin-bottom: 16px;
}
.progress-fill {
  height: 100%;
  background: linear-gradient(90deg, #6366f1, #818cf8);
  border-radius: 3px;
  transition: width 0.5s ease;
  width: 0%;
}
.status {
  font-size: 13px;
  color: #86868b;
  min-height: 20px;
}
.steps {
  text-align: left;
  margin-top: 28px;
  font-size: 13px;
}
.step {
  padding: 8px 0;
  display: flex;
  align-items: center;
  gap: 10px;
  color: #86868b;
}
.step.active { color: #1d1d1f; font-weight: 500; }
.step.done { color: #34c759; }
.step .dot {
  width: 8px; height: 8px;
  border-radius: 50%;
  background: #e8e8ed;
  flex-shrink: 0;
}
.step.active .dot { background: #6366f1; box-shadow: 0 0 8px rgba(99,102,241,0.5); }
.step.done .dot { background: #34c759; }
.error { color: #ff3b30; font-size: 12px; margin-top: 12px; }
</style>
</head>
<body>
<div class="container">
  <div class="icon">
    <svg viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2" stroke-linecap="round">
      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
      <polyline points="7 10 12 15 17 10"/>
      <line x1="12" y1="15" x2="12" y2="3"/>
    </svg>
  </div>
  <h1>Setting up Fovea</h1>
  <p class="subtitle">First-time setup, this only happens once</p>
  <div class="progress-track"><div class="progress-fill" id="progress"></div></div>
  <div class="status" id="status">Preparing...</div>
  <div class="steps">
    <div class="step" data-step="1"><span class="dot"></span>Create Python environment</div>
    <div class="step" data-step="2"><span class="dot"></span>Update package manager</div>
    <div class="step" data-step="3"><span class="dot"></span>Install core framework</div>
    <div class="step" data-step="4"><span class="dot"></span>Install native window</div>
    <div class="step" data-step="5"><span class="dot"></span>Install RAW file support</div>
    <div class="step" data-step="6"><span class="dot"></span>Install Photos library support</div>
    <div class="step" data-step="7"><span class="dot"></span>Install image analysis</div>
    <div class="step" data-step="8"><span class="dot"></span>Launch Fovea</div>
  </div>
  <div class="error" id="error"></div>
</div>
<script>
function poll() {
  fetch('/status').then(r => r.json()).then(data => {
    document.getElementById('progress').style.width = data.progress + '%';
    document.getElementById('status').textContent = data.message;
    document.querySelectorAll('.step').forEach(el => {
      const s = parseInt(el.dataset.step);
      el.className = 'step' + (s < data.step ? ' done' : s === data.step ? ' active' : '');
    });
    if (data.error) {
      document.getElementById('error').textContent = data.error;
    }
    if (data.done) {
      document.getElementById('status').textContent = 'Launching...';
      setTimeout(() => { window.location.href = 'http://127.0.0.1:' + data.main_port; }, 2000);
    } else {
      setTimeout(poll, 800);
    }
  }).catch(() => setTimeout(poll, 1000));
}
poll();
</script>
</body>
</html>"""


class SetupHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/status":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            try:
                with open(STATUS_FILE) as f:
                    self.wfile.write(f.read().encode())
            except FileNotFoundError:
                self.wfile.write(b'{"step":0,"message":"Starting...","progress":0}')
        else:
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(SETUP_HTML.encode())

    def log_message(self, format, *args):
        pass  # Suppress logs


def main():
    os.makedirs(FOVEA_HOME, exist_ok=True)
    update_status(0, "Starting setup...", 0)

    # Start setup in background
    threading.Thread(target=run_setup, daemon=True).start()

    # Serve setup page
    server = http.server.HTTPServer(("127.0.0.1", SETUP_PORT), SetupHandler)
    print(f"Setup server on http://127.0.0.1:{SETUP_PORT}")

    # Auto-shutdown after setup completes
    def watch_completion():
        while True:
            time.sleep(1)
            try:
                with open(STATUS_FILE) as f:
                    data = json.load(f)
                    if data.get("done"):
                        time.sleep(3)  # Let the redirect happen
                        server.shutdown()
                        return
            except Exception:
                pass

    threading.Thread(target=watch_completion, daemon=True).start()
    server.serve_forever()


if __name__ == "__main__":
    main()
