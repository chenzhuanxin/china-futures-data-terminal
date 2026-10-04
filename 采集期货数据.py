# -*- coding: utf-8 -*-
"""
国内期货全量数据采集器
=======================================================================
数据源（全部为真实线上接口，无任何模拟数据）
  1. 东方财富 期货行情快照  https://futsseapi.eastmoney.com/list/{market}
  2. 东方财富 数据中心      https://datacenter-web.eastmoney.com/api/data/v1/get
       - RPT_FUTU_POSITIONCODE   合约字典
       - RPT_FUTU_FUTUREORGLIST  期货公司(会员)字典
       - RPT_FUTU_DAILYPOSITION  成交持仓 / 持仓结构 / 建仓过程
       - RPT_FUTU_AVGPPAL        持仓均价 / 盈亏分析
  3. 新浪财经 期货K线        https://stock2.finance.sina.com.cn/futures/api/jsonp.php/#/InnerFuturesNewService.*
  4. 新浪财经 期货实时       https://hq.sinajs.cn/list=nf_{code}

输出：同目录 data/*.json
用法：
    C:/Python314/python.exe 采集期货数据.py            # 全量采集
    C:/Python314/python.exe 采集期货数据.py --quick    # 跳过K线预抓与龙虎榜
=======================================================================
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import os
import re
import ssl
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, date

# ----------------------------------------------------------------------
# 基础 HTTP（直连，不走系统代理）
# ----------------------------------------------------------------------
ssl._create_default_https_context = ssl._create_unverified_context
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
LHB_DIR = os.path.join(DATA_DIR, "lhb")
KL_DIR = os.path.join(DATA_DIR, "kline_core")
WK_DIR = os.path.join(DATA_DIR, "weighted_kline")
os.makedirs(LHB_DIR, exist_ok=True)
os.makedirs(KL_DIR, exist_ok=True)
os.makedirs(WK_DIR, exist_ok=True)


def http_get(url: str, referer: str = "", timeout: int = 20, retries: int = 2) -> str:
    """带重试的 GET，返回解码后的文本。"""
    headers = {"User-Agent": UA, "Accept": "*/*"}
    if referer:
        headers["Referer"] = referer
    last = None
    for i in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=headers)
            return _OPENER.open(req, timeout=timeout).read().decode("utf-8", "ignore")
        except Exception as e:                      # noqa: BLE001
            last = e
            time.sleep(0.4 * (i + 1))
    raise last


def http_get_json(url: str, referer: str = "") -> dict:
    txt = http_get(url, referer)
    return json.loads(txt)


def load_json(path: str, default):
    """读取已落盘的 JSON；文件不存在或损坏时返回 default。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:                               # noqa: BLE001
        return default


# ----------------------------------------------------------------------
# 常量配置
# ----------------------------------------------------------------------
# market_id -> (交易所代码, 中文名, 简称, 该市场数据语义)
MARKETS = [
    ("113", "SHFE",  "上海期货交易所",     "上期所"),
    ("114", "DCE",   "大连商品交易所",     "大商所"),
    ("115", "CZCE",  "郑州商品交易所",     "郑商所"),
    ("225", "GFEX",  "广州期货交易所",     "广期所"),
    ("142", "INE",   "上海国际能源交易中心", "上期能源"),
    ("220", "CFFEX", "中国金融期货交易所",  "中金所"),
    ("8",   "CFFEX", "中国金融期货交易所",  "中金所"),
]
MARKET_NAME = {"113": "上期所", "114": "大商所", "115": "郑商所", "225": "广期所",
               "142": "上期能源", "220": "中金所", "8": "中金所", "159": "加权指数"}

# 东财 RPT_FUTU_* 的 TRADE_MARKET_CODE（取自数据中心官方品种字典，勿随意改动）
EM_TRADE_MARKET_CODE = {
    "113": "069001005",   # 上期所
    "115": "069001008",   # 郑商所
    "220": "069001009",   # 中金所
    "8":   "069001009",
    "114": "069001007",   # 大商所
    "225": "069001021",   # 广期所
    "142": "069001016",   # 上期能源
}
# 龙虎榜中合约代码使用小写的交易所
LHB_LOWER_EXCH = {"INE", "GFEX"}

# 中金所名称 -> 交易所标准品种码（按名称长度从长到短匹配）
CFFEX_NAME_CODE = [
    ("三十债", "TL"), ("中证1000股指", "IM"), ("中证500股指", "IC"),
    ("沪深", "IF"), ("上证", "IH"), ("二债", "TS"), ("五债", "TF"), ("十债", "T"),
]

# 品种 -> 板块（用于「按品种类型」分类）
SECTOR_MAP = {
    # 黑色建材
    "RB": "黑色建材", "HC": "黑色建材", "I": "黑色建材", "J": "黑色建材",
    "JM": "黑色建材", "SF": "黑色建材", "SM": "黑色建材", "SS": "黑色建材",
    "WR": "黑色建材", "ZC": "黑色建材", "FG": "黑色建材", "SA": "黑色建材",
    # 有色金属
    "CU": "有色金属", "AL": "有色金属", "ZN": "有色金属", "PB": "有色金属",
    "NI": "有色金属", "SN": "有色金属", "AO": "有色金属", "BC": "有色金属",
    "SI": "有色金属", "LC": "有色金属", "PS": "有色金属", "AD": "有色金属",
    # 贵金属
    "AU": "贵金属", "AG": "贵金属",
    # 能源化工
    "SC": "能源化工", "FU": "能源化工", "LU": "能源化工", "BU": "能源化工",
    "RU": "能源化工", "NR": "能源化工", "BR": "能源化工", "L": "能源化工",
    "PP": "能源化工", "V": "能源化工", "EG": "能源化工", "EB": "能源化工",
    "PG": "能源化工", "MA": "能源化工", "TA": "能源化工", "PX": "能源化工",
    "PF": "能源化工", "PR": "能源化工", "UR": "能源化工", "SP": "能源化工",
    "SH": "能源化工", "WH": "能源化工",
    # 农产品
    "M": "农产品", "Y": "农产品", "A": "农产品", "B": "农产品", "P": "农产品",
    "C": "农产品", "CS": "农产品", "JD": "农产品", "LH": "农产品", "RR": "农产品",
    "SR": "农产品", "CF": "农产品", "CY": "农产品", "OI": "农产品", "RM": "农产品",
    "RS": "农产品", "AP": "农产品", "CJ": "农产品", "PK": "农产品", "JR": "农产品",
    "RI": "农产品", "LR": "农产品", "PM": "农产品", "BB": "农产品", "FB": "农产品",
    # 金融
    "IF": "金融期货", "IH": "金融期货", "IC": "金融期货", "IM": "金融期货",
    "T": "金融期货", "TF": "金融期货", "TS": "金融期货", "TL": "金融期货",
    # 航运
    "EC": "航运指数",
}

