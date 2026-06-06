"""
omniscope.py — OmniScope メインアプリケーション

スタイル: 青ネオン / サイバーパンク HUD テーマ
GUI フレームワーク: tkinter（標準ライブラリ）
画像プレビュー: Pillow（PIL）

起動方法:
    python omniscope.py

ホットキー:
    Ctrl+Shift+S     : キャプチャ実行
    Ctrl+Shift+1/2/3 : 対象モニター切り替え
"""

from __future__ import annotations

import math
import threading
import sys
import os
import io
import time
import re
import traceback
from pathlib import Path
from datetime import datetime
from typing import Optional, Callable
import tkinter as tk
from tkinter import scrolledtext

# ─── サードパーティ ──────────────────────────────────────────────────
try:
    from PIL import Image, ImageTk
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

try:
    import keyboard as kb
    KEYBOARD_AVAILABLE = True
except ImportError:
    KEYBOARD_AVAILABLE = False

try:
    from winotify import Notification, audio
    TOAST_AVAILABLE = True
except ImportError:
    TOAST_AVAILABLE = False

import yaml

# ─── OmniScope 内部モジュール ──────────────────────────────────────
from engine import capture_sync, check_connection_sync, CaptureResult
from gemini_client import GeminiClient
from monitor import get_all_monitors, MonitorInfo

# ══════════════════════════════════════════════════════════════════════
#  カラーパレット — 青ネオン・サイバーパンクテーマ
# ══════════════════════════════════════════════════════════════════════
C = {
    # 背景系（暗い青黒）
    "bg":         "#020912",   # 最暗部（メイン背景）
    "bg_panel":   "#030e1f",   # パネル背景
    "bg_card":    "#06152a",   # カード背景
    "bg_card2":   "#091d3a",   # ライトカード（ホバー等）
    "bg_active":  "#041230",   # アクティブ状態の背景

    # ボーダー系（外→内で輝度が上がりグロー感を演出）
    "border_1":   "#020c22",   # 最外周ボーダー（ほぼ背景色）
    "border_2":   "#063060",   # 中間ボーダー
    "border_3":   "#0a4888",   # 内側ボーダー

    # ネオンカラー
    "neon":       "#00c8ff",   # メインネオンブルー（プライマリ）
    "neon2":      "#007acc",   # セカンダリブルー
    "cyan":       "#00fff0",   # シアン（ホバー・アクティブ強調）
    "glow_bg":    "#001428",   # グローエフェクト背景

    # テキスト
    "text":       "#8ac8ee",   # メインテキスト
    "text_dim":   "#2a5a88",   # 薄いテキスト（ラベル等）
    "text_bright":"#c8e8ff",   # 明るいテキスト（強調）
    "text_cyan":  "#00fff0",   # シアンテキスト（アクティブ時）

    # ステータスインジケーター
    "success":    "#00ff88",   # 成功・接続済み（緑）
    "error":      "#ff2055",   # エラー・未接続（赤）
    "warning":    "#ffaa00",   # 警告・注意（アンバー）
    "idle":       "#2a5a88",   # アイドル（薄青）
}

# ─── フォント ─────────────────────────────────────────────────────────
# Consolas: 等幅フォント、サイバーパンクHUDに最適
FM = "Consolas"
FONT_TITLE  = (FM, 16, "bold")
FONT_HEAD   = (FM, 10, "bold")
FONT_BODY   = (FM,  9)
FONT_SMALL  = (FM,  8)
FONT_MONO   = (FM, 10)
FONT_BIG    = (FM, 18, "bold")
FONT_STATUS = (FM,  8)
FONT_LABEL  = (FM,  8, "bold")

# ─── ウィンドウサイズ ─────────────────────────────────────────────────
W_WIDTH  = 470
W_HEIGHT = 860

# ─── 設定ファイルパス ─────────────────────────────────────────────────
BASE_DIR    = Path(__file__).parent
CONFIG_PATH = BASE_DIR / "config.yaml"

# ══════════════════════════════════════════════════════════════════════
#  設定管理
# ══════════════════════════════════════════════════════════════════════

def _load_config() -> dict:
    """config.yaml を読み込み、デフォルト値とマージして返す"""
    defaults = {
        "chrome":   {"debug_host": "127.0.0.1", "debug_port": 9222},
        "capture":  {"output_dir": "screenshots", "save_locally": True},
        "monitors": {"auto_detect": True, "default": 2},
        "hotkeys":  {
            "capture":   "ctrl+shift+s",
            "monitor_1": "ctrl+shift+1",
            "monitor_2": "ctrl+shift+2",
            "monitor_3": "ctrl+shift+3",
        },
        "gemini": {
            "model":          "gemini-2.0-flash",
            "api_key":        "",
            "auto_analyze":   True,
            "default_prompt": (
                "このWebページのスクリーンショットを分析してください。"
                "レイアウト、コンテンツ、主要な情報を詳しく説明してください。"
            ),
            "system_prompt":  "",
        },
    }
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                loaded = yaml.safe_load(f) or {}
            for key, val in loaded.items():
                if isinstance(val, dict) and key in defaults:
                    defaults[key].update(val)
                else:
                    defaults[key] = val
        except Exception:
            pass
    return defaults


def _save_config(cfg: dict) -> None:
    """設定を config.yaml に書き戻す"""
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False)
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════
#  カスタムウィジェット群
# ══════════════════════════════════════════════════════════════════════

def _neon_border(canvas: tk.Canvas, x1: int, y1: int, x2: int, y2: int,
                 color: str = None, fill: str = None) -> None:
    """
    Canvas に3層のネオングローボーダーを描画するユーティリティ

    外→中→内の順に輝度が上がることで、発光しているように見える。
    """
    col = color or C["neon"]
    bg  = fill  or C["bg_card"]
    # 最外周（薄い）
    canvas.create_rectangle(x1,   y1,   x2,   y2,   outline=C["border_2"], fill=bg)
    # 中間
    canvas.create_rectangle(x1+2, y1+2, x2-2, y2-2, outline=C["border_3"], fill="")
    # 最内周（明るい）
    canvas.create_rectangle(x1+4, y1+4, x2-4, y2-4, outline=col, fill="")


def _corner_accents(canvas: tk.Canvas, x1: int, y1: int, x2: int, y2: int,
                    color: str = None, length: int = 10, width: int = 2) -> None:
    """
    Canvas に四隅のコーナーアクセントを描画するユーティリティ

    サイバーパンク系UIでよく使われる「角だけ枠線」スタイル。
    """
    col = color or C["neon"]
    # 左上
    canvas.create_line(x1, y1, x1 + length, y1, fill=col, width=width)
    canvas.create_line(x1, y1, x1, y1 + length, fill=col, width=width)
    # 右上
    canvas.create_line(x2 - length, y1, x2, y1, fill=col, width=width)
    canvas.create_line(x2, y1, x2, y1 + length, fill=col, width=width)
    # 左下
    canvas.create_line(x1, y2, x1 + length, y2, fill=col, width=width)
    canvas.create_line(x1, y2 - length, x1, y2, fill=col, width=width)
    # 右下
    canvas.create_line(x2 - length, y2, x2, y2, fill=col, width=width)
    canvas.create_line(x2, y2 - length, x2, y2, fill=col, width=width)


