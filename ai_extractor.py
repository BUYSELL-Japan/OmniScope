import os
import json
import base64
import requests
from pathlib import Path
from dotenv import load_dotenv
from openai import OpenAI
from winotify import Notification, audio

# OmniScope の .env を読み込む（TOA_SEARCHER_URL 等）
_env_file = Path(__file__).parent / ".env"
load_dotenv(_env_file)

# TOA Searcher への送信先URL（.env の TOA_SEARCHER_URL を優先、なければ localhost）
TOA_SEARCHER_URL = os.environ.get("TOA_SEARCHER_URL", "http://localhost:3000").rstrip("/")

# OpenAI APIキー（TOA Searcher の openai-api.env からロード）
_openai_env_path = Path(os.environ.get(
    "OPENAI_ENV_PATH",
    r"C:\Users\buyse\OneDrive\デスクトップ\Antigravity\TOA Searcher\openai-api.env"
))
with open(_openai_env_path, 'r', encoding='utf-8') as f:
    api_key = f.read().strip()

client = OpenAI(api_key=api_key)

SCHEMA_PROMPT = """
You are an expert data extractor. Extract product information from the provided screenshot of an eBay item page.
Return ONLY a valid JSON object strictly matching the following schema. Do not include markdown code blocks or any other text.

{
  "jan_code": "string or null",
  "model_number": "string or null",
  "brand": "string or null",
  "category": "string or null",
  "title": "string",
  "price": "number",
  "currency": "string (ISO 4217, e.g. USD)",
  "shipping_cost": "number or null",
  "weight_g": "number or null",
  "dimensions_mm": {"length": number, "width": number, "height": number} or null,
  "condition": "new" | "used_like_new" | "used_good" | "used_acceptable" | "unknown",
  "sold_status": "active" | "sold" | "unknown",
  "sold_date": "ISO8601 string or null"
}
"""

def encode_image(image_path):
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')

def show_notification(title, msg, duration="short", sound=audio.Default):
    try:
        toast = Notification(app_id="OmniScope", title=title, msg=msg, duration=duration)
        toast.set_audio(sound, loop=False)
        toast.show()
    except Exception as e:
        print(f"Notification error: {e}")

def check_connection() -> bool:
    """TOA Searcher への接続確認を行い、Windows 通知で結果を表示する。
    接続失敗でも False を返すだけでアプリ自体は止めない。
    """
    health_url = f"{TOA_SEARCHER_URL}/health"
    print(f"[OmniScope] Checking connection to: {health_url}")
    try:
        res = requests.get(health_url, timeout=5)
        if res.status_code == 200:
            show_notification(
                "TOA Searcher 接続成功 ✅",
                f"接続しました: {TOA_SEARCHER_URL}"
            )
            print(f"[OmniScope] Connection OK: {TOA_SEARCHER_URL}")
            return True
        else:
            show_notification(
                "TOA Searcher 接続エラー ⚠️",
                f"HTTP {res.status_code} が返されました: {TOA_SEARCHER_URL}",
                sound=audio.Mail
            )
            print(f"[OmniScope] Connection failed (HTTP {res.status_code}): {TOA_SEARCHER_URL}")
            return False
    except requests.exceptions.ConnectionError:
        show_notification(
            "TOA Searcher に接続できません ❌",
            f"URLを確認してください: {TOA_SEARCHER_URL}",
            sound=audio.Mail
        )
        print(f"[OmniScope] Connection error (server not reachable): {TOA_SEARCHER_URL}")
        return False
    except requests.exceptions.Timeout:
        show_notification(
            "TOA Searcher 接続タイムアウト ⏱️",
            f"5秒以内に応答がありませんでした: {TOA_SEARCHER_URL}",
            sound=audio.Mail
        )
        print(f"[OmniScope] Connection timeout: {TOA_SEARCHER_URL}")
        return False
    except Exception as e:
        show_notification(
            "接続確認エラー",
            f"予期せぬエラー: {e}",
            sound=audio.Mail
        )
        print(f"[OmniScope] Unexpected error during health check: {e}")
        return False

def extract_and_send(image_path: str, url: str):
    print(f"Processing image: {image_path}")
    print(f"Extracted URL: {url}")
    
    try:
        show_notification("OmniScope", "AIデータ抽出を開始しました...")
        
        base64_image = encode_image(image_path)
        
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": SCHEMA_PROMPT
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": f"Extract data for this product. The page URL is: {url}"
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{base64_image}",
                                "detail": "high"
                            }
                        }
                    ]
                }
            ],
            max_tokens=1000,
            temperature=0.0
        )
        
        usage = response.usage
        print(f"Tokens used: Prompt={usage.prompt_tokens}, Completion={usage.completion_tokens}, Total={usage.total_tokens}")
        # GPT-4o-mini cost: $0.15 / 1M prompt, $0.60 / 1M completion
        cost = (usage.prompt_tokens * 0.15 + usage.completion_tokens * 0.60) / 1000000
        print(f"Estimated Cost: ${cost:.5f}")
        
        result_text = response.choices[0].message.content.strip()
        
        # Markdownコードブロックを削除 (if any)
        if result_text.startswith("```json"):
            result_text = result_text[7:]
        if result_text.endswith("```"):
            result_text = result_text[:-3]
            
        data = json.loads(result_text.strip())
        
        # URLが存在しなければ追加
        data["url"] = url if url else ""
        
        # OmniScopeが撮影したスクリーンショットのパスを記録 (UIでの目視確認用)
        data["screenshot_path"] = image_path
        
        print(f"Extracted Data: {json.dumps(data, indent=2, ensure_ascii=False)}")
        
        # TOA Searcher APIへ送信
        api_url = f"{TOA_SEARCHER_URL}/api/products/import"
        print(f"Sending to: {api_url}")
        res = requests.post(api_url, json=data, timeout=15)
        
        if res.status_code == 200:
            show_notification("保存完了 ✅", f"{data.get('title', '商品')}を保存し、メルカリ検索を開始しました。")
            print("Successfully sent to TOA Searcher.")
        else:
            show_notification("APIエラー", f"保存に失敗しました: {res.text}", sound=audio.Mail)
            print(f"API Error: {res.status_code} - {res.text}")
            
    except requests.exceptions.ConnectionError:
        show_notification("接続エラー", "TOA Searcherのサーバーが起動していません。", sound=audio.Mail)
        print("Error: Could not connect to TOA Searcher API. Is it running?")
    except json.JSONDecodeError as e:
        show_notification("抽出エラー", "JSONのパースに失敗しました。", sound=audio.Mail)
        print(f"JSON Decode Error: {e}\nRaw output: {result_text}")
    except Exception as e:
        show_notification("システムエラー", f"予期せぬエラー: {str(e)}", sound=audio.Mail)
        print(f"Error: {e}")
