#!/usr/bin/env python3
# Copyright (C) CVAT.ai Corporation
# SPDX-License-Identifier: MIT

"""
CVAT Desktop Application Launcher
Serves the compiled CVAT web application locally, manages API reverse proxying,
and opens the default browser automatically.
"""

import sys
import os
import socket
import threading
import webbrowser
import mimetypes
import urllib.request
import urllib.error
import json
from pathlib import Path
from http.server import HTTPServer, SimpleHTTPRequestHandler

# Register required MIME types
mimetypes.add_type('application/wasm', '.wasm')
mimetypes.add_type('application/javascript', '.mjs')
mimetypes.add_type('application/javascript', '.js')
mimetypes.add_type('application/json', '.json')
mimetypes.add_type('image/svg+xml', '.svg')
mimetypes.add_type('application/octet-stream', '.onnx')
mimetypes.add_type('image/webp', '.webp')

def get_bundle_dir() -> Path:
    """Get the base directory where PyInstaller extracted the assets or current dir."""
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent

def get_static_dir() -> Path:
    """Find the directory containing compiled CVAT-UI static files."""
    bundle_dir = get_bundle_dir()
    
    # Check bundled path first (PyInstaller datas)
    candidates = [
        bundle_dir / "cvat_dist",
        bundle_dir / "dist",
        bundle_dir / "cvat-ui" / "dist",
        Path(__file__).resolve().parent / "cvat-ui" / "dist",
        Path(__file__).resolve().parent / "dist",
    ]
    for c in candidates:
        if c.exists() and (c / "index.html").exists():
            return c
            
    # Fallback to candidate that exists even if index.html isn't there yet
    for c in candidates:
        if c.exists():
            return c
            
    return bundle_dir / "cvat_dist"

def find_free_port(start_port: int = 3000, max_tries: int = 50) -> int:
    """Find an open TCP port starting from start_port."""
    for port in range(start_port, start_port + max_tries):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('127.0.0.1', port))
                return port
        except OSError:
            continue
    return start_port

class CVATRequestHandler(SimpleHTTPRequestHandler):
    """Custom request handler with SPA routing fallback and API reverse-proxying."""
    
    static_directory: Path = Path(".")
    backend_url: str = "http://localhost:7000"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(self.static_directory), **kwargs)

    def log_message(self, format, *args):
        """Suppress standard HTTP request logging for cleaner console output."""
        pass

    def do_GET(self):
        # Reverse proxy for API requests if requested path starts with /api/
        if self.path.startswith(("/api/", "/analytics/", "/static/", "/admin/", "/documentation/")):
            self.proxy_request()
            return

        # Serve static file or fallback to index.html (SPA client-side routing)
        clean_path = self.path.split('?')[0].split('#')[0].lstrip('/')
        target_file = self.static_directory / clean_path

        if clean_path and target_file.exists() and not target_file.is_dir():
            return super().do_GET()

        # If requesting a directory or root, serve index.html
        index_file = self.static_directory / "index.html"
        if index_file.exists():
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            content = index_file.read_bytes()
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
            return

        # If index.html doesn't exist, regular 404
        self.send_error(404, f"File not found: {self.path}")

    def do_POST(self):
        if self.path.startswith(("/api/", "/analytics/", "/admin/")):
            self.proxy_request()
        else:
            self.send_error(405, "Method Not Allowed")

    def do_PUT(self):
        if self.path.startswith(("/api/", "/analytics/", "/admin/")):
            self.proxy_request()
        else:
            self.send_error(405, "Method Not Allowed")

    def do_DELETE(self):
        if self.path.startswith(("/api/", "/analytics/", "/admin/")):
            self.proxy_request()
        else:
            self.send_error(405, "Method Not Allowed")

    def proxy_request(self):
        """Forward requests to the backend CVAT server if running."""
        url = f"{self.backend_url.rstrip('/')}{self.path}"
        content_len = int(self.headers.get('Content-Length', 0))
        post_body = self.rfile.read(content_len) if content_len > 0 else None

        req = urllib.request.Request(url, data=post_body, method=self.command)
        for header, value in self.headers.items():
            if header.lower() not in ('host', 'content-length'):
                req.add_header(header, value)

        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                self.send_response(resp.status)
                for h, v in resp.headers.items():
                    if h.lower() not in ('transfer-encoding', 'content-length'):
                        self.send_header(h, v)
                data = resp.read()
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
        except urllib.error.HTTPError as e:
            self.send_response(e.code)
            for h, v in e.headers.items():
                self.send_header(h, v)
            data = e.read()
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except Exception as e:
            # Backend not reachable
            self.send_response(503)
            self.send_header("Content-Type", "application/json")
            err_payload = (
                f'{{"error": "CVAT Backend unreachable at {self.backend_url}", '
                f'"details": "{str(e)}", '
                f'"hint": "Ensure CVAT backend is running or set CVAT_BACKEND_URL environment variable"}}'
            ).encode('utf-8')
            self.send_header("Content-Length", str(len(err_payload)))
            self.end_headers()
            self.wfile.write(err_payload)