# 有夜盘的品种（21:00 起，含夜盘时段交易）
NIGHT_VARIETIES = {
    # 上期所
    "CU", "AL", "ZN", "PB", "NI", "SN", "AU", "AG", "RB", "HC", "SS",
    "RU", "BU", "FU", "SP", "BR", "AO", "AD",
    # 上期能源
    "SC", "LU", "NR", "BC",
    # 大商所
    "A", "B", "M", "Y", "P", "C", "CS", "I", "J", "JM", "L", "V",
    "PP", "EG", "EB", "PG",
    # 郑商所
    "SR", "CF", "CY", "OI", "RM", "MA", "TA", "FG", "SA", "PF", "SH", "PX", "PR",
    # 广期所
    "SI", "LC", "PS",
}

# 品种中文名
VARIETY_CN = {
    "RB": "螺纹钢", "HC": "热轧卷板", "I": "铁矿石", "J": "焦炭", "JM": "焦煤",
    "SF": "硅铁", "SM": "锰硅", "SS": "不锈钢", "WR": "线材", "ZC": "动力煤",
    "FG": "玻璃", "SA": "纯碱", "CU": "沪铜", "AL": "沪铝", "ZN": "沪锌",
    "PB": "沪铅", "NI": "沪镍", "SN": "沪锡", "AO": "氧化铝", "BC": "国际铜",
    "SI": "工业硅", "LC": "碳酸锂", "PS": "多晶硅", "AD": "铸造铝合金",
    "AU": "沪金", "AG": "沪银", "SC": "原油", "FU": "燃料油", "LU": "低硫燃料油",
    "BU": "石油沥青", "RU": "天然橡胶", "NR": "20号胶", "BR": "丁二烯橡胶",
    "L": "塑料", "PP": "聚丙烯", "V": "聚氯乙烯", "EG": "乙二醇",
    "EB": "苯乙烯", "PG": "液化石油气", "MA": "甲醇", "TA": "PTA",
    "PX": "对二甲苯", "PF": "短纤", "PR": "瓶片", "UR": "尿素", "SP": "纸浆",
    "SH": "烧碱", "OP": "胶版印刷纸", "M": "豆粕", "Y": "豆油", "A": "豆一",
    "B": "豆二", "P": "棕榈油", "C": "玉米", "CS": "玉米淀粉", "JD": "鸡蛋",
    "LH": "生猪", "RR": "粳米", "SR": "白糖", "CF": "棉花", "CY": "棉纱",
    "OI": "菜籽油", "RM": "菜籽粕", "RS": "油菜籽", "AP": "苹果", "CJ": "红枣",
    "PK": "花生", "JR": "粳稻", "RI": "早籼稻", "LR": "晚籼稻", "PM": "普麦",
    "WH": "强麦", "BB": "胶合板", "FB": "纤维板", "IF": "沪深300",
    "IH": "上证50", "IC": "中证500", "IM": "中证1000", "T": "十年国债",
    "TF": "五年国债", "TS": "二年国债", "TL": "三十年国债", "EC": "集运指数(欧线)",
}

SECTOR_ORDER = ["黑色建材", "有色金属", "贵金属", "能源化工", "农产品", "金融期货", "航运指数", "其他"]

# 合约属性分类（非真实合约）
LINK_KINDS = [
    ("次主连", "sub_main_link", "次主连"),
    ("主连", "main_link", "主连"),
    ("加权", "index", "加权指数"),
    ("月均", "index", "月均价指数"),
    ("指数", "index", "指数"),
    ("当月连续", "month_link", "当月连续"),
    ("下月连续", "month_link", "下月连续"),
    ("下季连续", "month_link", "下季连续"),
    ("隔季连续", "month_link", "隔季连续"),
    ("连续", "continuous", "连续"),
]


def detect_kind(name: str) -> tuple[str, str]:
    """返回 (kind, kindLabel)。kind == 'real' 表示真实可交割合约。"""
    for kw, kind, label in LINK_KINDS:
        if kw in name:
            return kind, label
    return "real", "真实合约"


LINK_SUFFIX_KW = ["次主连", "主连", "当月连续", "下月连续", "下季连续", "隔季连续",
                  "连续", "加权", "月均", "指数", "当月", "下月", "下季", "隔季"]
# 英文俗称 -> 交易所品种代码
EN_ALIAS = {"PVC": "V", "PTA": "TA", "LPG": "PG", "PE": "L", "PP": "PP",
            "LLDPE": "L", "TOCOM": "RU"}


def cn_to_variety(cn: str, known: set[str]) -> str | None:
    """品种中文名 -> 品种代码。先按中文名精确匹配，再取最长前缀匹配。"""
    if not cn:
        return None
    cn = cn.strip()
    for k, v in VARIETY_CN.items():
        if k in known and cn == v:
            return k
    best_k = None
    for k, v in VARIETY_CN.items():
        if k not in known or len(v) < 2:
            continue
        if cn.startswith(v) or v.startswith(cn):
            if best_k is None or len(VARIETY_CN[best_k]) < len(v):
                best_k = k
    return best_k


def resolve_variety(code: str, name: str, kind: str, exch: str,
                    known: set[str]) -> str:
    """稳健解析合约所属品种代码。"""
    if exch == "CFFEX":
        for cn, vcode in CFFEX_NAME_CODE:
            if name.startswith(cn):
                return vcode
        m = re.match(r"^([A-Za-z]+)", code)
        base = (m.group(1) if m else code).upper()
        for suf in ("M0", "S0", "M", "S", "0"):
            if base.endswith(suf) and base[: -len(suf)] in known:
                return base[: -len(suf)]
        return base

    p = month_from_dm(code)
    if p:
        return p[0]                       # 真实合约 / 形如 rb2610

    # 形如 v2610F（月均）、rb2610F 等，剥离尾部标记后重试
    m = re.match(r"^([A-Za-z]+)(\d+)([A-Za-z]*)$", code)
    if m and m.group(3):
        p2 = month_from_dm(m.group(1) + m.group(2))
        if p2:
            return p2[0]

    upper = code.upper()
    # 主连 M / 次主连 S / 连续 0 后缀剥离
    for suf in ("M", "S", "0"):
        if upper.endswith(suf) and upper[: -len(suf)] in known:
            return upper[: -len(suf)]
    # 用名称反查
    base = name
    for kw in LINK_SUFFIX_KW:
        base = base.replace(kw, "")
    hit = cn_to_variety(base.strip(), known)
    if hit:
        return hit
    # 名称里的英文代码（如 "PVC月均主连"、"LPG主连"）
    m2 = re.match(r"^([A-Za-z]{1,4})", base.strip())
    if m2:
        en = m2.group(1).upper()
        if en in known:
            return en
        if EN_ALIAS.get(en) in known:
            return EN_ALIAS[en]
    return upper


