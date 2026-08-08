#!/usr/bin/env python3
"""
剪贴板管理器 - Windows 剪贴板历史记录工具
===========================================
后台监控剪贴板，记录所有复制内容（带时间戳）。
功能：搜索、自动清理、系统托盘运行、现代圆角界面。
"""

import tkinter as tk
from tkinter import ttk, messagebox
import tkinter.font as tkfont
import sqlite3
import hashlib
import threading
import queue
import time
import os
import sys
import math
from datetime import datetime, timedelta

# ============================================================
# Windows 高 DPI 感知（修复界面模糊的关键）
# ============================================================

def _enable_hidpi():
    """开启 Windows DPI 感知并返回界面缩放系数。

    未开启 DPI 感知时，Windows 会把 96 DPI 渲染的画面整体拉伸到实际缩放，
    导致 Tkinter 界面发虚。此函数必须在创建 Tk 根窗口之前调用。
    """
    scale = 1.0
    if sys.platform == "win32":
        try:
            import ctypes
            try:
                ctypes.windll.shcore.SetProcessDpiAwareness(1)  # SYSTEM_DPI_AWARE
            except Exception:
                try:
                    ctypes.windll.user32.SetProcessDPIAware()
                except Exception:
                    pass
            try:
                dpi = ctypes.windll.user32.GetDpiForSystem()
                if dpi:
                    scale = dpi / 96.0
            except Exception:
                pass
        except Exception:
            pass
    return scale


# 全局界面缩放系数（DPI / 96），布局尺寸乘以该系数以适配高分屏
UI_SCALE = _enable_hidpi()

def S(value):
    """将逻辑像素换算为当前 DPI 下的物理像素。"""
    return int(round(value * UI_SCALE))


# ============================================================
# 单实例控制（命名互斥锁 + 本地 socket 通知）
# ============================================================

SINGLE_INSTANCE_PORT = 47117
_instance_queue = queue.Queue()      # 线程安全：跨进程通知 -> 主线程轮询
_instance_mutex = None               # 保持互斥锁句柄引用


def _ensure_single_instance():
    """保证程序只有一个实例在运行。

    若已存在实例，则通知它显示主窗口并返回 False（本进程退出）；
    否则作为主实例启动一个监听线程，接收后续启动的"显示窗口"请求。
    """
    global _instance_mutex
    if sys.platform != "win32":
        return True
    try:
        import ctypes
        _instance_mutex = ctypes.windll.kernel32.CreateMutexW(
            None, False, "ClipboardManager_SingleInstance")
        if ctypes.windll.kernel32.GetLastError() == 183:   # ERROR_ALREADY_EXISTS
            try:
                import socket
                s = socket.create_connection(
                    ("127.0.0.1", SINGLE_INSTANCE_PORT), timeout=2)
                s.sendall(b"show\n")
                s.close()
            except Exception:
                pass
            return False
    except Exception:
        return True

    def _listen():
        try:
            import socket
            server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind(("127.0.0.1", SINGLE_INSTANCE_PORT))
            server.listen(2)
            server.settimeout(0.5)
            while True:
                try:
                    conn, _ = server.accept()
                except socket.timeout:
                    continue
                except OSError:
                    break
                try:
                    with conn:
                        data = conn.recv(64)
                        if data.strip() == b"show":
                            _instance_queue.put(("show_window", None))
                except Exception:
                    pass
        except Exception:
            pass
    threading.Thread(target=_listen, daemon=True).start()
    return True


# ============================================================
# 第三方依赖检查
# ============================================================

MISSING_DEPS = []
try:
    import pyperclip
except ImportError:
    MISSING_DEPS.append("pyperclip")
try:
    from PIL import Image, ImageDraw
except ImportError:
    MISSING_DEPS.append("Pillow")
try:
    import pystray
except ImportError:
    MISSING_DEPS.append("pystray")

if MISSING_DEPS:
    print("缺少依赖，请运行以下命令安装：")
    print(f"  pip install {' '.join(MISSING_DEPS)}")
    print("或运行 setup.bat 一键安装启动。")
    sys.exit(1)

# ============================================================
# 配置常量
# ============================================================

APP_NAME = "Clipboard"
APP_VERSION = "2.1.0"

def _get_app_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    else:
        return os.path.dirname(os.path.abspath(__file__))

APP_DIR = _get_app_dir()
DB_DIR = os.path.join(APP_DIR, "data")
DB_PATH = os.path.join(DB_DIR, "history.db")

POLL_INTERVAL = 0.5
QUEUE_CHECK_MS = 200
SEARCH_DEBOUNCE_MS = 300
CLEANUP_INTERVAL_MS = 3600000
MAX_DISPLAY_ENTRIES = 200

# ---- 现代渐变主题 ----

# 主色调
GRADIENT_TOP = "#5B6EF7"      # 靛蓝
GRADIENT_BOTTOM = "#8B7CF6"   # 紫罗兰

COLORS = {
    # 面板
    "bg_body": "#F4F5FA",
    "bg_card": "#FFFFFF",
    "bg_card_hover": "#F6F7FF",
    "bg_status": "#252836",

    # 渐变头
    "gradient_top": GRADIENT_TOP,
    "gradient_bottom": GRADIENT_BOTTOM,
    "header_text": "#FFFFFF",

    # 文字
    "text_primary": "#2D3146",
    "text_secondary": "#9DA3B5",
    "text_muted": "#C4C8D4",

    # 强调
    "accent": "#5B6EF7",
    "accent_hover": "#4A5DE0",
    "accent_light": "#EEF0FF",

    # 功能色
    "danger": "#FF6B7B",
    "danger_hover": "#E85565",
    "danger_light": "#FFF0F2",
    "success": "#34D399",
    "success_light": "#ECFDF5",
    "warning": "#FBBF24",

    # 边框（更柔和的颜色）
    "border": "#E9EAF1",
    "border_hover": "#C6CDF0",

    # 卡片左边框强调色（轮换）
    "card_accents": ["#5B6EF7", "#34D399", "#F59E0B", "#EC4899", "#6366F1", "#06B6D4"],

    # 自定义滚动条滑块颜色
    "scroll_thumb": "#C6CAE0",
    "scroll_thumb_hover": "#A9B0D6",
    "scroll_thumb_drag": "#8E95C6",
}

