"""Purple Paper Windows desktop launcher.
Starts the local simulator server and hosts it in a native WebView2 window.
No brokerage-order endpoints are used by this desktop shell.
"""
from __future__ import annotations
import socket
import threading
import time
import urllib.request
from pathlib import Path

import uvicorn
import webview

ROOT = Path(__file__).resolve().parent
HOST = "127.0.0.1"
PORT = 8787


def port_open(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.25)
        return sock.connect_ex((host, port)) == 0


def run_server() -> None:
    uvicorn.run("app:app", host=HOST, port=PORT, log_level="warning", app_dir=str(ROOT))


def wait_for_server(timeout: float = 12.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://{HOST}:{PORT}/", timeout=0.5) as response:
                return response.status == 200
        except Exception:
            time.sleep(0.15)
    return False


def main() -> None:
    if not port_open(HOST, PORT):
        thread = threading.Thread(target=run_server, daemon=True, name="purple-paper-server")
        thread.start()
        wait_for_server()

    window = webview.create_window(
        "Purple Paper V8 — Network",
        f"http://{HOST}:{PORT}",
        width=1480,
        height=920,
        min_size=(1050, 680),
        background_color="#09070d",
        text_select=True,
    )
    webview.start(debug=False, private_mode=False)


if __name__ == "__main__":
    main()
