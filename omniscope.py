import tkinter as tk
import sys
import os
import threading
import time
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from macro_engine import execute_chrome_macro, send_image_to_clipboard

# --- Configuration & Theme ---
C = {
    "bg":         "#0f1218",
    "fg":         "#ffffff",
    "accent":     "#00d2ff",
    "neon":       "#00d2ff",
    "text_dim":   "#2a5a88",
    "text_bright":"#c8e8ff",
    "success":    "#00ff88",
    "warning":    "#ffcc00",
    "error":      "#ff2055",
}
W_WIDTH, W_HEIGHT = 450, 250

class DownloadHandler(FileSystemEventHandler):
    def __init__(self, callback):
        self.callback = callback
        self.processed = set()

    def on_created(self, event):
        self._handle_event(event)

    def on_moved(self, event):
        self._handle_event(event, event.dest_path)

    def _handle_event(self, event, path=None):
        target_path = path or event.src_path
        if target_path.lower().endswith(".png"):
            if target_path in self.processed:
                return
            self.processed.add(target_path)
            self.callback(target_path)

class OmniScopeApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("OmniScope - 全自動モード")
        self.root.geometry(f"{W_WIDTH}x{W_HEIGHT+50}+100+100")
        self.root.configure(bg=C["bg"])
        self.root.attributes("-topmost", True)
        
        self.downloads_path = str(Path.home() / "Downloads")
        self.target_monitor = 1 # デフォルトのモニター
        self._build_ui()
        self._start_watchdog()

    def _build_ui(self):
        main_frame = tk.Frame(self.root, bg=C["bg"])
        main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)

        title_lbl = tk.Label(main_frame, text="OmniScope [Auto]", fg=C["neon"], bg=C["bg"], font=("Segoe UI", 16, "bold"))
        title_lbl.pack(anchor="w")

        desc = "【全自動モード】\nこのボタンを押すとChrome上でキャプチャが自動実行され、\nダウンロード完了後にクリップボードへ転送されます。"
        tk.Label(main_frame, text=desc, fg=C["text_bright"], bg=C["bg"], font=("Segoe UI", 9), justify=tk.LEFT).pack(anchor="w", pady=(5,10))

        # Monitor Selection
        tk.Label(main_frame, text="TARGET MONITOR", bg=C["bg"], fg=C["text_dim"], font=("Segoe UI", 9, "bold")).pack(anchor="w")
        mon_frame = tk.Frame(main_frame, bg=C["bg"])
        mon_frame.pack(fill=tk.X, pady=(2, 10))
        
        self.mon_btns = []
        for i in range(1, 4):
            btn = tk.Button(mon_frame, text=f"Monitor {i}", bg="#0a0c10", fg=C["text_bright"] if i == self.target_monitor else C["text_dim"],
                            font=("Segoe UI", 9), relief=tk.FLAT, cursor="hand2",
                            command=lambda n=i: self._set_monitor(n))
            btn.pack(side=tk.LEFT, padx=(0, 5), ipadx=8, ipady=2)
            self.mon_btns.append(btn)

        self.btn = tk.Button(main_frame, text="CAPTURE & COPY", bg=C["accent"], fg="#000000", font=("Segoe UI", 12, "bold"), 
                             relief=tk.FLAT, cursor="hand2", command=self.do_capture)
        self.btn.pack(fill=tk.X, ipady=8)

        self.status_lbl = tk.Label(main_frame, text="🟢 ダウンロードフォルダ監視中...", fg=C["success"], bg=C["bg"], font=("Segoe UI", 10))
        self.status_lbl.pack(pady=(10, 0))

    def _set_monitor(self, num):
        self.target_monitor = num
        for i, btn in enumerate(self.mon_btns):
            btn.config(fg=C["text_bright"] if (i+1) == num else C["text_dim"])

    def _start_watchdog(self):
        self.observer = Observer()
        handler = DownloadHandler(self._on_new_png)
        self.observer.schedule(handler, self.downloads_path, recursive=False)
        self.observer.start()

    def _on_new_png(self, filepath):
        self.root.after(0, lambda: self.status_lbl.config(text="📥 ダウンロードを検知、コピー中...", fg=C["warning"]))
        
        # Chromeがファイルの書き込みを終えるまで少し待つ
        time.sleep(1.0)
        
        success = send_image_to_clipboard(filepath)
        if success:
            msg = "✅ コピー完了！ (GeminiでCtrl+V)"
            color = C["success"]
        else:
            msg = "❌ コピー失敗 (ファイルが開けません)"
            color = C["error"]
            
        self.root.after(0, lambda: self.status_lbl.config(text=msg, fg=color))
        self.root.after(10000, lambda: self.status_lbl.config(text="🟢 ダウンロードフォルダ監視中...", fg=C["success"]))

    def do_capture(self):
        self.status_lbl.config(text=f"🚀 Monitor {self.target_monitor} で自動キャプチャ実行中...", fg=C["accent"])
        self.btn.config(state=tk.DISABLED)
        
        def _task():
            try:
                execute_chrome_macro(self.target_monitor)
            except Exception as e:
                self.root.after(0, lambda: self.status_lbl.config(text=f"❌ エラー: {e}", fg=C["error"]))
            finally:
                self.root.after(0, lambda: self.btn.config(state=tk.NORMAL))

        threading.Thread(target=_task, daemon=True).start()

    def _on_close(self):
        self.observer.stop()
        self.observer.join(timeout=1.0)
        self.root.destroy()
        sys.exit(0)

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    app = OmniScopeApp()
    app.root.protocol("WM_DELETE_WINDOW", app._on_close)
    app.root.mainloop()
