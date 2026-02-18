"""
EDBB Runner
Receives bot.py over HTTP, starts the bot process, and exposes status/logs.
"""

import json
import re
import subprocess
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

PORT = 6859
MAX_LOG_LINES = 2000

ALLOWED_ORIGINS = [
    re.compile(r"^https?://localhost(:\d+)?$"),
    re.compile(r"^https?://127\.0\.0\.1(:\d+)?$"),
    re.compile(r"^https?://\[::1\](:\d+)?$"),
    re.compile(r"^https?://himais0giiiin\.com$"),
    re.compile(r"^https?://([a-zA-Z0-9-]+\.)?himais0giiiin\.com$"),
    re.compile(r"^https?://beta\.himais0giiiin\.com$"),
    re.compile(r"^https?://([a-zA-Z0-9-]+\.)?edbb\.himaiso\.workers\.dev$"),
    re.compile(r"^https?://edbplugin\.github\.io$"),
]

bot_process = None
server = None
log_lock = threading.Lock()
log_lines = []
log_offset = 0
MODULE_PACKAGE_MAP = {
    "discord": "discord.py[voice]",
    "cv2": "opencv-python",
    "PIL": "Pillow",
    "yaml": "PyYAML",
    "dotenv": "python-dotenv",
    "bs4": "beautifulsoup4",
    "sklearn": "scikit-learn",
    "Crypto": "pycryptodome",
    "OpenSSL": "pyopenssl",
    "dateutil": "python-dateutil",
    "google.generativeai": "google-generativeai",
    "google.genai": "google-genai",
    "aiohttp": "aiohttp",
    "requests": "requests",
}


def append_log(line):
    """Append one line to in-memory log buffer."""
    global log_offset
    if line is None:
        return
    text = str(line).rstrip("\r\n")
    with log_lock:
        log_lines.append(text)
        if len(log_lines) > MAX_LOG_LINES:
            overflow = len(log_lines) - MAX_LOG_LINES
            del log_lines[:overflow]
            log_offset += overflow


def clear_logs():
    """Reset in-memory log buffer."""
    global log_offset
    with log_lock:
        log_lines.clear()
        log_offset = 0


def get_logs_from(offset):
    """Return logs from absolute offset."""
    with log_lock:
        normalized = max(int(offset or 0), log_offset)
        start = max(normalized - log_offset, 0)
        items = log_lines[start:]
        next_offset = log_offset + len(log_lines)
        return {
            "offset": normalized,
            "next_offset": next_offset,
            "logs": items,
            "truncated": normalized > next_offset,
        }


def _summarize_command_output(stdout, stderr, max_lines=6):
    lines = []
    for text in (stderr or "", stdout or ""):
        lines.extend([line.strip() for line in text.splitlines() if line.strip()])
    if not lines:
        return "No output."
    return " | ".join(lines[-max_lines:])


