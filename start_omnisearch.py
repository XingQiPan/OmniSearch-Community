"""Safe local launcher. --check never starts services or opens a browser."""

import argparse
from contextlib import contextmanager
import hashlib
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import webbrowser

ROOT = Path(__file__).resolve().parent
BACKEND_PORT = 8088
FRONTEND_PORT = 5173
API_TITLE = "OmniSearch 聚合大搜索引擎 & 总网关控制台 API"
API_VERSION = "2.1.0"
API_PATHS = {"/api/admin/dashboard", "/api/v1/search", "/api/v1/agent/stream", "/v1/chat/completions", "/v1/search", "/v1/extract", "/v1/answer"}
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())


class LaunchError(RuntimeError):
    pass


def request(port, path):
    url = f"http://127.0.0.1:{port}{path}"
    try:
        with OPENER.open(url, timeout=2) as response:
            # Never follow a redirect to an external server or an alternate port.
            if response.geturl() != url:
                raise LaunchError(f"Unexpected redirect at {url}")
            data = response.read(2_000_001)
            if len(data) > 2_000_000:
                raise LaunchError(f"Oversized response at {url}")
            return data.decode("utf-8")
    except (OSError, ValueError, urllib.error.URLError) as exc:
        raise LaunchError(f"Cannot verify {url}: {exc}") from exc


def read_json(port, path):
    try:
        return json.loads(request(port, path))
    except ValueError as exc:
        raise LaunchError(f"Port {port}: invalid JSON from {path}") from exc