RETENTION_OPTIONS = [
    (7,  "保留 7 天"),
    (30, "保留 30 天"),
    (90, "保留 90 天"),
    (0,  "不自动清理"),
]

# ============================================================
# 渐变绘制工具
# ============================================================

def draw_gradient(canvas, width, height, color_top, color_bottom):
    """在 Canvas 上绘制平滑的垂直渐变（逐像素行，避免出现色带横纹）。"""
    canvas.delete("gradient")
    r1, g1, b1 = int(color_top[1:3], 16), int(color_top[3:5], 16), int(color_top[5:7], 16)
    r2, g2, b2 = int(color_bottom[1:3], 16), int(color_bottom[3:5], 16), int(color_bottom[5:7], 16)

    steps = max(2, height)
    for i in range(steps):
        t = i / (steps - 1)
        r = int(r1 + (r2 - r1) * t)
        g = int(g1 + (g2 - g1) * t)
        b = int(b1 + (b2 - b1) * t)
        color = f"#{r:02x}{g:02x}{b:02x}"
        y0 = int(i * height / steps)
        y1 = int((i + 1) * height / steps) + 1
        canvas.create_rectangle(0, y0, width, y1, fill=color, outline="", tags="gradient")


def draw_rounded_rect(canvas, x1, y1, x2, y2, radius, fill, outline="", width=1, tags=""):
    """在 Canvas 上绘制圆角矩形。"""
    points = [
        x1 + radius, y1,
        x2 - radius, y1,
        x2, y1,
        x2, y1 + radius,
        x2, y2 - radius,
        x2, y2,
        x2 - radius, y2,
        x1 + radius, y2,
        x1, y2,
        x1, y2 - radius,
        x1, y1 + radius,
        x1, y1,
    ]
    canvas.create_polygon(points, fill=fill, outline=outline, width=width,
                          smooth=True, tags=tags)


# ============================================================
# 数据库层（不变）
# ============================================================

class Database:
    def __init__(self, db_path=DB_PATH):
        db_dir = os.path.dirname(os.path.abspath(db_path))
        os.makedirs(db_dir, exist_ok=True)
        self.db_path = db_path
        self._local = threading.local()
        self._init_db()

    @property
    def conn(self):
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute("PRAGMA journal_mode=WAL")
        return self._local.conn

    def _init_db(self):
        c = self.conn.cursor()
        c.execute("""CREATE TABLE IF NOT EXISTS clipboard_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT NOT NULL, created_at TEXT NOT NULL, content_hash TEXT NOT NULL)""")
        c.execute("CREATE INDEX IF NOT EXISTS idx_created_at ON clipboard_history(created_at DESC)")
        c.execute("""CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY, value TEXT NOT NULL)""")
        c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('retention_days', '30')")
        self.conn.commit()

    def add_entry(self, content):
        content_hash = hashlib.md5(content.encode("utf-8")).hexdigest()
        c = self.conn.cursor()
        c.execute("SELECT content_hash FROM clipboard_history ORDER BY id DESC LIMIT 1")
        row = c.fetchone()
        if row and row["content_hash"] == content_hash:
            return None
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        c.execute("INSERT INTO clipboard_history (content, created_at, content_hash) VALUES (?, ?, ?)",
                  (content, now, content_hash))
        self.conn.commit()
        return c.lastrowid

    def delete_entry(self, entry_id):
        self.conn.execute("DELETE FROM clipboard_history WHERE id = ?", (entry_id,))
        self.conn.commit()

    def clear_all(self):
        self.conn.execute("DELETE FROM clipboard_history")
        self.conn.commit()

    def cleanup_old(self, days):
        if days <= 0: return 0
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
        c = self.conn.cursor()
        c.execute("DELETE FROM clipboard_history WHERE created_at < ?", (cutoff,))
        count = c.rowcount
        self.conn.commit()
        return count

    def search(self, query, limit=MAX_DISPLAY_ENTRIES):
        c = self.conn.cursor()
        if query:
            c.execute("SELECT id, content, created_at FROM clipboard_history "
                      "WHERE content LIKE ? ORDER BY id DESC LIMIT ?", (f"%{query}%", limit))
        else:
            c.execute("SELECT id, content, created_at FROM clipboard_history "
                      "ORDER BY id DESC LIMIT ?", (limit,))
        return c.fetchall()

    def get_recent(self, limit=MAX_DISPLAY_ENTRIES):
        return self.search(None, limit)

    def get_count(self):
        c = self.conn.cursor()
        c.execute("SELECT COUNT(*) as count FROM clipboard_history")
        return c.fetchone()["count"]

    def get_entry_by_id(self, entry_id):
        c = self.conn.cursor()
        c.execute("SELECT id, content, created_at FROM clipboard_history WHERE id = ?", (entry_id,))
        return c.fetchone()

    def get_setting(self, key, default=None):
        c = self.conn.cursor()
        c.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = c.fetchone()
        return row["value"] if row else default

    def set_setting(self, key, value):
        self.conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                          (key, str(value)))
        self.conn.commit()


# ============================================================
# 剪贴板监控线程（不变）
# ============================================================

class ClipboardMonitor(threading.Thread):
    def __init__(self, database, ui_queue):
        super().__init__(daemon=True)
        self.db = database
        self.queue = ui_queue
        self._running = threading.Event()
        self._last_content = None

    def run(self):
        self._running.set()
        while self._running.is_set():
            try:
                content = pyperclip.paste()
                if isinstance(content, str) and content.strip() and content != self._last_content:
                    entry_id = self.db.add_entry(content.strip())
                    if entry_id is not None:
                        self.queue.put(("new_entry", entry_id))
                    self._last_content = content
            except Exception:
                pass
            time.sleep(POLL_INTERVAL)

    def stop(self):
        self._running.clear()


# ============================================================
# 现代滚动条（圆角滑块、可拖拽、悬停/拖拽高亮）
# ============================================================

