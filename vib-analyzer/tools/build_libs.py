# -*- coding: utf-8 -*-
"""生成数据层的两个文件： 数据\\轴承库.json  和  数据\\机型库.json

为什么要有这个工具
------------------
程序原来把「明阳 2.0MW 的齿轮比」写死在代码里（GB_I1/I2/I3、GB_ZR/GB_ZP），
再用它去换算所有项目的各轴转频——别的机型/别的项目齿轮比完全不同，结果必然偏。
现在机型参数全部外置成 数据\\机型库.json：

    shafts: 各轴转频 ÷ 高速轴(电机)转频     -> 由高速轴转速算出 L/S/M/H/P
    gears:  各级齿轮齿数 + 挂在哪个轴       -> 啮合频率 = 齿数 × 该轴转频
    points: 测点名关键字 -> 该测点该看的轴承 -> 打开谱图自动标线、报告自动查包络峰

轴承库 数据\\轴承库.json 只放「轴承名 -> (轴代码, 四个倍数)」，倍数一律相对该轴转频。

数据来源与优先级
----------------
    运达 2.0MW          《运达各类型机组振动档案库.xls》2000kW 页「南高齿FD2250Z」（附件2，最高优先级）；
                        附件1《运达2.0MW轴承参数.xlsx》仅作交叉核对——实测它把 BPFO/BPFI 两列写反了，
                        且用 1757rpm 当基准，所以一律以附件2 的绝对频率 ÷ 该轴转频重算。
    明阳 2.0MW(府谷/田家寨) 原代码内置值，逐条迁出，倍数与齿轮比保持原样（行为不变）。
    其它 14 个机型        《C各机组振动诊断参数表-dd-3（20140103）.xls》，倍数按「原表特征频率 ÷ 该页电机转频」
                        归一成相对高速轴，避免依赖各机型齿轮比。

用法：
    python tools\\build_libs.py                 # 重新生成两个数据文件
    python tools\\build_libs.py --dry-run       # 只统计，不写文件
"""

import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.dirname(HERE)
DATA = os.path.join(APP_DIR, "数据")
BEARING_FILE = os.path.join(DATA, "轴承库.json")
MACHINE_FILE = os.path.join(DATA, "机型库.json")

YUNDA_XLS = r"D:\振动\调试工具和文档\振动\运达各类型机组振动档案库.xls"
C_XLS = r"D:\振动\调试工具和文档\振动\C各机组振动诊断参数表-dd-3（20140103）.xls"

FEATS = ("BPFI", "BPFO", "BSF", "FTF")
SHAFT_CN = {"L": "主轴/行星架", "S": "低速轴", "M": "中速轴", "H": "高速轴", "P": "行星轮"}


# --------------------------------------------------------------------------- #
# 通用小工具
# --------------------------------------------------------------------------- #
def txt(v):
    if v is None:
        return ""
    if isinstance(v, float) and v == int(v):
        v = int(v)
    return re.sub(r"\s+", " ", str(v).strip())


def num(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v.replace(" ", ""))
        except ValueError:
            return None
    return None


def rows_of(sheet):
    return [[sheet.cell_value(r, c) for c in range(sheet.ncols)] for r in range(sheet.nrows)]


def cell(rows, r, c):
    if 0 <= r < len(rows) and 0 <= c < len(rows[r]):
        return rows[r][c]
    return None


def round6(x):
    return round(float(x), 6)


def round9(x):
    """轴转频比：0.0076 这种量级 6 位小数不够，重算频率时相对误差会到 1e-4。"""
    return round(float(x), 9)


def teeth_gcd(values):
    """一对啮合齿轮齿数的公约数；n>=2 时才有意义（材料里 n=3 / n=11 决定边带间隔）。"""
    from math import gcd
    ts = sorted({int(t) for t in values if t and t >= 6})
    if len(ts) < 2:
        return None
    g = 0
    for t in ts:
        g = gcd(g, t)
    return g if g >= 2 else None


# --------------------------------------------------------------------------- #
# 明阳 2.0MW（府谷 / 田家寨）：原代码内置值，原样迁出
# --------------------------------------------------------------------------- #
# 齿轮箱链（与 明阳2.0MW.xlsx 一致）：高速轴→中速轴→太阳轮→低速轴/行星架
GB_I3 = 112.0 / 23.0        # 三级 4.8696
GB_I2 = 113.0 / 24.0        # 二级 4.7083
GB_I1 = 1.0 + 109.0 / 23.0  # 一级行星 5.7391
GB_ZR, GB_ZP = 109.0, 43.0

