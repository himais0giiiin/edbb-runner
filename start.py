"""
EDBB - Discord Bot環境
HTTPサーバーでbot.pyを受信し、BOTを起動します
"""

import os
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
import subprocess
import signal
from pathlib import Path

# ============================================
# 設定
# ============================================

# HTTPサーバーのポート番号
PORT = 6859

# CORS許可ドメインリスト
ALLOWED_ORIGINS = [
    "https://himais0giiiin.com",
    "https://beta.himais0giiiin.com",
]

# ============================================
# グローバル変数
# ============================================

bot_process = None


class BotHandler(BaseHTTPRequestHandler):
    """HTTPリクエストハンドラー"""

    def log_message(self, format, *args):
        """ログ出力を抑制"""
        pass

    def _set_cors_headers(self):
        """CORSヘッダーを設定"""
        origin = self.headers.get('Origin')
        if origin in ALLOWED_ORIGINS:
            self.send_header('Access-Control-Allow-Origin', origin)
            self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
            self.send_header('Access-Control-Allow-Headers', 'Content-Type, X-Bot-Token')
            self.send_header('Access-Control-Allow-Credentials', 'true')

    def do_OPTIONS(self):
        """プリフライトリクエストに対応"""
        self.send_response(200)
        self._set_cors_headers()
        self.end_headers()

    def do_POST(self):
        """POSTリクエストでbot.pyを受信"""
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length)

        try:
            # bot.pyとして保存
            bot_code = body.decode('utf-8')
            with open('bot.py', 'w', encoding='utf-8') as f:
                f.write(bot_code)

            # bot.pyを起動
            start_bot()

            self.send_response(200)
            self._set_cors_headers()
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{"status": "ok", "message": "bot.py saved and started"}')

        except Exception as e:
            self.send_response(500)
            self._set_cors_headers()
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(f'{{"status": "error", "message": "{str(e)}"}}'.encode())

    def do_GET(self):
        """GETリクエストでステータスを返す"""
        bot_exists = Path('bot.py').exists()
        bot_running = bot_process is not None and bot_process.poll() is None

        status = {
            "status": "running",
            "port": PORT,
            "bot_exists": bot_exists,
            "bot_running": bot_running
        }

        self.send_response(200)
        self._set_cors_headers()
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        import json
        self.wfile.write(json.dumps(status, ensure_ascii=False).encode('utf-8'))


def start_bot():
    """bot.pyを起動（既に起動中の場合は再起動）"""
    global bot_process

    if not Path('bot.py').exists():
        return

    # 既存のプロセスを終了
    if bot_process and bot_process.poll() is None:
        bot_process.terminate()
        try:
            bot_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            bot_process.kill()

    # 新しいプロセスを起動
    python_path = os.path.join('venv', 'Scripts', 'python.exe')
    bot_process = subprocess.Popen(
        [python_path, 'bot.py'],
        stdout=sys.stdout,
        stderr=sys.stderr
    )


def run_server():
    """HTTPサーバーを起動"""
    server = HTTPServer(('localhost', PORT), BotHandler)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


def signal_handler(sig, frame):
    """Ctrl+Cシグナルハンドラー"""
    # BOTプロセスを終了
    global bot_process
    if bot_process and bot_process.poll() is None:
        bot_process.terminate()
        try:
            bot_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            bot_process.kill()

    sys.exit(0)


def main():
    """メイン処理"""
    # シグナルハンドラーを登録
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # bot.pyが存在する場合は起動
    if Path('bot.py').exists():
        start_bot()

    # メッセージ表示
    print("準備完了")
    print("EDBBページから▶ボタンを押すことで実行できます。")

    # HTTPサーバーを起動（メインスレッドで実行）
    run_server()


if __name__ == '__main__':
    main()
