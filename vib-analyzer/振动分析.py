# -*- coding: utf-8 -*-
""" 风电振动分析工具
修复：1.细化后红框持续显示(每次重绘补画patch) 2.全图x轴左边留2%空白不贴0
新增：所有谱图默认锁定X/Y轴(冻结视图，鼠标点击不再改标记) / 时域“基频+频率”标注
      (基频图标与谱图基频一致，频率单位Hz) / 基频点击自动吸附附近谱峰、方向键每次走一条谱线、
      Shift+方向每次0.5Hz并自动找峰、Shift+滚轮细化图谱 / 倍频·边带·带宽标识与信息面板美化
      / 时域坐标两侧不留自动空白(0~记录末尾铺满)、标题信息压缩并反算频率、标注5个周期
      / 自相关点选谱峰→基频→时域自动按周期标注
      / 自相关结果缓存+主线程轮询(修掉旧结果覆盖新图、工作线程碰 Tk、重复重算等问题)
"""
import os, sys, json, re, shutil, time, tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
from tkcalendar import DateEntry
import numpy as np
import pandas as pd
from scipy.signal import butter, filtfilt, sosfiltfilt, spectrogram, hilbert, find_peaks, resample
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from matplotlib.colors import Normalize, to_rgba
from matplotlib.offsetbox import TextArea, VPacker, AnnotationBbox
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.widgets import RectangleSelector
from datetime import datetime, date, timedelta
import threading
import sqlite3
import zipfile


def enable_dpi_awareness():
    """Windows 高 DPI 感知：让窗口按物理像素绘制，125%/150% 系统缩放下不再被 Windows
    位图拉伸（界面发虚、图上字偏小）。必须在创建任何 Tk 窗口之前调用；
    重复调用/非 Windows 平台都静默跳过（已被其他方式设置过会返回错误码，无害）。"""
    if sys.platform != "win32":
        return False
    try:
        import ctypes
    except Exception:
        return False
    try:
        # Win8.1+：SYSTEM_DPI_AWARE=1，跟随系统缩放且不做逐显示器动态切换，行为最稳
        if ctypes.windll.shcore.SetProcessDpiAwareness(1) == 0:
            return True
    except Exception:
        pass
    try:
        return bool(ctypes.windll.user32.SetProcessDPIAware())
    except Exception:
        return False


# 必须在 tk.Tk() 之前执行：本模块在 __main__ 里先导入、后建窗口，因此这里调用即生效
enable_dpi_awareness()

plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei']
plt.rcParams['axes.unicode_minus'] = False

# 程序所在目录：源码运行为脚本目录；PyInstaller 打包后为 exe 所在目录。
# 窗口几何等本地状态固定写到该目录，避免从快捷方式启动时工作目录不确定（可能落到 System32）。
if getattr(sys, "frozen", False):
    APP_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))

STATE_FILE = os.path.join(APP_DIR, "gui_state.json")
CACHE_SUFFIX = ".vibcache.json"
ANNOT_FILE = "vib_annotations.json"   # 按测点保存基频/倍频/边带/带宽标注
SUMMARY_FILE = "trend_summary.json"  # 趋势汇总缓存，避免遍历几千个小json
DB_FILE = "vib_cache.db"             # SQLite 趋势缓存库（取代大汇总 JSON，启动秒开）
DB_SCHEMA_VERSION = 2                # SQLite 表结构版本；VDI_VERSION 控制数据内容版本
# 明阳 MY2.0 齿轮箱链（与 明阳2.0MW.xlsx 一致）：高速轴→中速轴→太阳轮→低速轴/行星架
GB_I3 = 112.0 / 23.0        # 三级 4.8696
GB_I2 = 113.0 / 24.0        # 二级 4.7083
GB_I1 = 1.0 + 109.0 / 23.0  # 一级行星 5.7391
GB_ZR, GB_ZP = 109.0, 43.0

# 轴承特征频率倍数（明阳 2.0MW 库）：名称 -> (所在轴, {特征: 倍数})
# 轴代号：L=低速轴/行星架 S=太阳轮/低速轴 M=中速轴 H=高速轴/电机 P=行星轮(相对行星架)
BEARING_LIB = {
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
# 五峰（运达 2.0MW / 南高齿 FD2250Z）轴承库：附件2《运达各类型机组振动档案库.xls》2000kW 页
# 附件2 给出的是额定转速下的绝对频率(Hz)，这里除以所在轴转频换算成“倍数”，与明阳库同口径。
# 轴转频：行星架 0.229709、低速轴 1.286371、中速轴 5.75804、高速轴 29.989791、电机 30.0 Hz
_WF_LIB = {
    "五峰行星架前 NCF28/750": ("P", {"BPFO": 27.5, "BPFI": 30.6}),
    "五峰行星轮 NNCF5044": ("P", {"BPFO": 26.8, "BPFI": 34.8}),
    "五峰行星架后 NCF18/630": ("P", {"BPFO": 29.0, "BPFI": 32.1}),
    "五峰低速轴前 NU1080": ("S", {"BPFO": 11.74, "BPFI": 14.30, "FTF": 0.451, "BSF": 9.93}),
    "五峰低速轴后 LM567949": ("S", {"BPFO": 19.12, "BPFI": 22.00, "FTF": 0.466, "BSF": 14.02}),
    "五峰中速轴后 30244": ("M", {"BPFO": 8.58, "BPFI": 11.43, "FTF": 0.429, "BSF": 6.63}),
    "五峰中速轴后2 32244": ("M", {"BPFO": 9.07, "BPFI": 11.93, "FTF": 0.432, "BSF": 6.91}),
    "五峰高速轴前 NU2236": ("H", {"BPFO": 7.65, "BPFI": 10.36, "FTF": 0.423, "BSF": 6.51}),
    "五峰高速轴后 NU2230": ("H", {"BPFO": 8.16, "BPFI": 10.85, "FTF": 0.430, "BSF": 6.93}),
    "五峰高速轴后2 QJ330": ("H", {"BPFO": 5.42, "BPFI": 7.58, "FTF": 0.417, "BSF": 4.80}),
    # 发电机（附件2“发电机振动参数”：永济 6332 M.C4 / 湘电 6334 M/C3，1800rpm 绝对Hz）
    "五峰发电机 6332M C4": ("H", {"BPFO": 3.187, "BPFI": 4.813, "FTF": 0.400, "BSF": 4.72}),
    "五峰发电机 6334M C3": ("H", {"BPFO": 3.160, "BPFI": 4.840, "FTF": 0.397, "BSF": 4.56}),
}
BEARING_LIB.update(_WF_LIB)

# 外部轴承库：数据\轴承库.json（可选）。存在则合并进 BEARING_LIB：
#   同名轴承 → 用文件里的值覆盖；新名字 → 追加。
# 结构：
#   {"version": 1,
#    "bearings": {"轴承名": {"shaft": "H|M|S|L|P", "BPFI": 4.813, "BPFO": 3.187,
#                            "FTF": 0.400, "BSF": 2.360}}}
# 目的：改倍数不必动源码；缺文件或字段非法时只记 warning，启动不受影响。
BEARING_LIB_FILE = os.path.join(APP_DIR, "数据", "轴承库.json")
BEARING_SHAFTS = ("H", "M", "S", "L", "P")
BEARING_LIB_WARNINGS = []


def load_bearing_lib(path=None):
    """把 JSON 轴承库合并进 BEARING_LIB，返回 (新增数, 覆盖数, warnings)。

    文件不存在视为“用内置库”，返回 (0, 0, []) 且不留 warning。
    """
    path = path or BEARING_LIB_FILE
    warns = []
    if not os.path.exists(path):
        return 0, 0, warns
    try:
        # utf-8-sig：容忍记事本/PowerShell 另存时带的 BOM（纯 utf-8 也能读）
        with open(path, encoding="utf-8-sig") as fp:
            doc = json.load(fp)
    except Exception as e:
        warns.append("轴承库读取失败(%s): %s" % (os.path.basename(path), e))
        BEARING_LIB_WARNINGS.extend(warns)
        return 0, 0, warns
    items = doc.get("bearings") if isinstance(doc, dict) else None
    if not isinstance(items, dict):
        warns.append("轴承库格式错误：缺少 bearings 对象")
        BEARING_LIB_WARNINGS.extend(warns)
        return 0, 0, warns
    added = overridden = 0
    for name, spec in items.items():
        name = str(name).strip()
        if not name or not isinstance(spec, dict):
            warns.append("跳过非法条目: %r" % (name,))
            continue
        shaft = str(spec.get("shaft") or "").strip().upper()
        if shaft not in BEARING_SHAFTS:
            warns.append("%s: shaft 必须是 %s 之一，实际 %r" % (name, "/".join(BEARING_SHAFTS), shaft))
            continue
        mult = {}
        for k in ("BPFI", "BPFO", "BSF", "FTF"):
            v = spec.get(k)
            if v is None or str(v).strip() == "":
                continue
            try:
                v = float(v)
            except (TypeError, ValueError):
                warns.append("%s: %s=%r 不是数字" % (name, k, v))
                continue
            if v > 0:
                mult[k] = v
        if not mult:
            warns.append("%s: 没有任何有效倍数，已跳过" % name)
            continue
        overridden += 1 if name in BEARING_LIB else 0
        added += 0 if name in BEARING_LIB else 1
        BEARING_LIB[name] = (shaft, mult)
    BEARING_LIB_WARNINGS.extend(warns)
    return added, overridden, warns


load_bearing_lib()

_WF_POINTS = [
    ("主轴轴承", ["五峰行星架前 NCF28/750"]),
    ("齿轮箱输入端", ["五峰低速轴前 NU1080"]),
    ("齿轮箱一级齿圈", ["五峰行星架前 NCF28/750"]),
    ("齿轮箱高速轴", ["五峰高速轴前 NU2236", "五峰高速轴后 NU2230"]),
    ("发电机前轴", ["五峰发电机 6332M C4", "五峰发电机 6334M C3"]),
    ("发电机后轴", ["五峰发电机 6332M C4", "五峰发电机 6334M C3"]),
]

# 五峰测点采集异常清单（2026-03 全月抽样比对，偏离同型中位 10 倍以上）：
# 这些测点数据不参与分析/入库，避免误判。格式 {机组: [测点, ...]}
WF_BAD_POINTS = {
    "13": ["齿轮箱高速轴"],
    "14": ["齿轮箱高速轴"],
    "15": ["齿轮箱输入端"],
    "21": ["齿轮箱一级齿圈", "齿轮箱高速轴", "发电机前轴"],
    "22": ["齿轮箱一级齿圈"],
    "27": ["主轴轴承"],
    "30": ["齿轮箱一级齿圈", "发电机前轴", "发电机后轴"],
    "31": ["齿轮箱一级齿圈", "发电机前轴", "发电机后轴"],
    "33": ["发电机后轴"],
}
WF_BAD_POINTS_NOTE = "13#高速轴/22#一级齿圈/27#主轴轴承/15#输入端 为断线或严重干扰；14#高速轴、30#一级齿圈/发电机前后轴 为 48~50Hz 工频干扰"

def wf_bad_point(project, unit, point):
    """五峰项目里被判定为采集错误的测点：返回 True 表示该测点数据不可信、不参与分析。"""
    proj = str(project or "")
    if "五峰" not in proj and "五峰" not in str(unit or ""):
        return False
    u = str(unit or "").strip().rstrip("#号").lstrip("0")
    bad = WF_BAD_POINTS.get(u)
    if not bad:
        return False
    pt = str(point or "")
    return any(k in pt for k in bad)


BEARING_COLORS = {"BPFI": "#c62828", "BPFO": "#1565c0", "BSF": "#2e7d32", "FTF": "#6a1b9a"}

# 齿轮级定义（明阳 2.0MW 齿轮箱）：(显示名, 轴代号, 齿数, 边带所在轴)
# 一级行星：啮合 = 内齿圈109 × 行星架(低速轴)转频；二级：113齿在低速轴；三级：112齿在中速轴
GEAR_STAGES = [
    ("一级行星（109齿 × 行星架转频）", "L", 109.0, "L"),
    ("二级（113齿 × 低速轴转频）", "S", 113.0, "S"),
    ("三级（112齿 × 中速轴转频）", "M", 112.0, "M"),
]
GEAR_COLOR = "#d35400"       # 啮合频率
GEAR_SB_COLOR = "#e8a06a"    # 边带

# 哪个项目用这套轴承库（明阳2.0MW）。项目名里含关键字即生效；其它项目（如五峰/田家寨）不自动标注。
# 每条： (测点名里含的关键字, [轴承名...])，按顺序匹配，先匹配到的生效。
_FUGU_POINTS = [
    ("主轴承", ["主轴 N1 F-612211"]),
    ("行星轮", ["行星轮 N2 NNCF5052"]),
    ("低速轴前", ["低速轴前 N3 NU1080"]),
    ("低速轴后", ["低速轴后 N4 LM567949"]),
    ("中速轴前", ["中速轴前 N5 NU2244"]),
    ("中速轴后", ["中速轴后 N6 30244"]),
    ("高速轴径向", ["高速轴后 N9 NU234"]),
    ("高速轴轴向", ["高速轴后 N9 NU234"]),
    ("中部径向", ["中速轴前 N5 NU2244"]),
    ("一级内齿圈", ["低速轴前 N3 NU1080"]),
    # 发电机前/后轴承都可能是 6332MC4（B12、B13 是同一型号、倍数一致）或 SKF6334
    ("发电机前轴承", ["电机前 B12 6332MC4", "电机 SKF6334"]),
    ("发电机后轴承", ["电机后 6332MC4", "电机 SKF6334"]),
    ("发电机", ["电机前 B12 6332MC4", "电机 SKF6334"]),
]
# 同一套库对应多个项目名：府谷（原称）、田家寨（现场名）、五峰（运达 2.0MW / 南高齿 FD2250Z）
BEARING_PROJECT_MAP = {"府谷": _FUGU_POINTS, "田家寨": _FUGU_POINTS, "五峰": _WF_POINTS}

AUTOCORR_MAX_TAU = 0.2
AUTOCORR_DOWNSAMPLE_FS = None  # 不降采样，用原始fs保证精度

rule_text = """齿轮箱_高速轴径向,10,5000,7.5
齿轮箱_高速轴轴向,10,5000,7.5
齿轮箱_一级内齿圈径向,0,10,0.3
齿轮箱_中部径向,10,2000,7.5
发电机_后轴承径向,10,5000,7.5
发电机_前轴承径向,10,5000,7.5
发电机_前轴承轴向,10,5000,7.5
主轴承_后轴径向,10,5000,7.5
主轴承_前轴径向,10,5000,7.5
主轴_前轴径向,0,100,0.3
主轴_后轴径向,0,100,0.3"""

rule_dict = {}
for line in rule_text.strip().splitlines():
    name, f1, f2, thr = line.split(',')
    rule_dict[name] = {"f_low": float(f1), "f_high": float(f2), "threshold": float(thr)}

# 打开时域图/各谱图时默认应用的带通滤波范围（下限,上限 Hz）；命中即默认勾选“应用带通”
default_bp_text = """主轴承_前轴径向,0,150
主轴承_后轴径向,0,150
主轴_前轴径向,0,150
主轴_后轴径向,0,150
齿轮箱_输入端水平径向,0,200
齿轮箱_输入轴水平径向,0,200
齿轮箱_一级内齿圈径向,0,300
齿轮箱_一级齿圈径向,0,300
齿轮箱_二级内齿圈径向,0,300
齿轮箱_二级齿圈径向,0,300
齿轮箱_中部径向,0,750
齿轮箱_高速轴径向,0,1000
齿轮箱_高速轴轴向,0,1000
发电机_前轴承径向,0,5000
发电机_前轴承轴向,0,5000
发电机_后轴承径向,0,5000
齿轮箱高速轴,0,1000
齿轮箱输入端,0,200
齿轮箱一级齿圈,0,300
发电机后轴,0,5000
发电机前轴,0,5000
主轴轴承,0,150"""

default_bp = {}
for line in default_bp_text.strip().splitlines():
    _name, _lo, _hi = line.split(',')
    default_bp[_name.strip()] = (float(_lo), float(_hi))

# 表中若有测点不在计算规则内，补入可处理名单（阈值暂记 0，滤波范围用默认表）
for _name, (_lo, _hi) in default_bp.items():
    if _name not in rule_dict:
        rule_dict[_name] = {"f_low": _lo, "f_high": _hi, "threshold": 0.0}


# 树状图测点固定展示顺序：三大类严格按 主轴（含主轴承）→ 齿轮箱 → 发电机 排列；
# 大类内部再按部位/方向排序，无方向简称归入所属大类末尾，未命中名称统一排最后并按名称排序，保证不丢点。
def tree_unit_order(name):
    """机组排序：按数字从小到大（1#、2#、…、10#、25#），无数字的排后面按名字。"""
    import re as _re
    m = _re.search(r"(\d+)", str(name or ""))
    if m:
        return (0, int(m.group(1)), str(name))
    return (1, 0, str(name))


def tree_point_order(name):
    n = name or ""
    rules = (
        ("主轴" in n and "前" in n and "承" not in n),       # 0 主轴_前轴径向
        ("主轴" in n and "后" in n and "承" not in n),       # 1 主轴_后轴径向
        ("主轴承" in n and "前" in n),                        # 2 主轴承_前轴径向
        ("主轴承" in n and "后" in n),                        # 3 主轴承_后轴径向
        ("主轴" in n),                                        # 4 主轴类兜底（如简称“主轴轴承”）
        ("齿轮箱" in n and "输入" in n),                      # 5 齿轮箱输入
        ("齿轮箱" in n and "一级" in n),                      # 6 齿轮箱一级齿圈
        ("齿轮箱" in n and "二级" in n),                      # 7 齿轮箱二级齿圈
        ("齿轮箱" in n and "中部" in n),                      # 8 齿轮箱中部
        ("齿轮箱" in n and "高速" in n and "径向" in n),      # 9 齿轮箱高速轴径向
        ("齿轮箱" in n and "高速" in n and "轴向" in n),      # 10 齿轮箱高速轴轴向
        ("齿轮箱" in n),                                      # 11 齿轮箱类兜底（无方向简称，仍在发电机之前）
        ("发电机" in n and "前" in n and "径向" in n),        # 12 发电机前轴径向
        ("发电机" in n and "前" in n and "轴向" in n),        # 13 发电机前轴轴向
        ("发电机" in n and "后" in n and "径向" in n),        # 14 发电机后轴径向
        ("发电机" in n),                                      # 15 发电机类兜底（无方向简称）
    )
    for i, ok in enumerate(rules):
        if ok:
            return i
    return len(rules)


def rms_alarm_for(point):
    """按测点名称返回 RMS 报警阈值；返回 None 表示该测点不设 RMS 报警线。
    规则：发电机 10；齿轮箱高速轴/二级齿圈/中部 7.5，其余齿轮箱 0.3；主轴与主轴承 0.3。"""
    p = point or ""
    if "发电机" in p:
        return 10.0
    if "齿轮箱" in p:
        if ("高速轴" in p) or ("二级齿圈" in p) or ("中部" in p):
            return 7.5
        return 0.3
    if "主轴" in p:  # “主轴承”名称含“主轴”子串，同归低速级 0.3
        return 0.3
    return None


# ===== VDI 3834 风力发电机加速度分频段 RMS 报警（仅加速度，单位 m/s²；三档 B/C/D）=====
VDI_VERSION = 3  # 缓存结构版本号：v3 起 RMS 改为按测点分频带计算（0.1-10 / 10-1000 / 10-5000Hz）
# 每个测点类别下的频带：(结果键, 下限Hz, 上限Hz, B/C报警边界, C/D危险边界)
VDI_SPEC = {
    "mainshaft": [("vdi_low", 0.1, 10.0, 0.3, 0.5)],
    "gearbox": [("vdi_low", 0.1, 10.0, 0.3, 0.5),
                ("vdi_mid", 10.0, 1000.0, 7.5, 12.0)],
    "generator": [("vdi_mid", 10.0, 1000.0, 6.0, 10.0),
                  ("vdi_hi", 10.0, 5000.0, 10.0, 16.0)],
}
_VDI_RANK = {"B": 1, "C": 2, "D": 3}
# 频带键 -> 中文频率范围标注（趋势图阈值线右端文字）
_VDI_BAND_NAME = {"vdi_low": "0.1-10Hz", "vdi_mid": "10-1000Hz", "vdi_hi": "10-5000Hz"}
_VDI_BAND_SHORT = {"vdi_low": "低频", "vdi_mid": "中频", "vdi_hi": "高频"}
_VDI_BAND_ORDER = ["vdi_low", "vdi_mid", "vdi_hi"]
# 三个固定频带的纯数值定义（不含阈值）：所有 VDI 测点都计算带内 RMS 供表格/趋势显示，
# 但 B/C/D 评级只使用 VDI_SPEC 中为该类别规定的频带
_VDI_ALL_BANDS = [("vdi_low", 0.1, 10.0), ("vdi_mid", 10.0, 1000.0), ("vdi_hi", 10.0, 5000.0)]
VDI_BC_COLOR = "#e07b00"  # B/C 报警边界：橙色虚线
VDI_CD_COLOR = "#d00000"  # C/D 危险边界：红色虚线
TREND_HEADER_BG = "#e8edf3"  # 趋势图标题+图例整条统一底色：柔和浅蓝灰
TREND_HEADER_FG = "#243447"  # 标题/图例文字色：深蓝灰，与浅底形成稳重对比


def vdi_category(point):
    p = point or ""
    if "发电机" in p:
        return "generator"
    if "齿轮箱" in p:
        return "gearbox"
    if "主轴" in p:  # “主轴承”含“主轴”子串
        return "mainshaft"
    return None


RMS_BANDS = {"vdi_low": (0.1, 10.0), "vdi_mid": (10.0, 1000.0), "vdi_hi": (10.0, 5000.0)}


def rms_band_key(point):
    """按现场口径把测点归到 RMS 计算频带（与 VDI 频带同义）：
      主轴轴承 / 齿轮箱输入 / 齿轮箱(一级)齿圈            → 0.1-10 Hz   (vdi_low)
      齿轮箱二级齿圈 / 中部 / 低速 / 高速                 → 10-1000 Hz  (vdi_mid)
      发电机                                              → 10-5000 Hz  (vdi_hi)
    判断顺序很重要：先“二级齿圈”，再“输入/齿圈”，最后才是“高速/中部”等通用词。
    未命中返回 None，调用方回退到规则表的带通 RMS。
    """
    p = point or ""
    if "发电机" in p:
        return "vdi_hi"
    if "齿轮箱" in p:
        if ("二级" in p and "齿圈" in p) or ("中部" in p) or ("低速" in p) or ("高速" in p):
            return "vdi_mid"
        if ("输入" in p) or ("齿圈" in p):
            return "vdi_low"
        return "vdi_low"   # 只写“齿轮箱”未细分：按低速级处理
    if ("主轴" in p) or ("主轴承" in p):
        return "vdi_low"
    return None


def table_rms_band(point):
    """数据表格 / 趋势图 RMS 列采用的频带键，与 rms_band_key 同一口径。"""
    return rms_band_key(point)


def rms_band_for(point):
    """返回 (下限Hz, 上限Hz)；未命中返回 None。"""
    return RMS_BANDS.get(rms_band_key(point))


def format_table_rms(value):
    """数据表格 RMS 列显示：保留两位小数；0<value<0.01 的极小正值按下限 0.01 计，0 仍显示 0.00。"""
    if not isinstance(value, (int, float)):
        value = 0.0
    if 0 < value < 0.01:
        value = 0.01
    return f"{value:.2f}"


def shift_pressed(event):
    """滚轮事件是否按住 Shift。新版 matplotlib 把修饰键放在 modifiers，
    旧版/TkAgg 可能给空元组或放在 key / guiEvent.state，这里逐级兜底判断，
    避免“按住 Shift 滚轮没反应”。"""
    mods = getattr(event, "modifiers", None)
    try:
        if mods and "shift" in mods:
            return True
    except TypeError:
        pass
    if getattr(event, "key", None) == "shift":
        return True
    try:
        return bool(int(getattr(getattr(event, "guiEvent", None), "state", 0)) & 0x1)
    except Exception:
        return False


def band_rms_fft(sig, fs, f1, f2):
    """一次 FFT 求 [f1,f2] 频带内加速度 RMS（m/s²，矩形窗、能量严格守恒）。
    上限按有效分析频率 fs/2.56 收口；频带无效或无频点返回 None。"""
    x = np.asarray(sig, dtype=float)
    x = x - np.mean(x)
    n = len(x)
    f2 = min(float(f2), float(fs) / 2.56)  # 用户固定口径：有效上限 fs/2.56
    if n < 4 or f2 <= f1:
        return None
    X = np.fft.rfft(x)
    fr = np.fft.rfftfreq(n, 1.0 / fs)
    power = np.abs(X) ** 2
    weights = np.full(len(fr), 2.0)  # 单边谱：内部频点加倍
    weights[0] = 1.0
    if n % 2 == 0:
        weights[-1] = 1.0  # Nyquist 不加倍
    mask = (fr >= f1) & (fr <= f2)
    if not np.any(mask):
        return None
    return float(np.sqrt(np.sum(weights[mask] * power[mask]) / (n * n)))


def _vdi_letter(value, bc, cd):
    if value is None:
        return ""
    if value > cd:
        return "D"
    if value > bc:
        return "C"
    return "B"


def compute_vdi(sig, fs, point):
    """按测点类别计算各频带加速度 RMS 与 B/C/D 评级，综合等级取各频带最差者。
    整条信号只做一次 FFT，多个频带复用同一频谱；上限统一按 fs/2.56 收口。"""
    res = {"vdi_low": None, "vdi_mid": None, "vdi_hi": None,
           "vdi_low_g": "", "vdi_mid_g": "", "vdi_hi_g": "", "vdi_grade": ""}
    cat = vdi_category(point)
    if cat is None:
        return res
    x = np.asarray(sig, dtype=float)
    x = x - np.mean(x)
    n = len(x)
    if n < 4:
        return res
    X = np.fft.rfft(x)
    fr = np.fft.rfftfreq(n, 1.0 / fs)
    power = np.abs(X) ** 2
    weights = np.full(len(fr), 2.0)  # 单边谱：内部频点加倍
    weights[0] = 1.0
    if n % 2 == 0:
        weights[-1] = 1.0  # Nyquist 不加倍
    f_eff = float(fs) / 2.56
    worst = 0
    _graded = set()
    for key, f1, f2, bc, cd in VDI_SPEC[cat]:
        _graded.add(key)
        value = None
        fb = min(float(f2), f_eff)
        if fb > f1:
            mask = (fr >= f1) & (fr <= fb)
            if np.any(mask):
                value = float(np.sqrt(np.sum(weights[mask] * power[mask]) / (n * n)))
        res[key] = value
        letter = _vdi_letter(value, bc, cd)
        res[key + "_g"] = letter
        if letter and _VDI_RANK[letter] > worst:
            worst = _VDI_RANK[letter]
    # 补齐该类别不参与评级的频带：只存带内 RMS 数值，等级留空、不计入综合 vdi_grade
    for key, f1, f2 in _VDI_ALL_BANDS:
        if key in _graded:
            continue
        value = None
        fb = min(float(f2), f_eff)
        if fb > f1:
            mask = (fr >= f1) & (fr <= fb)
            if np.any(mask):
                value = float(np.sqrt(np.sum(weights[mask] * power[mask]) / (n * n)))
        res[key] = value
    res["vdi_grade"] = {1: "B", 2: "C", 3: "D"}.get(worst, "")
    return res



def design_band(fs, lowcut, highcut, order=4, sos=False):
    """统一的低通/带通滤波器设计：Nyquist 一律用真实的 fs/2，截止频率收口到 (0, fs/2)。

    旧代码在多处把 fs/2.56（有效分析带宽）当作 Nyquist 传给 scipy，造成两类问题：
      1) 实际截止频率被放大约 1.28 倍（设定 0-1000Hz，实际 1280Hz 才开始衰减）；
      2) 请求上限 >= fs/2.56 时归一化频率 Wn >= 1，scipy 直接抛 ValueError，
         表现为“包络带通错误/带通错误”弹窗且图画不出来。
    """
    nyq = float(fs) / 2.0
    hi = min(max(float(highcut), 1e-3), nyq * 0.999)
    lo = max(float(lowcut), 0.0)
    if lo <= 1e-9:
        return butter(order, hi / nyq, btype="low", output="sos" if sos else "ba")
    lo = min(lo, hi * 0.98)
    return butter(order, [lo / nyq, hi / nyq], btype="band", output="sos" if sos else "ba")


def butter_bandpass(fs, lowcut, highcut, order=4):
    """兼容旧调用：等价于 design_band(..., sos=False)。"""
    return design_band(fs, lowcut, highcut, order=order)


def bandpass_rms(sig, fs, f_low, f_high):
    b, a = design_band(fs, f_low, f_high)
    return float(np.sqrt(np.mean(filtfilt(b, a, sig) ** 2)))


def parse_filename(fn):
    """解析文件名：<项目>_<机组>_<测点>_<fs>Hz_<时长>s_加速度值_<转速>_<14位时间>.csv

    也兼容“文件名里没有转速”的导出（如 ..._加速度值_20250504090029.csv）：此时 speed=None，
    阶次谱会改用基频标记或弹框让用户填转频。
    """
    stem = os.path.splitext(fn)[0]
    empty = {"project": "", "unit": "", "point": "", "fs": None, "duration": None,
             "dt": None, "speed": None}
    speed = None
    # 五峰/中节能等采集软件：<项目>_<机组>_<测点>_<fs>Hz_加速度_<转速>_<14位时间>（无时长字段）
    m_wf = re.match(r"(.*?)_(\d+)Hz_加速度_(\d+)_(\d{14})$", stem)
    if m_wf:
        pre_str, fs_str, rpm_str, timestr = m_wf.groups()
        pre_parts = pre_str.split("_", 2)
        if len(pre_parts) < 3:
            return empty
        project, unit, point = pre_parts
        try:
            fs = float(fs_str)
            speed = int(rpm_str)
            dt = datetime.strptime(timestr, "%Y%m%d%H%M%S")
        except Exception:
            return empty
        return {"project": project, "unit": unit, "point": point,
                "fs": fs, "duration": None, "dt": dt, "speed": speed}
    m_wf2 = re.match(r"(.*?)_(\d+)Hz_加速度_(\d{14})$", stem)
    if m_wf2:
        pre_str, fs_str, timestr = m_wf2.groups()
        pre_parts = pre_str.split("_", 2)
        if len(pre_parts) < 3:
            return empty
        project, unit, point = pre_parts
        try:
            fs = float(fs_str)
            dt = datetime.strptime(timestr, "%Y%m%d%H%M%S")
        except Exception:
            return empty
        return {"project": project, "unit": unit, "point": point,
                "fs": fs, "duration": None, "dt": dt, "speed": None}
    m = re.match(r"(.*?)_(\d+)Hz_([\d\.]+)s_加速度值_(\d+)_(\d{14})$", stem)
    if m:
        pre_str, fs_str, dur_str, rpm_str, timestr = m.groups()
        try:
            speed = int(rpm_str)
        except Exception:
            speed = None
    else:
        m2 = re.match(r"(.*?)_(\d+)Hz_([\d\.]+)s_加速度值_(\d{14})$", stem)
        if not m2:
            return empty
        pre_str, fs_str, dur_str, timestr = m2.groups()
    pre_parts = pre_str.split("_", 2)
    if len(pre_parts) < 3:
        return empty
    project, unit, point = pre_parts
    try:
        fs = float(fs_str); duration = float(dur_str)
        dt = datetime.strptime(timestr, "%Y%m%d%H%M%S")
    except Exception:
        return empty
    return {"project": project, "unit": unit, "point": point,
            "fs": fs, "duration": duration, "dt": dt, "speed": speed}


def decode_zip_name(name):
    """还原因解压软件编码问题变成乱码的 zip 内文件名。

    Windows 采集软件打的包，中文名常是 UTF-8 字节却没设置 UTF-8 标志位，
    zipfile 会按 cp437 解成乱码（"鍖楅鍨?..."），这里按 cp437 取回原始字节再按 UTF-8/GBK 解码。
    """
    if not name:
        return name
    try:
        name.encode("ascii")
        return name                      # 纯 ASCII，不用动
    except Exception:
        pass
    try:
        raw = name.encode("cp437")
    except Exception:
        return name
    for enc in ("utf-8", "gbk"):
        try:
            out = raw.decode(enc)
            if out and out != name:
                return out
        except Exception:
            continue
    return name


def parse_vendor_name(fname, point_names):
    """识别采集软件导出的文件名：<项目>_<机组><测点><转速>_<14位时间>.csv

    例：北风垭_125齿轮箱高速轴1483_20250504090029
        -> 项目=北风垭 机组=125 测点=齿轮箱高速轴 转速=1483 时间=20250504090029
    测点用程序内置名单反查（优先匹配长名字），识别不出返回 None。
    """
    stem = os.path.splitext(os.path.basename(str(fname)))[0]
    m = re.match(r"^(?P<head>.+)_(?P<ts>\d{14})$", stem)
    if not m:
        return None
    head, ts = m.group("head"), m.group("ts")
    for pn in sorted(point_names, key=len, reverse=True):
        m2 = re.match(r"^(?P<pre>.*?)(?P<point>%s)(?P<rpm>\d+)?$" % re.escape(pn), head)
        if not m2:
            continue
        pre = (m2.group("pre") or "").rstrip("_")
        rpm = m2.group("rpm") or ""
        parts = pre.split("_", 1) if pre else []
        return {"project": parts[0] if parts else "",
                "unit": parts[1] if len(parts) > 1 else "",
                "point": pn, "rpm": rpm, "ts": ts}
    return None


def normalize_projects(rows):
    # 一个项目总目录视为同一个项目：清理项目/机组/测点名称首尾空白，
    # 并把不同写法的项目名统一到主项目（出现次数最多者），
    # 避免向已存在项目上传新数据时因文件名项目段差异而新建顶层项目节点。
    from collections import Counter
    for r in rows:
        for k in ("project", "unit", "point"):
            v = r.get(k)
            if isinstance(v, str):
                r[k] = v.strip()
    names = [r.get("project", "") for r in rows if r.get("project")]
    if not names:
        return
    main_project = Counter(names).most_common(1)[0][0]
    for r in rows:
        if r.get("project") and r["project"] != main_project:
            r["project"] = main_project


def get_cache_path(csv_path): return csv_path + CACHE_SUFFIX


def load_cache(csv_path):
    cp = get_cache_path(csv_path)
    if os.path.exists(cp):
        try: return json.load(open(cp, encoding="utf-8"))
        except: return None
    return None


def save_cache(csv_path, data):
    json.dump(data, open(get_cache_path(csv_path), "w", encoding="utf-8"), ensure_ascii=False, indent=2)


# ===================== SQLite 趋势缓存（取代 trend_summary.json 与启动遍历小 JSON）=====================
# 记录列与 process_one_csv 输出 dict 的键保持一致，便于按列名直接映射、下游 all_data 零改动。
RECORD_COLUMNS = [
    "csv_path", "project", "unit", "point", "dt_str", "dt_ts", "dt_date",
    "rms", "threshold", "peak", "kurtosis", "ge", "f_low", "f_high", "speed", "vdi_ver",
    "vdi_low", "vdi_mid", "vdi_hi",
    "vdi_low_g", "vdi_mid_g", "vdi_hi_g", "vdi_grade",
]
_DDL_RECORDS = """
CREATE TABLE IF NOT EXISTS records(
    csv_path  TEXT PRIMARY KEY,
    project   TEXT, unit TEXT, point TEXT,
    dt_str    TEXT, dt_ts REAL, dt_date TEXT,
    rms       REAL, threshold REAL, peak REAL, kurtosis REAL, ge REAL,
    f_low     REAL, f_high REAL, speed REAL, vdi_ver INTEGER,
    vdi_low   REAL, vdi_mid REAL, vdi_hi REAL,
    vdi_low_g TEXT, vdi_mid_g TEXT, vdi_hi_g TEXT, vdi_grade TEXT
)"""
_DDL_META = "CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v)"
# 覆盖树分组、趋势按测点+时间、日期/转速筛选等主要访问路径
_DDL_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_rec_point_time ON records(point, dt_ts)",
    "CREATE INDEX IF NOT EXISTS idx_rec_pup ON records(project, unit, point)",
    "CREATE INDEX IF NOT EXISTS idx_rec_time ON records(dt_ts)",
    "CREATE INDEX IF NOT EXISTS idx_rec_date ON records(dt_date)",
]


def get_db_path(main_dir):
    return os.path.join(main_dir, DB_FILE)


def db_connect(main_dir):
    """打开（不存在则初始化）项目 SQLite 库：建表、建索引并做写入性能 PRAGMA 调优。"""
    conn = sqlite3.connect(get_db_path(main_dir), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA cache_size=-65536")  # 64MB 页缓存，加速批量写入与全量读取
    conn.execute(_DDL_RECORDS)
    conn.execute(_DDL_META)
    conn.commit()
    _ensure_schema(conn)
    for _ddl in _DDL_INDEXES:
        conn.execute(_ddl)
    conn.commit()
    return conn


def _col_type(col):
    if col == "vdi_ver":
        return "INTEGER"
    if col in ("csv_path", "project", "unit", "point", "dt_str", "dt_date",
               "vdi_low_g", "vdi_mid_g", "vdi_hi_g", "vdi_grade"):
        return "TEXT"
    return "REAL"


def _ensure_schema(conn):
    """校验/迁移 SQLite 表结构：补列、写 schema_ver；库版本高于程序则拒绝使用。"""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(records)")}
    missing = [c for c in RECORD_COLUMNS if c not in cols]
    old = db_get_meta(conn, "schema_ver")
    try:
        old_i = int(old) if old is not None else 0
    except (TypeError, ValueError):
        old_i = 0
    if old_i > DB_SCHEMA_VERSION:
        raise RuntimeError(
            f"数据库结构版本 {old_i} 高于当前程序支持的 {DB_SCHEMA_VERSION}，"
            "请升级程序后再打开该目录")
    for c in missing:
        conn.execute(f"ALTER TABLE records ADD COLUMN {c} {_col_type(c)}")
    if missing or old_i != DB_SCHEMA_VERSION:
        db_set_meta(conn, "schema_ver", DB_SCHEMA_VERSION)
        conn.commit()


def db_peek_schema(main_dir):
    """只读查看库结构版本，供上传前判断是否需要强制重算（不建表、不迁移）。"""
    p = get_db_path(main_dir)
    if not os.path.exists(p):
        return None
    try:
        c = sqlite3.connect(p, timeout=5)
        try:
            row = c.execute("SELECT v FROM meta WHERE k='schema_ver'").fetchone()
            return row[0] if row else None
        finally:
            c.close()
    except Exception:
        return None


def db_get_meta(conn, key, default=None):
    row = conn.execute("SELECT v FROM meta WHERE k=?", (key,)).fetchone()
    return row["v"] if row is not None else default


def db_set_meta(conn, key, value):
    conn.execute("INSERT OR REPLACE INTO meta(k, v) VALUES(?, ?)", (key, value))


def db_count(conn):
    return conn.execute("SELECT COUNT(*) FROM records").fetchone()[0]


def _records_insert_sql():
    collist = ",".join(RECORD_COLUMNS)
    placeholders = ",".join("?" * len(RECORD_COLUMNS))
    return f"INSERT OR REPLACE INTO records({collist}) VALUES({placeholders})"


def _coerce_row(r):
    """按列转成可绑定到 SQLite 的元组；dt_date 在内存里可能是 date 对象，统一转回 ISO 文本。"""
    vals = []
    for c in RECORD_COLUMNS:
        v = r.get(c)
        if c == "dt_date" and isinstance(v, (date, datetime)):
            v = v.isoformat()
        vals.append(v)
    return tuple(vals)


def db_upsert_rows(conn, rows):
    """按主键 csv_path 批量 upsert（用于旧汇总 JSON 一次性迁移），单事务提交。"""
    if not rows:
        return
    sql = _records_insert_sql()
    data = [_coerce_row(r) for r in rows]
    with conn:
        conn.executemany(sql, data)


def db_delete_paths(conn, paths):
    """按 csv_path 批量删除孤儿记录（磁盘上已删除/移走的 CSV）。"""
    if not paths:
        return
    with conn:
        conn.executemany("DELETE FROM records WHERE csv_path=?", [(p,) for p in paths])


def db_replace_all(conn, rows):
    """全量替换：清空旧记录后批量写入（同时清除已删 CSV 的孤儿记录与旧版本数据），单事务。"""
    sql = _records_insert_sql()
    data = [_coerce_row(r) for r in rows]
    with conn:
        conn.execute("DELETE FROM records")
        conn.executemany(sql, data)


def db_load_all(conn):
    """一次性读出全部记录为 list[dict]；dt_date 由文本转为 date 对象，与历史缓存主路径一致。"""
    collist = ",".join(RECORD_COLUMNS)
    out = []
    for row in conn.execute(f"SELECT {collist} FROM records"):
        d = dict(row)
        ds = d.get("dt_date")
        if isinstance(ds, str):
            try:
                d["dt_date"] = date.fromisoformat(ds)
            except Exception:
                d["dt_date"] = None
        out.append(d)
    return out


def process_one_csv(csv_path):
    try:
        fn = os.path.basename(csv_path); info = parse_filename(fn); point = info["point"]
        if not point: return None, f"测点名为空: {fn}"
        if point not in rule_dict: return None, f"测点[{point}]不在规则列表"
        rule = rule_dict[point]; fs = info["fs"]
        if fs is None: return None, f"未解析到fs: {fn}"
        try:
            sig = pd.read_csv(csv_path, header=None).iloc[:, 0]
            sig = pd.to_numeric(sig, errors="coerce").dropna().values.astype(float)
        except Exception as e:
            return None, f"读csv失败: {e}"
        if len(sig) < fs * 0.5: return None, f"数据点太少({len(sig)})"
        # RMS 口径：按测点名称落到 0.1-10 / 10-1000 / 10-5000 Hz 三个频带之一；
        # 不在映射内的测点回退到规则表带通。带内 RMS 用一次 FFT 求，和 VDI 分频段值完全同口径。
        rms_lo, rms_hi = rms_band_for(point) or (float(rule["f_low"]), float(rule["f_high"]))
        rms = band_rms_fft(sig, fs, rms_lo, rms_hi)
        if rms is None:
            rms = bandpass_rms(sig, fs, rms_lo, rms_hi)
        rms = float(rms)
        peak = float(np.max(np.abs(sig)))
        sig_c = sig - np.mean(sig)
        var = float(np.mean(sig_c ** 2))
        _pk_c = float(np.max(np.abs(sig_c)))
        _sd = float(np.sqrt(var))
        # 近停机/近恒定信号：背景能量趋零时方差分母极小，单个量化尖峰会令峭度虚高到数百上千。
        # 当波峰因子 peak/sd 极高（sd/peak < 0.03）判定峭度不可信并置 0；有效信号的真实冲击峭度照常保留。
        if var <= 0.0 or _pk_c <= 0.0 or (_sd / _pk_c) < 0.03:
            kurt = 0.0
        else:
            kurt = float(np.mean(sig_c ** 4) / (var ** 2) - 3.0)
        # 包络gE：整体包络信号的RMS
        env_sig = np.abs(hilbert(sig))
        ge = float(np.sqrt(np.mean(env_sig ** 2)))
        # VDI 3834 加速度分频段 RMS 与 B/C/D 评级（频域一次 FFT）
        vdi = compute_vdi(sig, fs, point)
        out = {"csv_path": csv_path, "project": info["project"], "unit": info["unit"], "point": point,
               "dt_str": info["dt"].strftime("%Y-%m-%d %H:%M:%S") if info["dt"] else None,
               "dt_ts": info["dt"].timestamp() if info["dt"] else None,
               "dt_date": info["dt"].date().isoformat() if info["dt"] else None,
               "rms": rms, "threshold": rule["threshold"],
               "peak": peak, "kurtosis": kurt, "ge": ge,
               "f_low": rms_lo, "f_high": rms_hi, "speed": info["speed"],
               "vdi_ver": VDI_VERSION, **vdi}
        # 不再逐文件写 .vibcache.json：SQLite 已是唯一缓存，避免十几万次小文件写盘
        return out, None
    except Exception as e:
        import traceback
        return None, f"异常: {e}\n{traceback.format_exc()[:300]}"


def autocorr_fft(x, max_lag):
    n = len(x); x = x - np.mean(x)
    L = 1
    while L < n + max_lag: L <<= 1
    f = np.fft.rfft(x, L)
    ac = np.fft.irfft(f * np.conj(f))[:max_lag + 1]
    if not np.isfinite(ac[0]) or ac[0] <= 0:
        return ac  # 全零/异常信号：不做归一化，交给上层判空
    return ac / ac[0]


def copy_figure_to_clipboard(fig):
    """把 matplotlib 图像以 DIB 位图放入系统剪贴板，可直接在微信/Word/画图等粘贴。
    仅依赖标准库 ctypes（Windows），无需 Pillow/pywin32。"""
    import ctypes
    from ctypes import wintypes
    import struct
    canvas = fig.canvas
    canvas.draw()
    w, h = canvas.get_width_height()
    rgba = np.asarray(canvas.buffer_rgba())[:, :, :4]   # 顶向下 RGBA
    bgra = rgba[:, :, [2, 1, 0, 3]][::-1, :, :]         # 转 BGRA 并翻转为底向上
    pixel = np.ascontiguousarray(bgra).tobytes()
    # BITMAPINFOHEADER：40 字节，32 位 BI_RGB
    header = struct.pack("<IiiHHIIiiII", 40, w, h, 1, 32, 0,
                         w * h * 4, 0, 0, 0, 0)
    data = header + pixel
    CF_DIB = 8
    GMEM_MOVEABLE = 0x0002
    u32, k32 = ctypes.windll.user32, ctypes.windll.kernel32
    k32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    k32.GlobalAlloc.restype = wintypes.HGLOBAL
    k32.GlobalLock.argtypes = [wintypes.HGLOBAL]; k32.GlobalLock.restype = ctypes.c_void_p
    k32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]; k32.GlobalUnlock.restype = wintypes.BOOL
    k32.GlobalFree.argtypes = [wintypes.HGLOBAL]; k32.GlobalFree.restype = wintypes.HGLOBAL
    u32.OpenClipboard.argtypes = [wintypes.HWND]; u32.OpenClipboard.restype = wintypes.BOOL
    u32.EmptyClipboard.restype = wintypes.BOOL
    u32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]; u32.SetClipboardData.restype = wintypes.HANDLE
    u32.CloseClipboard.argtypes = []; u32.CloseClipboard.restype = wintypes.BOOL
    h_mem = k32.GlobalAlloc(GMEM_MOVEABLE, len(data))
    if not h_mem:
        raise MemoryError("剪贴板内存分配失败")
    ptr = k32.GlobalLock(h_mem)
    if not ptr:
        k32.GlobalFree(h_mem); raise MemoryError("剪贴板内存锁定失败")
    ctypes.memmove(ptr, data, len(data))
    k32.GlobalUnlock(h_mem)
    if not u32.OpenClipboard(None):
        k32.GlobalFree(h_mem); raise RuntimeError("无法打开剪贴板")
    try:
        u32.EmptyClipboard()
        if not u32.SetClipboardData(CF_DIB, h_mem):
            raise RuntimeError("写入剪贴板失败")
    finally:
        u32.CloseClipboard()


def fit_window(win, pref_w, pref_h, min_w=None, min_h=None):
    # 按当前屏幕分辨率自适应窗口大小并在屏幕居中定位。
    # 高 DPI 下按屏幕缩放放大首选尺寸，保证开启 DPI 感知后窗口的物理大小不变
    sw = win.winfo_screenwidth(); sh = win.winfo_screenheight()
    k = max(1.0, ui_dpi(win) / 96.0)
    pref_w = int(round(pref_w * k)); pref_h = int(round(pref_h * k))
    if min_w and min_h:
        min_w = int(round(min_w * k)); min_h = int(round(min_h * k))
    w = int(min(pref_w, max(320, sw - 20)))
    h = int(min(pref_h, max(320, sh - 70)))
    if min_w and min_h:
        win.minsize(min(min_w, w), min(min_h, h))
    x = int(max(0, (sw - w) / 2))
    y = int(max(0, (sh - h) / 2))
    win.geometry(f"{w}x{h}+{x}+{y}")


def ui_dpi(widget, fallback=100.0):
    """屏幕 DPI（每英寸像素数）。matplotlib 默认 dpi=100，在 Windows 125%/150% 缩放下，
    Tk 控件会按系统缩放变大而图谱文字不变，看起来“图上的字变小了”。
    这里取 Tk 报告的屏幕 DPI 作为 figure.dpi，让图谱字号与界面保持一致；取不到时退回 100。"""
    try:
        f = float(widget.winfo_fpixels("1i"))
        if 60.0 <= f <= 480.0:
            return f
    except Exception:
        pass
    return float(fallback)


def format_elapsed(sec):
    """秒数 → 1:23 / 1:02:03，用于进度提示。"""
    sec = int(max(0, sec))
    h, r = divmod(sec, 3600)
    m, s = divmod(r, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def center_window(win, parent):
    """把弹窗摆到 parent 窗口正中间；parent 尚未显示/尺寸未知时退回屏幕居中。"""
    try:
        parent.update_idletasks()
        win.update_idletasks()
        pw, ph = parent.winfo_width(), parent.winfo_height()
        if parent.winfo_ismapped() and pw > 1 and ph > 1:
            px, py = parent.winfo_rootx(), parent.winfo_rooty()
        else:
            # 启动阶段主窗口还没映射：程序本身是屏幕居中的，直接按屏幕居中即可
            pw, ph = parent.winfo_screenwidth(), parent.winfo_screenheight()
            px = py = 0
        if win.winfo_ismapped():
            w, h = win.winfo_width(), win.winfo_height()
        else:
            w, h = win.winfo_reqwidth(), win.winfo_reqheight()
        sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
        x = max(0, min(px + (pw - w) // 2, sw - w))
        y = max(0, min(py + (ph - h) // 2, sh - h))
        win.geometry(f"+{x}+{y}")
    except Exception:
        pass


def center_window_later(win, parent):
    """先立即居中一次，再在主窗口真正映射后补两次，解决启动阶段取不到主窗口坐标的问题。"""
    center_window(win, parent)
    try:
        win.after(60, lambda: center_window(win, parent))
        win.after(200, lambda: center_window(win, parent))
    except Exception:
        pass


# ---------------- 窗口大小/位置记忆（写入同一个 gui_state.json，读-改-写保留其他键） ----------------
SPECTRUM_GEOM_KEY = "spectrum_geom"

def _read_state_dict():
    """读取状态 JSON 为 dict；文件缺失/损坏/类型不符时返回空 dict，绝不阻断启动。"""
    try:
        with open(STATE_FILE, encoding="utf-8") as fp:
            data = json.load(fp)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}

def save_window_geom(win, key=SPECTRUM_GEOM_KEY):
    """关闭时保存窗口当前宽高与左上角位置（物理像素），并记下当时的屏幕缩放，
    下次在不同缩放下打开时按比例换算，窗口物理大小保持一致。"""
    try:
        data = _read_state_dict()
        data[key] = {"w": int(win.winfo_width()), "h": int(win.winfo_height()),
                     "x": int(win.winfo_x()), "y": int(win.winfo_y()),
                     "scale": round(ui_dpi(win) / 96.0, 3)}
        with open(STATE_FILE, "w", encoding="utf-8") as fp:
            json.dump(data, fp, ensure_ascii=False)
    except Exception:
        pass

def restore_window_geom(win, key=SPECTRUM_GEOM_KEY, fallback=(1102, 682)):
    """打开时恢复上次窗口几何；无记录或记录在当前屏幕不可见（换电脑/改分辨率/改缩放）时回退居中默认。"""
    geom = _read_state_dict().get(key)
    sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
    if isinstance(geom, dict):
        try:
            w, h = int(geom["w"]), int(geom["h"])
            x, y = int(geom["x"]), int(geom["y"])
            # 上次保存时的屏幕缩放和现在不同（如 125% 改成 150%）：按比例换算，
            # 否则窗口在物理像素下会明显变大/变小
            try:
                # 老版本没存 scale：按 1.0（当时按逻辑像素保存）处理，缩放到 125%/150% 后
                # 仍按比例换算，窗口物理大小保持一致
                old_k = float(geom.get("scale") or 1.0)
            except (TypeError, ValueError):
                old_k = 1.0
            new_k = max(0.5, ui_dpi(win) / 96.0)
            if old_k > 0.1 and abs(new_k - old_k) > 0.02:
                r = new_k / old_k
                w = int(round(w * r)); h = int(round(h * r))
                x = int(round(x * r)); y = int(round(y * r))
            # 尺寸下限/不超主屏，且窗口四边至少各留 80px 在主屏可见范围内，防止恢复到屏外
            if (320 <= w <= sw and 320 <= h <= sh and x < sw - 80 and y < sh - 80
                    and x + w > 80 and y + h > 80):
                win.geometry(f"{w}x{h}+{x}+{y}")
                return
        except Exception:
            pass
    fit_window(win, fallback[0], fallback[1], fallback[0], fallback[1])


# ---------------- 全局界面主题：clam + 统一浅色商务风 ----------------
UI_FONT_FAMILY = "Microsoft YaHei UI"
UI_BG = "#f4f6fa"        # 窗口/容器底色（极浅灰蓝）
UI_PANEL = "#ffffff"     # 表格/输入字段白底
UI_HEADER = "#e8edf3"    # 标题栏/分区浅蓝灰
UI_TABHEAD = "#d9e2ec"   # 表头底色
UI_PRIMARY = "#2f66a3"   # 主蓝：选中/强调
UI_PRIMARY_HI = "#3d7bbf"  # 悬停主蓝
UI_BORDER = "#c7d0db"    # 统一描边灰蓝
UI_TXT = "#243447"       # 主文字深蓝灰
UI_SEL_BG = "#cfe0f5"    # 选中行淡蓝
UI_SEL_FG = "#16324f"
CHART_BG = "#e2e7ed"     # 图谱绘图区灰底（明显暗于纯白，与趋势图统一）


def apply_app_theme(root):
    """在创建任何业务控件前调用一次：切到内置 clam 主题（可完整自定义且不触发实例级 -background 报错），
    并统一字体、配色与各控件观感。"""
    st = ttk.Style(root)
    try:
        st.theme_use("clam")
    except tk.TclError:
        pass
    f_base = (UI_FONT_FAMILY, 9)
    f_bold = (UI_FONT_FAMILY, 9, "bold")
    # 界面缩放：字体是“点”单位、Tk 会按屏幕 DPI 自动放大；这里把纯像素的内边距/行高
    # 也按同一比例放大，避免 125%/150% 下控件挤在一起
    ui_k = max(1.0, ui_dpi(root) / 96.0)

    # 根默认样式：统一字体/底色，其余 ttk 控件继承（描边色在各控件上单独设置，避免根样式选项兼容问题）
    st.configure(".", font=f_base, background=UI_BG, foreground=UI_TXT)
    st.configure("TFrame", background=UI_BG)
    st.configure("TLabel", background=UI_BG, foreground=UI_TXT, font=f_base)
    st.configure("TPanedwindow", background=UI_BG)
    st.configure("TSeparator", background=UI_BORDER)

    # 按钮：扁平、柔和描边，悬停/按下变主蓝白字
    st.configure("TButton", padding=(int(round(12 * ui_k)), int(round(6 * ui_k))),
                 relief="flat", borderwidth=1,
                 background="#e9eef4", foreground=UI_TXT, bordercolor=UI_BORDER, font=f_base)
    st.map("TButton",
           background=[("active", UI_PRIMARY_HI), ("pressed", UI_PRIMARY)],
           foreground=[("active", "#ffffff"), ("pressed", "#ffffff")],
           bordercolor=[("active", UI_PRIMARY_HI), ("pressed", UI_PRIMARY)])

    # 工具栏图标按钮：符号字体、小巧紧凑；width=5 把等宽外框固定在约 49px（clam 默认约 91px 的一半），
    # 保留有框等宽观感，仅收窄按钮占位；底色与悬停/按下配色继承 TButton
    st.configure("Icon.TButton", font=("Segoe UI Symbol", 10), padding=(4, 2), width=5)
    # 画布悬浮工具条容器：无边框，底色与“画布外标题条/窗口”一致（UI_BG 浅色），视觉上不形成方框
    st.configure("ChartTool.TFrame", background=UI_BG, relief="flat", borderwidth=0)
    # 悬浮条上的无框图标按钮（常态/关闭态）：
    # width=0 解除 clam 主题约 77px 的按钮最小宽，按字形自适应；字号 12、适度内边距，
    # 常态融入标题条浅色底（边框色与底色相同，彻底无轮廓），仅悬停浮现浅蓝，不出现矩形块
    st.configure("IconFlat.TButton", font=("Segoe UI Symbol", 12), width=0, padding=(4, 3),
                 relief="flat", borderwidth=0, focusthickness=0,
                 background=UI_BG, foreground=UI_TXT,
                 bordercolor=UI_BG, lightcolor=UI_BG, darkcolor=UI_BG)
    st.map("IconFlat.TButton",
           background=[("active", UI_SEL_BG), ("disabled", UI_BG)],
           foreground=[("active", UI_SEL_FG), ("disabled", UI_TXT)],
           bordercolor=[("active", UI_SEL_BG), ("disabled", UI_BG)])
    # 悬浮图标“开启态”：与常态完全同底、同样无框，仅把符号变主蓝，避免蓝色矩形块（各谱图标格式统一）
    st.configure("IconFlatOn.TButton", font=("Segoe UI Symbol", 12), width=0, padding=(4, 3),
                 relief="flat", borderwidth=0, focusthickness=0,
                 background=UI_BG, foreground=UI_PRIMARY,
                 bordercolor=UI_BG, lightcolor=UI_BG, darkcolor=UI_BG)
    st.map("IconFlatOn.TButton",
           background=[("active", UI_SEL_BG), ("disabled", UI_BG)],
           foreground=[("active", UI_SEL_FG), ("disabled", UI_PRIMARY)],
           bordercolor=[("active", UI_SEL_BG), ("disabled", UI_BG)])
    # 3D 瀑布专用：画布是灰底，图标按钮也必须同底，否则每个图标都会像一块浅色小方块
    st.configure("IconFlatDark.TButton", font=("Segoe UI Symbol", 12), width=0, padding=(4, 3),
                 relief="flat", borderwidth=0, focusthickness=0,
                 background=CHART_BG, foreground=UI_TXT,
                 bordercolor=CHART_BG, lightcolor=CHART_BG, darkcolor=CHART_BG)
    st.map("IconFlatDark.TButton",
           background=[("active", UI_SEL_BG), ("disabled", CHART_BG)],
           foreground=[("active", UI_SEL_FG), ("disabled", UI_TXT)],
           bordercolor=[("active", UI_SEL_BG), ("disabled", CHART_BG)])
    st.configure("IconFlatOnDark.TButton", font=("Segoe UI Symbol", 12), width=0, padding=(4, 3),
                 relief="flat", borderwidth=0, focusthickness=0,
                 background=CHART_BG, foreground=UI_PRIMARY,
                 bordercolor=CHART_BG, lightcolor=CHART_BG, darkcolor=CHART_BG)
    st.map("IconFlatOnDark.TButton",
           background=[("active", UI_SEL_BG), ("disabled", CHART_BG)],
           foreground=[("active", UI_SEL_FG), ("disabled", UI_PRIMARY)],
           bordercolor=[("active", UI_SEL_BG), ("disabled", CHART_BG)])
    # 画布外标题条文本样式
    st.configure("ChartTitle.TLabel", background=UI_BG, foreground=UI_TXT)
    # 3D 瀑布专用：整个画布是灰色绘图底，标题条/工具条容器也跟着用灰底，避免上下两块颜色不一致
    st.configure("ChartTitleDark.TLabel", background=CHART_BG, foreground=UI_TXT)
    st.configure("ChartToolDark.TFrame", background=CHART_BG, relief="flat", borderwidth=0)

    # 输入框/下拉：白底灰边，聚焦时主蓝描边
    st.configure("TEntry", fieldbackground=UI_PANEL, foreground=UI_TXT, insertcolor=UI_TXT,
                 padding=int(round(3 * ui_k)), relief="solid", borderwidth=1,
                 bordercolor=UI_BORDER, lightcolor=UI_BORDER, darkcolor=UI_BORDER)
    st.map("TEntry",
           bordercolor=[("focus", UI_PRIMARY)], lightcolor=[("focus", UI_PRIMARY)],
           darkcolor=[("focus", UI_PRIMARY)])
    st.configure("TCombobox", fieldbackground=UI_PANEL, background="#e9eef4",
                 foreground=UI_TXT, arrowcolor=UI_PRIMARY, padding=int(round(3 * ui_k)),
                 relief="solid", borderwidth=1, bordercolor=UI_BORDER)
    st.map("TCombobox",
           bordercolor=[("focus", UI_PRIMARY)],
           fieldbackground=[("readonly", UI_PANEL)],
           foreground=[("readonly", UI_TXT)])

    # 表格/树：白底、舒展行高、扁平深蓝灰表头、淡蓝选中
    st.configure("Treeview", background=UI_PANEL, fieldbackground=UI_PANEL, foreground=UI_TXT,
                 rowheight=int(round(24 * ui_k)), font=f_base, relief="solid", borderwidth=1, bordercolor=UI_BORDER)
    st.map("Treeview",
           background=[("selected", UI_SEL_BG)],
           foreground=[("selected", UI_SEL_FG)])
    st.configure("Treeview.Heading", background=UI_TABHEAD, foreground="#1f2d3d",
                 font=f_bold, relief="flat", padding=(4, 6), bordercolor=UI_BORDER)
    st.map("Treeview.Heading", background=[("active", "#c7d4e3")])

    # 勾选框/单选：白底，选中填充主蓝、标记变白
    st.configure("TCheckbutton", background=UI_BG, foreground=UI_TXT, font=f_base,
                 indicatorbackground=UI_PANEL, indicatorforeground=UI_BORDER,
                 indicatordiameter=13, indicatorrelief="flat")
    st.map("TCheckbutton",
           background=[("active", UI_BG)],
           indicatorbackground=[("selected", UI_PRIMARY)],
           indicatorforeground=[("selected", "#ffffff")])
    st.configure("TRadiobutton", background=UI_BG, foreground=UI_TXT, font=f_base,
                 indicatorbackground=UI_PANEL, indicatorforeground=UI_BORDER,
                 indicatordiameter=13, indicatorrelief="flat")
    st.map("TRadiobutton",
           background=[("active", UI_BG)],
           indicatorbackground=[("selected", UI_PRIMARY)],
           indicatorforeground=[("selected", "#ffffff")])

    # 滚动条：纤细、低饱和
    for _orient in ("Vertical", "Horizontal"):
        _sn = _orient + ".TScrollbar"
        st.configure(_sn, background="#c9d3de", troughcolor=UI_BG,
                     bordercolor=UI_BG, arrowcolor="#5b6b7c", relief="flat", width=12)
        st.map(_sn, background=[("active", "#a9b8c7")])

    # 进度条：主蓝填充 + 浅灰槽。clam 默认填充色与槽几乎同色，会导致“进度条看起来一直是空的”
    st.configure("TProgressbar", background=UI_PRIMARY, troughcolor="#dbe3ec",
                 bordercolor=UI_BORDER, lightcolor=UI_PRIMARY, darkcolor=UI_PRIMARY,
                 thickness=10)

    root.configure(bg=UI_BG)
    # 所有后续 Toplevel 弹窗的原生底色统一（创建前写入 option 数据库，一次覆盖全部弹窗，边缘不露系统灰）
    root.option_add("*Toplevel.background", UI_BG)


class ToolTip:
    """轻量鼠标悬停提示：停留片刻在控件下方弹出浅色小框，移出/按下即消失。"""

    def __init__(self, delay=450):
        self.delay = delay
        self._after_id = None
        self._owner = None
        self.win = None
        self.texts = {}

    def bind(self, w, text):
        self.texts[w] = text
        w.bind("<Enter>", lambda _e, ww=w: self._schedule(ww), add="+")
        w.bind("<Leave>", lambda _e: self.hide(), add="+")
        w.bind("<ButtonPress>", lambda _e: self.hide(), add="+")
        w.bind("<Destroy>", lambda _e: self.hide(), add="+")

    def set_text(self, w, text):
        self.texts[w] = text

    def _schedule(self, w):
        self._cancel()
        self._owner = w
        self._after_id = w.after(self.delay, self._show)

    def _cancel(self):
        if self._after_id is not None and self._owner is not None:
            try:
                self._owner.after_cancel(self._after_id)
            except Exception:
                pass
        self._after_id = None

    def _show(self):
        w = self._owner
        try:
            if w is None or not w.winfo_exists():
                return
            txt = self.texts.get(w, "")
            if not txt:
                return
            self.hide()
            tw = tk.Toplevel(w)
            tw.overrideredirect(True)
            tw.attributes("-topmost", True)
            lbl = tk.Label(tw, text=txt, background="#fff7d6", foreground="#243447",
                           relief="solid", borderwidth=1, font=(UI_FONT_FAMILY, 9),
                           padx=8, pady=4, justify="left")
            lbl.pack()
            tw.update_idletasks()
            x = w.winfo_rootx() + max(0, (w.winfo_width() - tw.winfo_reqwidth()) // 2)
            y = w.winfo_rooty() + w.winfo_height() + 4
            x = max(4, min(x, w.winfo_screenwidth() - tw.winfo_reqwidth() - 4))
            y = max(4, min(y, w.winfo_screenheight() - tw.winfo_reqheight() - 4))
            tw.geometry("+%d+%d" % (x, y))
            self.win = tw
        except Exception:
            self.hide()

    def hide(self):
        self._cancel()
        if self.win is not None:
            try:
                self.win.destroy()
            except Exception:
                pass
        self.win = None


class SpectrumWindow(tk.Toplevel):
    # 多个基频的配色：每个基频及其倍频/边带/带宽共用一种颜色
    BASE_COLORS = ["#c62828", "#6a1b9a", "#00695c", "#ad1457",
                   "#4e342e", "#283593", "#827717", "#e65100"]
    BW_COLOR = "#e6a700"          # 带宽统一用黄色
    RING_COLOR = "#d62728"        # 倍频/边带/带宽频率处的空心红圈
    RING_MS = 3.0                 # 与 19.1Hz 峰值标注红圈同尺寸
    RING_MEW = 1.2

    def __init__(self, master, init_dir="", auto_load=None):
        super().__init__(master)
        self.title("图谱分析")
        # 恢复上次关闭时的窗口大小与位置；无有效记录时回退 1102x682 居中，关闭时自动保存
        restore_window_geom(self)
        self.protocol("WM_DELETE_WINDOW", self._on_spectrum_close)
        self.csv_path = None; self.sig = None; self.fs = None; self.info = None
        self.last_dir = init_dir; self.current_plot = None; self.rs = None
        self.project_dir = init_dir or ""
        self._panel_collapsed = False
        self.refine_on = False; self.refine_range = None
        self._refine_saved = {}   # 每种谱图各自的细化范围，切换后回来仍保持原缩放
        self.mark_time_on = False
        self._drag_period = False
        self.single_line_on = False
        self._single_start_t = None
        self._freq_confirmed = False
        self._manual_marks_time = []  # 手动标注的时间点
        self.manual_marks = []   # [(x_val, label), ...]
        self.annotate_mode = False
        self.active_mark_x = None  # 活动基频线当前x位置
        self.show_peaks = True  # 自动峰值标注开关
        self._undo_stack = []  # 撤销栈
        self._xmax_override = None  # 倍频后强制扩展的x轴右边界
        self._harmonics_text = None   # 倍频信息文本
        self._sidebands_text = None   # 边带信息文本
        self._bandwidth_text = None   # 带宽信息文本
        self._bandwidth_regions = []  # [(fs, fe, label), ...]
        self._base_colors = {}        # {基频: 颜色}
        self._sideband_params = {}    # {基频: 边带间隔}
        self._active_f0_color = self.BASE_COLORS[0]
        self._cur_f = None; self._cur_amp = None  # 当前谱图数据，用于方向键找峰
        # 标注整体显示/隐藏（隐藏不删除状态，可恢复）
        self.marks_hidden = False
        # 视图锁定：冻结当前 X/Y 轴范围并关闭鼠标点击/拖拽改标记的交互，
        # 用于自相关等场景下“找准周期后不让误点击把它改掉”
        self.axis_locked = False
        self._locked_xlim = None
        self._locked_ylim = None
        # 所有谱图默认锁定：每张谱图首次绘出后自动锁定其 X/Y 轴（显式看图动作会临时解锁并重新锁定）
        self._auto_lock_pending = True
        self._refine_relock = False
        self._annotate_relock = False
        self._single_relock = False
        # 自相关：全量计算结果缓存（细化/移动标记只重绘不重算）+ 结果序号（丢弃过期异步结果）
        self._ac_cache = None
        self._ac_cache_key = None
        self._autocorr_seq = 0
        # 瀑布图（STFT 逐帧频谱堆叠）：缓存放 spectrogram 结果，缩放/标注/锁定时只重绘不重算
        self._wf_cache = None
        self._wf_cache_key = None
        self._spectrum_cache = {}   # (谱型+文件+参数) -> (f, amp)，切谱图直接复用
        self._wf_3d = False          # 瀑布图是否使用 3D 视图（右键菜单切换）
        self._wf_db = True           # 瀑布幅值用 dB 显示（右键菜单可切回线性）
        self._rot_hz = None          # 手动设置的转频(1X, Hz)；None 表示按文件名转速
        self._bearing_marks = []     # 轴承特征频率标注：[{hz,label,color}]
        self._bearing_sel = None     # 上次选的轴承名
        self._gear_marks = []        # 齿轮啮合/边带标注：[{hz,label,color,lw}]
        self._gear_stage = 2         # 上次选的齿轮级（默认三级=中速轴）
        self._auto_bearing_on = True   # 按项目+测点自动标注轴承特征频率（府谷库）
        self._auto_bearing_used = False
        self._fft_ref_cache = None   # 全记录幅值谱缓存：把瀑布等低分辨率谱图上的峰细化到 fs/N
        self._fft_ref_key = None
        # 基频是否来自“自相关点选”，用于切到时域时自动补一个起点进行周期标注
        self._period_from_autocorr = False
        # 自相关选好周期后，首次切到时域是否把视图收到“约 10 个周期”（只做一次，之后随用户缩放）
        self._autocorr_zoom_pending = False
        self.plot_lock = threading.Lock()

        self.tip = ToolTip()
        bar1 = ttk.Frame(self); bar1.pack(fill="x", padx=5, pady=(4, 0))
        self._icon(bar1, "\u25a4", "选择 CSV 数据文件", self.pick_csv)
        self.lbl = ttk.Label(bar1, text="未选择文件"); self.lbl.pack(side="left", padx=8)

        # 第二行：图谱切换
        bar2 = ttk.Frame(self); bar2.pack(fill="x", padx=5, pady=(2, 1))
        self._icon(bar2, "\u223f", "时域波形", lambda: self._safe("time", self.plot_time))
        self._icon(bar2, "\u2261", "瀑布图（各时间段频谱自下而上堆叠）",
                   lambda: self._safe("stft", self.plot_waterfall))
        self._icon(bar2, "\u224b", "自相关", lambda: self._safe("autocorr", self.plot_autocorr))
        ttk.Separator(bar2, orient="vertical").pack(side="left", fill="y", padx=6)
        self._icon(bar2, "\u0192", "FFT 幅值谱", lambda: self._safe("fft", self.plot_fft))
        self._icon(bar2, "\u25e1", "包络谱", lambda: self._safe("envelope", self.plot_envelope))
        self._icon(bar2, "\u03bd", "速度谱", lambda: self._safe("velocity", self.plot_velocity))
        self.btn_order = self._icon(bar2, "#", "阶次谱", lambda: self._safe("order", self.plot_order))
        self._icon(bar2, "\u21c4", "倒频谱", lambda: self._safe("cepstrum", self.plot_cepstrum))

        # 基频频率变量（Hz）：时域“频率”按钮用它设定基频，标记按 1/f 的周期重复
        self.var_single_freq = tk.StringVar(value="28.9")

        # 带通参数变量（UI 已迁入对应图谱右键菜单，此处仅保留状态变量）
        self.var_bp = tk.BooleanVar(value=False)
        self.var_bp_low = tk.StringVar(value="0")
        self.var_bp_high = tk.StringVar(value="2000")
        self.var_env_low = tk.StringVar(value="0")
        self.var_env_high = tk.StringVar(value="5000")
        # 窗函数开关：FFT/包络谱汉宁窗（默认开，降泄漏并做幅值校正）；瀑布图分段汉宁窗（默认开，50% 重叠）
        self.var_hann = tk.BooleanVar(value=True)
        self.var_stft_win = tk.BooleanVar(value=True)

        # 图谱标题独立条带（画布外），不与悬浮图标争用同一区域，窗口缩小时也不会互相遮挡
        self.chart_title = ttk.Label(self, style="ChartTitle.TLabel", justify="center",
                                     anchor="center", font=(UI_FONT_FAMILY, 10))
        self.chart_title.pack(fill="x", padx=8, pady=(6, 0))
        # 画布承载容器：左/右两个角的悬浮工具条 place 在它之上
        self.plot_holder = ttk.Frame(self)
        self.plot_holder.pack(fill="both", expand=True, padx=5, pady=(2, 5))
        # figure 外围（顶部图标留白带）用与标题条一致的浅色 UI_BG，深灰仅用于 axes 绘图面。
        # dpi 基准用 96：matplotlib 的 Tk 后端会按 tk scaling 再乘设备像素比（125% 时 ×1.25），
        # 最终 figure.dpi 正好等于屏幕 DPI，图上的字号与界面一致（不要在这里再乘一次缩放）
        self.fig = plt.figure(figsize=(11, 5.5), dpi=96, facecolor=UI_BG)
        self.ax = self.fig.add_subplot(111)
        self.canvas = FigureCanvasTkAgg(self.fig, master=self.plot_holder)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)
        self.canvas.get_tk_widget().configure(background=UI_BG)
        self.canvas.mpl_connect("button_press_event", self._on_click_annotate)
        self.canvas.mpl_connect("pick_event", self._on_pick_panel)
        self.canvas.mpl_connect("button_press_event", self._onclick_mark_time)
        self.canvas.mpl_connect("button_press_event", self._onclick_single_line)
        self.canvas.mpl_connect("button_press_event", self._on_press_period)
        self.canvas.mpl_connect("motion_notify_event", self._on_motion_period)
        self.canvas.mpl_connect("button_release_event", self._on_release_period)
        self.canvas.mpl_connect("button_press_event", self._on_canvas_context)
        self.canvas.mpl_connect("key_press_event", self._on_key_press)
        self.canvas.mpl_connect("scroll_event", self._on_spectrum_scroll)
        # 画布尺寸自适应：拖动边框/最大化/改系统缩放后，按新尺寸重算抽稀点数、四边留白与悬浮按钮位置
        self._canvas_size = (0, 0)
        self._resize_job = None
        self.canvas.get_tk_widget().bind("<Configure>", self._on_canvas_configure, add="+")

        # 右上角悬浮工具条：锁定视图 / 框选细化 / 缩小 / 撤销 / 还原（无框紧凑图标，贴画布最上边框）
        self.flow_right = ttk.Frame(self.plot_holder, style="ChartTool.TFrame")
        self.flow_right.place(relx=1.0, rely=0.0, anchor="ne")
        # 锁定视图：自相关等谱图找准周期后按一下，X/Y 轴与基频标记即被冻结，
        # 之后在图上误点、误拖、误滚都不再改变标记；再按一次解锁
        self.btn_lock = self._icon(self.flow_right, "\U0001F513",
                                   "锁定视图（冻结 X/Y 轴，鼠标点击不改标记；方向键仍可微调）",
                                   self._toggle_lock, toggle=True,
                                   btn_style="IconFlat.TButton", padx=4)
        ttk.Separator(self.flow_right, orient="vertical").pack(side="left", fill="y", padx=5)
        self.btn_refine = self._icon(self.flow_right, "\u229e", "框选细化（拖拽框选局部放大）",
                                     self._toggle_refine, toggle=True,
                                     btn_style="IconFlat.TButton", padx=4)
        self._icon(self.flow_right, "\u229f", "缩小", self._zoom_out,
                   btn_style="IconFlat.TButton", padx=4)
        self._icon(self.flow_right, "\u21b6", "撤销上一步", self._undo,
                   btn_style="IconFlat.TButton", padx=4)
        self._icon(self.flow_right, "\u27f2", "还原原图", self._reset_view,
                   btn_style="IconFlat.TButton", padx=4)

        # 左上角悬浮工具条：基频/频率(时域) + 基频/倍频/边带/带宽/峰值（按谱类型显隐）
        self.flow_left = ttk.Frame(self.plot_holder, style="ChartTool.TFrame")
        # 时域专用：基频标注（与谱图“基频”同一图标）、频率（仅时域显示，排在最前）
        self.btn_single = self._fund_button(self.flow_left, self._toggle_single_line,
                                            tip="基频标注（在时域图上选起点）", toggle=True)
        self.btn_freq = self._icon(self.flow_left, "Hz", "频率（设置基频频率，单位 Hz）",
                                   self._popup_freq, btn_style="IconFlat.TButton", padx=4)
        self.btn_annotate = self._fund_button(self.flow_left, self._toggle_annotate, tip="基频")
        self.btn_harm = self._icon(self.flow_left, "\u00d7n", "倍频标注", self._draw_harmonics,
                                   btn_style="IconFlat.TButton", padx=4)
        self.btn_side = self._icon(self.flow_left, "\u2225", "边带标注", self._draw_sidebands,
                                   btn_style="IconFlat.TButton", padx=4)
        self.btn_bw = self._icon(self.flow_left, "\u2194", "带宽标注", self._draw_bandwidth,
                                 btn_style="IconFlat.TButton", padx=4)
        self.btn_peak = self._icon(self.flow_left, "\u25b2", "峰值自动标注", self._toggle_peak,
                                   toggle=True, btn_style="IconFlat.TButton", padx=4)
        # 悬浮按钮初始开关视觉态：峰值标注默认开启，其余默认关闭
        self._set_on(self.btn_refine, False)
        self._set_on(self.btn_annotate, False)
        self._set_on(self.btn_peak, self.show_peaks)

        if auto_load:
            self._pending_auto_load = auto_load
            self._show_loading()
            self.after(120, self._do_auto_load)
        else:
            self._pending_auto_load = None
        # 初始无数据：阶次谱按钮先置灰，载入含转速的文件后由 load_file 自动恢复
        self._refresh_plot_availability()

    def _do_auto_load(self):
        path = getattr(self, "_pending_auto_load", None)
        if not path: return
        try:
            self.load_file(path)
            if self.sig is None:
                messagebox.showerror("错误", f"文件加载失败:\n{path}"); return
            self._safe("time", self.plot_time)
        except Exception as e:
            import traceback
            messagebox.showerror("跳转加载异常", traceback.format_exc()[:800])

    def _show_loading(self):
        ax = self.fig.gca()
        ax.clear()
        ax.text(0.5, 0.5, "加载中...", transform=ax.transAxes,
                ha="center", va="center", fontsize=16)
        self.canvas.draw()

    def _destroy_selector(self):
        if self.rs is not None:
            try: self.rs.set_active(False)
            except: pass
            try: self.rs.clear()
            except: pass
            self.rs = None

    def _push_undo(self):
        self._undo_stack.append({
            "refine_range": self.refine_range,
            "manual_marks": list(self.manual_marks),
            "active_mark_x": self.active_mark_x,
            "_xmax_override": self._xmax_override,
            "_harmonics_text": self._harmonics_text,
            "_sidebands_text": self._sidebands_text,
            "_bandwidth_text": self._bandwidth_text,
            "_bandwidth_regions": list(self._bandwidth_regions),
            "_single_start_t": self._single_start_t,
            "_freq_confirmed": self._freq_confirmed,
            "_base_colors": dict(getattr(self, "_base_colors", {})),
            "_sideband_params": dict(getattr(self, "_sideband_params", {})),
            "_manual_marks_time": list(getattr(self, "_manual_marks_time", [])),
        })
        if len(self._undo_stack) > 20: self._undo_stack.pop(0)

    def _undo(self):
        if not self._undo_stack: return
        was_locked = self.axis_locked
        if was_locked: self._set_locked(False)
        s = self._undo_stack.pop()
        self.refine_range = s["refine_range"]
        self.manual_marks = s["manual_marks"]
        self.active_mark_x = s["active_mark_x"]
        self._xmax_override = s["_xmax_override"]
        self._harmonics_text = s["_harmonics_text"]
        self._sidebands_text = s["_sidebands_text"]
        self._bandwidth_text = s["_bandwidth_text"]
        self._bandwidth_regions = s["_bandwidth_regions"]
        self._single_start_t = s.get("_single_start_t")
        self._freq_confirmed = s.get("_freq_confirmed", False)
        self._base_colors = dict(s.get("_base_colors", {}))
        self._sideband_params = dict(s.get("_sideband_params", {}))
        self._manual_marks_time = list(s.get("_manual_marks_time", []))
        self._redraw_current_plot()
        if was_locked: self._set_locked(True)

    def _zoom_out(self):
        if self._wf3d_active():
            return
        # 已经细化/缩放过：再点“缩小”= 取消细化状态，回到全图
        if self.refine_range is not None:
            self.refine_range = None
            self._refine_saved.pop(self.current_plot, None)
            self._xmax_override = None
            was_locked = self.axis_locked
            if was_locked:
                self._set_locked(False)
            self._redraw_current_plot()
            if was_locked:
                self._set_locked(True)
            return
        # 缩小是明确的看图动作：锁定态下临时解锁执行，完成后按新范围重新锁定
        was_locked = self.axis_locked
        if was_locked:
            self._set_locked(False)
        ax = self.fig.gca()
        x0, x1 = ax.get_xlim()
        f_max = self._cur_f[-1] if self._cur_f is not None and len(self._cur_f) > 0 else self.fs/2.56
        # 已经是全图范围，不能再缩小
        if x0 <= 0.001 and x1 >= f_max * 0.999:
            if was_locked:
                self._set_locked(True)
            return
        center = (x0 + x1) / 2
        half = (x1 - x0) / 2 * 1.5
        new_x0 = max(0, center - half)
        new_x1 = min(center + half, f_max)
        # 走“显式视图范围”而不是直接 set_xlim：这样会按新范围重画（抽稀密度跟着视图变），
        # 否则曲线还是按旧视图抽稀的，放大/缩小后看着发虚或断头
        self._set_view_range(new_x0, new_x1)
        self._refine_saved[self.current_plot] = self.refine_range
        self._redraw_current_plot()
        if was_locked:
            self._set_locked(True)

    def _set_view_range(self, a, b):
        # 把视图精确设为 [a,b]：_post_draw 会以细化区间的 5% 再向外加边距，
        # 这里按 1.1 倍关系反算内缩区间，保证滚轮缩放后显示的就是 [a,b]
        if not (np.isfinite(a) and np.isfinite(b)) or b <= a:
            return
        d = (b - a) / 1.1
        r0 = a + 0.05 * d
        self._xmax_override = None   # 手动缩放优先于倍频/边带的自动扩边
        self.refine_range = (r0, r0 + d)

    def _on_spectrum_scroll(self, event):
        """Shift + 滚轮：以指针位置为锚点细化/放大图谱（等价于框选细化的快捷方式）。
        向上滚放大、向下滚缩小；锁定态下临时解锁执行，完成后按新范围重新锁定。"""
        if not shift_pressed(event):
            return
        if self._wf3d_active():   # 3D 视图交给 mplot3d 自己处理鼠标
            return
        if event.inaxes is None or event.xdata is None:
            return
        if self.current_plot not in ("fft", "envelope", "velocity", "order",
                                     "cepstrum", "autocorr", "stft", "time"):
            return
        if getattr(event, "button", None) not in ("up", "down"):
            return
        x0, x1 = self.fig.gca().get_xlim()
        if not (np.isfinite(x0) and np.isfinite(x1)) or x1 <= x0:
            return
        anchor = float(event.xdata)
        factor = 0.8 if event.button == "up" else 1.25
        a = anchor - (anchor - x0) * factor
        b = anchor + (x1 - anchor) * factor
        # 限定在数据范围内，最多缩回原图
        if self.current_plot == "time" and self.sig is not None:
            dlo, dhi = 0.0, (len(self.sig) - 1) / float(self.fs)
        else:
            f = self._cur_f
            dlo, dhi = (float(f[0]), float(f[-1])) if f is not None and len(f) > 1 else (None, None)
        if dlo is not None:
            pad = (dhi - dlo) * 0.02
            a = max(dlo - pad, a)
            b = min(dhi, b)
        if b - a <= 0:
            return
        was_locked = self.axis_locked
        if was_locked:
            self._set_locked(False)
        self._xmax_override = None   # 滚轮缩放优先，倍频/边带不再抢 X 轴范围
        self._set_view_range(a, b)
        self._redraw_current_plot()
        if was_locked:
            self._set_locked(True)

    def _reset_view(self):
        self._push_undo()
        was_locked = self.axis_locked
        if was_locked:
            self._set_locked(False)
        self.refine_range = None
        self._refine_saved.pop(self.current_plot, None)
        self.manual_marks = []
        self.active_mark_x = None
        self._xmax_override = None
        self._harmonics_text = None
        self._sidebands_text = None
        self._bandwidth_text = None
        self._bandwidth_regions = []
        self._single_start_t = None
        self._freq_confirmed = False
        if self.rs is not None:
            try: self.rs.clear()
            except: pass
        self._redraw_current_plot()
        if was_locked: self._set_locked(True)

    def _toggle_annotate(self):
        # 自相关：不再用鼠标点频率。按“基频”直接把标记放到转频周期（无转速则放视窗中心），
        # 之后 ←/→ 走最小分辨率、Shift+←/→ 粗调并自动吸附峰。
        if self.current_plot == "autocorr":
            self._place_autocorr_base()
            return
        self._annotate_relock = self.axis_locked
        if self.axis_locked:
            self._set_locked(False)
        self.annotate_mode = not self.annotate_mode
        self._set_on(self.btn_annotate, self.annotate_mode)
        if self.annotate_mode:
            # 开基频定位时自动关框选细化，避免抢鼠标事件
            self.refine_on = False
            self._set_on(self.btn_refine, False)
            self._destroy_selector()
        else:
            # 关基频定位时保留基频线，只是不再响应鼠标点击
            if getattr(self, "_annotate_relock", False):
                self._auto_lock_pending = True
            self._redraw_current_plot()

    def _reset_overlay_marks(self):
        # 清除基频/倍频/边带/带宽等叠加标注线与信息框。切换谱图或切换标注功能时调用，
        # 避免上一张图（或上一种标注）的线、填充区、文字残留到另一张谱图上。
        self.manual_marks = []
        self.active_mark_x = None
        self._xmax_override = None
        self._harmonics_text = None
        self._sidebands_text = None
        self._bandwidth_text = None
        self._bandwidth_regions = []
        self._base_colors = {}
        self._sideband_params = {}
        self.annotate_mode = False
        self._side_bw = None

    def _clear_marks(self):
        # 清除标注：只关自动峰值标注，保留手动基频/倍频线
        self.show_peaks = False
        self._set_on(self.btn_peak, False)
        self._redraw_current_plot()

    def _toggle_marks_visible(self):
        # 标注整体显示/隐藏：仅切换可见性，不删除任何标注状态，可再次点击恢复
        self.marks_hidden = not self.marks_hidden
        self._redraw_current_plot()

    def _clear_all_marks(self):
        # 一键清空全部标注：先入撤销栈，误删可连续撤销
        self._push_undo()
        self.show_peaks = False
        self._set_on(self.btn_peak, False)
        self._reset_overlay_marks()
        self._set_on(self.btn_annotate, False)
        self.single_line_on = False
        self._set_on(self.btn_single, False)
        self._single_start_t = None
        self._freq_confirmed = False
        self._manual_marks_time = []
        self.marks_hidden = False
        self._redraw_current_plot()

    def _toggle_peak(self):
        self.show_peaks = not self.show_peaks
        self._set_on(self.btn_peak, self.show_peaks)
        self._redraw_current_plot()

    def _color_for_base(self, f0):
        """每个基频固定一种颜色，它的倍频/边带/带宽都用这一色。"""
        key = round(float(f0), 2)
        if key not in self._base_colors:
            self._base_colors[key] = self.BASE_COLORS[
                len(self._base_colors) % len(self.BASE_COLORS)]
        return self._base_colors[key]

    def _snap_hz_to_peak(self, f_target, tol_hz):
        """把“算出来的频率”（k×f0、f0±n·BW）吸附到附近幅值最高的那条谱线。

        谱图频率只显示到 0.1Hz，而倍频/边带的理论位置与实际谱峰常差几分之一 Hz
        （基频本身取整、边带间隔取整都会累积），不吸附的话竖线会落在峰旁边，
        标注取的幅值也不是真实峰值。tol_hz 是允许的吸附范围（Hz）。
        """
        try:
            f = self._cur_f
            a = self._cur_amp
            if f is None or a is None or len(f) == 0 or len(f) != len(a):
                return float(f_target)
            f_target = float(f_target)
            tol = float(tol_hz)
            if not np.isfinite(tol) or tol <= 0:
                idx = int(np.argmin(np.abs(f - f_target)))
                return float(f[idx])
            idx = np.where((f >= f_target - tol) & (f <= f_target + tol))[0]
            if idx.size == 0:
                return f_target
            k = int(idx[int(np.argmax(a[idx]))])
            return float(f[k])
        except Exception:
            return float(f_target)

    def _spec_bin_hz(self):
        """当前谱图的频率分辨率（谱线间隔）。"""
        try:
            if self._cur_f is not None and len(self._cur_f) > 2:
                return float(np.median(np.diff(self._cur_f)))
        except Exception:
            pass
        return 0.0

    def _peak_in_range(self, f_lo, f_hi):
        """区间 [f_lo, f_hi] 内幅值最高的谱线，返回 (峰频率, 峰幅值)。

        带宽标注的每一组都按带内真实峰值画标记（右边界一般不是峰）。
        区间内没有谱线（如极窄带）时退回中点，幅值给 0.01 保证可见。
        """
        try:
            f = self._cur_f
            a = self._cur_amp
            if f is not None and a is not None and len(f) == len(a) and len(f):
                lo = min(float(f_lo), float(f_hi))
                hi = max(float(f_lo), float(f_hi))
                m = (f >= lo) & (f <= hi)
                if m.any():
                    idx = np.where(m)[0]
                    k = int(idx[int(np.argmax(a[idx]))])
                    return float(f[k]), max(float(a[k]), 0.01)
        except Exception:
            pass
        return 0.5 * (float(f_lo) + float(f_hi)), 0.01

    def _draw_harmonics(self):
        if self.active_mark_x is None:
            messagebox.showwarning("提示", "请先用基频定位标出基频")
            return
        if self._cur_f is None or len(self._cur_f) == 0: return
        f0 = float(self.active_mark_x)
        color = self._color_for_base(f0)
        self._active_f0_color = color
        self._push_undo()
        self._xmax_override = None  # 倍频标注不再改 X 轴范围
        # 只替换“这个基频”的倍频标记，其它基频的倍频保留
        self.manual_marks = [
            mk for mk in self.manual_marks
            if not (str(mk[1]).endswith("X") and len(mk) > 4
                    and abs(float(mk[4]) - f0) < 1e-6)]
        f_last = float(self._cur_f[-1])
        bin_hz = self._spec_bin_hz()
        for k in range(2, 11):   # 1X 由基频标记表示，倍频只标 2X 起
            fx = f0 * k
            if fx > f_last: break
            # 允许吸附范围：≥2.5 条谱线，或该倍频的 0.2%（基频取整误差会随倍频放大）
            f_at = self._snap_hz_to_peak(fx, max(2.5 * bin_hz, 0.002 * fx))
            idx = int(np.argmin(np.abs(self._cur_f - f_at)))
            yi = max(float(self._cur_amp[idx]), 0.01)
            self.manual_marks.append((f_at, f"{k}X", color, yi, f0))
        self._harmonics_text = None
        self._redraw_current_plot()

    def _draw_sidebands(self):
        if self.active_mark_x is None:
            messagebox.showwarning("提示", "请先用基频定位标出基频")
            return
        bw = simpledialog.askfloat("边带带宽", "请输入边带间隔频率(Hz):", parent=self)
        if bw is None or bw <= 0: return
        if self._cur_f is None or len(self._cur_f) == 0: return
        f0 = float(self.active_mark_x)
        color = self._color_for_base(f0)
        self._active_f0_color = color
        self._push_undo()
        # 只替换这个基频上一次的边带
        self.manual_marks = [
            mk for mk in self.manual_marks
            if not ("sb" in str(mk[1]) and len(mk) > 4
                    and abs(float(mk[4]) - f0) < 1e-6)]
        self._sideband_params[round(f0, 2)] = bw
        f_last = float(self._cur_f[-1])
        bin_hz = self._spec_bin_hz()
        for n in range(1, 4):
            for sign in (-1, 1):
                fx = f0 + sign * n * bw
                if fx <= 0 or fx > f_last: continue
                # 吸附范围不超过 35% 边带间隔，避免跳到相邻那条边带上
                tol = max(2.0 * bin_hz, min(0.35 * bw, 0.002 * fx))
                f_at = self._snap_hz_to_peak(fx, tol)
                idx = int(np.argmin(np.abs(self._cur_f - f_at)))
                amp = max(float(self._cur_amp[idx]), 0.01)
                self.manual_marks.append((f_at, f"{sign*n:+d}sb", color, amp, f0))
        self._sidebands_text = None
        self._redraw_current_plot()

    def _draw_bandwidth(self):
        if self.active_mark_x is None:
            messagebox.showwarning("提示", "请先用基频定位标出基频")
            return
        bw = simpledialog.askfloat("带宽", "请输入每组带宽宽度(Hz):", parent=self)
        if bw is None or bw <= 0: return
        if self._cur_f is None or len(self._cur_f) == 0: return
        f0 = float(self.active_mark_x)
        color = self.BW_COLOR
        self._active_f0_color = self._color_for_base(f0)
        self._push_undo()
        # 每个基频各自保留一组带宽，按基频替换
        self._bandwidth_regions = [
            r for r in self._bandwidth_regions
            if not (isinstance(r, dict) and abs(float(r.get("base", -1)) - f0) < 1e-6)]
        f_last = float(self._cur_f[-1])
        for k in range(1, 6):
            f_lo = f0 + (k - 1) * bw
            fe = f0 + k * bw
            if fe > f_last: break
            # 带内找峰：标记画在带内真实峰值处（不再固定画在右边界，右边界一般不是峰）
            f_pk, yp = self._peak_in_range(f_lo, fe)
            self._bandwidth_regions.append(
                {"base": f0, "lo": f_lo, "hi": fe, "label": f"BW{k}",
                 "peak": f_pk, "amp": yp, "color": color})
        self._bandwidth_text = None
        self._redraw_current_plot()

    def _recompute_overlay_xmax(self):
        # 不再自动把 X 轴右限拉到倍频/边带/带宽的最大频率：
        # 始终保留完整频段，用户自己框选/Shift+滚轮决定看哪一段。
        self._xmax_override = None

    def _base_list(self):
        """当前图上的所有基频（活动基频 + 历史基频标记 + 带宽所属基频），去重升序。"""
        vals = []
        try:
            if self.active_mark_x is not None:
                vals.append(float(self.active_mark_x))
            for mk in self.manual_marks:
                if str(mk[1]) == "f0":
                    vals.append(float(mk[0]))
                elif len(mk) > 4:
                    vals.append(float(mk[4]))
            for r in self._bandwidth_regions:
                if isinstance(r, dict) and "base" in r:
                    vals.append(float(r["base"]))
        except Exception:
            pass
        out = []
        for f in sorted(vals):
            if not out or abs(f - out[-1]) > 1e-6:
                out.append(f)
        return out

    def _base_has_annotations(self, f0):
        """该基频是否标过倍频/边带/带宽（历史基频标记本身不算）。"""
        try:
            f0 = float(f0)
        except Exception:
            return False
        for mk in self.manual_marks:
            if len(mk) > 4:
                try:
                    if abs(float(mk[4]) - f0) < 1e-6:
                        return True
                except Exception:
                    pass
        for r in self._bandwidth_regions:
            if isinstance(r, dict) and "base" in r:
                try:
                    if abs(float(r["base"]) - f0) < 1e-6:
                        return True
                except Exception:
                    pass
        return False

    def _add_base_at(self, x, xpx=None):
        """右键添加基频：把 x 处设为新的活动基频，原来的活动基频自动转为历史基频标记（虚线+圆圈）。

        与原来“基频定位 + 左键点击”是同一套数据结构，所以倍频/边带/带宽都能按各自的基频分别标注。
        """
        if x is None or self._cur_f is None or len(self._cur_f) == 0:
            return
        f_new = self._snap_to_peak(float(x), xpx)
        if self.active_mark_x is not None and abs(float(self.active_mark_x) - f_new) < 1e-6:
            self._redraw_current_plot()   # 已经就是这个基频，不重复添加
            return
        self._push_undo()
        f0_colors = ["red", "blue", "green", "purple", "orange", "magenta", "brown", "teal"]
        if self.active_mark_x is not None:
            old = float(self.active_mark_x)
            # 新基频取代旧基频：旧基频没标过倍频/边带/带宽就直接消失；
            # 标过的保留成历史基频标记（否则那些标注会失去归属）
            if self._base_has_annotations(old):
                i0 = int(np.argmin(np.abs(self._cur_f - old)))
                amp_val = max(float(self._cur_amp[i0]), 0.01)
                f0_count = sum(1 for m in self.manual_marks if str(m[1]) == "f0")
                c = getattr(self, "_active_f0_color", None) or f0_colors[f0_count % len(f0_colors)]
                dup = any(str(mk[1]) == "f0" and abs(float(mk[0]) - old) < 1e-6
                          for mk in self.manual_marks)
                if not dup:
                    self.manual_marks.append((old, "f0", c, amp_val))
        self.active_mark_x = f_new
        self._active_f0_color = self._color_for_base(f_new)
        if self.current_plot == "autocorr":
            self._sync_freq_from_tau(f_new)
        self._harmonics_text = None
        self._sidebands_text = None
        self._bandwidth_text = None
        self._redraw_current_plot()

    def _remove_base(self, f0):
        """右键删除基频：连同它的倍频/边带/带宽一起删掉；删的是活动基频时，把最近的历史基频提为活动。"""
        try:
            f0 = float(f0)
        except Exception:
            return
        self._push_undo()
        self.manual_marks = [
            mk for mk in self.manual_marks
            if not ((len(mk) > 4 and abs(float(mk[4]) - f0) < 1e-6)
                    or (str(mk[1]) == "f0" and abs(float(mk[0]) - f0) < 1e-6))]
        self._bandwidth_regions = [
            r for r in self._bandwidth_regions
            if not (isinstance(r, dict) and abs(float(r.get("base", -1)) - f0) < 1e-6)]
        self._sideband_params.pop(round(f0, 2), None)
        self._base_colors.pop(round(f0, 2), None)
        if self.active_mark_x is not None and abs(float(self.active_mark_x) - f0) < 1e-6:
            hist = [float(mk[0]) for mk in self.manual_marks if str(mk[1]) == "f0"]
            if hist:
                new_f = min(hist, key=lambda v: abs(v - f0))
                self.manual_marks = [
                    mk for mk in self.manual_marks
                    if not (str(mk[1]) == "f0" and abs(float(mk[0]) - new_f) < 1e-6)]
                self.active_mark_x = new_f
                self._active_f0_color = self._color_for_base(new_f)
            else:
                self.active_mark_x = None
                self._active_f0_color = None
        self._harmonics_text = None
        self._sidebands_text = None
        self._bandwidth_text = None
        self._redraw_current_plot()

    def _on_click_annotate(self, event):
        # 锁定视图后，图上点击一律不再改基频标记（自相关找周期时最易误触）
        if self.axis_locked: return
        if not self.annotate_mode or event.inaxes is None: return
        if event.button != 1: return
        x_val = event.xdata
        if x_val is None: return
        # 默认标在附近的峰上：吸附到点击位置附近（14 像素内）最近的谱峰
        x_val = self._snap_to_peak(x_val, getattr(event, "x", None))
        self._push_undo()  # 标基频前存状态
        # 之前的基频转成普通标记保留，存频率和幅值和颜色
        f0_colors = ["red", "blue", "green", "purple", "orange", "magenta", "brown", "teal"]
        f0_count = sum(1 for m in self.manual_marks if m[1] == "f0")
        if self.active_mark_x is not None:
            old = float(self.active_mark_x)
            # 新基频取代旧基频：没标过倍频/边带/带宽的旧基频不再保留成历史标记
            if self._base_has_annotations(old):
                amp_val = 0.01
                if self._cur_f is not None and len(self._cur_f) > 0:
                    i0 = np.argmin(np.abs(self._cur_f - old))
                    amp_val = max(float(self._cur_amp[i0]), 0.01)
                c = getattr(self, "_active_f0_color", f0_colors[(f0_count - 1) % len(f0_colors)])
                self.manual_marks.append((old, "f0", c, amp_val))
        self.active_mark_x = x_val
        self._active_f0_color = self._color_for_base(x_val)
        if self.current_plot == "autocorr":
            # 自相关横轴是 τ：选中后同步 f=1/τ，切到时域即按该周期标注
            self._sync_freq_from_tau(x_val)
        self.annotate_mode = False
        self._set_on(self.btn_annotate, False)
        # 从锁定态进入的取点：选完回到锁定态（方向键仍可继续微调频率）
        if getattr(self, "_annotate_relock", False):
            self._auto_lock_pending = True
        self._redraw_current_plot()

    def _view_span(self):
        # 当前视窗的 x 轴跨度：粗调步长（Shift+方向/滚轮）在非 Hz 横轴上按它取比例
        try:
            x0, x1 = self.fig.gca().get_xlim()
            s = abs(float(x1) - float(x0))
            if s > 0 and np.isfinite(s):
                return s
        except Exception:
            pass
        return float(self.fs) / 2.56 if self.fs else 1.0

    def _bin_step(self):
        # 最小分辨率：一条谱线的间距（FFT/包络/阶次/倒频谱/自相关都适用）
        f = self._cur_f
        if f is not None and len(f) > 2:
            try:
                d = float(np.median(np.diff(f[:2000])))
                if d > 0 and np.isfinite(d):
                    return d
            except Exception:
                pass
        return max(self._view_span() / 1000.0, 1e-12)

    def _coarse_step(self):
        # Shift+方向键的粗调：0.5Hz（用户口径）。自相关/倒频谱横轴是秒、跨度只有零点几，
        # 0.5 会一步跨出整张图，因此这种情况下收到视窗的 10%
        span = self._view_span()
        return min(0.5, max(span * 0.1, self._bin_step()))

    def _nearest_bin(self, x, sign):
        # 最小分辨率移动：到相邻的一条谱线（不吸附峰，保证每次只走一格）
        f = self._cur_f
        if f is None or len(f) == 0:
            return None
        idx = (int(np.searchsorted(f, x, side="right")) if sign > 0
               else int(np.searchsorted(f, x, side="left")) - 1)
        return float(f[idx]) if 0 <= idx < len(f) else None

    def _snap_to_peak(self, x, xpx=None, max_px=14):
        # 把点击位置吸附到附近（默认 14 像素内）的谱峰：取离点击点最近的局部峰，找不到就保持原值
        f = self._cur_f; a = self._cur_amp
        if x is None or f is None or a is None or len(f) < 3 or len(a) != len(f):
            return x
        try:
            ax = self.fig.gca()
            cx = float(xpx) if xpx is not None else float(ax.transData.transform((x, 0.0))[0])
            pk, _ = find_peaks(a, height=float(np.max(a)) * 0.05)
            if len(pk) == 0:
                return x
            px = np.array([float(ax.transData.transform((float(f[i]), 0.0))[0]) for i in pk])
        except Exception:
            return x
        close = np.abs(px - cx) <= max_px
        if not np.any(close):
            return x
        idxs = pk[close]
        # 窗口内取幅值最高的峰：比“离点击点最近”更符合“标在峰上”的预期，
        # 避免点到强峰肩膀时标在旁边一个低峰上
        return float(f[int(idxs[np.argmax(a[idxs])])])

    def _on_key_press(self, event):
        if self._wf3d_active():
            return
        # 统一解析修饰键与实际按键（matplotlib 形如 "shift+right"）
        raw = (getattr(event, "key", "") or "").lower()
        parts = raw.split("+")
        base_key = parts[-1]
        mods = set(parts[:-1])
        shift = "shift" in mods
        # Ctrl+方向键不再有功能（原“逐谱线”已合并到普通方向键），按住 Ctrl 时忽略
        if mods & {"ctrl", "control"}:
            return
        # 时域：基频起点移动（普通方向 1ms，Shift+方向 10ms）
        if self.current_plot == "time" and self._single_start_t is not None:
            if base_key == "escape":
                self._single_start_t = None
                self._freq_confirmed = False
                self._redraw_current_plot()
                return
            if base_key in ("left", "right"):
                sign = 1 if base_key == "right" else -1
                step = 0.01 if shift else 0.001
                self._single_start_t = max(0, self._single_start_t + sign * step)
                self._redraw_current_plot()
                return
        if self.active_mark_x is None: return
        if base_key == "escape":
            self.active_mark_x = None
            if hasattr(self, "_info_text") and self._info_text in self.fig.texts:
                self._info_text.remove()
                self._info_text = None
            self._redraw_current_plot()
            return
        if base_key not in ("left", "right"): return
        sign = 1 if base_key == "right" else -1
        if shift:
            # Shift+方向：每次移动 0.5Hz，并优先吸附到该 0.5Hz 窗口内最强的谱峰；
            # 窗口内没有明显峰时，就按 0.5Hz 精确移动
            step = self._coarse_step()
            center = self.active_mark_x
            new_x = center + sign * step
            f = self._cur_f
            if f is not None and len(f) > 2 and self._cur_amp is not None:
                try:
                    pk_all, _ = find_peaks(self._cur_amp,
                                           height=float(np.max(self._cur_amp)) * 0.02)
                except Exception:
                    pk_all = np.array([], dtype=int)
                if len(pk_all):
                    if sign > 0:
                        m = (f[pk_all] > center) & (f[pk_all] <= center + step)
                    else:
                        m = (f[pk_all] >= center - step) & (f[pk_all] < center)
                    if np.any(m):
                        cand = pk_all[m]
                        new_x = float(f[int(cand[np.argmax(self._cur_amp[cand])])])
            self.active_mark_x = max(0.0, new_x)
        else:
            # 普通方向键：每次只移动最小分辨率（一条谱线）
            nb = self._nearest_bin(self.active_mark_x, sign)
            if nb is not None:
                self.active_mark_x = nb
            else:
                self.active_mark_x = max(0.0, self.active_mark_x + sign * self._bin_step())
        # 自相关里的活动标记就是“选中的周期”：方向键微调后同步基频，时域标注跟着变
        if self.current_plot == "autocorr" and self.active_mark_x is not None:
            self._sync_freq_from_tau(self.active_mark_x)
        self._redraw_current_plot()

    def _peak_annotate(self, ax, f_m, amp_m, top_n=5, unit="Hz"):
        if not self.show_peaks or self.marks_hidden: return
        xmin, xmax = ax.get_xlim()
        mask_view = (f_m >= xmin) & (f_m <= xmax)
        f_view = f_m[mask_view]; amp_view = amp_m[mask_view]
        if len(f_view) < 3: return
        pk, _ = find_peaks(amp_view, height=np.max(amp_view) * 0.1)
        # 按幅值从高到低选峰，间隔小于视窗0.5%的簇只保留最高那个
        min_gap = (xmax - xmin) * 0.005
        cand = pk[np.argsort(amp_view[pk])[::-1]]
        chosen = []
        for i in cand:
            if all(abs(f_view[i] - f_view[j]) >= min_gap for j in chosen):
                chosen.append(i)
            if len(chosen) >= top_n: break
        top = sorted(chosen, key=lambda i: f_view[i])
        ymin, ymax = ax.get_ylim()
        offset = (ymax - ymin) * 0.06
        for idx in top:
            fi = f_view[idx]; ai = amp_view[idx]
            ax.plot(fi, ai, "ro", ms=3, mfc="white", mec="red", mew=1.2)
            ha = "left" if fi < xmin + (xmax-xmin)*0.05 else "center"
            ax.annotate(f"{fi:.1f}{unit}", xy=(fi, ai), xytext=(fi, ai+offset),
                        fontsize=8, ha=ha, color="darkred",
                        arrowprops=dict(arrowstyle="-", color="gray", lw=0.6))

    def _on_select_refine(self, eclick, erelease):
        if self.axis_locked: return
        if self._wf3d_active(): return
        try:
            x0, x1 = eclick.xdata, erelease.xdata
            if x0 is None or x1 is None: return
            x_start, x_end = sorted([x0, x1])
            x_start = max(x_start, 0.0)
            # 横轴量纲随谱图而变（Hz / Order / s），不能统一用“2 Hz”当最小跨度：
            # 旧逻辑在倒频谱（0~0.2s）上任何框选都会被 abs(x_end-x_start)<2 直接丢弃，
            # 阶次谱小于 2 阶的框选同样无效。
            if self.current_plot == "time":
                t_max = (len(self.sig) - 1) / self.fs if self.sig is not None else x_end
                x_end = min(x_end, float(t_max))
                min_span = 0.01
            else:
                f = self._cur_f
                if f is not None and len(f) > 1:
                    x_max = float(np.max(f))
                    x_end = min(x_end, x_max)
                    min_span = max((x_max - float(np.min(f))) * 0.002, 1e-9)
                else:
                    min_span = 1e-9
            if x_end - x_start < min_span: return
            self._push_undo()
            self.refine_range = (x_start, x_end)
            self._xmax_override = None  # 细化时清除倍频扩展
            # 细化保持“激活”状态，可以连续框选；再次点细化图标才退出并回到全图
            self._redraw_current_plot()
        except Exception as e:
            print("框选异常：", e)

    def _toggle_refine(self):
        # 细化是“状态”：点图标进入，可连续框选；再点一次退出并回到全图
        turning_on = not self.refine_on
        if turning_on:
            self._refine_relock = self.axis_locked
            if self.axis_locked:
                self._set_locked(False)
            self.annotate_mode = False
        elif self.axis_locked:
            self._set_locked(False)
        self.refine_on = turning_on
        ax = self.fig.gca()
        if self.refine_on:
            self._set_on(self.btn_refine, True)
            if self.rs is None:
                self.rs = RectangleSelector(ax, self._on_select_refine, useblit=False, button=[1],
                    minspanx=3, minspany=3, spancoords='pixels', interactive=False,
                    props=dict(edgecolor='none', facecolor='red', alpha=0.15))
            else:
                self.rs.set_active(True); self.rs.ax = ax
        else:
            self._set_on(self.btn_refine, False)
            self.refine_range = None
            self._destroy_selector()
            if self._refine_relock:
                self._auto_lock_pending = True
            self._redraw_current_plot()

    def _signal_key(self):
        """当前参与计算的信号指纹：带通开关/上下限、fs、长度。用于判断缓存是否仍有效。"""
        return (bool(self.var_bp.get()), self.var_bp_low.get(), self.var_bp_high.get(),
                self.fs, 0 if self.sig is None else len(self.sig))

    def _redraw_current_plot(self):
        # 自相关有全量缓存时直接重绘缓存（细化、移动标记、点选周期都秒响应，不重算 FFT）；
        # 但改过带通设置后指纹会变，必须重算，否则图上还是旧滤波结果的曲线。
        if (self.current_plot == "autocorr" and getattr(self, "_ac_cache", None) is not None
                and getattr(self, "_ac_cache_key", None) == self._signal_key()):
            tau_all, ac_all = self._ac_cache
            self.draw_autocorr_result(tau_all, ac_all, "自相关函数")
            return
        {"fft": self.plot_fft, "envelope": self.plot_envelope, "order": self.plot_order,
         "cepstrum": self.plot_cepstrum, "velocity": self.plot_velocity,
         "time": self.plot_time, "autocorr": self.plot_autocorr,
         "stft": self.plot_waterfall}.get(self.current_plot, lambda: None)()

    def _toggle_hann(self):
        # FFT/包络谱：汉宁窗 ↔ 矩形窗 切换后立即重绘
        self.var_hann.set(not self.var_hann.get())
        self._redraw_current_plot()

    def _toggle_stft_win(self):
        # 瀑布图：分段汉宁窗 ↔ 矩形窗 切换后立即重绘
        self.var_stft_win.set(not self.var_stft_win.get())
        self._redraw_current_plot()

    def _on_canvas_context(self, event):
        # 右键菜单：当前谱可用的带通设置 + 复制图片
        if event.button != 3 or event.inaxes is None:
            return
        menu = tk.Menu(self, tearoff=0)
        # 窗函数菜单项名称随“当前所用窗”动态切换，并标明点击后会切到哪一种窗
        hann_lbl = ("窗函数：汉宁窗（当前）· 点击切矩形窗" if self.var_hann.get()
                    else "窗函数：矩形窗（当前）· 点击切汉宁窗")
        stft_lbl = ("瀑布分段窗：汉宁窗（当前）· 点击切矩形窗" if self.var_stft_win.get()
                    else "瀑布分段窗：矩形窗（当前）· 点击切汉宁窗")
        if self.current_plot == "fft":
            menu.add_command(label="应用带通设置…", command=lambda: self._open_band_dialog("bp"))
            menu.add_separator()
            menu.add_command(label=hann_lbl, command=self._toggle_hann)
            menu.add_separator()
        elif self.current_plot in ("velocity", "order"):
            menu.add_command(label="应用带通设置…", command=lambda: self._open_band_dialog("bp"))
            if self.current_plot == "order":
                menu.add_command(label="设置转速 / 转频…", command=self._order_set_rot)
            menu.add_separator()
        elif self.current_plot == "envelope":
            menu.add_command(label="包络带通设置…", command=lambda: self._open_band_dialog("env"))
            menu.add_separator()
            menu.add_command(label=hann_lbl, command=self._toggle_hann)
            menu.add_separator()
        elif self.current_plot == "stft":
            menu.add_command(label=stft_lbl, command=self._toggle_stft_win)
            menu.add_command(label=("切换到 2D 瀑布" if getattr(self, "_wf_3d", False)
                                    else "切换到 3D 瀑布（可旋转）"),
                             command=self._toggle_wf_3d)
            menu.add_command(label=("瀑布幅值：dB（当前）· 点击切线性格" if getattr(self, "_wf_db", True)
                                    else "瀑布幅值：线性（当前）· 点击切 dB"),
                             command=self._toggle_wf_db)
            menu.add_separator()
        if self.current_plot in ("fft", "envelope", "velocity"):
            menu.add_command(label="齿轮啮合/边带标注…（断齿、点蚀）",
                             command=self._gear_dialog)
            if self._gear_marks:
                menu.add_command(label="清除齿轮啮合/边带标注", command=self._clear_gear_marks)
            menu.add_separator()
            menu.add_command(label="轴承特征频率标注…（BPFI/BPFO/BSF/FTF）",
                             command=self._bearing_dialog)
            menu.add_command(
                label=("自动轴承标注（府谷库）：开 · 点击关闭"
                       if getattr(self, "_auto_bearing_on", True)
                       else "自动轴承标注（府谷库）：关 · 点击开启"),
                command=self._toggle_auto_bearing)
            if self._bearing_marks:
                menu.add_command(label="清除轴承特征频率标注", command=self._clear_bearing_marks)
            menu.add_separator()
        # 基频管理（同一张谱上可以同时存在多个基频）：右键在此处添加一个，或按频率逐个删除
        if self.current_plot not in ("time", "autocorr"):
            x_now = getattr(event, "xdata", None)
            try:
                add_lbl = ("在此处添加基频（%.1fHz）" % float(x_now)) if x_now is not None else "在此处添加基频"
            except Exception:
                add_lbl = "在此处添加基频"
            menu.add_command(
                label=add_lbl,
                command=lambda x=x_now, px=getattr(event, "x", None): self._add_base_at(x, px))
            sub = tk.Menu(menu, tearoff=0)
            bases = self._base_list()
            if bases:
                for fb in bases:
                    act = ("   ← 当前" if (self.active_mark_x is not None
                                         and abs(float(self.active_mark_x) - fb) < 1e-6) else "")
                    sub.add_command(label="删除 %.2fHz%s" % (fb, act),
                                    command=lambda v=fb: self._remove_base(v))
            else:
                sub.add_command(label="（暂无基频）", state="disabled")
            menu.add_cascade(label="删除基频", menu=sub)
            menu.add_separator()
        menu.add_command(label="隐藏标注" if not self.marks_hidden else "显示标注",
                         command=self._toggle_marks_visible)
        menu.add_command(label="清除全部标注", command=self._clear_all_marks)
        menu.add_separator()
        menu.add_command(label="解锁视图（恢复交互）" if self.axis_locked
                         else "锁定视图（冻结 X/Y 轴）", command=self._toggle_lock)
        menu.add_command(label="复制图片", command=self._copy_current_figure)
        menu.add_command(label="另存图片…", command=self._save_current_figure)
        try:
            menu.tk_popup(event.guiEvent.x_root, event.guiEvent.y_root)
        finally:
            menu.grab_release()

    def _open_band_dialog(self, kind):
        # bp：应用带通（带启用开关，FFT/速度/阶次）；env：包络带通（始终生效，包络谱）
        is_bp = (kind == "bp")
        v_lo = self.var_bp_low if is_bp else self.var_env_low
        v_hi = self.var_bp_high if is_bp else self.var_env_high
        dlg = tk.Toplevel(self)
        dlg.title("应用带通设置" if is_bp else "包络带通设置")
        dlg.transient(self); dlg.resizable(False, False)
        frm = ttk.Frame(dlg, padding=12); frm.pack(fill="both", expand=True)
        row = 0
        if is_bp:
            ttk.Checkbutton(frm, text="启用应用带通", variable=self.var_bp).grid(
                row=row, column=0, columnspan=4, sticky="w", pady=(0, 8)); row += 1
        ttk.Label(frm, text="低频(Hz)").grid(row=row, column=0, padx=(0, 4), sticky="e")
        e_lo = ttk.Entry(frm, textvariable=v_lo, width=10); e_lo.grid(row=row, column=1, padx=4)
        ttk.Label(frm, text="高频(Hz)").grid(row=row, column=2, padx=(8, 4), sticky="e")
        e_hi = ttk.Entry(frm, textvariable=v_hi, width=10); e_hi.grid(row=row, column=3, padx=4)

        def apply():
            try:
                lo = float(v_lo.get()); hi = float(v_hi.get())
            except (ValueError, TypeError):
                messagebox.showerror("输入错误", "频率请填写数字。", parent=dlg); return
            if lo < 0 or hi <= 0 or hi <= lo:
                messagebox.showerror("输入错误", "请保证 0 ≤ 低频 < 高频。", parent=dlg); return
            dlg.destroy()
            self._redraw_current_plot()

        btns = ttk.Frame(frm); btns.grid(row=row + 1, column=0, columnspan=4, pady=(12, 0), sticky="e")
        ttk.Button(btns, text="确定", command=apply).pack(side="left", padx=4)
        ttk.Button(btns, text="取消", command=dlg.destroy).pack(side="left", padx=4)
        dlg.bind("<Return>", lambda e: apply())
        dlg.bind("<Escape>", lambda e: dlg.destroy())
        dlg.update_idletasks(); dlg.withdraw(); self.update_idletasks()
        x = self.winfo_rootx() + max(0, (self.winfo_width() - dlg.winfo_reqwidth()) // 2)
        y = self.winfo_rooty() + max(0, (self.winfo_height() - dlg.winfo_reqheight()) // 3)
        dlg.geometry(f"+{x}+{y}"); dlg.deiconify(); dlg.grab_set()
        e_lo.focus_set()

    def _copy_current_figure(self):
        # 静默复制位图到系统剪贴板：不弹窗、不写硬盘，直接在微信/Word/画图等 Ctrl+V 粘贴；
        # 仅在真正失败时弹错误框，避免无提示地静默失败
        try:
            copy_figure_to_clipboard(self.fig)
        except Exception as e:
            messagebox.showerror("复制失败", str(e), parent=self)

    def _save_current_figure(self):
        """右键“另存图片…”：默认桌面 + 测点_谱型_时间戳.png。"""
        import datetime
        desktop = os.path.join(os.path.expanduser("~"), "Desktop")
        if not os.path.isdir(desktop):
            desktop = os.path.expanduser("~")
        point = str((self.info or {}).get("point") or "测点")
        for ch in '\\/:*?"<>|':
            point = point.replace(ch, "_")
        names = {"fft": "FFT", "envelope": "包络", "velocity": "速度", "order": "阶次",
                 "cepstrum": "倒频谱", "time": "时域", "autocorr": "自相关", "stft": "瀑布"}
        plot = names.get(self.current_plot, self.current_plot or "图谱")
        default = f"{point}_{plot}_{datetime.datetime.now():%Y%m%d_%H%M}.png"
        path = filedialog.asksaveasfilename(
            parent=self, title="保存图谱", defaultextension=".png",
            initialdir=desktop, initialfile=default,
            filetypes=[("PNG 图片", "*.png"), ("JPEG 图片", "*.jpg"),
                       ("PDF 文档", "*.pdf"), ("SVG 矢量图", "*.svg")])
        if not path:
            return
        try:
            self.fig.savefig(path, dpi=200, facecolor=self.fig.get_facecolor())
            messagebox.showinfo("保存成功", path, parent=self)
        except Exception as e:
            messagebox.showerror("保存失败", str(e), parent=self)

    # 三类标注的统一配色：倍频跟随基频色，边带紫、带宽青，一眼可分
    SIDEBAND_COLOR = "#7b52ab"
    BANDWIDTH_COLOR = "#0f7b7d"

    def _gear_marks_for(self, stage_idx, f_hss, n_mesh=1, n_sb=1):
        """算某级齿轮的啮合频率、谐波与 ±边带，返回标注列表。"""
        try:
            name, shaft_k, teeth, sb_shaft = GEAR_STAGES[stage_idx]
        except Exception:
            return []
        f = self._bearing_shaft_freqs(f_hss)
        base = f.get(shaft_k, 0.0)
        f_sb = f.get(sb_shaft, base)
        if base <= 0:
            return []
        mesh = teeth * base
        marks = []
        for m in range(1, int(n_mesh) + 1):
            hz = mesh * m
            lab = "啮合 %.0f" % hz if m == 1 else "%d×啮合 %.0f" % (m, hz)
            marks.append({"hz": hz, "label": lab, "color": GEAR_COLOR, "lw": 1.2})
            for k in range(1, int(n_sb) + 1):
                for sign, tag in ((-1, "-"), (1, "+")):
                    sb = hz + sign * k * f_sb
                    if sb <= 0:
                        continue
                    marks.append({"hz": sb, "label": "", "color": GEAR_SB_COLOR, "lw": 0.8})
        return marks

    def _gear_dialog(self):
        """选齿轮级 + 转速，标注啮合频率及其 ±转频边带（断齿/点蚀诊断）。"""
        f0 = self._get_rot_hz()
        rpm0 = (f0 * 60.0) if f0 > 0 else 0.0
        dlg = tk.Toplevel(self)
        dlg.title("齿轮啮合/边带标注")
        dlg.transient(self); dlg.resizable(False, False)
        frm = ttk.Frame(dlg, padding=12); frm.pack(fill="both", expand=True)
        ttk.Label(frm, text="标注齿轮啮合频率及 ±转频边带（断齿、点蚀看边带）：").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))
        names = [g[0] for g in GEAR_STAGES]
        v_g = tk.StringVar(value=names[min(self._gear_stage, len(names) - 1)])
        ttk.Label(frm, text="齿轮级：").grid(row=1, column=0, sticky="e", pady=3)
        ttk.Combobox(frm, textvariable=v_g, values=names, width=32,
                     state="readonly").grid(row=1, column=1, sticky="w", pady=3)
        v_rpm = tk.StringVar(value=("%.0f" % rpm0) if rpm0 > 0 else "")
        ttk.Label(frm, text="高速轴转速(rpm)：").grid(row=2, column=0, sticky="e", pady=3)
        ttk.Entry(frm, textvariable=v_rpm, width=12).grid(row=2, column=1, sticky="w", pady=3)
        v_mesh = tk.StringVar(value="1")
        ttk.Label(frm, text="啮合谐波次数：").grid(row=3, column=0, sticky="e", pady=3)
        ttk.Combobox(frm, textvariable=v_mesh, values=["1", "2", "3"], width=5,
                     state="readonly").grid(row=3, column=1, sticky="w", pady=3)
        v_sb = tk.StringVar(value="1")
        ttk.Label(frm, text="边带阶数(±k×转频)：").grid(row=4, column=0, sticky="e", pady=3)
        ttk.Combobox(frm, textvariable=v_sb, values=["0", "1", "2", "3"], width=5,
                     state="readonly").grid(row=4, column=1, sticky="w", pady=3)
        # 自定义倍数：库里没有的轴承（例如发电机非驱动端轴承）可直接填特征倍数
        ttk.Label(frm, text="自定义倍数(可留空)：").grid(row=5, column=0, sticky="e", pady=3)
        cbox = ttk.Frame(frm); cbox.grid(row=5, column=1, sticky="w", pady=3)
        v_cust = {}
        for _i, _k in enumerate(("BPFI", "BPFO", "BSF", "FTF")):
            ttk.Label(cbox, text=_k).grid(row=0, column=_i * 2, padx=(0 if _i == 0 else 6, 1))
            v_cust[_k] = tk.StringVar(value="")
            ttk.Entry(cbox, textvariable=v_cust[_k], width=6).grid(row=0, column=_i * 2 + 1)
        res = {"ok": False}

        def ok():
            try:
                rpm = float(v_rpm.get())
            except Exception:
                messagebox.showerror("输入错误", "转速请填数字。", parent=dlg); return
            if rpm <= 0:
                messagebox.showerror("输入错误", "转速必须大于 0。", parent=dlg); return
            idx = names.index(v_g.get())
            marks = self._gear_marks_for(idx, rpm / 60.0,
                                         int(v_mesh.get() or 1), int(v_sb.get() or 0))
            if not marks:
                messagebox.showerror("计算失败", "无法计算，请检查转速。", parent=dlg); return
            self._gear_marks = marks
            self._gear_stage = idx
            self._rot_hz = rpm / 60.0
            res["ok"] = True
            dlg.destroy()

        bf = ttk.Frame(frm); bf.grid(row=5, column=0, columnspan=2, pady=(10, 0), sticky="e")
        ttk.Button(bf, text="确定", command=ok).pack(side="left", padx=4)
        ttk.Button(bf, text="取消", command=dlg.destroy).pack(side="left", padx=4)
        dlg.bind("<Return>", lambda e: ok())
        dlg.bind("<Escape>", lambda e: dlg.destroy())
        center_window(dlg, self)
        dlg.wait_window()
        if res["ok"]:
            self._redraw_current_plot()

    def _clear_gear_marks(self):
        self._gear_marks = []
        self._redraw_current_plot()

    def _draw_gear_marks(self, ax):
        """画啮合频率（粗线+文字）和边带（细淡线）。"""
        if not self._gear_marks:
            return
        try:
            x0, x1 = ax.get_xlim()
            for item in self._gear_marks:
                hz = float(item["hz"])
                if hz < x0 or hz > x1:
                    continue
                ax.axvline(hz, color=item["color"], ls=(0, (5, 3)),
                           lw=item.get("lw", 1.0), alpha=0.95 if item["label"] else 0.55,
                           zorder=1.6)
                if item["label"]:
                    ax.text(hz, 1.008, item["label"], rotation=90,
                            transform=ax.get_xaxis_transform(),
                            va="bottom", ha="center", fontsize=6.2,
                            color=item["color"], zorder=8, clip_on=False,
                            bbox=dict(boxstyle="round,pad=0.06", fc="white",
                                      ec="none", alpha=0.75))
        except Exception:
            pass

    def _apply_auto_bearing_marks(self):
        """按“项目 + 测点”自动标注轴承特征频率；只有登记过的项目（府谷）才生效。"""
        self._bearing_marks = []
        self._auto_bearing_used = False
        if not getattr(self, "_auto_bearing_on", True):
            return
        info = self.info or {}
        proj = str(info.get("project") or "")
        pt = str(info.get("point") or "")
        if wf_bad_point(proj, info.get("unit"), pt):
            return
        mapping = None
        for pk, pm in BEARING_PROJECT_MAP.items():
            if pk and pk in proj:
                mapping = pm
                break
        if not mapping:
            return
        names = None
        for kw, blist in mapping:
            if kw and kw in pt:
                names = blist
                break
        if not names:
            return
        try:
            rpm = float(info.get("speed") or 0)
        except (TypeError, ValueError):
            rpm = 0.0
        if rpm <= 0:
            return
        try:
            f = self._bearing_shaft_freqs(rpm / 60.0)
        except Exception:
            return
        marks = []
        multi = len(names) > 1
        for nm in names:
            entry = BEARING_LIB.get(nm)
            if not entry:
                continue
            shaft, mult = entry
            base = f.get(shaft, 0.0)
            if base <= 0:
                continue
            if ("B12" in nm) or ("B13" in nm):
                short = "6332"          # 同一型号 6332MC4（B12/B13 倍数一致）
            elif "SKF" in nm:
                short = "SKF"
            else:
                short = ""
            tag = (short + "-") if (multi and short) else ""
            for k in ("BPFI", "BPFO", "BSF", "FTF"):
                m = mult.get(k)
                if not m:
                    continue
                marks.append({"hz": m * base, "label": tag + k,
                              "color": BEARING_COLORS[k]})
        self._bearing_marks = marks
        self._auto_bearing_used = bool(marks)

    def _toggle_auto_bearing(self):
        self._auto_bearing_on = not getattr(self, "_auto_bearing_on", True)
        if self._auto_bearing_on:
            self._apply_auto_bearing_marks()
        else:
            self._bearing_marks = []
            self._auto_bearing_used = False
        self._redraw_current_plot()

    def _bearing_shaft_freqs(self, f_hss):
        """由高速轴(发电机)转频算各轴转频(Hz)。"""
        fM = f_hss / GB_I3
        fS = fM / GB_I2
        fL = fS / GB_I1
        return {"H": f_hss, "M": fM, "S": fS, "L": fL, "P": fL * GB_ZR / GB_ZP}

    def _bearing_dialog(self):
        """选轴承 + 转速，在谱图上标注 BPFI/BPFO/BSF/FTF（含谐波）。"""
        f0 = self._get_rot_hz()
        rpm0 = (f0 * 60.0) if f0 > 0 else 0.0
        dlg = tk.Toplevel(self)
        dlg.title("轴承特征频率标注")
        dlg.transient(self); dlg.resizable(False, False)
        frm = ttk.Frame(dlg, padding=12); frm.pack(fill="both", expand=True)
        ttk.Label(frm, text="选择轴承与转速，标注 BPFI / BPFO / BSF / FTF：").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))
        names = list(BEARING_LIB.keys())
        v_b = tk.StringVar(value=self._bearing_sel or names[0])
        ttk.Label(frm, text="轴承：").grid(row=1, column=0, sticky="e", pady=3)
        cb = ttk.Combobox(frm, textvariable=v_b, values=names, width=30, state="readonly")
        cb.grid(row=1, column=1, sticky="w", pady=3)
        v_rpm = tk.StringVar(value=("%.0f" % rpm0) if rpm0 > 0 else "")
        ttk.Label(frm, text="高速轴转速(rpm)：").grid(row=2, column=0, sticky="e", pady=3)
        ttk.Entry(frm, textvariable=v_rpm, width=12).grid(row=2, column=1, sticky="w", pady=3)
        v_ord = tk.StringVar(value="1")
        ttk.Label(frm, text="谐波次数：").grid(row=3, column=0, sticky="e", pady=3)
        ttk.Combobox(frm, textvariable=v_ord, values=["1", "2", "3"], width=5,
                     state="readonly").grid(row=3, column=1, sticky="w", pady=3)
        keys = {}
        box = ttk.Frame(frm); box.grid(row=4, column=0, columnspan=2, sticky="w", pady=(6, 0))
        for i, k in enumerate(("BPFI", "BPFO", "BSF", "FTF")):
            v = tk.BooleanVar(value=(k in ("BPFI", "BPFO")))
            ttk.Checkbutton(box, text=k, variable=v).grid(row=0, column=i, padx=6)
            keys[k] = v
        # 自定义倍数：库里没有的轴承（或临时改倍数）可直接填特征倍数。
        # 留空 = 用 BEARING_LIB 的库值；填了 = 按所选轴承的轴转频覆盖对应项。
        ttk.Label(frm, text="自定义倍数(可留空)：").grid(row=5, column=0, sticky="e", pady=3)
        cbox = ttk.Frame(frm); cbox.grid(row=5, column=1, sticky="w", pady=3)
        v_cust = {}
        for _i, _k in enumerate(("BPFI", "BPFO", "BSF", "FTF")):
            ttk.Label(cbox, text=_k).grid(row=0, column=_i * 2, padx=(0 if _i == 0 else 6, 1))
            v_cust[_k] = tk.StringVar(value="")
            ttk.Entry(cbox, textvariable=v_cust[_k], width=6).grid(row=0, column=_i * 2 + 1)
        res = {"ok": False}

        def ok():
            try:
                rpm = float(v_rpm.get())
            except Exception:
                messagebox.showerror("输入错误", "转速请填数字。", parent=dlg); return
            if rpm <= 0:
                messagebox.showerror("输入错误", "转速必须大于 0。", parent=dlg); return
            sel = [k for k, v in keys.items() if v.get()]
            if not sel:
                messagebox.showerror("输入错误", "至少勾选一个特征频率。", parent=dlg); return
            self._bearing_sel = v_b.get()
            marks = []
            try:
                f = self._bearing_shaft_freqs(rpm / 60.0)
            except Exception:
                messagebox.showerror("计算失败", "转速换算失败。", parent=dlg); return
            shaft, mult = BEARING_LIB[v_b.get()]
            base = f.get(shaft, 0.0)
            _cust = {}
            for _k, _v in v_cust.items():
                try:
                    _val = float(str(_v.get()).strip())
                except Exception:
                    _val = 0.0
                if _val > 0:
                    _cust[_k] = _val
            if _cust:
                mult = dict(mult)          # 复制一份：mult 原为 BEARING_LIB 里的字典，直接改会污染全局表
                mult.update(_cust)
            n_ord = int(v_ord.get() or 1)
            for k in sel:
                m = mult.get(k)
                if not m or base <= 0:
                    continue
                for o in range(1, n_ord + 1):
                    hz = m * base * o
                    lab = k if o == 1 else "%s×%d" % (k, o)
                    marks.append({"hz": hz, "label": lab, "color": BEARING_COLORS.get(k, "#444")})
            self._bearing_marks = marks
            self._rot_hz = rpm / 60.0
            res["ok"] = True
            dlg.destroy()

        bf = ttk.Frame(frm); bf.grid(row=6, column=0, columnspan=2, pady=(10, 0), sticky="e")
        ttk.Button(bf, text="确定", command=ok).pack(side="left", padx=4)
        ttk.Button(bf, text="取消", command=dlg.destroy).pack(side="left", padx=4)
        dlg.bind("<Return>", lambda e: ok())
        dlg.bind("<Escape>", lambda e: dlg.destroy())
        center_window(dlg, self)
        dlg.wait_window()
        if res["ok"]:
            self._redraw_current_plot()

    def _clear_bearing_marks(self):
        self._bearing_marks = []
        self._redraw_current_plot()

    def _draw_bearing_marks(self, ax):
        """把轴承特征频率画成竖虚线 + 顶部标签（只在频率轴上画）。"""
        if not self._bearing_marks:
            return
        try:
            x0, x1 = ax.get_xlim()
            y0, y1 = ax.get_ylim()
            span = (y1 - y0) or 1.0
            top = y1 - span * 0.015
            shown = 0
            for item in self._bearing_marks:
                hz = float(item["hz"])
                if hz < x0 or hz > x1:
                    continue
                first = ("×" not in str(item["label"]))     # 只有 1× 写文字，谐波只画线
                ax.axvline(hz, color=item["color"],
                           ls=(0, (4, 3)) if first else (0, (2, 3)),
                           lw=1.0 if first else 0.8,
                           alpha=0.9 if first else 0.5, zorder=1.5)
                if not first:
                    continue
                ax.text(hz, 1.008, "%s %.0f" % (item["label"], hz), rotation=90,
                        transform=ax.get_xaxis_transform(),
                        va="bottom", ha="center", fontsize=6.2, color=item["color"],
                        zorder=8, clip_on=False,
                        bbox=dict(boxstyle="round,pad=0.06", fc="white", ec="none", alpha=0.75))
                shown += 1
        except Exception:
            pass

    def _post_draw(self):
        ax = self.fig.gca()
        ax.format_coord = lambda x, y: ""  # 不显示鼠标坐标
        if self.current_plot not in ("time", "autocorr", "cepstrum"):
            x_left, xmax = ax.get_xlim()
            # X 轴左边界锁在 0：不再用 -2% 留白（带通视图原本从 10Hz 起的话保留 10Hz）
            ax.set_xlim(max(0.0, x_left), xmax)
            # 瀑布图的纵轴是“帧偏移”，顶部留白由 plot_waterfall 自己控制，不再统一放大 1.25
            if self.current_plot != "stft":
                ymax = ax.get_ylim()[1]
                ax.set_ylim(0, ymax * 1.25)
        # 细化模式：x轴左右各留边距（时域图也支持）
        if self.refine_range is not None:
            r0, r1 = self.refine_range
            pad = (r1 - r0) * 0.05
            ax.set_xlim(max(0.0, r0 - pad), r1 + pad)
            # 只在全图视图下画淡红竖条标示选中频段
            cur_x0, cur_x1 = ax.get_xlim()
            if (cur_x1 - cur_x0) > (r1 - r0) * 1.5:
                for p in list(ax.patches):
                    if getattr(p, "_is_refine_box", False):
                        p.remove()
                y0, y1 = ax.get_ylim()
                box = Rectangle((r0, y0), r1 - r0, y1 - y0,
                                edgecolor='none', facecolor='red', alpha=0.15)
                box._is_refine_box = True
                ax.add_patch(box)
        # 倍频后强制扩展x轴到10x位置（不受refine_range限制）
        if self._xmax_override is not None and self.current_plot not in ("time", "stft", "autocorr"):
            # 左边界必须按“新右限”重算 2% 留白；不能沿用切换前的 x0，
            # 否则新右限远小于原范围时会残留一个很大的负左界，X 轴出现大片负坐标
            new_x1 = self._xmax_override
            ax.set_xlim(0, new_x1)
        # 视图锁定：以上所有自动缩放/细化/倍频扩展，最终都以锁定时的范围为准
        if self.axis_locked and self._locked_xlim is not None and self._locked_ylim is not None:
            ax.set_xlim(*self._locked_xlim)
            ax.set_ylim(*self._locked_ylim)
        # 标注绘制顺序：带宽填充（最底层）→ 基频/倍频/边带 → 活动基频 → 信息面板
        # 标注只画在横轴为频率的谱图上（时域/自相关/阶次/倒频谱量纲不同，不画错位）
        _freq_plot = self.current_plot in ("fft", "envelope", "velocity", "stft")
        if not self.marks_hidden and _freq_plot:
            self._draw_bandwidth_regions(ax)
            self._draw_manual_marks(ax)
        if not self.marks_hidden and self.current_plot in ("fft", "envelope", "velocity"):
            self._draw_bearing_marks(ax)
            self._draw_gear_marks(ax)
        if (not self.marks_hidden and self.active_mark_x is not None
                and self.current_plot in ("fft", "envelope", "velocity", "stft", "autocorr")):
            self._draw_active_mark(ax)
        if self.refine_on and not self.axis_locked:
            # fig.clear()后旧selector已废，在新ax上重建，保证每次框选都有淡红跟随
            self._destroy_selector()
            self.rs = RectangleSelector(ax, self._on_select_refine, useblit=False, button=[1],
                minspanx=3, minspany=3, spancoords='pixels', interactive=False,
                props=dict(edgecolor='none', facecolor='red', alpha=0.15))
        if not self.marks_hidden and _freq_plot:
            self._draw_annotation_panel(ax)
        # rect 顶部预留 5% 灰区用于摆放悬浮图标（标题已移到画布外独立条带）；
        # pad=0.4 收紧绘图区四周浅灰留白（默认 1.08 偏宽），在不裁切轴标签/色标的前提下放大波形区
        self.fig.tight_layout(rect=(0, 0, 1, 0.95), pad=0.4)
        if len(self.fig.axes) == 1:
            # 四边边距按“画布像素 + 屏幕 DPI”换算：窗口小/系统缩放时给刻度文字多留一些，
            # 窗口大时按固定像素收紧，绘图区随之变大（拉伸/缩放都能自适应，标签不会被裁）
            try:
                wpx = max(float(self.fig.get_figwidth() * self.fig.dpi), 320.0)
                hpx = max(float(self.fig.get_figheight() * self.fig.dpi), 240.0)
                k = float(self.fig.dpi) / 96.0
                left = min(0.22, max(0.09, 62.0 * k / wpx))
                bottom = min(0.28, max(0.12, 36.0 * k / hpx))
                top = 1.0 - min(0.16, max(0.07, 30.0 * k / hpx))
                right = 1.0 - min(0.10, max(0.015, 14.0 * k / wpx))
                if self._bearing_marks or self._gear_marks:
                    top = min(top, 1.0 - 0.10)   # 给标注文字留一条窄带
                self.fig.subplots_adjust(left=left, right=right, top=top, bottom=bottom)
            except Exception:
                pass
        self.canvas.draw()
        self._schedule_save_annotations()
        # 谱图首次绘出后按当前范围自动锁定（所有谱图默认锁定 X/Y）：
        # 之后标注/窗函数/峰值等重绘都沿用锁定范围；显式看图动作会临时解锁并重新锁定
        if getattr(self, "_auto_lock_pending", False):
            self._auto_lock_pending = False
            if not self.axis_locked:
                self._set_locked(True)
        self._position_chart_tools()
        self.canvas.get_tk_widget().focus_set()

    def _amp_at(self, x):
        """取当前谱线在频率 x 处的幅值（用于把标注线限制在真实谱线高度内）。"""
        if self._cur_f is None or self._cur_amp is None or len(self._cur_f) == 0:
            return None
        try:
            i = int(np.argmin(np.abs(self._cur_f - x)))
            return float(self._cur_amp[i])
        except Exception:
            return None

    def _stem_height(self, ax, x, frac=0.035):
        """短标线高度：至少占纵轴 frac，若该频率确有更高谱线则升到谱线高度。"""
        ymin, ymax = ax.get_ylim()
        span = (ymax - ymin) or 1.0
        a = self._amp_at(x)
        return max(span * frac, a if a is not None else 0.0)

    def _draw_bandwidth_regions(self, ax):
        """带宽区：交替浅填充 + 边界虚线；窄带不标文字（必然糊），只有像素宽度足够时才写 BW 序号。
        每组的起止频率与带内峰值统一在右上角面板列出。"""
        regions = getattr(self, "_bandwidth_regions", [])
        if not regions:
            return
        ymin, ymax = ax.get_ylim()
        x0, x1 = ax.get_xlim()
        for i, reg in enumerate(regions):
            if isinstance(reg, dict):
                f_lo, fe, lab = reg["lo"], reg["hi"], reg["label"]
                col = reg.get("color", self.BANDWIDTH_COLOR)
                amp = float(reg.get("amp", 0.0) or 0.0)
                peak = float(reg.get("peak", 0.0) or 0.0)
            else:
                f_lo, fe, lab = reg
                col = self.BANDWIDTH_COLOR
                amp = 0.0
                peak = 0.0
            ax.axvspan(f_lo, fe, facecolor=col, alpha=0.28,
                       hatch="///", edgecolor="#8a5a00", linewidth=0.7, zorder=0)
            # 组边界：深琥珀色虚线，从底一直延伸到图顶
            for _edge in (f_lo, fe):
                ax.vlines(_edge, 0, ymax, color="#8a5a00", ls=(0, (4, 3)),
                          lw=1.1, alpha=0.95, zorder=1)
            # BWx 标记放在“带内真实峰值”处；老标注没有 peak 字段时现算
            if not (f_lo <= peak <= fe):
                peak, _a_peak = self._peak_in_range(f_lo, fe)
                amp = max(amp, _a_peak)
            mark_x = peak
            if amp <= 0.0:
                amp = self._amp_at(mark_x) or 0.0
            span = (ymax - ymin) or 1.0
            h = max(amp, span * 0.05)
            cap = max((x1 - x0) * 0.003, 1e-9)
            ax.vlines(mark_x, 0, h, color=col, ls="--", lw=1.0, alpha=0.9, zorder=2)
            if self.current_plot != "stft":
                _a = self._amp_at(mark_x)
                if _a is not None:
                    ax.plot(mark_x, _a, "o", ms=self.RING_MS, mfc="white",
                            mec="red", mew=self.RING_MEW, zorder=6)
            yy = h + span * 0.02
            va = "bottom"
            if yy + span * 0.09 > ymax:
                yy = h - span * 0.02
                va = "top"
            ax.text(mark_x, yy, lab, fontsize=7.0, color=col, ha="center", va=va,
                    zorder=7,
                    bbox=dict(boxstyle="round,pad=0.12", fc="white", ec=col,
                              lw=0.6, alpha=0.94))

    def _draw_manual_marks(self, ax):
        """基频（实线+空心点）、倍频（点划线+底部角标，密集时自动省略）、边带（紫色点线+引线角标）。"""
        if not self.manual_marks:
            return
        ymin, ymax = ax.get_ylim()
        span = ymax - ymin
        x0, x1 = ax.get_xlim()
        f0_count = 0
        last_hx = None  # 上一个倍频角标的像素 x：倍频密集时自动省略文字，避免糊成一团
        last_sb_x = None  # 上一个边带角标的像素 x
        for mark in self.manual_marks:
            xv = mark[0]; lab = str(mark[1])
            mc = mark[2] if len(mark) > 2 else "darkred"
            amp_val = mark[3] if len(mark) > 3 else 0.01
            if xv < x0 or xv > x1:
                continue
            if lab == "f0":
                # 历史基频：短虚线到该频率的真实谱线高度，不再通高
                _a = self._amp_at(xv)
                if _a is None:
                    _a = amp_val
                if self.current_plot != "stft":
                    ax.vlines(xv, 0, self._stem_height(ax, xv, 0.045), color=mc,
                              ls=(0, (5, 3)), lw=0.9, alpha=0.55, zorder=3)
                    ax.plot(xv, _a, "o", ms=4.5, mfc="white", mec=mc, mew=1.5, zorder=5)
                y_text = _a + span * 0.03
                va = "bottom"
                if y_text + span * 0.10 > ymax:
                    y_text = max(ymin + span * 0.03, _a - span * 0.03)
                    va = "top"
                ax.text(xv, y_text, f"{xv:.1f}Hz  {amp_val:.2f}", fontsize=8, color=mc,
                        ha="center", va=va, zorder=7,
                        bbox=dict(boxstyle="round,pad=0.18", fc="white", ec=mc, lw=0.6, alpha=0.9))
                f0_count += 1
            elif lab.endswith("X"):
                k = int(lab[:-1]) if lab[:-1].isdigit() else 0
                # 倍频：竖线到谱线高度，顶端加一小段横向短线，标号放在横线之上
                _h = self._stem_height(ax, xv, 0.05)
                _cap = (x1 - x0) * 0.004
                if self.current_plot != "stft":
                    ax.vlines(xv, 0, _h, color=mc, ls="-.", lw=0.9,
                              alpha=max(0.45, 0.85 - 0.04 * k), zorder=2)
                    _a = self._amp_at(xv)
                    if _a is not None:
                        ax.plot(xv, _a, "o", ms=self.RING_MS, mfc="white",
                                mec="red", mew=self.RING_MEW, zorder=6)
                try:
                    px = float(ax.transData.transform((xv, 0.0))[0])
                except Exception:
                    px = None
                if px is None or last_hx is None or abs(px - last_hx) >= 24:
                    yy = _h + span * 0.02
                    va = "bottom"
                    if yy + span * 0.10 > ymax:
                        yy = _h - span * 0.02
                        va = "top"
                    ax.text(xv, yy, lab, fontsize=7.6, color=mc, ha="center", va=va,
                            zorder=7,
                            bbox=dict(boxstyle="round,pad=0.14", fc="white", ec=mc, lw=0.6,
                                      alpha=0.94))
                    last_hx = px
            else:
                col = mc   # 边带跟随所属基频的颜色
                txt = lab.replace("sb", "SB")
                _h = self._stem_height(ax, xv, 0.045)
                _cap = (x1 - x0) * 0.003
                if self.current_plot != "stft":
                    ax.vlines(xv, 0, _h, color=col, ls=(0, (1, 1.6)), lw=1.0,
                              alpha=0.9, zorder=2)
                    _a = self._amp_at(xv)
                    if _a is not None:
                        ax.plot(xv, _a, "o", ms=self.RING_MS, mfc="white",
                                mec="red", mew=self.RING_MEW, zorder=6)
                try:
                    px = float(ax.transData.transform((xv, 0.0))[0])
                except Exception:
                    px = None
                if px is None or last_sb_x is None or abs(px - last_sb_x) >= 30:
                    yy = _h + span * 0.02
                    va = "bottom"
                    if yy + span * 0.10 > ymax:
                        yy = _h - span * 0.02
                        va = "top"
                    ax.text(xv, yy, txt, fontsize=7.2, color=col, ha="center", va=va,
                            zorder=7,
                            bbox=dict(boxstyle="round,pad=0.14", fc="white", ec=col,
                                      lw=0.6, alpha=0.94))
                    last_sb_x = px

    def _draw_active_mark(self, ax):
        """当前活动基频：淡色窄带 + 峰值短竖线 + 大圆点 + 带箭头的数值标签。
        颜色跟随该基频的专属颜色，多基频时一眼可分。"""
        x0, x1 = ax.get_xlim()
        if not (x0 <= self.active_mark_x <= x1):
            if hasattr(self, "_info_text") and self._info_text in self.fig.texts:
                self._info_text.remove()
                self._info_text = None
            return
        c = self._color_for_base(self.active_mark_x)
        ymin, ymax = ax.get_ylim()
        span = (ymax - ymin) or 1.0
        band = max((x1 - x0) * 0.004, 1e-9)
        ax.axvspan(self.active_mark_x - band, self.active_mark_x + band,
                   color=c, alpha=0.10, lw=0, zorder=1)
        yi = None
        if self._cur_f is not None and len(self._cur_f) > 0:
            idx = int(np.argmin(np.abs(self._cur_f - self.active_mark_x)))
            yi = float(self._cur_amp[idx])
        if yi is not None and self.current_plot != "stft":
            ax.vlines(self.active_mark_x, 0, yi, color=c, lw=0.8,
                      alpha=0.55, zorder=2)
        if self.current_plot == "stft":
            label = f"{self.active_mark_x:.1f}Hz"
            ax.text(self.active_mark_x + (x1 - x0) * 0.008, ymin + span * 0.88,
                    label, fontsize=8, color=c, ha="left", va="top", zorder=7,
                    bbox=dict(boxstyle="round,pad=0.2", fc="white", ec=c,
                              lw=0.6, alpha=0.9))
        elif yi is not None:
            ax.plot(self.active_mark_x, yi, "o",
                    ms=(5.0 if self.current_plot == "autocorr" else 7.0),
                    mfc="white", mec=c, mew=1.8, zorder=6)
            if self.current_plot == "autocorr":
                f_imp = 1.0 / self.active_mark_x if self.active_mark_x > 0 else 0.0
                label = f"f={f_imp:.2f}Hz\nτ={self.active_mark_x:.4f}s"
            else:
                label = f"f={self.active_mark_x:.1f}Hz\nA={max(yi, 0.01):.2f}"
            _left_zone = self.active_mark_x < x0 + (x1 - x0) * 0.22
            if _left_zone:
                # 基频靠近左边界时，标签放到数据点右下方，避免与相邻的 1X/倍频标签叠字
                ax.annotate(label, xy=(self.active_mark_x, yi),
                            xytext=(10, -24), textcoords="offset points",
                            fontsize=8.2, color=c, ha="left", va="top", zorder=7,
                            bbox=dict(boxstyle="round,pad=0.22", fc="white", ec=c,
                                      lw=0.7, alpha=0.95),
                            arrowprops=dict(arrowstyle="-", color=c, lw=0.7,
                                            shrinkA=2, shrinkB=4, alpha=0.8))
            else:
                right = self.active_mark_x < x0 + (x1 - x0) * 0.72
                ax.annotate(label, xy=(self.active_mark_x, yi),
                            xytext=(12 if right else -12, 16), textcoords="offset points",
                            fontsize=8.2, color=c,
                            ha="left" if right else "right", va="bottom", zorder=7,
                            bbox=dict(boxstyle="round,pad=0.22", fc="white", ec=c,
                                      lw=0.7, alpha=0.95),
                            arrowprops=dict(arrowstyle="-", color=c, lw=0.7,
                                            shrinkA=2, shrinkB=4, alpha=0.8))
        else:
            label = f"{self.active_mark_x:.1f}Hz"
            ax.text(self.active_mark_x + (x1 - x0) * 0.008, ymin + span * 0.88,
                    label, fontsize=8, color=c, ha="left", va="top", zorder=7,
                    bbox=dict(boxstyle="round,pad=0.2", fc="white", ec=c,
                              lw=0.6, alpha=0.9))
        if hasattr(self, "_info_text") and self._info_text in self.fig.texts:
            self._info_text.remove()
            self._info_text = None

    def _annotation_text_blocks(self):
        """按基频汇总倍频/边带/带宽，返回 [(颜色, 标题, 正文行), ...]。"""
        from collections import defaultdict
        data = defaultdict(lambda: {"harm": {}, "sb": {}, "bw": []})
        for mk in self.manual_marks:
            if len(mk) < 5:
                continue
            try:
                base = float(mk[4])
            except Exception:
                continue
            lab = str(mk[1])
            amp = float(mk[3]) if len(mk) > 3 else 0.01
            if lab.endswith("X") and lab[:-1].isdigit():
                data[base]["harm"][int(lab[:-1])] = (float(mk[0]), amp)
            elif lab.endswith("sb"):
                data[base]["sb"][lab] = (float(mk[0]), amp)
        for reg in self._bandwidth_regions:
            if isinstance(reg, dict):
                data[float(reg["base"])]["bw"].append(reg)
        out = []
        for base in sorted(data):
            d = data[base]
            if not (d["harm"] or d["sb"] or d["bw"]):
                continue
            color = self._base_colors.get(round(base, 2), self.BASE_COLORS[0])
            if d["bw"] and not (d["harm"] or d["sb"]):
                color = "#b8860b"   # 只有带宽的块，标题用深金色与黄色填充呼应
            tags = []
            lines = []
            if d["harm"]:
                tags.append("倍频")   # 行内已列出 1X-10X，标题不再重复，避免被右上角折叠按钮压住
                cells = []
                for k in range(1, 11):
                    if k == 1 and k not in d["harm"]:
                        # 图内 1X 用基频标记表示，面板仍补上 1X 行
                        fx = float(base)
                        amp = self._amp_at(base) or 0.01
                    elif k in d["harm"]:
                        fx, amp = d["harm"][k]
                    else:
                        cells.append(None)
                        continue
                    cells.append(f"{k:>2}X{fx:>8.2f}Hz{amp:>5.2f}")
                half = (len(cells) + 1) // 2
                for i in range(half):
                    left = cells[i] if cells[i] else " " * 20
                    right = cells[i + half] if (i + half < len(cells) and cells[i + half]) else ""
                    lines.append((left + "   " + right).rstrip())
            if d["sb"]:
                bw = self._sideband_params.get(round(base, 2), 0.0)
                tags.append(f"边带 ±3SB({bw:.1f}Hz)")
                for n in range(1, 4):
                    fm = d["sb"].get(f"{-n}sb")
                    fp = d["sb"].get(f"+{n}sb")
                    parts = []
                    if fm:
                        parts.append(f"-{n}SB{fm[0]:>8.2f}Hz{fm[1]:>5.2f}")
                    if fp:
                        parts.append(f"+{n}SB{fp[0]:>8.2f}Hz{fp[1]:>5.2f}")
                    if parts:
                        lines.append("   ".join(parts))
            if d["bw"]:
                step = d["bw"][0]["hi"] - d["bw"][0]["lo"]
                tags.append(f"带宽 {step:.1f}Hz×{len(d['bw'])}")
                for r in d["bw"]:
                    # BWx 标在带内峰值处，面板同步显示峰频率与峰值（两位小数，便于对照谱线）
                    pk = float(r.get("peak", r["hi"]) or r["hi"])
                    lines.append(f"{r['label']:<4}{pk:>8.2f}Hz{r['amp']:>6.2f}")
            header = f"◆ f0={base:.2f}Hz   " + "   ".join(tags)
            out.append((color, header, lines))
        return out

    def _annot_path(self):
        base = self.project_dir or (os.path.dirname(self.csv_path) if self.csv_path else "")
        return os.path.join(base, ANNOT_FILE) if base else ""

    def _point_key(self):
        info = self.info or {}
        return "|".join(str(info.get(k, "") or "") for k in ("project", "unit", "point"))

    def _collect_annotations(self):
        return {
            "manual_marks": [list(m) for m in self.manual_marks],
            "bandwidth_regions": [dict(r) if isinstance(r, dict) else list(r)
                                  for r in getattr(self, "_bandwidth_regions", [])],
            "base_colors": {str(k): v for k, v in getattr(self, "_base_colors", {}).items()},
            "sideband_params": {str(k): v for k, v in getattr(self, "_sideband_params", {}).items()},
            "active_mark_x": self.active_mark_x,
            "single_start_t": self._single_start_t,
            "freq_confirmed": bool(self._freq_confirmed),
        }

    def _schedule_save_annotations(self):
        """重绘后延迟保存，避免缩放/拖动时频繁写 JSON。"""
        try:
            old = getattr(self, "_annot_save_id", None)
            if old:
                self.after_cancel(old)
            self._annot_save_id = self.after(700, self._save_point_annotations)
        except Exception:
            pass

    def _save_point_annotations(self):
        """把当前基频/倍频/边带/带宽写入项目根目录的 vib_annotations.json。"""
        path = self._annot_path(); key = self._point_key()
        if not path or not key.strip("|"):
            return
        try:
            data = {}
            if os.path.exists(path):
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
            if not isinstance(data, dict):
                data = {}
            data.setdefault("points", {})[key] = self._collect_annotations()
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2, default=float)
            os.replace(tmp, path)
        except Exception:
            pass

    def _load_point_annotations(self):
        path = self._annot_path(); key = self._point_key()
        if not path or not os.path.exists(path):
            return
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            rec = (data.get("points") or {}).get(key)
        except Exception:
            return
        if not isinstance(rec, dict):
            return
        marks = []
        for m in rec.get("manual_marks") or []:
            try:
                if len(m) >= 4:
                    marks.append(tuple(m))
            except Exception:
                pass
        self.manual_marks = marks
        regs = []
        for r in rec.get("bandwidth_regions") or []:
            if isinstance(r, dict):
                regs.append(dict(r))
            elif isinstance(r, (list, tuple)) and len(r) >= 3:
                regs.append(tuple(r))
        self._bandwidth_regions = regs
        self._base_colors = {}
        for k, v in (rec.get("base_colors") or {}).items():
            try:
                self._base_colors[round(float(k), 2)] = v
            except Exception:
                pass
        self._sideband_params = {}
        for k, v in (rec.get("sideband_params") or {}).items():
            try:
                self._sideband_params[round(float(k), 2)] = float(v)
            except Exception:
                pass
        self.active_mark_x = rec.get("active_mark_x")
        self._single_start_t = rec.get("single_start_t")
        self._freq_confirmed = bool(rec.get("freq_confirmed", False))

    def _on_pick_panel(self, event):
        if event.artist is getattr(self, "_panel_chip", None):
            self._panel_collapsed = not self._panel_collapsed
            self._redraw_current_plot()

    def _draw_annotation_panel(self, ax):
        """右上角信息卡：按基频分块、左对齐、无边框；带 −/+ 折叠按钮。"""
        blocks = self._annotation_text_blocks()
        if not blocks:
            return
        if self._panel_collapsed:
            chip = TextArea("＋", textprops=dict(color="#2b3d51", fontsize=9, weight="bold"))
            cab = AnnotationBbox(chip, (0.975, 0.965), xycoords=ax.transAxes,
                                 box_alignment=(1, 1), frameon=True,
                                 bboxprops=dict(boxstyle="round,pad=0.25", fc="white",
                                                ec="#93a4b8", lw=0.7),
                                 zorder=10)
            cab.set_picker(5); cab.set_in_layout(False)
            ax.add_artist(cab); self._panel_chip = cab
            return
        boxes = []
        for color, header, lines in blocks:
            h = TextArea(header, textprops=dict(color=color, fontsize=7.8, weight="bold"))
            b = TextArea("\n".join(lines), textprops=dict(color="#2b3d51", fontsize=7.0,
                                                         family="SimSun", linespacing=1.1))
            boxes.append(VPacker(children=[h, b], align="left", pad=0, sep=0))
        pack = VPacker(children=boxes, align="left", pad=0, sep=3)
        ab = AnnotationBbox(pack, (0.972, 0.975), xycoords=ax.transAxes,
                            box_alignment=(1, 1), frameon=False, pad=0, zorder=9)
        # 关键：不参与 tight_layout，否则信息框会把 X 轴挤窄、谱图缩到左半边
        ab.set_in_layout(False)
        ax.add_artist(ab)
        chip = TextArea("－", textprops=dict(color="#2b3d51", fontsize=9, weight="bold"))
        cab = AnnotationBbox(chip, (0.995, 0.968), xycoords=ax.transAxes,
                             box_alignment=(1, 1), frameon=True,
                             bboxprops=dict(boxstyle="round,pad=0.25", fc="white",
                                            ec="#93a4b8", lw=0.7),
                             zorder=10)
        cab.set_picker(5); cab.set_in_layout(False)
        ax.add_artist(cab); self._panel_chip = cab

    def _on_canvas_configure(self, event):
        """画布尺寸变化（拖边框/最大化/改系统缩放）：只记下尺寸并延迟重绘，
        拖动过程中不反复重算，停手后再按新尺寸重画（抽稀、留白、悬浮按钮都跟着变）。"""
        size = (int(getattr(event, "width", 0) or 0), int(getattr(event, "height", 0) or 0))
        if size == getattr(self, "_canvas_size", None):
            return
        self._canvas_size = size
        job = getattr(self, "_resize_job", None)
        if job is not None:
            try:
                self.after_cancel(job)
            except Exception:
                pass
        self._resize_job = self.after(200, self._apply_canvas_resize)

    def _apply_canvas_resize(self):
        self._resize_job = None
        if self.sig is None or not self.current_plot:
            return
        try:
            self._redraw_current_plot()
        except Exception:
            pass

    def _position_chart_tools(self):
        # 悬浮图标条贴在“绘图坐标区上边框线”正上方的顶部预留灰区（标题在画布外，不会与之重叠）。
        # 注意坐标系方向：matplotlib 的 y 从底部向上增大，而 Tk place 的 rely 从顶部向下增大，需做 1-y 翻转。
        try:
            # 取面积最大的坐标区作为主绘图区（瀑布图的 colorbar 轴窄小，借此排除其干扰）
            ax0 = max(self.fig.axes,
                      key=lambda a: a.get_position().width * a.get_position().height)
            pos = ax0.get_position()
        except Exception:
            return
        mpl_top = min(1.0, pos.y1 + 0.005)   # 距 axes 顶线留微小间隙（matplotlib 底起坐标）
        tk_rely = 1.0 - mpl_top              # 换算为 Tk 顶起坐标
        if self._wf3d_active():
            # 3D 图直接贴画布上沿，避免被标题条挤压
            if self.flow_left.winfo_manager():
                self.flow_left.place_configure(relx=0.0, rely=0.0, anchor="nw")
                self.flow_left.lift()
            if self.flow_right.winfo_manager():
                self.flow_right.place_configure(relx=1.0, rely=0.0, anchor="ne")
                self.flow_right.lift()
            return
        if self.flow_left.winfo_manager():
            self.flow_left.place_configure(relx=pos.x0, rely=tk_rely, anchor="sw")
            self.flow_left.lift()
        if self.flow_right.winfo_manager():
            self.flow_right.place_configure(relx=pos.x1, rely=tk_rely, anchor="se")
            self.flow_right.lift()

    def _apply_hann(self, x):
        # 单边幅值谱前按需加汉宁窗，返回(加窗信号, 幅值恢复系数)。
        # 汉宁窗相干增益约 0.5，在既有 2/n 单边归一化上再乘 2 还原峰值；矩形窗(不加窗)系数为 1。
        if self.var_hann.get():
            return x * np.hanning(len(x)), 2.0
        return x, 1.0

    def _get_sig(self):
        if not self.var_bp.get(): return self.sig
        try:
            lo = float(self.var_bp_low.get()); hi = float(self.var_bp_high.get())
            # 设计用真实 Nyquist=fs/2；若再拿 fs/2.56 当 Nyquist，
            # 截止频率会偏大约 1.28 倍，且 hi>=fs/2.56 时 scipy 直接抛错。
            b, a = design_band(self.fs, lo, hi)
            return filtfilt(b, a, self.sig)
        except Exception as e:
            # 出错后自动关掉带通，避免每次重绘（含方向键微调）都弹同一个错误框
            self.var_bp.set(False)
            messagebox.showerror("带通错误", f"{e}\n已临时关闭“应用带通”，按原始信号显示。")
            return self.sig

    def _on_spectrum_close(self):
        # 关闭前保存该测点的标注与窗口大小/位置
        try:
            if getattr(self, "_annot_save_id", None):
                self.after_cancel(self._annot_save_id)
                self._annot_save_id = None
        except Exception:
            pass
        # 取消待执行的“窗口尺寸变化重绘”，避免窗口销毁后回调再触发（控制台报 invalid command name）
        try:
            if getattr(self, "_resize_job", None):
                self.after_cancel(self._resize_job)
                self._resize_job = None
        except Exception:
            pass
        self._save_point_annotations()
        save_window_geom(self)
        # 释放 matplotlib 全局注册表里的 Figure，否则每开一次图谱窗口都会永久占用一份画布内存
        try:
            plt.close(self.fig)
        except Exception:
            pass
        self.destroy()

    def _icon(self, parent, glyph, tip, command, toggle=False,
              btn_style="Icon.TButton", padx=1):
        # 创建一个图标按钮并绑定悬停说明；toggle 按钮的“开/关”视觉由 _set_on 切换 IconFlat(On) 样式
        b = ttk.Button(parent, text=glyph, style=btn_style, command=command)
        b.pack(side="left", padx=padx)
        b._tip_base = tip
        b._is_toggle = bool(toggle)
        b._is_on = False
        self.tip.bind(b, tip)
        if toggle:
            self._set_on(b, False)
        return b

    def _set_on(self, b, on):
        # 开关型图标按钮：开=符号变主蓝(IconFlatOn)，关=常态深色(IconFlat)；两者同底无框、无矩形块，
        # 并同步悬停文字的开/关状态；3D 灰底下自动切到 Dark 版本
        dark = "Dark" if getattr(self, "_dark_icons", False) else ""
        b.configure(style=("IconFlatOn" if on else "IconFlat") + dark + ".TButton")
        b._is_on = bool(on)
        base = getattr(b, "_tip_base", "")
        if base:
            self.tip.set_text(b, "%s（当前：%s）" % (base, "开" if on else "关"))

    def _apply_icon_theme(self, dark):
        """3D 灰底时把悬浮图标条切成同底样式，切回二维再恢复浅色。"""
        self._dark_icons = bool(dark)
        if not hasattr(self, "flow_left"):
            return
        for b in list(self.flow_left.winfo_children()) + list(self.flow_right.winfo_children()):
            if not isinstance(b, ttk.Button):
                continue
            if getattr(b, "_is_toggle", False):
                self._set_on(b, bool(getattr(b, "_is_on", False)))
            else:
                b.configure(style="IconFlatDark.TButton" if dark else "IconFlat.TButton")

    def _fund_icon(self):
        # 基频按钮统一图标：优先用程序目录的 line_icon.png（谱图基频按钮一直用它），
        # 缺图或加载失败时回退到 ƒ₁，保证时域“基频”与包络谱“基频”外观完全一致
        if getattr(self, "_fund_img", None) is None:
            from tkinter import PhotoImage
            _p = os.path.join(APP_DIR, "line_icon.png")
            self._fund_img = ""
            if os.path.exists(_p):
                try:
                    self._fund_img = PhotoImage(file=_p).subsample(3, 3)
                except Exception:
                    self._fund_img = ""
        return self._fund_img or None

    def _fund_button(self, parent, command, tip="基频", toggle=False):
        # 生成与谱图“基频”完全一致的按钮（图片优先，回退 ƒ₁ 文字），并绑定悬停说明
        img = self._fund_icon()
        if img is not None:
            b = ttk.Button(parent, image=img, style="IconFlat.TButton", command=command)
        else:
            b = ttk.Button(parent, text="\u0192\u2081", style="IconFlat.TButton", command=command)
        b.pack(side="left", padx=4)
        b._tip_base = tip
        b._is_toggle = bool(toggle)
        b._is_on = False
        self.tip.bind(b, tip)
        if toggle:
            self._set_on(b, False)
        return b

    def _toggle_lock(self):
        if self._wf3d_active():   # 3D 视图不锁定坐标轴
            return
        self._set_locked(not self.axis_locked)

    def _set_locked(self, on, redraw=False):
        """锁定/解锁视图。锁定时把当前 X/Y 轴范围记下来，之后每次重绘都会强制回写，
        并关闭框选、基频定位、基频起点选点、时间点标注等鼠标交互；
        键盘方向键仍可微调基频标记（只动标记、不动坐标轴），保证锁定后还能逐峰找频率。"""
        on = bool(on)
        if on == self.axis_locked and (on or self._locked_xlim is None):
            return
        self.axis_locked = on
        if on:
            ax = self.fig.gca()
            try:
                self._locked_xlim = tuple(ax.get_xlim())
                self._locked_ylim = tuple(ax.get_ylim())
            except Exception:
                self._locked_xlim = self._locked_ylim = None
            # 锁定时收起所有交互态：选择器销毁，各类“点击模式”全部关闭，
            # 避免锁住后仍有隐藏的鼠标模式把基频标记挪走
            self.refine_on = False
            self.annotate_mode = False
            self.single_line_on = False
            self.mark_time_on = False
            self._destroy_selector()
            for _b in (self.btn_refine, self.btn_annotate, self.btn_single):
                try:
                    self._set_on(_b, False)
                except Exception:
                    pass
        else:
            self._locked_xlim = self._locked_ylim = None
        try:
            self.btn_lock.configure(text="\U0001F512" if on else "\U0001F513")
        except Exception:
            pass
        self._set_on(self.btn_lock, on)
        if redraw:
            self._redraw_current_plot()

    def _safe(self, name, fn):
        if self.sig is None:
            p = filedialog.askopenfilename(initialdir=self.last_dir, filetypes=[("CSV", "*.csv")])
            if not p: return
            self.load_file(p)
            if self.sig is None:      # 加载失败或用户取消了采样率输入：不再继续画空图
                return
        # 同一测点换谱图时，时域起点/周期标注不能被重置
        _keep_time = (self._single_start_t,
                      bool(getattr(self, "_freq_confirmed", False)),
                      bool(getattr(self, "_period_from_autocorr", False)))
        _prev_plot = self.current_plot
        self.current_plot = name
        # 换谱图类型后原锁定范围无意义，先解锁；瀑布图/自相关保持可交互（不自动锁定）
        if self.axis_locked:
            self._set_locked(False)
        self._auto_lock_pending = True
        if self.refine_range is not None and _prev_plot:
            self._refine_saved[_prev_plot] = self.refine_range
        self.refine_range = self._refine_saved.get(name)
        self.refine_on = self.refine_range is not None
        self._set_on(self.btn_refine, self.refine_on)
        self._destroy_selector()
        # 同一测点切换谱图时保留标注；只有 load_file 打开新文件/测点时才清空
        self.annotate_mode = False
        self._set_on(self.btn_annotate, False)
        # 左上角悬浮条按谱类型显隐：基频/频率仅时域，峰值各谱通用，基频/倍频/边带/带宽仅频域类
        _all_left = (self.btn_single, self.btn_freq, self.btn_annotate,
                     self.btn_harm, self.btn_side, self.btn_bw, self.btn_peak)
        for btn in _all_left:
            btn.pack_forget()
        if name == "time":
            self.btn_single.pack(side="left", padx=4)
            self.btn_freq.pack(side="left", padx=4)
        elif name == "stft":
            # 瀑布图：锁定后仍可用“基频”选主频、方向键微调，Shift+滚轮细化
            for btn in (self.btn_annotate, self.btn_peak):
                btn.pack(side="left", padx=4)
        elif name == "autocorr":
            # 自相关：用“基频”按钮选周期，之后方向键/Shift+方向微调，Shift+滚轮细化
            for btn in (self.btn_annotate, self.btn_peak):
                btn.pack(side="left", padx=4)
        elif name in ("fft", "envelope", "order", "velocity"):
            for btn in (self.btn_annotate, self.btn_harm, self.btn_side, self.btn_bw, self.btn_peak):
                btn.pack(side="left", padx=4)
        elif name == "cepstrum":
            for btn in (self.btn_annotate, self.btn_harm, self.btn_peak):
                btn.pack(side="left", padx=4)
        # autocorr 无任何左浮按钮：有可见项则贴画布左上角顶部显示，否则整条隐藏
        if any(b.winfo_manager() for b in _all_left):
            self.flow_left.place(relx=0.0, rely=0.0, anchor="nw")
            self.flow_left.lift()
        else:
            self.flow_left.place_forget()
        # 防御：清除悬浮工具条按钮可能残留的 disabled 态，保证当前谱可用功能始终可点击
        # （阶次“#”按钮在顶部 bar2、不在此容器，其按转速置灰的逻辑不受影响）
        for _b in list(self.flow_left.winfo_children()) + list(self.flow_right.winfo_children()):
            try:
                _b.state(["!disabled"])
            except Exception:
                pass
        self._single_start_t, self._freq_confirmed, self._period_from_autocorr = _keep_time
        fn()

    def pick_csv(self):
        p = filedialog.askopenfilename(initialdir=self.last_dir, filetypes=[("CSV", "*.csv")])
        if p: self.load_file(p)

    def _refresh_plot_availability(self):
        # 阶次谱依赖转频（转速/60）：当前数据无有效转速时把“#”置灰不可点（从源头避免无转频弹窗），
        # 切到有转速的数据时自动恢复可用
        try:
            speed = float(self.info.get("speed") or 0) if self.info else 0.0
        except (TypeError, ValueError):
            speed = 0.0
        self.btn_order.state(["!disabled"] if speed > 0 else ["disabled"])

    def _clear_loaded_data(self, why=""):
        """打开失败时清掉当前数据，避免窗口继续显示上一个文件的曲线（看起来像新文件已加载）。"""
        self.sig = None
        self.csv_path = None
        try:
            self.chart_title.config(text=why or "未加载数据")
        except Exception:
            pass
        try:
            self.fig.clear()
            self.canvas.draw()
        except Exception:
            pass

    def load_file(self, path):
        self.csv_path = path; self.last_dir = os.path.dirname(path)
        self.lbl.config(text=path); self.info = parse_filename(os.path.basename(path))
        self.fs = self.info["fs"]
        self._rot_hz = None          # 换文件：回到“按文件名转速”，没有就等用户给
        self._bearing_marks = []     # 换文件：清掉上一份数据的轴承标注
        self._gear_marks = []        # 换文件：清掉齿轮啮合/边带标注
        if not (self.info.get("speed") or 0):
            # 文件名没转速时，用表格里“设置转速”写下的同目录 sidecar
            try:
                _ov = speed_sidecar_load(path)
                _rpm = _ov.get(os.path.basename(path))
                if _rpm and float(_rpm) > 0:
                    self.info["speed"] = int(round(float(_rpm)))
            except Exception:
                pass
        if not self.fs:
            # 文件名不符合命名规范、解析不到采样率时，允许手动输入 fs，支持任意 CSV 独立分析
            fs_in = simpledialog.askfloat(
                "采样率",
                f"文件名未包含采样率，请输入该CSV的采样频率(Hz)：\n{os.path.basename(path)}",
                parent=self, minvalue=1.0)
            if not fs_in:
                self._clear_loaded_data("未加载数据（已取消输入采样率）")
                return  # 用户取消
            self.info["fs"] = float(fs_in)
            self.info.setdefault("project", ""); self.info.setdefault("unit", "")
            self.info.setdefault("point", ""); self.info.setdefault("speed", None)
            self.info.setdefault("dt", None)
            self.fs = float(fs_in)
        try:
            self.sig = pd.read_csv(path, header=None).iloc[:, 0]
            self.sig = pd.to_numeric(self.sig, errors="coerce").dropna().values.astype(float)
        except Exception as e:
            messagebox.showerror("读文件错误", str(e))
            self._clear_loaded_data("未加载数据（文件读取失败）")
            return
        if len(self.sig) < 1024: messagebox.showerror("错误", "数据点太少")
        pt = self.info["point"]
        if pt in rule_dict:
            self.var_bp_low.set(str(rule_dict[pt]["f_low"]))
            self.var_bp_high.set(str(rule_dict[pt]["f_high"]))
        # 命中默认滤波表：按该测点范围自动勾选“应用带通”，时域与各谱图默认看滤波后信号
        if pt in default_bp:
            bp_lo, bp_hi = default_bp[pt]
            self.var_bp_low.set(str(bp_lo)); self.var_bp_high.set(str(bp_hi))
            self.var_bp.set(True)
        else:
            self.var_bp.set(False)
        if "发电机" in pt: self.var_env_low.set("0"); self.var_env_high.set("5000")
        elif "齿轮箱" in pt: self.var_env_low.set("0"); self.var_env_high.set("2000")
        elif "主轴承" in pt: self.var_env_low.set("0"); self.var_env_high.set("150")
        elif "主轴" in pt: self.var_env_low.set("0"); self.var_env_high.set("100")
        self.refine_range = None; self.refine_on = False
        self._refine_saved.clear()
        self._set_on(self.btn_refine, False)
        self._destroy_selector()
        # 换文件后坐标范围完全不同，先解除视图锁定
        if self.axis_locked:
            self._set_locked(False)
        self.manual_marks = []
        self.active_mark_x = None
        self._xmax_override = None
        self._harmonics_text = None
        self._sidebands_text = None
        self._bandwidth_text = None
        self._bandwidth_regions = []
        self._base_colors = {}
        self._sideband_params = {}
        self.annotate_mode = False
        # 新文件：清掉自相关/瀑布缓存、基频起点/频率确认与“来自自相关”的联动标记、旧文件的时间点
        self._ac_cache = None
        self._wf_cache = None
        self._spectrum_cache = {}
        self._wf_cache_key = None
        self._wf_3d = False
        self._single_start_t = None
        self._freq_confirmed = False
        self._period_from_autocorr = False
        self._autocorr_zoom_pending = False
        self._manual_marks_time = []
        # 按本次数据是否含有效转速，启用/置灰阶次谱等依赖转频的功能
        self._refresh_plot_availability()
        # 新文件：清空撤销栈，并恢复该测点上次保存的标注
        self._undo_stack.clear()
        self._load_point_annotations()
        # 新数据画完后自动锁定坐标轴（默认锁定）
        self._auto_lock_pending = True
        # 府谷项目：按测点自动标注轴承特征频率（其它项目为空）
        self._apply_auto_bearing_marks()
        # 重绘当前图
        self._redraw_current_plot()

    def _fresh_ax(self, title):
        self.fig.clear(); ax = self.fig.add_subplot(111)
        # 从 3D 瀑布切回二维谱图时，把标题条/工具条的灰底恢复成浅色
        self.chart_title.configure(style="ChartTitle.TLabel")
        self.flow_left.configure(style="ChartTool.TFrame")
        self.flow_right.configure(style="ChartTool.TFrame")
        self._apply_icon_theme(False)
        # figure 外围浅色（与标题条/图标条一致）；axes 绘图面用调暗灰底，降低纯白刺眼感
        self.fig.patch.set_facecolor(UI_BG)
        ax.set_facecolor(CHART_BG)
        # 恢复绘图区矩形边框：四条 spine 显示为中灰，刻度短线与坐标标签保留
        for _sp in ax.spines.values():
            _sp.set_visible(True)
            _sp.set_color("#848f9d")
            _sp.set_linewidth(0.9)
        ax.tick_params(axis="both", which="major", length=4, width=0.8, colors=UI_TXT)
        # 所有谱图统一主网格：白色半透明细线，在调暗的灰底上柔和可读；瀑布图/色标上同样可辨
        ax.grid(True, which="major", color="#ffffff", linewidth=0.6, alpha=0.55)
        ax.set_axisbelow(True)
        # 第二行：采集时间+转频
        info = self.info
        proj = info.get("project", "")
        unit = info.get("unit", "")
        point = info.get("point", "")
        dt = info.get("dt")
        dt_str = dt.strftime("%Y/%m/%d %H:%M:%S") if dt else ""
        speed = info.get("speed", 0)
        f_rot = speed / 60.0 if speed else 0
        line1 = f"{title}-{proj}-{unit}{point}"
        line2 = f"采集时间：{dt_str}  转速：{speed}rpm  转频：{f_rot:.2f}Hz" if speed else f"采集时间：{dt_str}"
        # 标题放到画布外独立条带，避免与悬浮图标重叠
        self.chart_title.config(text=f"{line1}\n{line2}")
        return ax

    def _toggle_mark_time(self):
        self.mark_time_on = not self.mark_time_on
        _b = getattr(self, "btn_mark_time", None)  # 该按钮当前无 UI 入口，存在才更新，避免属性错误
        if _b is not None:
            _b.config(text=f"手动标注:{'开' if self.mark_time_on else '关'}")

    def _toggle_single_line(self):
        self._single_relock = self.axis_locked
        if self.axis_locked:
            self._set_locked(False)
        self.single_line_on = not self.single_line_on
        self._set_on(self.btn_single, self.single_line_on)
        if self.single_line_on:
            self._single_start_t = None
        elif getattr(self, "_single_relock", False):
            # 取消取点：回到锁定态
            self._set_locked(True)

    def _fund_freq(self):
        # 基频频率（Hz）；非法输入按 0 处理，调用方据此判断是否已设定
        try:
            v = float(self.var_single_freq.get())
        except (TypeError, ValueError):
            return 0.0
        return v if v > 0 else 0.0

    def _fund_period(self):
        # 由基频频率换算周期（时间轴单位 s）：T = 1/f
        f = self._fund_freq()
        return 1.0 / f if f > 0 else 0.0

    def _onclick_single_line(self, event):
        if self.axis_locked: return
        if not getattr(self, "single_line_on", False) or event.inaxes is None: return
        if event.button != 1 or event.xdata is None: return
        self._single_start_t = self._snap_time_to_peak(event.xdata)
        self.single_line_on = False
        self._freq_confirmed = False
        self._set_on(self.btn_single, False)
        if getattr(self, "_single_relock", False):
            self._auto_lock_pending = True
        self._redraw_current_plot()

    def _on_press_period(self, event):
        """时域：在基频起点竖线附近按下，进入拖动周期标注状态。"""
        if self.current_plot != "time" or self._single_start_t is None:
            return
        if event.button != 1 or event.inaxes is None or event.xdata is None:
            return
        try:
            ax = self.fig.gca()
            px = float(ax.transData.transform((event.xdata, 0.0))[0])
            sx = float(ax.transData.transform((self._single_start_t, 0.0))[0])
        except Exception:
            return
        if abs(px - sx) <= 12:
            self._drag_period = True

    def _on_motion_period(self, event):
        if not getattr(self, "_drag_period", False):
            return
        if event.inaxes is None or event.xdata is None:
            return
        self._single_start_t = max(0.0, self._snap_time_to_peak(float(event.xdata)))
        self._redraw_current_plot()

    def _snap_time_to_peak(self, x):
        """把时间 x 吸附到附近 ±10 像素内幅值最大的样点（自动找峰）。"""
        t = getattr(self, "_snap_t", None)
        sig = getattr(self, "_snap_sig", None)
        if t is None or sig is None or len(t) < 3:
            return x
        try:
            ax = self.fig.gca()
            x0, x1 = ax.get_xlim()
            wpx = max(float(ax.bbox.width), 1.0)
            win = abs(float(x1) - float(x0)) * 10.0 / wpx
        except Exception:
            win = 0.01
        win = max(win, 1e-9)
        i0 = int(np.searchsorted(t, x - win))
        i1 = int(np.searchsorted(t, x + win))
        if i1 - i0 < 3:
            return x
        seg = np.abs(sig[i0:i1])
        return float(t[i0 + int(np.argmax(seg))])

    def _on_release_period(self, event):
        self._drag_period = False

    def _place_autocorr_base(self):
        """自相关“基频”按钮：把标记放到转频周期（无转速时放视窗中心），不依赖鼠标点图。"""
        tau = self._cur_f
        ac = self._cur_amp
        if tau is None or ac is None or len(tau) < 4:
            return
        tau = np.asarray(tau, dtype=float)
        ac = np.asarray(ac, dtype=float)
        speed = (self.info or {}).get("speed", 0) or 0
        target = (60.0 / speed) if speed else float((tau[0] + tau[-1]) / 2.0)
        target = min(max(target, float(tau[0])), float(tau[-1]))
        # 直接落在转频对应的谱线上（不额外找峰），之后 Shift+方向键再自动吸附峰
        i = int(np.argmin(np.abs(tau - target)))
        self._push_undo()
        self.active_mark_x = float(tau[i])
        self._active_f0_color = self._color_for_base(self.active_mark_x)
        self._sync_freq_from_tau(self.active_mark_x)
        self._set_on(self.btn_annotate, True)
        self._redraw_current_plot()

    def _sync_freq_from_tau(self, tau_sel=None):
        """把自相关选中的周期同步为基频频率（f=1/τ），并给时域补一个 0 起点，
        保证切到时域就能看到按该频率标注的周期线。"""
        tau_sel = self.active_mark_x if tau_sel is None else tau_sel
        if not tau_sel or not np.isfinite(tau_sel) or tau_sel <= 0:
            return
        self.var_single_freq.set(f"{1.0 / tau_sel:.6g}")
        self._freq_confirmed = True
        self._period_from_autocorr = True
        self._autocorr_zoom_pending = True
        if self._single_start_t is None:
            self._single_start_t = 0.0

    def _popup_freq(self):
        # 时域“频率”：设定基频频率（Hz），标记按 1/f 的周期重复
        if self._single_start_t is None:
            messagebox.showinfo("提示", "请先点“基频”按钮，在时域图上选一个起点")
            return
        self._push_undo()
        cur_hz = self._fund_freq() or 28.9
        freq = simpledialog.askfloat(
            "基频频率", "请输入基频频率（Hz）：",
            initialvalue=cur_hz, minvalue=0.001, parent=self)
        if freq and freq > 0:
            self.var_single_freq.set(f"{freq:g}")
            self._freq_confirmed = True
            self._redraw_current_plot()

    def _onclick_mark_time(self, event):
        if self.axis_locked: return
        if not getattr(self, "mark_time_on", False) or event.inaxes is None: return
        if event.button != 1: return
        if event.xdata is None: return
        self._manual_marks_time.append(round(event.xdata, 3))
        self._redraw_current_plot()

    def plot_time(self):
        sig = self._get_sig()
        ax = self._fresh_ax("时域波形")
        t = np.arange(len(sig)) / self.fs
        # 拖动周期起点时用它自动吸附到附近的峰
        self._snap_t = t
        self._snap_sig = np.asarray(sig, dtype=float)
        # 细化：截断数据
        if self.refine_range is not None:
            r0, r1 = self.refine_range
            mask = (t >= r0) & (t <= r1)
            t_plot = t[mask]; sig_plot = sig[mask]
        else:
            t_plot = t; sig_plot = sig
        ax.plot(*self._decimate_xy(t_plot, sig_plot), lw=0.5)
        ax.axhline(0, color="black", lw=0.8)
        # 纵轴按“当前显示段”的峰值取：细化后若仍用整段信号的峰值，局部波形会被压扁
        _peak_abs = max(abs(float(np.min(sig_plot))), abs(float(np.max(sig_plot)))) if len(sig_plot) else 0.0
        m = (_peak_abs or 1.0) * 1.1
        ax.set_ylim(-m, m); ax.set_xlabel("时间(s)"); ax.set_ylabel("Acceleration (m/s$^2$)")
        # 时域左右不留自动留白：坐标轴正好是 0 ~ 记录末尾，波形铺满整个绘图区
        # （细化时由 _post_draw 按细化区间加 5% 边距，不在此处覆盖）
        if self.refine_range is None and len(t) > 1:
            ax.set_xlim(0.0, float(t[-1]))
            # 自相关选好周期后首次切到时域：把视图收到 5 个周期，
            # 否则 8ms 这类短周期的标注线会全挤在最左边看不见（只自动做一次）
            if (getattr(self, "_autocorr_zoom_pending", False)
                    and getattr(self, "_freq_confirmed", False)
                    and self._single_start_t is not None):
                _f = self._fund_freq()
                _T = 1.0 / _f if _f > 0 else 0.0
                if _T > 0:
                    _t0 = float(self._single_start_t)
                    _lo = max(0.0, _t0 - 0.5 * _T)
                    _hi = min(float(t[-1]), _lo + 5.5 * _T)
                    if _hi - _lo >= 2.0 * _T:
                        ax.set_xlim(_lo, _hi)
                        self._autocorr_zoom_pending = False
        # 手动标注的时间点
        for mt in ([] if self.marks_hidden else self._manual_marks_time):
            ax.axvline(mt, color="green", ls=":", lw=1.5)
            ax.text(mt, -m*0.9, f"{mt:.2f}s", color="green", fontsize=8, ha="center")
        # 基频标记：起点竖线 + 按基频周期（1/f）重复的标记线/填充，用于目视核对整周期
        if self._single_start_t is not None and not self.marks_hidden:
            t0 = float(self._single_start_t)
            f_hz = self._fund_freq()
            T = 1.0 / f_hz if f_hz > 0 else 0.0
            confirmed = bool(getattr(self, "_freq_confirmed", False)) and T > 0
            ax.axvline(t0, color="#2f66a3", ls="--", lw=1.4, alpha=0.9, zorder=4)
            # 起点处空心红圈：与频域标识保持同一视觉语言
            if t[0] <= t0 <= t[-1]:
                try:
                    i0s = int(np.argmin(np.abs(t - t0)))
                    ax.plot(t0, float(sig[i0s]), "o", ms=self.RING_MS, mfc="white",
                            mec="red", mew=self.RING_MEW, zorder=6)
                except Exception:
                    pass
            label = f"f={f_hz:.2f}Hz" if confirmed else "基频起点（待设频率）"
            if not confirmed:
                ax.annotate(label, xy=(t0, m * 0.90), xytext=(8, 0), textcoords="offset points",
                            color="#1d4e89", fontsize=9, ha="left", va="center", zorder=7,
                            annotation_clip=True,
                            bbox=dict(boxstyle="round,pad=0.24", fc="white", ec="#2f66a3", alpha=0.94, lw=0.8),
                            arrowprops=dict(arrowstyle="-", color="#2f66a3", lw=0.7, shrinkA=0, shrinkB=2))
            if confirmed:
                t_end = float(t[-1])
                for k in range(1, 6):
                    tk = t0 + k * T
                    lo, hi = t0 + (k - 1) * T, tk
                    if hi < t[0] or lo > t_end * 1.001:
                        continue  # 细化到窗口外时整段跳过，避免文字/填充跑到图外
                    # 每个周期与带宽同款：黄色填充 + 深琥珀色斜线
                    ax.axvspan(max(lo, t[0]), min(hi, t_end), facecolor=self.BW_COLOR,
                               alpha=0.28, hatch="///", edgecolor="#8a5a00",
                               linewidth=0.6, zorder=0)
                    # 周期分界：深琥珀色虚线，一直延伸到图顶
                    ax.axvline(hi, color="#8a5a00", ls=(0, (4, 3)), lw=1.0,
                               alpha=0.9, zorder=1)
                    # 每个周期分界（1T/2T…）也在波形上画空心红圈
                    if t[0] <= hi <= t_end:
                        try:
                            ih = int(np.argmin(np.abs(t - hi)))
                            ax.plot(hi, float(sig[ih]), "o", ms=self.RING_MS,
                                    mfc="white", mec="red", mew=self.RING_MEW, zorder=6)
                        except Exception:
                            pass
                ax.plot(t0, m * 1.0, marker="^", color="#2f66a3", markersize=8, zorder=5)
                ax.plot(t0 + T, m * 1.0, marker="v", color="#8a5a00", markersize=8, zorder=5)
                t_end = float(t[-1])
                # 右上角只显示第 1 个周期：开始/结束/间隔/频率（无边框）
                hi1 = min(t0 + T, t_end)
                txt = (f"1T  开始 {t0:.3f}s  结束 {hi1:.3f}s  "
                       f"间隔 {T:.4f}s  频率 {f_hz:.2f}Hz")
                ax.text(0.985, 0.975, txt, transform=ax.transAxes,
                        ha="right", va="top", zorder=8, clip_on=False,
                        fontsize=7.6, family="SimSun", color="#2b3d51")
        self._post_draw()

    def plot_autocorr(self):
        # 主线程先取信号（带通设置、滤波器异常提示都在主线程处理），工作线程只做纯计算，
        # 避免在工作线程里调用 Tk；并用序号丢弃过期结果（换谱图/重复点击时不会把旧结果画上去）
        try:
            sig = np.asarray(self._get_sig(), dtype=float)
            fs = float(self.fs)
        except Exception as e:
            messagebox.showerror("自相关错误", str(e)); return
        self._autocorr_seq = getattr(self, "_autocorr_seq", 0) + 1
        seq = self._autocorr_seq
        self._ac_key_req = self._signal_key()  # 记录本次计算所用的信号指纹
        self._ac_result = None
        self._ac_error = None

        def calc_task():
            # 工作线程只做纯计算、不碰任何 Tk 接口；结果由主线程轮询取回
            try:
                with self.plot_lock:
                    if AUTOCORR_DOWNSAMPLE_FS is None:
                        sig_down = sig; fs_down = fs
                    else:
                        n_down = max(2, int(len(sig) * AUTOCORR_DOWNSAMPLE_FS / fs))
                        sig_down = resample(sig, n_down); fs_down = AUTOCORR_DOWNSAMPLE_FS
                    max_lag = max(1, int(AUTOCORR_MAX_TAU * fs_down))
                    ac = autocorr_fft(sig_down, max_lag)
                    tau = np.arange(len(ac)) / fs_down
                    # 去掉τ=0处的恒值尖峰（自相关系数恒为1，无诊断意义）
                    mask0 = tau > 0.001
                    ac = ac[mask0]; tau = tau[mask0]
                    # 细化只影响显示：计算始终基于全量 τ，缓存后由 draw 阶段裁剪
                    self._ac_result = (seq, tau, ac)
            except Exception:
                import traceback
                self._ac_error = (seq, traceback.format_exc()[:500])
        threading.Thread(target=calc_task, daemon=True).start()
        self.after(50, lambda: self._poll_autocorr(seq, 0))

    def _poll_autocorr(self, seq, tries):
        """主线程轮询自相关结果：线程不直接调用 Tk，避免跨线程报错/丢结果。"""
        try:
            if not self.winfo_exists():
                return
        except Exception:
            return
        if seq != getattr(self, "_autocorr_seq", None):
            return
        res = getattr(self, "_ac_result", None)
        if res is not None and res[0] == seq:
            if self.current_plot == "autocorr":
                self.draw_autocorr_result(res[1], res[2], "自相关函数", seq)
            return
        err = getattr(self, "_ac_error", None)
        if err is not None and err[0] == seq:
            messagebox.showerror("自相关错误", err[1])
            return
        if tries < 600:  # 最多等约 30s，之后放弃（换图/关闭窗口时序号会变，自动失效）
            self.after(50, lambda: self._poll_autocorr(seq, tries + 1))

    def draw_autocorr_result(self, tau_all, ac_all, title, seq=None):
        # 过期结果（期间换了谱图或重新点了自相关）直接丢弃，避免把旧曲线画到新图上
        if seq is not None and seq != getattr(self, "_autocorr_seq", None):
            return
        if self.current_plot != "autocorr":
            return
        tau_all = np.asarray(tau_all, dtype=float)
        ac_all = np.asarray(ac_all, dtype=float)
        self._ac_cache = (tau_all, ac_all)
        self._ac_cache_key = getattr(self, "_ac_key_req", None)
        # 细化只是视图裁剪，缓存的始终是全量数据，来回细化不丢点
        if self.refine_range is not None:
            t_start, t_end = self.refine_range
            mask_t = (tau_all >= t_start) & (tau_all <= t_end)
            tau_view, ac_view = tau_all[mask_t], ac_all[mask_t]
        else:
            tau_view, ac_view = tau_all, ac_all
        if len(tau_view) < 5:
            tau_view, ac_view = tau_all, ac_all
        ax = self._fresh_ax(title)
        ax.plot(tau_view, ac_view, lw=0.7)
        ax.axhline(0, c="k", lw=0.6)
        ax.format_coord = lambda x, y: ""  # 不显示鼠标坐标
        if len(tau_view) > 20:
            # 先在转频位置标峰（不管有没有明显峰值）
            speed = self.info.get("speed", 0)
            rot_t = None  # 记录已标注的转频峰延迟，供自动找峰去重
            if speed and speed > 0:
                f_rot = speed / 60.0
                tau_rot = 1.0 / f_rot
                if tau_view[0] <= tau_rot <= tau_view[-1]:
                    idx = int(np.argmin(np.abs(tau_view - tau_rot)))
                    # 抛物线插值
                    if 0 < idx < len(ac_view)-1:
                        y0, y1, y2 = ac_view[idx-1], ac_view[idx], ac_view[idx+1]
                        denom = (y0 + y2 - 2*y1)
                        delta = 0.5*(y0 - y2)/denom if abs(denom) > 1e-10 else 0
                        delta = max(-0.5, min(0.5, delta))
                        t_val = tau_view[idx] + delta * (tau_view[1] - tau_view[0])
                    else:
                        t_val = tau_view[idx]
                    rot_t = t_val
                    ac_val = ac_view[idx]; f_imp = 1.0 / t_val
                    ax.plot(t_val, ac_val, "ro", ms=4, mfc="white", mec="red", mew=1.5, zorder=5)
                    ax.annotate(f"转频 {f_imp:.1f}Hz", xy=(t_val, ac_val),
                                xytext=(t_val, ac_val + 0.07),
                                fontsize=8.5, color="#c00000", ha="center", fontweight="bold")
            # 转频峰与当前活动标记也要占位，其它峰的文字不能压到它们上面
            occupied_px = []
            for _x in (rot_t, self.active_mark_x):
                if _x is None:
                    continue
                try:
                    occupied_px.append(float(ax.transData.transform((_x, 0.0))[0]))
                except Exception:
                    pass
            # 再找其他峰：只认“高于 0.10 且足够突出”的峰，
            # 否则近零延迟处的衰减纹波会被误当成周期（旧版会把 0.055 的噪声标成频率）
            peaks_idx, _ = find_peaks(
                ac_view,
                height=0.10,
                prominence=max(0.04, float(np.max(np.abs(ac_view))) * 0.05))
            valid = [i for i in peaks_idx if tau_view[i] > 0.005]
            if valid:
                valid = np.array(valid)
                order = np.argsort(ac_view[valid])[::-1]
                chosen = []
                chosen_px = list(occupied_px)
                for oi in order:
                    i = valid[oi]
                    # 与理论转频峰保持间隔，避免同一周期峰重复标注
                    if rot_t is not None and abs(tau_view[i] - rot_t) < 0.005:
                        continue
                    # 每个标注都要与“所有已选/已占位标注”至少隔 60 像素，否则文字会叠在一起
                    try:
                        px = float(ax.transData.transform((tau_view[i], 0.0))[0])
                    except Exception:
                        px = None
                    if px is not None and any(abs(px - q) < 60 for q in chosen_px):
                        continue
                    chosen.append(i)
                    if px is not None:
                        chosen_px.append(px)
                    if len(chosen) >= 4: break
                top = sorted(chosen, key=lambda i: tau_view[i])
                for pi in top:
                    # 抛物线插值提高峰位置精度
                    if 0 < pi < len(ac_view)-1:
                        y0, y1, y2 = ac_view[pi-1], ac_view[pi], ac_view[pi+1]
                        denom = (y0 + y2 - 2*y1)
                        delta = 0.5*(y0 - y2)/denom if abs(denom) > 1e-10 else 0
                        delta = max(-0.5, min(0.5, delta))
                        t_val = tau_view[pi] + delta * (tau_view[1] - tau_view[0])
                    else:
                        t_val = tau_view[pi]
                    ac_val = ac_view[pi]; f_imp = 1.0 / t_val
                    ax.plot(t_val, ac_val, "ro", ms=3, mfc="white", mec="red", mew=1.2)
                    ax.annotate(f"{f_imp:.1f}Hz", xy=(t_val, ac_val),
                                xytext=(t_val, ac_val + 0.08),
                                fontsize=8, color="#c00000", ha="center",
                                arrowprops=dict(arrowstyle="-", color="red", lw=0.5))
        # 与基频联动：已设过基频（时域设置或自相关点选）时，把对应周期也标出来
        if (self.active_mark_x is None and getattr(self, "_freq_confirmed", False)
                and self._fund_freq() > 0):
            t_sel = 1.0 / self._fund_freq()
            if tau_view[0] <= t_sel <= tau_view[-1]:
                ax.axvline(t_sel, color="#0f7b7d", ls="--", lw=1.3, zorder=4)
                ax.annotate(f"f={self._fund_freq():.2f}Hz\nτ={t_sel:.4f}s",
                            xy=(t_sel, 0.92), xytext=(6, 0), textcoords="offset points",
                            fontsize=8.5, color="#0f7b7d", ha="left", va="top", zorder=6,
                            bbox=dict(boxstyle="round,pad=0.2", fc="white",
                                      ec="#0f7b7d", lw=0.7, alpha=0.92))
        ax.set_xlabel("延迟 τ (s)"); ax.set_ylabel("归一化自相关系数")
        ax.set_ylim(-1.05, 1.05)
        # 自相关也登记当前曲线数据：方向键按视窗自适应步长在 τ 轴上找峰，
        # 缩小按钮的边界也不再回退到 fs/2.56（登记全量数据，细化后仍可整体缩放）
        self._cur_f = tau_all
        self._cur_amp = ac_all
        self._post_draw()

    def _view_for(self, x0, x1):
        """本次绘制的精细显示范围：细化区间优先于传入的默认范围；
        锁定区间与倍频扩边一并并进来，保证曲线不会在坐标区边缘被截断。"""
        v0, v1 = float(x0), float(x1)
        if self.refine_range is not None:
            v0, v1 = float(self.refine_range[0]), float(self.refine_range[1])
        if self._xmax_override is not None:
            v1 = max(v1, float(self._xmax_override))
        if self.axis_locked and self._locked_xlim is not None:
            v0 = min(v0, float(self._locked_xlim[0]))
            v1 = max(v1, float(self._locked_xlim[1]))
        if v1 < v0:
            v0, v1 = v1, v0
        return v0, v1

    def _fft_view(self, nyq):
        """FFT/速度谱的默认显示范围：带通打开时只显示该频段，否则 0~有效分析上限。"""
        v0, v1 = 0.0, float(nyq)
        if self.var_bp.get():
            try:
                lo = max(0.0, float(self.var_bp_low.get()))
                hi = float(self.var_bp_high.get())
                if hi > lo:
                    v0, v1 = lo, min(hi, float(nyq))
            except (TypeError, ValueError):
                pass
        return self._view_for(v0, v1)

    def _decimate_xy(self, x, y, view=None):
        """按像素列做 min/max 抽稀：只保留“当前显示范围”内的细节，放大后抽稀自然变细。
        view=(x0,x1) 为本次显示范围；范围外仍保留少量点，缩小/还原时曲线不会断头。"""
        x = np.asarray(x, dtype=float)
        y = np.asarray(y, dtype=float)
        n = len(x)
        if n <= 2:
            return x, y
        try:
            wpx = max(400.0, float(self.fig.get_figwidth() * self.fig.dpi) * 0.9)
        except Exception:
            wpx = 1000.0
        max_points = int(max(1200, wpx * 2))
        if view is not None:
            v0, v1 = view
            if v1 > v0:
                pad = (v1 - v0) * 0.06   # 比 _post_draw 的 5% 边距再宽一点，边缘不留缝
                lo = max(v0 - pad, float(x[0]))
                hi = min(v1 + pad, float(x[-1]))
                # 只有确实能裁掉一段（显示范围比数据窄）时才裁剪，避免把整条谱裁没
                if hi > lo and (lo > x[0] or hi < x[-1]):
                    m = (x >= lo) & (x <= hi)
                    n_in = int(np.count_nonzero(m))
                    if 0 < n_in < n:
                        x = x[m]; y = y[m]; n = n_in
        if n <= max_points:
            return x, y
        bins = max(1, max_points // 2)
        edges = np.linspace(0, n, bins + 1).astype(int)
        xs, ys = [], []
        for a, b in zip(edges[:-1], edges[1:]):
            if b <= a:
                continue
            seg = y[a:b]
            j = int(np.argmin(seg)); k = int(np.argmax(seg))
            if j <= k:
                xs.extend((x[a + j], x[a + k])); ys.extend((seg[j], seg[k]))
            else:
                xs.extend((x[a + k], x[a + j])); ys.extend((seg[k], seg[j]))
        return np.asarray(xs), np.asarray(ys)

    def plot_fft(self):
        sig = self._get_sig()
        nyq = self.fs / 2.56; x = sig - np.mean(sig)
        # 始终画全范围FFT，细化只是视图放大
        n = len(x)
        key = ("fft", self.csv_path, n, bool(self.var_hann.get()),
               bool(self.var_bp.get()), self.var_bp_low.get(), self.var_bp_high.get())
        cache = getattr(self, "_spectrum_cache", None)
        if cache is None:
            self._spectrum_cache = cache = {}
        cached = cache.get(key)
        if cached is None:
            xw, wgain = self._apply_hann(x)
            yf = np.fft.rfft(xw); f = np.fft.rfftfreq(n, 1/self.fs)
            amp = (2/n) * wgain * np.abs(yf)
            cached = (f, amp)
            cache[key] = cached
        f, amp = cached
        m = f <= nyq
        ax = self._fresh_ax("FFT幅值谱")
        ax.plot(*self._decimate_xy(f[m], amp[m], view=self._fft_view(nyq)), lw=0.8)
        # 纵轴按全谱峰值定，缩放时只变横轴，幅值口径不跟着跳
        ax.set_ylim(0, max(float(np.max(amp[m])), 1e-12) * 1.05)
        self._cur_f = f[m]; self._cur_amp = amp[m]
        self._peak_annotate(ax, f[m], amp[m])
        if self.refine_range is None and self.var_bp.get():
            try:
                lo = float(self.var_bp_low.get()); hi = float(self.var_bp_high.get())
                ax.set_xlim(max(0, lo), hi)
            except: pass
        elif self.refine_range is None:
            ax.set_xlim(-nyq * 0.02, nyq)
        ax.set_ylim(bottom=0); ax.set_xlabel("频率(Hz)"); ax.set_ylabel("Amplitude (m/s$^2$)")
        self._post_draw()

    def plot_envelope(self):
        try:
            lo = float(self.var_env_low.get()); hi = float(self.var_env_high.get())
        except (TypeError, ValueError):
            messagebox.showerror("错误", "包络带通值无效"); return
        f_disp = self.fs / 2.56  # 有效分析频率口径：只用于限制显示/分析上限
        hi = min(hi, f_disp)
        lo = max(0.0, min(lo, hi * 0.9))
        key = ("env", self.csv_path, len(self.sig), lo, hi, bool(self.var_hann.get()))
        cache = getattr(self, "_spectrum_cache", None)
        if cache is None:
            self._spectrum_cache = cache = {}
        cached = cache.get(key)
        if cached is None:
            try:
                # 滤波设计必须用真实 Nyquist=fs/2。旧代码用 fs/2.56 当 Nyquist，
                # 当带宽上限 >= fs/2.56 时 Wn=1，scipy 抛 ValueError，包络谱画不出来。
                sos = design_band(self.fs, lo, hi, sos=True)
                filt = sosfiltfilt(sos, self.sig)
                if not np.isfinite(filt).all():
                    raise ValueError("滤波结果含非数值")
            except Exception as e:
                messagebox.showerror("包络带通错误", str(e)); return
            env = np.abs(hilbert(filt)); env = env - np.mean(env)
            n = len(env)
            envw, wgain = self._apply_hann(env)
            yf = np.fft.rfft(envw); f = np.fft.rfftfreq(n, 1/self.fs)
            amp = (2/n) * wgain * np.abs(yf)
            cached = (f, amp)
            cache[key] = cached
        f, amp = cached
        m = f <= hi
        ax = self._fresh_ax("包络谱")
        ax.plot(*self._decimate_xy(f[m], amp[m], view=self._view_for(0.0, float(hi))), lw=0.8)
        ax.set_ylim(0, max(float(np.max(amp[m])), 1e-12) * 1.05)
        self._cur_f = f[m]; self._cur_amp = amp[m]
        rpm = self.info.get("speed")
        if rpm:
            pass
        self._peak_annotate(ax, f[m], amp[m])
        ax.set_ylim(bottom=0); ax.set_xlabel("包络频率(Hz)"); ax.set_ylabel("Amplitude (m/s$^2$)")
        # X 轴只显示到最大分析频率（包络带通上限 hi），不保留 autoscale 的右侧余量
        ax.set_xlim(0, hi)
        self._post_draw()

    def _get_rot_hz(self):
        """当前 1X 转频(Hz)：优先手动设置，其次文件名里的转速。"""
        try:
            if self._rot_hz and float(self._rot_hz) > 0:
                return float(self._rot_hz)
        except Exception:
            pass
        try:
            spd = (self.info or {}).get("speed")
            if spd and float(spd) > 0:
                return float(spd) / 60.0
        except Exception:
            pass
        return 0.0

    def _ask_rot_hz(self):
        """没有转速时询问 1X 转频：可用当前基频标记一键带入，也可直接填转速/转频。"""
        dlg = tk.Toplevel(self)
        dlg.title("设置转速 / 转频")
        dlg.transient(self); dlg.resizable(False, False)
        frm = ttk.Frame(dlg, padding=12); frm.pack(fill="both", expand=True)
        ttk.Label(frm, text="文件名里没有转速。阶次谱需要 1X 转频，请填写转速或转频：",
                  wraplength=330, justify="left").grid(row=0, column=0, columnspan=2,
                                                       sticky="w", pady=(0, 8))
        base = None
        try:
            if (self.active_mark_x is not None
                    and self.current_plot in ("fft", "envelope", "velocity", "stft")):
                base = float(self.active_mark_x)
        except Exception:
            base = None
        v_rpm = tk.StringVar(value=("%.0f" % (base * 60.0)) if base and base > 0 else "")
        v_hz = tk.StringVar(value=("%.3f" % base) if base and base > 0 else "")
        ttk.Label(frm, text="转速 (rpm):").grid(row=1, column=0, sticky="e", pady=4)
        ttk.Entry(frm, textvariable=v_rpm, width=14).grid(row=1, column=1, sticky="w", pady=4)
        ttk.Label(frm, text="转频 (Hz):").grid(row=2, column=0, sticky="e", pady=4)
        ttk.Entry(frm, textvariable=v_hz, width=14).grid(row=2, column=1, sticky="w", pady=4)
        hint = ttk.Label(frm, text="", foreground=UI_PRIMARY, wraplength=330, justify="left")
        hint.grid(row=3, column=0, columnspan=2, sticky="w", pady=(4, 0))
        state = {"busy": False}

        def sync(src):
            if state["busy"]:
                return
            state["busy"] = True
            try:
                if src == "rpm":
                    hz = float(v_rpm.get()) / 60.0
                    v_hz.set("%.3f" % hz)
                else:
                    rpm = float(v_hz.get()) * 60.0
                    v_rpm.set("%.0f" % rpm)
                hint.config(text="")
            except Exception:
                pass
            finally:
                state["busy"] = False

        v_rpm.trace_add("write", lambda *a: sync("rpm"))
        v_hz.trace_add("write", lambda *a: sync("hz"))
        if base and base > 0:
            hint.config(text="已用当前基频标记（%.2fHz）带入，可直接改成别的值" % base)
        res = {"hz": 0.0}

        def ok():
            try:
                hz = float(v_hz.get()) if v_hz.get().strip() else float(v_rpm.get()) / 60.0
            except Exception:
                messagebox.showerror("输入错误", "请填写数字。", parent=dlg); return
            if not (0.01 <= hz <= float(self.fs) / 2.0):
                messagebox.showerror("输入错误", "转频超出合理范围。", parent=dlg); return
            res["hz"] = hz
            dlg.destroy()

        bf = ttk.Frame(frm); bf.grid(row=4, column=0, columnspan=2, pady=(10, 0), sticky="e")
        ttk.Button(bf, text="确定", command=ok).pack(side="left", padx=4)
        ttk.Button(bf, text="取消", command=dlg.destroy).pack(side="left", padx=4)
        dlg.bind("<Return>", lambda e: ok())
        dlg.bind("<Escape>", lambda e: dlg.destroy())
        center_window(dlg, self)
        dlg.wait_window()
        if res["hz"] > 0:
            self._rot_hz = res["hz"]
            try:
                self.info["speed"] = int(round(res["hz"] * 60.0))
            except Exception:
                pass
        return res["hz"]

    def _order_set_rot(self):
        if self._ask_rot_hz() > 0:
            self._redraw_current_plot()

    def plot_order(self):
        """阶次谱：频率轴除以 1X 转频。转频来源：手动设置 → 文件名转速 → 基频标记/弹框输入。"""
        sig = self._get_sig()
        if sig is None:
            return
        nyq = self.fs / 2.56; x = sig - np.mean(sig)
        n = len(x)
        yf = np.fft.rfft(x); f = np.fft.rfftfreq(n, 1/self.fs)
        amp = 2/n * np.abs(yf)
        m = f <= nyq
        f0 = self._get_rot_hz()
        if f0 <= 0:
            f0 = self._ask_rot_hz()
        if f0 > 0:
            # 回填到 info，标题里的“转速/转频”就有值了
            self._rot_hz = float(f0)
            try:
                if not (self.info or {}).get("speed"):
                    self.info["speed"] = int(round(float(f0) * 60.0))
            except Exception:
                pass
        if f0 <= 0:
            messagebox.showwarning(
                "提示", "阶次谱需要 1X 转频：可在 FFT 图上点选 1X 峰作基频，"
                        "或右键「设置转速 / 转频…」填写。")
            return
        orders = f[m] / f0  # 阶次 = 频率/转频
        ax = self._fresh_ax("阶次谱")
        ax.plot(*self._decimate_xy(orders, amp[m],
                                   view=self._view_for(float(orders[0]), float(orders[-1]))), lw=0.8)
        ax.set_ylim(0, max(float(np.max(amp[m])), 1e-12) * 1.05)
        self._cur_f = orders; self._cur_amp = amp[m]
        self._peak_annotate(ax, orders, amp[m], unit=" Order")
        ax.set_ylim(bottom=0); ax.set_xlabel("阶次 (Order)"); ax.set_ylabel("Amplitude (m/s$^2$)")
        self._post_draw()

    def plot_cepstrum(self):
        """倒频谱：IFFT(log|FFT|^2)"""
        sig = self._get_sig()
        x = sig - np.mean(sig)
        n = len(x)
        yf = np.fft.rfft(x)
        logspec = np.log(np.abs(yf) ** 2 + 1e-20)
        cep = np.fft.irfft(logspec, n)
        dt = 1/self.fs
        q = np.arange(n) * dt  # quefrency (s)
        # 跳过0点，只显示前0.2s
        mask = (q > 0.001) & (q <= 0.2)
        ax = self._fresh_ax("倒频谱")
        ax.plot(*self._decimate_xy(q[mask], cep[mask],
                                   view=self._view_for(float(q[mask][0]), float(q[mask][-1]))), lw=0.8)
        # 倒频谱有正有负：给出上下 8% 余量，让负峰完整可见（_post_draw 不再强制 ylim 下限为 0）
        ax.margins(y=0.08)
        self._cur_f = q[mask]; self._cur_amp = cep[mask]
        self._peak_annotate(ax, q[mask], cep[mask], unit="s")
        ax.set_xlabel("Quefrency (s)"); ax.set_ylabel("Cepstrum")
        self._post_draw()

    def plot_velocity(self):
        sig = self._get_sig()
        dt = 1/self.fs
        key = ("vel", self.csv_path, len(sig), float(self.fs),
               bool(self.var_bp.get()), self.var_bp_low.get(), self.var_bp_high.get())
        cache = getattr(self, "_spectrum_cache", None)
        if cache is None:
            self._spectrum_cache = cache = {}
        cached = cache.get(key)
        if cached is None:
            x = sig - np.mean(sig)
            v = np.cumsum(x) * dt
            # 1Hz 高通用 SOS 形式：fs 较高（如 51200Hz）时 Wn≈4e-5，
            # ba 形式的 filtfilt 会数值失稳（实测噪声被放大 17 倍以上，速度谱幅值完全失真）。
            sos_hp = butter(4, 1.0 / (self.fs / 2.0), btype="high", output="sos")
            v = sosfiltfilt(sos_hp, v)
            v = v * 1000.0  # m/s → mm/s
            n = len(v); yf = np.fft.rfft(v - np.mean(v)); f = np.fft.rfftfreq(n, dt)
            amp = 2/n * np.abs(yf)
            cached = (f, amp)
            cache[key] = cached
        f, amp = cached
        nyq = self.fs / 2.56
        m = f <= nyq
        ax = self._fresh_ax("速度谱")
        ax.plot(*self._decimate_xy(f[m], amp[m], view=self._fft_view(nyq)), lw=0.8)
        ax.set_ylim(0, max(float(np.max(amp[m])), 1e-12) * 1.05)
        self._cur_f = f[m]; self._cur_amp = amp[m]
        self._peak_annotate(ax, f[m], amp[m])
        if self.refine_range is None and self.var_bp.get():
            try:
                lo = float(self.var_bp_low.get()); hi = float(self.var_bp_high.get())
                ax.set_xlim(max(0, lo), hi)
            except: pass
        elif self.refine_range is None:
            ax.set_xlim(-nyq * 0.02, nyq)
        ax.set_xlabel("频率(Hz)"); ax.set_ylabel("Velocity (mm/s)")
        self._post_draw()

    def _full_fft_for_refine(self):
        """全记录幅值谱缓存（到 fs/2），用于把瀑布这类低分辨率谱图上的峰细化到 fs/N。

        必须与 plot_fft 走同一条链路（同样的带通 + 同样的窗），否则两处标注会落在
        相邻的不同谱线上（实测差过 1.4Hz，看起来像两个频率）。
        """
        sig = self._get_sig()
        n = int(len(sig)) if sig is not None else 0
        key = ("ref", self.csv_path, n, float(self.fs), bool(self.var_hann.get()),
               bool(self.var_bp.get()), self.var_bp_low.get(), self.var_bp_high.get())
        cache = getattr(self, "_fft_ref_cache", None)
        if cache is not None and getattr(self, "_fft_ref_key", None) == key:
            return cache
        x = np.asarray(sig, dtype=float)
        x = x - float(np.mean(x))
        xw, wgain = self._apply_hann(x)
        amp = (2.0 / max(n, 1)) * wgain * np.abs(np.fft.rfft(xw))
        f = np.fft.rfftfreq(n, 1.0 / float(self.fs))
        cache = (f, amp)
        self._fft_ref_cache = cache
        self._fft_ref_key = key
        return cache

    def _refine_peak_hz(self, f0, half):
        """在 f0±half 内用全记录 FFT 找更精确的峰频率：取窗口内幅值最大的那条谱线。
        与其它谱图显示的“谱线中心”口径一致（25600Hz/131072 点时谱线宽 0.195Hz），
        不用抛物线插值——矩形窗下插值反而会偏 0.05~0.1Hz，和速度谱对不上。"""
        try:
            f, amp = self._full_fft_for_refine()
            lo = max(0.0, float(f0) - float(half))
            hi = float(f0) + float(half)
            idx = np.where((f >= lo) & (f <= hi))[0]
            idx = idx[idx > 0]                 # 跳过直流分量，否则低端峰会被细化到 0Hz
            if idx.size == 0:
                return float(f0)
            k = int(idx[int(np.argmax(amp[idx]))])
            return float(f[k])
        except Exception:
            return float(f0)

    def plot_waterfall(self):
        """瀑布图：把 STFT 每个时间段的频谱按时间自下而上错开堆叠（时频瀑布）。

        - 分段：汉宁/矩形窗、50% 重叠；默认 2048 点，低频窄带测点在记录够长时自动用 4096 点提高频率分辨率；
        - 幅值默认 dB 显示（动态范围按本图自适应 20~60dB），右键菜单可切回线性；
        - 横轴是频率、默认只显示该测点分析频带，纵轴是“帧偏移”，缩放/细化/基频竖线等交互照常可用；
        - 帧数过多时等间隔抽帧（最多 26 帧），颜色由深到亮表示时间先后，右侧色标为时间。
        """
        sig = self.sig
        if sig is None or len(sig) < 32:
            return
        nyq = self.fs / 2.56
        # 本测点的分析频带（决定默认显示范围，也用来决定分段长度）
        x_hi = float(nyq)
        _pt = (self.info or {}).get("point", "")
        _bp = default_bp.get(_pt)
        if _bp is None and _pt in rule_dict:
            _bp = (rule_dict[_pt]["f_low"], rule_dict[_pt]["f_high"])
        if _bp and float(_bp[1]) > 0:
            x_hi = min(x_hi, float(_bp[1]))
        # 分段长度：默认 2048；窄带低频测点（<=1000Hz）在记录够长、帧数够多时用 4096，
        # 频率分辨率翻倍——否则 0-100Hz 这种带在 2048 点下只有十几条谱线，瀑布看不出形状
        nperseg = int(min(2048, max(32, len(sig) // 4)))
        try:
            if (x_hi <= 1000.0 and len(sig) >= 4096 * 6
                    and (float(self.fs) / nperseg) > x_hi / 50.0):
                nperseg = 4096
        except Exception:
            pass
        nperseg = int(max(32, min(nperseg, len(sig) // 2)))
        stft_window = "hann" if self.var_stft_win.get() else "boxcar"
        key = (self.csv_path, len(sig), float(self.fs), stft_window, nperseg)
        cache = getattr(self, "_wf_cache", None)
        if cache is None or getattr(self, "_wf_cache_key", None) != key:
            f, t, Sxx = spectrogram(sig, fs=self.fs, window=stft_window,
                                    nperseg=nperseg, noverlap=nperseg // 2)
            fm = f <= nyq
            # 功率谱开方得幅值谱；按全图最大值归一化，保留帧间相对强弱
            amp = np.sqrt(np.maximum(Sxx[fm], 0.0))
            cache = (f[fm], np.asarray(t, dtype=float), amp)
            self._wf_cache = cache
            self._wf_cache_key = key
        f, t, amp = cache
        n_frames = amp.shape[1]
        if n_frames < 2 or len(f) < 2:
            return
        max_frames = 26
        if n_frames > max_frames:
            idx = np.unique(np.linspace(0, n_frames - 1, max_frames).round().astype(int))
        else:
            idx = np.arange(n_frames)
        amp = amp[:, idx]
        t = t[idx]
        f_all, amp_all = f, amp          # 交互（方向键/缩小/竖线）仍用全频段
        step = 1.0
        base0 = 0.15
        # 默认只显示该测点的分析频带（x_hi 在函数开头已算好）；2D/3D 两条路径共用同一范围，
        # 需要看全通频时按“缩小”或 Shift+滚轮向外拉即可。
        keep = f <= x_hi
        f, amp = f[keep], amp[keep]
        if len(f) < 2:
            return
        gmax = float(np.max(amp)) or 1.0
        # 幅值映射：默认 dB（相对显示频带内的峰值）。动态范围按本图实际的峰值/噪声底取 20~60dB：
        # 固定 50dB 时，峰值噪声比只有十几 dB 的记录仍会压成一条直线；自适应后主频脊线明显立起来。
        if getattr(self, "_wf_db", True):
            _pos = amp[amp > 0]
            _floor = float(np.median(_pos)) * 0.7 if _pos.size else gmax * 1e-6
            _floor = max(_floor, gmax * 1e-7)
            _dr = float(np.clip(20.0 * np.log10(gmax / _floor), 20.0, 60.0))
            with np.errstate(divide="ignore"):
                _db = 20.0 * np.log10(np.maximum(amp, gmax * 1e-10) / gmax)
            amp_n = np.clip((_db + _dr) / _dr, 0.0, 1.0)
            z_label = "相对幅值(dB)"
        else:
            amp_n = amp / gmax
            z_label = "相对幅值"
        if getattr(self, "_wf_3d", False):
            self._plot_waterfall_3d(f, amp_n, t, nperseg, z_label)
            return
        ax = self._fresh_ax("瀑布图")
        cmap = plt.get_cmap("viridis")
        colors = cmap(np.linspace(0.12, 0.95, len(idx)))
        for k, col in enumerate(colors):
            base = base0 + k * step
            # 幅值占 0.72 个帧距：既留出帧间空隙，又不会让相邻帧互相遮挡
            ax.fill_between(f, base, base + amp_n[:, k] * 0.72, color=col,
                            alpha=0.28 if k % 2 else 0.20, linewidth=0, zorder=2 + k)
            ax.plot(f, base + amp_n[:, k] * 0.72, color=col, lw=0.9,
                    alpha=0.95, zorder=2 + k)
        top = base0 + (len(idx) - 1) * step + 0.95
        ax.set_xlim(0.0, x_hi)
        # 栈顶之上留 1.2 个帧距，专门给“主频标注”用，避免文字压在最上层曲线上
        ax.set_ylim(0.0, top + 1.2)
        ax.set_yticks([])
        ax.tick_params(axis="y", left=False)
        ax.set_xlabel("频率(Hz)")
        ax.set_ylabel("时间（自下而上）")
        # 标题只保留“瀑布图-测点 / 采集时间+转速+转频”两行，不再显示分段与帧数
        # 时间色标：颜色由深到亮对应时间先后
        sm = plt.cm.ScalarMappable(cmap=cmap, norm=Normalize(float(t[0]), float(t[-1])))
        self.fig.colorbar(sm, ax=ax, pad=0.01, label="时间(s)")
        # 登记“平均谱”：方向键找峰、基频/倍频/边带竖线在频率轴上仍然有意义（用全频段，缩小还能拉回）
        self._cur_f = f_all
        self._cur_amp = amp_all.mean(axis=1)
        # 主频标注：在“显示频带内”的平均谱上找峰，画成贯穿瀑布的竖直虚线。
        # 不能在全频段找峰——全频段最大峰常落在带外（如齿轮啮合频率），按它取 25% 阈值会导致带内一个标注都没有。
        _bm = f_all <= x_hi
        _fb = f_all[_bm]
        _mb = self._cur_amp[_bm]
        if (self.show_peaks and not self.marks_hidden
                and _mb.size and float(np.max(_mb)) > 0):
            pk, _ = find_peaks(_mb, height=float(np.max(_mb)) * 0.25)
            # 按幅值从高到低挑，标签之间至少隔 90 像素避免叠字
            chosen, chosen_px = [], []
            for pi in pk[np.argsort(_mb[pk])[::-1]] if len(pk) else []:
                try:
                    px = float(ax.transData.transform((float(_fb[pi]), 0.0))[0])
                except Exception:
                    px = None
                if px is not None and any(abs(px - q) < 90 for q in chosen_px):
                    continue
                chosen.append(int(pi))
                if px is not None:
                    chosen_px.append(px)
                if len(chosen) >= 5:
                    break
            speed = self.info.get("speed", 0)
            f_rot = speed / 60.0 if speed else 0
            # STFT 谱线宽 = fs/nperseg（如 25600Hz+2048点 → 12.5Hz），1X 只能落在 25.0 这样的谱线上。
            # 标注前用全记录 FFT 在该谱线 ±半个谱线宽内细化，避免出现“速度谱 26.0Hz、瀑布 25.0Hz”的错觉。
            _df_band = float(f[1] - f[0]) if len(f) > 1 else 0.0
            for pi in sorted(chosen):
                f_pk = float(_fb[pi])
                f_lbl = self._refine_peak_hz(f_pk, _df_band * 0.5) if _df_band > 0 else f_pk
                if f_lbl < 1.0:
                    continue      # 直流/极低频峰不标注
                ax.axvline(f_lbl, color="#b8860b", ls="--", lw=0.9, alpha=0.75, zorder=1)
                label = (f"{f_lbl:.1f}Hz ({f_lbl / f_rot:.1f}X)" if f_rot > 0
                         else f"{f_lbl:.1f}Hz")
                ax.annotate(label, xy=(f_lbl, top + 0.10), xycoords="data",
                            xytext=(0, 0), textcoords="offset points",
                            fontsize=7.5, color="#8a6d00", ha="center", va="bottom",
                            zorder=9, clip_on=False,
                            bbox=dict(boxstyle="round,pad=0.12", fc="#fff8dc",
                                      ec="none", alpha=0.75))
        self.current_plot = "stft"
        self._post_draw()

    def _plot_waterfall_3d(self, f, amp_n, t, nperseg, z_label="相对幅值"):
        """3D 瀑布视图：各帧频谱沿时间轴排开，鼠标左键拖动可旋转。
        背景/网格与二维谱图保持一致；帧色按时间渐变（与 2D 一致），频率范围也与 2D 相同。"""
        self.fig.clear()
        self.fig.patch.set_facecolor(CHART_BG)
        self.chart_title.configure(style="ChartTitleDark.TLabel")
        self.flow_left.configure(style="ChartToolDark.TFrame")
        self.flow_right.configure(style="ChartToolDark.TFrame")
        self._apply_icon_theme(True)
        ax = self.fig.add_subplot(111, projection="3d")
        ax.set_facecolor(CHART_BG)
        # 三维“墙面”也刷成和二维绘图区一样的灰色，否则默认是白色，整块图发白
        pane = to_rgba(CHART_BG, 1.0)
        for _axis in (ax.xaxis, ax.yaxis, ax.zaxis):
            try:
                _axis.set_pane_color(pane)
            except Exception:
                pass
            try:
                _axis._axinfo["grid"].update(color=(1, 1, 1, 0.55), linewidth=0.6)
            except Exception:
                pass
            try:
                _axis.line.set_color("#848f9d")
            except Exception:
                pass
        # 放大三维图：zoom 比单纯改 box_aspect 更不容易把 z 轴标签顶出画布
        try:
            ax.set_box_aspect((2.4, 1.0, 0.55), zoom=1.38)
        except TypeError:
            try:
                ax.set_box_aspect((2.4, 1.0, 0.55))
            except Exception:
                pass
        ax.set_position([0.0, 0.0, 1.0, 0.96])
        # 参考专业振动软件的“层叠填充”瀑布：每帧频谱填充到底面，按时间段分色
        from mpl_toolkits.mplot3d.art3d import Poly3DCollection
        n_show = min(12, len(t))
        sel = np.unique(np.linspace(0, len(t) - 1, n_show).round().astype(int))
        fi = np.unique(np.linspace(0, len(f) - 1, min(len(f), 700)).astype(int))
        fd = f[fi]
        # 帧色按时间渐变（与 2D 的 viridis 一致），比固定三色更容易看出时间先后
        palette = plt.get_cmap("viridis")(np.linspace(0.15, 0.92, max(1, len(sel))))
        for j, k in enumerate(sel):
            col = palette[j]
            z = amp_n[fi, k]
            xs = np.concatenate([fd, fd[::-1]])
            ys = np.full(xs.shape, float(t[k]))
            zs = np.concatenate([z, np.zeros_like(z)])
            poly = Poly3DCollection([list(zip(xs, ys, zs))],
                                    facecolor=col, edgecolor=col,
                                    linewidth=0.3, alpha=0.84)
            ax.add_collection3d(poly)
        ax.set_xlim(float(f[0]), float(f[-1]))
        ax.set_ylim(float(t[0]), float(t[-1]))
        try:
            ax.set_zlim(0.0, 1.05)
        except Exception:
            pass
        # 轴标题离刻度远一点，避免汉字与数字重叠
        ax.set_xlabel("频率(Hz)", labelpad=14, color=UI_TXT)
        ax.set_ylabel("时间(s)", labelpad=20, color=UI_TXT)
        ax.set_zlabel(z_label, labelpad=14, color=UI_TXT)
        ax.tick_params(colors=UI_TXT, labelsize=8)
        ax.view_init(elev=26, azim=-64)
        ax.grid(True)
        # 标题与二维瀑布一致（含采集信息、分段信息），不写“3D 视图”操作提示
        info = self.info or {}
        proj = info.get("project", "")
        unit = info.get("unit", "")
        point = info.get("point", "")
        dt = info.get("dt")
        dt_str = dt.strftime("%Y/%m/%d %H:%M:%S") if dt else ""
        speed = info.get("speed", 0) or 0
        f_rot = speed / 60.0 if speed else 0
        line1 = f"瀑布图-{proj}-{unit}{point}"
        line2 = (f"采集时间：{dt_str}  转速：{speed}rpm  转频：{f_rot:.2f}Hz" if speed
                 else f"采集时间：{dt_str}")
        self.chart_title.config(
            text=f"{line1}\n{line2}")
        self.current_plot = "stft"
        self.canvas.draw()
        self._position_chart_tools()

    def _wf3d_active(self):
        """3D 瀑布视图是否正在显示（只在瀑布图上生效，切到别的谱自动失效）。"""
        return bool(getattr(self, "_wf_3d", False)) and self.current_plot == "stft"

    def _toggle_wf_3d(self):
        self._wf_3d = not getattr(self, "_wf_3d", False)
        if self.axis_locked:
            self._set_locked(False)
        if not self._wf_3d:
            # 从 3D 回到 2D：按当前范围重新自动锁定（3D 需要拖动旋转，只有 3D 期间保持解锁）
            self._auto_lock_pending = True
        self._redraw_current_plot()

    def _toggle_wf_db(self):
        """瀑布幅值显示在 dB / 线性之间切换（dB 能看清边带与噪声底）。"""
        self._wf_db = not getattr(self, "_wf_db", True)
        self._redraw_current_plot()


class ExportDialog(tk.Toplevel):
    def __init__(self, master, units, points):
        super().__init__(master)
        self.title("导出范围"); self.geometry("420x230"); self.resizable(False, False)
        self.result = None; self.grab_set()
        self.scope = tk.StringVar(value="all")
        ttk.Radiobutton(self, text="全部机组测点", variable=self.scope, value="all", command=self._t).pack(anchor="w", padx=15, pady=8)
        ttk.Radiobutton(self, text="指定机组+测点", variable=self.scope, value="one", command=self._t).pack(anchor="w", padx=15)
        fr = ttk.Frame(self); fr.pack(padx=15, pady=8, fill="x")
        ttk.Label(fr, text="机组:").grid(row=0, column=0, padx=3)
        self.cu = ttk.Combobox(fr, width=10, state="readonly", values=units); self.cu.grid(row=0, column=1, padx=3)
        ttk.Label(fr, text="测点:").grid(row=0, column=2, padx=3)
        self.cp = ttk.Combobox(fr, width=22, state="readonly", values=points); self.cp.grid(row=0, column=3, padx=3)
        if units: self.cu.current(0)
        if points: self.cp.current(0)
        bf = ttk.Frame(self); bf.pack(pady=10)
        ttk.Button(bf, text="确定", command=self._ok).pack(side="left", padx=10)
        ttk.Button(bf, text="取消", command=self.destroy).pack(side="left", padx=10)
        self._t()
        center_window_later(self, master)
    def _t(self):
        s = "disabled" if self.scope.get() == "all" else "readonly"
        self.cu.configure(state=s); self.cp.configure(state=s)
    def _ok(self):
        self.result = ("all", None, None) if self.scope.get() == "all" else ("one", self.cu.get(), self.cp.get())
        self.destroy()


class ZipImportDialog(tk.Toplevel):
    """导入压缩包时的采样率设置：每个测点填一个采样率，可用默认值一键套用。

    采样率不在压缩包/文件名里，只能按测点指定；填过的值会记住，下次自动带出。
    """

    def __init__(self, master, points, info_text="", saved=None):
        super().__init__(master)
        self.title("导入压缩包 · 设置采样率")
        self.resizable(False, False)
        self.result = None
        self.grab_set()
        saved = dict(saved or {})
        frm = ttk.Frame(self, padding=12)
        frm.pack(fill="both", expand=True)
        if info_text:
            ttk.Label(frm, text=info_text, justify="left").pack(anchor="w", pady=(0, 6))
        ttk.Label(frm, text="请为下列测点填写采样频率（Hz），会记住上次填的值：").pack(anchor="w")
        outer = ttk.Frame(frm)
        outer.pack(fill="both", expand=True, pady=6)
        rows = max(1, len(points))
        canvas = tk.Canvas(outer, height=min(260, 28 * rows + 12), width=340,
                           highlightthickness=0, bg=UI_BG)
        sb = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas)
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        self.vars = {}
        for r, pt in enumerate(points):
            ttk.Label(inner, text=pt).grid(row=r, column=0, sticky="w", padx=(8, 12), pady=3)
            dv = saved.get(pt)
            v = tk.StringVar(value=("%d" % int(dv)) if dv else "")
            ttk.Entry(inner, textvariable=v, width=12).grid(row=r, column=1, sticky="w", pady=3)
            self.vars[pt] = v
        dflt = ttk.Frame(frm)
        dflt.pack(fill="x", pady=(6, 0))
        ttk.Label(dflt, text="默认采样率:").pack(side="left")
        self.var_default = tk.StringVar(value="25600")
        ttk.Entry(dflt, textvariable=self.var_default, width=10).pack(side="left", padx=6)
        ttk.Button(dflt, text="全部设为该值", command=self._apply_default).pack(side="left")
        bf = ttk.Frame(frm)
        bf.pack(pady=(10, 0))
        ttk.Button(bf, text="开始导入", command=self._ok).pack(side="left", padx=8)
        ttk.Button(bf, text="取消", command=self.destroy).pack(side="left", padx=8)
        self.bind("<Return>", lambda e: self._ok())
        self.bind("<Escape>", lambda e: self.destroy())
        # 用一次性居中：对话框关闭后不会再触发延迟回调（避免控制台 invalid command name）
        center_window(self, master)

    def _apply_default(self):
        s = self.var_default.get().strip()
        for v in self.vars.values():
            v.set(s)

    def _ok(self):
        out = {}
        for pt, v in self.vars.items():
            try:
                fs = float(str(v.get()).strip())
            except Exception:
                messagebox.showerror("输入错误", "「%s」的采样率请填写数字。" % pt, parent=self)
                return
            if not (1.0 <= fs <= 1e7):
                messagebox.showerror("输入错误", "「%s」的采样率超出合理范围。" % pt, parent=self)
                return
            out[pt] = fs
        try:
            self.default_fs = float(self.var_default.get().strip())
        except Exception:
            self.default_fs = 0.0
        self.result = out
        self.destroy()


SPEED_SIDECAR = "vib_speeds.json"   # 每个数据目录一份：{文件名: 转速rpm}，供阶次谱/表格复用


def speed_sidecar_load(csv_path):
    """读取同一目录下的转速 sidecar（文件名 -> rpm），没有就返回 {}。"""
    try:
        d = os.path.dirname(os.path.abspath(csv_path))
        p = os.path.join(d, SPEED_SIDECAR)
        if not os.path.exists(p):
            return {}
        with open(p, encoding="utf-8") as fp:
            data = json.load(fp)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def speed_sidecar_save(csv_path, rpm):
    """把某个文件的转速写进同目录 sidecar。"""
    try:
        d = os.path.dirname(os.path.abspath(csv_path))
        p = os.path.join(d, SPEED_SIDECAR)
        data = {}
        if os.path.exists(p):
            try:
                with open(p, encoding="utf-8") as fp:
                    data = json.load(fp)
            except Exception:
                data = {}
        if not isinstance(data, dict):
            data = {}
        data[os.path.basename(csv_path)] = float(rpm)
        with open(p, "w", encoding="utf-8") as fp:
            json.dump(data, fp, ensure_ascii=False, indent=1)
    except Exception:
        pass


class SpeedSetDialog(tk.Toplevel):
    """批量设置转速：文件名里没有转速时，给一批记录补上（写入库并记住）。"""

    def __init__(self, master, default_rpm=None, scope_opts=None, info_text=""):
        super().__init__(master)
        self.title("设置转速")
        self.resizable(False, False)
        self.result = None
        self.grab_set()
        frm = ttk.Frame(self, padding=12)
        frm.pack(fill="both", expand=True)
        if info_text:
            ttk.Label(frm, text=info_text, justify="left", wraplength=380).pack(anchor="w", pady=(0, 6))
        ttk.Label(frm, text="转速 (rpm)：").pack(anchor="w")
        self.var_rpm = tk.StringVar(value=("%d" % int(default_rpm)) if default_rpm else "")
        ttk.Entry(frm, textvariable=self.var_rpm, width=16).pack(anchor="w", pady=(2, 8))
        self.var_scope = tk.StringVar(value=(scope_opts[0][0] if scope_opts else "sel"))
        ttk.Label(frm, text="应用到：").pack(anchor="w")
        for key, text in (scope_opts or [("sel", "选中的行"), ("point", "当前测点全部记录"),
                                         ("all", "全部记录")]):
            ttk.Radiobutton(frm, text=text, value=key, variable=self.var_scope).pack(anchor="w")
        bf = ttk.Frame(frm)
        bf.pack(pady=(10, 0), fill="x")
        ttk.Button(bf, text="确定", command=self._ok).pack(side="right")
        ttk.Button(bf, text="取消", command=self.destroy).pack(side="right", padx=8)
        self.bind("<Return>", lambda e: self._ok())
        self.bind("<Escape>", lambda e: self.destroy())
        center_window(self, master)

    def _ok(self):
        try:
            rpm = float(str(self.var_rpm.get()).strip())
        except Exception:
            messagebox.showerror("输入错误", "转速请填写数字。", parent=self)
            return
        if not (0.0 <= rpm <= 60000.0):
            messagebox.showerror("输入错误", "转速超出合理范围。", parent=self)
            return
        self.result = (rpm, self.var_scope.get())
        self.destroy()


class ProjectDirsDialog(tk.Toplevel):
    """项目目录管理：列出已登记的目录，可移除（只移出列表，不动磁盘上的数据）。"""

    def __init__(self, master, dirs):
        super().__init__(master)
        self.title("项目目录")
        self.geometry("620x320")
        self.result = None
        self.grab_set()
        ttk.Label(self, text="已登记的项目目录（上传新目录会追加到这里；移除只影响列表，不删数据）：",
                  wraplength=580, justify="left").pack(anchor="w", padx=12, pady=(10, 6))
        body = ttk.Frame(self)
        body.pack(fill="both", expand=True, padx=12)
        self.lb = tk.Listbox(body, height=10, activestyle="none")
        sb = ttk.Scrollbar(body, orient="vertical", command=self.lb.yview)
        self.lb.configure(yscrollcommand=sb.set)
        self.lb.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self._dirs = list(dirs)
        self._refresh()
        bf = ttk.Frame(self)
        bf.pack(fill="x", padx=12, pady=10)
        ttk.Button(bf, text="移除选中", command=self._remove).pack(side="left")
        ttk.Button(bf, text="全部移除", command=self._clear).pack(side="left", padx=8)
        ttk.Button(bf, text="取消", command=self.destroy).pack(side="right")
        ttk.Button(bf, text="确定", command=self._ok).pack(side="right", padx=8)
        center_window(self, master)

    def _refresh(self):
        self.lb.delete(0, "end")
        for d in self._dirs:
            self.lb.insert("end", d)

    def _remove(self):
        for i in reversed(self.lb.curselection()):
            del self._dirs[i]
        self._refresh()

    def _clear(self):
        self._dirs = []
        self._refresh()

    def _ok(self):
        self.result = list(self._dirs)
        self.destroy()


# ===================== 分析报告（按时间段生成 Word 报告） =====================
# VDI 超限≠故障：齿轮箱/主轴承只按第一限度统计，未见故障特征时判"正常（振动偏大）"
VDI_ONLY_PARTS = ("主轴承", "齿轮箱")

REPORT_VDI = {"vdi_low": ("0.1–10 Hz", 0.3), "vdi_mid": ("10–1000 Hz", 7.5),
              "vdi_hi": ("10–5000 Hz", 10.0)}
REPORT_PART = ("主轴承", "齿轮箱", "发电机")


def report_band(point):
    """返回 (频带键, 频带文字, 第一限度)。"""
    key = rms_band_key(point)
    label, lim = REPORT_VDI.get(key, REPORT_VDI["vdi_mid"])
    return key, label, lim


def report_grade(ratio):
    """按第一限度占比判级：<80% 正常，80%~100% 关注，100%~200% 警告，≥200% 危险。

    与人工报告口径一致：13# 发电机 129%~153% 都判警告，达到 200% 才判危险。
    """
    if ratio >= 2.0:
        return "危险"
    if ratio >= 1.0:
        return "警告"
    if ratio >= 0.8:
        return "关注"
    return "正常"


def report_unit_label(unit, project=""):
    """报告里的机组编号：府谷/田家寨的数据文件名用 101#~125#，报告里写 1#~25#。"""
    u = str(unit or "").strip().rstrip("#号")
    try:
        n = int(u)
    except Exception:
        return str(unit or "?")
    if n >= 100 and ("府谷" in str(project) or "田家寨" in str(project)):
        n -= 100
    return "%d#" % n


def report_part_of(point):
    pt = str(point or "")
    if "发电机" in pt:
        return "发电机"
    if "齿轮箱" in pt:
        return "齿轮箱"
    return "主轴承"


def report_stats(rows, vdi_only_normal=True):
    """按 机组 → 测点 汇总时间段内的带内 RMS（最大/平均/次数/最大值时刻）。"""
    agg = {}
    for r in rows:
        u = report_unit_label(r.get("unit"), r.get("project"))
        pt = str(r.get("point") or "?").strip()
        key = rms_band_key(pt)
        val = r.get(key)
        if val is None:
            val = r.get("rms")
        if val is None:
            continue
        try:
            val = float(val)
        except Exception:
            continue
        d = agg.setdefault(u, {}).setdefault(
            pt, {"max": 0.0, "sum": 0.0, "n": 0, "ts": "", "min": None})
        d["n"] += 1
        d["sum"] += val
        d["min"] = val if d["min"] is None else min(d["min"], val)
        if val > d["max"]:
            d["max"] = val
            d["ts"] = str(r.get("dt_str") or "")
    for u, pts in agg.items():
        for pt, d in pts.items():
            key, label, lim = report_band(pt)
            d["mean"] = d["sum"] / max(1, d["n"])
            d["band"] = label
            d["limit"] = lim
            d["ratio"] = (d["max"] / lim) if lim else 0.0
            d["grade"] = report_grade(d["ratio"])
            d["raw_grade"] = d["grade"]
            d["vdi_big"] = False
            if vdi_only_normal and d["ratio"] >= 0.8 and report_part_of(pt) in VDI_ONLY_PARTS:
                d["vdi_big"] = d["grade"] != "正常"
                d["grade"] = "正常"       # 振动偏大但无故障特征，判正常
    # 数值异常偏小：远低于同型测点中位 → 传感器/采集通道问题，判“数据异常”
    _peer = {}
    for u, pts in agg.items():
        for pt, d in pts.items():
            _peer.setdefault(pt, []).append(d["max"])
    _med = {}
    for pt, lst in _peer.items():
        lst.sort()
        _med[pt] = lst[len(lst) // 2]
    for u, pts in agg.items():
        for pt, d in pts.items():
            m0 = _med.get(pt, 0.0)
            d["data_bad"] = False
            if m0 > 0 and d["max"] < DATA_BAD_RATIO * m0:
                d["data_bad"] = True
                d["peer_med"] = m0
                d["grade"] = "数据异常"
    return agg


# ----------------- 包络谱故障判定（报告用） -----------------
DATA_BAD_RATIO = 0.05        # 低于同型中位的 5% 判“数据异常”（传感器/采集通道）
ENV_FAULT_AMP_MIN = 3.0      # 包络谱故障阶次最小幅值
ENV_FAULT_REL = 5.0          # 相对同型测点中位数的倍数


def _shaft_freqs(rpm):
    """由发电机(高速轴)转速换算出各轴转频(Hz)。"""
    fH = float(rpm) / 60.0
    fM = fH / GB_I3
    fS = fM / GB_I2
    fL = fS / GB_I1
    return {"H": fH, "M": fM, "S": fS, "L": fL, "P": fL * GB_ZR / GB_ZP}


def report_bearing_names(project, point):
    """按项目与测点名解析出可能的轴承（下划线不敏感的子串匹配）。"""
    mapping = None
    for pk, pm in BEARING_PROJECT_MAP.items():
        if pk and pk in str(project):
            mapping = pm
            break
    if not mapping:
        return []
    pt = str(point).replace("_", "")
    for kw, blist in mapping:
        if kw and kw.replace("_", "") in pt:
            return list(blist)
    return []


def report_env_curve(csv_path, nrows=131072):
    """包络谱曲线（用于绘图）：返回 (f, amp)。解调带 1000–8000Hz。"""
    try:
        info = parse_filename(os.path.basename(csv_path)) or {}
        fs = info.get("fs")
        if not fs:
            return None, None
        sig = pd.read_csv(csv_path, header=None, nrows=nrows).iloc[:, 0]
        sig = pd.to_numeric(sig, errors="coerce").dropna().values.astype(float)
        if len(sig) < fs * 0.25:
            return None, None
        lo = 1000.0
        hi = min(8000.0, fs / 2.0 * 0.95)
        if hi <= lo * 1.2:
            lo, hi = 400.0, hi
        filt = sosfiltfilt(design_band(fs, lo, hi, sos=True), sig)
        env = np.abs(hilbert(filt))
        env = env - np.mean(env)
        yf = np.fft.rfft(env * np.hanning(len(env)))
        f = np.fft.rfftfreq(len(env), 1.0 / fs)
        amp = (2.0 / len(env)) * 2.0 * np.abs(yf)
        return f, amp
    except Exception:
        return None, None


def report_env_peak(csv_path, point, project):
    """对一个 CSV 做包络谱分析，返回最贴近轴承故障阶次的峰值 {amp, hz, label, bearing}。"""
    try:
        info = parse_filename(os.path.basename(csv_path))
        fs, rpm = info.get("fs"), info.get("speed")
        if not fs or not rpm:
            return None
        names = report_bearing_names(project, point)
        if not names:
            return None
        f, amp = report_env_curve(csv_path)
        if f is None:
            return None
        sh = _shaft_freqs(rpm)
        best = None
        for nm in names:
            brg = BEARING_LIB.get(nm)
            if not brg:
                continue
            code, mult = brg
            base = sh.get(code, 0.0)
            if base <= 0:
                continue
            for key in ("BPFO", "BPFI", "BSF"):
                m_ord = mult.get(key)
                if not m_ord:
                    continue
                tgt = m_ord * base                       # 只认基频峰
                if tgt <= 0 or tgt > f[-1]:
                    continue
                band = (f > tgt * 0.97) & (f < tgt * 1.03)
                if not band.any():
                    continue
                a = float(amp[band].max())
                # 2 倍频幅值：真正的轴承损伤通常有谐波族，宽带噪声没有
                t2 = tgt * 2.0
                b2 = (f > t2 * 0.97) & (f < t2 * 1.03)
                a2 = float(amp[b2].max()) if (t2 <= f[-1] and b2.any()) else 0.0
                if best is None or a > best["amp"]:
                    best = {"amp": a, "amp2": a2, "hz": tgt, "label": "%s×1" % key,
                            "bearing": nm, "order": m_ord}
        return best
    except Exception:
        return None


REPORT_SCAN_STAT = {}


def report_scan_faults(agg, rows, project):
    """对每个测点做包络谱判定，写回 agg 等级并返回 {(机组,测点): 故障信息}。"""
    fault_info = {}
    _n_pt = 0
    _n_miss = 0
    _cand = {}
    for r in rows:
        _pt = str(r.get("point") or "")
        if not _pt:
            continue
        _u = report_unit_label(r.get("unit"), r.get("project"))
        _kv = r.get(rms_band_key(_pt))
        if _kv is None:
            _kv = r.get("rms")
        try:
            _val = float(_kv or 0.0)
        except Exception:
            _val = 0.0
        try:
            _ge = float(r.get("ge") or 0.0)
        except Exception:
            _ge = 0.0
        _cand.setdefault((_u, _pt), []).append((_val, _ge, r.get("csv_path"), str(r.get("dt_str") or "")))
    _res_map = {}
    for _k, _lst in _cand.items():
        if "发电机" in _k[1]:
            _lst.sort(key=lambda x: (-x[1], -x[0]))
        else:
            _lst.sort(key=lambda x: -x[0])
        if _lst[0][0] < 0.15 and "发电机" not in _k[1]:
            continue
        _hit = None
        _n_pt += 1
        if not any(_x[2] for _x in _lst[:2]):
            _n_miss += 1
        for _val, _ge, _p, _ts in _lst[:2]:
            if not _p:
                continue
            _r = report_env_peak(_p, _k[1], project)
            if _r and (_hit is None or _r["amp"] > _hit["amp"]):
                _hit = dict(_r)
                _hit["csv"] = _p
                _hit["ts"] = _ts
        if _hit:
            _res_map[_k] = _hit
    REPORT_SCAN_STAT.clear()
    REPORT_SCAN_STAT.update({"points": _n_pt, "missing": _n_miss})
    _mids = {}
    for _k, _r in _res_map.items():
        _mids.setdefault(_k[1], []).append(_r["amp"])
    for _pt, _lst in _mids.items():
        _lst.sort()
        _mids[_pt] = _lst[len(_lst) // 2]
    for _k, _r in _res_map.items():
        _med = _mids.get(_k[1], 0.0)
        _thr = max(ENV_FAULT_AMP_MIN, ENV_FAULT_REL * _med)
        fault_info[_k] = {"alarm": _r["amp"] >= _thr, "amp": _r["amp"], "label": _r["label"],
                          "hz": _r["hz"], "thr": _thr, "bearing": _r["bearing"],
                          "order": _r.get("order", 0.0), "csv": _r.get("csv"), "ts": _r.get("ts", "")}
    return fault_info


def report_project_name(project):
    """报告里显示的项目名称：按目录/项目名映射成正式名称。"""
    t = str(project or "")
    if ("田家寨" in t) or ("府谷" in t):
        return "京能田家寨风电场"
    if "五峰" in t:
        return "中节能五峰北风垭风电场"
    return t


def report_point_cn(point):
    """测点名显示用：去掉命名里的下划线（发电机_前轴承轴向 → 发电机前轴承轴向）。"""
    return (point or "").replace("_", "").replace(" ", "")


def report_apply_faults(agg, fault_info, scan_faults=True):
    """把包络判定结果写回 agg：fault / fault_lab / csv / amp / grade。"""
    for _u, _pts in agg.items():
        for _pt, _d in _pts.items():
            _f = fault_info.get((_u, _pt))
            if _f is not None:
                _d["fault"] = _f["alarm"]
                _d["fault_lab"] = "%s %.1fHz 幅值 %.2f" % (_f["label"], _f["hz"], _f["amp"])
                _d["csv"] = _f.get("csv")
                _d["amp"] = _f["amp"]
                _d["ts"] = _f.get("ts", _d.get("ts", ""))
                if _f["alarm"]:
                    _d["grade"] = "警告"
                else:
                    _d["grade"] = "数据异常" if _d.get("data_bad") else "正常"
            elif scan_faults:
                _d["grade"] = "数据异常" if _d.get("data_bad") else "正常"
    return agg


def _docx_cn(run, cn="宋体", en="Times New Roman"):
    from docx.oxml.ns import qn
    run.font.name = en
    run._element.rPr.rFonts.set(qn("w:eastAsia"), cn)


def _docx_shade(cell, color):
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement
    tcPr = cell._tc.get_or_add_tcPr()
    shd = tcPr.find(qn("w:shd"))
    if shd is None:
        shd = OxmlElement("w:shd")
        shd.set(qn("w:val"), "clear")
        shd.set(qn("w:color"), "auto")
        tcPr.append(shd)
    shd.set(qn("w:fill"), color)


# ---------------- 项目档案（模板 / 无数据测点 / 报警预警记录） ----------------
PROFILE_NAME = "项目档案.json"
PROFILE_MAX_PERIODS = 36


def profile_path(pdir):
    return os.path.join(pdir, PROFILE_NAME)


def profile_template(prof):
    """取项目模板路径：原路径失效时回退到项目目录里的备份副本。"""
    t = (prof or {}).get("template") or {}
    for k in ("path", "backup"):
        p = t.get(k)
        if p and os.path.exists(p):
            return p
    return None


def load_profile(pdir):
    prof = {"version": 1, "project": os.path.basename(str(pdir).rstrip("\\/")),
            "template": None, "periods": {}, "units_known": [], "points_known": {}}
    try:
        p = profile_path(pdir)
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                d = json.load(f)
            if isinstance(d, dict):
                prof.update(d)
    except Exception:
        pass
    return prof


def save_profile(pdir, prof):
    try:
        with open(profile_path(pdir), "w", encoding="utf-8") as f:
            json.dump(prof, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def report_period_key(d0, d1):
    if d0 and d1 and (d0.year, d0.month) == (d1.year, d1.month):
        return "%04d-%02d" % (d0.year, d0.month)
    return "%s_%s" % (d0.isoformat() if d0 else "?", d1.isoformat() if d1 else "?")


def prev_period(prof, key):
    keys = [k for k in ((prof or {}).get("periods") or {}) if k != key]
    if not keys:
        return None
    keys.sort()
    return keys[-1]


def collect_period(agg, d0, d1, prof):
    """把本期结果整理成档案记录：机组/测点、无数据机组与测点、>=80% 报警记录。"""
    key = report_period_key(d0, d1)
    units = sorted(agg.keys(), key=tree_unit_order)
    known = list((prof or {}).get("units_known") or [])
    pk = (prof or {}).get("points_known") or {}
    no_units = [u for u in known if u not in agg]
    no_points = []
    for u in units:
        miss = [p for p in (pk.get(u) or []) if p not in agg[u]]
        if miss:
            no_points.append({"unit": u, "points": miss})
    alarms = []
    for u in units:
        for pt, d in agg[u].items():
            if d.get("ratio", 0.0) >= 0.8:
                alarms.append({"unit": u, "point": pt, "band": d.get("band", ""),
                               "rms": round(float(d.get("max", 0.0)), 3),
                               "limit": d.get("limit", 0.0),
                               "ratio": round(float(d.get("ratio", 0.0)), 3),
                               "grade": d.get("grade", "正常"),
                               "time": str(d.get("ts", ""))[:16]})
    alarms.sort(key=lambda a: -a["ratio"])
    rec = {"label": key,
           "range": "%s ~ %s" % (d0.isoformat() if d0 else "?", d1.isoformat() if d1 else "?"),
           "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
           "template": ((prof or {}).get("template") or {}).get("name", ""),
           "units": units,
           "points": {u: sorted(agg[u].keys(), key=tree_point_order) for u in units},
           "no_data_units": no_units,
           "no_data_points": no_points,
           "alarms": alarms}
    return key, rec


def merge_period(prof, key, rec):
    periods = prof.setdefault("periods", {})
    periods[key] = rec
    if len(periods) > PROFILE_MAX_PERIODS:
        for k in sorted(periods)[:-PROFILE_MAX_PERIODS]:
            periods.pop(k, None)
    uk = set(prof.get("units_known") or [])
    uk.update(rec.get("units") or [])
    prof["units_known"] = sorted(uk, key=tree_unit_order)
    pk = prof.get("points_known") or {}
    for u, pts in (rec.get("points") or {}).items():
        have = set(pk.get(u) or [])
        have.update(pts)
        pk[u] = sorted(have, key=tree_point_order)
    prof["points_known"] = pk
    prof["updated"] = rec.get("generated")
    return prof


def alarm_diff(prev_rec, cur_rec):
    p = {(a["unit"], a["point"]): a for a in ((prev_rec or {}).get("alarms") or [])}
    c = {(a["unit"], a["point"]): a for a in ((cur_rec or {}).get("alarms") or [])}
    new = [c[k] for k in c if k not in p]
    gone = [p[k] for k in p if k not in c]
    stay = [(p[k], c[k]) for k in c if k in p]
    return new, gone, stay


class ReportDialog(tk.Toplevel):
    """选择项目与时间段，生成分析报告（.docx）。"""

    def __init__(self, master, main_dir, project_dirs):
        super().__init__(master)
        self.title("生成分析报告")
        self.transient(master)
        self.resizable(False, False)
        self.main_dir = main_dir
        self.map = {}
        for d in (project_dirs or ([main_dir] if main_dir else [])):
            self.map[os.path.basename(d.rstrip("\\/"))] = d
        if not self.map and main_dir:
            self.map[os.path.basename(main_dir.rstrip("\\/"))] = main_dir
        self.grab_set()

        frm = ttk.Frame(self, padding=12)
        frm.pack(fill="both", expand=True)

        ttk.Label(frm, text="项目：").grid(row=0, column=0, sticky="e", pady=4)
        names = list(self.map.keys())
        self.var_proj = tk.StringVar(value=names[0] if names else "")
        ttk.Combobox(frm, textvariable=self.var_proj, values=names, state="readonly",
                     width=34).grid(row=0, column=1, sticky="w", pady=4)

        d0, d1 = self._date_span()
        ttk.Label(frm, text="开始日期：").grid(row=1, column=0, sticky="e", pady=4)
        self.dp0 = DateEntry(frm, date_pattern="yyyy-mm-dd", width=14,
                             year=d0.year, month=d0.month, day=d0.day)
        self.dp0.grid(row=1, column=1, sticky="w", pady=4)
        ttk.Label(frm, text="结束日期：").grid(row=2, column=0, sticky="e", pady=4)
        self.dp1 = DateEntry(frm, date_pattern="yyyy-mm-dd", width=14,
                             year=d1.year, month=d1.month, day=d1.day)
        self.dp1.grid(row=2, column=1, sticky="w", pady=4)

        ttk.Label(frm, text="点日历图标选择时间段，报告统计该时间段内全部数据。",
                  foreground="#666666").grid(row=3, column=0, columnspan=2, sticky="w", pady=(2, 8))
        ttk.Label(frm, text="报告按 VDI3834 三个频带分别取时间段内最大带内 RMS，\n给出各测点占第一限度比例与等级。",
                  foreground="#666666").grid(row=4, column=0, columnspan=2, sticky="w", pady=(0, 10))

        tplbar = ttk.Frame(frm)
        tplbar.grid(row=5, column=0, columnspan=2, sticky="w", pady=(0, 6))
        ttk.Label(tplbar, text="报告模板：").pack(side="left")
        ttk.Button(tplbar, text="选择模板…", command=self._choose_template).pack(side="left")
        ttk.Button(tplbar, text="清除", command=self._clear_template).pack(side="left", padx=6)
        self.tpl_lbl = ttk.Label(tplbar, text="", foreground="#666666")
        self.tpl_lbl.pack(side="left", padx=4)

        bar = ttk.Frame(frm)
        bar.grid(row=6, column=0, columnspan=2, sticky="e")
        ttk.Button(bar, text="生成报告", command=self._go).pack(side="left", padx=6)
        ttk.Button(bar, text="取消", command=self.destroy).pack(side="left")

        ttk.Label(frm, text="项目档案：每次生成报告会记录本期机组/测点、无数据测点与报警记录，\n"
                           "并与历史记录自动对比（存项目目录 项目档案.json）。",
                  foreground="#666666").grid(row=7, column=0, columnspan=2, sticky="w", pady=(8, 0))
        self.var_proj.trace_add("write", lambda *a: self._refresh_tpl())
        self._refresh_tpl()

    def _tpl_profile(self):
        d = self.map.get(self.var_proj.get())
        return d, load_profile(d) if d else None

    def _refresh_tpl(self):
        try:
            d, prof = self._tpl_profile()
            t = (prof or {}).get("template") or {}
            p = profile_template(prof)
            if p:
                _tip = "" if p == t.get("path") else "（使用备份副本）"
                self.tpl_lbl.config(text="已设置：%s%s" % (t.get("name") or os.path.basename(p), _tip))
            else:
                self.tpl_lbl.config(text="未设置（使用程序内置版式）")
        except Exception:
            pass

    def _choose_template(self):
        d = self.map.get(self.var_proj.get())
        if not d:
            messagebox.showwarning("提示", "请先选择项目目录")
            return
        p = filedialog.askopenfilename(title="选择该项目的报告模板（.docx）",
                                       filetypes=[("Word 文档", "*.docx")])
        if not p:
            return
        prof = load_profile(d)
        bak = ""
        try:
            tdir = os.path.join(d, "模板")
            os.makedirs(tdir, exist_ok=True)
            bak = os.path.join(tdir, "报告模板_%s.docx" % os.path.splitext(os.path.basename(p))[0])
            if os.path.abspath(bak) != os.path.abspath(p):
                shutil.copyfile(p, bak)
        except Exception:
            bak = ""
        prof["template"] = {"path": p, "name": os.path.basename(p), "backup": bak,
                            "set_at": datetime.now().strftime("%Y-%m-%d %H:%M")}
        if save_profile(d, prof):
            self._refresh_tpl()
            messagebox.showinfo("已保存", "模板已记入项目档案：\n%s" % p)
        else:
            messagebox.showerror("保存失败", "无法写入 %s" % profile_path(d))

    def _clear_template(self):
        d = self.map.get(self.var_proj.get())
        if not d:
            return
        prof = load_profile(d)
        prof["template"] = None
        save_profile(d, prof)
        self._refresh_tpl()

    def _date_span(self):
        """从库里取该项目的日期范围作为默认值。"""
        d = self.map.get(self.var_proj.get()) if hasattr(self, "var_proj") else self.main_dir
        d = d or self.main_dir
        try:
            conn = db_connect(d)
            row = conn.execute("SELECT MIN(dt_date), MAX(dt_date) FROM records").fetchone()
            conn.close()
            if row and row[0] and row[1]:
                return date.fromisoformat(str(row[0])), date.fromisoformat(str(row[1]))
        except Exception:
            pass
        return date.today(), date.today()

    @staticmethod
    def _parse_date(txt):
        txt = str(txt or "").strip()
        if not txt:
            return None
        txt = txt.replace("/", "-").replace(".", "-").replace("年", "-").replace("月", "-").replace("日", "")
        parts = [p for p in txt.split("-") if p.strip()]
        try:
            y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
            return date(y, m, d)
        except Exception:
            return None

    def _go(self):
        proj = self.var_proj.get()
        d = self.map.get(proj)
        if not d:
            messagebox.showwarning("提示", "请先选择项目目录")
            return
        d0 = self.dp0.get_date()
        d1 = self.dp1.get_date()
        if d0 and d1 and d0 > d1:
            d0, d1 = d1, d0
        try:
            conn = db_connect(d)
            rows = db_load_all(conn)
            conn.close()
        except Exception as ex:
            messagebox.showerror("读取失败", "读取缓存库失败：%s" % ex)
            return
        picked = []
        for r in rows:
            dt = r.get("dt_date")
            if isinstance(dt, str):
                try:
                    dt = date.fromisoformat(dt)
                except Exception:
                    dt = None
            if d0 and (dt is None or dt < d0):
                continue
            if d1 and (dt is None or dt > d1):
                continue
            picked.append(r)
        if not picked:
            messagebox.showwarning("提示", "该时间段内没有已计算的数据，请先“计算数据”。")
            return
        _prof0 = load_profile(d)
        agg = report_stats(picked, bool(_prof0.get("vdi_only_normal", True)))
        if not agg:
            messagebox.showwarning("提示", "该时间段内的记录没有可用的带内 RMS。")
            return
        prof = load_profile(d)
        # 首次生成时用库内全部历史补齐“已知机组/测点”，否则识别不出本期无数据的机组
        try:
            _kn = prof.setdefault("units_known", [])
            _lbls = {report_unit_label(r.get("unit"), r.get("project")) for r in rows if r.get("unit")}
            for _u in sorted(_lbls, key=tree_unit_order):
                if _u not in _kn:
                    _kn.append(_u)
            _pk = prof.setdefault("points_known", {})
            for r in rows:
                _u, _pt = str(r.get("unit") or ""), r.get("point")
                if _u and _pt:
                    _lst = _pk.setdefault(_u, [])
                    if _pt not in _lst:
                        _lst.append(_pt)
        except Exception:
            pass
        pkey, rec = collect_period(agg, d0, d1, prof)
        out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "输出")
        try:
            os.makedirs(out_dir, exist_ok=True)
        except Exception:
            out_dir = d
        stamp = datetime.now().strftime("%Y%m%d_%H%M")
        rng = "%s_%s" % (d0.isoformat() if d0 else "起",
                         d1.isoformat() if d1 else "止")
        fn = "分析报告_%s_%s_%s.docx" % (proj, rng, stamp)
        path = os.path.join(out_dir, fn)
        try:
            _tmpl = profile_template(prof) if prof else None
            if not _tmpl or not os.path.exists(_tmpl):
                # 项目档案没登记/路径失效：自动在程序目录与项目目录里找模板
                _base = os.path.dirname(os.path.abspath(__file__))
                _dirs = [os.path.join(_base, "数据", "模板"), os.path.join(_base, "模板"),
                         os.path.join(proj, "模板") if proj else "", _base]
                _cands = []
                for _d in _dirs:
                    if _d and os.path.isdir(_d):
                        for _f in os.listdir(_d):
                            if _f.lower().endswith(".docx") and not _f.startswith("~$"):
                                _p = os.path.join(_d, _f)
                                if os.path.exists(_p):
                                    _cands.append(_p)
                if _cands:
                    _tmpl = max(_cands, key=os.path.getmtime)
            if _tmpl and os.path.exists(_tmpl):
                import importlib.util as _ilu
                _spec = _ilu.spec_from_file_location(
                    "tpl_fill", os.path.join(os.path.dirname(os.path.abspath(__file__)), "tpl_fill.py"))
                _tf = _ilu.module_from_spec(_spec)
                _spec.loader.exec_module(_tf)

                def _figc(u, pt, _agg=agg):
                    d = _agg[u][pt]
                    png = os.path.join(os.environ.get("TEMP", "."), "repfig_%s.png" % u.rstrip("#"))
                    try:
                        report_fault_figure(d.get("csv"), pt, proj, u, png)
                        return png if os.path.exists(png) else None
                    except Exception:
                        return None

                def _capc(u, pt, png):
                    d = agg[u][pt]
                    return "图%s-1 %s测点包络谱图（%s）" % (
                        u.rstrip("#"), report_point_cn(pt), (d.get("ts") or "")[:16].replace("T", " "))

                def _anac(u, pt):
                    d = agg[u][pt]
                    return ("如图 %s-1 所示，%s测点包络谱图中存在轴承故障阶次（%s），判断该测点存在轴承损伤特征，"
                            "等级：警告，建议加强跟踪监测。" % (u.rstrip("#"), report_point_cn(pt),
                                                                d.get("fault_lab", "")))

                _tf.fill(_tmpl, path, proj, d0, d1, agg, list(agg.keys()), report_part_of,
                         {"正常": 0, "数据异常": 1, "关注": 2, "警告": 3, "危险": 4},
                         prof=prof, rows=picked,
                         fig_cb=_figc, caption_cb=_capc, analysis_cb=_anac)
            else:
                build_template_report(path, proj, d0, d1, agg, picked, prof=prof, cur=rec)
        except Exception as ex:
            import traceback
            messagebox.showerror("生成失败", "%s\n%s" % (ex, traceback.format_exc()[:800]))
            return
        try:
            os.startfile(path)
        except Exception:
            pass
        try:
            merge_period(prof, pkey, rec)
            prof["project"] = proj
            save_profile(d, prof)
            _saved = "\n项目档案已更新：%s（期次 %s）" % (profile_path(d), pkey)
        except Exception:
            _saved = ""
        messagebox.showinfo("完成", "报告已生成：\n%s%s" % (path, _saved))
        self.destroy()


# ----------------- 按项目模板生成月报（封面→注意事项→概述→运行状态→逐台机组） -----------------
REPORT_NOTES = [
    "1.  本报告无“珠海市鑫世达测控技术有限公司”专用章无效。",
    "2.  本报告涂改无效。",
    "3.  未经本公司书面许可，部分复制、摘用或篡改本报告内容，引起法律纠纷，责任自负。",
    "4.  检测分析结果仅对受检样品有效。",
    "5.  对检测报告若有异议，请于收到报告之日起一个月内向本公司提出，逾期不在受理。",
]
REPORT_COMPANY = "珠海市鑫世达测控技术有限公司"
REPORT_COMPANY_EN = "Zhuhai Sensestar Measurement technology Co.,Ltd."


def report_month_text(d0, d1):
    if d0 and d1 and d0.year == d1.year and d0.month == d1.month:
        return "%d 年 %d 月" % (d0.year, d0.month)
    return "%s 至 %s" % (d0.strftime("%Y-%m-%d") if d0 else "-",
                         d1.strftime("%Y-%m-%d") if d1 else "-")


def report_fault_figure(csv_path, point, project, unit, out_png, mark=None):
    """故障测点图谱：上=幅值谱(0–1000Hz)，下=包络谱(0–400Hz，解调 1000–8000Hz)。"""
    import pandas as pd
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg

    info = parse_filename(os.path.basename(csv_path)) or {}
    fs = info.get("fs") or 20000
    rpm = info.get("speed") or 0
    df = pd.read_csv(csv_path, header=None)
    sig = pd.to_numeric(df.iloc[:, 0], errors="coerce").dropna().values.astype(float)
    if sig.size < 4096:
        return None

    fig = Figure(figsize=(9.0, 5.0), dpi=200)
    FigureCanvasAgg(fig)
    ax1 = fig.add_subplot(211)
    ax2 = fig.add_subplot(212)

    n = len(sig)
    yf = np.fft.rfft(sig * np.hanning(n))
    f1 = np.fft.rfftfreq(n, 1.0 / fs)
    a1 = (2.0 / n) * np.abs(yf)
    ax1.plot(f1, a1, lw=0.55, color="#1f4e79")
    ax1.set_xlim(0, 1000)
    ax1.set_xlabel("频率 (Hz)", fontsize=8)
    ax1.set_ylabel("加速度 (m/s2)", fontsize=8)
    ax1.tick_params(labelsize=7)
    ax1.grid(alpha=0.25, lw=0.4)
    ax1.set_title("幅值谱 (0–1000Hz)   rpm=%s" % (int(rpm) if rpm else "-"), fontsize=8.5)

    fe, ae = report_env_curve(csv_path)
    if fe is None:
        fe, ae = np.zeros(1), np.zeros(1)
    ax2.plot(fe, ae, lw=0.7, color="#8b4513")
    ax2.set_xlim(0, 400)
    ax2.set_xlabel("频率 (Hz)", fontsize=8)
    ax2.set_ylabel("包络幅值", fontsize=8)
    ax2.tick_params(labelsize=7)
    ax2.grid(alpha=0.25, lw=0.4)
    ax2.set_title("包络谱 (0–400Hz，解调 1000–8000Hz)", fontsize=8.5)

    if rpm:
        _sh = _shaft_freqs(rpm)
        _marks = []
        for nm in report_bearing_names(project, point):
            brg = BEARING_LIB.get(nm)
            if not brg:
                continue
            code, mult = brg
            base = _sh.get(code, 0.0)
            if base <= 0:
                continue
            for key, color in (("BPFO", "#c00000"), ("BPFI", "#0070c0"), ("BSF", "#548235")):
                m_ord = mult.get(key)
                if m_ord and m_ord * base <= 400 and key not in [m[0] for m in _marks]:
                    _marks.append((key, m_ord * base, color))
        _ymax = ax2.get_ylim()[1]
        _ys = (0.95, 0.72, 0.50, 0.30)
        for _k, (key, hz, color) in enumerate(_marks):
            if hz > 400:
                continue
            ax2.axvline(hz, ls="--", lw=0.8, color=color, alpha=0.75)
            _hit = bool(mark and abs(hz - mark[1]) < 1.0)
            _txt = ("%s=%.1fHz" % (key, hz)) if _hit else key
            ax2.annotate(_txt, xy=(hz, _ymax * _ys[_k % 4]), fontsize=6.5 if _hit else 6.0,
                         color=color, rotation=90, va="top", ha="right",
                         fontweight="bold" if _hit else "normal")
    try:
        fig.tight_layout()
    except Exception:
        pass
    fig.savefig(out_png)
    return out_png


def report_fault_figure2(csv_paths, point, project, unit, out_png, mark=None):
    """故障多视图：时域波形与包络 / 包络自相关 / 包络阶次瀑布（多记录）。"""
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    if not csv_paths:
        return None
    path0 = csv_paths[0]
    info = parse_filename(os.path.basename(path0)) or {}
    fs = info.get("fs") or 20000
    rpm = info.get("speed") or 0
    if not rpm:
        return None
    try:
        raw = pd.read_csv(path0, header=None).iloc[:, 0]
        sig = pd.to_numeric(raw, errors="coerce").dropna().values.astype(float)
        if sig.size < fs * 0.3:
            return None
        lo = 1000.0
        hi = min(8000.0, fs / 2.0 * 0.95)
        if hi <= lo * 1.2:
            lo, hi = 400.0, hi
        filt = sosfiltfilt(design_band(fs, lo, hi, sos=True), sig)
        env = np.abs(hilbert(filt))
        n25 = min(len(sig), int(fs * 0.25))
        t = np.arange(n25) / float(fs)
        fig = Figure(figsize=(9.2, 5.8), dpi=200)
        FigureCanvasAgg(fig)
        ax1 = fig.add_subplot(221)
        ax2 = fig.add_subplot(222)
        ax3 = fig.add_subplot(212)
        ax1.plot(t, sig[:n25], lw=0.35, color="#1f4e79", label="加速度")
        ax1.plot(t, env[:n25], lw=1.1, color="#c00000", label="包络")
        ax1.set_xlabel("时间 (s)", fontsize=8)
        ax1.set_ylabel("加速度 (m/s2)", fontsize=8)
        ax1.tick_params(labelsize=7)
        ax1.legend(fontsize=6.5, loc="upper right", framealpha=0.6)
        ax1.grid(alpha=0.25, lw=0.4)
        ax1.set_title("时域波形与包络 (0-0.25s)", fontsize=8.5)
        e = env - np.mean(env)
        ac = np.correlate(e[:int(fs * 0.4)], e[:int(fs * 0.4)], mode="full")
        ac = ac[len(ac) // 2:]
        ac = ac / (ac[0] + 1e-12)
        lag = np.arange(len(ac)) / float(fs) * 1000.0
        keep = lag <= 35.0
        ax2.plot(lag[keep], ac[keep], lw=0.7, color="#8b4513")
        _ord = mark[2] if mark and len(mark) > 2 else None
        _fr = _shaft_freqs(rpm)
        _base = _fr.get("H", 0.0) or (rpm / 60.0)
        if _ord and _base > 0:
            for k in (1, 2, 3):
                per = 1000.0 / (_base * _ord * k)
                if per <= 35.0:
                    ax2.axvline(per, ls="--", lw=0.7, color="#0070c0", alpha=0.7)
        ax2.set_xlabel("延迟 (ms)", fontsize=8)
        ax2.set_ylabel("归一化自相关", fontsize=8)
        ax2.tick_params(labelsize=7)
        ax2.grid(alpha=0.25, lw=0.4)
        ax2.set_title("包络自相关", fontsize=8.5)
        _n = 0
        for k, cp in enumerate(csv_paths[:5]):
            pe, pa = report_env_curve(cp)
            if pe is None or pa is None:
                continue
            od = pe / (_base if _base > 0 else 1.0)
            keep2 = (od >= 1.2) & (od <= 5.6)
            if not keep2.any():
                continue
            ax3.plot(od[keep2], pa[keep2] + _n * 0.9, lw=0.5, color="#4a4a4a")
            _n += 1
        ax3.set_xlim(1.2, 5.6)
        ax3.set_xlabel("阶次 (×转频)", fontsize=8)
        ax3.set_ylabel("包络幅值 (记录)", fontsize=8)
        ax3.tick_params(labelsize=7)
        ax3.grid(alpha=0.25, lw=0.4)
        ax3.set_title("包络阶次瀑布（近 %d 条记录）" % max(1, _n), fontsize=8.5)
        if _ord:
            for k in (1, 2, 3):
                xo = _ord * k
                if 1.2 <= xo <= 5.6:
                    ax3.axvline(xo, ls="--", lw=0.7, color="#c00000", alpha=0.6)
        try:
            fig.tight_layout()
        except Exception:
            pass
        fig.savefig(out_png)
        _cf = float(np.max(np.abs(sig)) / (np.sqrt(np.mean(sig ** 2)) + 1e-12))
        _per = 0.0
        if _ord and _base > 0:
            _per = 1000.0 / (_base * _ord)
        return {"png": out_png, "cf": _cf, "period": _per, "n": max(1, _n)}
    except Exception:
        return None


def build_template_report(path, project, d0, d1, agg, rows, prof=None, cur=None,
                          scan_faults=True, fig_dir=None):
    """按人工月报模板生成：封面、注意事项、报告概述、运行状态、逐台机组（故障机组加图谱页）。"""
    from docx import Document
    from docx.shared import Pt, Cm, RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.enum.table import WD_TABLE_ALIGNMENT
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement

    HEAD_FONT, BODY_FONT = "黑体", "宋体"
    COLOR_HEAD = RGBColor(0x1F, 0x3B, 0x63)
    STATUS_FILL = {"正常": "C6EFCE", "数据异常": "E7E6E6", "关注": "FFF2CC",
                   "警告": "FFEB9C", "危险": "FFC7CE"}
    order = {"正常": 0, "数据异常": 1, "关注": 2, "警告": 3, "危险": 4}
    part_of = report_part_of

    _proj_key = str(project or "")
    if not any(_k in _proj_key for _k in ("田家寨", "府谷", "五峰")):
        _vs = [str(r.get("project")) for r in rows if r.get("project")]
        if _vs:
            _vs.sort(key=_vs.count, reverse=True)
            _proj_key = _vs[0]
    project = _proj_key                        # 轴承库/测点映射用项目关键字
    _pname = report_project_name(_proj_key)    # 显示名
    fault_info = report_scan_faults(agg, rows, project) if scan_faults else {}
    report_apply_faults(agg, fault_info, scan_faults)

    doc = Document()
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Cm(21.0), Cm(29.7)
    sec.left_margin = Cm(2.96)
    sec.right_margin = Cm(2.96)
    sec.top_margin = Cm(2.79)
    sec.bottom_margin = Cm(0.49)
    sec.footer_distance = Cm(0.9)
    sec.left_margin = sec.right_margin = Cm(2.2)
    sec.top_margin = Cm(2.3)
    sec.bottom_margin = Cm(2.0)
    sec.header_distance = Cm(1.2)
    sec.different_first_page_header_footer = True
    sec.footer_distance = Cm(1.0)
    st = doc.styles["Normal"]
    st.font.name = "Times New Roman"
    st.font.size = Pt(10.5)
    st.element.rPr.rFonts.set(qn("w:eastAsia"), BODY_FONT)
    st.paragraph_format.line_spacing = 1.5

    def _cn(run, cn=BODY_FONT):
        run.font.name = "Times New Roman"
        run._element.rPr.rFonts.set(qn("w:eastAsia"), cn)

    def para(text="", size=10.5, bold=False, cn=BODY_FONT, color=None, align=None,
             after=4, before=0, indent=True, line=1.5):
        p = doc.add_paragraph()
        pf = p.paragraph_format
        pf.space_before = Pt(before)
        pf.space_after = Pt(after)
        pf.line_spacing = line
        pf.first_line_indent = Pt(size * 2) if indent else Pt(0)
        if align is not None:
            p.alignment = align
        if text:
            r = p.add_run(text)
            r.font.size = Pt(size)
            r.bold = bold
            r.font.color.rgb = color if color else RGBColor(0, 0, 0)
            _cn(r, cn)
        return p

    def heading(text, size=12, before=8, after=6, align=None):
        p = doc.add_paragraph()
        pf = p.paragraph_format
        pf.space_before = Pt(before)
        pf.space_after = Pt(after)
        pf.line_spacing = 1.3
        pf.first_line_indent = Pt(0)
        pf.keep_with_next = True
        p.alignment = align if align is not None else WD_ALIGN_PARAGRAPH.LEFT
        r = p.add_run(text)
        r.font.size = Pt(size)
        r.bold = True
        r.font.color.rgb = COLOR_HEAD
        _cn(r, HEAD_FONT)
        return p

    def page_break():
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.space_after = Pt(0)
        p.add_run().add_break(__import__("docx").enum.text.WD_BREAK.PAGE)

    def shade(cell, color):
        tcPr = cell._tc.get_or_add_tcPr()
        shd = OxmlElement("w:shd")
        shd.set(qn("w:val"), "clear")
        shd.set(qn("w:color"), "auto")
        shd.set(qn("w:fill"), color)
        tcPr.append(shd)

    def cell_text(cell, text, size=9, bold=False, align=WD_ALIGN_PARAGRAPH.CENTER):
        cell.text = ""
        p = cell.paragraphs[0]
        p.alignment = align
        p.paragraph_format.first_line_indent = Pt(0)
        p.paragraph_format.space_before = Pt(1)
        p.paragraph_format.space_after = Pt(1)
        p.paragraph_format.line_spacing = 1.05
        for i, seg in enumerate(str(text).split("\n")):
            if i:
                p.add_run().add_break()
            r = p.add_run(seg)
            r.font.size = Pt(size)
            r.bold = bold
            _cn(r, HEAD_FONT if bold else BODY_FONT)

    def make_table(n_rows, n_cols, widths):
        t = doc.add_table(rows=n_rows, cols=n_cols)
        t.style = "Table Grid"
        t.alignment = WD_TABLE_ALIGNMENT.CENTER
        t.autofit = False
        tblPr = t._tbl.tblPr
        lay = OxmlElement("w:tblLayout")
        lay.set(qn("w:type"), "fixed")
        tblPr.append(lay)
        for i, w in enumerate(widths):
            t.columns[i].width = Cm(w)
            for row in t.rows:
                row.cells[i].width = Cm(w)
        return t

    # ---------------- 页眉页脚 ----------------
    hp = sec.header.paragraphs[0]
    hp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    hr = hp.add_run("%s %s振动分析报告" % (_pname, report_month_text(d0, d1)))
    hr.font.size = Pt(9)
    _cn(hr)
    pPr = hp._p.get_or_add_pPr()
    pbdr = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), "6")
    bottom.set(qn("w:space"), "1")
    bottom.set(qn("w:color"), "1F3B63")
    pbdr.append(bottom)
    pPr.append(pbdr)

    fp = sec.footer.paragraphs[0]
    fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = fp.add_run("第 ")
    r.font.size = Pt(9)
    _cn(r)
    fld = OxmlElement("w:fldSimple")
    fld.set(qn("w:instr"), "PAGE")
    fp._p.append(fld)
    r = fp.add_run(" 页 / 共 ")
    r.font.size = Pt(9)
    _cn(r)
    fld2 = OxmlElement("w:fldSimple")
    fld2.set(qn("w:instr"), "NUMPAGES")
    fp._p.append(fld2)
    r = fp.add_run(" 页")
    r.font.size = Pt(9)
    _cn(r)

    # ---------------- 封面 ----------------
    for _ in range(4):
        para("", after=6)
    para("检 测 报 告", size=28, bold=True, cn=HEAD_FONT, align=WD_ALIGN_PARAGRAPH.CENTER,
         indent=False, after=6)
    para("TEST  REPORT", size=16, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER, indent=False, after=40)
    para("受 检 样 品：    %s" % _pname, size=13, align=WD_ALIGN_PARAGRAPH.CENTER, indent=False, after=8)
    para("Sample", size=9, cn=BODY_FONT, align=WD_ALIGN_PARAGRAPH.CENTER, indent=False, after=16)
    para("检 测 类 型：    振动测试", size=13, align=WD_ALIGN_PARAGRAPH.CENTER, indent=False, after=8)
    para("Test  Type", size=9, align=WD_ALIGN_PARAGRAPH.CENTER, indent=False, after=16)
    para("报 告 日 期：    %s" % date.today().strftime("%Y.%m.%d"), size=13,
         align=WD_ALIGN_PARAGRAPH.CENTER, indent=False, after=8)
    para("Report  Date", size=9, align=WD_ALIGN_PARAGRAPH.CENTER, indent=False, after=80)
    para(REPORT_COMPANY, size=12, bold=True, cn=HEAD_FONT, align=WD_ALIGN_PARAGRAPH.CENTER,
         indent=False, after=4)
    para(REPORT_COMPANY_EN, size=10, align=WD_ALIGN_PARAGRAPH.CENTER, indent=False, after=4)
    page_break()

    # ---------------- 注意事项 ----------------
    heading("注　意　事　项", size=14, before=2, after=14)
    for _n in REPORT_NOTES:
        para(_n, size=10.5, indent=False, after=10)
    para("", after=10)
    para("地址：中国广东省珠海市香洲区银桦路 102 号", size=10.5, indent=False, after=8)
    para("Add: China's Zhuhai City of Guangdong Province Xiangzhou District Yinhua Road 102",
         size=9, indent=False, after=8)
    para("邮编 Post：519000    电话 Tel：0756-2552328    传真 Fax：0756-2552119",
         size=10.5, indent=False, after=4)
    page_break()

    # ---------------- 1. 报告概述 ----------------
    units = sorted(agg.keys(), key=tree_unit_order)
    n_pt = sum(len(v) for v in agg.values())
    dates = [str(r.get("dt_str") or "") for r in rows if r.get("dt_str")]
    heading("1. 报告概述", size=16, before=0, after=8)
    heading("1.1 检测报告", size=12, before=6, after=6)
    info = [
        ("样 品 名 称\nSample Name", _pname, "样 品 地 址\nSample Add", ""),
        ("样 品 数 量\nSample Quantity", "%d" % len(units), "样 品 编 号\nSample No", ""),
        ("规 格 型 号\nSpecification", "MY2000kw", "样 品 状 态\nSample State", "运行状态"),
        ("委 托 单 位\nApplicant", "", "委 托 人\n      Client", ""),
        ("测 试 日 期\nTesting Date", "%s" % ("%d.%d" % (d0.year, d0.month) if d0 else "-"),
         "检 测 方 式\nTesting Type", "在线监测"),
        ("检 测 标 准\nTesting Standard", "VDI 3834", "", ""),
        ("监 测 设 备\nTesting Equipment", "", "", ""),
        ("报告责任人\nResponsible", "", "报告日期\n      Report Date", date.today().strftime("%Y.%m.%d")),
    ]
    t = make_table(len(info) + 2, 4, [3.76, 3.80, 3.72, 3.81])
    t.cell(0, 0).merge(t.cell(0, 3))
    _tc = t.cell(0, 0)
    cell_text(_tc, "", size=9)
    _p0 = _tc.paragraphs[0]
    _r0 = _p0.add_run("检 测 报 告")
    _r0.bold = True
    _r0.font.size = Pt(16)
    _cn(_r0, HEAD_FONT)
    _p1 = _tc.add_paragraph()
    _p1.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _r1 = _p1.add_run("TEST REPORT")
    _r1.bold = True
    _r1.font.size = Pt(12)
    _cn(_r1)
    for i, rec in enumerate(info, start=1):
        for j, v in enumerate(rec):
            cell_text(t.cell(i, j), v, size=9, bold=(j % 2 == 0))
            if j % 2 == 0:
                shade(t.cell(i, j), "DCE6F1")
    # 检测标准/监测设备 行的右侧合并
    t.cell(6, 1).merge(t.cell(6, 3))
    t.cell(7, 1).merge(t.cell(7, 3))
    # 末尾两行：测试数据分析结果 + 概述
    _last = len(info) + 1
    t.cell(_last, 0).merge(t.cell(_last, 3))
    _tc = t.cell(_last, 0)
    cell_text(_tc, "测试数据分析结果", size=9, bold=True)
    _tc.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
    # 概述正文
    _n_nd = len((cur or {}).get("no_data_units") or [])
    _bad_pt = [(u, pt, d) for u in units for pt, d in agg[u].items() if d.get("data_bad")]
    _alarm = [(u, pt, d) for u in units for pt, d in agg[u].items() if d.get("fault")]
    _big = [(u, pt, d) for u in units for pt, d in agg[u].items()
            if d.get("ratio", 0) >= 0.8 and not d.get("fault") and not d.get("data_bad")]
    para("")
    _ov = _tc.add_paragraph()
    _ov.paragraph_format.first_line_indent = Pt(0)
    _ov.paragraph_format.space_after = Pt(4)
    _ro = _ov.add_run("1、概述")
    _ro.bold = True
    _ro.font.size = Pt(10.5)
    _cn(_ro, HEAD_FONT)
    _ov2 = _tc.add_paragraph()
    _ov2.paragraph_format.first_line_indent = Pt(21)
    _ov2.paragraph_format.line_spacing = 1.5
    _co = _ov2.add_run("本报告针对 %s 在线监测数据进行分析，共有 %d 台机组列入报告，测点 %d 个，有效记录 %d 条，"
                       "记录时间从 %s 至 %s。"
                       % (report_month_text(d0, d1), len(units), n_pt, len(rows),
                          (min(dates)[:16] if dates else "-"), (max(dates)[:16] if dates else "-")))
    _co.font.size = Pt(10.5)
    _cn(_co)
    _ov3 = _tc.add_paragraph()
    _ov3.paragraph_format.first_line_indent = Pt(21)
    _ov3.paragraph_format.line_spacing = 1.5
    _sent = []
    if _bad_pt:
        _sent.append("测点数据异常：%s（振动值仅为同型机组的 %.0f%%~%.0f%%，判断为传感器安装或采集通道问题，需现场核查）"
                     % ("、".join("%s %s" % (u, report_point_cn(pt)) for u, pt, d in _bad_pt[:6]),
                        min(d.get("max", 0) / max(1e-9, d.get("peer_med", 1)) * 100 for u, pt, d in _bad_pt),
                        max(d.get("max", 0) / max(1e-9, d.get("peer_med", 1)) * 100 for u, pt, d in _bad_pt)))
    if _alarm:
        _sent.append("通过包络谱分析可知，%s 存在轴承故障阶次（%s），等级：警告"
                     % ("、".join("%s %s" % (u, report_point_cn(pt)) for u, pt, d in _alarm),
                        "；".join(d.get("fault_lab", "") for u, pt, d in _alarm[:4])))
    if _n_nd:
        _sent.append("另有 %d 台机组本期无有效数据" % _n_nd)
    if _big:
        _sent.append("%d 个测点振动值偏大（占第一限度 ≥80%%）但未见故障特征，判为正常" % len(_big))
    if not _alarm and fault_info is not None and REPORT_SCAN_STAT.get("points"):
        _mp = int(REPORT_SCAN_STAT.get("missing") or 0)
        _tp = int(REPORT_SCAN_STAT.get("points") or 0)
        if _mp:
            _sent.append("包络谱扫描覆盖 %d 个测点，其中 %d 个测点因数据文件缺失未能完成分析，本期未发现轴承故障阶次"
                         % (_tp, _mp))
        else:
            _sent.append("包络谱扫描覆盖 %d 个测点，未发现轴承故障阶次" % _tp)
    if not _sent:
        _sent.append("各机组测点振动值均在第一限度以内，未发现轴承故障特征")
    _cs = _ov3.add_run("；".join(_sent) + "；其余机组运行正常。")
    _cs.font.size = Pt(10.5)
    _cn(_cs)

    # ---------------- 2. 运行状态 ----------------
    para("", after=6)
    _pb = doc.add_paragraph()
    _pb.paragraph_format.space_after = Pt(4)
    _pb.paragraph_format.page_break_before = True
    _u1 = [u for u in units if (int(re.sub(r"\D", "", u) or 0)) <= 15]
    _u2 = [u for u in units if (int(re.sub(r"\D", "", u) or 0)) > 15]
    _W = [0.15, 1.25, 3.6, 3.6, 3.6, 0.15]
    for _grp, _idx in ((_u1, 0), (_u2, 1)):
        _nr = len(_grp) + (3 if _idx == 0 else 1)
        if _idx:
            para("", after=2)
        t = make_table(_nr, 6, _W)
        _r = 0
        if _idx == 0:
            t.cell(0, 0).merge(t.cell(0, 5))
            _tc0 = t.cell(0, 0)
            cell_text(_tc0, "2、运行状态", size=10.5, bold=True)
            _p = _tc0.add_paragraph()
            _p.paragraph_format.first_line_indent = Pt(0)
            _rr = _p.add_run("机组运行状况是依据 VDI3834 标准进行时域统计评估，并结合现场运行状况进行"
                             "频域 特征分析，最终得出机组健康状态，如下表所示：")
            _rr.font.size = Pt(9)
            _cn(_rr)
            _r = 1
        for _j, _v in enumerate(["机组编号", "主轴承", "齿轮箱", "发电机"], start=1):
            cell_text(t.cell(_r, _j), _v, size=9, bold=True)
            shade(t.cell(_r, _j), "DCE6F1")
        _r += 1
        if _idx == 0:
            t.cell(_r, 1).merge(t.cell(_r, 4))
            cell_text(t.cell(_r, 1), "共监测明阳机组 %d 台，列入报告 %d 台" % (len(units), len(units)), size=9)
            _r += 1
        for u in _grp:
            cell_text(t.cell(_r, 1), u, size=9)
            for _j, part in enumerate(("主轴承", "齿轮箱", "发电机"), start=2):
                gs = [d["grade"] for pt, d in agg[u].items() if part_of(pt) == part]
                g = max(gs, key=lambda x: order.get(x, 0)) if gs else "—"
                cell_text(t.cell(_r, _j), g, size=9)
                if g in STATUS_FILL:
                    shade(t.cell(_r, _j), STATUS_FILL[g])
            _r += 1

    heading("2.2 故障等级说明", size=12, before=10, after=6)
    for _g, _col, _txt in (("正常", "C6EFCE", "运行状态处于正常状态，机组可照常运行。"),
                           ("警告", "FFEB9C", "有较明显的故障特征，并且故障在发展，机组必须在一个月内采取维修措施。"),
                           ("危险", "FFC7CE", "机组故障严重，会产生设备损坏，机组必须立即停机，采取维修措施。")):
        p = doc.add_paragraph()
        p.paragraph_format.first_line_indent = Pt(0)
        p.paragraph_format.space_after = Pt(4)
        r = p.add_run("　%s　" % _g)
        r.font.size = Pt(9)
        r.bold = True
        rPr = r._element.get_or_add_rPr()
        shd = OxmlElement("w:shd")
        shd.set(qn("w:val"), "clear")
        shd.set(qn("w:color"), "auto")
        shd.set(qn("w:fill"), _col)
        rPr.append(shd)
        r2 = p.add_run("：%s" % _txt)
        r2.font.size = Pt(10.5)
        _cn(r2)

    # ---------------- 3. 详细分析 ----------------
    page_break()
    heading("3. 详细分析", size=16, before=0, after=10)
    _figs = fig_dir or os.path.join(os.path.dirname(os.path.abspath(path)), "figs_%s" %
                                    datetime.now().strftime("%Y%m%d_%H%M%S"))
    try:
        os.makedirs(_figs, exist_ok=True)
    except Exception:
        _figs = os.path.dirname(os.path.abspath(path))

    for _ui, u in enumerate(units):
        pts_sorted = sorted(agg[u].keys(), key=tree_point_order)
        _fl = [(pt, d) for pt, d in agg[u].items() if d.get("fault")]
        if _ui:
            page_break()
        heading("%d  %s机组" % (int(re.sub(r"\D", "", u) or 0), u), size=14, before=0, after=10)
        # N.1 机组状态评估
        heading("%d.1 机组状态评估" % int(re.sub(r"\D", "", u) or 0), size=12, before=4, after=6)
        t = make_table(3, 4, [4.1, 4.1, 4.1, 4.1])
        t.cell(0, 0).merge(t.cell(0, 3))
        cell_text(t.cell(0, 0), "MY2000kw", size=9, bold=True)
        shade(t.cell(0, 0), "DCE6F1")
        cell_text(t.cell(1, 0), "诊断部位", size=9, bold=True)
        cell_text(t.cell(2, 0), "故障等级", size=9, bold=True)
        for j, part in enumerate(("主轴承", "齿轮箱", "发电机"), start=1):
            cell_text(t.cell(1, j), part, size=9, bold=True)
            gs = [d["grade"] for pt, d in agg[u].items() if part_of(pt) == part]
            g = max(gs, key=lambda x: order.get(x, 0)) if gs else "—"
            cell_text(t.cell(2, j), g, size=9)
            if g in STATUS_FILL:
                shade(t.cell(2, j), STATUS_FILL[g])
        # N.2 VDI3834 标准
        heading("%d.2 VDI3834 标准" % int(re.sub(r"\D", "", u) or 0), size=12, before=10, after=6)
        nrow = 3 + len(pts_sorted)
        t = make_table(nrow, 7, [1.6, 1.8, 5.4, 1.9, 2.3, 1.7, 1.7])
        t.cell(0, 0).merge(t.cell(0, 1))          # 测试工况
        cell_text(t.cell(0, 0), "测试工况", size=8.5, bold=True)
        t.cell(0, 2).merge(t.cell(0, 4))          # 测试数据时域统计
        cell_text(t.cell(0, 2), "测试数据时域统计", size=8.5, bold=True)
        t.cell(0, 5).merge(t.cell(1, 5))          # VDI 标准第一限度
        cell_text(t.cell(0, 5), "VDI 标准\n第一限度", size=8.5, bold=True)
        t.cell(0, 6).merge(t.cell(1, 6))          # 占标准比例
        cell_text(t.cell(0, 6), "占标准\n比例(%)", size=8.5, bold=True)
        cell_text(t.cell(1, 0), "机组\n编号", size=8.5, bold=True)
        cell_text(t.cell(1, 1), "发电机\n转速", size=8.5, bold=True)
        cell_text(t.cell(1, 2), "测点安装位置", size=8.5, bold=True)
        cell_text(t.cell(1, 3), "频率范围", size=8.5, bold=True)
        cell_text(t.cell(1, 4), "rms (m/s²)", size=8.5, bold=True)
        for j in range(7):
            shade(t.cell(0, j), "DCE6F1")
            shade(t.cell(1, j), "DCE6F1")
        if len(pts_sorted):
            t.cell(2, 0).merge(t.cell(nrow - 2, 0))
            t.cell(2, 1).merge(t.cell(nrow - 2, 1))
        _spd = ""
        for pt in pts_sorted:
            r0 = next((r for r in rows if report_unit_label(r.get("unit"), r.get("project")) == u
                       and r.get("point") == pt and r.get("speed")), None)
            if r0:
                _spd = "%s rpm" % int(r0.get("speed"))
                break
        cell_text(t.cell(2, 0), u, size=9)
        cell_text(t.cell(2, 1), _spd or "—", size=9)
        for i, pt in enumerate(pts_sorted, start=2):
            d = agg[u][pt]
            cell_text(t.cell(i, 2), report_point_cn(pt), size=9)
            cell_text(t.cell(i, 3), d["band"].replace(" Hz", ""), size=9)
            _v = d["max"]
            cell_text(t.cell(i, 4), ("%.4f" % _v) if _v < 0.01 else "%.2f" % _v, size=9)
            cell_text(t.cell(i, 5), "%.1f" % d["limit"], size=9)
            cell_text(t.cell(i, 6), "%.1f%%" % (d["ratio"] * 100), size=9)
        _lastr = nrow - 1
        t.cell(_lastr, 0).merge(t.cell(_lastr, 1))
        cell_text(t.cell(_lastr, 0), "评估分析", size=9, bold=True)
        t.cell(_lastr, 2).merge(t.cell(_lastr, 6))
        _rs = [d["ratio"] * 100.0 for d in agg[u].values()]
        _rtxt = ("各测点振动有效值占 VDI3834 标准第一限度比例 %.1f%%~%.1f%%。" % (min(_rs), max(_rs))
                 if _rs else "本月该机组无有效测点数据，测点数据异常。")
        _bd = [report_point_cn(pt) for pt, d in agg[u].items() if d.get("data_bad")]
        if _bd:
            _rtxt += "测点数据异常：%s。" % "、".join(_bd)
        cell_text(t.cell(_lastr, 2), _rtxt, size=9)
        t.cell(_lastr, 2).paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.LEFT

        _num = int(re.sub(r"\D", "", u) or 0)
        if _fl:
            # 诊断分析页
            page_break()
            heading("%d.3 诊断分析" % _num, size=12, before=0, after=6)
            _pt, _d = max(_fl, key=lambda x: x[1].get("amp", 0))
            _f = fault_info.get((u, _pt), {})
            heading("%s存在轴承故障特征" % report_point_cn(_pt), size=11, before=2, after=6)
            fig_png = os.path.join(_figs, "fig_%s.png" % _num)
            _ok = False
            try:
                _ok = bool(report_fault_figure(_d.get("csv", ""), _pt, project, u, fig_png,
                               mark=(str(_f.get("label", "")).split("×")[0], _f.get("hz", 0.0))))
            except Exception:
                _ok = False
            if _ok:
                p = doc.add_paragraph()
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                p.paragraph_format.first_line_indent = Pt(0)
                p.add_run().add_picture(fig_png, width=Cm(15.0))
            _cap = "图%d-1  %s测点包络谱图（%s）" % (_num, report_point_cn(_pt), (_d.get("ts") or "")[:16])
            para(_cap, size=9, align=WD_ALIGN_PARAGRAPH.CENTER, indent=False, after=8)
            _lab = _f.get("label", "BPFO×1")
            _hz = _f.get("hz", 0.0)
            _amp = _f.get("amp", 0.0)
            _base = 0.0
            try:
                _base = float(re.search(r"(\d+)", _spd).group(1)) / 60.0 if _spd else 0.0
            except Exception:
                _base = 0.0
            para("如图 %d-1 所示，%s测点包络谱图中存在 %.1fHz 及其倍频，1x 幅值约为 %.2f，"
                 "对应转频为 %.2fHz。根据轴承型号及参数（%s，%s 为 %.3f 倍转频），判断 %.1fHz 为 %s 的故障频率；"
                 "该峰族在本期记录中稳定出现，由谱图特征判断故障处于早中期阶段，建议加强跟踪监测。"
                 % (_num, report_point_cn(_pt), _hz, _amp, _base,
                    _f.get("bearing", "—"), _lab.split("×")[0],
                    (_f.get("order", 0.0) or 0.0), _hz, report_point_cn(_pt)),
                 indent=True, after=8)
            _cands = [r for r in rows if r.get("csv_path") and r.get("point") == _pt
                      and report_unit_label(r.get("unit"), r.get("project") or project) == u]
            _cands.sort(key=lambda r: (r.get("ge") or 0.0), reverse=True)
            _cps = []
            for _r in _cands:
                _cp = _r.get("csv_path")
                if _cp and _cp not in _cps:
                    _cps.append(_cp)
                if len(_cps) >= 5:
                    break
            if _d.get("csv"):
                if _d["csv"] in _cps:
                    _cps.remove(_d["csv"])
                _cps.insert(0, _d["csv"])
            _res2 = None
            try:
                _res2 = report_fault_figure2(_cps, _pt, project, u,
                                             os.path.join(_figs, "fig2_%s.png" % _num),
                                             mark=(str(_f.get("label", "")).split("×")[0],
                                                   _f.get("hz", 0.0), _f.get("order", 0.0)))
            except Exception:
                _res2 = None
            if _res2:
                p2 = doc.add_paragraph()
                p2.alignment = WD_ALIGN_PARAGRAPH.CENTER
                p2.paragraph_format.first_line_indent = Pt(0)
                p2.paragraph_format.keep_with_next = True
                p2.paragraph_format.page_break_before = True
                p2.add_run().add_picture(_res2["png"], width=Cm(15.0))
                _cap2 = "图%d-2  %s测点时域波形/包络自相关/包络阶次瀑布（近 %d 条记录）" % (
                    _num, report_point_cn(_pt), _res2.get("n", 1))
                para(_cap2, size=9, align=WD_ALIGN_PARAGRAPH.CENTER, indent=False, after=8)
                para("如图 %d-2 所示，时域波形存在周期性冲击（峰值因子 %.2f），包络自相关在 %.2fms 处出现明显周期峰；"
                     "包络阶次瀑布中 %.2f 倍阶次谱线在多条记录中稳定存在，与包络谱判断一致。"
                     % (_num, _res2.get("cf", 0.0), _res2.get("period", 0.0),
                        (_f.get("order", 0.0) or 0.0)),
                     indent=True, after=8)
            heading("%d.4 诊断结论" % _num, size=12, before=8, after=6)
            para("%s存在轴承故障特征（%s），等级：警告。" % (report_point_cn(_pt), _f.get("label", "")),
                 indent=True, after=8)
            heading("%d.5 处理建议" % _num, size=12, before=8, after=6)
            _part = part_of(_pt)
            if _part == "发电机":
                _adv = "检查发电机轴承润滑与装配状态，结合停机检查确认损伤程度，必要时安排更换。"
            elif _part == "齿轮箱":
                _adv = "检查齿轮箱对应轴承与齿面状态，复核润滑油质与油温，必要时安排开箱检查。"
            else:
                _adv = "检查主轴承润滑与密封状态，结合停机内窥检查确认损伤程度。"
            para(_adv, indent=True, after=6)
        else:
            heading("%d.3 诊断结论" % _num, size=12, before=10, after=6)
            _badp = [(pt, d) for pt, d in agg[u].items() if d.get("data_bad")]
            if _badp:
                _t = "、".join("%s（最大 %.4f m/s²，仅为同型机组的 %.0f%%）"
                              % (pt, d["max"], d["max"] / max(1e-9, d.get("peer_med", 1)) * 100)
                              for pt, d in _badp)
                para("机组传动链运行正常；%s 测点数据异常，疑似传感器安装或采集通道问题，建议重新安装并核查该测点。" % _t,
                     indent=True, after=6)
            else:
                para("机组传动链运行正常。", indent=True, after=6)

    doc.save(path)
    return path


def build_report_docx(path, project, d0, d1, agg, rows, prof=None, cur=None, scan_faults=True):
    """生成 Word 分析报告：概况 + 状态汇总 + 超限测点 + 分机组明细 + 无数据/对比/历史 + 结论。
    prof/cur 为项目档案与本期记录，用于“与上期对比”“历史报警记录”。"""
    from docx import Document
    from docx.shared import Pt, Cm, RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.enum.table import WD_TABLE_ALIGNMENT
    from docx.enum.section import WD_ORIENT
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement

    HEAD_FONT = "黑体"
    BODY_FONT = "宋体"
    COLOR_HEAD = RGBColor(0x1F, 0x3B, 0x63)
    STATUS_FILL = {"正常": "C6EFCE", "关注": "FFF2CC", "警告": "FFEB9C", "危险": "FFC7CE", "数据异常": "E7E6E6"}

    doc = None
    _tmpl = profile_template(prof)
    if _tmpl:
        try:
            doc = Document(_tmpl)          # 沿用项目模板的页面设置与样式
            _body = doc.element.body
            for _ch in list(_body):
                if not _ch.tag.endswith("}sectPr"):
                    _body.remove(_ch)
        except Exception:
            doc = None
    if doc is None:
        doc = Document()
    sec = doc.sections[0]
    if _tmpl:
        for _hf in (sec.header, sec.footer):      # 模板的页眉页脚整段清空，避免串项目名/残留横线
            _el = _hf._element
            for _ch in list(_el):
                if _ch.tag.endswith("}p") or _ch.tag.endswith("}tbl"):
                    _el.remove(_ch)
            _el.append(OxmlElement("w:p"))
    sec.page_width, sec.page_height = Cm(21.0), Cm(29.7)
    sec.left_margin = sec.right_margin = Cm(2.2)
    sec.top_margin = Cm(2.4)
    sec.bottom_margin = Cm(2.2)
    st = doc.styles["Normal"]
    st.font.name = "Times New Roman"
    st.font.size = Pt(10.5)
    st.element.rPr.rFonts.set(qn("w:eastAsia"), BODY_FONT)

    def para(text, size=10.5, bold=False, cn=BODY_FONT, color=None, align=None,
             before=0, after=6, line=1.5):
        p = doc.add_paragraph()
        r = p.add_run(text)
        r.bold = bold
        r.font.size = Pt(size)
        r.font.color.rgb = color or RGBColor(0, 0, 0)
        _docx_cn(r, cn)
        if align is not None:
            p.alignment = align
        pf = p.paragraph_format
        pf.space_before = Pt(before)
        pf.space_after = Pt(after)
        pf.line_spacing = line
        return p

    def heading(text, size=14):
        return para(text, size=size, bold=True, cn=HEAD_FONT, color=COLOR_HEAD, before=10, after=6)

    def table(headers, data, widths=None, head_fill="DCE6F1", status_col=None):
        t = doc.add_table(rows=1, cols=len(headers))
        t.style = "Table Grid"
        t.alignment = WD_TABLE_ALIGNMENT.CENTER
        hdr = t.rows[0]
        _trPr = hdr._tr.get_or_add_trPr()
        _th = OxmlElement("w:tblHeader"); _trPr.append(_th)
        for i, h in enumerate(headers):
            c = hdr.cells[i]
            c.text = ""
            p = c.paragraphs[0]
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            r = p.add_run(h)
            r.bold = True
            r.font.size = Pt(9)
            _docx_cn(r, HEAD_FONT)
            _docx_shade(c, head_fill)
        for row in data:
            cells = t.add_row().cells
            for i, v in enumerate(row):
                cells[i].text = ""
                p = cells[i].paragraphs[0]
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                r = p.add_run(str(v))
                r.font.size = Pt(9)
                _docx_cn(r, BODY_FONT)
                if status_col is not None and i == status_col:
                    _docx_shade(cells[i], STATUS_FILL.get(str(v), "FFFFFF"))
        for row in t.rows:
            _rp = row._tr.get_or_add_trPr()
            if _rp.find(qn("w:cantSplit")) is None:
                _rp.append(OxmlElement("w:cantSplit"))
        if widths:
            t.autofit = False
            _tblPr = t._tbl.tblPr
            _lay = OxmlElement("w:tblLayout"); _lay.set(qn("w:type"), "fixed"); _tblPr.append(_lay)
            for i, w in enumerate(widths):
                t.columns[i].width = Cm(w)
                for row in t.rows:
                    row.cells[i].width = Cm(w)
        return t

    # ---------- 标题 ----------
    para("%s 振动分析报告" % project, size=20, bold=True, cn=HEAD_FONT,
         color=COLOR_HEAD, align=WD_ALIGN_PARAGRAPH.CENTER, before=30, after=10)
    para("统计时间段：%s ～ %s" % (d0.isoformat() if d0 else "最早", d1.isoformat() if d1 else "最新"),
         size=12, align=WD_ALIGN_PARAGRAPH.CENTER, after=4)
    para("报告生成时间：%s" % datetime.now().strftime("%Y-%m-%d %H:%M"),
         size=10.5, align=WD_ALIGN_PARAGRAPH.CENTER, after=18)

    # ---------- 包络谱判定：谱图报警才写报警 ----------
    fault_info = {}
    _fi = report_scan_faults(agg, rows, project) if scan_faults else {}
    report_apply_faults(agg, _fi, scan_faults)

    # ---------- 一、数据概况 ----------
    units = sorted(agg.keys(), key=tree_unit_order)
    n_pt = sum(len(v) for v in agg.values())
    dates = [str(r.get("dt_str") or "") for r in rows if r.get("dt_str")]
    heading("一、数据概况")
    para("本报告基于振动在线监测数据自动生成。统计时间段内共 %d 台机组、%d 个测点、%d 条有效记录，"
         "记录时间从 %s 至 %s。" % (len(units), n_pt, len(rows),
                                 min(dates) if dates else "-", max(dates) if dates else "-"),
         after=6)
    para("计算口径：每个测点按 VDI 3834 频带取带内 RMS（主轴、齿轮箱输入端、齿轮箱一级齿圈取 0.1–10 Hz；"
         "齿轮箱高速轴取 10–1000 Hz；发电机前后轴承取 10–5000 Hz），取时间段内最大值与平均值；"
         "占第一限度比例 = 最大带内 RMS ÷ 对应频带第一限度。", after=6)
    table(["频带", "适用测点", "第一限度 (m/s²)"],
          [["0.1–10 Hz", "主轴、齿轮箱输入端、齿轮箱一级齿圈", "0.3"],
           ["10–1000 Hz", "齿轮箱高速轴（含中部/低速轴等）", "7.5"],
           ["10–5000 Hz", "发电机前后轴承", "10"]],
          widths=[3.2, 9.0, 4.0])
    para("等级判定：以包络谱（解调带 1000–8000 Hz）中的轴承故障阶次为准——出现 BPFO/BPFI/BSF 基频峰值、"
         "幅值 ≥ %.1f 且 ≥ %.0f 倍同型测点中位数时判“警告”，否则判“正常”；VDI 3834 第一限度占比仅作振动量级参考，不单独定级。"
         % (ENV_FAULT_AMP_MIN, ENV_FAULT_REL), size=9, after=10)

    # ---------- 二、机组状态汇总 ----------
    heading("二、机组状态汇总")
    order = {"正常": 0, "数据异常": 1, "关注": 2, "警告": 3, "危险": 4}
    data = []
    worst = {}
    for u in units:
        row = [u]
        unit_worst = "正常"
        for part in REPORT_PART:
            pts = [d for pt, d in agg[u].items() if report_part_of(pt) == part]
            if not pts:
                row.append("—")
                continue
            g = max((d["grade"] for d in pts), key=lambda x: order.get(x, 0))
            row.append(g)
            if order.get(g, 0) > order.get(unit_worst, 0):
                unit_worst = g
        mx = max((d["ratio"] for d in agg[u].values()), default=0.0)
        row.append("%.0f%%" % (mx * 100))
        row.append(unit_worst)
        worst[u] = unit_worst
        data.append(row)
    table(["机组", "主轴承", "齿轮箱", "发电机", "最高占限比", "判定等级"], data,
          widths=[1.9, 3.0, 3.0, 3.0, 3.1, 2.4], status_col=5)

    # ---------- 三、超限测点清单 ----------
    heading("三、超限测点清单")
    over = []
    for u in units:
        for pt, d in agg[u].items():
            if d["ratio"] >= 0.8:
                over.append([u, pt, d["band"], "%.3f" % d["max"], "%.1f" % d["limit"],
                             "%.0f%%" % (d["ratio"] * 100), d["ts"][:16], d["grade"]])
    over.sort(key=lambda r: -float(r[5].rstrip("%")))
    if over:
        para("时间段内共有 %d 个测点达到或超过第一限度的 80%%，按占比从高到低排列：" % len(over), after=6)
        table(["机组", "测点", "频带", "最大RMS", "第一限度", "占限比", "最大值时刻", "等级"],
              over, widths=[1.6, 4.6, 2.6, 2.3, 2.1, 1.8, 3.1, 1.5], status_col=7)
        _alarms = [(u, pt, d) for u in units for pt, d in agg[u].items() if d.get("fault")]
        _big = sum(1 for u in units for pt, d in agg[u].items() if d.get("ratio", 0) >= 0.8 and not d.get("fault"))
        if _big:
            para("注：另有 %d 个测点振动值偏大（占第一限度 ≥80%%）但包络谱未见轴承故障阶次，判为正常，建议持续跟踪。" % _big,
                 size=9, after=4)
        if _alarms:
            para("包络谱报警测点：" + "；".join("%s %s（%s）" % (u, pt, d.get("fault_lab", "")) for u, pt, d in _alarms),
                 size=9, after=8)
    else:
        para("时间段内所有测点带内 RMS 均低于第一限度的 80%，机组运行状态稳定。", after=6)

    # ---------- 四、分机组明细 ----------
    heading("四、分机组测点明细")
    for u in units:
        pts = sorted(agg[u].keys(), key=tree_point_order)
        para("%s机组" % u, size=11, bold=True, cn=HEAD_FONT, before=8, after=4)
        data = []
        for pt in pts:
            d = agg[u][pt]
            data.append([pt, d["band"], "%.3f" % d["mean"], "%.3f" % d["max"],
                         "%.1f" % d["limit"], "%.0f%%" % (d["ratio"] * 100),
                         d["ts"][:16], d["grade"]])
        table(["测点", "频带", "平均RMS", "最大RMS", "第一限度", "占限比", "最大值时刻", "等级"],
              data, widths=[4.4, 2.6, 2.2, 2.2, 2.0, 1.8, 3.1, 1.5], status_col=7)

    # ---------- 五、无数据机组与测点 ----------
    heading("五、数据异常与无数据测点")
    _dbad = [(u, pt, d) for u in units for pt, d in sorted(agg[u].items()) if d.get("data_bad")]
    if _dbad:
        para("数值异常测点（远低于同型机组，疑似传感器未可靠安装或采集通道故障，本期不纳入趋势对比）：", after=4)
        for _u, _pt, _d in _dbad:
            para("· %s %s：最大值 %.4f m/s²，仅为同型中位（%.4f）的 %.0f%%。"
                 % (_u, _pt, _d["max"], _d.get("peer_med", 0.0),
                    (_d["max"] / _d["peer_med"] * 100.0) if _d.get("peer_med") else 0), size=9, after=2)
    nd_u = (cur or {}).get("no_data_units") or []
    nd_p = (cur or {}).get("no_data_points") or []
    if nd_u:
        para("本期缺数机组（历史有数据、本期无数据）：%s。" % "、".join(nd_u), after=4)
    if nd_p:
        para("本期缺数测点：%s。" % "；".join("%s %s" % (x["unit"], "、".join(x["points"]))
                                          for x in nd_p), after=4)
    if not nd_u and not nd_p:
        para("本期全部机组、全部测点均有有效数据。", after=4)

    # ---------- 六、历史报警记录 ----------
    heading("六、历史报警记录")
    _hist = []
    for _k in sorted((prof or {}).get("periods") or {}):
        if _k == (cur or {}).get("label"):
            continue
        for a in (prof["periods"][_k].get("alarms") or []):
            _hist.append([_k, a["unit"], a["point"], "%.0f%%" % (a["ratio"] * 100),
                          a["grade"], a.get("time", "")])
    _hist = _hist[-40:]
    if _hist:
        table(["期次", "机组", "测点", "占限比", "等级", "最大值时刻"], _hist,
              widths=[2.0, 1.8, 5.0, 1.9, 1.8, 3.6], status_col=4)
    else:
        para("暂无历史报警记录（生成第二期报告后自动累积）。", after=4)

    # ---------- 七、结论 ----------
    heading("七、结论")
    bad = [u for u in units if worst.get(u) in ("警告", "危险")]
    dgr = [u for u in units if worst.get(u) == "危险"]
    att = [u for u in units if worst.get(u) == "关注"]
    _no = 1
    if dgr:
        para("（%d）%s 等 %d 台机组有测点达到危险等级（超第一限度 150%%），建议尽快安排停机检查。"
             % (_no, "、".join(dgr), len(dgr)), after=4)
        _no += 1
    bad_w = [u for u in bad if worst.get(u) != "危险"]
    if bad_w:
        para("（%d）%s 等 %d 台机组存在振动超限测点（警告等级），建议结合频谱与包络分析确认故障部位，加强跟踪。"
             % (_no, "、".join(bad_w), len(bad_w)), after=4)
        _no += 1
    _badu = []
    for _u in units:
        if any(d.get("data_bad") for d in agg[_u].values()) and _u not in _badu:
            _badu.append(_u)
    if _badu:
        para("（%d）%s 等 %d 台机组存在测点数据异常（振动值远低于同型机组），建议核查传感器安装与采集通道。"
             % (_no, "、".join(_badu), len(_badu)), after=4)
        _no += 1
    if att:
        para("（%d）%s 等 %d 台机组有个别测点接近第一限度，建议加强跟踪监测。"
             % (_no, "、".join(att), len(att)), after=4)
    if not bad and not att:
        para("时间段内各机组各测点振动值均在第一限度以内，机组传动链运行正常。", after=4)
    para("说明：本报告为按时间段统计的自动生成结果，故障判定需结合包络谱、阶次谱等图谱分析综合判断。",
         size=9, after=6)

    # ---------- 页脚页码 ----------
    footer_p = sec.footer.paragraphs[0]
    footer_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = footer_p.add_run("第 ")
    r.font.size = Pt(9)
    _docx_cn(r)
    fld = OxmlElement("w:fldSimple")
    fld.set(qn("w:instr"), "PAGE")
    footer_p._p.append(fld)
    r2 = footer_p.add_run(" 页")
    r2.font.size = Pt(9)
    _docx_cn(r2)

    doc.save(path)
    return path



class VibGUI:
    def __init__(self, root):
        self.root = root; root.title("VibSpec"); fit_window(root, 1124, 722)
        # 界面缩放：左栏/表格列宽这些纯像素尺寸按屏幕 DPI 放大，字体由 Tk 自动放大
        ui_k = max(1.0, ui_dpi(root) / 96.0)
        self.main_dir = ""; self.all_data = []; self.checked_points = set(); self.tree_node_map = {}
        # 多个项目目录：上传新目录会追加到这里，树/趋势里合并显示（不再互相覆盖）
        self.project_dirs = []
        self._line_rows = {}
        self.var_show_rms = tk.BooleanVar(value=True)
        self.var_show_ge = tk.BooleanVar(value=False)
        self.var_show_cf = tk.BooleanVar(value=False)
        # VDI 3834 加速度阈值线开关：B/C 报警边界、C/D 危险边界，可单独或一起显示
        self.var_show_bc = tk.BooleanVar(value=True)
        self.var_show_cd = tk.BooleanVar(value=True)
        # 趋势 RMS 当前所选 VDI 频带键（vdi_low/mid/hi），RMS 点与阈值线均按该档同口径显示
        self.var_band = tk.StringVar(value="vdi_mid")
        # 报警阈值：None 或空表示不启用；rms/ge 走左轴，cf 走右轴
        self.alarm = {"rms": None, "ge": None, "cf": None}

        # 趋势标题/图例统一配色走 ttk.Style：部分 Tk 版本的 ttk 控件不接受实例级 -background/-foreground
        _style = ttk.Style(root)
        _style.configure("TrendHeader.TFrame", background=TREND_HEADER_BG)
        _style.configure("TrendHeader.TLabel", background=TREND_HEADER_BG, foreground=TREND_HEADER_FG)
        for _mi, _mc in enumerate(("#1f77b4", "#ff7f0e", "#2ca02c")):
            _style.configure("TrendMark%d.TLabel" % _mi, background=TREND_HEADER_BG, foreground=_mc)

        top = ttk.Frame(root); top.pack(fill="x", padx=5, pady=5)
        ttk.Button(top, text="上传", command=self.select_dir).pack(side="left", padx=3)
        ttk.Button(top, text="计算数据", command=self.calc_new_files).pack(side="left", padx=3)
        ttk.Button(top, text="清空缓存", command=self.clear_all_cache).pack(side="left", padx=3)
        ttk.Button(top, text="图谱分析", command=self.open_spectrum).pack(side="left", padx=3)
        ttk.Button(top, text="分析报告", command=self.open_report).pack(side="left", padx=3)
        self.dir_label = ttk.Label(top, text="未选择项目目录"); self.dir_label.pack(side="left", padx=10)
        self.dir_label.bind("<Button-3>", lambda e: self._manage_dirs())   # 右键管理项目目录

        paned = ttk.PanedWindow(root, orient="horizontal"); paned.pack(fill="both", expand=True, padx=5, pady=5)
        self._paned = paned
        left = ttk.Frame(paned, width=int(round(244 * ui_k))); paned.add(left, weight=1)
        right = ttk.Frame(paned); paned.add(right, weight=3)
        _ubar = ttk.Frame(left); _ubar.pack(fill="x", padx=2, pady=(0, 2))
        ttk.Label(_ubar, text="机组:").pack(side="left")
        self.unit_sel = tk.StringVar(value="全部机组")
        self.unit_combo = ttk.Combobox(_ubar, textvariable=self.unit_sel,
                                       values=["全部机组"], state="readonly", width=12)
        self.unit_combo.pack(side="left", fill="x", expand=True, padx=(2, 0))
        self.unit_combo.bind("<<ComboboxSelected>>", self._jump_unit)
        self.tree = ttk.Treeview(left, columns=("check",), show="tree headings")
        self.tree.heading("#0", text="项目/机组/测点"); self.tree.heading("check", text="选择")
        self.tree.column("check", width=int(round(40 * ui_k)), anchor="center")
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<Button-1>", self.on_tree_click)
        # 右侧上方数据表格
        table_frame = ttk.Frame(right); table_frame.pack(fill="x", padx=2, pady=2)
        cols = ("time", "rms", "ge", "cf", "speed", "peak", "kurtosis", "vdi")
        self.data_tree = ttk.Treeview(table_frame, columns=cols, show="headings", height=12)
        self._table_rows = []; self._table_csvs = []; self._table_sort_state = {}
        self._table_iid_csv = {}; self._table_tags = []
        # RMS 超限时整行标红高亮；VDI 评级 C 级橙色、D 级红色（可与 rms_over 叠加）
        self.data_tree.tag_configure("rms_over", foreground="#d00000")
        self.data_tree.tag_configure("vdi_c", foreground="#e07b00")
        self.data_tree.tag_configure("vdi_d", foreground="#d00000")
        # 奇偶行交替浅蓝底，形成数据表格的水平网格分层（只设背景，与上面的前景报警色可叠加）
        self.data_tree.tag_configure("zebra", background="#f2f6fb")
        for c, w, t in [("time", 150, "采集时间"), ("rms", 70, "RMS"), ("ge", 70, "包络gE"),
                        ("cf", 70, "冲击因子"), ("speed", 70, "转速rpm"),
                        ("peak", 70, "Peak"), ("kurtosis", 70, "峭度"), ("vdi", 75, "VDI等级")]:
            self.data_tree.heading(c, text=t, command=lambda cc=c: self._sort_table(cc))
            self.data_tree.column(c, width=int(round(w * ui_k)), anchor="center")
        vsb = ttk.Scrollbar(table_frame, orient="vertical", command=self.data_tree.yview)
        self.data_tree.configure(yscrollcommand=vsb.set)
        # 先放置垂直滚动条并固定占用右侧宽度，防止左面板拖宽、右面板变窄时滚动条被挤没
        vsb.pack(side="right", fill="y")
        self.data_tree.pack(side="left", fill="both", expand=True)
        self.data_tree.bind("<Double-1>", self._on_data_row_double)
        self.data_tree.bind("<Button-3>", self._on_data_tree_menu)   # 右键：批量设置转速
        # 日期/转速筛选改为趋势图右键弹窗（确认即刷新）；这里仅保留控件宿主、不占布局空间，
        # 控件不 pack 到可见界面，但 DateEntry 的 get_date/set_date 与变量照常可用，缓存逻辑不变
        ff = ttk.Frame(right)
        ttk.Label(ff, text="起始日期:").pack(side="left")
        self.date_start = DateEntry(ff, date_pattern="yyyy-MM-dd"); self.date_start.pack(side="left", padx=2)
        ttk.Label(ff, text="结束日期:").pack(side="left", padx=(10, 0))
        self.date_end = DateEntry(ff, date_pattern="yyyy-MM-dd"); self.date_end.pack(side="left", padx=2)
        ttk.Label(ff, text="转速>=").pack(side="left", padx=(10, 0))
        self.var_speed_min = tk.StringVar(value="")
        ttk.Entry(ff, textvariable=self.var_speed_min, width=8).pack(side="left")
        self.fig, self.ax = plt.subplots(figsize=(11, 6), dpi=96)   # 见 SpectrumWindow 里的 dpi 说明
        self.fig.patch.set_facecolor(CHART_BG)
        self.ax.set_facecolor(CHART_BG)
        self.ax2 = self.ax.twinx()  # 右轴：冲击因子（无量纲）
        self.ax2.set_facecolor("none")  # 透明，透出左轴灰底
        # 标题与图例放在筛选行下方、画布外的独立条带，不占用趋势绘图区
        self.trend_info = ttk.Frame(right, style="TrendHeader.TFrame")
        self.trend_info.pack(fill="x", padx=2, pady=(0, 2))
        self.trend_info.columnconfigure(0, weight=1)
        self.trend_title_lbl = ttk.Label(self.trend_info, text="", font=(UI_FONT_FAMILY, 11, "bold"),
                                         anchor="center", style="TrendHeader.TLabel", padding=(8, 5))
        self.trend_title_lbl.grid(row=0, column=0, sticky="ew")
        self.trend_legend_frame = ttk.Frame(self.trend_info, style="TrendHeader.TFrame")
        self.trend_legend_frame.grid(row=1, column=0, sticky="w", pady=(2, 5), padx=(8, 0))
        self.canvas = FigureCanvasTkAgg(self.fig, master=right)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)
        self.canvas.get_tk_widget().configure(background=CHART_BG)
        # 趋势图尺寸自适应：拖边框/最大化后按新宽度重算右侧阈值留白并重绘
        self._trend_canvas_size = (0, 0)
        self._trend_resize_job = None
        self.canvas.get_tk_widget().bind("<Configure>", self._on_trend_configure, add="+")
        self.fig.canvas.mpl_connect("button_press_event", self._on_trend_double)
        self.fig.canvas.mpl_connect("button_press_event", self._on_trend_right_click)
        self.fig.canvas.mpl_connect("scroll_event", self._on_trend_scroll)
        # 左键拖拽框选时间段（挂在最上层右轴，单击/双击不拖拽不会触发）
        self._trend_selector = RectangleSelector(
            self.ax2, self._on_trend_select, useblit=True,
            button=[1], minspanx=8, minspany=5, spancoords="pixels",
            interactive=False,
            props=dict(alpha=0.25, fill=True, facecolor="#1f77b4",
                       edgecolor="#1f77b4", linewidth=1))
        self._trend_view0 = None
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.load_state()
        # 固定左列宽度（Frame width 会被内部 Treeview 覆盖，用 sashpos 强制）
        root.update_idletasks()
        self._paned.sashpos(0, int(round(244 * ui_k)))

    def open_spectrum(self): SpectrumWindow(self.root, init_dir=self.main_dir)

    def open_report(self):
        """按时间段生成分析报告（Word）。"""
        dirs = list(getattr(self, "project_dirs", []) or [])
        if not dirs and self.main_dir:
            dirs = [self.main_dir]
        if not dirs:
            messagebox.showwarning("提示", "请先上传项目目录")
            return
        ReportDialog(self.root, self.main_dir, dirs)

    def select_dir(self):
        """上传：选项目目录。目录里的压缩包会先自动导入；多次上传不同目录会合并显示。"""
        d = filedialog.askdirectory(title="选择项目目录（可多次上传，多个项目会一起显示）")
        if not d: return
        d = os.path.normpath(d)
        same = [x for x in getattr(self, "project_dirs", []) if os.path.normpath(x) != d]
        self.project_dirs = [d] + same          # 新上传的排最前，作为当前目录
        self.main_dir = d
        self.dir_label.config(text=d)
        self.save_state()
        self._import_zips_in_dir(d)
        self.load_all_files(on_done=lambda: (self._sync_dates_to_data(), self.build_tree()),
                            force_dirs=[d])

    def _dirs_label(self):
        """状态栏文字：单目录显示路径，多目录显示数量 + 当前目录名。"""
        dirs = [d for d in getattr(self, "project_dirs", []) if d]
        if not dirs:
            return "未选择项目目录"
        if len(dirs) == 1:
            return "%s | 记录数: %d" % (dirs[0], len(self.all_data))
        return "%d 个项目目录：%s 等 | 记录数: %d" % (
            len(dirs), os.path.basename(dirs[0]), len(self.all_data))

    def _manage_dirs(self):
        """管理已登记的项目目录：可移除（只移出列表，不动磁盘文件）。"""
        dirs = [d for d in getattr(self, "project_dirs", []) if d]
        if not dirs:
            messagebox.showinfo("项目目录", "还没有上传任何项目目录。")
            return
        dlg = ProjectDirsDialog(self.root, dirs)
        self.root.wait_window(dlg)
        if dlg.result is None:
            return
        self.project_dirs = [d for d in dlg.result if os.path.isdir(d)]
        self.main_dir = self.project_dirs[0] if self.project_dirs else ""
        self.save_state()
        self.load_all_files(on_done=lambda: (self._sync_dates_to_data(), self.build_tree()))

    # ---------------- 上传：目录里的压缩包自动解压+改名，然后扫描全部 csv ----------------
    def _zip_fs_cfg(self):
        """上次给各测点填的采样率（存在 gui_state.json 的 zip_fs 键里）。"""
        cfg = _read_state_dict().get("zip_fs")
        out = {}
        if isinstance(cfg, dict):
            for k, v in cfg.items():
                try:
                    out[str(k)] = float(v)
                except (TypeError, ValueError):
                    pass
        return out

    def _save_zip_fs_cfg(self, fs_map):
        try:
            st = _read_state_dict()
            cur = st.get("zip_fs")
            cfg = dict(cur) if isinstance(cur, dict) else {}
            for k, v in (fs_map or {}).items():
                cfg[str(k)] = float(v)
            st["zip_fs"] = cfg
            with open(STATE_FILE, "w", encoding="utf-8") as fp:
                json.dump(st, fp, ensure_ascii=False)
        except Exception:
            pass

    def _scan_zips(self, zips):
        """只解析压缩包里的文件名（不解压数据），返回 (待导入条目, 无法识别的名字)。"""
        entries, problems = [], []
        point_names = list(rule_dict.keys())
        for zp in zips:
            try:
                with zipfile.ZipFile(zp) as zf:
                    for info in zf.infolist():
                        if info.is_dir():
                            continue
                        base = os.path.basename(decode_zip_name(info.filename))
                        if not base.lower().endswith(".csv"):
                            continue
                        parsed = parse_filename(base)
                        if parsed["point"] and parsed["fs"]:
                            entries.append({"zp": zp, "member": info.filename, "base": base,
                                            "project": parsed["project"], "unit": parsed["unit"],
                                            "point": parsed["point"], "rpm": parsed["speed"] or 0,
                                            "ts": (parsed["dt"].strftime("%Y%m%d%H%M%S")
                                                   if parsed["dt"] else ""),
                                            "fs": parsed["fs"]})
                            continue
                        v = parse_vendor_name(base, point_names)
                        if not v:
                            problems.append(base)
                            continue
                        entries.append({"zp": zp, "member": info.filename, "base": base,
                                        "project": v["project"], "unit": v["unit"],
                                        "point": v["point"], "rpm": v["rpm"],
                                        "ts": v["ts"], "fs": None})
            except Exception as e:
                problems.append("%s（%s）" % (os.path.basename(zp), e))
        return entries, problems

    def _existing_import(self, target, e):
        """该压缩包成员是不是已经导入过。

        同时看“时间戳子文件夹”和项目根目录：早期手工改名的数据直接放在根目录，
        只看子文件夹会把同一批数据再导入一遍、产生重复记录。
        """
        prefix = "%s_%s_%s_" % (e["project"] or "项目", e["unit"] or "1#", e["point"])
        suffix = "_%s.csv" % e["ts"]
        dirs = []
        if e["ts"]:
            dirs.append(os.path.join(target, e["ts"]))
        dirs.append(target)
        for sub in dict.fromkeys(dirs):
            if not os.path.isdir(sub):
                continue
            try:
                for f in os.listdir(sub):
                    if f.lower().endswith(".csv") and f.startswith(prefix) and f.endswith(suffix):
                        return os.path.join(sub, f)
            except Exception:
                pass
        return None

    def _import_zips_into(self, zips, target):
        """解压+改名写入 target。返回 (写入数, 跳过数, 失败列表, 未识别列表, 是否被取消)。"""
        entries, problems = self._scan_zips(zips)
        failed = []
        skipped = 0
        todo = []
        for e in entries:
            if self._existing_import(target, e):
                skipped += 1
                continue
            todo.append(e)
        fs_map = {}
        need = sorted({e["point"] for e in todo if not e["fs"]})
        if need:
            info = "项目里检测到压缩包：待导入 %d 个文件 / %d 个测点\n解压到：%s" % (
                len(todo), len({e["point"] for e in todo}), target)
            dlg = ZipImportDialog(self.root, need, info, self._zip_fs_cfg())
            self.root.wait_window(dlg)
            if not dlg.result:
                return 0, skipped, failed, problems, True
            fs_map = dlg.result
            self._save_zip_fs_cfg(fs_map)
        made = 0
        for e in todo:
            fs = e["fs"] or fs_map.get(e["point"])
            if not fs:
                skipped += 1
                continue
            try:
                with zipfile.ZipFile(e["zp"]) as zf:
                    data = zf.read(e["member"])
            except Exception as ex:
                failed.append("%s：%s" % (e["base"], ex))
                continue
            n = data.count(b"\n") + (0 if (not data or data.endswith(b"\n")) else 1)
            if n < 100:
                failed.append("%s：数据太少(%d)" % (e["base"], n))
                continue
            dur = n / float(fs)
            sub = os.path.join(target, e["ts"]) if e["ts"] else target
            try:
                os.makedirs(sub, exist_ok=True)
            except Exception as ex:
                failed.append("%s：建目录失败(%s)" % (e["base"], ex))
                continue
            if str(e.get("rpm") or "").strip():
                name = "%s_%s_%s_%dHz_%.2fs_加速度值_%s_%s.csv" % (
                    e["project"] or "项目", e["unit"] or "1#", e["point"],
                    int(fs), dur, e["rpm"], e["ts"])
            else:
                # 原始文件名里没有转速：生成的文件名也不带转速段，
                # 阶次谱到时候用基频标记或弹框让用户填（不会伪造 0rpm）
                name = "%s_%s_%s_%dHz_%.2fs_加速度值_%s.csv" % (
                    e["project"] or "项目", e["unit"] or "1#", e["point"],
                    int(fs), dur, e["ts"])
            dst = os.path.join(sub, name)
            if os.path.exists(dst):
                skipped += 1
                continue
            try:
                with open(dst, "wb") as fp:
                    fp.write(data)
                made += 1
            except Exception as ex:
                failed.append("%s：%s" % (name, ex))
        return made, skipped, failed, problems, False

    def _import_zips_in_dir(self, d):
        """上传目录前，先把目录里（含子目录）的压缩包导入。"""
        zips = []
        for rd, _, fs in os.walk(d):
            for f in fs:
                if f.lower().endswith(".zip"):
                    zips.append(os.path.join(rd, f))
        if not zips:
            return
        made, skipped, failed, problems, cancelled = self._import_zips_into(sorted(zips), d)
        if cancelled:
            return
        if made or failed or problems:
            msg = "压缩包已导入：写入 %d 个文件" % made
            if skipped:
                msg += "，跳过 %d 个（已导入过）" % skipped
            if failed:
                msg += "\n失败 %d 个：\n%s" % (len(failed), "\n".join(failed[:5]))
            if problems:
                msg += "\n未识别 %d 个（文件名里找不到内置测点名）：\n%s" % (
                    len(problems), "\n".join(problems[:5]))
            messagebox.showinfo("导入压缩包", msg)

    def load_all_files(self, on_done=None, force_rescan=False, force_dirs=None):
        """依次加载全部已登记的项目目录，合并成一棵树（上传新项目不会再顶掉旧项目）。

        force_dirs：只对这些目录强制重扫（新上传的那个）；其它目录走 SQLite 秒开，
        避免每上传一个项目就把所有项目重新扫一遍。
        """
        dirs = [d for d in getattr(self, "project_dirs", []) if d and os.path.isdir(d)]
        if not dirs and self.main_dir and os.path.isdir(self.main_dir):
            dirs = [self.main_dir]
            self.project_dirs = list(dirs)
        self._load_queue = list(dirs)
        self._load_rows = []
        self._load_on_done = on_done
        self._load_force = bool(force_rescan)
        self._load_force_dirs = {os.path.normpath(x) for x in (force_dirs or [])}
        self.all_data.clear()
        if not dirs:
            self.dir_label.config(text="未选择项目目录")
            cb, self._load_on_done = self._load_on_done, None
            if cb: cb()
            return
        if len(dirs) > 1:
            self.dir_label.config(text="正在加载 %d 个项目目录…" % len(dirs))
        self._load_next_dir()

    def _load_next_dir(self):
        """加载队列：逐个目录走原有单目录逻辑，结果累加后再统一刷新界面。"""
        if not self._load_queue:
            self.all_data = list(self._load_rows)
            self._load_rows = []
            # 注意：项目名归一化必须“按目录”做（各目录内部统一写法），
            # 不能对合并后的总表再做一次，否则不同项目的名字会被强制统一成一个，树里只剩一个项目。
            if self.project_dirs:
                self.main_dir = self.project_dirs[0]
            self.dir_label.config(text=self._dirs_label())
            cb, self._load_on_done = self._load_on_done, None
            if cb: cb()
            return
        d = self._load_queue.pop(0)
        self.main_dir = d
        force = self._load_force or (os.path.normpath(d) in self._load_force_dirs)
        try:
            self._load_one_dir(d, force)
        except Exception:
            self._load_next_dir()

    def _load_one_dir(self, d, force_rescan):
        def _finish():
            # 当前目录加载完：结果并入累计，继续下一个目录
            self._load_rows.extend(self.all_data)
            self.all_data = list(self._load_rows)
            self._load_next_dir()
        self.all_data.clear()
        if not d:
            self.dir_label.config(text="未选择项目目录"); _finish(); return
        summary_path = os.path.join(self.main_dir, SUMMARY_FILE)
        try:
            _old_schema = int(db_peek_schema(self.main_dir) or 0)
        except (TypeError, ValueError):
            _old_schema = 0
        try:
            conn = db_connect(self.main_dir)
        except Exception as e:
            messagebox.showerror("数据库版本不兼容", str(e))
            _finish()
            return
        if _old_schema != DB_SCHEMA_VERSION:
            # 表结构刚迁移过：旧行可能缺新列，强制重算补齐
            force_rescan = True
        try:
            db_ver = db_get_meta(conn, "vdi_ver")
            cnt = db_count(conn)
            # 路径A（启动默认，秒开）：不强制扫描、库内有数据且数据版本最新 → 直接 SELECT，
            # 完全不 walk 十几万文件、不解析小 JSON，这是启动提速的关键。
            if (not force_rescan) and cnt > 0 and db_ver == VDI_VERSION:
                self.all_data = db_load_all(conn)
                normalize_projects(self.all_data)
                self.dir_label.config(text=f"{self.main_dir} | 记录数: {len(self.all_data)} (SQLite缓存)")
                _finish()
                return
            # 路径B（首次建库）：旧汇总 JSON 存在且为最新版时一次性迁移入库，避免重算历史数据。
            if cnt == 0 and os.path.exists(summary_path):
                try:
                    cached_rows = json.load(open(summary_path, encoding="utf-8"))
                except Exception:
                    cached_rows = []
                if cached_rows and all(cd.get("vdi_ver") == VDI_VERSION for cd in cached_rows):
                    db_upsert_rows(conn, cached_rows)
                    db_set_meta(conn, "vdi_ver", VDI_VERSION)
                    db_set_meta(conn, "schema_ver", DB_SCHEMA_VERSION)
                    conn.commit()
                    if not force_rescan:
                        # 启动/非强制场景：迁移后直接秒开，不扫描目录
                        self.all_data = db_load_all(conn)
                        normalize_projects(self.all_data)
                        self.dir_label.config(text=f"{self.main_dir} | 记录数: {len(self.all_data)} (迁移→SQLite)")
                        _finish()
                        return
                    # 主动上传(force)：迁移入库后继续走路径C，基于库增量扫描并合并新 CSV
            # 路径C 需要扫描：先取库内已有行（键为 csv_path），供增量合并复用
            existing = {r.get("csv_path"): r for r in db_load_all(conn)}
        finally:
            conn.close()

        def _stale(csv_full):
            row = existing.get(csv_full)
            return bool(row is None or row.get("vdi_ver") != VDI_VERSION)
        from concurrent.futures import ThreadPoolExecutor, as_completed
        def _read_one(csv_full):
            # 单个文件出问题绝不能让整个工作线程挂掉（否则进度会永远停在最后一个数字）
            try:
                # SQLite 行已是唯一缓存：过期文件直接重算，不再读写逐文件 JSON
                cd, err = process_one_csv(csv_full)
                if cd is None: return None
                cd["csv_path"] = csv_full
                if not cd.get("project") or not cd.get("unit") or not cd.get("point"):
                    info = parse_filename(os.path.basename(csv_full))
                    if info["project"]:
                        cd["project"] = info["project"]; cd["unit"] = info["unit"]; cd["point"] = info["point"]
                        if info["dt"]:
                            cd["dt_date"] = info["dt"].date().isoformat()
                            cd["dt_str"] = info["dt"].strftime("%Y-%m-%d %H:%M:%S")
                            cd["dt_ts"] = info["dt"].timestamp()
                        if info["speed"] is not None: cd["speed"] = info["speed"]
                return cd
            except Exception:
                return None
        # 进度弹窗：先 indeterminate 扫描目录，再 determinate 只计算库内缺失/过期的文件
        prog = tk.Toplevel(self.root)
        prog.title("上传数据"); prog.geometry("440x130"); prog.transient(self.root)
        prog.resizable(False, False)
        ttk.Label(prog, text="正在扫描目录文件…").pack(pady=(14, 6))
        lbl = ttk.Label(prog, text="准备开始..."); lbl.pack()
        pb = ttk.Progressbar(prog, mode="indeterminate", length=400)
        pb.pack(pady=8, padx=20); pb.start(12)
        center_window_later(prog, self.root)   # 摆到主窗口正中，而不是系统默认的屏幕左上角
        prog.protocol("WM_DELETE_WINDOW", lambda: None)  # 计算途中禁止关闭，避免状态半成品
        prog.grab_set()
        state = {"phase": "scan", "done": 0, "todo_total": 0, "rows": [], "finished": False,
                 "fails": [], "error": None, "t0": time.time()}

        def worker():
            # 任何异常都必须落到 state["error"] 并置 finished，否则进度窗会永远停在最后一个数字
            try:
                csv_list = []
                for rd, _, fs in os.walk(self.main_dir):
                    for fn in fs:
                        if fn.lower().endswith(".csv"):
                            csv_list.append(os.path.join(rd, fn))
                # 复用库内仍存在且版本最新的行；磁盘上已删除的 CSV 不在 csv_list，自然作为孤儿被剔除
                rows = [existing[p] for p in csv_list if p in existing]
                todo = [c for c in csv_list if _stale(c)]
                csv_set = set(csv_list)
                new_rows = []
                state["todo_total"] = len(todo)
                if todo:
                    state["phase"] = "calc"
                    with ThreadPoolExecutor(max_workers=8) as ex:
                        futs = {ex.submit(_read_one, c): c for c in todo}
                        for fut in as_completed(futs):
                            try:
                                r = fut.result()
                            except Exception:
                                r = None
                            if r is not None:
                                rows.append(r)
                                new_rows.append(r)
                            else:
                                # 计算失败的文件必须显式记录：全量写库后它不会出现，
                                # 旧实现静默丢弃，用户只看到“记录数变少”却查不到原因。
                                state["fails"].append(os.path.basename(futs[fut]))
                            state["done"] += 1
                state["phase"] = "write"
                orig_projects = {p: r.get("project") for p, r in existing.items()}
                normalize_projects(rows)
                # 只 upsert 新算出的行 + 项目名被归一化改动过的旧行，不再全库重写
                upsert = list(new_rows)
                for p, r in existing.items():
                    if r.get("project") != orig_projects.get(p):
                        upsert.append(r)
                # 线程内独立连接增量写库（不与主线程连接共享），单事务批量提交
                wconn = db_connect(self.main_dir)
                try:
                    db_upsert_rows(wconn, upsert)
                    db_delete_paths(wconn, [p for p in existing if p not in csv_set])
                    db_set_meta(wconn, "vdi_ver", VDI_VERSION)
                    db_set_meta(wconn, "schema_ver", DB_SCHEMA_VERSION)
                    wconn.commit()
                finally:
                    wconn.close()
                state["rows"] = rows
            except Exception:
                import traceback
                state["error"] = traceback.format_exc()
            finally:
                state["finished"] = True
        threading.Thread(target=worker, daemon=True).start()

        def poll():
            if not prog.winfo_exists(): return
            try:
                if state["finished"]:
                    prog.destroy()
                    if state.get("error"):
                        messagebox.showerror("上传失败", state["error"][:1500])
                        _finish()
                        return
                    # 以库为唯一数据源重新读出，保证内存与后续秒开路径完全同源
                    rconn = db_connect(self.main_dir)
                    try:
                        self.all_data = db_load_all(rconn)
                    finally:
                        rconn.close()
                    normalize_projects(self.all_data)
                    self.dir_label.config(text=f"{self.main_dir} | 记录数: {len(self.all_data)}")
                    _fails = state.get("fails") or []
                    if _fails:
                        messagebox.showwarning(
                            "部分数据未计算",
                            f"{len(_fails)} 个文件计算失败，已跳过（不会写入趋势库）：\n" +
                            "\n".join(_fails[:10]) +
                            (f"\n… 共 {len(_fails)} 个" if len(_fails) > 10 else ""))
                    _finish()
                    return
                if state["phase"] == "scan":
                    lbl.config(text="正在扫描目录文件…（大目录可能需要几分钟）")
                elif state["phase"] == "write":
                    lbl.config(text=f"正在写入趋势库…（共 {len(state['rows'])} 条）")
                    pb["value"] = pb["maximum"]
                else:
                    if str(pb.cget("mode")) != "determinate":
                        pb.stop(); pb.config(mode="determinate", maximum=max(state["todo_total"], 1))
                    d = state["done"]; t = state["todo_total"]
                    pb["value"] = d
                    elapsed = max(0.1, time.time() - state["t0"])
                    lbl.config(text="计算新增/过期数据 %d/%d (%d%%) · %.1f 个/秒 · 已用 %s"
                               % (d, t, (d * 100 // t) if t else 100,
                                  d / elapsed, format_elapsed(elapsed)))
            except Exception:
                import traceback
                traceback.print_exc()
            self.root.after(250, poll)
        self.root.after(200, poll)

    def calc_new_files(self):
        """计算数据：对全部项目目录做一次增量计算（只算库内缺失/过期的文件）。"""
        dirs = [d for d in getattr(self, "project_dirs", []) if os.path.isdir(d)]
        if not dirs:
            messagebox.showwarning("提示", "请先选择项目目录"); return
        self.load_all_files(on_done=lambda: (self._sync_dates_to_data(), self.build_tree()),
                            force_rescan=True)
        return

    def _calc_new_files_legacy(self):
        if not self.main_dir: messagebox.showwarning("提示", "请先选择项目总目录"); return
        def _needs_recalc(csv_full):
            cp = get_cache_path(csv_full)
            if not os.path.exists(cp):
                return True
            try:  # 旧版缓存缺 VDI 字段也纳入重算，实现自动补算
                return json.load(open(cp, encoding="utf-8")).get("vdi_ver") != VDI_VERSION
            except Exception:
                return True
        news = [os.path.join(r, f) for r, _, fs in os.walk(self.main_dir) for f in fs
                if f.lower().endswith(".csv") and _needs_recalc(os.path.join(r, f))]
        if not news: messagebox.showinfo("提示", "无新增未计算数据"); return
        total = len(news)
        # 进度窗口
        prog = tk.Toplevel(self.root)
        prog.title("计算中"); prog.geometry("420x110"); prog.transient(self.root)
        prog.resizable(False, False)
        ttk.Label(prog, text=f"共 {total} 个文件待计算...").pack(pady=(12, 4))
        lbl = ttk.Label(prog, text="准备开始...")
        lbl.pack()
        pb = ttk.Progressbar(prog, mode="determinate", maximum=total, length=380)
        pb.pack(pady=8, padx=20)
        center_window_later(prog, self.root)
        prog.grab_set()
        state = {"done": 0, "ok": 0, "fails": [], "finished": False, "error": None}
        def worker():
            from concurrent.futures import ThreadPoolExecutor, as_completed
            try:
                with ThreadPoolExecutor(max_workers=8) as ex:
                    futs = {ex.submit(process_one_csv, cp): cp for cp in news}
                    for fut in as_completed(futs):
                        try:
                            out, err = fut.result()
                        except Exception as e:
                            out, err = None, str(e)
                        state["done"] += 1
                        if out is not None: state["ok"] += 1
                        else: state["fails"].append(f"{os.path.basename(futs[fut])}: {err}")
            except Exception:
                import traceback
                state["error"] = traceback.format_exc()
            finally:
                state["finished"] = True
        threading.Thread(target=worker, daemon=True).start()
        def poll():
            if state["finished"]:
                prog.destroy()
                if state.get("error"):
                    messagebox.showerror("计算失败", state["error"][:1500])
                    return
                sp = os.path.join(self.main_dir, SUMMARY_FILE)
                if os.path.exists(sp): os.remove(sp)
                def _after_reload():
                    self._sync_dates_to_data(); self.build_tree()
                    diag = self._auto_export_diagnostic()
                    msg = f"新增{total}个,成功{state['ok']}条"
                    if state["fails"]:
                        msg += "\n\n失败明细:\n" + "\n".join(state["fails"][:20])
                        if len(state["fails"]) > 20: msg += f"\n...共{len(state['fails'])}条失败"
                    if diag:
                        msg += f"\n\n诊断关注清单: {diag[1]}条\n{diag[0]}"
                    messagebox.showinfo("完成", msg)
                self.load_all_files(on_done=_after_reload, force_rescan=True)
                return
            try:
                d = state["done"]
                pb["value"] = d
                lbl.config(text=f"已完成 {d}/{total} ({d*100//total}%)")
            except Exception:
                pass
            self.root.after(300, poll)
        self.root.after(200, poll)

    def _auto_export_diagnostic(self):
        """计算/重算后自动生成《诊断关注清单.xlsx》。
        关注类型：高峭度(>=10，近停机虚高已置0不会命中)、RMS报警(按测点阈值严格大于)、
        包络gE偏大(同一测点内 gE >= 均值+2倍标准差)。返回 (路径, 条数)，失败返回 None。"""
        try:
            if not self.main_dir or not self.all_data:
                return None
            from collections import defaultdict
            ge_vals = defaultdict(list)
            for r in self.all_data:
                if r.get("ge") is not None:
                    ge_vals[r["point"]].append(float(r["ge"]))
            ge_lim = {}
            for pt, a in ge_vals.items():
                arr = np.asarray(a, dtype=float)
                sd = float(np.std(arr, ddof=1)) if len(arr) > 1 else 0.0
                ge_lim[pt] = float(np.mean(arr)) + 2.0 * sd
            KURT_THR = 10.0
            out = []
            for r in self.all_data:
                pt = r.get("point", "")
                rms = float(r.get("rms", 0) or 0)
                ge = float(r.get("ge", 0) or 0)
                kurt = float(r.get("kurtosis", 0) or 0)
                cf = float(ge / rms) if rms > 0 else 0.0
                thr = rms_alarm_for(pt)
                tags = []
                if kurt >= KURT_THR:
                    tags.append("高峭度")
                if thr is not None and rms > thr:
                    tags.append("RMS报警")
                if ge >= ge_lim.get(pt, float("inf")):
                    tags.append("包络gE偏大")
                _vg = r.get("vdi_grade", "") or ""
                if _vg == "C":
                    tags.append("VDI-C级预警")
                elif _vg == "D":
                    tags.append("VDI-D级危险")
                if not tags:
                    continue
                _v4 = lambda k: round(r[k], 4) if isinstance(r.get(k), (int, float)) else ""
                out.append({
                    "项目": r.get("project", ""), "机组": r.get("unit", ""), "测点": pt,
                    "采集时间": r.get("dt_str", ""), "文件名": os.path.basename(r.get("csv_path", "")),
                    "RMS": round(rms, 4), "RMS报警阈值": (thr if thr is not None else ""),
                    "包络gE": round(ge, 4), "gE上限(均值+2σ)": round(ge_lim.get(pt, 0.0), 4),
                    "冲击因子": round(cf, 2), "峭度": round(kurt, 2), "转速": r.get("speed", ""),
                    "低频0.1-10Hz加速度": _v4("vdi_low"),
                    "中频10-1000Hz加速度": _v4("vdi_mid"),
                    "高频10-5000Hz加速度": _v4("vdi_hi"),
                    "VDI等级": _vg,
                    "关注类型": "、".join(tags)})
            cols = ["项目", "机组", "测点", "采集时间", "文件名", "RMS", "RMS报警阈值", "包络gE",
                    "gE上限(均值+2σ)", "冲击因子", "峭度", "转速",
                    "低频0.1-10Hz加速度", "中频10-1000Hz加速度", "高频10-5000Hz加速度",
                    "VDI等级", "关注类型"]
            out.sort(key=lambda x: (x["机组"], x["测点"], x["采集时间"]))
            path = os.path.join(self.main_dir, "诊断关注清单.xlsx")
            df = pd.DataFrame(out, columns=cols)
            try:
                df.to_excel(path, index=False)
            except (ModuleNotFoundError, ImportError):
                # 环境缺少 openpyxl 时降级为 CSV（utf-8-sig，Excel 可直接双击打开）
                path = os.path.join(self.main_dir, "诊断关注清单.csv")
                df.to_csv(path, index=False, encoding="utf-8-sig")
            return path, len(out)
        except PermissionError:
            messagebox.showwarning("诊断清单", "诊断关注清单.xlsx 正被占用，请关闭该Excel后重新计算。")
            return None
        except Exception as e:
            messagebox.showwarning("诊断清单", f"生成诊断关注清单失败: {e}")
            return None

    def clear_all_cache(self):
        dirs = [d for d in getattr(self, "project_dirs", []) if os.path.isdir(d)]
        if not dirs: return
        tip = "删除全部缓存?" if len(dirs) == 1 else "删除全部缓存（%d 个项目目录）?" % len(dirs)
        if not messagebox.askyesno("确认", tip): return
        n = 0
        for d in dirs:
            for r, _, fs in os.walk(d):
                for f in fs:
                    if f.endswith(CACHE_SUFFIX):
                        try:
                            os.remove(os.path.join(r, f)); n += 1
                        except Exception: pass
            sp = os.path.join(d, SUMMARY_FILE)
            if os.path.exists(sp):
                try: os.remove(sp)
                except Exception: pass
            # 同时删除 SQLite 库及其 WAL/SHM 临时文件，下次上传将全新建库重算
            for suffix in ("", "-wal", "-shm"):
                dbp = get_db_path(d) + suffix
                try:
                    if os.path.exists(dbp): os.remove(dbp)
                except Exception: pass
        self.all_data.clear(); self.tree.delete(*self.tree.get_children())
        # 清空后同步清掉树节点映射/勾选/表格与趋势图，避免界面还停在清空前的旧数据上
        self.tree_node_map.clear(); self.checked_points.clear()
        for item in self.data_tree.get_children():
            self.data_tree.delete(item)
        self._table_rows = []; self._table_csvs = []; self._table_iid_csv = {}
        self._table_tags = []
        self.dir_label.config(text=self._dirs_label())
        self.plot_trend()
        messagebox.showinfo("完成", f"删除{n}个缓存")

    def _sync_dates_to_data(self):
        # 把起止日期自动设为当前缓存数据的最小~最大日期，使打开/切换目录后默认显示全部数据。
        # 该范围仅用于趋势图/数据表格筛选，不影响树状图。
        ds = []
        for r in self.all_data:
            d = r.get("dt_date")
            if isinstance(d, str):
                try:
                    d = date.fromisoformat(d)
                except Exception:
                    d = None
            elif isinstance(d, datetime):
                d = d.date()
            if isinstance(d, date):
                ds.append(d)
        if ds:
            self.date_start.set_date(min(ds))
            self.date_end.set_date(max(ds))

    def build_tree(self):
        self.tree.delete(*self.tree.get_children()); self.tree_node_map.clear()
        pm = {}
        for row in self.all_data:
            pm.setdefault(row["project"], {}).setdefault(row["unit"], set()).add(row["point"])
        for proj in sorted(pm):
            units = pm[proj]
            pi = self.tree.insert("", "end", text=proj, values=[""], open=True)
            for unit in sorted(units, key=tree_unit_order):
                pts = units[unit]
                ui = self.tree.insert(pi, "end", text=unit, values=[""], open=True)
                for pt in sorted(pts, key=lambda x: (tree_point_order(x), x)):
                    ni = self.tree.insert(ui, "end", text=pt, values=["☐"])
                    self.tree_node_map[f"{proj}|{unit}|{pt}"] = ni
        self._refresh_check_marks()
        self._refresh_unit_combo()

    def _refresh_unit_combo(self):
        """机组下拉框：全部机组 + 按 1#..25# 排列。"""
        try:
            units = sorted({r["unit"] for r in self.all_data}, key=tree_unit_order)
            vals = ["全部机组"] + units
            self.unit_combo.configure(values=vals)
            if self.unit_sel.get() not in vals:
                self.unit_sel.set("全部机组")
        except Exception:
            pass

    def _jump_unit(self, _evt=None):
        """下拉选机组后，展开并定位到该机组。"""
        u = self.unit_sel.get()
        try:
            if not u or u == "全部机组":
                for it in self.tree.get_children():
                    self.tree.item(it, open=True)
                    for ch in self.tree.get_children(it):
                        self.tree.item(ch, open=True)
                return
            for proj_iid in self.tree.get_children():
                for unit_iid in self.tree.get_children(proj_iid):
                    if self.tree.item(unit_iid, "text") == u:
                        self.tree.item(proj_iid, open=True)
                        self.tree.see(unit_iid)
                        self.tree.selection_set(unit_iid)
                        return
        except Exception:
            pass

    def _refresh_check_marks(self):
        for iid in self.tree_node_map.values(): self.tree.item(iid, values=["☐"])
        for key in self.checked_points:
            iid = self.tree_node_map.get(key)
            if iid: self.tree.item(iid, values=["☑"])

    def on_tree_click(self, event):
        if self.tree.identify_column(event.x) != "#1": return
        item = self.tree.identify_row(event.y)
        if not item or self.tree.get_children(item): return
        key = None
        for k, iid in self.tree_node_map.items():
            if iid == item: key = k; break
        if not key: return
        if key in self.checked_points: self.checked_points.discard(key)
        else: self.checked_points.clear(); self.checked_points.add(key)
        self._refresh_check_marks(); self.plot_trend()

    def _filtered_rows(self, uf=None, pf=None):
        s = self.date_start.get_date(); e = self.date_end.get_date()
        try:
            txt = self.var_speed_min.get().strip(); sm = float(txt) if txt else None
        except: sm = None
        picked = []
        for r in self.all_data:
            if r.get("dt_date") is None: continue
            try:
                dd = date.fromisoformat(r["dt_date"]) if isinstance(r["dt_date"], str) else r["dt_date"]
            except: continue
            if not (s <= dd <= e): continue
            if sm is not None and (r.get("speed") is None or r["speed"] < sm): continue
            if uf is not None and r["unit"] != uf: continue
            if pf is not None and r["point"] != pf: continue
            picked.append(r)
        # 每次采集都显示，按测点与采集时间排序
        return sorted(picked, key=lambda x: (x["project"], x["unit"], x["point"],
                                             x.get("dt_ts") or 0))

    def _available_bands(self):
        # 当前勾选测点“联合”支持的 VDI 频带键，按低/中/高顺序返回（任一测点支持即可选）
        _avail = set()
        for _k in self.checked_points:
            _c = vdi_category(_k.split("|")[2])
            if _c:
                for _spec in VDI_SPEC[_c]:
                    _avail.add(_spec[0])
        return [b for b in _VDI_BAND_ORDER if b in _avail]

    def plot_trend(self):
        self.ax.clear(); self.ax2.clear(); titles = []; self._line_rows = {}
        self._table_sort_state = {}   # 新数据重排后，之前的列排序状态不再适用
        bc_map = {}; cd_map = {}  # 各测点自身频带的 B/C、C/D 阈值水平线
        for item in self.data_tree.get_children(): self.data_tree.delete(item)
        all_rows = []; all_ts = []
        for key in self.checked_points:
            proj, unit, pt = key.split("|"); titles.append(f"{unit}-{pt}")
            dl = self._filtered_rows(unit, pt)
            if not dl: continue
            # RMS 已是入库时分频带算好的值；阈值线按该测点自己的频带取，保证同口径
            _cat = vdi_category(pt)
            _bk = table_rms_band(pt)
            if _cat and _bk:
                for _spec in VDI_SPEC[_cat]:
                    if _spec[0] == _bk:
                        _bc, _cd = _spec[3], _spec[4]
                        _bn = _VDI_BAND_NAME[_bk]
                        bc_map.setdefault(_bc, set()).add(_bn)
                        cd_map.setdefault(_cd, set()).add(_bn)
                        break
            ts = []
            for r in dl:
                if r.get("dt_ts"):
                    ts.append(datetime.fromtimestamp(r["dt_ts"]))
                else:
                    dd = date.fromisoformat(r["dt_date"]) if isinstance(r["dt_date"], str) else r["dt_date"]
                    ts.append(datetime.combine(dd, datetime.min.time()))
            if self.var_show_rms.get():
                vs = [r.get("rms") if isinstance(r.get("rms"), (int, float)) else np.nan for r in dl]
                _lbl = _VDI_BAND_SHORT[_bk] if _bk else "规则带"
                line, = self.ax.plot(ts, vs, marker="o", lw=0, ms=2, color="#1f77b4",
                                     label=f"{pt}-RMS({_lbl})", picker=5, pickradius=8)
                self._line_rows[line] = dl
            if self.var_show_ge.get():
                ge_vs = [r.get("ge", 0) for r in dl]
                line2, = self.ax.plot(ts, ge_vs, marker="s", lw=0, ms=2, ls="", color="#ff7f0e",
                                      label=f"{pt}-gE", picker=5, pickradius=8)
                self._line_rows[line2] = dl
                thr = self.alarm.get("ge")
                if thr is not None:
                    pass
            if self.var_show_cf.get():
                cf_vs = [r.get("ge", 0) / r["rms"] if r["rms"] else 0 for r in dl]
                line3, = self.ax2.plot(ts, cf_vs, marker="^", lw=0, ms=2, ls="", color="#2ca02c",
                                       label=f"{pt}-冲击因子", picker=5, pickradius=8)
                self._line_rows[line3] = dl
                thr = self.alarm.get("cf")
                if thr is not None:
                    pass
            all_rows.extend(dl); all_ts.extend(ts)
        # 填充数据表格，按时间倒序，最多500条
        all_rows.sort(key=lambda r: r.get("dt_ts") or 0, reverse=True)
        self._table_rows = []; self._table_csvs = []; self._table_iid_csv = {}; self._table_tags = []
        for seq, r in enumerate(all_rows[:500]):
            ge_val = r.get("ge", 0)
            cf_val = ge_val / r["rms"] if r["rms"] else 0
            _grade = r.get("vdi_grade", "") or ""
            # 表格 RMS 列直接取入库的分频带 RMS（与趋势图、诊断清单同口径）
            _rms_disp = r.get("rms", 0.0)
            try:
                _spd = float(r.get("speed")) if r.get("speed") not in (None, "") else None
            except (TypeError, ValueError):
                _spd = None
            _spd_disp = ("%.0f" % _spd) if _spd is not None else ""
            row = (r.get("dt_str", ""), format_table_rms(_rms_disp), f"{ge_val:.3f}", f"{cf_val:.2f}",
                   _spd_disp, f"{r.get('peak', 0):.2f}", f"{r.get('kurtosis', 0):.2f}",
                   _grade if _grade else "—")
            iid = f"row{seq}"
            _thr = rms_alarm_for(r.get("point"))
            _tags = []
            if _thr is not None and r["rms"] > _thr:
                _tags.append("rms_over")
            if _grade == "C":
                _tags.append("vdi_c")
            elif _grade == "D":
                _tags.append("vdi_d")
            if seq % 2 == 1:
                _tags.append("zebra")
            _tag = tuple(_tags)
            self._table_rows.append(row); self._table_csvs.append(r.get("csv_path"))
            self._table_tags.append(_tag)
            self._table_iid_csv[iid] = r.get("csv_path")
            self.data_tree.insert("", "end", iid=iid, values=row, tags=_tag)
        # 标题与图例移到画布外 tk 信息带，绘图区内不再绘制
        self.trend_title_lbl.config(text=" | ".join(titles) if titles else "未勾选测点")
        _pts = [k.split("|")[2] for k in self.checked_points]
        self._refresh_trend_legend(_pts[0] if len(set(_pts)) == 1 else None)
        self.ax.set_ylabel(r"加速度有效值 m/s$^2$", labelpad=12)
        # 趋势图坐标网格：浅灰虚线、置于最底层，不遮挡数据点与阈值线（双轴只在左轴画一次，避免竖线重复）
        self.ax.grid(True, which="major", linestyle="--", linewidth=0.6,
                     color="#c4c9d0", alpha=0.8, zorder=0)
        # 右侧Y轴（冲击因子）仅在启用冲击因子趋势时显示，关闭时连同刻度、标题、右边框一起隐藏
        if self.var_show_cf.get():
            self.ax2.set_ylabel("冲击因子 gE/RMS", color="#2ca02c", labelpad=12)
            self.ax2.yaxis.set_label_position("right")
            self.ax2.yaxis.tick_right()
            self.ax2.tick_params(axis="y", colors="#2ca02c")
            self.ax2.yaxis.set_visible(True)
            self.ax2.spines["right"].set_visible(True)
        else:
            self.ax2.set_ylabel("")
            self.ax2.yaxis.set_visible(False)
            self.ax2.spines["right"].set_visible(False)
        # VDI 3834 加速度阈值水平线（左轴，m/s²）：B/C 橙虚线、C/D 红虚线，右键可单独/一起开关
        if self.var_show_rms.get():
            # 同一 y 值可能既是某频带 C/D 又是另一频带 B/C（如发电机 10），合并为一条线、一段文字
            line_items = {}  # y -> {"color": 颜色, "texts": [标注]}
            if self.var_show_bc.get():
                for y in sorted(bc_map):
                    d = line_items.setdefault(y, {"color": VDI_BC_COLOR, "texts": []})
                    d["texts"].append("B/C %g（%s）" % (y, "、".join(sorted(bc_map[y]))))
            if self.var_show_cd.get():
                for y in sorted(cd_map):
                    d = line_items.setdefault(y, {"color": VDI_CD_COLOR, "texts": []})
                    d["color"] = VDI_CD_COLOR  # 同一高度含危险线时按更严重的红色显示
                    d["texts"].append("C/D %g（%s）" % (y, "、".join(sorted(cd_map[y]))))
            ys_all = sorted(line_items)
            span_all = (ys_all[-1] - ys_all[0]) if len(ys_all) > 1 else 1.0
            last_y = None
            dy = 0
            for y in ys_all:
                d = line_items[y]
                self.ax.axhline(y, color=d["color"], ls="--", lw=1.3, zorder=4, label="_nolegend_")
                # 标注放在绘图区右边框外侧；几个频带阈值挨得太近时上下错开，避免文字叠在一起
                if last_y is not None and abs(y - last_y) < span_all * 0.05:
                    dy += 14
                else:
                    dy = 0
                last_y = y
                self.ax.annotate("  ".join(d["texts"]), xy=(1.02, y),
                                 xycoords=("axes fraction", "data"),
                                 xytext=(0, dy), textcoords="offset points",
                                 color=d["color"], fontsize=8, ha="left", va="center",
                                 zorder=7, annotation_clip=False)
        if self.var_show_ge.get() and self.alarm.get("ge") is not None:
            self.ax.axhline(self.alarm["ge"], color="red", ls=":", lw=1.3,
                            label=f"gE报警 {self.alarm['ge']:.2f}")
        if self.var_show_cf.get() and self.alarm.get("cf") is not None:
            self.ax2.axhline(self.alarm["cf"], color="red", ls="--", lw=1.3,
                             label=f"冲击因子报警 {self.alarm['cf']:.2f}")
        # 图例已移至画布外 tk 信息带（_refresh_trend_legend），此处不再绘制
        # X 轴：只显示年月日 2026/8/1（无时分）；短跨度每日一个刻度，长跨度自动按比例
        mdates = plt.matplotlib.dates
        # 强制缩放到数据实际时间范围，避免自动缩放拉到1970
        if all_ts:
            _tmin, _tmax = min(all_ts), max(all_ts)
            self.ax.set_xlim(_tmin - timedelta(hours=6), _tmax + timedelta(hours=6))
        _x0, _x1 = self.ax.get_xlim()
        if (_x1 - _x0) <= 1.5:
            # 一天半以内：每个出现的日期只放一个刻度（取该日落在视图内区间的中点）
            _d0 = mdates.num2date(_x0).date(); _d1 = mdates.num2date(_x1).date()
            _ticks = []; _cur = _d0
            while _cur <= _d1:
                _ds = mdates.date2num(datetime(_cur.year, _cur.month, _cur.day))
                _lo = max(_x0, _ds); _hi = min(_x1, _ds + 1.0)
                if _hi > _lo:
                    _ticks.append((_lo + _hi) / 2.0)
                _cur += timedelta(days=1)
            self.ax.xaxis.set_major_locator(plt.matplotlib.ticker.FixedLocator(_ticks))
        else:
            # 长跨度：自动按天/周/月等间隔，横排刻度适当稀疏避免拥挤
            self.ax.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=4, maxticks=7))

        def _trend_date_fmt(x, pos):
            dt = mdates.num2date(x)  # 无状态纯函数，统一 年/月/日（不补零）
            return f"{dt.year}/{dt.month}/{dt.day}"

        self.ax.xaxis.set_major_formatter(plt.matplotlib.ticker.FuncFormatter(_trend_date_fmt))
        # 标题/图例在画布外、X轴无标题；日期横排显示，底部只留单行刻度高度，把面积留给趋势图
        self.ax.tick_params(axis="x", rotation=0)
        for _lbl in self.ax.get_xticklabels():
            _lbl.set_rotation(0); _lbl.set_ha("center")
        self._apply_trend_layout()
        self.canvas.draw()
        self._trend_view0 = (self.ax.get_xlim(), self.ax.get_ylim(), self.ax2.get_ylim())

    def _apply_trend_layout(self):
        """趋势图四边留白：右侧固定留给绘图区外的 VDI 阈值文字，窗口越宽绘图区按比例变大。"""
        try:
            wpx = max(float(self.canvas.get_tk_widget().winfo_width()), 320.0)
            # 阈值文字大约需要 190px（按屏幕 DPI 等比放大），换算成 figure 比例并限幅，
            # 窄窗口/高缩放下不把绘图区挤没
            need_px = 190.0 * (float(self.fig.dpi) / 96.0)
            right = 1.0 - min(0.32, max(0.14, need_px / wpx))
        except Exception:
            right = 0.84
        try:
            self.fig.subplots_adjust(right=right, top=0.95, bottom=0.12)
        except Exception:
            pass

    def _on_trend_configure(self, event):
        size = (int(getattr(event, "width", 0) or 0), int(getattr(event, "height", 0) or 0))
        if size == getattr(self, "_trend_canvas_size", None):
            return
        self._trend_canvas_size = size
        job = getattr(self, "_trend_resize_job", None)
        if job is not None:
            try:
                self.root.after_cancel(job)
            except Exception:
                pass
        self._trend_resize_job = self.root.after(200, self._apply_trend_resize)

    def _apply_trend_resize(self):
        self._trend_resize_job = None
        if not getattr(self, "all_data", None) or not getattr(self, "checked_points", None):
            return
        try:
            self._apply_trend_layout()
            self.canvas.draw()
        except Exception:
            pass

    def _refresh_trend_legend(self, single_pt):
        # 画布外 tk 图例：只列当前勾选启用的参数，符号/颜色与曲线一致；
        # 仅勾选一个测点时文字带点名，多个测点时只显示参数名
        for w in self.trend_legend_frame.winfo_children():
            w.destroy()
        _rms_name = "RMS（分频带）"
        items = [
            (self.var_show_rms, "\u25cf", "TrendMark0.TLabel", _rms_name),
            (self.var_show_ge, "\u25a0", "TrendMark1.TLabel", "gE"),
            (self.var_show_cf, "\u25b2", "TrendMark2.TLabel", "冲击因子"),
        ]
        for var, mark, mark_style, name in items:
            if not var.get():
                continue
            text = f"{single_pt}-{name}" if single_pt else name
            cell = ttk.Frame(self.trend_legend_frame, style="TrendHeader.TFrame")
            cell.pack(side="left", padx=(0, 18))
            ttk.Label(cell, text=mark, style=mark_style, font=(UI_FONT_FAMILY, 11)).pack(side="left")
            ttk.Label(cell, text=text, style="TrendHeader.TLabel").pack(side="left", padx=(3, 0))

    def _sort_table(self, col):
        # 三态：初始(时间倒序) -> 降序 -> 升序 -> 初始
        state = self._table_sort_state.get(col, 0)
        state = (state + 1) % 3
        self._table_sort_state = {col: state}
        idx = {"time": 0, "rms": 1, "ge": 2, "cf": 3, "speed": 4, "peak": 5,
               "kurtosis": 6, "vdi": 7}[col]
        tags0 = getattr(self, "_table_tags", [() for _ in self._table_rows])
        rows = list(zip(self._table_rows, self._table_csvs, tags0))
        if state == 0:
            rows.sort(key=lambda x: x[0][0], reverse=True)  # 时间由近及远
        else:
            def keyf(x):
                v = x[0][idx]
                try: return float(v)
                except: return v
            rows.sort(key=keyf, reverse=(state == 1))
        self._table_rows = [r for r, _, _ in rows]
        self._table_csvs = [c for _, c, _ in rows]
        self._table_tags = [tg for _, _, tg in rows]
        self._table_iid_csv = {}
        for item in self.data_tree.get_children(): self.data_tree.delete(item)
        for seq, (r, c, tg) in enumerate(rows):
            iid = f"row{seq}"
            tg = tuple(t for t in tg if t != "zebra")  # 去掉旧斑马纹，按排序后的新行序重算
            if seq % 2 == 1:
                tg = tg + ("zebra",)
            self._table_iid_csv[iid] = c
            self.data_tree.insert("", "end", iid=iid, values=r, tags=tg)

    def _on_data_tree_menu(self, event):
        """数据表格右键：批量设置转速（文件名没有转速时用）。"""
        iid = self.data_tree.identify_row(event.y)
        if iid:
            self.data_tree.selection_set(iid)
        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label="设置转速…", command=self._set_speed_dialog)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _set_speed_dialog(self):
        """给一批记录补转速：写入 SQLite（表格/趋势/筛选都用）并记住到同目录 sidecar（阶次谱用）。"""
        sel = [c for c in (self.data_tree.selection() or []) if c]
        sel_paths = [self._table_iid_csv.get(i) for i in sel]
        sel_paths = [p for p in sel_paths if p]
        rows = {r.get("csv_path"): r for r in self.all_data}
        if sel_paths:
            base = rows.get(sel_paths[0]) or {}
            pt = base.get("point", "")
            info = "已选中 %d 条记录" % len(sel_paths) + ("（测点：%s）" % pt if pt else "")
            opts = [("sel", "选中的 %d 行" % len(sel_paths)),
                    ("point", "测点「%s」的全部记录" % pt if pt else "当前测点全部记录"),
                    ("all", "全部记录")]
        else:
            info = "未选中行：默认给当前测点全部记录补转速"
            opts = [("point", "当前测点全部记录"), ("all", "全部记录")]
        cur = None
        for p in sel_paths[:1]:
            try:
                cur = float(rows.get(p, {}).get("speed") or 0) or None
            except Exception:
                cur = None
        dlg = SpeedSetDialog(self.root, cur, opts, info)
        self.root.wait_window(dlg)
        if not dlg.result:
            return
        rpm, scope = dlg.result
        if scope == "sel":
            targets = sel_paths
        elif scope == "point":
            pt = (rows.get(sel_paths[0]) or {}).get("point") if sel_paths else None
            if not pt:
                pt = self._table_rows_cur_point()
            targets = [r.get("csv_path") for r in self.all_data if r.get("point") == pt]
        else:
            targets = [r.get("csv_path") for r in self.all_data]
        targets = [t for t in targets if t]
        if not targets:
            messagebox.showinfo("设置转速", "没有可更新的记录。")
            return
        changed = []
        for p in targets:
            r = rows.get(p)
            if not r:
                continue
            r["speed"] = float(rpm)
            r["speed_manual"] = True
            changed.append(r)
            speed_sidecar_save(p, rpm)
        # 按项目目录分组写库
        by_root = {}
        for r in changed:
            p = r.get("csv_path") or ""
            root = next((d for d in getattr(self, "project_dirs", [])
                         if os.path.normpath(p).startswith(os.path.normpath(d))), None)
            if root:
                by_root.setdefault(root, []).append(r)
        for d, rs in by_root.items():
            try:
                conn = db_connect(d)
                try:
                    db_upsert_rows(conn, rs)
                    conn.commit()
                finally:
                    conn.close()
            except Exception as e:
                messagebox.showerror("写入失败", "%s\n%s" % (d, e))
        self.plot_trend()
        messagebox.showinfo("设置转速", "已给 %d 条记录写入转速 %.0f rpm" % (len(changed), rpm))

    def _table_rows_cur_point(self):
        """没有选中行时，取表格第一行对应记录的测点。"""
        try:
            for r in self.all_data:
                return r.get("point")
        except Exception:
            return None

    def _on_data_row_double(self, event):
        sel = self.data_tree.selection()
        if not sel: return
        iid = sel[0]
        csv_path = self._table_iid_csv.get(iid)
        if not csv_path or not os.path.exists(csv_path):
            messagebox.showwarning("提示", f"找不到文件:\n{csv_path}"); return
        SpectrumWindow(self.root, auto_load=csv_path)

    def _on_trend_right_click(self, event):
        if event.button != 3 or event.inaxes not in (self.ax, self.ax2): return
        menu = tk.Menu(self.root, tearoff=0)
        menu.add_checkbutton(label="RMS", variable=self.var_show_rms, command=self.plot_trend)
        menu.add_checkbutton(label="gE", variable=self.var_show_ge, command=self.plot_trend)
        menu.add_checkbutton(label="冲击因子", variable=self.var_show_cf, command=self.plot_trend)
        menu.add_separator()
        menu.add_checkbutton(label="VDI B/C 报警线", variable=self.var_show_bc, command=self.plot_trend)
        menu.add_checkbutton(label="VDI C/D 危险线", variable=self.var_show_cd, command=self.plot_trend)
        menu.add_separator()
        menu.add_command(label="筛选：日期 / 转速...", command=self._open_filter_dialog)
        menu.add_command(label="复制图片", command=self._copy_trend_figure)
        menu.add_command(label="报警阈值设置...", command=self._open_alarm_dialog)
        menu.add_command(label="重置视图", command=self._reset_trend_view)
        menu.add_command(label="操作：左键拖拽框选时段 / 滚轮缩放时间轴", state="disabled")
        try:
            menu.tk_popup(event.guiEvent.x_root, event.guiEvent.y_root)
        finally:
            menu.grab_release()

    def _open_filter_dialog(self):
        # 趋势图右键弹出的日期/转速筛选框：确认后写回筛选变量并立即刷新，无需单独的“刷新绘图”按钮
        top = tk.Toplevel(self.root)
        top.title("趋势筛选")
        top.resizable(False, False)
        top.transient(self.root)
        top.withdraw()  # 先隐藏，定位完成后再显示，避免窗口管理器抢先放到默认角落
        frm = ttk.Frame(top, padding=14); frm.pack(fill="both", expand=True)
        ttk.Label(frm, text="起始日期:").grid(row=0, column=0, sticky="e", padx=4, pady=6)
        ds = DateEntry(frm, date_pattern="yyyy-MM-dd")
        ds.grid(row=0, column=1, columnspan=2, sticky="w", padx=4, pady=6)
        try: ds.set_date(self.date_start.get_date())
        except Exception: pass
        ttk.Label(frm, text="结束日期:").grid(row=1, column=0, sticky="e", padx=4, pady=6)
        de = DateEntry(frm, date_pattern="yyyy-MM-dd")
        de.grid(row=1, column=1, columnspan=2, sticky="w", padx=4, pady=6)
        try: de.set_date(self.date_end.get_date())
        except Exception: pass
        ttk.Label(frm, text="转速>=").grid(row=2, column=0, sticky="e", padx=4, pady=6)
        ev = tk.StringVar(value=self.var_speed_min.get())
        ttk.Entry(frm, textvariable=ev, width=10).grid(row=2, column=1, sticky="w", padx=4, pady=6)
        ttk.Label(frm, text="rpm（留空不过滤）").grid(
            row=2, column=2, sticky="w", padx=4)

        def apply():
            txt = ev.get().strip()
            if txt:
                try:
                    float(txt)
                except ValueError:
                    messagebox.showwarning("输入有误", "转速需为数字，或留空表示不过滤。", parent=top)
                    return
            try:
                s = ds.get_date(); e = de.get_date()
                if s > e:
                    messagebox.showwarning("日期有误", "起始日期不能晚于结束日期。", parent=top)
                    return
                self.date_start.set_date(s); self.date_end.set_date(e)
            except Exception as ex:
                messagebox.showerror("日期有误", str(ex), parent=top); return
            self.var_speed_min.set(txt)
            top.destroy()
            self.plot_trend()

        btns = ttk.Frame(frm); btns.grid(row=3, column=0, columnspan=3, pady=(10, 0))
        ttk.Button(btns, text="确认", command=apply).pack(side="left", padx=8)
        ttk.Button(btns, text="取消", command=top.destroy).pack(side="left", padx=8)
        top.bind("<Return>", lambda _e: apply())
        top.bind("<Escape>", lambda _e: top.destroy())
        top.update_idletasks()
        # 定位到趋势图标题栏正上方：相对标题水平居中、纵向贴标题上沿；并做屏幕边界保护
        anchor = self.trend_title_lbl
        # 锚点若未映射或尺寸未就绪，回退到主窗口，避免坐标取 0 导致弹窗落到屏幕左上角
        if not anchor.winfo_ismapped() or anchor.winfo_width() <= 1:
            anchor = self.root
        _dw, _dh = top.winfo_reqwidth(), top.winfo_reqheight()
        _ax, _ay = anchor.winfo_rootx(), anchor.winfo_rooty()
        _aw, _ah = anchor.winfo_width(), anchor.winfo_height()
        _x = _ax + (_aw - _dw) // 2
        _y = _ay - _dh - 6
        _sw, _sh = anchor.winfo_screenwidth(), anchor.winfo_screenheight()
        _x = max(4, min(_x, _sw - _dw - 4))
        if _y < 4:  # 标题上方空间不足时，翻到标题栏下方
            _y = _ay + _ah + 6
        _y = max(4, min(_y, _sh - _dh - 4))
        top.geometry("+%d+%d" % (_x, _y))
        top.deiconify()  # 位置确定后再显示，保证窗口管理器按目标坐标摆放
        top.update_idletasks()
        top.grab_set(); top.focus_set()

    def _copy_trend_figure(self):
        try:
            copy_figure_to_clipboard(self.fig)
            messagebox.showinfo("已复制", "趋势图图片已复制到剪贴板，可直接粘贴。", parent=self.root)
        except Exception as e:
            messagebox.showerror("复制失败", str(e), parent=self.root)

    def _open_alarm_dialog(self):
        dlg = tk.Toplevel(self.root)
        dlg.title("报警阈值设置"); dlg.transient(self.root); dlg.grab_set()
        dlg.resizable(False, False)
        ttk.Label(dlg, text="加速度 RMS 阈值线按 VDI 3834 分档自动绘制，可在趋势图右键开关 B/C、C/D 线；此处仅配置 gE/冲击因子，留空停用").grid(
            row=0, column=0, columnspan=2, padx=12, pady=(10, 4), sticky="w")
        rows = [("gE 报警值（左轴）", "ge"),
                ("冲击因子报警值（右轴，无量纲）", "cf")]
        entries = {}
        for r, (lab, key) in enumerate(rows, start=1):
            ttk.Label(dlg, text=lab).grid(row=r, column=0, padx=12, pady=6, sticky="w")
            e = ttk.Entry(dlg, width=12); e.grid(row=r, column=1, padx=12, pady=6)
            v = self.alarm.get(key)
            if v is not None: e.insert(0, f"{v:g}")
            entries[key] = e

        def apply():
            new = {"rms": None}
            for key, e in entries.items():
                txt = e.get().strip()
                if txt == "":
                    new[key] = None; continue
                try:
                    val = float(txt)
                    if val < 0: raise ValueError
                    new[key] = val
                except Exception:
                    messagebox.showerror("错误", "请输入非负数字，或留空停用", parent=dlg); return
            self.alarm = new; self.save_state(); self.plot_trend(); dlg.destroy()

        bf = ttk.Frame(dlg); bf.grid(row=4, column=0, columnspan=2, pady=10)
        ttk.Button(bf, text="确定", command=apply).pack(side="left", padx=8)
        ttk.Button(bf, text="取消", command=dlg.destroy).pack(side="left", padx=8)
        center_window_later(dlg, self.root)

    def _reset_trend_view(self):
        view = getattr(self, "_trend_view0", None)
        if not view: return
        xlim, ylim, ylim2 = view
        self.ax.set_xlim(xlim); self.ax.set_ylim(ylim); self.ax2.set_ylim(ylim2)
        self.canvas.draw()

    def _on_trend_select(self, eclick, erelease):
        if eclick.xdata is None or erelease.xdata is None: return
        x1, x2 = sorted((eclick.xdata, erelease.xdata))
        if x2 - x1 <= 0: return
        self.ax.set_xlim(x1, x2)
        # 左右轴分别按框选时段内的可见数据自适应
        groups = {self.ax: [], self.ax2: []}
        for line in self._line_rows:
            if not line.get_visible(): continue
            xy = line.get_xydata()
            if len(xy) == 0: continue
            xs, ys = xy[:, 0], xy[:, 1]
            m = (xs >= x1) & (xs <= x2)
            if m.any():
                groups.setdefault(line.axes, []).append((float(np.min(ys[m])), float(np.max(ys[m]))))
        for ax, vals in groups.items():
            if not vals: continue
            lo = min(v[0] for v in vals); hi = max(v[1] for v in vals)
            pad = (hi - lo) * 0.1 or (abs(hi) * 0.1 or 1.0)
            ax.set_ylim(lo - pad, hi + pad)
        self.canvas.draw()

    def _on_trend_scroll(self, event):
        # 仅按住 Shift 时滚轮才缩放，普通滚轮不触发
        if not shift_pressed(event): return
        if event.inaxes not in (self.ax, self.ax2) or event.xdata is None: return
        xlo, xhi = self.ax.get_xlim()
        factor = 0.8 if event.button == "up" else 1.25  # 上滚放大、下滚缩小
        anchor = event.xdata
        self.ax.set_xlim(anchor - (anchor - xlo) * factor,
                         anchor + (xhi - anchor) * factor)  # 共享X轴，右轴自动跟随
        self.canvas.draw()

    def _on_trend_double(self, event):
        if event.button != 1 or not getattr(event, "dblclick", False): return
        if event.inaxes not in (self.ax, self.ax2) or event.xdata is None or event.ydata is None: return
        best = None; best_d = 25.0  # 像素阈值，点空白处不误跳
        mx, my = event.x, event.y
        for line, dl in self._line_rows.items():
            if not line.get_visible(): continue
            xy = line.get_xydata()
            if len(xy) == 0: continue
            pix = line.axes.transData.transform(xy)  # 各曲线用所属坐标轴换算像素
            for i, (px, py) in enumerate(pix):
                d = ((px - mx) ** 2 + (py - my) ** 2) ** 0.5
                if d < best_d:
                    best_d = d; best = (dl, i)
        if best is None: return
        dl, i = best
        if i >= len(dl): return
        csv_path = dl[i].get("csv_path")
        if not csv_path or not os.path.exists(csv_path):
            messagebox.showwarning("提示", f"找不到文件:\n{csv_path}")
            return
        SpectrumWindow(self.root, init_dir=self.main_dir, auto_load=csv_path)

    def export_excel(self):
        if not self.all_data: messagebox.showinfo("提示", "暂无数据"); return
        units = sorted({r["unit"] for r in self.all_data if r["unit"]})
        points = sorted({r["point"] for r in self.all_data if r["point"]})
        dlg = ExportDialog(self.root, units, points); self.root.wait_window(dlg)
        if not dlg.result: return
        scope, uf, pf = dlg.result
        rows = self._filtered_rows(uf, pf) if scope == "one" else self._filtered_rows()
        if not rows: messagebox.showinfo("提示", "无数据"); return
        out = [{"项目": r["project"], "机组": r["unit"], "测点": r["point"], "日期": r["dt_date"],
                "当日最大有效值": round(r["rms"], 4), "报警阈值": r["threshold"],
                "带通下限Hz": r["f_low"], "带通上限Hz": r["f_high"], "转速": r.get("speed")} for r in rows]
        sp = filedialog.asksaveasfilename(defaultextension=".xlsx", filetypes=[("Excel", "*.xlsx")])
        if not sp: return
        pd.DataFrame(out).to_excel(sp, index=False)
        messagebox.showinfo("成功", f"导出{len(out)}条\n{sp}")

    def save_state(self):
        # 先读回现有状态再更新，保留窗口几何等由别处写入的键，避免整体覆写丢失
        st = _read_state_dict()
        st.update({"main_dir": self.main_dir,
                   "project_dirs": list(getattr(self, "project_dirs", [])),
                   "checked": list(self.checked_points),
                   "start": self.date_start.get(), "end": self.date_end.get(), "speed": self.var_speed_min.get(),
                   "show_rms": self.var_show_rms.get(), "show_ge": self.var_show_ge.get(),
                   "show_cf": self.var_show_cf.get(),
                   "show_bc": self.var_show_bc.get(), "show_cd": self.var_show_cd.get(),
                   "band": self.var_band.get(),
                   "alarm": self.alarm})
        try:
            with open(STATE_FILE, "w", encoding="utf-8") as fp:
                json.dump(st, fp, ensure_ascii=False)
        except: pass

    def load_state(self):
        if not os.path.exists(STATE_FILE): return
        try: st = json.load(open(STATE_FILE, encoding="utf-8"))
        except: return
        self.main_dir = st.get("main_dir", "")
        self.project_dirs = [d for d in (st.get("project_dirs") or [])
                             if isinstance(d, str) and d and os.path.isdir(d)]
        if self.main_dir and os.path.isdir(self.main_dir) and self.main_dir not in self.project_dirs:
            self.project_dirs.insert(0, self.main_dir)
        self.checked_points = set(st.get("checked", []))
        try: self.date_start.set_date(st.get("start")); self.date_end.set_date(st.get("end"))
        except: pass
        self.var_speed_min.set(st.get("speed", ""))
        self.var_show_bc.set(bool(st.get("show_bc", True)))
        self.var_show_cd.set(bool(st.get("show_cd", True)))
        self.var_show_rms.set(bool(st.get("show_rms", True)))
        self.var_show_ge.set(bool(st.get("show_ge", False)))
        self.var_show_cf.set(bool(st.get("show_cf", False)))
        _saved_band = st.get("band", "vdi_mid")
        if _saved_band in _VDI_BAND_ORDER:
            self.var_band.set(_saved_band)
        saved_alarm = st.get("alarm")
        if isinstance(saved_alarm, dict):
            for k in ("rms", "ge", "cf"):
                v = saved_alarm.get(k)
                self.alarm[k] = float(v) if v is not None else None
        if self.main_dir and os.path.isdir(self.main_dir):
            self.dir_label.config(text=self.main_dir)
            self.load_all_files(on_done=lambda: (self._sync_dates_to_data(),
                                                self.build_tree(), self.plot_trend()))

    def on_close(self):
        self.save_state()
        try:
            if getattr(self, "_trend_resize_job", None):
                self.root.after_cancel(self._trend_resize_job)
                self._trend_resize_job = None
        except Exception:
            pass
        try:
            plt.close(self.fig)   # 释放全局 Figure 注册表，避免进程退出前内存不回收
        except Exception:
            pass
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    apply_app_theme(root)
    app = VibGUI(root)
    root.mainloop()