def month_from_dm(dm: str) -> tuple[str, str] | None:
    """
    从东财合约代码解析 (品种字母大写, 四位年月)。
    rb2610 -> ('RB','202610')     4位 => YYMM
    AP610  -> ('AP','202610')     3位 => 年个位+月
    """
    m = re.match(r"^([A-Za-z]+)(\d+)$", dm)
    if not m:
        return None
    letters, digits = m.group(1).upper(), m.group(2)
    if len(digits) == 4:
        yy, mm = int(digits[:2]), int(digits[2:])
        return letters, f"{2000 + yy}{mm:02d}"
    if len(digits) == 3:
        y, mm = int(digits[0]), int(digits[1:])
        return letters, f"{2020 + y}{mm:02d}"
    return None


def sina_symbol_of(dm: str) -> str | None:
    """真实合约 -> 新浪K线代码（大写品种码 + 4位年月）。"""
    p = month_from_dm(dm)
    if not p:
        return None
    letters, ym = p
    return f"{letters}{ym[2:]}"          # 202610 -> 2610


# ----------------------------------------------------------------------
# 1. 采集合约快照
# ----------------------------------------------------------------------
def fetch_market(market_id: str) -> list[dict]:
    """拉取单个市场的全部合约（含全字段行情）。"""
    out, page = [], 0
    while True:
        q = urllib.parse.urlencode({
            "orderBy": "dm", "sort": "asc", "pageIndex": page,
            "pageSize": 500, "_": int(time.time() * 1000),
        })
        url = f"https://futsseapi.eastmoney.com/list/{market_id}?{q}"
        try:
            d = http_get_json(url, "https://qhweb.eastmoney.com/")
        except Exception as e:                                   # noqa: BLE001
            print(f"    [warn] market {market_id} page {page} 失败: {e}")
            break
        lst = d.get("list") or []
        for it in lst:
            it["_market"] = market_id
        out.extend(lst)
        total = d.get("total") or 0
        page += 1
        if len(out) >= total or not lst:
            break
    return out


def fetch_all_contracts() -> list[dict]:
    print("[1/6] 拉取各交易所合约快照 ...")
    raw: list[dict] = []
    with cf.ThreadPoolExecutor(7) as ex:
        for mid, res in zip([m[0] for m in MARKETS], ex.map(fetch_market, [m[0] for m in MARKETS])):
            print(f"    {MARKET_NAME.get(mid, mid):<8} {len(res):>5} 条")
            raw.extend(res)

    # ---- 去重 ----
    rows, seen = [], set()
    for it in raw:
        dm = it.get("dm")
        mid = it.get("_market")
        if not dm:
            continue
        key = (dm.upper(), mid)
        if key in seen:
            continue
        seen.add(key)
        rows.append(it)

    # ---- 第一遍：收集真实品种代码集合（权威） ----
    known: set[str] = set()
    for it in rows:
        name = (it.get("name") or "").strip()
        if detect_kind(name)[0] != "real":
            continue
        p = month_from_dm(it["dm"])
        if p:
            known.add(p[0])
    for cn, vcode in CFFEX_NAME_CODE:
        known.add(vcode)

    contracts = []
    for it in rows:
        dm = it.get("dm")
        mid = it.get("_market")

        exch, exch_cn = "OTHER", "其他"
        for m in MARKETS:
            if m[0] == mid:
                exch, exch_cn = m[1], m[2]
                break

        name = (it.get("name") or "").strip()
        kind, kind_label = detect_kind(name)

        variety = resolve_variety(dm, name, kind, exch, known)
        ym = ""
        p = month_from_dm(dm)
        if p and kind == "real":
            ym = p[1]
        elif exch == "CFFEX" and kind == "real":
            m2 = re.search(r"(\d{4})\s*$", name)
            ym = m2.group(1) if m2 else ""

        sina = sina_symbol_of(dm) if kind == "real" else None
        if kind == "main_link":
            sina = f"{variety}0"                    # 新浪主连代码
        elif kind in ("continuous", "month_link", "index"):
            sina = None

        rec = {
            "code": dm,
            "codeUpper": dm.upper(),
            "name": name,
            "exch": exch,
            "exchName": exch_cn,
            "market": mid,
            "marketName": MARKET_NAME.get(mid, mid),
            "tradeMarketCode": EM_TRADE_MARKET_CODE.get(mid, ""),
            "variety": variety,
            "varietyName": VARIETY_CN.get(variety, VARIETY_CN.get(variety.upper(), name)),
            "sector": SECTOR_MAP.get(variety, SECTOR_MAP.get(variety.upper(), "其他")),
            "night": variety in NIGHT_VARIETIES,
            "kind": kind,
            "kindLabel": kind_label,
            "month": ym,
            "sina": sina,
            # 行情
            "p": it.get("p"), "zde": it.get("zde"), "zdf": it.get("zdf"),
            "o": it.get("o"), "h": it.get("h"), "l": it.get("l"),
            "zjsj": it.get("zjsj"), "jjsj": it.get("jjsj"),
            "vol": it.get("vol"), "ccl": it.get("ccl"), "rz": it.get("rz"),
            "cje": it.get("cje"), "zf": it.get("zf"),
            "wp": it.get("wp"), "np": it.get("np"),
            "uid": it.get("uid"),
        }
        contracts.append(rec)

    # 中金所 220 优先于 8（8 为内部数字码，名称相同则丢弃）
    def rank(c):
        return (0 if c["market"] == "220" else 1)
    bykey: dict[str, dict] = {}
    for c in sorted(contracts, key=rank):
        k = f'{c["variety"]}|{c["name"]}'
        bykey.setdefault(k, c)
    contracts = list(bykey.values())

    print(f"    合约合计 {len(contracts)} 个（已去重）")
    return contracts


# ----------------------------------------------------------------------
# 2. 分类与品种聚合
# ----------------------------------------------------------------------
def build_varieties(contracts: list[dict]) -> list[dict]:
    print("[2/6] 构建品种聚合与分类 ...")
    groups: dict[str, list[dict]] = {}
    for c in contracts:
        if c["kind"] in ("index",):
            continue
        groups.setdefault(c["variety"], []).append(c)

    varieties = []
    for code, items in sorted(groups.items()):
        reals = [x for x in items if x["kind"] == "real"]
        links = [x for x in items if x["kind"] != "real"]
        main_link = next((x for x in links if x["kind"] == "main_link"), None)
        main = max(reals, key=lambda x: (x["ccl"] or 0)) if reals else None
        total_vol = sum(x["vol"] or 0 for x in reals)
        total_ccl = sum(x["ccl"] or 0 for x in reals)
        varieties.append({
            "variety": code,
            "name": (main or main_link or items[0])["varietyName"],
            "exch": items[0]["exch"],
            "exchName": items[0]["exchName"],
            "market": items[0]["market"],
            "sector": items[0]["sector"],
            "night": items[0]["night"],
            "contractCount": len(reals),
            "linkCount": len(links),
            "mainContract": main["code"] if main else None,
            "mainContractName": main["name"] if main else None,
            "mainLink": main_link["code"] if main_link else None,
            "mainLinkName": main_link["name"] if main_link else None,
            "sinaLink": (main_link or {}).get("sina"),
            "sinaMain": main["sina"] if main else None,
            "vol": total_vol,
            "ccl": total_ccl,
            "p": main["p"] if main else None,
            "zdf": main["zdf"] if main else None,
        })
    print(f"    品种 {len(varieties)} 个")
    return varieties