class MonitorButton(tk.Canvas):
    """
    モニター選択ボタン（Canvas 実装）

    通常: 薄い青ボーダー・暗い背景
    ホバー: ネオンブルーボーダー + グロー背景
    選択中: 塗りつぶし + シアンテキスト + 下部インジケーターライン
    """

    BTN_W, BTN_H = 130, 72

    def __init__(self, parent: tk.Widget, monitor_num: int,
                 on_select: Callable[[int], None], **kwargs):
        super().__init__(
            parent,
            width=self.BTN_W, height=self.BTN_H,
            bg=C["bg"], highlightthickness=0,
            cursor="hand2",
            **kwargs,
        )
        self.monitor_num = monitor_num
        self.on_select   = on_select
        self.selected    = False
        self._hovering   = False

        self.bind("<Enter>",    self._hover_on)
        self.bind("<Leave>",    self._hover_off)
        self.bind("<Button-1>", self._click)
        self._draw()

    def set_selected(self, selected: bool) -> None:
        self.selected = selected
        self._draw()

    def _hover_on(self, _) -> None:
        self._hovering = True
        self._draw()

    def _hover_off(self, _) -> None:
        self._hovering = False
        self._draw()

    def _click(self, _) -> None:
        self.on_select(self.monitor_num)

    def _draw(self) -> None:
        self.delete("all")
        w, h = self.BTN_W, self.BTN_H

        # 状態によって色を切り替え
        if self.selected:
            bg       = C["bg_active"]
            bdr      = C["cyan"]
            txt_col  = C["cyan"]
            sub_col  = C["neon"]
            show_bar = True
        elif self._hovering:
            bg       = C["glow_bg"]
            bdr      = C["neon"]
            txt_col  = C["neon"]
            sub_col  = C["text"]
            show_bar = False
        else:
            bg       = C["bg_card"]
            bdr      = C["border_3"]
            txt_col  = C["text_dim"]
            sub_col  = C["text_dim"]
            show_bar = False

        # 背景 + 外枠
        self.create_rectangle(0, 0, w - 1, h - 1,
                               outline=C["border_2"], fill=bg)
        # 内枠
        self.create_rectangle(2, 2, w - 3, h - 3,
                               outline=bdr, fill="")

        # コーナーアクセント
        _corner_accents(self, 2, 2, w - 3, h - 3, color=bdr, length=8)

        # メインテキスト: DISP 01 など
        self.create_text(
            w // 2, h // 2 - 10,
            text=f"DISP {self.monitor_num:02d}",
            font=FONT_HEAD, fill=txt_col,
        )
        # サブテキスト
        self.create_text(
            w // 2, h // 2 + 10,
            text="▸ SELECT" if not self.selected else "● ACTIVE",
            font=FONT_SMALL, fill=sub_col,
        )

        # 選択時の下部インジケーターライン（ネオングロー風）
        if show_bar:
            self.create_line(8, h - 5, w - 9, h - 5, fill=C["cyan"], width=2)
            self.create_line(8, h - 7, w - 9, h - 7, fill=C["neon2"], width=1)


class CaptureButton(tk.Canvas):
    """
    メインキャプチャボタン（大型・パルスアニメーション付き）

    アイドル時にボーダーがゆっくりパルス（点滅）する。
    ホバー時にシアン色にハイライト。
    実行中は「CAPTURING...」表示でインタラクションを無効化。
    """

    BTN_W, BTN_H = 440, 64

    def __init__(self, parent: tk.Widget, command: Callable, **kwargs):
        super().__init__(
            parent,
            width=self.BTN_W, height=self.BTN_H,
            bg=C["bg"], highlightthickness=0,
            cursor="hand2",
            **kwargs,
        )
        self.command   = command
        self.busy      = False
        self._hovering = False
        self._phase    = 0.0   # アニメーションフェーズ（0〜2π）

        self.bind("<Enter>",    lambda _: self._set_hover(True))
        self.bind("<Leave>",    lambda _: self._set_hover(False))
        self.bind("<Button-1>", self._click)

        self._draw()
        self._tick()

    def set_busy(self, busy: bool) -> None:
        self.busy = busy
        self._draw()

    def _set_hover(self, state: bool) -> None:
        self._hovering = state
        self._draw()

    def _click(self, _) -> None:
        if not self.busy:
            self.command()

    def _tick(self) -> None:
        """50ms ごとにパルスフェーズを進めて再描画"""
        if not self.busy and not self._hovering:
            self._phase += 0.06
            self._draw()
        self.after(50, self._tick)

    def _draw(self) -> None:
        self.delete("all")
        w, h = self.BTN_W, self.BTN_H

        if self.busy:
            bg    = C["bg_active"]
            bdr   = C["neon2"]
            label = "  CAPTURING...  "
            tcol  = C["text"]
        elif self._hovering:
            bg    = C["glow_bg"]
            bdr   = C["cyan"]
            label = "  [ CAPTURE ]  "
            tcol  = C["cyan"]
        else:
            # パルス：sin 波でボーダー色を変化させる
            t   = (math.sin(self._phase) + 1) / 2  # 0〜1
            # border_3 と neon の間を補間
            bg  = C["bg_card"]
            bdr = C["neon"]
            label = "  [ CAPTURE ]  "
            tcol  = C["neon"]

        # 3層ボーダー
        self.create_rectangle(0, 0, w - 1, h - 1,
                               outline=C["border_2"], fill=bg)
        self.create_rectangle(2, 2, w - 3, h - 3,
                               outline=C["border_3"], fill="")
        self.create_rectangle(5, 5, w - 6, h - 6,
                               outline=bdr, fill="")

        # コーナーアクセント
        _corner_accents(self, 5, 5, w - 6, h - 6, color=bdr, length=14, width=2)

        # ラベル
        self.create_text(w // 2, h // 2,
                         text=label, font=FONT_BIG, fill=tcol)


class StatusLight(tk.Canvas):
    """LED インジケーター（丸いドット + ラベルテキスト）"""

    def __init__(self, parent: tk.Widget, label: str, **kwargs):
        super().__init__(
            parent, width=200, height=22,
            bg=C["bg_panel"], highlightthickness=0,
            **kwargs,
        )
        self.label = label
        self._color = C["idle"]
        self._text  = "UNKNOWN"
        self._draw()

    def set_status(self, color: str, text: str) -> None:
        self._color = color
        self._text  = text
        self._draw()

    def _draw(self) -> None:
        self.delete("all")
        # LED ドット
        r = 5
        self.create_oval(4, 6, 4 + r * 2, 6 + r * 2,
                         fill=self._color, outline=self._color)
        # ラベル + ステータステキスト
        self.create_text(
            20, 11,
            text=f"{self.label}: {self._text}",
            font=FONT_SMALL, fill=C["text"],
            anchor="w",
        )