def port_available(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        if os.name == "nt":
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            sock.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def dashboard_ready(port):
    data = read_json(port, "/api/admin/dashboard")
    if not isinstance(data, dict) or not isinstance(data.get("kpis"), dict) or not isinstance(data.get("providers"), list):
        raise LaunchError(f"Port {port}: OmniSearch dashboard is not ready")


def verify_backend():
    schema = read_json(BACKEND_PORT, "/openapi.json")
    info = schema.get("info") if isinstance(schema, dict) else None
    paths = schema.get("paths") if isinstance(schema, dict) else None
    if (not isinstance(info, dict) or not isinstance(paths, dict)
            or info.get("title") != API_TITLE
            or info.get("version") != API_VERSION
            or not API_PATHS.issubset(paths)):
        raise LaunchError(f"Port {BACKEND_PORT} belongs to a different application (OpenAPI identity mismatch)")
    # This existing GET performs local SELECTs only; no provider/search/test calls.
    dashboard_ready(BACKEND_PORT)


def verify_frontend(root):
    html = request(FRONTEND_PORT, "/")
    local_html = (root / "frontend" / "index.html").read_text(encoding="utf-8")
    title = re.search(r"<title>(.*?)</title>", local_html)
    entry = re.search(r"src=[\"']/src/main\.tsx(?:\?[^\"']*)?[\"']", html)
    if not title or title.group(0) not in html or not entry or "/@vite/client" not in html:
        raise LaunchError(f"Port {FRONTEND_PORT} belongs to a different application (frontend identity mismatch)")
    main = request(FRONTEND_PORT, "/src/main.tsx")
    app = request(FRONTEND_PORT, "/src/App.tsx")
    if "/src/App.tsx" not in main or not all(name in app for name in ("SearchWorkspace", "RoutingStudio", "AuditAndGatewayPage")):
        raise LaunchError(f"Port {FRONTEND_PORT}: OmniSearch frontend modules are not ready")


def service_states(root):
    states = {}
    for name, port, verify in (
        ("backend", BACKEND_PORT, verify_backend),
        ("frontend", FRONTEND_PORT, lambda: verify_frontend(root)),
    ):
        if port_available(port):
            states[name] = "stopped"
        else:
            try:
                verify()
            except LaunchError as exc:
                raise LaunchError(f"Port {port} is occupied but is not a verified ready OmniSearch service: {exc}. No process was stopped; no port was changed.") from exc
            states[name] = "ready"
    return states


def version_tuple(value):
    match = re.match(r"^(\d+)\.(\d+)(?:\.(\d+))?", value)
    if not match:
        raise LaunchError(f"Cannot verify dependency version: {value}")
    return tuple(int(part or 0) for part in match.groups())


def check_dependencies(root):
    if sys.version_info < (3, 9):
        raise LaunchError("Python 3.9+ is required")
    required_files = ("backend/app/main.py", "backend/requirements.txt", "frontend/package.json", "frontend/index.html", "frontend/vite.config.ts")
    for relative in required_files:
        if not (root / relative).is_file():
            raise LaunchError(f"Missing application file: {root / relative}")
    modules = {"beautifulsoup4": "bs4"}
    for line in (root / "backend/requirements.txt").read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = re.fullmatch(r"([\w-]+)>=(\d+\.\d+(?:\.\d+)?)", line.strip())
        if not match:
            raise LaunchError(f"Unsupported requirement; check manually: {line}")
        name, minimum = match.groups()
        try:
            installed = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError as exc:
            raise LaunchError(f"Missing Python dependency: {name} (interpreter: {sys.executable}). Install manually; nothing was installed.") from exc
        if version_tuple(installed) < version_tuple(minimum) or importlib.util.find_spec(modules.get(name, name.replace("-", "_"))) is None:
            raise LaunchError(f"Python dependency {name}>={minimum} is required; found {installed}")
    node = shutil.which("node")
    if not node:
        raise LaunchError("Node.js is missing from PATH; install dependencies manually")
    try:
        result = subprocess.run([node, "--version"], capture_output=True, text=True, timeout=5, check=True)
    except (OSError, subprocess.SubprocessError) as exc:
        raise LaunchError(f"Node.js cannot run: {exc}") from exc
    if version_tuple(result.stdout.strip().lstrip("v")) < (18, 0, 0):
        raise LaunchError("Vite 6 requires Node.js 18+")
    package = json.loads((root / "frontend/package.json").read_text(encoding="utf-8"))
    for name in {**package.get("dependencies", {}), **package.get("devDependencies", {})}:
        manifest = root / "frontend" / "node_modules" / name / "package.json"
        if not manifest.is_file():
            raise LaunchError(f"Missing frontend dependency: {name}. Install manually; nothing was installed.")
    vite = root / "frontend/node_modules/vite/bin/vite.js"
    if not vite.is_file():
        raise LaunchError(f"Missing Vite entry point: {vite}")
    return node, vite


def runtime_dir(root):
    digest = hashlib.sha256(str(root.resolve()).casefold().encode("utf-8")).hexdigest()[:16]
    directory = Path(tempfile.gettempdir()) / f"omnisearch-launcher-{digest}"
    directory.mkdir(exist_ok=True)
    return directory


@contextmanager
def launch_lock(directory):
    # The file is intentionally retained; locking is released by the OS on exit.
    with (directory / "launch.lock").open("a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise LaunchError("Another launcher is checking/starting this project. Wait and retry; no duplicate service was started.") from exc
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def start_service(name, command, cwd, directory):
    log_path = directory / f"{name}-{time.time_ns()}.log"
    environment = os.environ.copy()
    environment["PYTHONUNBUFFERED"] = "1"
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    flags = subprocess.CREATE_NEW_CONSOLE if os.name == "nt" else 0
    try:
        with log_path.open("ab") as log:
            process = subprocess.Popen(command, cwd=cwd, env=environment, stdin=subprocess.DEVNULL,
                                       stdout=log, stderr=subprocess.STDOUT, creationflags=flags)
    except OSError as exc:
        raise LaunchError(f"Cannot start {name}: {exc}; log: {log_path}") from exc
    print(f"[STARTING] {name}: PID {process.pid}; log: {log_path}")
    return process, log_path


def wait_ready(name, verify, process, log_path, timeout):
    deadline = time.monotonic() + timeout
    last_error = "no response"
    while time.monotonic() < deadline:
        code = process.poll()
        if code is not None:
            raise LaunchError(f"{name} exited before readiness (exit {code}); see {log_path}")
        try:
            verify()
            # Do not accept an endpoint if our child has already failed to bind.
            time.sleep(0.2)
            if process.poll() is not None:
                raise LaunchError(f"{name} exited during readiness; see {log_path}")
            return
        except LaunchError as exc:
            last_error = str(exc)
        time.sleep(0.25)
    raise LaunchError(f"{name} was not ready within {timeout:g}s: {last_error}; PID {process.pid}, log: {log_path}. No process was stopped.")


def launch(root=ROOT, check=False, no_browser=False, timeout=30):
    node, vite = check_dependencies(root)
    with launch_lock(runtime_dir(root)):
        # Inspect BOTH ports before starting either component.
        states = service_states(root)
        if check:
            for name, state in states.items():
                print(f"[CHECK] {name}: {state}")
            if any(state != "ready" for state in states.values()):
                raise LaunchError("Check only: both services must already be ready. Nothing was started.")
        else:
            commands = {
                "backend": [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(BACKEND_PORT)],
                # Direct node invocation avoids npm.cmd/cmd quoting; strictPort forbids fallback.
                "frontend": [node, str(vite), "--host", "127.0.0.1", "--port", str(FRONTEND_PORT), "--strictPort"],
            }
            for name, verify in (("backend", verify_backend), ("frontend", lambda: verify_frontend(root))):
                if states[name] == "ready":
                    print(f"[REUSE] Verified ready OmniSearch {name}; existing process unchanged")
                    continue
                process, log_path = start_service(name, commands[name], root / name, runtime_dir(root))
                wait_ready(name, verify, process, log_path, timeout)
        # Also verify Vite's API proxy (read-only), not just a matching HTML page.
        verify_backend()
        verify_frontend(root)
        dashboard_ready(FRONTEND_PORT)
        print("[READY] Backend API: http://127.0.0.1:8088/docs")
        print("[READY] Frontend: http://127.0.0.1:5173 (API proxy verified)")
        if not check and not no_browser:
            if not webbrowser.open(f"http://127.0.0.1:{FRONTEND_PORT}"):
                print("[WARNING] Browser could not open; use the frontend URL above")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Verify dependencies and running services only; no launch/browser")
    parser.add_argument("--no-browser", action="store_true", help="Start/reuse services without opening a browser")
    parser.add_argument("--timeout", type=float, default=30, help="Readiness deadline per new service in seconds (default: 30)")
    args = parser.parse_args(argv)
    if not 0 < args.timeout <= 300:
        parser.error("--timeout must be greater than 0 and at most 300")
    try:
        return launch(check=args.check, no_browser=args.no_browser, timeout=args.timeout)
    except (LaunchError, OSError, ValueError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("[ERROR] Launcher interrupted; no existing service was stopped. Any newly started PID/log is shown above.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="backslashreplace")
    sys.exit(main())