def build_categories(contracts: list[dict], varieties: list[dict]) -> dict:
    reals = [c for c in contracts if c["kind"] == "real"]
    links = [c for c in contracts if c["kind"] != "real"]

    # 按主力（各品种持仓量最大真实合约）
    main_codes = {v["mainContract"] for v in varieties if v["mainContract"]}
    # 按主连
    mainlink_codes = {v["mainLink"] for v in varieties if v["mainLink"]}

    def bucket(pred):
        return [c["code"] for c in contracts if pred(c)]

    cats = {
        "real": {
            "label": "全部真实合约",
            "desc": "各交易所全部可交易的真实月份合约（不含主连/次主连/连续/加权等衍生代码）",
            "items": bucket(lambda c: c["kind"] == "real"),
        },
        "main": {
            "label": "主力合约",
            "desc": "每个品种按持仓量最大的真实合约（实时计算）",
            "items": bucket(lambda c: c["code"] in main_codes),
        },
        "main_link": {
            "label": "主连",
            "desc": "交易所/东财维护的主力连续代码（含换月拼接）",
            "items": bucket(lambda c: c["kind"] == "main_link"),
        },
        "sub_main_link": {
            "label": "次主连",
            "desc": "次主力连续代码",
            "items": bucket(lambda c: c["kind"] == "sub_main_link"),
        },
        "month_link": {
            "label": "月连续",
            "desc": "当月/下月/下季/隔季连续（主要用于股指、国债）",
            "items": bucket(lambda c: c["kind"] == "month_link"),
        },
        "continuous": {
            "label": "连续",
            "desc": "品种连续代码",
            "items": bucket(lambda c: c["kind"] == "continuous"),
        },
        "index": {
            "label": "加权/指数",
            "desc": "交易所或数据商编制的品种加权、指数合约",
            "items": bucket(lambda c: c["kind"] == "index"),
        },
        "night": {
            "label": "夜盘品种",
            "desc": "21:00 起参与夜盘交易的品种所含全部合约",
            "items": bucket(lambda c: c["night"] and c["kind"] == "real"),
        },
        "day_only": {
            "label": "仅日盘品种",
            "desc": "无夜盘的品种所含全部合约",
            "items": bucket(lambda c: (not c["night"]) and c["kind"] == "real"),
        },
        "all": {
            "label": "全部代码",
            "desc": "东财行情中心收录的全部期货代码",
            "items": [c["code"] for c in contracts],
        },
    }

    by_exch, by_sector = {}, {}
    for c in reals:
        by_exch.setdefault(c["exch"], {"label": c["exchName"], "desc": c["exchName"],
                                       "items": []})["items"].append(c["code"])
        by_sector.setdefault(c["sector"], {"label": c["sector"], "desc": c["sector"] + "类品种",
                                           "items": []})["items"].append(c["code"])
    cats["_byExch"] = by_exch
    cats["_bySector"] = by_sector

    stats = {
        "realCount": len(reals),
        "linkCount": len(links),
        "total": len(contracts),
        "exchCount": len(by_exch),
        "sectorCount": len(by_sector),
        "nightVarietyCount": len([v for v in varieties if v["night"]]),
        "nightContractCount": len([c for c in reals if c["night"]]),
    }
    print(f"    真实合约 {stats['realCount']} / 衍生代码 {stats['linkCount']}")
    return {"categories": cats, "stats": stats}


# ----------------------------------------------------------------------
# 3. 品种加权合约（用真实合约按持仓量加权，剔除主连/次主连/月均等）
# ----------------------------------------------------------------------
EXCLUDE_KINDS = {"main_link", "sub_main_link", "month_link", "continuous", "index"}


def build_weighted(contracts: list[dict]) -> dict:
    print("[3/6] 计算品种加权合约（真实合约按持仓量加权） ...")
    groups: dict[str, list[dict]] = {}
    for c in contracts:
        if c["kind"] in EXCLUDE_KINDS:
            continue                                   # 严格剔除主力/次主力/主连/次主连/月均/加权
        if not isinstance(c.get("p"), (int, float)) or not c["p"]:
            continue
        groups.setdefault(c["variety"], []).append(c)

    out = {}
    for var, items in groups.items():
        items = sorted(items, key=lambda x: x["code"])
        wsum = sum((x["ccl"] or 0) for x in items)
        vsum = sum((x["vol"] or 0) for x in items)
        if wsum <= 0:
            continue
        wp = sum(x["p"] * (x["ccl"] or 0) for x in items) / wsum
        # 加权昨结算
        wz = sum((x["zjsj"] or x["p"]) * (x["ccl"] or 0) for x in items) / wsum
        # 加权开高低
        def wavg(f):
            return sum((x[f] or x["p"]) * (x["ccl"] or 0) for x in items) / wsum
        wvol_price = (sum(x["p"] * (x["vol"] or 0) for x in items) / vsum) if vsum else None
        out[var] = {
            "variety": var,
            "name": items[0]["varietyName"] + "加权",
            "exch": items[0]["exch"],
            "exchName": items[0]["exchName"],
            "sector": items[0]["sector"],
            "night": items[0]["night"],
            "rule": "Σ(合约最新价 × 合约持仓量) / Σ(合约持仓量)，样本为全部真实月份合约",
            "contractCount": len(items),
            "members": [x["code"] for x in items],
            "memberDetail": [{"code": x["code"], "name": x["name"], "p": x["p"],
                              "ccl": x["ccl"], "vol": x["vol"], "weight": round((x["ccl"] or 0) / wsum * 100, 4)}
                             for x in items],
            "p": round(wp, 2),
            "zjsj": round(wz, 2),
            "o": round(wavg("o"), 2),
            "h": round(wavg("h"), 2),
            "l": round(wavg("l"), 2),
            "zde": round(wp - wz, 2),
            "zdf": round((wp - wz) / wz * 100, 2) if wz else None,
            "vol": vsum,
            "ccl": wsum,
            "volWeightedPrice": round(wvol_price, 2) if wvol_price else None,
        }
    print(f"    加权合约 {len(out)} 个品种")
    return out


