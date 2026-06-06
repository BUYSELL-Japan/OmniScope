"""
monitor.py — マルチモニター情報の取得モジュール

screeninfo ライブラリで接続中のモニター一覧を取得し、
各モニターの座標・解像度情報を提供します。

使用方法:
    python monitor.py       # モニター一覧をコンソールに表示
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional


@dataclass
class MonitorInfo:
    """モニター1枚の情報を保持するデータクラス"""
    index: int          # 1始まりのインデックス（DISP 01, 02, 03...）
    x: int              # 画面左端のX座標（マルチモニター絶対座標）
    y: int              # 画面上端のY座標
    width: int          # 水平解像度（ピクセル）
    height: int         # 垂直解像度（ピクセル）
    name: str = ""      # OS上のモニター識別名

    def contains_point(self, px: int, py: int) -> bool:
        """指定した絶対座標 (px, py) がこのモニターの表示範囲内かどうか判定"""
        return (self.x <= px < self.x + self.width and
                self.y <= py < self.y + self.height)

    def contains_window_center(self, wx: int, wy: int, ww: int, wh: int) -> bool:
        """
        ウィンドウの中心点がこのモニター上にあるかどうか判定
        
        Args:
            wx, wy: ウィンドウ左上のスクリーン座標
            ww, wh: ウィンドウの幅・高さ
        """
        center_x = wx + ww // 2
        center_y = wy + wh // 2
        return self.contains_point(center_x, center_y)

    def __str__(self) -> str:
        return (f"DISP {self.index:02d}: {self.width}x{self.height} "
                f"@ ({self.x:+d}, {self.y:+d})  [{self.name}]")


def get_all_monitors() -> list[MonitorInfo]:
    """
    現在接続されている全モニターの情報を取得して返す

    screeninfo が利用可能な場合はそちらを使用。
    失敗した場合は Windows API (ctypes) でフォールバック。

    Returns:
        MonitorInfo のリスト（インデックスは1始まり）
    """
    monitors: list[MonitorInfo] = []

    # ─── 方法1: screeninfo ライブラリ ─────────────────────────────────
    try:
        from screeninfo import get_monitors as _si_get
        raw = _si_get()
        for i, m in enumerate(raw):
            monitors.append(MonitorInfo(
                index=i + 1,
                x=m.x,
                y=m.y,
                width=m.width,
                height=m.height,
                name=getattr(m, "name", None) or f"Display {i+1}",
            ))
        if monitors:
            return monitors
    except Exception:
        pass

    # ─── 方法2: Windows API (ctypes) フォールバック ────────────────────
    try:
        import ctypes
        import ctypes.wintypes

        _monitors_raw: list[tuple[int, int, int, int]] = []

        MonitorEnumProc = ctypes.WINFUNCTYPE(
            ctypes.c_bool,
            ctypes.c_ulong, ctypes.c_ulong,
            ctypes.POINTER(ctypes.wintypes.RECT),
            ctypes.c_double,
        )

        def _cb(hMon, hdcMon, lprcMon, dwData) -> bool:
            mi_buf = ctypes.create_string_buffer(40)
            ctypes.c_uint32.from_address(ctypes.addressof(mi_buf)).value = 40
            ctypes.windll.user32.GetMonitorInfoW(hMon, mi_buf)
            left   = ctypes.c_int32.from_address(ctypes.addressof(mi_buf) +  4).value
            top    = ctypes.c_int32.from_address(ctypes.addressof(mi_buf) +  8).value
            right  = ctypes.c_int32.from_address(ctypes.addressof(mi_buf) + 12).value
            bottom = ctypes.c_int32.from_address(ctypes.addressof(mi_buf) + 16).value
            _monitors_raw.append((left, top, right - left, bottom - top))
            return True

        ctypes.windll.user32.EnumDisplayMonitors(
            None, None, MonitorEnumProc(_cb), 0
        )

        for i, (x, y, w, h) in enumerate(_monitors_raw):
            monitors.append(MonitorInfo(
                index=i + 1, x=x, y=y, width=w, height=h,
                name=f"Display {i+1}",
            ))
        if monitors:
            return monitors
    except Exception:
        pass

    # ─── 最終フォールバック: 仮のシングルモニター ─────────────────────
    return [MonitorInfo(1, 0, 0, 1920, 1080, "Display 1 (fallback)")]


def get_monitor_by_index(index: int) -> Optional[MonitorInfo]:
    """
    1始まりのインデックスで特定のモニター情報を取得

    Args:
        index: モニター番号（1〜）

    Returns:
        MonitorInfo または None（該当なし）
    """
    for m in get_all_monitors():
        if m.index == index:
            return m
    return None


# ──────────────────────────────────────────────────────────────────────
# コマンドライン実行時の動作確認用
# ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    # Windows コンソールの文字コード問題を回避
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print("=" * 60)
    print("  OmniScope -- Monitor Detection Result")
    print("=" * 60)
    monitors = get_all_monitors()
    for m in monitors:
        print(f"  {m}")
    print(f"\n  Total: {len(monitors)} monitor(s) detected")
    print("=" * 60)