class ModernScrollbar(tk.Canvas):
    """在 Canvas 上绘制的自定义滚动条：胶囊形滑块 + 轨迹。

    相比系统默认滚动条更纤细美观、更易拖拽，且支持悬停与拖拽状态反馈。
    """

    PAD = 2          # 轨迹与边缘间距
    MIN_LEN = S(30)  # 滑块最小长度

    def __init__(self, parent, command, width=16):
        super().__init__(parent, width=width, highlightthickness=0, bd=0,
                         bg=COLORS["bg_body"], cursor="hand2")
        self.command = command
        self._first, self._last = 0.0, 1.0
        self._dragging = False
        self._drag_offset = 0.0
        self._hover = False

        self.bind("<Configure>", lambda e: self._redraw())
        self.bind("<Enter>", lambda e: self._set_hover(True))
        self.bind("<Leave>", lambda e: self._set_hover(False))
        self.bind("<Button-1>", self._on_click)
        self.bind("<B1-Motion>", self._on_drag)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<MouseWheel>", self._on_wheel)

    # ---- 公共接口（由 canvas 的 yscrollcommand 调用） ----
    def set(self, first, last):
        self._first, self._last = float(first), float(last)
        self._redraw()

    # ---- 滑块几何 ----
    def _thumb(self):
        H = self.winfo_height()
        if H <= 0:
            return None
        T = H - 2 * self.PAD
        v = self._last - self._first                 # 可见比例
        length = max(v * T, min(self.MIN_LEN, T))
        start = self._first * T
        if start + length > T:
            start = max(0.0, T - length)
        return self.PAD + start, self.PAD + start + length

    # ---- 绘制 ----
    def _redraw(self):
        self.delete("all")
        W, H = self.winfo_width(), self.winfo_height()
        if W <= 0 or H <= 0:
            return
        t = self._thumb()
        if t is None:
            return
        y0, y1 = t
        if y1 - y0 < 1:
            return
        if self._dragging:
            color = COLORS["scroll_thumb_drag"]
        elif self._hover:
            color = COLORS["scroll_thumb_hover"]
        else:
            color = COLORS["scroll_thumb"]
        x0, x1 = self.PAD, W - self.PAD
        radius = min((x1 - x0) / 2, (y1 - y0) / 2, 8)   # 胶囊形
        draw_rounded_rect(self, x0, y0, x1, y1, radius, fill=color, outline="")

    def _set_hover(self, val):
        self._hover = val
        self._redraw()

    # ---- 事件 ----
    def _on_wheel(self, event):
        self.command("scroll", int(-4 * (event.delta / 120)), "units")
        return "break"

    def _on_click(self, event):
        t = self._thumb()
        if t is None:
            return "break"
        y0, y1 = t
        if y0 <= event.y <= y1:
            self._dragging = True
            self._drag_offset = event.y - y0
            self._redraw()
        else:
            # 点击滑块上方/下方：整页翻动
            self.command("scroll", -1 if event.y < y0 else 1, "pages")
        return "break"

    def _on_drag(self, event):
        if not self._dragging:
            return "break"
        H = self.winfo_height()
        if H <= 0:
            return "break"
        T = H - 2 * self.PAD
        t = self._thumb()
        length = (t[1] - t[0]) if t else 0
        start = event.y - self.PAD - self._drag_offset
        start = max(0.0, min(T - length, start))
        first = (start / T) if T > 0 else 0.0
        self.command("moveto", first)
        return "break"

    def _on_release(self, event):
        self._dragging = False
        self._redraw()


# ============================================================
# 设置对话框
# ============================================================

class SettingsDialog:
    def __init__(self, parent, database, on_save_callback):
        self.db = database
        self.on_save = on_save_callback

        self.dialog = tk.Toplevel(parent)
        self.dialog.title("设置")
        self.dialog.geometry(f"{S(340)}x{S(320)}")
        self.dialog.configure(bg=COLORS["bg_body"])
        self.dialog.resizable(False, False)
        self.dialog.transient(parent)
        self.dialog.grab_set()

        self._build_ui()
        self._load_current_setting()
        self._size_and_center(parent)

    def _size_and_center(self, parent):
        """按内容实际尺寸调整对话框大小并居中，避免按钮被裁切。"""
        self.dialog.update_idletasks()
        content_w = self.content.winfo_reqwidth()
        content_h = self.content.winfo_reqheight()
        dw = max(S(340), content_w + S(48))      # 左右各 S(24) 内边距
        dh = S(52) + content_h + S(40)           # 标题栏 + 内容 + 上下边距
        pw, ph = parent.winfo_width(), parent.winfo_height()
        px, py = parent.winfo_rootx(), parent.winfo_rooty()
        x = px + (pw - dw) // 2
        y = py + (ph - dh) // 2
        self.dialog.geometry(f"{dw}x{dh}+{x}+{y}")

    def _build_ui(self):
        # 渐变标题栏
        header_canvas = tk.Canvas(self.dialog, height=S(52), highlightthickness=0, bg=COLORS["gradient_top"])
        header_canvas.pack(fill=tk.X)
        draw_gradient(header_canvas, S(400), S(52), COLORS["gradient_top"], COLORS["gradient_bottom"])
        header_canvas.create_text(S(24), S(26), text="⚙  设置", anchor="w",
                                  fill="white", font=("Microsoft YaHei UI", 13, "bold"))

        # 内容区
        self.content = tk.Frame(self.dialog, bg=COLORS["bg_body"])
        self.content.pack(fill=tk.BOTH, expand=True, padx=S(24), pady=S(20))

        tk.Label(self.content, text="自动清理时间范围", bg=COLORS["bg_body"],
                 fg=COLORS["text_primary"], font=("Microsoft YaHei UI", 11, "bold")).pack(anchor="w")

        tk.Label(self.content, text="超过所选天数的记录将被自动清除", bg=COLORS["bg_body"],
                 fg=COLORS["text_secondary"], font=("Microsoft YaHei UI", 9)).pack(anchor="w", pady=(S(2), S(14)))

        self.var = tk.IntVar(value=1)

        for i, (days, label) in enumerate(RETENTION_OPTIONS):
            frame = tk.Frame(self.content, bg=COLORS["bg_body"])
            frame.pack(fill=tk.X, pady=S(2))

            rb = tk.Radiobutton(
                frame, text=label, variable=self.var, value=i,
                bg=COLORS["bg_body"], fg=COLORS["text_primary"],
                activebackground=COLORS["bg_body"], activeforeground=COLORS["accent"],
                selectcolor=COLORS["bg_body"],
                font=("Microsoft YaHei UI", 10), cursor="hand2", anchor="w",
            )
            rb.pack(side=tk.LEFT)
            if days == 30:
                tk.Label(frame, text="推荐", bg=COLORS["accent_light"], fg=COLORS["accent"],
                         font=("Microsoft YaHei UI", 8), padx=S(6), pady=S(1)).pack(side=tk.LEFT, padx=S(8))

        # 按钮
        btn_frame = tk.Frame(self.content, bg=COLORS["bg_body"])
        btn_frame.pack(fill=tk.X, pady=(S(20), S(4)))

        tk.Button(btn_frame, text="取消", font=("Microsoft YaHei UI", 10),
                  bg=COLORS["border"], fg=COLORS["text_primary"],
                  activebackground=COLORS["text_muted"], relief=tk.FLAT,
                  cursor="hand2", padx=S(24), pady=S(8),
                  command=self.dialog.destroy).pack(side=tk.RIGHT, padx=(S(8), 0))

        tk.Button(btn_frame, text="保存", font=("Microsoft YaHei UI", 10, "bold"),
                  bg=COLORS["accent"], fg="white",
                  activebackground=COLORS["accent_hover"], relief=tk.FLAT,
                  cursor="hand2", padx=S(24), pady=S(8),
                  command=self._on_save).pack(side=tk.RIGHT)

    def _load_current_setting(self):
        days_str = self.db.get_setting("retention_days", "30")
        try:
            days = int(days_str)
        except ValueError:
            days = 30
        for i, (d, _) in enumerate(RETENTION_OPTIONS):
            if d == days:
                self.var.set(i)
                break

    def _on_save(self):
        idx = self.var.get()
        days = RETENTION_OPTIONS[idx][0]
        self.db.set_setting("retention_days", str(days))
        self.dialog.destroy()
        self.on_save()


