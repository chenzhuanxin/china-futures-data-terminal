# -*- coding: utf-8 -*-
"""
把 模板.html + vendor 依赖库 + data/*.json 打包为单文件 HTML。

产物：期货数据终端.html
     - 双击即可打开（无需本地服务器、无需联网即可查看行情快照 / 加权合约 / 分类 / 资讯链接）
     - K线、龙虎榜 通过 JSONP 直连新浪/东财实时获取
用法：
    C:/Python314/python.exe 生成终端页面.py
"""
import json
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
TPL = os.path.join(BASE, "模板.html")
OUT = os.path.join(BASE, "期货数据终端.html")
DATA = os.path.join(BASE, "data")
VENDOR = os.path.join(BASE, "vendor")

INLINE_FILES = {
    "contracts.json": "contracts",
    "varieties.json": "varieties",
    "categories.json": "categories",
    "weighted.json": "weighted",
    "newslinks.json": "newslinks",
    "lhb_index.json": "lhbIndex",
    "lhb_coverage.json": "lhbCoverage",
    "kline_core_index.json": "klineCoreIndex",
    "weighted_kline_index.json": "weightedKlineIndex",
    "meta.json": "meta",
}


def read_text(p, enc="utf-8"):
    with open(p, "r", encoding=enc) as f:
        return f.read()


def main():
    if not os.path.exists(TPL):
        sys.exit("找不到模板文件：%s" % TPL)

    payload = {}
    for fn, key in INLINE_FILES.items():
        p = os.path.join(DATA, fn)
        if os.path.exists(p):
            payload[key] = json.loads(read_text(p))
        else:
            payload[key] = {} if key in ("weighted", "newslinks", "lhbIndex",
                                         "lhbCoverage", "klineCoreIndex",
                                         "weightedKlineIndex", "meta") else []
            print("  [warn] 缺少 %s，已使用空数据占位" % fn)

    echarts = read_text(os.path.join(VENDOR, "echarts.min.js"))
    xlsx = read_text(os.path.join(VENDOR, "xlsx.full.min.js"))

    html = read_text(TPL)
    html = html.replace("/*__ECHARTS__*/", echarts)
    html = html.replace("/*__XLSX__*/", xlsx)
    data_js = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    html = html.replace("/*__DATA__*/{}", data_js)

    with open(OUT, "w", encoding="utf-8") as f:
        f.write(html)

    size = os.path.getsize(OUT)
    print("已生成：%s" % OUT)
    print("  文件大小：%.2f MB" % (size / 1024 / 1024))
    print("  内联数据：合约 %d 个 / 品种 %d 个 / 加权 %d 个 / 资讯 %d 个 / 龙虎榜索引 %d 个"
          % (len(payload.get("contracts") or []), len(payload.get("varieties") or []),
             len(payload.get("weighted") or {}), len(payload.get("newslinks") or {}),
             len(payload.get("lhbIndex") or {})))


if __name__ == "__main__":
    main()