# 东方财富「期货品种资讯页」slug 映射（经穷举探测确认，标题已逐一核对）
#   资讯页 https://futures.eastmoney.com/a/a{slug}.html
#   评论页 https://futures.eastmoney.com/a/a{slug}pl.html
EM_SLUG = {
    "AD": "ad", "AO": "ao", "AP": "ap", "BC": "bc", "FG": "bl", "BR": "br",
    "SR": "bt", "AG": "by", "BZ": "bz", "CJ": "cj", "CY": "cy", "A": "dl",
    "M": "dp", "Y": "dy", "EB": "eb", "EC": "ec", "EG": "eg", "RB": "gc",
    "SF": "gt", "AU": "hj", "IM": "im", "MA": "jc", "JD": "jd", "JM": "jm",
    "JR": "jr", "J": "jt", "AL": "l", "LC": "lc", "LG": "lg", "LH": "lh",
    "LR": "lr", "LU": "lu", "SM": "mg", "CF": "mh", "NI": "ni", "NR": "nr",
    "OP": "op", "PD": "pd", "PF": "pf", "PG": "pg", "PK": "pk", "PL": "pl",
    "PR": "pr", "PS": "ps", "PT": "pt", "PX": "px", "PB": "q", "RR": "rr",
    "SA": "sa", "SH": "sh", "SI": "si", "SN": "sn", "SP": "sp", "SS": "ss",
    "CU": "t", "T": "tk", "TL": "tl", "TS": "ts", "UR": "ur", "WR": "wr",
    "ZN": "x", "RU": "xj", "WH": "xm", "C": "ym", "ZC": "zc", "PP": "jbx",
    "V": "pvc", "TA": "pta", "FU": "rly", "P": "zly", "OI": "ycz",
    "RI": "zxd", "FB": "xwb", "BB": "jhb", "I": "tks", "CS": "ymdf",
}
# 东财未单独建品种资讯页的品种（页面确实不存在，前端会给出明确提示）
EM_NO_PAGE = {"B", "HC", "L", "RM", "RS", "PM", "SC", "IF", "IH", "IC", "TF"}


def http_get_bytes(url: str, referer: str = "", timeout: int = 20, retries: int = 1) -> bytes:
    headers = {"User-Agent": UA, "Accept": "*/*"}
    if referer:
        headers["Referer"] = referer
    last = None
    for i in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=headers)
            return _OPENER.open(req, timeout=timeout).read()
        except Exception as e:                      # noqa: BLE001
            last = e
            time.sleep(0.3 * (i + 1))
    raise last


def page_title(url: str, referer: str = "") -> str:
    """取网页 <title>，自动处理 gbk/utf-8。"""
    raw = http_get_bytes(url, referer, timeout=14, retries=1)
    for enc in ("utf-8", "gb18030"):
        try:
            html = raw.decode(enc)
            break
        except Exception:                                        # noqa: BLE001
            continue
    else:
        html = raw.decode("utf-8", "ignore")
    m = re.search(r"<title>(.*?)</title>", html, re.S)
    t = (m.group(1) if m else "").strip()
    if "不存在" in t or "已删除" in t:
        return ""
    return t


# ----------------------------------------------------------------------
# 4. 资讯链接（按权威 slug 映射 + 逐一在线校验）
# ----------------------------------------------------------------------
def probe_news(varieties: list[dict]) -> dict:
    print("[4/6] 校验品种资讯链接 ...")
    result: dict[str, dict] = {}

    def one(v):
        code = v["variety"]
        slug = EM_SLUG.get(code)
        em_news = em_news_pl = em_title = None
        if slug:
            u1 = f"https://futures.eastmoney.com/a/a{slug}.html"
            u2 = f"https://futures.eastmoney.com/a/a{slug}pl.html"
            try:
                t1 = page_title(u1, "https://futures.eastmoney.com/")
                if t1:
                    em_news, em_title = u1, t1
            except Exception:                                    # noqa: BLE001
                pass
            try:
                t2 = page_title(u2, "https://futures.eastmoney.com/")
                if t2 and "评论" in t2:
                    em_news_pl = u2
            except Exception:                                    # noqa: BLE001
                pass

        # 新浪：品种资讯页
        sina_news = None
        cu = code.upper()
        try:
            t = page_title(f"http://finance.sina.com.cn/money/future/{cu}/",
                           "http://finance.sina.com.cn/money/future/")
            if t and "期货" in t:
                sina_news = f"http://finance.sina.com.cn/money/future/{cu}/"
        except Exception:                                        # noqa: BLE001
            pass
        sina_quote = f"https://finance.sina.com.cn/futures/quotes/{cu}.shtml"

        return code, {
            "emNews": em_news,
            "emNewsTitle": em_title,
            "emNewsComment": em_news_pl,
            "emNewsChannel": "https://futures.eastmoney.com/",
            "emSlug": slug,
            "emHasPage": bool(em_news),
            "sinaNews": sina_news,
            "sinaQuote": sina_quote,
            "sinaChannel": "http://finance.sina.com.cn/money/future/",
            "note": "" if em_news else ("东方财富未单独设立该品种资讯页，已提供频道入口"
                                        if (not slug or code in EM_NO_PAGE)
                                        else "东财品种页暂不可访问"),
        }

    with cf.ThreadPoolExecutor(12) as ex:
        for code, links in ex.map(one, varieties):
            result[code] = links
    ok = sum(1 for v in result.values() if v["emHasPage"])
    ok2 = sum(1 for v in result.values() if v["sinaNews"])
    print(f"    东财品种资讯页 {ok}/{len(varieties)} ；新浪品种资讯页 {ok2}/{len(varieties)}")
    return result


# ----------------------------------------------------------------------
# 5. 龙虎榜
# ----------------------------------------------------------------------
DC = "https://datacenter-web.eastmoney.com/api/data/v1/get"


def dc_query(report: str, filt: str, page: int = 1, size: int = 500,
             sort_cols: str = "", sort_types: str = "") -> dict:
    q = {
        "reportName": report, "columns": "ALL", "filter": filt,
        "pageNumber": page, "pageSize": size, "source": "WEB", "client": "WEB",
    }
    if sort_cols:
        q["sortColumns"] = sort_cols
        q["sortTypes"] = sort_types or "-1"
    return http_get_json(f"{DC}?{urllib.parse.urlencode(q)}", "https://data.eastmoney.com/")


def dc_all(report: str, filt: str, size: int = 500, max_pages: int = 10,
           sort_cols: str = "", sort_types: str = "") -> list[dict]:
    rows, page = [], 1
    while page <= max_pages:
        try:
            d = dc_query(report, filt, page, size, sort_cols, sort_types)
        except Exception as e:                                       # noqa: BLE001
            print(f"      [warn] {report} page{page}: {e}")
            break
        r = d.get("result") or {}
        data = r.get("data") or []
        rows.extend(data)
        pages = r.get("pages") or 1
        if page >= pages or not data:
            break
        page += 1
    return rows


