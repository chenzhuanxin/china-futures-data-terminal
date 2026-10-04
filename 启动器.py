# -*- coding: utf-8 -*-
"""
国内期货全量数据终端 · 一键启动器（打包为 exe）

功能：
  - 双击 exe 即启动内置本地服务（无需安装 Python）；
  - 自动用默认浏览器打开终端页面；
  - exe 与「期货数据终端.html」放在同一目录时直接服务该目录（离线快照全可用）；
  - 找不到页面文件时使用 exe 内置的页面副本（任何位置都能启动，联网功能可用）。

打包（PyInstaller）：
  python -m PyInstaller --noconfirm --onefile --windowed --name 国内期货数据终端
      --icon assets/logo.ico --add-data "期货数据终端.html;."
      --add-data "assets/logo.png;assets" --add-data "assets/logo.ico;assets"
      --version-file version.txt 启动器.py
"""
import os
import shutil
import socket
import sys
import tempfile
import threading
import urllib.parse
import urllib.request
import webbrowser
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
import tkinter as tk
from tkinter import messagebox, font as tkfont

APP_TITLE = "国内期货全量数据终端"
PAGE = "期货数据终端.html"
MARK = APP_TITLE                       # 识别"是否已在服务本页面"的关键字
PROBE_PORTS = 20                       # 端口冲突时向后尝试次数
DEFAULT_PORT = 8907


# ----------------------------------------------------------------------
# 路径
# ----------------------------------------------------------------------
def is_frozen() -> bool:
    return getattr(sys, "frozen", False)


def res_dir() -> str:
    """打包内资源目录（onefile 解包目录）/ 脚本目录。"""
    return sys._MEIPASS if is_frozen() else os.path.dirname(os.path.abspath(__file__))


def exe_dir() -> str:
    """exe 所在目录 / 脚本所在目录。"""
    return os.path.dirname(sys.executable) if is_frozen() else os.path.dirname(os.path.abspath(__file__))


def pick_base() -> str:
    """确定服务目录：优先 exe 旁的真实项目目录（离线快照 / 更新后页面即时生效）。"""
    d = exe_dir()
    if os.path.exists(os.path.join(d, PAGE)):
        return d
    # 兜底：把 exe 内置的页面副本解到临时目录再服务
    dst = os.path.join(tempfile.gettempdir(), "期货数据终端_app")
    os.makedirs(dst, exist_ok=True)
    src = os.path.join(res_dir(), PAGE)
    target = os.path.join(dst, PAGE)
    if not os.path.exists(target) or os.path.getsize(src) != os.path.getsize(target):
        shutil.copyfile(src, target)
    return dst


# ----------------------------------------------------------------------
# 端口探测
# ----------------------------------------------------------------------
def port_open(port: int, timeout: float = 0.4) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout):
            return True
    except OSError:
        return False


def serves_our_page(port: int) -> bool:
    url = "http://127.0.0.1:%d/%s" % (port, urllib.parse.quote(PAGE))
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(url, timeout=1.5) as r:
            return MARK in r.read(4096).decode("utf-8", "ignore")
    except Exception:                                   # noqa: BLE001
        return False


# ----------------------------------------------------------------------
# 本地 HTTP 服务
# ----------------------------------------------------------------------
def make_handler(base: str):
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=base, **kw)

        def end_headers(self):
            self.send_header("Cache-Control", "no-store")
            super().end_headers()

        def log_message(self, fmt, *args):              # 静默
            pass
    return Handler


