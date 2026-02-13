"""
EDBB Runner
Receives bot.py over HTTP, starts the bot process, and exposes status/logs.
"""

import json
import os
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

    python_path = os.path.join("venv", "Scripts", "python.exe")
    if not Path(python_path).exists():
        raise FileNotFoundError(f"Python runtime not found: {python_path}")

    append_log("Starting bot process...")
    bot_process = subprocess.Popen(
        [python_path, "bot.py"],
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
    print("EDBB Runner started")
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
