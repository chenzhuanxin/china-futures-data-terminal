# -*- coding: utf-8 -*-
"""
启动本地服务，使「期货数据终端.html」获得完整离线能力：
  - 龙虎榜：直接读取 data/lhb/*.json 预抓快照（断网也可用）
  - 核心K线：新浪接口不可达时回退读取 data/kline_core/*.json

用法：
    python start_server.py              # 默认端口 8907
    python start_server.py --port 9000  # 指定端口

端口被占用时的处理：
  - 若该端口已在服务本页面（重复启动）→ 直接打开浏览器，不再重复监听；
  - 若被其它程序占用 → 自动向后寻找空闲端口（8908、8909…）并提示实际地址。
"""
import argparse
import os
import socket
import sys
import urllib.request
import webbrowser
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

BASE = os.path.dirname(os.path.abspath(__file__))
PORT = 8907
PAGE = "期货数据终端.html"
PROBE_PORTS = 20          # 端口被占用时向后尝试的次数


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=BASE, **kw)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt, *args):
        pass


def port_open(port: int, timeout: float = 0.5) -> bool:
    """该端口是否已有服务在监听。"""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout):
            return True
    except OSError:
        return False


def serves_our_page(port: int) -> bool:
    """该端口是否已经在服务本项目的页面（用于识别重复启动）。"""
    from urllib.parse import quote
    url = "http://127.0.0.1:%d/%s" % (port, quote(PAGE))
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(url, timeout=1.5) as r:
            head = r.read(2048).decode("utf-8", "ignore")
        return "国内期货全量数据终端" in head
    except Exception:                               # noqa: BLE001
        return False


def pick_port(start: int) -> int:
    """从 start 开始找一个可用端口；全都不可用则抛错。"""
    for p in range(start, start + PROBE_PORTS):
        if not port_open(p):
            return p
    raise SystemExit("[!] %d~%d 端口均被占用，请用 --port 指定其它端口"
                     % (start, start + PROBE_PORTS - 1))


def main():
    ap = argparse.ArgumentParser(description="国内期货全量数据终端 · 本地服务")
    ap.add_argument("--port", type=int, default=PORT, help="监听端口（默认 8907）")
    ap.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    args = ap.parse_args()

    if not os.path.exists(os.path.join(BASE, PAGE)):
        print("[!] 未找到 %s，请先运行 生成终端页面.py" % PAGE)
        return

    port = args.port

    # 端口已被占用：先判断是不是本项目已经在跑
    if port_open(port):
        if serves_our_page(port):
            url = "http://127.0.0.1:%d/%s" % (port, PAGE)
            print("=" * 62)
            print("  服务已经在运行，直接打开页面：")
            print("  %s" % url)
            print("=" * 62)
            if not args.no_browser:
                try:
                    webbrowser.open(url)
                except Exception:                   # noqa: BLE001
                    pass
            return
        old = port
        port = pick_port(port + 1)
        print("[i] 端口 %d 已被其它程序占用，改用 %d" % (old, port))

    url = "http://127.0.0.1:%d/%s" % (port, PAGE)
    try:
        httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    except OSError as e:
        print("[!] 无法监听端口 %d：%s" % (port, e))
        print("    请用 python start_server.py --port 9000 指定其它端口。")
        return

    with httpd:
        print("=" * 62)
        print("  国内期货数据终端 · 本地服务已启动")
        print("  地址：%s" % url)
        print("  数据目录：%s" % os.path.join(BASE, "data"))
        print("  按 Ctrl+C 停止服务")
        print("=" * 62)
        if not args.no_browser:
            try:
                webbrowser.open(url)
            except Exception:                       # noqa: BLE001
                pass
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n已停止。")


if __name__ == "__main__":
    main()