def get_app_dir() -> Path:
    """Returns directory where executable resides (or script directory)."""
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent

def get_config_path() -> Path:
    return get_app_dir() / "config.json"

def load_backend_url() -> str:
    """Load backend URL from environment, config.json, or default."""
    env_val = os.environ.get("CVAT_BACKEND_URL")
    if env_val:
        return env_val.strip()

    cfg_path = get_config_path()
    if cfg_path.exists():
        try:
            with open(cfg_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                url = data.get("backend_url")
                if url:
                    return url.strip()
        except Exception as err:
            print(f"[!] Warning reading {cfg_path}: {err}")
    else:
        # Create default config.json for user convenience
        try:
            with open(cfg_path, 'w', encoding='utf-8') as f:
                json.dump({
                    "backend_url": "http://localhost:7000",
                    "description": "Specify the URL of your CVAT backend server. Example: http://localhost:7000, http://192.168.1.100:8080, or https://app.cvat.ai"
                }, f, indent=2)
        except Exception:
            pass

    return "http://localhost:7000"

def check_backend_health(url: str, timeout: float = 2.0) -> bool:
    """Quick check to see if backend responds."""
    try:
        health_url = f"{url.rstrip('/')}/api/server/about"
        req = urllib.request.Request(health_url, headers={'User-Agent': 'CVAT_Desktop_App'})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status in (200, 301, 302)
    except Exception:
        return False

def main():
    print("=" * 68)
    print("        CVAT Studio - Custom Dense Segmentation Workflow        ")
    print("=" * 68)

    static_dir = get_static_dir()
    backend_url = load_backend_url()

    if not static_dir.exists():
        print(f"[!] Warning: Static directory not found at: {static_dir}")
        print("    Ensure cvat-ui has been built (run `yarn workspace cvat-ui run build`).")
    else:
        print(f"[*] Static Assets : {static_dir}")

    port = find_free_port(3000)
    CVATRequestHandler.static_directory = static_dir
    CVATRequestHandler.backend_url = backend_url

    httpd = HTTPServer(('127.0.0.1', port), CVATRequestHandler)
    app_url = f"http://localhost:{port}"

    server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    server_thread.start()

    print(f"[*] Application Server : {app_url}")
    print(f"[*] Backend Server URL : {backend_url}")
    print(f"[*] Config File        : {get_config_path()}")

    # Check backend connectivity
    is_alive = check_backend_health(backend_url)
    if is_alive:
        print("[+] Backend Status     : CONNECTED")
    else:
        print("[-] Backend Status     : NOT REACHABLE")
        print("\n" + "-" * 68)
        print(" [!] NOTICE: The CVAT Backend server is not running at this address.")
        print("     To connect to your CVAT backend:")
        print("     1. If you run a local server or Docker, start it:")
        print("        docker compose up -d")
        print("     2. If you have a remote server or different IP/port, edit 'config.json':")
        print(f"        Path: {get_config_path()}")
        print("        Set 'backend_url' to your server (e.g. http://192.168.1.100:8080)")
        print("-" * 68 + "\n")

    print("[*] Opening web browser...")
    print("=" * 68)
    print("Application is running! Press Ctrl+C or Enter in this window to exit.")
    print("=" * 68)

    try:
        webbrowser.open(app_url)
    except Exception:
        pass

    try:
        input()
    except (KeyboardInterrupt, EOFError):
        pass
    finally:
        print("\nShutting down CVAT server...")
        httpd.shutdown()
        print("Done. Goodbye!")

if __name__ == '__main__':
    main()