MINGYANG_BEARINGS = {
    "主轴 N1 F-612211": ("L", {"BPFI": 14.18, "BPFO": 11.82, "FTF": 0.455, "BSF": 5.46}),
    "行星轮 N2 NNCF5052": ("P", {"BPFI": 13.56, "BPFO": 12.44, "BSF": 5.71}),
    "低速轴前 N3 NU1080": ("S", {"BPFI": 14.3, "BPFO": 11.7, "FTF": 0.45, "BSF": 4.95}),
    "低速轴后 N4 LM567949": ("S", {"BPFI": 10.404, "BPFO": 7.596, "BSF": 3.623}),
    "中速轴前 N5 NU2244": ("M", {"BPFI": 8.794, "BPFO": 6.206, "FTF": 0.414, "BSF": 2.811}),
    "中速轴后 N6 30244": ("M", {"BPFI": 12.0, "BPFO": 9.0, "BSF": 3.48}),
    "中速轴后 N6b /32244": ("M", {"BPFI": 12.5, "BPFO": 9.5, "BSF": 3.63}),
    "高速轴前 N7 NU2236": ("H", {"BPFI": 10.352, "BPFO": 7.648, "FTF": 0.43, "BSF": 3.254}),
    "高速轴后 N8 QJ332": ("H", {"BPFI": 7.0923, "BPFO": 4.9077, "FTF": 0.409, "BSF": 4.35}),
    "高速轴后 N9 NU234": ("H", {"BPFI": 10.352, "BPFO": 7.667, "FTF": 0.43, "BSF": 3.3009}),
    "电机前 B12 6332MC4": ("H", {"BPFI": 4.813, "BPFO": 3.187, "FTF": 0.400, "BSF": 2.360}),
    "电机前 B13 6332MC4": ("H", {"BPFI": 4.813, "BPFO": 3.187, "FTF": 0.400, "BSF": 2.360}),
    "电机后 6332MC4": ("H", {"BPFI": 4.813, "BPFO": 3.187, "FTF": 0.400, "BSF": 2.360}),
    "电机 SKF6334": ("H", {"BPFI": 4.838, "BPFO": 3.162, "FTF": 0.395, "BSF": 2.28}),
}


def mingyang_machine():
    fM = 1.0 / GB_I3
    fS = fM / GB_I2
    fL = fS / GB_I1
    return {
        "projects": ["府谷", "田家寨"],
        "shafts": {"H": 1.0, "M": round9(fM), "S": round9(fS), "L": round9(fL),
                   "P": round9(fL * GB_ZR / GB_ZP)},
        "gears": [
            {"name": "一级行星（109齿 × 行星架）", "teeth": 109.0, "shaft": "L", "sideband": "L"},
            {"name": "二级（113齿 × 低速轴）", "teeth": 113.0, "shaft": "S", "sideband": "S"},
            {"name": "三级（112齿 × 中速轴）", "teeth": 112.0, "shaft": "M", "sideband": "M"},
        ],
        "points": [
            ["主轴承", ["主轴 N1 F-612211"]],
            ["行星轮", ["行星轮 N2 NNCF5052"]],
            ["低速轴前", ["低速轴前 N3 NU1080"]],
            ["低速轴后", ["低速轴后 N4 LM567949"]],
            ["中速轴前", ["中速轴前 N5 NU2244"]],
            ["中速轴后", ["中速轴后 N6 30244"]],
            ["高速轴径向", ["高速轴后 N9 NU234"]],
            ["高速轴轴向", ["高速轴后 N9 NU234"]],
            ["中部径向", ["中速轴前 N5 NU2244"]],
            ["一级内齿圈", ["低速轴前 N3 NU1080"]],
            ["发电机前轴承", ["电机前 B12 6332MC4", "电机 SKF6334"]],
            ["发电机后轴承", ["电机后 6332MC4", "电机 SKF6334"]],
            ["发电机", ["电机前 B12 6332MC4", "电机 SKF6334"]],
        ],
        "_note": "明阳 2.0MW（府谷/田家寨），齿轮比沿用原程序内置值 GB_I1/I2/I3。",
    }


# --------------------------------------------------------------------------- #
# 运达 2.0MW（五峰）：附件2《运达各类型机组振动档案库.xls》2000kW 页 南高齿FD2250Z
# --------------------------------------------------------------------------- #
YUNDA_SHEET = "2000kW机组档案"
YUNDA_BLOCK = "南高齿FD2250Z"