# ============================================================
# 主窗口
# ============================================================

class ClipboardManager:
    def __init__(self):
        self.db = Database()
        self.ui_queue = queue.Queue()

        # 主窗口
        self.root = tk.Tk()
        self.root.title(APP_NAME)
        self.root.configure(bg=COLORS["bg_body"])

        # 确保字体点阵换算使用真实 DPI（避免高分屏下文字过小/发虚）
        try:
            dpi = self.root.winfo_fpixels("1i")
            if dpi > 0:
                self.root.tk.call("tk", "scaling", dpi / 72.0)
        except Exception:
            pass

        w, h = S(580), S(700)
        self.root.geometry(f"{w}x{h}")
        self.root.minsize(S(440), S(520))
        self._center_window(w, h)

        # 字体（点值自动随 DPI 缩放，无需乘以缩放系数）
        self._init_fonts()

        # 构建 UI
        self._build_header()
        self._build_search_bar()
        self._build_list_area()
        self._build_status_bar()

        # 系统托盘
        self.tray_icon = None
        self._setup_tray()

        self.root.protocol("WM_DELETE_WINDOW", self.hide_window)
        self.root.bind("<Control-f>", lambda e: self.search_entry.focus_set())
        self.root.bind("<Escape>", lambda e: self._clear_search())

        # 启动
        self.monitor = ClipboardMonitor(self.db, self.ui_queue)
        self.monitor.start()
        self._process_queue()
        self._refresh_list()
        self._run_cleanup()
        self._schedule_cleanup()

    def _init_fonts(self):
        self._font_time = tkfont.Font(family="Consolas", size=9)
        self._font_content = tkfont.Font(family="Microsoft YaHei UI", size=10)
        self._font_hint = tkfont.Font(family="Microsoft YaHei UI", size=8)

    def _center_window(self, w, h):
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        self.root.geometry(f"{w}x{h}+{(sw - w)//2}+{(sh - h)//2}")

    # ================================================================
    # 顶部渐变标题栏（圆角底部）
    # ================================================================

    def _build_header(self):
        self.header_height = S(56)
        self.header_canvas = tk.Canvas(
            self.root, height=self.header_height,
            highlightthickness=0, bg=COLORS["gradient_top"]
        )
        self.header_canvas.pack(fill=tk.X)
        self.header_canvas.bind("<Configure>", self._redraw_header)

        # 真正的设置按钮（在 _redraw_header 中通过 create_window 定位）
        self.settings_btn = tk.Label(
            self.root, text="  ⚙  设置  ", fg="white",
            bg=COLORS["accent"], font=("Microsoft YaHei UI", 10, "bold"),
            cursor="hand2", padx=S(10), pady=S(4),
        )
        self.settings_btn.bind("<Button-1>", lambda e: self._open_settings())
        self.settings_btn.bind("<Enter>", lambda e: self.settings_btn.configure(
            bg=COLORS["accent_hover"]))
        self.settings_btn.bind("<Leave>", lambda e: self.settings_btn.configure(
            bg=COLORS["accent"]))

        # 延迟绘制（窗口映射后才有正确宽度）
        self.root.after(200, self._redraw_header)

    def _redraw_header(self, event=None):
        w = self.root.winfo_width()
        if w < 50:
            return  # 窗口还没映射好，等下次 Configure 事件
        h = self.header_height

        # ---- 清空 Canvas 全部内容后重绘 ----
        self.header_canvas.delete("all")

        draw_gradient(self.header_canvas, w, h, COLORS["gradient_top"], COLORS["gradient_bottom"])

        # 底部圆角：用背景色在左右下角切出 1/4 圆
        r = S(16)
        self.header_canvas.create_arc(-1, h - 2 * r, 2 * r, h + 1,
                                      start=180, extent=90, style="pieslice",
                                      fill=COLORS["bg_body"], outline="")
        self.header_canvas.create_arc(w - 2 * r, h - 2 * r, w + 1, h + 1,
                                      start=270, extent=90, style="pieslice",
                                      fill=COLORS["bg_body"], outline="")

        # App 标题
        self.header_canvas.create_text(
            S(20), h // 2 - 1, anchor="w", text="📋 剪贴板管理器",
            fill="white", font=("Microsoft YaHei UI", 14, "bold"),
        )

        # ---- 设置按钮：用 create_window 嵌入真正的 Label 控件 ----
        btn_w = S(80)
        self.header_canvas.create_window(
            w - btn_w // 2 - S(14), h // 2,
            window=self.settings_btn, anchor="center",
        )
        self.settings_btn.lift()

    # ================================================================
    # 搜索栏（圆角输入框）
    # ================================================================

    def _build_search_bar(self):
        bar = tk.Frame(self.root, bg=COLORS["bg_body"], height=S(58))
        bar.pack(fill=tk.X, padx=S(18), pady=(S(14), S(4)))
        bar.pack_propagate(False)

        self.search_canvas = tk.Canvas(bar, height=S(40), highlightthickness=0,
                                       bd=0, bg=COLORS["bg_body"])
        self.search_canvas.pack(fill=tk.X, pady=S(8))
        self.search_canvas.bind("<Configure>", self._redraw_search)

        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", self._on_search_change)
        self.search_entry = tk.Entry(
            self.search_canvas, textvariable=self.search_var,
            font=("Microsoft YaHei UI", 11),
            bg="white", fg=COLORS["text_primary"],
            insertbackground=COLORS["accent"],
            relief=tk.FLAT, bd=0, highlightthickness=0,
        )
        self._setup_placeholder()
        self._redraw_search()

    def _redraw_search(self, event=None):
        c = self.search_canvas
        w = c.winfo_width()
        h = c.winfo_height()
        if w <= 10:
            return
        c.delete("all")

        r = S(12)
        draw_rounded_rect(c, 0, 0, w, h, r, fill="white", outline=COLORS["border"])

        # 放大镜
        icon_x = S(18)
        c.create_text(icon_x, h // 2, text="🔍", fill=COLORS["text_secondary"],
                      font=("Segoe UI Emoji", 11), anchor="w")

        # 输入框
        entry_x = S(42)
        entry_w = w - entry_x - S(46)
        if entry_w > 20:
            c.create_window(entry_x, h // 2, window=self.search_entry, anchor="w", width=entry_w)

        # 清除按钮
        c.create_text(w - S(22), h // 2, text="✕", fill=COLORS["text_muted"],
                      font=("Segoe UI", 12), tags="clear_btn")
        c.tag_bind("clear_btn", "<Button-1>", lambda e: self._clear_search())
        c.tag_bind("clear_btn", "<Enter>",
                   lambda e: c.itemconfigure("clear_btn", fill=COLORS["danger"]))
        c.tag_bind("clear_btn", "<Leave>",
                   lambda e: c.itemconfigure("clear_btn", fill=COLORS["text_muted"]))
        self._update_clear_btn()

    def _setup_placeholder(self):
        self._placeholder_text = "搜索剪贴板历史..."
        self._placeholder_active = True

        def on_focus_in(e):
            if self._placeholder_active:
                self.search_entry.delete(0, tk.END)
                self.search_entry.config(fg=COLORS["text_primary"])
                self._placeholder_active = False
            self._update_clear_btn()

        def on_focus_out(e):
            if not self.search_var.get().strip():
                self.search_entry.delete(0, tk.END)
                self.search_entry.insert(0, self._placeholder_text)
                self.search_entry.config(fg=COLORS["text_secondary"])
                self._placeholder_active = True
            self._update_clear_btn()

        self.search_entry.bind("<FocusIn>", on_focus_in)
        self.search_entry.bind("<FocusOut>", on_focus_out)
        self.search_entry.insert(0, self._placeholder_text)

    def _update_clear_btn(self):
        if not hasattr(self, "search_canvas"):
            return
        show = bool(self.search_var.get().strip()) and not self._placeholder_active
        try:
            self.search_canvas.itemconfigure("clear_btn", state="normal" if show else "hidden")
        except tk.TclError:
            pass

    def _on_search_change(self, *args):
        if self._placeholder_active:
            return
        self._update_clear_btn()
        if hasattr(self, "_search_timer") and self._search_timer:
            self.root.after_cancel(self._search_timer)
        self._search_timer = self.root.after(SEARCH_DEBOUNCE_MS, self._do_search)

    def _do_search(self):
        query = self.search_var.get().strip()
        if self._placeholder_active:
            query = ""
        self._refresh_list(query)

    def _clear_search(self):
        self.search_var.set("")
        self._refresh_list()
        self._update_clear_btn()

    # ================================================================
    # 列表区域（卡片直接绘制在 Canvas 上，支持圆角与悬停）
    # ================================================================

    def _build_list_area(self):
        list_container = tk.Frame(self.root, bg=COLORS["bg_body"])
        list_container.pack(fill=tk.BOTH, expand=True, padx=S(14))

        self.canvas = tk.Canvas(list_container, bg=COLORS["bg_body"],
                                highlightthickness=0, bd=0)

        self.scrollbar = ModernScrollbar(list_container, command=self.canvas.yview,
                                         width=S(16))
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.canvas.bind("<MouseWheel>", self._on_mousewheel)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas.bind("<Motion>", self._on_canvas_motion)
        self.canvas.bind("<Leave>", self._on_canvas_leave)

        # 滚动条：更粗、更短（上下留白），呈悬浮式胶囊
        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y, pady=S(26), padx=(S(4), 0))
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._cards = []           # 卡片数据列表
        self._rows = []            # 当前查询结果
        self._current_query = ""
        self._hover_index = None
        self._scroll_height = 0
        self._render_job = None

    def _on_canvas_configure(self, event):
        # 窗口缩放时防抖重绘（保证文字换行宽度正确）
        if self._render_job:
            self.root.after_cancel(self._render_job)
        self._render_job = self.root.after(80, self._render_cards)

    def _on_mousewheel(self, event):
        self._hide_tooltip()
        self.canvas.yview_scroll(int(-4 * (event.delta / 120)), "units")
        return "break"

    # ================================================================
    # 状态栏
    # ================================================================

    def _build_status_bar(self):
        status = tk.Frame(self.root, bg=COLORS["bg_status"], height=S(40))
        status.pack(fill=tk.X, side=tk.BOTTOM)
        status.pack_propagate(False)

        self.status_label = tk.Label(
            status, text="", bg=COLORS["bg_status"],
            fg="#8890A8", font=("Microsoft YaHei UI", 9),
        )
        self.status_label.pack(side=tk.LEFT, padx=S(18), pady=S(10))

        clear_btn = tk.Label(
            status, text="清空全部记录", bg=COLORS["bg_status"],
            fg="#8890A8", font=("Microsoft YaHei UI", 9), cursor="hand2",
        )
        clear_btn.pack(side=tk.RIGHT, padx=S(18), pady=S(10))
        clear_btn.bind("<Button-1>", lambda e: self._clear_all())
        clear_btn.bind("<Enter>", lambda e: clear_btn.configure(fg=COLORS["danger"]))
        clear_btn.bind("<Leave>", lambda e: clear_btn.configure(fg="#8890A8"))

    # ================================================================
    # 卡片渲染（Canvas 圆角卡片）
    # ================================================================

    def _refresh_list(self, query=""):
        self._current_query = query
        self._rows = self.db.search(query) if query else self.db.get_recent()
        self._render_cards()

        total = self.db.get_count()
        if query:
            self.status_label.config(text=f"搜索到 {len(self._rows)} 条  ·  共 {total} 条记录")
        else:
            self.status_label.config(text=f"共 {total} 条记录")
        self.canvas.yview_moveto(0)

    def _render_cards(self):
        self.canvas.delete("list")
        self._cards = []
        self._hover_index = None

        W = self.canvas.winfo_width()
        if not self._rows:
            self._draw_empty()
            self._scroll_height = 0
            self.canvas.configure(scrollregion=(0, 0, max(W, 1), 1))
            return
        if W <= 20:
            return  # 尚未映射完成，等待 Configure 事件

        x0, x1 = S(2), W - S(2)
        y = S(2)
        card_w = x1 - x0
        for idx, row in enumerate(self._rows):
            accent = COLORS["card_accents"][idx % len(COLORS["card_accents"])]
            h = self._card_height(card_w, row["content"])
            self._cards.append({
                "idx": idx, "entry_id": row["id"], "content": row["content"],
                "created_at": row["created_at"], "accent": accent,
                "x0": x0, "y0": y, "w": card_w, "h": h,
            })
            self._draw_card(idx)
            y += h + S(8)

        self._scroll_height = y
        self.canvas.configure(scrollregion=(0, 0, W, y))

    def _card_height(self, card_w, content):
        text_w = card_w - S(36)
        lines = self._preview_lines(content, self._font_content, text_w, 3)
        content_h = len(lines) * self._font_content.metrics("linespace")
        hint_h = (self._font_hint.metrics("linespace") + S(4)) if "\n" in content else 0
        return S(12) + self._font_time.metrics("linespace") + S(8) + content_h + hint_h + S(12)

    @staticmethod
    def _preview_lines(content, font, max_w, max_lines=3):
        """将内容按宽度换行，最多保留 max_lines 行，超出加省略号。"""
        text = content.replace("\r\n", "\n")
        if len(text) > 600:
            text = text[:600]
        lines = []
        for raw in text.split("\n"):
            cur = ""
            for ch in raw:
                if font.measure(cur + ch) <= max_w:
                    cur += ch
                else:
                    lines.append(cur)
                    cur = ch
            lines.append(cur)
        if len(lines) > max_lines:
            lines = lines[:max_lines]
            lines[-1] = lines[-1][:-1] + "…"
        return lines

    def _draw_card(self, idx):
        card = self._cards[idx]
        c = self.canvas
        x0, y0, card_w, h = card["x0"], card["y0"], card["w"], card["h"]
        entry_id = card["entry_id"]
        accent = card["accent"]
        tag_base = f"card_{idx}"

        hovered = (idx == self._hover_index)
        bg = COLORS["bg_card_hover"] if hovered else "white"
        border = COLORS["border_hover"] if hovered else COLORS["border"]

        # 卡片背景（圆角 + 柔和描边）
        draw_rounded_rect(c, x0, y0, x0 + card_w, y0 + h, S(11),
                          fill=bg, outline=border, width=1, tags=(f"list", tag_base))

        # 左侧颜色强调条
        draw_rounded_rect(c, x0 + S(3), y0 + S(9), x0 + S(7), y0 + h - S(9), S(2),
                          fill=accent, outline="", tags=(f"list", tag_base))

        content_x = x0 + S(18)
        text_w = card_w - S(36)
        time_y = y0 + S(12) + self._font_time.metrics("ascent")

        # 时间
        c.create_text(content_x, time_y, text=self._format_time(card["created_at"]),
                      anchor="w", fill=COLORS["text_secondary"], font=self._font_time,
                      tags=(f"list", tag_base))

        # 操作图标（复制 / 删除）—— 矢量图标，悬停变色 + 悬浮提示
        del_x = x0 + card_w - S(16)
        copy_x = del_x - S(26)
        self._draw_copy_icon(idx, copy_x, time_y, accent)
        self._draw_delete_icon(idx, del_x, time_y, COLORS["text_muted"])

        def on_copy_enter(e, i=entry_id):
            c.itemconfigure(f"copy_{idx}_f", fill=COLORS["accent_hover"])
            self._show_tooltip("复制", e)
        def on_copy_leave(e):
            c.itemconfigure(f"copy_{idx}_f", fill=accent)
            self._hide_tooltip()
        def on_del_enter(e, i=entry_id):
            c.itemconfigure(f"del_{idx}", fill=COLORS["danger"])
            self._show_tooltip("删除", e)
        def on_del_leave(e):
            c.itemconfigure(f"del_{idx}", fill=COLORS["text_muted"])
            self._hide_tooltip()

        c.tag_bind(f"copy_{idx}", "<Button-1>", lambda e, i=entry_id: self._copy_entry(i))
        c.tag_bind(f"copy_{idx}", "<Enter>", on_copy_enter)
        c.tag_bind(f"copy_{idx}", "<Leave>", on_copy_leave)
        c.tag_bind(f"del_{idx}", "<Button-1>", lambda e, i=entry_id: self._delete_entry(i))
        c.tag_bind(f"del_{idx}", "<Enter>", on_del_enter)
        c.tag_bind(f"del_{idx}", "<Leave>", on_del_leave)
        c.tag_bind(tag_base, "<Double-Button-1>",
                   lambda e, i=entry_id: self._copy_entry(i))

        # 内容预览
        lines = self._preview_lines(card["content"], self._font_content, text_w, 3)
        line_h = self._font_content.metrics("linespace")
        content_y = y0 + S(12) + self._font_time.metrics("linespace") + S(8)
        for i, line in enumerate(lines):
            c.create_text(content_x, content_y + i * line_h, text=line, anchor="nw",
                          fill=COLORS["text_primary"], font=self._font_content,
                          tags=(f"list", tag_base))

        # 多行内容提示
        if "\n" in card["content"]:
            hint_y = content_y + len(lines) * line_h + S(4) + self._font_hint.metrics("ascent")
            c.create_text(content_x, hint_y, text="多行内容 · 双击查看全部", anchor="w",
                          fill=COLORS["text_muted"], font=self._font_hint,
                          tags=(f"list", tag_base))

    def _redraw_card(self, idx):
        if not (0 <= idx < len(self._cards)):
            return
        self.canvas.delete(f"card_{idx}")
        self.canvas.delete(f"copy_{idx}")
        self.canvas.delete(f"del_{idx}")
        self._draw_card(idx)

    # ------------------------------------------------------------
    # 矢量图标
    # ------------------------------------------------------------

    def _draw_copy_icon(self, idx, cx, cy, color):
        """绘制"复制"图标：两个叠放的圆角方块（经典复制样式）。

        两图标采用相同外框与中心点，保证与删除图标对齐。
        """
        c = self.canvas
        tag = f"copy_{idx}"
        c.delete(tag)
        s = S(13)
        r = max(1.5, s * 0.15)
        # 背面（浅灰描边，略向右上偏移）
        draw_rounded_rect(c, cx - s*0.30, cy - s*0.70, cx + s*0.70, cy + s*0.30,
                          r, fill="", outline="#C9CDE0", width=1.5,
                          tags=(tag, f"{tag}_b"))
        # 正面（主色实心）
        draw_rounded_rect(c, cx - s*0.50, cy - s*0.50, cx + s*0.50, cy + s*0.50,
                          r, fill=color, outline="", tags=(tag, f"{tag}_f"))

    def _draw_delete_icon(self, idx, cx, cy, color):
        """绘制"删除"图标：粗壮的垃圾桶（把手 + 盖 + 梯形桶身）。"""
        c = self.canvas
        tag = f"del_{idx}"
        c.delete(tag)
        s = S(18)   # 约上一版(13)的 1.3 倍
        # 把手
        draw_rounded_rect(c, cx - s*0.13, cy - s*0.46, cx + s*0.13, cy - s*0.36,
                          s*0.04, fill=color, outline="", tags=tag)
        # 盖子（更宽）
        c.create_polygon([cx - s*0.40, cy - s*0.36, cx + s*0.40, cy - s*0.36,
                          cx + s*0.31, cy - s*0.28, cx - s*0.31, cy - s*0.28],
                         fill=color, outline="", tags=tag)
        # 桶身（上宽下窄，整体更粗壮）
        c.create_polygon([cx - s*0.35, cy - s*0.28, cx + s*0.35, cy - s*0.28,
                          cx + s*0.27, cy + s*0.38, cx - s*0.27, cy + s*0.38],
                         fill=color, outline="", tags=tag)

    # ------------------------------------------------------------
    # 悬浮提示（Tooltip）
    # ------------------------------------------------------------

    def _show_tooltip(self, text, event):
        try:
            if not hasattr(self, "_tip") or self._tip is None:
                self._tip = tk.Toplevel(self.root)
                self._tip.wm_overrideredirect(True)
                self._tip.wm_attributes("-topmost", True)
                try:
                    self._tip.wm_attributes("-toolwindow", True)
                except Exception:
                    pass
                frame = tk.Frame(self._tip, bg=COLORS["bg_status"], bd=0)
                frame.pack()
                self._tip_label = tk.Label(frame, text="", bg=COLORS["bg_status"],
                                           fg="white", font=("Microsoft YaHei UI", 9),
                                           padx=S(8), pady=S(4))
                self._tip_label.pack()
            self._tip_label.config(text=text)
            self._tip.update_idletasks()
            tw = self._tip.winfo_reqwidth()
            th = self._tip.winfo_reqheight()
            sw = self.root.winfo_screenwidth()
            sh = self.root.winfo_screenheight()
            x = event.x_root + 12
            y = event.y_root + 14
            if x + tw > sw:
                x = event.x_root - tw - 12
            if y + th > sh:
                y = event.y_root - th - 14
            self._tip.geometry(f"+{max(x, 0)}+{max(y, 0)}")
            self._tip.deiconify()
            self._tip.lift()
        except Exception:
            pass

    def _hide_tooltip(self):
        try:
            if hasattr(self, "_tip") and self._tip is not None:
                self._tip.withdraw()
        except Exception:
            pass

    def _hit_card(self, x, world_y):
        for card in self._cards:
            x0, y0, w, h = card["x0"], card["y0"], card["w"], card["h"]
            if x0 <= x <= x0 + w and y0 <= world_y <= y0 + h:
                return card["idx"]
        return None

    def _on_canvas_motion(self, event):
        if not self._cards or self._scroll_height <= 0:
            return
        top_px = self.canvas.yview()[0] * self._scroll_height
        idx = self._hit_card(event.x, event.y + top_px)
        if idx != self._hover_index:
            old = self._hover_index
            self._hover_index = idx
            if old is not None:
                self._redraw_card(old)
            if idx is not None:
                self._redraw_card(idx)

    def _on_canvas_leave(self, event):
        self._hide_tooltip()
        if self._hover_index is not None:
            old = self._hover_index
            self._hover_index = None
            self._redraw_card(old)

    def _draw_empty(self):
        c = self.canvas
        W = c.winfo_width()
        H = c.winfo_height()
        if W <= 10:
            return
        c.create_text(W // 2, H // 2 - S(40), text="📋",
                      font=("Segoe UI Emoji", 40), tags="list")
        c.create_text(W // 2, H // 2 + S(10), text="暂无剪贴板记录",
                      font=("Microsoft YaHei UI", 13, "bold"),
                      fill=COLORS["text_primary"], tags="list")
        c.create_text(W // 2, H // 2 + S(40), text="复制任意文字，即可自动记录在此处",
                      font=("Microsoft YaHei UI", 10),
                      fill=COLORS["text_secondary"], tags="list")

    @staticmethod
    def _format_time(created_at):
        try:
            dt = datetime.strptime(created_at, "%Y-%m-%d %H:%M:%S")
            now = datetime.now()
            diff = now - dt
            if diff < timedelta(minutes=1):
                return "刚刚"
            elif diff < timedelta(hours=1):
                return f"{int(diff.total_seconds()/60)} 分钟前"
            elif diff < timedelta(days=1):
                return f"{int(diff.total_seconds()/3600)} 小时前"
            elif diff < timedelta(days=7):
                return f"{diff.days} 天前"
            else:
                return created_at
        except (ValueError, TypeError):
            return created_at

    # ================================================================
    # 操作
    # ================================================================

    def _copy_entry(self, entry_id):
        self._hide_tooltip()
        row = self.db.get_entry_by_id(entry_id)
        if row:
            try:
                pyperclip.copy(row["content"])
                self._flash_status("已复制到剪贴板")
            except Exception as e:
                self._flash_status(f"复制失败: {e}")

    def _delete_entry(self, entry_id):
        self._hide_tooltip()
        self.db.delete_entry(entry_id)
        self._refresh_list(self._current_query)

    def _clear_all(self):
        result = messagebox.askyesno(
            "确认清空", "确定要清空所有剪贴板历史记录吗？\n此操作不可恢复。",
            parent=self.root, icon="warning")
        if result:
            self.db.clear_all()
            self._refresh_list()

    # ================================================================
    # 设置 / 清理 / 托盘 / 队列 / 退出
    # ================================================================

    def _open_settings(self):
        SettingsDialog(self.root, self.db, self._run_cleanup)

    def _run_cleanup(self):
        days_str = self.db.get_setting("retention_days", "30")
        try:
            days = int(days_str)
        except ValueError:
            days = 30
        if days > 0:
            deleted = self.db.cleanup_old(days)
            if deleted > 0:
                self._flash_status(f"已自动清理 {deleted} 条过期记录")
                self._refresh_list()

    def _schedule_cleanup(self):
        self.root.after(CLEANUP_INTERVAL_MS, self._schedule_cleanup)

    def _setup_tray(self):
        icon_image = self._create_tray_image()
        menu = pystray.Menu(
            pystray.MenuItem("显示主窗口", self._tray_show, default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出", self._tray_exit),
        )
        self.tray_icon = pystray.Icon("clipboard_manager", icon_image, APP_NAME, menu)

    def _create_tray_image(self):
        size = 64
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.rounded_rectangle([10, 18, 54, 58], radius=6, fill="#5B6EF7")
        draw.rounded_rectangle([18, 28, 46, 50], radius=2, fill="white")
        draw.rectangle([22, 6, 42, 24], fill="#4A5DE0")
        draw.rounded_rectangle([22, 6, 42, 24], radius=4, fill="#5B6EF7")
        draw.rectangle([23, 34, 41, 37], fill="#C7D2FE")
        draw.rectangle([23, 39, 41, 42], fill="#C7D2FE")
        draw.rectangle([23, 44, 35, 47], fill="#C7D2FE")
        return img

    def _tray_show(self, icon=None, item=None):
        self.root.after(0, self.show_window)

    def _tray_exit(self, icon=None, item=None):
        self.root.after(0, self._quit_app)
        if icon:
            icon.stop()

    def _run_tray(self):
        try:
            self.tray_icon.run()
        except Exception:
            pass

    def hide_window(self):
        self._hide_tooltip()
        self.root.withdraw()
        if not hasattr(self, "_tray_started") or not self._tray_started:
            self._tray_started = True
            threading.Thread(target=self._run_tray, daemon=True).start()

    def show_window(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()
        self._refresh_list()

    def _process_queue(self):
        try:
            while True:
                msg_type, data = self.ui_queue.get_nowait()
                if msg_type == "new_entry":
                    if not self.search_var.get().strip() or self._placeholder_active:
                        self._refresh_list()
        except queue.Empty:
            pass
        # 单实例"显示主窗口"请求（来自再次启动的进程）
        try:
            while True:
                msg_type, data = _instance_queue.get_nowait()
                if msg_type == "show_window":
                    self.show_window()
        except queue.Empty:
            pass
        self.root.after(QUEUE_CHECK_MS, self._process_queue)

    def _flash_status(self, message):
        self.status_label.config(text=message)
        def restore():
            self.status_label.config(text=f"共 {self.db.get_count()} 条记录")
        self.root.after(2000, restore)

    def _quit_app(self):
        self.monitor.stop()
        if self.tray_icon:
            try:
                self.tray_icon.stop()
            except Exception:
                pass
        self.root.destroy()

    def run(self):
        self.root.mainloop()


# ============================================================
# 入口
# ============================================================

def main():
    if not _ensure_single_instance():
        return  # 已有实例在运行，已通知其显示主窗口
    app = ClipboardManager()
    app.run()

if __name__ == "__main__":
    main()