class NeonEntry(tk.Frame):
    """ネオンスタイルのテキスト入力フィールド"""

    def __init__(self, parent: tk.Widget, show: str = "", width: int = 30,
                 **kwargs):
        super().__init__(parent, bg=C["bg_panel"], **kwargs)

        # ボーダーCanvas（グロー枠）
        self._canvas = tk.Canvas(
            self, height=28, bg=C["bg"], highlightthickness=0,
        )
        self._canvas.pack(fill="x")

        # 実際の Entry ウィジェット
        self.entry = tk.Entry(
            self._canvas,
            show=show,
            bg=C["bg_card"],
            fg=C["text"],
            insertbackground=C["neon"],
            selectbackground=C["border_3"],
            selectforeground=C["cyan"],
            relief="flat",
            bd=0,
            font=FONT_BODY,
            width=width,
        )
        self._entry_window = self._canvas.create_window(
            3, 3, anchor="nw", window=self.entry,
        )

        self._canvas.bind("<Configure>", self._on_resize)
        self.entry.bind("<FocusIn>",  self._focus_in)
        self.entry.bind("<FocusOut>", self._focus_out)
        self._focused = False
        self._draw_border()

    def _on_resize(self, e) -> None:
        w = e.width
        self._canvas.itemconfig(self._entry_window, width=w - 6)
        self._draw_border()

    def _focus_in(self, _) -> None:
        self._focused = True
        self._draw_border()

    def _focus_out(self, _) -> None:
        self._focused = False
        self._draw_border()

    def _draw_border(self) -> None:
        self._canvas.delete("border")
        w = self._canvas.winfo_width() or 200
        col = C["neon"] if self._focused else C["border_3"]
        self._canvas.create_rectangle(
            0, 0, w - 1, 27,
            outline=col, fill=C["bg_card"], tags="border",
        )
        self._canvas.create_rectangle(
            1, 1, w - 2, 26,
            outline=C["border_2"], fill="", tags="border",
        )

    def get(self) -> str:
        return self.entry.get()

    def set(self, value: str) -> None:
        self.entry.delete(0, "end")
        self.entry.insert(0, value)

    def delete(self, first, last=None) -> None:
        self.entry.delete(first, last)

    def insert(self, index, string: str) -> None:
        self.entry.insert(index, string)


# ══════════════════════════════════════════════════════════════════════
#  セクションヘッダー描画ユーティリティ
# ══════════════════════════════════════════════════════════════════════

def _section_header(parent: tk.Widget, text: str) -> tk.Canvas:
    """セクションの区切りヘッダー（横線 + タイトル）を作成して返す"""
    c = tk.Canvas(parent, height=22, bg=C["bg_panel"],
                  highlightthickness=0)
    c.pack(fill="x", padx=10, pady=(12, 4))

    def _draw(e=None):
        w = c.winfo_width() or 440
        c.delete("all")
        # ラベルテキスト
        c.create_text(0, 11, text=f"▸ {text}", font=FONT_HEAD,
                      fill=C["neon"], anchor="w")
        # 右側の横線
        txt_w = len(text) * 7 + 20
        c.create_line(txt_w, 11, w - 2, 11, fill=C["border_3"], width=1)

    c.bind("<Configure>", _draw)
    return c


# ══════════════════════════════════════════════════════════════════════
#  メインアプリケーションクラス
# ══════════════════════════════════════════════════════════════════════