# 轴承描述关键字 -> 轴代码
YUNDA_SHAFT_KW = [
    ("行星架前", "L"), ("行星架后", "L"), ("低速轴", "S"),
    ("行星轮", "P"), ("中速轴", "M"), ("高速轴", "H"),
]


def parse_yunda(path):
    """返回 (machine_dict, bearings_dict)。倍数 = 附件2 绝对频率 ÷ 该轴承所在轴转频。"""
    import xlrd
    book = xlrd.open_workbook(path)
    if YUNDA_SHEET not in book.sheet_names():
        raise SystemExit("附件2 里找不到页：%s" % YUNDA_SHEET)
    rows = rows_of(book.sheet_by_name(YUNDA_SHEET))

    # 定位 南高齿FD2250Z 块
    start = None
    for r, row in enumerate(rows):
        if txt(row[0]) == YUNDA_BLOCK:
            start = r
            break
    if start is None:
        raise SystemExit("附件2 里找不到块：%s" % YUNDA_BLOCK)

    shafts_freq = {}          # 'n1' -> Hz
    gears = []
    bearings = []
    section = None
    for r in range(start, min(start + 80, len(rows))):
        a = txt(cell(rows, r, 0))
        if a in ("齿轮", "轴承"):
            if a == "齿轮" and section is not None:
                break                      # 又出现「齿轮」= 进入下一台齿轮箱，停
            section = a
            continue
        if a.startswith("Z") and section == "齿轮":
            teeth = num(re.sub(r"[^\d.]", "", txt(cell(rows, r, 2))))
            count = num(cell(rows, r, 3))
            f = num(cell(rows, r, 5))
            mesh = num(cell(rows, r, 6))
            desc = txt(cell(rows, r, 1))
            if teeth and f:
                gears.append({"id": a, "desc": desc, "teeth": teeth, "count": count,
                              "f": f, "mesh": mesh})
            continue
        if section == "轴承" and a:
            desc = txt(cell(rows, r, 1))
            model = txt(cell(rows, r, 2))
            bpfo, bpfi = num(cell(rows, r, 3)), num(cell(rows, r, 4))
            ftf, bsf = num(cell(rows, r, 5)), num(cell(rows, r, 7))
            if desc and (bpfo or bpfi):
                bearings.append({"id": a, "desc": desc, "model": model,
                                 "BPFO": bpfo, "BPFI": bpfi, "FTF": ftf,
                                 "BSF": bsf, "shaft": _yunda_shaft(desc)})

    # 轴转频：齿轮表里 n1 行星架、n3/n4 低速轴、n5/n6 中速轴、n7 高速轴、n2 行星轮
    by_id = {g["id"]: g for g in gears}
    need = {"n1": "Z1", "n2": "Z2", "n3": "Z3", "n4": "Z4", "n5": "Z5", "n7": "Z7"}
    for k, gid in need.items():
        if gid in by_id:
            shafts_freq[k] = by_id[gid]["f"]
    f_hss = shafts_freq.get("n7")
    if not f_hss:
        raise SystemExit("附件2 里取不到高速轴转频")
    f_carrier = shafts_freq["n1"]
    f_planet = shafts_freq.get("n2") or f_carrier
    f_lss = shafts_freq.get("n4") or shafts_freq.get("n3")
    f_mss = shafts_freq.get("n5")
    if not f_lss or not f_mss:
        raise SystemExit("附件2 里取不到低速/中速轴转频")

    shaft_hz = {"L": f_carrier, "P": f_planet, "S": f_lss, "M": f_mss, "H": f_hss}

    items = {}
    for bg in bearings:
        hz = shaft_hz.get(bg["shaft"])
        if not hz or hz <= 0:
            continue
        model = re.sub(r"\s+", " ", bg["model"]).strip()
        name = ("五峰%s %s" % (_short_desc(bg["desc"]), model)).strip()
        spec = {"shaft": bg["shaft"]}
        for k in FEATS:
            if bg[k]:
                spec[k] = round6(bg[k] / hz)
        items[name] = spec

    # 发电机轴承（附件2「发电机振动参数」：永济 6332 M.C4 / 湘电 6334 M/C3，1800rpm）
    gen = [
        ("五峰发电机 6332M C4", {"BPFO": 95.6, "BPFI": 144.4, "FTF": 12.0, "BSF": 141.6}),
        ("五峰发电机 6334M C3", {"BPFO": 94.8, "BPFI": 145.2, "FTF": 11.9, "BSF": 136.8}),
    ]
    for name, feats in gen:
        items[name] = dict({"shaft": "H"},
                           **{k: round6(v / f_hss) for k, v in feats.items()})

    # 主轴承（附件2「主轴承振动参数」240/800ECA/W33；原表数值量级很小，只入库不自动标注）
    mb = {"BPFO": 0.244, "BPFI": 0.289, "FTF": 0.008, "BSF": 0.194}
    items["五峰主轴承 240/800ECA/W33"] = dict({"shaft": "L"},
                                              **{k: round6(v / f_carrier) for k, v in mb.items()})

    # 行星级判读参数：齿数公约数（内齿圈/行星轮）与行星轮个数
    _planet = next((g for g in gears if g["id"] == "Z2"), None)
    _ring = next((g for g in gears if g["id"] == "Z1"), None)
    _gcd = teeth_gcd([_ring and _ring["teeth"], _planet and _planet["teeth"]])
    _planets = int(_planet["count"]) if (_planet and _planet.get("count")) else None

    g1 = {"name": "一级行星（92齿 × 行星架）", "teeth": 92.0, "shaft": "L", "sideband": "L"}
    if _gcd:
        g1["gcd"] = _gcd
    if _planets and _planets >= 2:
        g1["planets"] = _planets

    machine = {
        "projects": ["五峰"],
        "shafts": {k: round9(v / f_hss) for k, v in shaft_hz.items()},
        "gears": [
            g1,
            {"name": "二级（94齿 × 低速轴）", "teeth": 94.0, "shaft": "S", "sideband": "S"},
            {"name": "三级（125齿 × 中速轴）", "teeth": 125.0, "shaft": "M", "sideband": "M"},
        ],
        "points": _yunda_points(items),
        "_note": "运达 2.0MW（五峰），南高齿 FD2250Z；数据取自附件2 2000kW 页。",
    }
    return machine, items


