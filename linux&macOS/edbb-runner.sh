#!/bin/bash
# ============================================
# EDBB Runner - 自動セットアップスクリプト (Linux/macOS)
# ============================================

# スクリプトのディレクトリへ移動
cd "$(dirname "$0")"

# 引数パース
DEV_MODE=0
for arg in "$@"; do
    if [ "$arg" == "--dev" ] || [ "$arg" == "-dev" ]; then
        DEV_MODE=1
    fi
done

echo -e "\e[36m========================================\e[0m"
echo -e "\e[36mEDBB Runner v1.0.0 (Linux/macOS)\e[0m"
echo -e "\e[36m========================================\e[0m"
echo ""

# ============================================
# [1/3] Python環境の確認
# ============================================
PYTHON_CMD=""
if command -v python3 &>/dev/null; then
    PYTHON_CMD="python3"
elif command -v python &>/dev/null; then
    PYTHON_CMD="python"
else
    echo -e "\e[31m[1/3] Python: エラー - Pythonがインストールされていません\e[0m"
    echo -e "\e[90m[1/3] 手動でPython 3をインストールしてください (例: sudo apt install python3 python3-venv)\e[0m"
    exit 1
fi

echo -e "\e[32m[1/3] Python: インストール済み ($PYTHON_CMD)\e[0m"

# ============================================
# [2/3] 仮想環境の作成とアクティベート
# ============================================
if [ ! -d "venv" ]; then
    echo -e "\e[33m[2/3] venv: 作成中...\e[0m"
    $PYTHON_CMD -m venv venv
    if [ $? -ne 0 ]; then
        echo -e "\e[31m[2/3] venv: エラー - 仮想環境の作成に失敗しました。python3-venvパッケージが必要な場合があります。\e[0m"
        exit 1
    fi
    echo -e "\e[32m[2/3] venv: 作成完了\e[0m"
fi

source venv/bin/activate
echo -e "\e[32m[2/3] venv: アクティベート済み\e[0m"

# ============================================
# [3/3] パッケージのインストール確認
# ============================================
if ! python -c "import discord" &> /dev/null; then
    echo -e "\e[33m[3/3] discord.py: インストール中...\e[0m"
    pip install "discord.py[voice]" --quiet
    echo -e "\e[32m[3/3] discord.py: 完了\e[0m"
else
    echo -e "\e[32m[3/3] discord.py: インストール済み\e[0m"
fi

# ============================================
# Discord BOTトークンの確認
# ============================================
NEEDS_TOKEN=0
if [ ! -f ".env" ]; then
    NEEDS_TOKEN=1
else
    if ! grep -q "^DISCORD_TOKEN=.*" .env; then
        NEEDS_TOKEN=1
    fi
fi

if [ $NEEDS_TOKEN -eq 1 ]; then
    echo ""
    echo -e "\e[33mDiscord BOTトークンを入力してください:\e[0m"
    echo -e "\e[90m(Discord Developer Portalで取得したトークン)\e[0m"
    echo ""

    VALID_TOKEN=0
    while [ $VALID_TOKEN -eq 0 ]; do
        read -p "トークン: " BOT_TOKEN
        if [ -z "$BOT_TOKEN" ]; then
            echo -e "\e[31m× トークンを入力してください\e[0m\n"
            continue
        fi

        echo -e "\e[90mトークンを検証中...\e[0m"
        # curlでDiscord APIを叩いて検証
        HTTP_RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bot $BOT_TOKEN" https://discord.com/api/v10/users/@me)

        if [ "$HTTP_RESPONSE" == "200" ]; then
            echo -e "\e[32m✓ トークンが有効です\e[0m"
            echo "DISCORD_TOKEN=$BOT_TOKEN" > .env
            echo -e "\e[32m✓ トークンを保存しました\e[0m"
            VALID_TOKEN=1
        else
            echo -e "\e[31m× トークンが無効です。再度入力してください\e[0m\n"
        fi
    done
fi

# ============================================
# 環境変数の読み込み
# ============================================
if [ -f ".env" ]; then
    export $(grep -v '^#' .env | xargs)
fi

# ============================================
# Bot起動
# ============================================

# 子プロセスをキルするための関数
cleanup() {
    echo -e "\n\e[33m終了シグナルを受信しました。プロセスを終了しています...\e[0m"
    if [ -n "$CHILD_PID" ]; then
        kill -TERM "$CHILD_PID" 2>/dev/null
        wait "$CHILD_PID" 2>/dev/null
    fi
    exit 0
}

# SIGINT(Ctrl+C)とSIGTERMをトラップしてcleanup()を実行
trap cleanup SIGINT SIGTERM

if [ $DEV_MODE -eq 1 ]; then
    python edbb-runner.py &
    CHILD_PID=$!
    wait $CHILD_PID
else
    echo ""
    echo "=================================================="
    echo "🤖 BOT起動"
    echo "=================================================="
    echo ""
    python bot.py &
    CHILD_PID=$!
    wait $CHILD_PID
fi