def _scan_missing_modules(python_path, bot_path):
    script = r"""
import ast
import importlib.util
import json
import sys
from pathlib import Path

bot_path = Path(sys.argv[1])
source = bot_path.read_text(encoding="utf-8")
tree = ast.parse(source, filename=str(bot_path))

modules = set()
for node in ast.walk(tree):
    if isinstance(node, ast.Import):
        for alias in node.names:
            if alias.name:
                modules.add(alias.name)
    elif isinstance(node, ast.ImportFrom):
        if node.level == 0 and node.module:
            modules.add(node.module)

def module_exists(name):
    try:
        return importlib.util.find_spec(name) is not None
    except Exception:
        return False

def is_local_module(name):
    root = name.split(".", 1)[0]
    root_dir = bot_path.parent / root
    if (bot_path.parent / f"{root}.py").exists():
        return True
    if root_dir.exists():
        return True
    return False

missing = []
for module_name in sorted(modules):
    root = module_name.split(".", 1)[0]
    if root in sys.builtin_module_names:
        continue
    if hasattr(sys, "stdlib_module_names") and root in sys.stdlib_module_names:
        continue
    if is_local_module(module_name):
        continue
    if not module_exists(module_name):
        missing.append(module_name)

print(json.dumps({"missing_modules": missing}, ensure_ascii=False))
"""
    result = subprocess.run(
        [str(python_path), "-c", script, str(bot_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        details = _summarize_command_output(result.stdout, result.stderr)
        append_log(f"Dependency scan skipped: {details}")
        return []
    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        append_log("Dependency scan returned invalid output.")
        return []
    missing = payload.get("missing_modules", [])
    if not isinstance(missing, list):
        return []
    return [name for name in missing if isinstance(name, str) and name.strip()]


def _module_install_candidates(module_name):
    root = module_name.split(".", 1)[0]
    candidates = []

    for key in (module_name, root):
        mapped = MODULE_PACKAGE_MAP.get(key)
        if mapped and mapped not in candidates:
            candidates.append(mapped)

    fallback_root = root.replace("_", "-").lower()
    if fallback_root and fallback_root not in candidates:
        candidates.append(fallback_root)

    fallback_full = module_name.replace("_", "-").replace(".", "-").lower()
    if fallback_full and fallback_full not in candidates:
        candidates.append(fallback_full)

    return candidates


def _module_is_available(python_path, module_name):
    check_code = (
        "import importlib.util, sys\n"
        "name = sys.argv[1]\n"
        "try:\n"
        "    print('1' if importlib.util.find_spec(name) is not None else '0')\n"
        "except Exception:\n"
        "    print('0')\n"
    )
    result = subprocess.run(
        [str(python_path), "-c", check_code, module_name],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return result.returncode == 0 and result.stdout.strip() == "1"


def _install_package(python_path, package_name):
    result = subprocess.run(
        [
            str(python_path),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            package_name,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    success = result.returncode == 0
    details = _summarize_command_output(result.stdout, result.stderr)
    return success, details


def ensure_bot_dependencies(python_path, bot_path):
    missing_modules = _scan_missing_modules(python_path, bot_path)
    if not missing_modules:
        append_log("Dependency check complete. No missing package detected.")
        return

    append_log(f"Missing modules detected: {', '.join(missing_modules)}")
    attempted_packages = set()
    unresolved_modules = []

    for module_name in missing_modules:
        if _module_is_available(python_path, module_name):
            continue

        installed = False
        for package_name in _module_install_candidates(module_name):
            if package_name in attempted_packages:
                if _module_is_available(python_path, module_name):
                    installed = True
                    break
                continue

            attempted_packages.add(package_name)
            append_log(f"Installing package '{package_name}' for '{module_name}'...")
            success, details = _install_package(python_path, package_name)
            if success:
                append_log(f"Installed package '{package_name}'.")
                if _module_is_available(python_path, module_name):
                    installed = True
                    break
            else:
                append_log(f"Failed to install '{package_name}': {details}")

        if not installed:
            unresolved_modules.append(module_name)

    if unresolved_modules:
        raise RuntimeError(
            "Could not resolve module(s): " + ", ".join(unresolved_modules)
        )

    append_log("Dependency installation complete.")


def _stream_reader(stream, stream_name):
    """Read bot stdout/stderr and forward to console + memory."""
    try:
        for line in iter(stream.readline, ""):
            if not line:
                break
            line = line.rstrip("\r\n")
            append_log(f"[{stream_name}] {line}")
            print(line)
    finally:
        try:
            stream.close()
        except Exception:
            pass


def _wait_for_process_exit(process):
    """Append one line when bot process exits."""
    try:
        code = process.wait()
        append_log(f"Bot process exited with code {code}.")
    except Exception as exc:
        append_log(f"Runner error while waiting process exit: {exc}")


class BotHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def _set_cors_headers(self):
        origin = self.headers.get("Origin")
        if origin and any(regex.match(origin) for regex in ALLOWED_ORIGINS):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _send_json(self, payload, status=200):
        self.send_response(status)
        self._set_cors_headers()
        self.send_header("Content-type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps(payload, ensure_ascii=False).encode("utf-8"))

    def do_OPTIONS(self):
        self.send_response(200)
        self._set_cors_headers()
        self.end_headers()

    def do_POST(self):
        if self.path not in ("/", ""):
            self._send_json({"status": "error", "message": "Not found"}, status=404)
            return

        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)

        try:
            bot_code = body.decode("utf-8")
            with open("bot.py", "w", encoding="utf-8") as handle:
                handle.write(bot_code)

            clear_logs()
            append_log("Received new bot.py from editor.")

            start_bot()
            self._send_json({"status": "ok", "message": "bot.py saved and starting"})
        except Exception as exc:
            append_log(f"Runner error while starting bot: {exc}")
            self._send_json({"status": "error", "message": str(exc)}, status=500)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path or "/")
        route = parsed.path or "/"
        query = urllib.parse.parse_qs(parsed.query)

        if route == "/logs":
            try:
                offset = int(query.get("offset", ["0"])[0])
            except (TypeError, ValueError):
                offset = 0
            payload = get_logs_from(offset)
            payload["status"] = "ok"
            payload["bot_running"] = bot_process is not None and bot_process.poll() is None
            self._send_json(payload)
            return

        if route != "/":
            self._send_json({"status": "error", "message": "Not found"}, status=404)
            return

        bot_exists = Path("bot.py").exists()
        bot_running = bot_process is not None and bot_process.poll() is None
        self._send_json(
            {
                "status": "running",
                "port": PORT,
                "bot_exists": bot_exists,
                "bot_running": bot_running,
            }
        )


def start_bot():
    """Start bot.py and stream logs into memory."""
    global bot_process

    if not Path("bot.py").exists():
        append_log("bot.py not found.")
        return

    if bot_process and bot_process.poll() is None:
        append_log("Stopping previous bot process...")
        bot_process.terminate()
        try:
            bot_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            bot_process.kill()

    python_path = Path("venv") / "Scripts" / "python.exe"
    if not python_path.exists():
        raise FileNotFoundError(f"Python runtime not found: {python_path}")
    ensure_bot_dependencies(python_path, Path("bot.py"))

    append_log("Starting bot process...")
    bot_process = subprocess.Popen(
        [str(python_path), "bot.py"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    if bot_process.stdout is not None:
        threading.Thread(
            target=_stream_reader,
            args=(bot_process.stdout, "stdout"),
            daemon=True,
        ).start()
    if bot_process.stderr is not None:
        threading.Thread(
            target=_stream_reader,
            args=(bot_process.stderr, "stderr"),
            daemon=True,
        ).start()
    threading.Thread(target=_wait_for_process_exit, args=(bot_process,), daemon=True).start()


def run_server():
    global server
    try:
        HTTPServer.allow_reuse_address = False
        server = HTTPServer(("localhost", PORT), BotHandler)
    except OSError:
        print("EDBB Runner is already running. Close it and try again.")
        return False
    server.serve_forever()
    return True


def cleanup():
    global bot_process, server
    if bot_process and bot_process.poll() is None:
        bot_process.terminate()
        try:
            bot_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            bot_process.kill()
    if server:
        server.shutdown()


def main():
    print("")
    print("=" * 50)
    print("<<<EDBB Runner started>>>")
    print("=" * 50)
    print("")
    print("Keep this window open while using the Run button.")

    if Path("bot.py").exists():
        append_log("Existing bot.py detected. Starting bot.")
        start_bot()

    try:
        run_server()
    except KeyboardInterrupt:
        print("")
    finally:
        cleanup()


if __name__ == "__main__":
    main()