def _yunda_points(items):
    """测点 -> 轴承名，按名字关键字现取，避免改名后引用失配。"""
    def pick(*kws):
        return [n for n in items if all(k in n for k in kws)]

    rules = [
        ("主轴轴承", pick("行星架前")),
        ("齿轮箱输入端", pick("低速轴前")),
        ("齿轮箱一级齿圈", pick("行星架前")),
        ("齿轮箱高速轴", pick("高速轴前") + pick("高速轴后轴承1")),
        ("发电机前轴", pick("发电机 6332") + pick("发电机 6334")),
        ("发电机后轴", pick("发电机 6332") + pick("发电机 6334")),
    ]
    return [[pt, names] for pt, names in rules if names]



def _yunda_shaft(desc):
    for kw, code in YUNDA_SHAFT_KW:
        if kw in desc:
            return code
    return None


def _short_desc(desc):
    """'1级行星级行星架前轴承' -> '行星架前轴承'；'2级平行轴中速轴后轴承1' -> '中速轴后轴承1'"""
    return re.sub(r"^[0-9一二三]级(行星级|行星轮级|平行轴)?", "", desc).strip()


# --------------------------------------------------------------------------- #
# 其它 14 个机型：C各机组振动诊断参数表
# --------------------------------------------------------------------------- #
SHAFT_KEYS = [
    ("行星轮", "N2"), ("行星架", "N1"), ("主轴", "N1"), ("主轴承", "N1"),
    ("低速轴", "N3"), ("中速轴", "N4"), ("高速轴", "N5"), ("发电机", "N6"), ("电机", "N6"),
]
AXIS_CODE = {"N1": "L", "N2": "P", "N3": "S", "N4": "M", "N5": "H", "N6": "H"}
# 轴承名关键字 -> 该测点应看的轴承（顺序敏感：先具体后笼统）
POINT_RULES = [
    ("主轴前", "主轴承_前轴径向"), ("主轴后", "主轴承_后轴径向"),
    ("低速轴前", "齿轮箱_一级内齿圈径向"), ("低速轴后", "齿轮箱_一级内齿圈径向"),
    ("行星架前", "齿轮箱_一级内齿圈径向"), ("行星架后", "齿轮箱_一级内齿圈径向"),
    ("行星轮", "齿轮箱_一级内齿圈径向"),
    ("中速轴", "齿轮箱_中部径向"),
    ("高速轴前", "齿轮箱_高速轴径向"), ("高速轴后", "齿轮箱_高速轴轴向"),
    ("发电机前", "发电机_前轴承径向"), ("电机前", "发电机_前轴承径向"),
    ("发电机后", "发电机_后轴承径向"), ("电机后", "发电机_后轴承径向"),
]


