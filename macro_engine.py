import time
import io
import os
import win32clipboard
import win32api
import win32con
from PIL import Image

# キーコード定義
VK_F12 = 0x7B
VK_CONTROL = 0x11
VK_SHIFT = 0x10
VK_P = 0x50
VK_RETURN = 0x0D

def send_key(vk_code):
    win32api.keybd_event(vk_code, 0, 0, 0)
    time.sleep(0.05)
    win32api.keybd_event(vk_code, 0, win32con.KEYEVENTF_KEYUP, 0)

def send_hotkey(*vk_codes):
    for vk in vk_codes:
        win32api.keybd_event(vk, 0, 0, 0)
    time.sleep(0.05)
    for vk in reversed(vk_codes):
        win32api.keybd_event(vk, 0, win32con.KEYEVENTF_KEYUP, 0)

def type_string(text):
    for char in text:
        vk = win32api.VkKeyScan(char) & 0xFF
        send_key(vk)
        time.sleep(0.02)

from screeninfo import get_monitors

def get_monitor_center(monitor_index: int) -> tuple[int, int]:
    monitors = get_monitors()
    monitors.sort(key=lambda m: m.x)
    if monitor_index < 1 or monitor_index > len(monitors):
        m = monitors[0]
    else:
        m = monitors[monitor_index - 1]
    return m.x + m.width // 2, m.y + m.height // 2

def get_clipboard_text():
    win32clipboard.OpenClipboard()
    try:
        if win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_UNICODETEXT):
            data = win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)
            return data
        elif win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_TEXT):
            data = win32clipboard.GetClipboardData(win32clipboard.CF_TEXT)
            return data.decode('utf-8')
        return ""
    except Exception as e:
        print(f"Clipboard read error: {e}")
        return ""
    finally:
        win32clipboard.CloseClipboard()

def execute_chrome_macro(monitor_index: int) -> str:
    """
    指定モニターの中央をクリックしてChromeをアクティブにし、
    URLをコピー後、F12 -> Ctrl+Shift+P -> full -> Enter を送信する。
    戻り値: 取得したURL文字列（失敗時は空文字）
    """
    # 指定モニターの中央をクリックしてフォーカスを当てる
    cx, cy = get_monitor_center(monitor_index)
    original_pos = win32api.GetCursorPos()
    
    win32api.SetCursorPos((cx, cy))
    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, cx, cy, 0, 0)
    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, cx, cy, 0, 0)
    time.sleep(0.5)

    # --- URL取得処理 ---
    # Ctrl + L でアドレスバーフォーカス
    send_hotkey(VK_CONTROL, 0x4C) # VK_L
    time.sleep(0.3)
    
    # Ctrl + C でURLコピー
    send_hotkey(VK_CONTROL, 0x43) # VK_C
    time.sleep(0.3)
    
    url = get_clipboard_text()
    
    # アドレスバーからフォーカスを外し、ページ本文へフォーカスを戻す
    # (同じ場所をもう一度クリック)
    win32api.SetCursorPos((cx, cy))
    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, cx, cy, 0, 0)
    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, cx, cy, 0, 0)
    time.sleep(0.3)

    # 元のマウス位置に戻す
    win32api.SetCursorPos(original_pos)
    time.sleep(0.3)

    # F12 で DevTools を開く
    send_key(VK_F12)
    time.sleep(1.0) # DevToolsの起動待ち

    # Ctrl + Shift + P
    send_hotkey(VK_CONTROL, VK_SHIFT, VK_P)
    time.sleep(0.5)

    # IMEの影響を避けるため、クリップボード経由で "full" を貼り付ける
    win32clipboard.OpenClipboard()
    try:
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardText("full", win32clipboard.CF_UNICODETEXT)
    finally:
        win32clipboard.CloseClipboard()
    
    send_hotkey(VK_CONTROL, 0x56) # VK_V (0x56)
    time.sleep(0.5)

    # Enter でキャプチャ実行
    send_key(VK_RETURN)
    
    # 撮影が開始され、ダウンロードフォルダに入るまで待つ
    # 閉じるとキャプチャがキャンセルされる場合があるので閉じないでおく（後で手動か自動で閉じる）
    
    return url

def send_image_to_clipboard(image_path: str) -> bool:
    """
    保存された画像をWindowsのクリップボードにDIB形式でコピーする
    """
    try:
        # 画像が開けるようになるまで少しリトライ（ファイルロック回避）
        for _ in range(5):
            try:
                img = Image.open(image_path)
                break
            except PermissionError:
                time.sleep(0.2)
        else:
            return False

        output = io.BytesIO()
        img.convert("RGB").save(output, "BMP")
        data = output.getvalue()[14:]

        win32clipboard.OpenClipboard()
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(win32clipboard.CF_DIB, data)
        finally:
            win32clipboard.CloseClipboard()
        output.close()
        return True
    except Exception as e:
        print(f"Clipboard Error: {e}")
        return False
