#!/bin/bash
cd "$(dirname "$0")"

# Ctrl+Cで終了した場合は待機せずに終了する
trap 'exit 0' INT

bash ./edbb-runner.sh
EXIT_CODE=$?

# エラー終了時のみ待機する
if [ $EXIT_CODE -ne 0 ] && [ $EXIT_CODE -ne 130 ]; then
    read -p "Press enter to continue"
fi