class OmniScopeApp:
    """
    OmniScope メインアプリケーション

    tkinter ベースのGUI。カスタムタイトルバー（overrideredirect=True）を
    使用して完全なネオンテーマを実現する。
    """

    def __init__(self):
        # ─── 設定読み込み ────────────────────────────────────────────
        self.cfg = _load_config()

        # ─── 状態変数 ────────────────────────────────────────────────
        self.target_monitor: int        = self.cfg["monitors"]["default"]
        self.monitors: list[MonitorInfo] = get_all_monitors()
        self._gemini_client: Optional[GeminiClient] = None
        self._last_result: Optional[CaptureResult]  = None
        self._busy         = False           # キャプチャ中フラグ
        self._chrome_ok    = False           # Chrome接続状態
        self._drag_x = self._drag_y = 0     # ウィンドウドラッグ用

        # ─── ルートウィンドウ ─────────────────────────────────────────
        self.root = tk.Tk()
        self.root.title("OmniScope")
        self.root.geometry(f"{W_WIDTH}x{W_HEIGHT}")
        self.root.resizable(False, False)
        self.root.configure(bg=C["bg"])

        # カスタムタイトルバー（ボーダーレス）にするため
        # overrideredirect を使用
        self.root.overrideredirect(True)

        # ウィンドウを中央付近に配置
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x  = (sw - W_WIDTH)  // 2
        y  = (sh - W_HEIGHT) // 2
        self.root.geometry(f"{W_WIDTH}x{W_HEIGHT}+{x}+{y}")

        # 最前面表示（RWS作業中に他のウィンドウに隠れないように）
        self.root.attributes("-topmost", True)

        # ─── UI 構築 ─────────────────────────────────────────────────
        self._build_ui()

        # ─── 初期化処理（バックグラウンド） ──────────────────────────
        self._check_chrome_async()

        # Gemini クライアント初期化（API キーがあれば）
        saved_key = self.cfg["gemini"].get("api_key", "")
        if saved_key:
            self._api_key_entry.set(saved_key)
            self._init_gemini_client(saved_key)

        # プロンプト・システムプロンプトを設定から復元
        self._prompt_text.insert("end",
            self.cfg["gemini"].get("default_prompt", ""))
        self._system_prompt_text.insert("end",
            self.cfg["gemini"].get("system_prompt", ""))

        # Auto-analyze トグルを設定から復元
        self._auto_analyze_var.set(self.cfg["gemini"].get("auto_analyze", True))

        # ─── グローバルホットキー登録 ─────────────────────────────────
        self._register_hotkeys()

        # ─── スキャンラインアニメーション ─────────────────────────────
        self._scanline_y     = 0
        self._scanline_phase = 0.0
        self._animate_scanline()

    # ──────────────────────────────────────────────────────────────────
    # UI 構築
    # ──────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        """全UIコンポーネントを構築する"""

        # ─── カスタムタイトルバー ──────────────────────────────────────
        self._build_titlebar()

        # ─── スクロール可能なメインコンテンツエリア ───────────────────
        # 外枠キャンバス（ウィンドウ全体のネオンボーダー）
        self._outer_canvas = tk.Canvas(
            self.root, bg=C["bg"],
            highlightthickness=0,
        )
        self._outer_canvas.pack(fill="both", expand=True, padx=2, pady=(0, 2))

        # ネオンボーダーを最外周に描画
        self._outer_canvas.bind("<Configure>", self._draw_outer_border)

        # メインコンテンツフレーム
        self._main_frame = tk.Frame(
            self._outer_canvas, bg=C["bg_panel"],
        )
        self._outer_canvas.create_window(
            3, 3, anchor="nw", window=self._main_frame,
            width=W_WIDTH - 8, height=W_HEIGHT - 52,
        )

        # スクロール可能なキャンバス
        self._scroll_canvas = tk.Canvas(
            self._main_frame, bg=C["bg_panel"],
            highlightthickness=0,
        )
        self._scrollbar = tk.Scrollbar(
            self._main_frame, orient="vertical",
            command=self._scroll_canvas.yview,
            bg=C["bg_card"], troughcolor=C["bg"],
            activebackground=C["neon2"],
        )
        self._scroll_canvas.configure(
            yscrollcommand=self._scrollbar.set,
        )
        self._scroll_canvas.pack(side="left", fill="both", expand=True)
        self._scrollbar.pack(side="right", fill="y")

        # スクロール内部フレーム
        self._content = tk.Frame(self._scroll_canvas, bg=C["bg_panel"])
        self._scroll_canvas.create_window(
            0, 0, anchor="nw", window=self._content,
        )
        self._content.bind("<Configure>", lambda e: self._scroll_canvas.configure(
            scrollregion=self._scroll_canvas.bbox("all")
        ))

        # マウスホイールでスクロール
        self._scroll_canvas.bind_all(
            "<MouseWheel>",
            lambda e: self._scroll_canvas.yview_scroll(
                -1 * (e.delta // 120), "units"
            ),
        )

        # ─── 各セクション構築 ─────────────────────────────────────────
        self._build_monitor_section()
        self._build_status_section()
        self._build_capture_section()
        self._build_gemini_section()
        self._build_preview_section()
        self._build_statusbar()

    def _build_titlebar(self) -> None:
        """
        カスタムタイトルバーを構築する

        機能:
        - ドラッグでウィンドウ移動
        - 最前面固定トグル（📌）
        - 最小化ボタン
        - 閉じるボタン
        """
        self._titlebar = tk.Canvas(
            self.root,
            height=46,
            bg=C["bg"],
            highlightthickness=0,
        )
        self._titlebar.pack(fill="x", side="top")

        # ドラッグ操作のバインド
        self._titlebar.bind("<ButtonPress-1>",  self._drag_start)
        self._titlebar.bind("<B1-Motion>",       self._drag_motion)

        # タイトルバーの描画
        self._titlebar.bind("<Configure>", self._draw_titlebar)

    def _draw_titlebar(self, e=None) -> None:
        self._titlebar.delete("all")
        w = self._titlebar.winfo_width() or W_WIDTH
        h = 46

        # 下部ラインでタイトルバーとコンテンツを区切る
        self._titlebar.create_line(0, h - 1, w, h - 1,
                                    fill=C["border_3"], width=1)
        self._titlebar.create_line(0, h - 2, w, h - 2,
                                    fill=C["border_2"], width=1)

        # スキャンラインエフェクト
        self._titlebar.create_rectangle(
            0, h - 3, w, h - 2,
            fill=C["glow_bg"], outline="",
        )

        # ロゴ・ブランド名
        # ⬡ 六角形アイコン（サイバー感）
        self._titlebar.create_text(
            18, h // 2,
            text="⬡", font=(FM, 18, "bold"),
            fill=C["neon"], anchor="center",
        )
        self._titlebar.create_text(
            38, h // 2,
            text="OMNI", font=(FM, 13, "bold"),
            fill=C["text_bright"], anchor="w",
        )
        self._titlebar.create_text(
            85, h // 2,
            text="SCOPE", font=(FM, 13, "bold"),
            fill=C["neon"], anchor="w",
        )
        # バージョン
        self._titlebar.create_text(
            148, h // 2 + 4,
            text="v1.0", font=(FM, 7),
            fill=C["text_dim"], anchor="w",
        )

        # ─── コントロールボタン群（右上） ─────────────────────────────
        btn_y  = h // 2
        close_x   = w - 18
        min_x     = w - 52
        pin_x     = w - 86

        # 閉じるボタン [✕]
        self._titlebar.create_text(
            close_x, btn_y,
            text="✕", font=(FM, 11),
            fill=C["error"], anchor="center",
            tags="btn_close",
        )
        self._titlebar.tag_bind("btn_close", "<Button-1>", self._on_close)
        self._titlebar.tag_bind("btn_close", "<Enter>",
            lambda _: self._titlebar.itemconfig("btn_close", fill=C["cyan"]))
        self._titlebar.tag_bind("btn_close", "<Leave>",
            lambda _: self._titlebar.itemconfig("btn_close", fill=C["error"]))

        # 最小化ボタン [─]
        self._titlebar.create_text(
            min_x, btn_y,
            text="─", font=(FM, 11),
            fill=C["text_dim"], anchor="center",
            tags="btn_min",
        )
        self._titlebar.tag_bind("btn_min", "<Button-1>", self._on_minimize)
        self._titlebar.tag_bind("btn_min", "<Enter>",
            lambda _: self._titlebar.itemconfig("btn_min", fill=C["neon"]))
        self._titlebar.tag_bind("btn_min", "<Leave>",
            lambda _: self._titlebar.itemconfig("btn_min", fill=C["text_dim"]))

        # ピン（最前面固定）ボタン [📌]
        pinned = self.root.attributes("-topmost")
        pin_col = C["cyan"] if pinned else C["text_dim"]
        self._titlebar.create_text(
            pin_x, btn_y,
            text="📌", font=(FM, 10),
            fill=pin_col, anchor="center",
            tags="btn_pin",
        )
        self._titlebar.tag_bind("btn_pin", "<Button-1>", self._toggle_topmost)
        self._titlebar.tag_bind("btn_pin", "<Enter>",
            lambda _: self._titlebar.itemconfig("btn_pin", fill=C["neon"]))
        self._titlebar.tag_bind("btn_pin", "<Leave>",
            lambda _: self._titlebar.itemconfig(
                "btn_pin", fill=C["cyan"] if self.root.attributes("-topmost")
                else C["text_dim"]
            ))

    def _build_monitor_section(self) -> None:
        """モニター選択セクション"""
        _section_header(self._content, "TARGET MONITOR")

        btn_frame = tk.Frame(self._content, bg=C["bg_panel"])
        btn_frame.pack(fill="x", padx=10, pady=(0, 6))

        self._monitor_buttons: dict[int, MonitorButton] = {}
        for i in range(1, 4):
            btn = MonitorButton(btn_frame, i, self._on_monitor_select)
            btn.grid(row=0, column=i - 1, padx=4, pady=4)
            self._monitor_buttons[i] = btn

        # 現在の対象モニターを選択状態に
        if self.target_monitor in self._monitor_buttons:
            self._monitor_buttons[self.target_monitor].set_selected(True)

        # ホットキー表示
        hk_frame = tk.Frame(self._content, bg=C["bg_panel"])
        hk_frame.pack(fill="x", padx=10)
        tk.Label(
            hk_frame,
            text="  Ctrl+Shift+1/2/3 でモニター切り替え",
            font=FONT_SMALL, fg=C["text_dim"], bg=C["bg_panel"],
        ).pack(side="left")

    def _build_status_section(self) -> None:
        """Chrome・Gemini 接続ステータスセクション"""
        _section_header(self._content, "SYSTEM STATUS")

        status_frame = tk.Frame(self._content, bg=C["bg_card"],
                                bd=0, relief="flat")
        status_frame.pack(fill="x", padx=10, pady=(0, 6))

        # 内側フレーム（パディング用）
        inner = tk.Frame(status_frame, bg=C["bg_card"])
        inner.pack(fill="x", padx=8, pady=6)

        self._chrome_light = StatusLight(inner, "CHROME")
        self._chrome_light.pack(side="left", padx=(0, 20))
        self._chrome_light.set_status(C["idle"], "CHECKING...")

        self._gemini_light = StatusLight(inner, "GEMINI ")
        self._gemini_light.pack(side="left")
        self._gemini_light.set_status(C["idle"], "NO API KEY")

        # リフレッシュボタン
        refresh_btn = tk.Label(
            inner, text="⟳ REFRESH", font=FONT_SMALL,
            fg=C["neon2"], bg=C["bg_card"], cursor="hand2",
        )
        refresh_btn.pack(side="right", padx=4)
        refresh_btn.bind("<Button-1>", lambda _: self._check_chrome_async())
        refresh_btn.bind("<Enter>",
            lambda _: refresh_btn.configure(fg=C["cyan"]))
        refresh_btn.bind("<Leave>",
            lambda _: refresh_btn.configure(fg=C["neon2"]))

    def _build_capture_section(self) -> None:
        """キャプチャボタンセクション"""
        _section_header(self._content, "CAPTURE")

        cap_frame = tk.Frame(self._content, bg=C["bg_panel"])
        cap_frame.pack(fill="x", padx=12, pady=(2, 4))

        self._capture_btn = CaptureButton(cap_frame, self.do_capture)
        self._capture_btn.pack(pady=4)

        # ホットキー表示
        tk.Label(
            cap_frame,
            text="  Ctrl+Shift+S",
            font=FONT_SMALL, fg=C["text_dim"], bg=C["bg_panel"],
        ).pack()

    def _build_gemini_section(self) -> None:
        """Gemini API セクション"""
        _section_header(self._content, "GEMINI ANALYSIS")

        gem_frame = tk.Frame(self._content, bg=C["bg_card"])
        gem_frame.pack(fill="x", padx=10, pady=(0, 6))
        inner = tk.Frame(gem_frame, bg=C["bg_card"])
        inner.pack(fill="x", padx=8, pady=8)

        # ─── API キー入力 ────────────────────────────────────────────
        tk.Label(inner, text="API KEY", font=FONT_LABEL,
                 fg=C["neon"], bg=C["bg_card"]).pack(anchor="w")
        key_row = tk.Frame(inner, bg=C["bg_card"])
        key_row.pack(fill="x", pady=(2, 6))

        self._api_key_entry = NeonEntry(key_row, show="•", width=35)
        self._api_key_entry.pack(side="left", fill="x", expand=True)

        save_key_btn = tk.Label(
            key_row, text=" SAVE ", font=FONT_LABEL,
            fg=C["bg"], bg=C["neon2"], cursor="hand2", padx=4, pady=3,
        )
        save_key_btn.pack(side="right", padx=(4, 0))
        save_key_btn.bind("<Button-1>", self._on_save_api_key)
        save_key_btn.bind("<Enter>",
            lambda _: save_key_btn.configure(bg=C["cyan"]))
        save_key_btn.bind("<Leave>",
            lambda _: save_key_btn.configure(bg=C["neon2"]))

        # ─── モデル選択 ──────────────────────────────────────────────
        model_row = tk.Frame(inner, bg=C["bg_card"])
        model_row.pack(fill="x", pady=(0, 6))
        tk.Label(model_row, text="MODEL", font=FONT_LABEL,
                 fg=C["neon"], bg=C["bg_card"]).pack(side="left")

        self._model_var = tk.StringVar(
            value=self.cfg["gemini"].get("model", "gemini-2.0-flash")
        )
        models = ["gemini-2.0-flash", "gemini-2.0-flash-lite",
                  "gemini-1.5-pro-latest", "gemini-1.5-flash-latest"]
        model_menu = tk.OptionMenu(model_row, self._model_var, *models,
                                   command=self._on_model_change)
        model_menu.configure(
            bg=C["bg_card2"], fg=C["neon"],
            activebackground=C["glow_bg"], activeforeground=C["cyan"],
            highlightbackground=C["border_3"],
            font=FONT_SMALL, bd=0,
        )
        model_menu["menu"].configure(
            bg=C["bg_card2"], fg=C["text"],
            activebackground=C["glow_bg"], activeforeground=C["cyan"],
            font=FONT_SMALL,
        )
        model_menu.pack(side="left", padx=(8, 0))

        # Auto-analyze トグル
        self._auto_analyze_var = tk.BooleanVar(value=True)
        auto_chk = tk.Checkbutton(
            model_row,
            text=" AUTO ANALYZE",
            variable=self._auto_analyze_var,
            font=FONT_SMALL,
            fg=C["text_dim"], bg=C["bg_card"],
            selectcolor=C["bg_card"],
            activeforeground=C["neon"],
            activebackground=C["bg_card"],
            command=self._on_auto_analyze_toggle,
        )
        auto_chk.pack(side="right")

        # ─── プロンプト入力 ──────────────────────────────────────────
        tk.Label(inner, text="PROMPT", font=FONT_LABEL,
                 fg=C["neon"], bg=C["bg_card"]).pack(anchor="w")
        self._prompt_text = tk.Text(
            inner, height=3, width=50,
            bg=C["bg_card2"], fg=C["text"],
            insertbackground=C["neon"],
            selectbackground=C["border_3"],
            relief="flat", bd=1,
            font=FONT_BODY,
            wrap="word",
        )
        self._prompt_text.configure(highlightbackground=C["border_3"],
                                    highlightcolor=C["neon"])
        self._prompt_text.pack(fill="x", pady=(2, 6))

        # ─── システムプロンプト ──────────────────────────────────────
        sys_row = tk.Frame(inner, bg=C["bg_card"])
        sys_row.pack(fill="x")
        tk.Label(sys_row, text="SYSTEM PROMPT (RWSガイドライン等)",
                 font=FONT_LABEL, fg=C["text_dim"], bg=C["bg_card"]).pack(anchor="w")

        self._system_prompt_text = tk.Text(
            inner, height=3, width=50,
            bg=C["bg_card"], fg=C["text_dim"],
            insertbackground=C["neon"],
            relief="flat", bd=1,
            font=FONT_BODY,
            wrap="word",
        )
        self._system_prompt_text.configure(
            highlightbackground=C["border_2"],
            highlightcolor=C["border_3"],
        )
        self._system_prompt_text.pack(fill="x", pady=(2, 6))

        # ─── 手動送信ボタン ──────────────────────────────────────────
        send_btn_canvas = tk.Canvas(
            inner, height=36, bg=C["bg_card"], highlightthickness=0,
        )
        send_btn_canvas.pack(fill="x", pady=(2, 6))

        def _draw_send_btn(e=None):
            send_btn_canvas.delete("all")
            w = send_btn_canvas.winfo_width() or 400
            send_btn_canvas.create_rectangle(
                0, 0, w - 1, 35,
                outline=C["border_3"], fill=C["bg_card2"],
            )
            send_btn_canvas.create_rectangle(
                2, 2, w - 3, 33,
                outline=C["neon2"], fill="",
            )
            send_btn_canvas.create_text(
                w // 2, 18,
                text="▶  SEND TO GEMINI",
                font=FONT_HEAD, fill=C["neon2"],
            )

        send_btn_canvas.bind("<Configure>", _draw_send_btn)
        send_btn_canvas.bind("<Button-1>", self._on_send_to_gemini)
        send_btn_canvas.bind("<Enter>", lambda _: (
            send_btn_canvas.configure(cursor="hand2"),
            send_btn_canvas.delete("all") or True,
        ) and self._redraw_send_hover(send_btn_canvas))
        send_btn_canvas.bind("<Leave>", lambda _: _draw_send_btn())
        self._send_btn_canvas = send_btn_canvas

        # ─── Gemini レスポンス表示エリア ────────────────────────────
        tk.Label(inner, text="RESPONSE", font=FONT_LABEL,
                 fg=C["neon"], bg=C["bg_card"]).pack(anchor="w")

        resp_frame = tk.Frame(inner, bg=C["border_3"])
        resp_frame.pack(fill="x", pady=(2, 2))

        self._response_text = tk.Text(
            resp_frame,
            height=10, width=50,
            bg=C["bg"], fg=C["text"],
            insertbackground=C["neon"],
            relief="flat", bd=0,
            font=FONT_BODY,
            wrap="word",
            state="disabled",
        )
        resp_scrollbar = tk.Scrollbar(
            resp_frame, orient="vertical",
            command=self._response_text.yview,
            bg=C["bg_card"], troughcolor=C["bg"],
        )
        self._response_text.configure(
            yscrollcommand=resp_scrollbar.set,
        )
        self._response_text.pack(side="left", fill="both", expand=True, padx=1, pady=1)
        resp_scrollbar.pack(side="right", fill="y")

    def _build_preview_section(self) -> None:
        """最後のキャプチャプレビューセクション"""
        _section_header(self._content, "LAST CAPTURE")

        prev_frame = tk.Frame(self._content, bg=C["bg_card"])
        prev_frame.pack(fill="x", padx=10, pady=(0, 8))
        inner = tk.Frame(prev_frame, bg=C["bg_card"])
        inner.pack(fill="x", padx=8, pady=8)

        # サムネイル表示 Canvas
        THUMB_W, THUMB_H = 120, 80
        thumb_canvas = tk.Canvas(
            inner, width=THUMB_W, height=THUMB_H,
            bg=C["bg_card2"], highlightthickness=1,
            highlightbackground=C["border_3"],
        )
        thumb_canvas.pack(side="left", padx=(0, 10))
        # プレースホルダー
        thumb_canvas.create_text(
            THUMB_W // 2, THUMB_H // 2,
            text="NO CAPTURE\nYET",
            font=FONT_SMALL, fill=C["text_dim"],
            justify="center",
        )
        self._thumb_canvas = thumb_canvas
        self._thumb_image  = None  # PIL.ImageTk を保持

        # 情報テキスト
        info_frame = tk.Frame(inner, bg=C["bg_card"])
        info_frame.pack(side="left", fill="both", expand=True)

        self._prev_title_label = tk.Label(
            info_frame, text="—",
            font=FONT_BODY, fg=C["text"], bg=C["bg_card"],
            wraplength=270, justify="left",
        )
        self._prev_title_label.pack(anchor="w")

        self._prev_time_label = tk.Label(
            info_frame, text="",
            font=FONT_SMALL, fg=C["text_dim"], bg=C["bg_card"],
        )
        self._prev_time_label.pack(anchor="w")

        self._prev_size_label = tk.Label(
            info_frame, text="",
            font=FONT_SMALL, fg=C["text_dim"], bg=C["bg_card"],
        )
        self._prev_size_label.pack(anchor="w")

        self._prev_file_label = tk.Label(
            info_frame, text="",
            font=FONT_SMALL, fg=C["neon2"], bg=C["bg_card"],
        )
        self._prev_file_label.pack(anchor="w")

    def _build_statusbar(self) -> None:
        """ステータスバー（ウィンドウ最下部）"""
        self._statusbar = tk.Canvas(
            self.root, height=20, bg=C["bg"],
            highlightthickness=0,
        )
        self._statusbar.pack(fill="x", side="bottom")
        self._status_text_id = self._statusbar.create_text(
            8, 10, text="OmniScope Ready.",
            font=FONT_STATUS, fill=C["text_dim"], anchor="w",
        )
        # 上部境界線
        self._statusbar.bind("<Configure>", lambda e: (
            self._statusbar.create_line(
                0, 0, e.width, 0, fill=C["border_2"], width=1,
            )
        ))

    # ──────────────────────────────────────────────────────────────────
    # ドラッグ / ウィンドウ操作
    # ──────────────────────────────────────────────────────────────────

    def _drag_start(self, e: tk.Event) -> None:
        self._drag_x = e.x
        self._drag_y = e.y

    def _drag_motion(self, e: tk.Event) -> None:
        x = self.root.winfo_x() + e.x - self._drag_x
        y = self.root.winfo_y() + e.y - self._drag_y
        self.root.geometry(f"+{x}+{y}")

    def _on_close(self, _=None) -> None:
        self._unregister_hotkeys()
        _save_config(self.cfg)
        self.root.destroy()

    def _on_minimize(self, _=None) -> None:
        self.root.overrideredirect(False)
        self.root.iconify()
        self.root.bind("<Map>", self._on_restore)

    def _on_restore(self, _=None) -> None:
        self.root.overrideredirect(True)
        self.root.unbind("<Map>")

    def _toggle_topmost(self, _=None) -> None:
        current = self.root.attributes("-topmost")
        self.root.attributes("-topmost", not current)
        self._draw_titlebar()

    # ──────────────────────────────────────────────────────────────────
    # モニター選択
    # ──────────────────────────────────────────────────────────────────

    def _on_monitor_select(self, monitor_num: int) -> None:
        """モニター選択ボタンのクリックハンドラ"""
        self.target_monitor = monitor_num
        for num, btn in self._monitor_buttons.items():
            btn.set_selected(num == monitor_num)
        self.cfg["monitors"]["default"] = monitor_num
        self._set_status(f"対象モニター: DISP {monitor_num:02d}")
        self._notify_toast(f"OmniScope: DISP {monitor_num:02d} を対象に設定")

    # ──────────────────────────────────────────────────────────────────
    # Chrome 接続チェック
    # ──────────────────────────────────────────────────────────────────

    def _check_chrome_async(self) -> None:
        """バックグラウンドで Chrome 接続状態をチェック"""
        self._chrome_light.set_status(C["warning"], "CHECKING...")
        host = self.cfg["chrome"]["debug_host"]
        port = self.cfg["chrome"]["debug_port"]

        def _check():
            ok = check_connection_sync(host, port)
            self.root.after(0, lambda: self._update_chrome_status(ok))

        threading.Thread(target=_check, daemon=True).start()

    def _update_chrome_status(self, ok: bool) -> None:
        self._chrome_ok = ok
        if ok:
            self._chrome_light.set_status(C["success"], "CONNECTED")
            self._set_status("Chrome 接続OK。キャプチャ可能です。")
        else:
            self._chrome_light.set_status(C["error"], "NOT CONNECTED")
            self._set_status("Chrome 未接続。launch_chrome.bat を実行してください。")

    # ──────────────────────────────────────────────────────────────────
    # Gemini 設定
    # ──────────────────────────────────────────────────────────────────

    def _on_save_api_key(self, _=None) -> None:
        """API キーを保存してクライアントを初期化"""
        key = self._api_key_entry.get().strip()
        if not key:
            self._set_status("API キーを入力してください。")
            return
        self.cfg["gemini"]["api_key"] = key
        _save_config(self.cfg)
        self._init_gemini_client(key)

    def _init_gemini_client(self, api_key: str) -> None:
        """GeminiClient を初期化してステータスを更新"""
        try:
            model = self._model_var.get() if hasattr(self, "_model_var") else \
                    self.cfg["gemini"]["model"]
            self._gemini_client = GeminiClient(api_key, model)
            self._gemini_light.set_status(C["success"], "READY")
            self._set_status("Gemini API キーを設定しました。")
        except Exception as ex:
            self._gemini_light.set_status(C["error"], "ERROR")
            self._set_status(f"Gemini 初期化エラー: {ex}")

    def _on_model_change(self, model_name: str) -> None:
        """モデル変更"""
        if self._gemini_client:
            self._gemini_client.update_model(model_name)
        self.cfg["gemini"]["model"] = model_name
        self._set_status(f"モデル変更: {model_name}")

    def _on_auto_analyze_toggle(self) -> None:
        val = self._auto_analyze_var.get()
        self.cfg["gemini"]["auto_analyze"] = val

    # ──────────────────────────────────────────────────────────────────
    # キャプチャ実行
    # ──────────────────────────────────────────────────────────────────

    def do_capture(self) -> None:
        """
        キャプチャを実行する（メインのアクション）

        1. 別スレッドで capture_sync を実行
        2. 完了後、UIを更新
        3. Auto-analyze が ON なら Gemini に自動送信
        """
        if self._busy:
            self._set_status("キャプチャ中です。しばらくお待ちください。")
            return

        self._busy = True
        self._capture_btn.set_busy(True)
        self._set_status("キャプチャ開始...")

        def _run():
            try:
                host = self.cfg["chrome"]["debug_host"]
                port = self.cfg["chrome"]["debug_port"]
                save = self.cfg["capture"]["save_locally"]
                out  = BASE_DIR / self.cfg["capture"]["output_dir"] if save else None

                result = capture_sync(
                    monitor_index=self.target_monitor,
                    debug_host=host,
                    debug_port=port,
                    output_dir=out,
                    save_locally=save,
                    status_cb=lambda msg: self.root.after(0, lambda m=msg: self._set_status(m)),
                )
                self.root.after(0, lambda: self._on_capture_done(result))
            except Exception as ex:
                err = str(ex)
                self.root.after(0, lambda: self._on_capture_error(err))

        threading.Thread(target=_run, daemon=True).start()

    def _on_capture_done(self, result: CaptureResult) -> None:
        """キャプチャ完了後の処理（メインスレッドで実行）"""
        self._busy = False
        self._capture_btn.set_busy(False)
        self._last_result = result

        # プレビュー更新
        self._update_preview(result)
        self._set_status(f"キャプチャ完了: {result.title[:40]}")

        # Chrome 接続確認済みに更新
        self._chrome_light.set_status(C["success"], "CONNECTED")

        # トースト通知
        self._notify_toast(f"OmniScope: キャプチャ完了\n{result.title[:40]}")

        # Auto-analyze
        if self._auto_analyze_var.get() and self._gemini_client:
            self._set_status("Gemini に自動送信中...")
            self._do_gemini_analyze(result)

    def _on_capture_error(self, err: str) -> None:
        """キャプチャエラー処理"""
        self._busy = False
        self._capture_btn.set_busy(False)

        if "connect" in err.lower() or "refused" in err.lower():
            self._chrome_light.set_status(C["error"], "NOT CONNECTED")
            self._set_status(
                "Chrome に接続できません。launch_chrome.bat を使って起動してください。"
            )
        else:
            self._set_status(f"エラー: {err}")

        self._set_response(f"❌ キャプチャエラー:\n{err}")

    # ──────────────────────────────────────────────────────────────────
    # Gemini 送信
    # ──────────────────────────────────────────────────────────────────

    def _on_send_to_gemini(self, _=None) -> None:
        """手動 Gemini 送信ボタンのハンドラ"""
        if not self._gemini_client:
            self._set_status("Gemini API キーを設定してください。")
            return
        if not self._last_result:
            self._set_status("まずキャプチャを実行してください。")
            return
        self._do_gemini_analyze(self._last_result)

    def _do_gemini_analyze(self, result: CaptureResult) -> None:
        """Gemini 解析を実行（別スレッド）"""
        prompt  = self._prompt_text.get("1.0", "end").strip()
        sysprompt = self._system_prompt_text.get("1.0", "end").strip()

        if not prompt:
            prompt = self.cfg["gemini"]["default_prompt"]

        self._set_response("⟳  Gemini に送信中...\n")

        def _run():
            try:
                text = self._gemini_client.analyze(
                    screenshot_bytes=result.image_bytes,
                    prompt=prompt,
                    system_prompt=sysprompt if sysprompt else None,
                    status_cb=lambda m: self.root.after(0, lambda msg=m: self._set_status(msg)),
                )
                self.root.after(0, lambda: self._set_response(text))
                self.root.after(0, lambda: self._set_status("Gemini 解析完了"))
                self._notify_toast("OmniScope: Gemini 解析完了")
            except Exception as ex:
                err = str(ex)
                self.root.after(0, lambda: self._set_response(f"❌ Gemini エラー:\n{err}"))
                self.root.after(0, lambda: self._gemini_light.set_status(C["error"], "ERROR"))
                self.root.after(0, lambda: self._set_status(f"Gemini エラー: {err}"))

        threading.Thread(target=_run, daemon=True).start()

    # ──────────────────────────────────────────────────────────────────
    # UI 更新ヘルパー
    # ──────────────────────────────────────────────────────────────────

    def _set_status(self, msg: str) -> None:
        """ステータスバーのメッセージを更新"""
        try:
            self._statusbar.itemconfig(self._status_text_id, text=f"  {msg}")
        except Exception:
            pass

    def _set_response(self, text: str) -> None:
        """Gemini レスポンスエリアのテキストを更新"""
        self._response_text.configure(state="normal")
        self._response_text.delete("1.0", "end")
        self._response_text.insert("end", text)
        self._response_text.configure(state="disabled")
        self._response_text.see("1.0")

    def _update_preview(self, result: CaptureResult) -> None:
        """最後のキャプチャのプレビューを更新"""
        self._prev_title_label.configure(text=result.title[:60])
        self._prev_time_label.configure(
            text=f"📅 {result.timestamp.strftime('%Y-%m-%d %H:%M:%S')}"
        )
        self._prev_size_label.configure(
            text=f"📦 {result.file_size_kb} KB"
        )
        if result.filepath:
            self._prev_file_label.configure(
                text=f"💾 {result.filepath.name}"
            )
        else:
            self._prev_file_label.configure(text="（ローカル保存なし）")

        # サムネイル生成
        if PIL_AVAILABLE:
            try:
                THUMB_W, THUMB_H = 120, 80
                img = Image.open(io.BytesIO(result.image_bytes))
                img.thumbnail((THUMB_W, THUMB_H), Image.LANCZOS)
                photo = ImageTk.PhotoImage(img)
                self._thumb_canvas.delete("all")
                # 中央に配置
                ox = (THUMB_W - img.width)  // 2
                oy = (THUMB_H - img.height) // 2
                self._thumb_canvas.create_image(
                    ox, oy, anchor="nw", image=photo,
                )
                self._thumb_image = photo  # GC防止のため参照を保持
            except Exception:
                pass

    def _draw_outer_border(self, e=None) -> None:
        """ウィンドウ外周のネオンボーダーを描画"""
        self._outer_canvas.delete("outer_border")
        w = self._outer_canvas.winfo_width()
        h = self._outer_canvas.winfo_height()
        # 外周 2 重ボーダー
        self._outer_canvas.create_rectangle(
            0, 0, w - 1, h - 1,
            outline=C["border_2"], fill="", tags="outer_border",
        )
        self._outer_canvas.create_rectangle(
            1, 1, w - 2, h - 2,
            outline=C["border_3"], fill="", tags="outer_border",
        )

    def _animate_scanline(self) -> None:
        """スキャンラインアニメーション（薄い横線が上から下へ流れる）"""
        # ここではウィンドウへの直接描画は複雑なので省略し、
        # タイトルバーのキラキラエフェクトとして実装
        self._scanline_phase += 0.02
        # 100ms ごとにタイトルバーを再描画してアニメーションさせる
        self.root.after(100, self._animate_scanline)

    def _redraw_send_hover(self, canvas: tk.Canvas) -> None:
        """送信ボタンのホバー描画"""
        w = canvas.winfo_width() or 400
        canvas.delete("all")
        canvas.create_rectangle(0, 0, w - 1, 35,
                                  outline=C["border_3"], fill=C["glow_bg"])
        canvas.create_rectangle(2, 2, w - 3, 33,
                                  outline=C["cyan"], fill="")
        canvas.create_text(w // 2, 18,
                           text="▶  SEND TO GEMINI",
                           font=FONT_HEAD, fill=C["cyan"])

    # ──────────────────────────────────────────────────────────────────
    # グローバルホットキー
    # ──────────────────────────────────────────────────────────────────

    def _register_hotkeys(self) -> None:
        """グローバルホットキーを登録"""
        if not KEYBOARD_AVAILABLE:
            self._set_status("⚠ keyboard ライブラリ未インストール。ホットキー無効。")
            return
        try:
            hk = self.cfg["hotkeys"]
            kb.add_hotkey(hk["capture"],
                lambda: self.root.after(0, self.do_capture))
            kb.add_hotkey(hk["monitor_1"],
                lambda: self.root.after(0, lambda: self._on_monitor_select(1)))
            kb.add_hotkey(hk["monitor_2"],
                lambda: self.root.after(0, lambda: self._on_monitor_select(2)))
            kb.add_hotkey(hk["monitor_3"],
                lambda: self.root.after(0, lambda: self._on_monitor_select(3)))
            self._set_status("ホットキー登録完了。")
        except Exception as ex:
            self._set_status(f"ホットキー登録エラー: {ex}")

    def _unregister_hotkeys(self) -> None:
        """ホットキーの登録を解除"""
        if KEYBOARD_AVAILABLE:
            try:
                kb.unhook_all()
            except Exception:
                pass

    # ──────────────────────────────────────────────────────────────────
    # 通知
    # ──────────────────────────────────────────────────────────────────

    def _notify_toast(self, message: str) -> None:
        """Windows トースト通知（winotify が利用可能な場合）"""
        if not TOAST_AVAILABLE:
            return
        try:
            notif = Notification(
                app_id="OmniScope",
                title="OmniScope",
                msg=message,
                duration="short",
            )
            notif.set_audio(audio.Default, loop=False)
            notif.show()
        except Exception:
            pass

    # ──────────────────────────────────────────────────────────────────
    # アプリ実行
    # ──────────────────────────────────────────────────────────────────

    def run(self) -> None:
        """メインループを開始"""
        self.root.mainloop()


# ══════════════════════════════════════════════════════════════════════
#  エントリポイント
# ══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    app = OmniScopeApp()
    app.run()