# 龙虎榜字段裁剪白名单（去掉大量冗余的 _RANK 重复列，压缩体积 ~60%）
LHB_FIELDS = [
    "SECURITY_CODE", "TRADE_DATE", "ORG_CODE", "MEMBER_NAME_ABBR", "TYPE",
    "VOLUME", "VOLUME_CHANGE", "VOLUMERANK",
    "LONG_POSITION", "LP_CHANGE", "LPRANK",
    "SHORT_POSITION", "SP_CHANGE", "SPRANK",
    "NET_LONG_POSITION", "NLP_CHANGE", "NLPRANK",
    "NET_SHORT_POSITION", "NSP_CHANGE", "NSPRANK",
    "LPUPRANK", "LPDOWNRANK", "SPUPRANK", "SPDOWNRANK",
]
PPAL_FIELDS = [
    "SECURITY_CODE", "TRADE_DATE", "ORG_CODE", "MEMBER_NAME_ABBR", "SETTLE_PRICE",
    "LP_AVERAGE_PRICE", "SP_AVERAGE_PRICE", "LP_AVRNEW_PRICE", "SP_AVRNEW_PRICE",
    "LONG_POSITION", "SHORT_POSITION", "NET_LONG_POSITION", "NET_SHORT_POSITION",
    "LP_FLUCTUATE_PAL", "SP_FLUCTUATE_PAL", "FLUCTUATE_PAL",
    "LP_ACCUM_PAL", "SP_ACCUM_PAL", "ACCUM_PAL",
]


def trim(rows: list[dict], fields: list[str]) -> list[dict]:
    out = []
    for r in rows:
        out.append({k: r.get(k) for k in fields if k in r})
    return out


def latest_trade_date() -> str:
    """取龙虎榜最新可用交易日。"""
    try:
        d = dc_query("RPT_FUTU_DAILYPOSITION", '(SECURITY_CODE="RB2610")', 1, 1,
                     "TRADE_DATE", "-1")
        data = (d.get("result") or {}).get("data") or []
        if data:
            return str(data[0]["TRADE_DATE"])[:10]
    except Exception:                                                # noqa: BLE001
        pass
    return ""


def lhb_code_of(c: dict) -> str:
    """东财龙虎榜使用的合约代码：
       上期所/大商所/郑商所/中金所 = 品种码 + 4位年月（大写）
       上期能源 / 广期所            = 同一形式但小写
       （郑商所在行情接口是 3 位月份如 AP610，龙虎榜需补成年份，如 AP2610）
    """
    m = re.match(r"^([A-Za-z]+)(\d+)$", c["code"])
    if not m:
        return ""
    letters, digits = m.group(1), m.group(2)
    if len(digits) == 3:
        digits = "2" + digits                 # 610 -> 2610（2026年10月）
    code = letters + digits
    return code.lower() if c["exch"] in LHB_LOWER_EXCH else code.upper()


def fetch_lhb_dict() -> dict:
    """东财官方龙虎榜品种/合约字典（决定哪些合约有龙虎榜数据）。"""
    rows = dc_all("RPT_FUTU_POSITIONCODE", "", 500, 4)
    d = {}
    for r in rows:
        sc = r.get("SECURITY_CODE")
        if not sc:
            continue
        d[str(sc).upper()] = {
            "securityCode": sc,
            "tradeMarketCode": r.get("TRADE_MARKET_CODE"),
            "tradeCode": str(r.get("TRADE_CODE") or "").upper(),
            "tradeTypeName": r.get("TRADE_TYPE_NAME"),
            "isMain": r.get("IS_MAINCODE"),
        }
    return d