def parse_c_table(path):
    """返回 {机型: {"machine": ..., "bearings": {名: spec}}}"""
    import xlrd
    book = xlrd.open_workbook(path)
    out = {}
    for sheet in book.sheets():
        model, ctx, bgs, gears = _parse_c_sheet(sheet)
        if not ctx or not bgs:
            continue
        f_hss = ctx["f_hss"]
        bearings, points = {}, {}
        for bg in bgs:
            feats = {}
            for k, (mult, freq) in bg["feats"].items():
                if not (mult and mult > 0):
                    continue          # 倍数为空的不认（原表有残留垃圾行）
                h = (freq / f_hss) if (freq and freq > 0) else None
                if h and h > 0:
                    feats[k] = round6(h)
            if not feats:
                continue
            parts = [model, bg["name"]]
            if bg["code"]:
                parts.append(bg["code"])
            if bg["models"]:
                parts.append(" / ".join(bg["models"]))
            name = " ".join(p for p in parts if p).strip()
            bearings[name] = dict({"shaft": "H"}, **feats)
            for kw, pt in POINT_RULES:
                if kw in bg["name"]:
                    points.setdefault(pt, []).append(name)
                    break

        shafts = {"H": 1.0}      # 高速轴是基准，恒为 1
        for code, freq in ctx["axes"].items():
            k = AXIS_CODE.get(code)
            if k == "H" or not freq or freq <= 0:
                continue
            shafts[k] = round9(freq / f_hss)
        # 行星轮相对转速：取齿轮表 Z2 的故障频率（= 行星轮相对行星架转速）
        for g in gears:
            if g["id"] == "Z2" and g["f"]:
                shafts["P"] = round9(g["f"] / f_hss)
                break

        gs = []
        for g in _pick_gear_stages(gears, ctx, f_hss):
            gs.append(g)
        out[model] = {
            "machine": {
                "projects": [],
                "shafts": shafts,
                "gears": gs,
                "points": [[pt, names] for pt, names in points.items()],
                "_note": "由《C各机组振动诊断参数表》导入；倍数相对高速轴(电机)转频。",
            },
            "bearings": bearings,
        }
    return out


def _parse_c_sheet(sheet):
    rows = rows_of(sheet)
    model = txt(sheet.name)
    hdr = None
    for r in range(0, min(len(rows), 40)):
        if txt(cell(rows, r, 4)) == "名称" and txt(cell(rows, r, 7)).startswith("特征"):
            hdr = r
            break
    if hdr is None:
        return model, None, [], []
    f_hss = num(cell(rows, hdr - 1, 3))
    f_lss = num(cell(rows, hdr - 1, 1))
    if not f_hss:
        return model, None, [], []

    axes = {}
    for r in range(hdr + 1, len(rows)):
        code = txt(cell(rows, r, 1)).upper()
        mult = num(cell(rows, r, 2))
        freq = num(cell(rows, r, 3))
        if code.startswith("N"):
            # 原表「特征频率」列个别页写的是转速(rpm，如东汽 15.0)，统一用「倍数 × 叶轮转频」重算
            f = (mult * f_lss) if (mult and mult > 0 and f_lss) else freq
            if f and f > 0:
                axes[code] = f

    bearings, gears = [], []
    cur = None
    models = []
    for r in range(hdr + 1, len(rows)):
        nm = txt(cell(rows, r, 4))
        code = txt(cell(rows, r, 5))
        mdl = txt(cell(rows, r, 6))
        feat = txt(cell(rows, r, 7)).upper()
        if nm:
            if cur is not None:
                cur["models"] = models
                bearings.append(cur)
            cur = {"name": nm, "code": code, "models": [], "feats": {}}
            models = []
        if cur is not None:
            if mdl and mdl not in models:
                models.append(mdl)
            if feat in FEATS:
                cur["feats"][feat] = (num(cell(rows, r, 8)), num(cell(rows, r, 9)))
        # 右侧齿轮块：名称/代号/齿数/转频故障/故障频率/啮合频率
        gid = txt(cell(rows, r, 11))
        if gid.startswith("Z"):
            teeth = num(cell(rows, r, 12))
            count = num(cell(rows, r, 13))
            gf = num(cell(rows, r, 14))
            mesh = num(cell(rows, r, 15))
            gname = txt(cell(rows, r, 10))
            if teeth and mesh:
                gears.append({"id": gid, "name": gname, "teeth": teeth, "count": count,
                              "f": gf, "mesh": mesh})
    if cur is not None:
        cur["models"] = models
        bearings.append(cur)
    return model, {"f_hss": f_hss, "f_lss": f_lss, "axes": axes}, bearings, gears


