@echo off
:: ─────────────────────────────────────────────────────────────────────────
:: launch_chrome.bat — OmniScope 用 Chrome 起動スクリプト
::
:: 通常のChromeと異なり「--remote-debugging-port=9222」オプション付きで起動。
:: これにより OmniScope が CDP (Chrome DevTools Protocol) で接続できるようになります。
::
:: ★ 使い方：
::   このファイルをダブルクリックするだけ。
::   以降は通常通りChromeを使ってRWSタスクを実行してください。
::
:: ★ 注意：
::   既に Chrome が起動している場合は一旦すべて閉じてからこのスクリプトを実行してください。
:: ─────────────────────────────────────────────────────────────────────────

echo [OmniScope] Chrome を CDP モードで起動しています...
echo [OmniScope] ポート: 9222

:: Chrome の実行ファイルパス（環境に合わせて変更してください）
set CHROME_PATH="C:\Program Files\Google\Chrome\Application\chrome.exe"

:: インストール先が異なる場合は以下のパスも試してください
if not exist %CHROME_PATH% (
    set CHROME_PATH="C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
)

:: Chrome 起動オプション:
::   --remote-debugging-port=9222  : OmniScope が接続する CDP ポート
::   --restore-last-session        : 前回のタブを復元
::   --no-first-run                : 初回起動ダイアログを非表示
start "" %CHROME_PATH% ^
    --remote-debugging-port=9222 ^
    --restore-last-session ^
    --no-first-run

echo [OmniScope] Chrome が起動しました。通常通りRWSタスクを開始してください。
echo [OmniScope] 準備ができたら OmniScope を起動してください。
timeout /t 3 >nul
