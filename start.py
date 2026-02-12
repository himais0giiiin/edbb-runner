"""
EDBB - Discord Bot環境
HTTPサーバーでbot.pyを受信し、BOTを起動します
"""

import os
import sys
import re
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

# CORS許可リスト（正規表現）
ALLOWED_ORIGINS = [
    re.compile(r'^https?://localhost(:\d+)?$'),
    re.compile(r'^https?://127\.0\.0\.1(:\d+)?$'),
    re.compile(r'^https?://\[::1\](:\d+)?$'),
    re.compile(r'^https?://himais0giiiin\.com$'),
    re.compile(r'^https?://([a-zA-Z0-9-]+\.)?himais0giiiin\.com$'),
    re.compile(r'^https?://beta\.himais0giiiin\.com$'),
    re.compile(r'^https?://([a-zA-Z0-9-]+\.)?edbb\.himaiso\.workers\.dev$'),
    re.compile(r'^https?://edbplugin\.github\.io$'),
]

# ============================================
# グローバル変数
# ============================================

bot_process = None
server = None


class BotHandler(BaseHTTPRequestHandler):
    """HTTPリクエストハンドラー"""

    def log_message(self, format, *args):
        """ログ出力を抑制"""
        pass

    def _set_cors_headers(self):
        """CORSヘッダーを設定"""
        origin = self.headers.get('Origin')

        # 許可リストと正規表現で照合
        if origin and any(regex.match(origin) for regex in ALLOWED_ORIGINS):
            self.send_header('Access-Control-Allow-Origin', origin)
            self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
            self.send_header('Access-Control-Allow-Headers', 'Content-Type')

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

            # レスポンスを先に返す
            self.send_response(200)
            self._set_cors_headers()
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{"status": "ok", "message": "bot.py saved and starting"}')

            # bot.pyを起動
            start_bot()

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

    # デカデカとログ表示
    print("")
    print("=" * 50)
    print("🤖 BOT起動")
    print("=" * 50)
    print("")

    # 新しいプロセスを起動
    python_path = os.path.join('venv', 'Scripts', 'python.exe')
    bot_process = subprocess.Popen(
        [python_path, 'bot.py'],
        stdout=sys.stdout,
        stderr=sys.stderr
    )


def run_server():
    """HTTPサーバーを起動"""
    global server
    try:
        # ポートが被った場合はエラーを出す
        HTTPServer.allow_reuse_address = False

        # サーバー初期化
        server = HTTPServer(('localhost', PORT), BotHandler)
    except OSError as e:
        print(f"既にEDBB Runnerが起動しています。終了してから再実行してください。")
        return False

    # サーバー起動
    server.serve_forever()
    return True


def cleanup():
    """プロセスとサーバーをクリーンアップ"""
    global bot_process, server

    # BOTプロセスを終了
    if bot_process and bot_process.poll() is None:
        bot_process.terminate()
        try:
            bot_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            bot_process.kill()

    # HTTPサーバーを終了
    if server:
        server.shutdown()


def main():
    """メイン処理"""
    # メッセージ表示
    print("準備完了")
    print("EDBBページから▶ボタンを押すことで実行できます。")

    # bot.pyが存在する場合は起動
    if Path('bot.py').exists():
        start_bot()

    # HTTPサーバーを起動（メインスレッドで実行）
    try:
        run_server()
    except KeyboardInterrupt:
        print()  # 改行のみ
    finally:
        cleanup() # Botとサーバーを終了


if __name__ == '__main__':
    main()
