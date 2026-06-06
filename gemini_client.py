"""
gemini_client.py — Gemini API 連携モジュール

google-genai（新SDK）を使用してスクリーンショットのバイト列を
直接 Gemini Vision モデルに送信します。

ファイルへの保存なしにメモリ上のデータをそのまま送信できるため、
キャプチャ → 即時解析 のワークフローが実現できます。

使用モデル候補:
    gemini-2.0-flash       : 高速・コスト効率良（デフォルト）
    gemini-2.0-flash-lite  : さらに高速・低コスト
    gemini-2.5-pro-preview : 最高精度・複雑な解析向け
    gemini-1.5-flash-latest: バランス型
"""

from __future__ import annotations

import io
from typing import Optional, Callable

from google import genai
from google.genai import types
from PIL import Image


class GeminiClient:
    """
    Google Gemini API クライアント（google-genai 新SDK版）

    スクリーンショットのバイト列を受け取り、
    Gemini Vision モデルに直接送信してテキスト解析結果を返します。
    """

    # 利用可能なモデルの一覧（UIのドロップダウンに表示する）
    AVAILABLE_MODELS: list[str] = [
        "gemini-2.0-flash",
        "gemini-2.0-flash-lite",
        "gemini-2.5-pro-preview-06-05",
        "gemini-1.5-flash-latest",
        "gemini-1.5-pro-latest",
    ]

    def __init__(
        self,
        api_key: str,
        model_name: str = "gemini-2.0-flash",
    ):
        self.api_key    = api_key
        self.model_name = model_name
        self._client    = genai.Client(api_key=api_key)

    def update_api_key(self, api_key: str) -> None:
        """API キーを更新して再初期化"""
        self.api_key = api_key
        self._client = genai.Client(api_key=api_key)

    def update_model(self, model_name: str) -> None:
        """使用するモデルを変更"""
        self.model_name = model_name

    def analyze(
        self,
        screenshot_bytes: bytes,
        prompt: str,
        system_prompt: Optional[str] = None,
        status_cb: Optional[Callable[[str], None]] = None,
    ) -> str:
        """
        スクリーンショットを Gemini に送信して解析結果を返す

        ファイルへの保存は不要。
        bytes → PIL Image → Gemini API の流れで直接メモリ上から送信。

        Args:
            screenshot_bytes: キャプチャした PNG のバイト列
            prompt:           Gemini への質問・指示テキスト
            system_prompt:    システムプロンプト（RWSガイドライン等）
            status_cb:        進捗メッセージのコールバック

        Returns:
            Gemini の応答テキスト
        """
        def log(msg: str) -> None:
            if status_cb:
                status_cb(msg)

        log("画像を Gemini API に送信中...")

        # ─── バイト列 → PIL Image ────────────────────────────────────
        # google-genai は PIL Image および bytes を直接受け付けるため、
        # 一時ファイルなしで送信できる
        image = Image.open(io.BytesIO(screenshot_bytes))

        # ─── コンテンツの組み立て ─────────────────────────────────────
        # [テキストプロンプト, 画像] の順でマルチモーダル入力を構築
        contents = [prompt, image]

        # ─── システムプロンプトの設定（任意） ───────────────────────
        # RWSガイドラインをシステムプロンプトとして設定することで、
        # Gemini に評価コンテキストを与えられる
        config = None
        if system_prompt and system_prompt.strip():
            config = types.GenerateContentConfig(
                system_instruction=system_prompt.strip(),
            )

        # ─── Gemini に送信 ────────────────────────────────────────────
        if config:
            response = self._client.models.generate_content(
                model=self.model_name,
                contents=contents,
                config=config,
            )
        else:
            response = self._client.models.generate_content(
                model=self.model_name,
                contents=contents,
            )

        log("Gemini 解析完了")
        return response.text

    @staticmethod
    def quick_validate(api_key: str) -> bool:
        """
        API キーの形式をクイックチェック（ネットワーク接続なし）

        完全な検証は初回 API 呼び出し時に自動で行われる。
        """
        return (
            isinstance(api_key, str)
            and len(api_key) > 30
            and api_key.startswith("AI")
        )