def fetch_lhb(contracts: list[dict], varieties: list[dict], trade_date: str,
              lhb_dict: dict) -> tuple[dict, dict]:
    print(f"[5/6] 抓取龙虎榜（交易日 {trade_date}） ...")
    by_var: dict[str, list[dict]] = {}
    for c in contracts:
        if c["kind"] == "real":
            by_var.setdefault(c["variety"], []).append(c)

    targets: dict[str, dict] = {}
    coverage: dict[str, dict] = {}
    for v in varieties:
        var = v["variety"]
        cands = sorted(by_var.get(var, []), key=lambda x: -(x["ccl"] or 0))
        pick, note = None, ""
        # 1) 该品种在龙虎榜字典里的合约（按持仓量优先）
        dict_codes = {k for k, x in lhb_dict.items() if x["tradeCode"] == var}
        for c in cands:
            code = lhb_code_of(c)
            if code.upper() in dict_codes:
                pick = (code, lhb_dict[code.upper()]["securityCode"])
                break
        if not pick and dict_codes:
            k = sorted(dict_codes)[0]
            pick = (k, lhb_dict[k]["securityCode"])
            note = "使用龙虎榜字典中的合约（主力合约未收录）"
        if not pick:
            note = "东方财富龙虎榜未收录该品种"

        coverage[var] = {"covered": bool(pick), "note": note,
                         "dictCount": len(dict_codes),
                         "dictCodes": sorted(ld["securityCode"] for k, ld in lhb_dict.items()
                                             if ld["tradeCode"] == var)}
        if pick:
            targets[pick[1]] = next((c for c in cands if lhb_code_of(c).upper() == pick[0].upper()), cands[0] if cands else None)

    summary = {}

    def one(item):
        sec, c = item
        try:
            rank = dc_all("RPT_FUTU_DAILYPOSITION",
                          f'(SECURITY_CODE="{sec}")(TRADE_DATE=\'{trade_date}\')(TYPE="0")',
                          200, 2)
            total = dc_all("RPT_FUTU_DAILYPOSITION",
                           f'(SECURITY_CODE="{sec}")(TRADE_DATE=\'{trade_date}\')(TYPE="1")',
                           20, 1)
            structure = dc_all("RPT_FUTU_DAILYPOSITION",
                               f'(SECURITY_CODE="{sec}")(TRADE_DATE=\'{trade_date}\')',
                               200, 2)
            build = dc_all("RPT_FUTU_DAILYPOSITION",
                           f'(SECURITY_CODE="{sec}")', 200, 1,
                           "TRADE_DATE,VOLUMERANK", "-1,1")
            avgppal = dc_all("RPT_FUTU_AVGPPAL",
                             f'(SECURITY_CODE="{sec}")(TRADE_DATE=\'{trade_date}\')',
                             200, 2)
        except Exception as e:                                       # noqa: BLE001
            print(f"      [warn] 龙虎榜 {sec}: {e}")
            return None
        if not (rank or structure or avgppal):
            return None
        payload = {
            "securityCode": sec, "name": c["name"] if c else sec,
            "variety": c["variety"] if c else "", "exch": c["exch"] if c else "",
            "tradeDate": trade_date,
            "rank": trim(rank, LHB_FIELDS),
            "total": trim(total, LHB_FIELDS),
            "structure": trim(structure, LHB_FIELDS),
            "build": trim(build, LHB_FIELDS),
            "avgPpal": trim(avgppal, PPAL_FIELDS),
        }
        with open(os.path.join(LHB_DIR, f"{sec}.json"), "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
        summary[sec] = {
            "lhbCode": sec, "name": payload["name"], "variety": payload["variety"],
            "exch": payload["exch"], "tradeDate": trade_date,
            "rank": len(rank), "structure": len(structure),
            "build": len(build), "avgPpal": len(avgppal),
            "file": f"lhb/{sec}.json",
        }
        return sec

    with cf.ThreadPoolExecutor(8) as ex:
        list(ex.map(one, list(targets.items())))
    cov_n = sum(1 for x in coverage.values() if x["covered"])
    print(f"    龙虎榜落盘 {len(summary)} 个合约（覆盖品种 {cov_n}/{len(varieties)}）")
    return summary, coverage


# ----------------------------------------------------------------------
# 6. 核心合约K线预抓（离线兜底）
# ----------------------------------------------------------------------
SINA_API = "https://stock2.finance.sina.com.cn/futures/api/jsonp.php/var%20_k=/InnerFuturesNewService."
PERIOD_API = {
    "1": ("getFewMinLine", "&type=1"),
    "5": ("getFewMinLine", "&type=5"),
    "15": ("getFewMinLine", "&type=15"),
    "30": ("getFewMinLine", "&type=30"),
    "60": ("getFewMinLine", "&type=60"),
    "day": ("getDailyKLine", ""),
}


def sina_kline(symbol: str, period: str = "day") -> list[dict]:
    fn, extra = PERIOD_API.get(period, ("getDailyKLine", ""))
    url = f"{SINA_API}{fn}?symbol={urllib.parse.quote(symbol)}{extra}&_={int(time.time()*1000)}"
    txt = http_get(url, "https://finance.sina.com.cn/futures/quotes/RB.shtml")
    m = re.search(r"=\((\[.*?\])\)", txt, re.S)
    if not m:
        return []
    try:
        return json.loads(m.group(1))
    except Exception:                                                # noqa: BLE001
        return []


def validate_sina(varieties: list[dict]) -> dict:
    """按品种验证新浪K线代码规则是否有效。"""
    print("    校验新浪K线代码 ...")

    def one(v):
        sym = v["sinaLink"] or v["sinaMain"]
        if not sym:
            return v["variety"], False, None
        try:
            rows = sina_kline(sym, "day")
            return v["variety"], bool(rows), sym
        except Exception:                                            # noqa: BLE001
            return v["variety"], False, sym

    res = {}
    with cf.ThreadPoolExecutor(20) as ex:
        for var, ok, sym in ex.map(one, varieties):
            res[var] = {"ok": ok, "symbol": sym}
    good = sum(1 for x in res.values() if x["ok"])
    print(f"    新浪K线可用品种 {good}/{len(varieties)}")
    return res


def prefetch_kline(varieties: list[dict], validate: dict) -> dict:
    print("[6/6] 预抓核心合约日K（主连 + 主力，全量历史） ...")
    meta = {}

    def one(v):
        var = v["variety"]
        if not validate.get(var, {}).get("ok"):
            return None
        sym = validate[var]["symbol"]
        try:
            rows = sina_kline(sym, "day")
        except Exception as e:                                       # noqa: BLE001
            print(f"      [warn] {var} {sym}: {e}")
            return None
        if not rows:
            return None
        with open(os.path.join(KL_DIR, f"{var}.json"), "w", encoding="utf-8") as f:
            json.dump({"variety": var, "name": v["name"], "symbol": sym,
                       "period": "day", "count": len(rows), "rows": rows}, f,
                      ensure_ascii=False, separators=(",", ":"))
        return var, sym, len(rows), rows[0]["d"], rows[-1]["d"]

    with cf.ThreadPoolExecutor(16) as ex:
        for r in ex.map(one, varieties):
            if r:
                var, sym, n, f, l = r
                meta[var] = {"symbol": sym, "count": n, "first": f, "last": l,
                             "file": f"kline_core/{var}.json"}
    print(f"    预抓 {len(meta)} 个品种日K")
    return meta


# ----------------------------------------------------------------------
# 品种加权日K：全部真实合约（在市 + 近期过期）按持仓量自算加权
# ----------------------------------------------------------------------
WK_BACK_MONTHS = 30          # 向前探测多少个月的已过期合约
WK_FWD_MONTHS = 15           # 向后探测多少个月（覆盖远月挂牌）


def _month_list() -> list[str]:
    base = datetime.now().year * 12 + datetime.now().month
    out = []
    for k in range(-WK_BACK_MONTHS, WK_FWD_MONTHS + 1):
        t = base + k
        out.append(f"{t // 12 % 100:02d}{t % 12 + 1:02d}")   # YYMM
    return out


def build_weighted_kline(varieties: list[dict], contracts: list[dict]) -> dict:
    """
    对每个品种：抓取其全部真实合约（含近期过期）的新浪日K（含持仓量），
    按持仓量加权合成品种加权日K。周/月/年K 由前端在日K基础上聚合。
    """
    print(f"[7/7] 采集全部真实合约日K并自算品种加权日K（含近 {WK_BACK_MONTHS} 个月过期合约）...")
    months = _month_list()
    listed: dict[str, set[str]] = {}
    for c in contracts:
        if c.get("kind") == "real" and c.get("sina"):
            listed.setdefault(c["variety"], set()).add(c["sina"])
    # 中金所品种代码在 contracts 里可能取自名称（IF/IC/...），sinaSymbol 已按同一规则生成

    tasks = []                    # (variety, symbol)
    for v in varieties:
        var = v["variety"]
        syms = set(listed.get(var, set()))
        for ym in months:
            syms.add(f"{var}{ym}")
        for s in sorted(syms):
            tasks.append((var, s))
    print(f"    待探测合约日K {len(tasks)} 份（{len(varieties)} 个品种）")

    def fetch_one(t):
        var, sym = t
        try:
            rows = sina_kline(sym, "day")
        except Exception:                                         # noqa: BLE001
            return None
        if not rows or not isinstance(rows, list):
            return None
        return var, sym, rows

    per_var: dict[str, dict[str, list]] = {}      # var -> symbol -> rows
    done = 0
    with cf.ThreadPoolExecutor(16) as ex:
        for r in ex.map(fetch_one, tasks):
            done += 1
            if done % 800 == 0:
                print(f"      进度 {done}/{len(tasks)}")
            if not r:
                continue
            per_var.setdefault(r[0], {})[r[1]] = r[2]

    meta = {}
    for v in varieties:
        var = v["variety"]
        bysym = per_var.get(var)
        if not bysym:
            continue
        days: dict[str, list[tuple]] = {}
        for sym, rows in bysym.items():
            for r in rows:
                try:
                    d = r["d"]
                    o, h, l, c = float(r["o"]), float(r["h"]), float(r["l"]), float(r["c"])
                    vol = float(r.get("v") or 0)
                    oi = float(r.get("p") or 0)
                except (KeyError, TypeError, ValueError):
                    continue
                days.setdefault(d, []).append((o, h, l, c, vol, oi))
        if not days:
            continue
        bars = []
        for d in sorted(days):
            mem = days[d]
            ois = [m[5] for m in mem]
            if sum(ois) > 0:
                ws = ois
                tw = sum(ois)
            else:                                             # 当日无持仓数据时等权
                ws = [1.0] * len(mem)
                tw = float(len(mem))
            o = sum(m[0] * w for m, w in zip(mem, ws)) / tw
            h = sum(m[1] * w for m, w in zip(mem, ws)) / tw
            l = sum(m[2] * w for m, w in zip(mem, ws)) / tw
            c = sum(m[3] * w for m, w in zip(mem, ws)) / tw
            bars.append([d, round(o, 3), round(h, 3), round(l, 3), round(c, 3),
                         int(sum(m[4] for m in mem)), int(sum(ois))])
        if not bars:
            continue
        obj = {"variety": var, "name": v["name"], "method": "持仓量加权(自算)",
               "contracts": len(bysym), "count": len(bars),
               "first": bars[0][0], "last": bars[-1][0],
               "rows": bars}
        with open(os.path.join(WK_DIR, f"{var}.json"), "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
        meta[var] = {"count": len(bars), "first": bars[0][0], "last": bars[-1][0],
                     "contracts": len(bysym), "file": f"weighted_kline/{var}.json"}
    print(f"    加权日K完成 {len(meta)} 个品种")
    return meta


# ----------------------------------------------------------------------
# main
# ----------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="跳过高线预抓与龙虎榜")
    args = ap.parse_args()

    t0 = time.time()
    contracts = fetch_all_contracts()

    varieties = build_varieties(contracts)
    cats = build_categories(contracts, varieties)
    weighted = build_weighted(contracts)

    news = probe_news(varieties)
    for v in varieties:
        v["news"] = news.get(v["variety"], {})

    sina_check = validate_sina(varieties)
    for v in varieties:
        ck = sina_check.get(v["variety"], {})
        v["sinaUsable"] = bool(ck.get("ok"))
        v["sinaCheckedSymbol"] = ck.get("symbol")
    for c in contracts:
        vv = next((v for v in varieties if v["variety"] == c["variety"]), None)
        c["sinaUsable"] = bool(vv.get("sinaUsable")) if vv else False

    lhb_summary, lhb_coverage, kline_meta, wk_meta, trade_date = {}, {}, {}, {}, ""
    if args.quick:
        # 快速模式只刷新行情类数据：**沿用**上一次已落盘的龙虎榜 / 核心K线 / 加权日K索引，
        # 否则会把索引写成空对象，导致页面上已预抓的龙虎榜快照与离线K线全部失效
        # （快照文件 data/lhb/*.json、data/kline_core/*.json、data/weighted_kline/*.json 本身并不会被删除）。
        lhb_summary = load_json(os.path.join(DATA_DIR, "lhb_index.json"), {})
        lhb_coverage = load_json(os.path.join(DATA_DIR, "lhb_coverage.json"), {})
        kline_meta = load_json(os.path.join(DATA_DIR, "kline_core_index.json"), {})
        wk_meta = load_json(os.path.join(DATA_DIR, "weighted_kline_index.json"), {})
        trade_date = (load_json(os.path.join(DATA_DIR, "meta.json"), {}) or {}).get("tradeDate", "")
        if lhb_summary or kline_meta or wk_meta:
            print("    [快速模式] 沿用已落盘快照：龙虎榜 %d 个合约，核心K线 %d 个品种，加权日K %d 个品种"
                  % (len(lhb_summary), len(kline_meta), len(wk_meta)))
    if not args.quick:
        trade_date = latest_trade_date()
        try:
            lhb_dict = fetch_lhb_dict()
            print(f"    东财龙虎榜字典：{len(lhb_dict)} 个合约")
        except Exception as e:                                       # noqa: BLE001
            print(f"    [warn] 龙虎榜字典获取失败：{e}")
            lhb_dict = {}
        if trade_date:
            # 直接按合约代码覆盖写快照（不做批量删除——同名文件覆盖，历史遗留文件不影响页面：
            # 页面与索引均以本次 lhb_summary 为准）
            lhb_summary, lhb_coverage = fetch_lhb(contracts, varieties, trade_date, lhb_dict)
        kline_meta = prefetch_kline(varieties, sina_check)
        wk_meta = build_weighted_kline(varieties, contracts)

    for v in varieties:
        cov = lhb_coverage.get(v["variety"], {})
        v["lhbCovered"] = bool(cov.get("covered"))
        v["lhbNote"] = cov.get("note", "")
        v["lhbCodes"] = cov.get("dictCodes", [])
        item = lhb_summary.get(v["variety"])
        v["lhbCode"] = next((s["lhbCode"] for s in lhb_summary.values()
                             if s["variety"] == v["variety"]), None)

    meta = {
        "generatedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "tradeDate": trade_date or "最新交易日",
        "sources": [
            {"name": "东方财富·期货行情", "url": "https://qhweb.eastmoney.com/quote"},
            {"name": "东方财富·期货龙虎榜", "url": "https://data.eastmoney.com/futures/dl/data.html"},
            {"name": "新浪财经·期货K线", "url": "https://finance.sina.com.cn/futures/quotes/RB.shtml"},
        ],
        "stats": cats["stats"],
        "varietyCount": len(varieties),
        "weightedCount": len(weighted),
        "lhbCount": len(lhb_summary),
        "klineCoreCount": len(kline_meta),
        "weightedKlineCount": len(wk_meta),
        "elapsedSec": round(time.time() - t0, 1),
    }

    def dump(name, obj):
        p = os.path.join(DATA_DIR, name)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
        print(f"    -> {name:<22} {os.path.getsize(p)/1024:>10.1f} KB")

    print("\n[写出数据]")
    dump("contracts.json", contracts)
    dump("varieties.json", varieties)
    dump("categories.json", cats)
    dump("weighted.json", weighted)
    dump("newslinks.json", news)
    dump("lhb_index.json", lhb_summary)
    dump("lhb_coverage.json", lhb_coverage)
    dump("kline_core_index.json", kline_meta)
    dump("weighted_kline_index.json", wk_meta)
    dump("meta.json", meta)

    print(f"\n完成，用时 {meta['elapsedSec']}s")
    print(json.dumps(meta, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