def _pick_gear_stages(gears, ctx, f_hss):
    """按啮合频率分组，每组取齿数最大的那根轴，生成一级齿轮标注项。"""
    groups = {}
    for g in gears:
        key = round(g["mesh"], 1)
        groups.setdefault(key, []).append(g)
    stages = []
    for key in sorted(groups):
        best = max(groups[key], key=lambda g: g["teeth"])
        shaft = _shaft_for_freq(best["f"], ctx, f_hss)
        if not shaft:
            continue
        teeth = float(best["teeth"])
        item = {"name": "%s（%d齿 × %s）" % (best["name"], int(teeth), SHAFT_CN.get(shaft, shaft)),
                "teeth": teeth, "shaft": shaft, "sideband": shaft}
        # 同啮合频率的这对齿轮的齿数公约数 → 边带间隔可能是 GMF/n
        g = teeth_gcd([x["teeth"] for x in groups[key]])
        if g:
            item["gcd"] = g
        stages.append(item)
    return stages


def _shaft_for_freq(freq, ctx, f_hss):
    if not freq:
        return None
    cands = {}
    for code, f in ctx["axes"].items():
        if code in AXIS_CODE and f:
            cands[AXIS_CODE[code]] = f
    for code in ("L", "S", "M", "H"):
        f = cands.get(code)
        if f and abs(f - freq) / max(f, 1e-9) < 0.02:
            return code
    return None


# --------------------------------------------------------------------------- #
# 输出
# --------------------------------------------------------------------------- #
def build(dry_run=False):
    bearings = {}
    machines = {}

    # 1. 明阳
    machines["明阳2.0MW"] = mingyang_machine()
    for name, (shaft, mult) in MINGYANG_BEARINGS.items():
        bearings[name] = dict({"shaft": shaft}, **{k: round6(v) for k, v in mult.items()})

    # 2. 运达（五峰）
    if os.path.exists(YUNDA_XLS):
        m, b = parse_yunda(YUNDA_XLS)
        machines["运达2.0MW（五峰）"] = m
        bearings.update(b)
    else:
        print("警告：找不到附件2，跳过运达/五峰：%s" % YUNDA_XLS)

    # 3. 其它机型
    if os.path.exists(C_XLS):
        for model, pack in parse_c_table(C_XLS).items():
            machines[model] = pack["machine"]
            bearings.update(pack["bearings"])
    else:
        print("警告：找不到 C各机组表，跳过：%s" % C_XLS)

    print("机型 %d 个，轴承 %d 条" % (len(machines), len(bearings)))
    for name, m in machines.items():
        print("  %-18s 轴比 %-38s 齿轮 %d 级  测点 %d 个" % (
            name, "/".join("%s=%.5f" % (k, v) for k, v in m["shafts"].items() if k != "H"),
            len(m["gears"]), len(m["points"])))

    if dry_run:
        return
    os.makedirs(DATA, exist_ok=True)
    _backup(BEARING_FILE)
    _backup(MACHINE_FILE)
    with open(BEARING_FILE, "w", encoding="utf-8", newline="\n") as fp:
        json.dump({"version": 1,
                   "_note": "轴承名 -> (所在轴 H/M/S/L/P, 四个特征倍数)。倍数=特征频率/该轴转频。",
                   "bearings": bearings}, fp, ensure_ascii=False, indent=2)
        fp.write("\n")
    with open(MACHINE_FILE, "w", encoding="utf-8", newline="\n") as fp:
        json.dump({"version": 1,
                   "_note": "机型 -> 各轴转频比(相对高速轴)、齿轮级、测点->轴承。项目名关键字匹配 projects。",
                   "machines": machines}, fp, ensure_ascii=False, indent=2)
        fp.write("\n")
    print("已写入：\n  %s\n  %s" % (BEARING_FILE, MACHINE_FILE))


def _backup(path):
    if os.path.exists(path):
        import shutil
        shutil.copyfile(path, path + ".bak")


def main(argv=None):
    ap = argparse.ArgumentParser(description="生成 数据\\轴承库.json 与 数据\\机型库.json")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    build(args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
