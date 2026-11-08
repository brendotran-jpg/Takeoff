"""Takeoff desktop app.

Runs the FastAPI backend on a random loopback port, protected by a per-launch
secret token, and shows the UI in a native window (WebView2 on Windows,
WKWebView on macOS, Qt WebEngine on Linux). Native file dialogs are exposed
to the page through pywebview's JS bridge.

    python desktop.py [project.qto] [--browser] [--debug]
    python desktop.py --self-test          # start server, check the API, exit (used by CI/builds)
    python desktop.py --gui-self-test      # open the window, check the page loaded, close
"""
from __future__ import annotations

import argparse
import os
import secrets
import socket
import sys
import threading
import time
import urllib.request
from pathlib import Path

os.environ["TAKEOFF_NO_DEFAULT_APP"] = "1"  # don't build the dev-server app on import

import uvicorn  # noqa: E402

from app import paths  # noqa: E402
from app.main import create_app  # noqa: E402
from app.project import PROJECT_EXT  # noqa: E402


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def initial_project(arg: str | None) -> Path:
    if arg:
        p = Path(arg).expanduser().resolve()
        return p if p.suffix.lower() == PROJECT_EXT else p.with_suffix(PROJECT_EXT)
    recent = paths.recent_projects()
    if recent:
        return Path(recent[0])
    base = paths.default_projects_dir()
    p, n = base / f"Untitled project{PROJECT_EXT}", 2
    while p.exists():
        p, n = base / f"Untitled project {n}{PROJECT_EXT}", n + 1
    return p


class Server:
    def __init__(self, app, port: int):
        cfg = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning",
                             loop="asyncio", http="h11", ws="none", lifespan="off")
        self.server = uvicorn.Server(cfg)
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def start(self, timeout=20.0):
        self.thread.start()
        t0 = time.time()
        while not self.server.started:
            if time.time() - t0 > timeout or not self.thread.is_alive():
                raise RuntimeError("backend failed to start")
            time.sleep(0.05)

    def stop(self):
        self.server.should_exit = True
        self.thread.join(timeout=5)


class Bridge:
    """Methods callable from JS as window.pywebview.api.<name>().
    Attributes start with '_' so pywebview doesn't try to expose them."""

    def __init__(self, app):
        self._app = app
        self._window = None

    def _dialog(self, kind: str, **kw):
        import webview
        fd = getattr(webview, "FileDialog", None)
        mode = getattr(fd, kind) if fd else getattr(webview, f"{kind}_DIALOG")
        return self._window.create_file_dialog(mode, **kw)

    def open_project_dialog(self):
        r = self._dialog("OPEN", directory=str(paths.default_projects_dir()),
                         file_types=("Takeoff project (*.qto)", "All files (*.*)"))
        return r[0] if r else None

    def save_project_dialog(self, suggested: str = "New project.qto"):
        r = self._dialog("SAVE", directory=str(paths.default_projects_dir()), save_filename=suggested,
                         file_types=("Takeoff project (*.qto)",))
        if not r:
            return None
        return r if isinstance(r, str) else r[0]

    def open_pdf_dialog(self):
        r = self._dialog("OPEN", allow_multiple=True, file_types=("PDF drawings (*.pdf)", "All files (*.*)"))
        return list(r) if r else []

    def save_export_dialog(self, kind: str):
        if kind not in ("xlsx", "csv"):
            return None
        prj = self._app.state.project
        name = (prj.meta().get("name") or "takeoff").strip()
        r = self._dialog("SAVE", directory=str(prj.path.parent), save_filename=f"{name}.{kind}",
                         file_types=(("Excel workbook (*.xlsx)",) if kind == "xlsx" else ("CSV (*.csv)",)))
        if not r:
            return None
        path = Path(r if isinstance(r, str) else r[0])
        if path.suffix.lower() != f".{kind}":
            path = path.with_suffix(f".{kind}")
        path.write_bytes(self._app.state.export_bytes(kind))
        return str(path)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Takeoff desktop")
    ap.add_argument("project", nargs="?", help="project file (.qto) to open or create")
    ap.add_argument("--browser", action="store_true", help="use the system browser instead of a native window")
    ap.add_argument("--debug", action="store_true", help="enable web inspector")
    ap.add_argument("--self-test", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--gui-self-test", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args(argv)

    project = initial_project(args.project)
    project.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(32)
    app = create_app(project, token=token, user_rules_dir=paths.user_rules_dir())
    paths.add_recent(project)
    port = free_port()
    server = Server(app, port)
    server.start()
    url = f"http://127.0.0.1:{port}/?token={token}"

    if args.self_test:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/rules", headers={"x-takeoff-token": token})
        n = len(__import__("json").loads(urllib.request.urlopen(req, timeout=10).read())["rules"])
        idx = urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{port}/static/js/main.js",
                                                            headers={"x-takeoff-token": token}), timeout=10).status
        print(f"SELF-TEST OK project={project} rules={n} static={idx}")
        server.stop()
        return 0

    if args.browser:
        import webbrowser
        webbrowser.open(url)
        print(f"Takeoff running at http://127.0.0.1:{port}/  (project: {project}) – Ctrl+C to quit")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        server.stop()
        return 0

    import webview
    bridge = Bridge(app)
    window = webview.create_window("Takeoff", url, js_api=bridge, width=1440, height=900, min_size=(1024, 640),
                                   text_select=True)
    bridge._window = window
    result = {}

    if args.gui_self_test:
        def probe():
            js = ("JSON.stringify({title: document.title, project: document.getElementById('projName').textContent,"
                  " bridge: !!(window.pywebview && window.pywebview.api && window.pywebview.api.open_pdf_dialog),"
                  " rules: document.querySelectorAll('#tools button').length})")
            for _ in range(60):
                time.sleep(0.5)
                try:
                    r = window.evaluate_js(js)
                except Exception:
                    continue
                if r and '"project":""' not in r:
                    result["probe"] = r
                    break
            shot = os.environ.get("TAKEOFF_SHOT")
            if shot:
                time.sleep(1.0)
                os.system(f"import -window root {shot} 2>/dev/null")
            window.destroy()
        threading.Thread(target=probe, daemon=True).start()

    webview.start(debug=args.debug, private_mode=False)
    server.stop()
    if args.gui_self_test:
        print("GUI-SELF-TEST", "OK" if result.get("probe") else "FAILED", result.get("probe"))
        return 0 if result.get("probe") else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
