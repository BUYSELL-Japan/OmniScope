# OmniScope

**RWS（Search Quality Rating）補助ツール**  
指定モニター上のChromeページをフルページキャプチャし、Gemini APIに直接送信します。

---

## セットアップ

### 1. 依存パッケージのインストール

```powershell
cd OmniScope
pip install -r requirements.txt
playwright install chromium
```

### 2. Chrome を CDP モードで起動

`launch_chrome.bat` をダブルクリックして Chrome を起動します。  
（通常の Chrome を閉じてからこのスクリプトで起動してください）

### 3. OmniScope を起動

```powershell
python omniscope.py
```

---

## 使い方

1. **launch_chrome.bat** で Chrome を起動
2. Chrome で RWS タスクのページを手動で開く
3. OmniScope の **DISP 01/02/03** ボタンで対象モニターを選択
4. **Gemini API Key** を入力して SAVE
5. **CAPTURE** ボタンまたは `Ctrl+Shift+S` でキャプチャ → Gemini に自動送信

---

## ホットキー

| ホットキー | 動作 |
|---|---|
| `Ctrl+Shift+S` | キャプチャ実行 |
| `Ctrl+Shift+1` | モニター1を対象に |
| `Ctrl+Shift+2` | モニター2を対象に |
| `Ctrl+Shift+3` | モニター3を対象に |

---

## 設定ファイル（config.yaml）

| 設定項目 | デフォルト | 説明 |
|---|---|---|
| `chrome.debug_port` | 9222 | CDP ポート |
| `capture.save_locally` | true | ローカルにも保存するか |
| `gemini.model` | gemini-2.0-flash | 使用するモデル |
| `gemini.auto_analyze` | true | キャプチャ後の自動解析 |

---

## ⚠️ 注意事項

- OmniScope は指定モニター上のブラウザの **既存ページ** を撮影するだけです。
- RWS タスクの URL に自動でアクセスすることは **一切ありません**。
- `launch_chrome.bat` なしで起動した Chrome には接続できません。
- ホットキーには管理者権限が必要な場合があります。