# ----------------------------------------------------------------------
# 图形界面
# ----------------------------------------------------------------------
class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.httpd = None
        self.url = ""
        root.title(APP_TITLE)
        root.resizable(False, False)
        root.configure(bg="#f4f7fb")

        # 窗口图标
        ico = os.path.join(res_dir(), "assets", "logo.ico")
        if os.path.exists(ico):
            try:
                root.iconbitmap(ico)
            except Exception:                               # noqa: BLE001
                pass

        # 顶部横幅
        banner = tk.Frame(root, bg="#12275e")
        banner.pack(fill="x")
        png = os.path.join(res_dir(), "assets", "logo.png")
        self._logo = None
        if os.path.exists(png):
            try:
                self._logo = tk.PhotoImage(file=png).subsample(5, 5)
                tk.Label(banner, image=self._logo, bg="#12275e").pack(
                    side="left", padx=(16, 10), pady=12)
            except Exception:                               # noqa: BLE001
                pass
        head = tk.Frame(banner, bg="#12275e")
        head.pack(side="left", pady=12)
        tk.Label(head, text=APP_TITLE, bg="#12275e", fg="white",
                 font=("Microsoft YaHei UI", 14, "bold")).pack(anchor="w")
        tk.Label(head, text="本地服务 · 双击即用 · 红涨绿跌", bg="#12275e", fg="#9fc3ef",
                 font=("Microsoft YaHei UI", 9)).pack(anchor="w")

        # 状态区
        body = tk.Frame(root, bg="#f4f7fb")
        body.pack(fill="both", expand=True, padx=18, pady=14)
        self.status = tk.Label(body, text="正在启动本地服务…", bg="#f4f7fb",
                               fg="#33475e", font=("Microsoft YaHei UI", 10), anchor="w")
        self.status.pack(fill="x")
        self.addr = tk.Label(body, text="", bg="#f4f7fb", fg="#2563eb",
                             font=("Consolas", 10, "bold"), anchor="w", cursor="hand2")
        self.addr.pack(fill="x", pady=(2, 10))
        self.addr.bind("<Button-1>", lambda e: self.open_page())

        # 按钮
        btns = tk.Frame(root, bg="#f4f7fb")
        btns.pack(fill="x", padx=18, pady=(0, 6))
        f = ("Microsoft YaHei UI", 10)
        self.btn_open = tk.Button(btns, text="打开页面", command=self.open_page,
                                  bg="#2563eb", fg="white", activebackground="#1d4ed8",
                                  activeforeground="white", relief="flat", width=14,
                                  font=f, padx=8, pady=5, cursor="hand2")
        self.btn_open.pack(side="left", padx=(0, 10))
        self.btn_exit = tk.Button(btns, text="停止服务并退出", command=self.close,
                                  bg="#eef2f8", fg="#33475e", activebackground="#dde6f2",
                                  relief="flat", width=14, font=f, padx=8, pady=5,
                                  cursor="hand2")
        self.btn_exit.pack(side="left")
        tk.Label(root, text="关闭本窗口或点「停止服务并退出」即可停止服务；数据仅供学习研究，不构成投资建议。",
                 bg="#f4f7fb", fg="#8a99ad", font=("Microsoft YaHei UI", 8)).pack(
            fill="x", padx=18, pady=(0, 10))

        root.protocol("WM_DELETE_WINDOW", self.close)
        self.after_ids = []
        threading.Thread(target=self._startup, daemon=True).start()

    # -- 启动服务（后台线程，避免卡 UI） --
    def _startup(self):
        try:
            base = pick_base()
        except Exception as e:                              # noqa: BLE001
            self._ui(self._err, "初始化失败：" + str(e))
            return

        port, reuse = None, False
        for p in range(DEFAULT_PORT, DEFAULT_PORT + PROBE_PORTS):
            if not port_open(p):
                port = p
                break
            if serves_our_page(p):                          # 本项目已在运行
                port, reuse = p, True
                break
        if port is None:
            self._ui(self._err, "%d~%d 端口均被占用，请关闭其它程序后重试"
                     % (DEFAULT_PORT, DEFAULT_PORT + PROBE_PORTS - 1))
            return

        self.url = "http://127.0.0.1:%d/%s" % (port, urllib.parse.quote(PAGE))
        if reuse:
            self._ui(self._ok, "服务已在运行，直接打开页面。")
            webbrowser.open(self.url)
            return
        try:
            self.httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(base))
        except OSError as e:
            self._ui(self._err, "无法监听端口 %d：%s" % (port, e))
            return
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self._ui(self._ok, "服务已启动（目录：%s）" % base)
        webbrowser.open(self.url)

    # -- UI 辅助（跨线程安全） --
    def _ui(self, fn, *a):
        self.after_ids.append(self.root.after(0, lambda: fn(*a)))

    def _ok(self, msg):
        self.status.config(text=msg, fg="#0a7a48")
        self.addr.config(text=self.url + "　（点击也可打开）")

    def _err(self, msg):
        self.status.config(text=msg, fg="#c0392b")
        messagebox.showerror(APP_TITLE, msg)

    def open_page(self):
        if self.url:
            webbrowser.open(self.url)

    def close(self):
        if self.httpd:
            try:
                self.httpd.shutdown()
            except Exception:                               # noqa: BLE001
                pass
        self.root.destroy()


def main():
    root = tk.Tk()
    try:                                                    # 高分屏清晰化
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:                                       # noqa: BLE001
        pass
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
