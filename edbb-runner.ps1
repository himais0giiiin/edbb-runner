# ============================================
# EDBB Runner - 自動セットアップスクリプト
# ============================================

# コマンドライン引数
param(
    [switch]$dev
)

# UTF-8エンコーディング設定
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

# Python実行情報
$script:PythonExecutable = $null
$script:PythonBaseArgs = @()

# ============================================
# 関数定義
# ============================================

# Python実行コマンドを解決する関数（Windowsストアのダミー回避）
function Resolve-PythonCommand {
    try {
        # Windowsストアが開くだけの「python」コマンドを無視するため--versionを指定
        $version = & python --version 2>&1
        if ($LASTEXITCODE -eq 0 -and $version -match "Python") {
            $script:PythonExecutable = "python"
            $script:PythonBaseArgs = @()
            return $true
        }
    }
    catch {
        # fallbackに進む
    }

    try {
        # pythonコマンドが使えない環境ではpyランチャーを試す
        $version = & py -3 --version 2>&1
        if ($LASTEXITCODE -eq 0 -and $version -match "Python") {
            $script:PythonExecutable = "py"
            $script:PythonBaseArgs = @("-3")
            return $true
        }
    }
    catch {
        # 何もしない
    }

    $script:PythonExecutable = $null
    $script:PythonBaseArgs = @()
    return $false
}

# Pythonが使えるかチェックする関数
function Test-PythonInstalled {
    return Resolve-PythonCommand
}

# 解決済みコマンドでPythonを実行する関数
function Invoke-Python {
    param(
        [Parameter(ValueFromRemainingArguments = $true)]
        [string[]]$Arguments
    )

    if (-not $script:PythonExecutable) {
        if (-not (Resolve-PythonCommand)) {
            throw "Python command is not available."
        }
    }

    & $script:PythonExecutable @($script:PythonBaseArgs + $Arguments)
}

# ============================================
# ヘッダー表示
# ============================================

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "EDBB Runner v1.0.0" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# ============================================
# [1/3] Python環境の確認とインストール
# ============================================
if (Test-PythonInstalled) {
    Write-Host "[1/3] Python: インストール済み" -ForegroundColor Green
}
else {
    Write-Host "[1/3] Python: インストール中..." -ForegroundColor Yellow
    Write-Host "[1/3] Python: wingetを使用してPython 3.12をインストールします..." -ForegroundColor Gray

    winget install Python.Python.3.12 --accept-package-agreements --accept-source-agreements
    $wingetExitCode = $LASTEXITCODE

    Write-Host "[1/3] Python: インストール完了、環境変数を更新中..." -ForegroundColor Gray

    # 環境変数を再読み込み
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")

    # Pythonが使えるか再確認
    if (-not (Test-PythonInstalled)) {
        if ($wingetExitCode -ne 0) {
            Write-Host "[1/3] Python: エラー - wingetでの処理に失敗し、Pythonコマンドも利用できません" -ForegroundColor Red
            Write-Host "[1/3] Python: 手動で https://www.python.org/downloads/ からインストールしてください" -ForegroundColor Gray
            Read-Host "Enterキーを押して終了"
            exit 1
        }

        Write-Host "[1/3] Python: 環境変数の更新に時間がかかっています" -ForegroundColor Yellow
        Write-Host "[1/3] Python: このウィンドウを閉じて、再度edbb-runnerを起動.batを実行してください" -ForegroundColor Gray
        Read-Host "Enterキーを押して終了"
        exit 0
    }

    Write-Host "[1/3] Python: 完了" -ForegroundColor Green
}

# ============================================
# [2/3] 仮想環境の作成とアクティベート
# ============================================
if (-not (Test-Path "venv")) {
    Write-Host "[2/3] venv: 作成中..." -ForegroundColor Yellow
    Invoke-Python -m venv venv --upgrade-deps

    if ($LASTEXITCODE -ne 0) {
        Write-Host "[2/3] venv: エラー - 仮想環境の作成に失敗しました" -ForegroundColor Red
        Read-Host "Enterキーを押して終了"
        exit 1
    }

    Write-Host "[2/3] venv: 作成完了" -ForegroundColor Green
}

# 仮想環境をアクティベート
& "venv\Scripts\Activate.ps1"
Write-Host "[2/3] venv: アクティベート済み" -ForegroundColor Green

# ============================================
# [3/3] パッケージのインストール確認
# ============================================
$null = Invoke-Python -c "import discord" 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "[3/3] discord.py: インストール中..." -ForegroundColor Yellow
    pip install discord.py[voice] --quiet
    Write-Host "[3/3] discord.py: 完了" -ForegroundColor Green
}
else {
    Write-Host "[3/3] discord.py: インストール済み" -ForegroundColor Green
}

# ============================================
# Discord BOTトークンの確認
# ============================================

# .envファイルが存在しない、またはトークンが未設定の場合
$needsToken = $false
if (-not (Test-Path ".env")) {
    $needsToken = $true
}
else {
    $envContent = Get-Content ".env" -Raw -ErrorAction SilentlyContinue
    if (-not ($envContent -match "DISCORD_TOKEN=.+")) {
        $needsToken = $true
    }
}

if ($needsToken) {
    Write-Host ""
    Write-Host "Discord BOTトークンを入力してください:" -ForegroundColor Yellow
    Write-Host "(Discord Developer Portalで取得したトークン)" -ForegroundColor Gray
    Write-Host ""

    # トークンが有効になるまでループ
    $validToken = $false
    while (-not $validToken) {
        $botToken = Read-Host "トークン"

        if (-not $botToken) {
            Write-Host "× トークンを入力してください" -ForegroundColor Red
            Write-Host ""
            continue
        }

        # Discord APIでトークンの有効性を確認
        Write-Host "トークンを検証中..." -ForegroundColor Gray
        try {
            $headers = @{
                "Authorization" = "Bot $botToken"
            }
            $response = Invoke-RestMethod -Uri "https://discord.com/api/v10/users/@me" -Headers $headers -Method Get -ErrorAction Stop

            # トークンが有効
            Write-Host "✓ トークンが有効です (BOT: $($response.username)#$($response.discriminator))" -ForegroundColor Green

            # .envファイルに保存
            "DISCORD_TOKEN=$botToken" | Out-File -FilePath ".env" -Encoding utf8
            Write-Host "✓ トークンを保存しました" -ForegroundColor Green
            $validToken = $true
        }
        catch {
            # トークンが無効
            Write-Host "× トークンが無効です。再度入力してください" -ForegroundColor Red
            Write-Host ""
        }
    }
}

# ============================================
# 環境変数の読み込み
# ============================================

# .envファイルから環境変数を読み込み
if (Test-Path ".env") {
    Get-Content ".env" | Where-Object {
        # コメント行（#で始まる）と空行を無視
        $_ -notmatch '^\s*#' -and $_ -notmatch '^\s*$'
    } | ForEach-Object {
        if ($_ -match '^([^=]+)=(.*)$') {
            $name = $matches[1].Trim()
            $value = $matches[2].Trim()
            # プロセス環境変数として設定
            [System.Environment]::SetEnvironmentVariable($name, $value, "Process")
        }
    }
}

# ============================================
# Bot起動
# ============================================

# -dev引数がある場合はHTTPサーバー付きで起動、ない場合はbot.pyのみ起動
if ($dev) {
    Invoke-Python edbb-runner.py
}
else {
    Write-Host ""
    Write-Host "=================================================="
    Write-Host "🤖 BOT起動"
    Write-Host "=================================================="
    Write-Host ""
    Invoke-Python bot.py
}
