"""
engine.py — Playwright CDP接続 + フルページキャプチャエンジン

⚠️ 重要な設計方針:
    このモジュールは page.goto() / page.reload() 等の
    ナビゲーション操作を一切行いません。
    ユーザーが既にChromeで開いているページを
    そのままキャプチャするだけです。

    RWSタスクのURLへの自動アクセスは行いません。

動作の流れ:
    1. Chrome の CDP エンドポイントに WebSocket で接続
    2. 全タブの情報をCDPで取得
    3. 指定モニター上のChromeウィンドウを特定
    4. そのウィンドウのアクティブタブをフルページキャプチャ
    5. PNGバイト列を返す（ファイル保存は任意）
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime
from pathlib import Path
from typing import Optional, Callable

from playwright.async_api import async_playwright, Browser, Page

from monitor import MonitorInfo, get_monitor_by_index


class CaptureResult:
    """キャプチャ結果を保持するデータクラス"""

    def __init__(
        self,
        image_bytes: bytes,
        title: str,
        url: str,
        filepath: Optional[Path] = None,
    ):
        self.image_bytes = image_bytes    # PNGバイト列（Geminiに直接渡せる）
        self.title       = title          # ページタイトル
        self.url         = url            # ページURL
        self.filepath    = filepath       # ローカル保存先（Noneなら未保存）
        self.timestamp   = datetime.now()
        self.file_size_kb = len(image_bytes) // 1024

    def __repr__(self) -> str:
        return (f"CaptureResult(title={self.title!r}, "
                f"size={self.file_size_kb}KB, ts={self.timestamp:%H:%M:%S})")


class CaptureEngine:
    """
    既存Chromeにおけるフルページキャプチャエンジン

    使用方法:
        engine = CaptureEngine(debug_port=9222)
        result = asyncio.run(engine.capture(monitor_index=2))
        # result.image_bytes → Gemini に直接渡せる
    """

    def __init__(
        self,
        debug_host: str = "127.0.0.1",
        debug_port: int = 9222,
        output_dir: Optional[Path] = None,
    ):
        # ─── Chrome CDP 接続先設定 ─────────────────────────────────────
        # Chrome が --remote-debugging-port=9222 で起動されている必要あり
        self.debug_host = debug_host
        self.debug_port = debug_port
        self.cdp_url    = f"http://{debug_host}:{debug_port}"

        # スクリーンショット保存ディレクトリ（save_locally=True の場合に使用）
        self.output_dir = output_dir

    # ─────────────────────────────────────────────────────────────────
    # パブリックAPI
    # ─────────────────────────────────────────────────────────────────

    async def capture(
        self,
        monitor_index: int,
        save_locally: bool = True,
        status_cb: Optional[Callable[[str], None]] = None,
    ) -> CaptureResult:
        """
        指定モニター上のChrome アクティブタブをキャプチャ

        Args:
            monitor_index: 対象モニター番号（1〜3）
            save_locally:  True の場合 output_dir にも保存
            status_cb:     進捗メッセージを受け取るコールバック

        Returns:
            CaptureResult（.image_bytes でPNGバイト列を取得可能）
        """
        def log(msg: str):
            if status_cb:
                status_cb(msg)

        async with async_playwright() as pw:
            log(f"Chrome に接続中... ({self.cdp_url})")

            # ─── 既存 Chrome に接続（新規起動しない） ──────────────────
            # connect_over_cdp は launch ではなく接続のみ行うため、
            # ユーザーのブラウザを操作しない
            browser: Browser = await pw.chromium.connect_over_cdp(self.cdp_url)

            log("接続完了。対象タブを特定中...")

            # 指定モニターの MonitorInfo を取得
            monitor = get_monitor_by_index(monitor_index)
            if monitor is None:
                raise ValueError(f"モニター {monitor_index} が見つかりません")

            # ─── 対象ページを特定 ─────────────────────────────────────
            target_page = await self._find_page_on_monitor(browser, monitor, log)

            if target_page is None:
                # フォールバック: 最後にアクティブだったタブを使用
                log(f"⚠ DISP {monitor_index:02d} を特定できず。最前面タブを使用します。")
                target_page = await self._get_most_recent_page(browser)

            if target_page is None:
                raise RuntimeError(
                    "Chromeのタブが見つかりません。"
                    "launch_chrome.bat でChromeを起動してください。"
                )

            title = await target_page.title()
            url   = target_page.url
            log(f"ページ: {title[:50]}")

            # ─── キャプチャ前の安定化待機 ─────────────────────────────
            # ※ DOM変更（style注入等）は一切行わない。
            #    RWSのページに対して何らかの介入をすると
            #    検知されるリスクがあるため、ページはそのままの状態でキャプチャする。
            # 動的コンテンツが完全に描画されるよう少し待機するだけ
            await target_page.wait_for_timeout(300)

            log("フルページキャプチャ実行中...")

            # ─── フルページキャプチャ ─────────────────────────────────
            # full_page=True : スクロールで隠れている領域も含めてキャプチャ
            # type="png"     : 可逆圧縮（JPEGは文字がぼやける可能性がある）
            # scale="device" : OSのDPIスケールを反映（高DPIモニターで高精細になる）
            screenshot_bytes: bytes = await target_page.screenshot(
                full_page=True,
                type="png",
                scale="device",
            )

            log(f"キャプチャ完了 ({len(screenshot_bytes) // 1024} KB)")

            # ─── ローカル保存（オプション） ───────────────────────────
            filepath: Optional[Path] = None
            if save_locally and self.output_dir:
                self.output_dir.mkdir(parents=True, exist_ok=True)
                safe_title   = self._safe_filename(title)
                timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename      = f"{timestamp_str}_{safe_title}.png"
                filepath      = self.output_dir / filename
                filepath.write_bytes(screenshot_bytes)
                log(f"保存: screenshots/{filename}")

            return CaptureResult(
                image_bytes=screenshot_bytes,
                title=title,
                url=url,
                filepath=filepath,
            )

    async def check_connection(self) -> bool:
        """Chrome の CDP 接続が可能かチェック（UIからのヘルスチェック用）"""
        try:
            async with async_playwright() as pw:
                browser = await pw.chromium.connect_over_cdp(
                    self.cdp_url,
                )
                await browser.close()
                return True
        except Exception:
            return False

    # ─────────────────────────────────────────────────────────────────
    # プライベートメソッド
    # ─────────────────────────────────────────────────────────────────

    async def _find_page_on_monitor(
        self,
        browser: Browser,
        monitor: MonitorInfo,
        log: Callable,
    ) -> Optional[Page]:
        """
        CDP の Browser.getWindowBounds を使って
        指定モニター上にある Chrome ウィンドウのアクティブタブを特定する。

        Chrome DevTools Protocol の流れ:
            Target.getTargets → 全タブの一覧を取得
            Browser.getWindowForTarget → タブが属するウィンドウのIDを取得
            Browser.getWindowBounds → ウィンドウの画面上の座標を取得
            → モニターの座標範囲と照合して対象を絞り込む
        """
        try:
            # ブラウザレベルの CDP セッションを開始
            cdp = await browser.new_browser_cdp_session()

            # ─── 全ターゲット（タブ）情報を取得 ────────────────────────
            targets_result = await cdp.send("Target.getTargets")
            all_targets    = targets_result.get("targetInfos", [])

            # ページタイプのみ対象（iframe・devtools・about:blank を除外）
            page_targets = [
                t for t in all_targets
                if t.get("type") == "page"
                and not t.get("url", "").startswith("devtools://")
                and t.get("url", "") not in ("", "about:blank", "about:newtab")
            ]

            # ─── 各タブのウィンドウ位置を取得してモニターと照合 ─────
            candidates: list[dict] = []
            seen_window_ids: set[int] = set()

            for target in page_targets:
                try:
                    # このタブが属するウィンドウの ID を取得
                    win_res = await cdp.send(
                        "Browser.getWindowForTarget",
                        {"targetId": target["targetId"]},
                    )
                    window_id: int = win_res.get("windowId", -1)

                    # 同じウィンドウは一度だけ処理（タブが複数あっても）
                    if window_id in seen_window_ids:
                        # 同ウィンドウの別タブ候補として追加
                        candidates.append({
                            "target_id": target["targetId"],
                            "window_id": window_id,
                            "url":       target.get("url", ""),
                            "title":     target.get("title", ""),
                            "on_target_monitor": False,  # 同ウィンドウ扱い
                        })
                        continue

                    seen_window_ids.add(window_id)

                    # ウィンドウの画面上の位置・サイズを取得
                    bounds_res = await cdp.send(
                        "Browser.getWindowBounds",
                        {"windowId": window_id},
                    )
                    bounds  = bounds_res.get("bounds", {})
                    wx      = bounds.get("left",   0)
                    wy      = bounds.get("top",    0)
                    ww      = bounds.get("width",  800)
                    wh      = bounds.get("height", 600)

                    # ウィンドウ中心点がこのモニター上にあるか判定
                    on_monitor = monitor.contains_window_center(wx, wy, ww, wh)

                    if on_monitor:
                        candidates.append({
                            "target_id": target["targetId"],
                            "window_id": window_id,
                            "url":       target.get("url", ""),
                            "title":     target.get("title", ""),
                            "on_target_monitor": True,
                        })

                except Exception:
                    continue  # 個別タブのエラーは無視

            await cdp.detach()

            # モニター上のウィンドウが見つかった場合
            on_monitor_candidates = [c for c in candidates if c["on_target_monitor"]]

            if not on_monitor_candidates:
                return None

            log(f"DISP {monitor.index:02d} に {len(on_monitor_candidates)} タブを検出")

            # ─── Playwright の Page オブジェクトと突き合わせ ─────────────
            # CDP で取得したターゲット情報の URL と
            # Playwright の Page.url を照合して Page オブジェクトを取得する
            all_pages: list[Page] = []
            for ctx in browser.contexts:
                all_pages.extend(ctx.pages)

            # 最後の候補（最前面のタブ）を優先してマッチング
            for candidate in reversed(on_monitor_candidates):
                for page in reversed(all_pages):
                    if page.url == candidate["url"]:
                        return page

            # URL マッチに失敗した場合は最後のページを返す
            return all_pages[-1] if all_pages else None

        except Exception as e:
            log(f"ウィンドウ特定エラー: {e}")
            return None

    async def _get_most_recent_page(self, browser: Browser) -> Optional[Page]:
        """全コンテキストから最後にアクティブだったページを取得（フォールバック用）"""
        all_pages: list[Page] = []
        for ctx in browser.contexts:
            all_pages.extend(ctx.pages)
        return all_pages[-1] if all_pages else None

    @staticmethod
    def _safe_filename(title: str) -> str:
        """
        ページタイトルをWindowsファイル名として安全な文字列に変換

        除去する文字: \\ / : * ? " < > |
        日本語はそのまま保持（Windowsは日本語ファイル名に対応）
        """
        safe = re.sub(r'[\\/:*?"<>|]', "_", title)
        safe = safe.strip(". ")        # 先頭・末尾のピリオドとスペースを除去
        safe = safe[:50] or "untitled"  # 50文字で切り詰め、空なら untitled
        return safe


# ──────────────────────────────────────────────────────────────────────
# 同期版ラッパー関数（tkinter スレッドから asyncio.run で呼び出す用）
# ──────────────────────────────────────────────────────────────────────

def capture_sync(
    monitor_index: int,
    debug_host:  str = "127.0.0.1",
    debug_port:  int = 9222,
    output_dir:  Optional[Path] = None,
    save_locally: bool = True,
    status_cb:   Optional[Callable[[str], None]] = None,
) -> CaptureResult:
    """
    同期版キャプチャ関数

    tkinter の threading.Thread から呼び出す際に使用。
    内部で asyncio.run() を実行するため、既存イベントループがあると失敗します。
    """
    engine = CaptureEngine(debug_host, debug_port, output_dir)
    return asyncio.run(engine.capture(monitor_index, save_locally, status_cb))


def check_connection_sync(
    host: str = "127.0.0.1",
    port: int = 9222,
) -> bool:
    """CDP 接続チェックの同期版（UIのヘルスチェック用）"""
    engine = CaptureEngine(host, port)
    return asyncio.run(engine.check_connection())
