import time
import io
import win32clipboard
import win32api
import win32con
from PIL import Image, ImageGrab
import keyboard
from screeninfo import get_monitors

def get_monitor_bbox(monitor_index: int) -> tuple[int, int, int, int]:
    """
    指定されたモニター番号（1-indexed）のバウンディングボックスを取得する。
    戻り値: (left, top, right, bottom)
    """
    monitors = get_monitors()
    # screeninfo のモニター順序は環境依存のため、X座標でソートして左から1,2,3とする
    monitors.sort(key=lambda m: m.x)
    
    if monitor_index < 1 or monitor_index > len(monitors):
        # 範囲外の場合はプライマリモニターをフォールバック
        for m in monitors:
            if m.is_primary:
                return (m.x, m.y, m.x + m.width, m.y + m.height)
        return (monitors[0].x, monitors[0].y, monitors[0].x + monitors[0].width, monitors[0].y + monitors[0].height)

    m = monitors[monitor_index - 1]
    return (m.x, m.y, m.x + m.width, m.y + m.height)

def send_image_to_clipboard(image: Image.Image) -> None:
    """
    PillowのImageオブジェクトをWindowsのクリップボードにDIB形式でコピーする
    """
    output = io.BytesIO()
    image.convert("RGB").save(output, "BMP")
    data = output.getvalue()[14:] # BMPヘッダ(14バイト)をスキップしてDIBデータを取得

    win32clipboard.OpenClipboard()
    try:
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardData(win32clipboard.CF_DIB, data)
    finally:
        win32clipboard.CloseClipboard()
    output.close()

def capture_scrolling_page(monitor_index: int, scrolls: int = 3) -> Image.Image:
    """
    指定モニターの画面を撮影し、PageDownでスクロールしながら複数枚撮影して縦に結合する。
    """
    bbox = get_monitor_bbox(monitor_index)
    
    # 対象モニターの中央をクリックしてフォーカスを合わせる（スクロールを効かせるため）
    center_x = bbox[0] + (bbox[2] - bbox[0]) // 2
    center_y = bbox[1] + (bbox[3] - bbox[1]) // 2
    
    # 元のマウス位置を保存
    original_pos = win32api.GetCursorPos()
    
    # マウスを移動してクリック（フォーカス取得）
    win32api.SetCursorPos((center_x, center_y))
    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, center_x, center_y, 0, 0)
    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, center_x, center_y, 0, 0)
    time.sleep(0.5)

    images = []
    
    for i in range(scrolls):
        # スクリーンショット取得（all_screens=True でマルチモニターの真っ黒画像を防止）
        img = ImageGrab.grab(bbox=bbox, all_screens=True)
        images.append(img)
        
        # 最後の1回以外はスクロールする
        if i < scrolls - 1:
            keyboard.send('page down')
            time.sleep(0.8) # スクロールアニメーションとレンダリング待ち

    # 元のマウス位置に戻す
    win32api.SetCursorPos(original_pos)

    # 縦に結合 (Stitching)
    total_width = images[0].width
    total_height = sum(img.height for img in images)
    
    stitched_image = Image.new('RGB', (total_width, total_height))
    
    y_offset = 0
    for img in images:
        stitched_image.paste(img, (0, y_offset))
        y_offset += img.height

    return stitched_image
