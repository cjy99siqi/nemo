# -*- coding: utf-8 -*-
"""转速堆叠谱 / 阶次堆叠图（独立小工具，不改主程序）

做什么
------
把同一测点在一段时间内的多条记录，按转速分箱（默认 20rpm），每箱取**中位数谱**：

- 横轴=频率：图是「转速-频率-幅值」，阶次是**斜线**，固定频率是**水平线**；
- 横轴=阶次：图是「阶次-转速-幅值」，阶次是**竖直线**，固定频率是**双曲线**。

两种模式都能叠加 1X/2X/啮合/BPFO 参考线。

用法
----
图形界面：
    python tools\\转速堆叠谱.py

命令行：
    python tools\\转速堆叠谱.py --dir "D:\\数据\\府谷\\2026\\06" --point "121#_齿轮箱_中部径向" --min-speed 1500 --bin 20 --axis freq --fmax 900 --orders "1,2,23" --out 堆叠.png
    python tools\\转速堆叠谱.py --dir "D:\\数据\\府谷\\2026\\06" --point "121#_齿轮箱_中部径向" --min-speed 1500 --bin 20 --axis order --omax 28 --orders "1,2,23" --out 阶次堆叠.png
"""

import argparse
import glob
import importlib.util
import os
import queue
import re
import sqlite3
import zlib
import sys
import threading
from datetime import datetime

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
if getattr(sys, "frozen", False):
    APP_DIR = os.path.dirname(os.path.abspath(sys.executable))
    HERE = APP_DIR
else:
    APP_DIR = os.path.dirname(HERE)
APP_PY = os.path.join(APP_DIR, "振动分析.py")


def _load_app():
    spec = importlib.util.spec_from_file_location("vib_app", APP_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


APP = _load_app()

CACHE_DB = os.path.join(APP_DIR, "数据", "转速堆叠缓存.sqlite")
_MACHINE_FILE = os.path.join(APP_DIR, "数据", "机型库.json")
_BEARING_FILE = os.path.join(APP_DIR, "数据", "轴承库.json")
_LIB_CACHE = {}


def _load_json(path):
    try:
        import json
        with open(path, encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        return {}


def _norm(text):
    return "".join(ch for ch in str(text or "")
                   if ch.isalnum() or "一" <= ch <= "鿿")


def auto_orders(dir_path, point_name, omax=28.0):
    """按机型库给当前测点自动生成参考阶次：1X/2X + 齿啮合阶次 + 轴承 BPFO/BPFI/BSF。"""
    lib = _LIB_CACHE.get("machines")
    if lib is None:
        lib = _load_json(_MACHINE_FILE).get("machines") or {}
        _LIB_CACHE["machines"] = lib
    bearings = _LIB_CACHE.get("bearings")
    if bearings is None:
        bearings = _load_json(_BEARING_FILE).get("bearings") or {}
        _LIB_CACHE["bearings"] = bearings

    nd = _norm(dir_path)
    np_ = _norm(point_name)
    prof = None
    for name, p in lib.items():
        for kw in (p.get("projects") or []):
            if _norm(kw) and _norm(kw) in nd:
                prof = p
                break
        if prof:
            break
    if prof is None:
        return [1.0, 2.0]

    shafts = prof.get("shafts") or {}
    gears = prof.get("gears") or []
    point_map = prof.get("points") or []
    orders = [1.0, 2.0]
    hit_bearings = []
    for kw, blist in point_map:
        if _norm(kw) and _norm(kw) in np_:
            hit_bearings.extend(blist or [])
            break
    for bname in hit_bearings:
        info = bearings.get(bname) or {}
        ratio = float(shafts.get(info.get("shaft") or "H") or 1.0)
        for key in ("BPFO", "BPFI"):
            try:
                o = float(info.get(key)) * ratio
            except (TypeError, ValueError):
                continue
            if 1.0 <= o <= float(omax):
                orders.append(round(o, 3))
    for g in gears:
        try:
            o = float(g.get("teeth")) * float(shafts.get(g.get("shaft") or "H") or 1.0)
        except (TypeError, ValueError):
            continue
        if 1.0 <= o <= float(omax):
            orders.append(round(o, 3))
    # 保留先加入的（主轴承在前），近似重合的备选轴承阶次丢弃
    uniq = []
    for o in orders:
        if all(abs(o - u) > 0.01 * max(o, 1.0) for u in uniq):
            uniq.append(o)
    return sorted(uniq)


def _cache_conn():
    try:
        os.makedirs(os.path.dirname(CACHE_DB), exist_ok=True)
        conn = sqlite3.connect(CACHE_DB, timeout=10)
        conn.execute("CREATE TABLE IF NOT EXISTS curves ("
                     "path TEXT, mtime REAL, omax REAL, dorder REAL, kind TEXT, "
                     "lo REAL, hi REAL, data BLOB, "
                     "PRIMARY KEY(path, mtime, omax, dorder, kind, lo, hi))")
        return conn
    except Exception:
        return None


def cache_get(path, omax, dorder, kind, lo, hi):
    conn = _cache_conn()
    if conn is None:
        return None
    try:
        st = os.stat(path)
        row = conn.execute(
            "SELECT data FROM curves WHERE path=? AND mtime=? AND omax=? AND dorder=? "
            "AND kind=? AND lo=? AND hi=?",
            (path, st.st_mtime, float(omax), float(dorder), kind, float(lo), float(hi))
        ).fetchone()
        if row is None:
            return None
        return np.frombuffer(zlib.decompress(row[0]), dtype=np.float32).copy()
    except Exception:
        return None
    finally:
        conn.close()


def cache_put(path, omax, dorder, kind, lo, hi, arr):
    conn = _cache_conn()
    if conn is None:
        return
    try:
        st = os.stat(path)
        blob = zlib.compress(np.asarray(arr, dtype=np.float32).tobytes(), 6)
        conn.execute(
            "INSERT OR REPLACE INTO curves VALUES (?,?,?,?,?,?,?,?)",
            (path, st.st_mtime, float(omax), float(dorder), kind, float(lo), float(hi), blob))
        conn.commit()
    except Exception:
        pass
    finally:
        conn.close()

APP_ID = "VibSpec.SpeedStack.1"


def _set_app_id(appid=APP_ID):
    """Windows 任务栏图标：不设 AppUserModelID 时，pythonw 启动的窗口会被归到 Python 图标下。

    必须在创建任何窗口之前调用；设了之后任务栏用窗口自己的 iconbitmap/iconphoto。
    """
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(appid)
    except Exception:
        pass


_set_app_id()


def parse_orders(text):
    """'1, 2, 23' -> [1.0, 2.0, 23.0]（去空、去非法、保持顺序）"""
    out = []
    for part in str(text or "").replace("，", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            v = float(part)
        except ValueError:
            continue
        if v > 0 and v not in out:
            out.append(v)
    return out


def _project_db(root):
    """向上找主程序的 vib_cache.db（最多 4 层），用于快速取文件清单。"""
    d = os.path.abspath(root)
    for _ in range(4):
        p = os.path.join(d, "vib_cache.db")
        if os.path.isfile(p):
            return p
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return None


def _scan_from_db(root, point_kw, date_from, date_to, min_speed, max_records):
    """用主程序 SQLite 缓存取记录：几万条也只要 0.1–0.2 秒，不再 walk 目录。"""
    dbp = _project_db(root)
    if not dbp:
        return None
    try:
        conn = sqlite3.connect(dbp, timeout=10)
        rows = conn.execute(
            "SELECT csv_path, speed, dt_str FROM records WHERE speed>=?",
            (float(min_speed),)).fetchall()
        conn.close()
    except Exception:
        return None
    d0 = re.sub(r"[^0-9]", "", str(date_from))[:8]
    d1 = re.sub(r"[^0-9]", "", str(date_to))[:8]
    out = []
    for path, spd, dt in rows:
        if not path or not os.path.isfile(path):
            continue
        base = os.path.basename(path)
        if point_kw and point_kw not in base:
            continue
        d8 = re.sub(r"[^0-9]", "", str(dt or ""))[:8]
        if d0 and d8 and d8 < d0:
            continue
        if d1 and d8 and d8 > d1:
            continue
        out.append((float(spd or 0), d8, path))
        if len(out) >= max_records:
            break
    out.sort()
    return out


def scan_records(root, point_kw="", date_from="", date_to="", min_speed=0.0,
                 max_records=3000):
    """按测点关键字/日期/转速筛出记录；优先查主程序 SQLite，查不到再 walk 目录。"""
    point_kw = (point_kw or "").strip()
    fast = _scan_from_db(root, point_kw, date_from, date_to, min_speed, max_records)
    if fast:
        return fast
    out = []
    for p in glob.iglob(os.path.join(root, "**", "*.csv"), recursive=True):
        base = os.path.basename(p)
        # 先按文件名里的测点关键字过滤（根本不解析其它测点），3900 个文件时快 10 倍以上
        if point_kw and point_kw not in base:
            continue
        info = APP.parse_filename(base) or {}
        spd = float(info.get("speed") or 0)
        if spd < float(min_speed):
            continue
        if point_kw and point_kw not in os.path.basename(p):
            continue
        # parse_filename 的 dt 有时是 datetime、有时是字符串，统一取 YYYYMMDD 再比较，
        # 否则字符串 "2026-06-01 01:00:06" 和 "20260601" 比较会把所有记录都过滤掉
        _dt = info.get("dt")
        if isinstance(_dt, datetime):
            d8 = _dt.strftime("%Y%m%d")
        else:
            d8 = re.sub(r"[^0-9]", "", str(_dt or ""))[:8]
        if date_from and d8 and d8 < re.sub(r"[^0-9]", "", str(date_from))[:8]:
            continue
        if date_to and d8 and d8 > re.sub(r"[^0-9]", "", str(date_to))[:8]:
            continue
        out.append((spd, d8, p))
        if len(out) >= max_records:
            break
    out.sort()
    return out


def raw_signal(path):
    """读单条记录：返回 (sig, fs, rpm)。"""
    info = APP.parse_filename(os.path.basename(path)) or {}
    fs = info.get("fs")
    if not fs:
        return None, None, 0.0
    sig, _ = APP.read_signal_csv(path)
    if sig is None or len(sig) < 64:
        return None, None, 0.0
    return sig, float(fs), float(info.get("speed") or 0)


def envelope_from_signal(sig, fs, lo, hi):
    """带通 + Hilbert 解调，返回包络谱 (f, amp)。"""
    from scipy.signal import hilbert, sosfiltfilt
    sos = APP.design_band(fs, lo, hi, sos=True)
    filt = sosfiltfilt(sos, sig)
    env = np.abs(hilbert(filt))
    env = env - np.mean(env)
    n = len(env)
    w = np.hanning(n)
    amp = (2.0 / n) * 2.0 * np.abs(np.fft.rfft(env * w))
    return np.fft.rfftfreq(n, 1.0 / fs), amp


def envelope_spectrum(path, lo=1000.0, hi=4000.0):
    sig, fs, _rpm = raw_signal(path)
    if sig is None:
        return None, None
    return envelope_from_signal(sig, fs, lo, hi)


def raw_spectrum(path):
    """单条记录的原始幅值谱 (f, amp)，不做分箱。"""
    info = APP.parse_filename(os.path.basename(path)) or {}
    fs = info.get("fs")
    if not fs:
        return None, None
    sig, _ = APP.read_signal_csv(path)
    n = len(sig)
    if n < 64:
        return None, None
    w = np.hanning(n)
    amp = 2.0 * np.abs(np.fft.rfft((sig - np.mean(sig)) * w)) / w.sum()
    f = np.fft.rfftfreq(n, 1.0 / float(fs))
    return f, amp


def freq_curve(path, fmax, df):
    """幅值谱按 df 分箱取均值；返回 (bin_centers, amp)。"""
    f, amp = raw_spectrum(path)
    if f is None:
        return None, None
    nb = int(float(fmax) / float(df))
    idx = np.clip((f / float(df)).astype(int), 0, nb - 1)
    b = np.zeros(nb)
    c = np.zeros(nb)
    np.add.at(b, idx, amp)
    np.add.at(c, idx, 1)
    return np.arange(nb) * float(df) + float(df) / 2.0, b / np.maximum(c, 1)


def env_freq_curve(path, fmax, df, lo=1000.0, hi=4000.0):
    f, amp = envelope_spectrum(path, lo, hi)
    if f is None:
        return None, None
    nb = int(float(fmax) / float(df))
    idx = np.clip((f / float(df)).astype(int), 0, nb - 1)
    b = np.zeros(nb); c = np.zeros(nb)
    np.add.at(b, idx, amp); np.add.at(c, idx, 1)
    return np.arange(nb) * float(df) + float(df) / 2.0, b / np.maximum(c, 1)


def env_order_curve(path, omax, dorder, lo=1000.0, hi=4000.0):
    info = APP.parse_filename(os.path.basename(path)) or {}
    rpm = float(info.get("speed") or 0)
    if rpm <= 0:
        return None, None
    f, amp = envelope_spectrum(path, lo, hi)
    if f is None:
        return None, None
    return resample_to_order(f, amp, rpm / 60.0, omax, dorder)


def resample_to_order(f, amp, fr, omax, dorder):
    """把 (f, amp) 重采样到阶次轴：order = f / (rpm/60)。"""
    n = max(int(float(omax) / float(dorder)), 1)
    orders = np.arange(n) * float(dorder) + float(dorder) / 2.0
    a = np.interp(orders * float(fr), f, amp, left=0.0, right=0.0)
    return orders, a


def order_curve(path, omax, dorder, kind="raw", lo=1000.0, hi=4000.0):
    """单条记录的阶次谱 (order_centers, amp)，带 SQLite 缓存。"""
    cached = cache_get(path, omax, dorder, kind, lo, hi)
    n = max(int(float(omax) / float(dorder)), 1)
    orders = np.arange(n) * float(dorder) + float(dorder) / 2.0
    if cached is not None and len(cached) == n:
        return orders, cached
    info = APP.parse_filename(os.path.basename(path)) or {}
    rpm = float(info.get("speed") or 0)
    if rpm <= 0:
        return None, None
    if kind == "envelope":
        f, amp = envelope_spectrum(path, lo, hi)
    else:
        f, amp = raw_spectrum(path)
    if f is None:
        return None, None
    o, a = resample_to_order(f, amp, rpm / 60.0, omax, dorder)
    cache_put(path, omax, dorder, kind, lo, hi, a)
    return o, a


def stack_by_speed(records, bw=20.0, min_per_bin=2, domain="freq", fmax=900.0,
                   df=2.0, omax=28.0, dorder=0.02, max_per_bin=0,
                   spectrum="raw", env_lo=1000.0, env_hi=4000.0):
    """records: [(rpm, path)] -> (centers, matrix[axis, bin], used, total)。

    matrix 的纵轴量纲随 domain 变化：freq 是 Hz，order 是阶次。
    """
    if max_per_bin and int(max_per_bin) > 0:
        # 每个转速箱最多取 N 条（间隔取样，保持转速覆盖），大幅减少读文件/FFT 次数；
        # 中位数本来也不需要几千条，10 条就足够稳
        buckets = {}
        for rpm, p in records:
            buckets.setdefault(int(float(rpm) // float(bw)), []).append((rpm, p))
        picked = []
        for _k in sorted(buckets):
            lst = buckets[_k]
            n = int(max_per_bin)
            step = max(1, len(lst) // n)
            picked.extend(lst[::step][:n])
        records = picked
    curves = []
    for rpm, p in records:
        if domain == "order":
            if spectrum == "envelope":
                x, a = order_curve(p, omax, dorder, kind="envelope", lo=env_lo, hi=env_hi)
            else:
                x, a = order_curve(p, omax, dorder, kind="raw")
        else:
            if spectrum == "envelope":
                x, a = env_freq_curve(p, fmax, df, env_lo, env_hi)
            else:
                x, a = freq_curve(p, fmax, df)
        if x is None:
            continue
        curves.append((float(rpm), a))
    centers, matrix, used = stack_curves(curves, bw=bw, min_per_bin=min_per_bin)
    return centers, matrix, used, len(curves)


def stack_curves(curves, bw=20.0, min_per_bin=2):
    """把 [(rpm, curve)] 按转速分箱取中位数；返回 (centers, matrix, used)。"""
    if not curves:
        return np.array([]), np.empty((0, 0)), 0
    lo = min(s for s, _ in curves)
    hi = max(s for s, _ in curves)
    start = np.floor(lo / bw) * bw
    edges = np.arange(start, hi + bw, bw)
    centers, mats, used = [], [], 0
    for a, b in zip(edges[:-1], edges[1:]):
        sel = [m for s, m in curves if a <= s < b]
        if len(sel) < min_per_bin:
            continue
        centers.append((a + b) / 2.0)
        mats.append(np.median(np.array(sel), axis=0))
        used += len(sel)
    if not centers:
        return np.array([]), np.empty((0, 0)), 0
    return np.array(centers), np.array(mats).T, used


def detect_fixed(centers, matrix, axis, df=2.0, dorder=0.02, fmax=900.0,
                 topn=4):
    """从堆叠矩阵里找“不随转速移动”的固定频率。

    做法：在频率域沿竖直列取中位数（阶次域沿 order=f/(rpm/60) 双曲线取中位数），
    固定频率的得分会明显高于斜线/竖线，取前 topn 个峰。
    """
    if matrix.size == 0 or len(centers) == 0:
        return []
    from scipy.signal import find_peaks
    if axis == "order":
        o_axis = np.arange(matrix.shape[0]) * float(dorder) + float(dorder) / 2.0
        cand = np.arange(50.0, float(fmax), 2.0)
        score = []
        for f in cand:
            vals = []
            for i, rpm in enumerate(centers):
                o = f / (rpm / 60.0)
                if o <= o_axis[-1]:
                    j = int(round((o - dorder / 2.0) / dorder))
                    if 0 <= j < matrix.shape[0]:
                        vals.append(matrix[j, i])
            score.append(float(np.median(vals)) if vals else 0.0)
        score = np.asarray(score)
    else:
        cand = np.arange(matrix.shape[0]) * float(df) + df / 2.0
        score = np.median(matrix, axis=1)
    pk, _ = find_peaks(score, height=float(np.max(score)) * 0.3, distance=5)
    if len(pk) == 0:
        return []
    _step = float(cand[1] - cand[0]) if len(cand) > 1 else 1.0
    picked = []
    for i in pk[np.argsort(score[pk])[::-1]]:
        # 抛物线插值细化到小数（否则按 2Hz 网格只能得到整数）
        f = float(cand[i])
        if 0 < i < len(score) - 1:
            y0, y1, y2 = float(score[i - 1]), float(score[i]), float(score[i + 1])
            den = y0 - 2.0 * y1 + y2
            if abs(den) > 1e-12:
                f += 0.5 * (y0 - y2) / den * _step
        if all(abs(f - g) > 0.02 * max(f, g) for g in picked):
            picked.append(f)
        if len(picked) >= topn:
            break
    picked.sort()
    out = []
    for f in picked:
        if all(abs(f - g) > 0.02 * max(f, g) for g in out):
            out.append(f)
    return out


def render(centers, matrix, orders, axis, title, out_path=None, dpi=130,
           fmax=900.0, df=2.0, omax=28.0, dorder=0.02, fixed=None):
    """出图；axis='freq' 时纵轴频率、'order' 时纵轴阶次。"""
    import matplotlib
    if out_path:
        matplotlib.use("Agg")
    matplotlib.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei"]
    matplotlib.rcParams["axes.unicode_minus"] = False
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg

    fig = Figure(figsize=(11, 6), dpi=dpi)
    fig.patch.set_facecolor("#e2e7ed")
    FigureCanvasAgg(fig)
    try:
        fig.set_layout_engine("constrained")
    except Exception:
        pass
    ax = fig.add_subplot(111)
    ax.set_facecolor("#e2e7ed")
    if matrix.size == 0 or len(centers) == 0:
        ax.text(0.5, 0.5, "没有满足条件的记录", ha="center", va="center",
                transform=ax.transAxes)
        ax.set_axis_off()
        return fig
    db = 20.0 * np.log10(np.maximum(matrix, np.max(matrix) * 1e-5))
    if axis == "order":
        y = np.arange(matrix.shape[0]) * float(dorder) + float(dorder) / 2.0
        mesh = ax.pcolormesh(y, centers, db.T, shading="auto", cmap="magma",
                             vmin=np.percentile(db, 60), vmax=float(np.max(db)))
        # 阶次竖线 + 标签：分散的按 上/中/下 轮流，挨得近的一左一右
        import matplotlib.patheffects as _pe
        _axw = max(float(fig.get_size_inches()[0] * fig.dpi) * 0.72, 200.0)
        _items = []
        for k in orders:
            if k > omax:
                continue
            ax.axvline(k, color="#7fffd4", lw=1.0, ls="--", alpha=0.9, zorder=3)
            _ords = np.arange(matrix.shape[0]) * float(dorder) + float(dorder) / 2.0
            _m = np.abs(_ords - float(k)) <= max(2.0 * float(dorder), 0.04)
            _amp = float(np.max(matrix[_m, :])) if np.any(_m) else 0.0
            _lw = max(len("%.2fX" % k), len("%.2f" % _amp))
            _items.append((float(k), ("%.2fX" + chr(10) + "%.2f") % (k, _amp),
                           (_lw * 9.0 * 0.62 + 8.0) / _axw))
        _items.sort()

        # 簇：居中会互相压到的算一簇
        _clusters = []
        for it in _items:
            if _clusters:
                _prev = _clusters[-1][-1]
                if (it[0] - _prev[0]) / float(omax) < (_prev[2] + it[2]) / 2.0 - 0.004:
                    _clusters[-1].append(it)
                    continue
            _clusters.append([it])

        _zones = (0.90, 0.50, 0.12, 0.72, 0.30)
        _zi = 0
        for _cl in _clusters:
            if len(_cl) == 1:
                k, txt, w = _cl[0]
                _y = _zones[_zi % len(_zones)]
                _zi += 1
                _xx = k / float(omax)
                _ha, _dx = "center", 0
                if _xx - w / 2.0 < 0.002:
                    _ha, _dx = "left", 6
                elif _xx + w / 2.0 > 0.996:
                    _ha, _dx = "right", -6
                ax.annotate(txt, xy=(k, _y), xycoords=("data", "axes fraction"),
                            xytext=(_dx, 0), textcoords="offset points",
                            color="#ffffff", fontsize=9, ha=_ha, va="center",
                            linespacing=1.05, zorder=9,
                            path_effects=[_pe.withStroke(linewidth=1.6,
                                                         foreground="#222222")])
            else:
                # 近的：不仅左右分开，纵向也各占一行
                for _i, (k, txt, w) in enumerate(_cl):
                    _y = _zones[_zi % len(_zones)]
                    _zi += 1
                    _left = (_i % 2 == 0)
                    ax.annotate(txt, xy=(k, _y), xycoords=("data", "axes fraction"),
                                xytext=(-6 if _left else 6, 0), textcoords="offset points",
                                color="#ffffff", fontsize=9,
                                ha=("right" if _left else "left"), va="center",
                                linespacing=1.05, zorder=9,
                                path_effects=[_pe.withStroke(linewidth=1.6,
                                                             foreground="#222222")])

        # 固定频率曲线 + 单行标签（8pt、无背景，错层摆放）
        rr = np.linspace(float(np.min(centers)), float(np.max(centers)), 100)
        _fixed_slots = (0.90, 0.62, 0.34, 0.10)
        for _fi, ffix in enumerate(fixed if fixed is not None else []):
            ax.plot(ffix / (rr / 60.0), rr, color="#ffffff", lw=0.8, ls=":",
                    alpha=0.75)
            _yf = _fixed_slots[_fi % len(_fixed_slots)]
            _rpm = float(np.min(centers)) + _yf * (float(np.max(centers)) - float(np.min(centers)))
            _o = ffix / (_rpm / 60.0)
            if 0 < _o < float(omax):
                ax.annotate("%.2fHz" % ffix, xy=(_o, _yf),
                            xycoords=("data", "axes fraction"),
                            xytext=(3, 0), textcoords="offset points",
                            color="#555555", fontsize=8, ha="left", va="center",
                            zorder=8)
        ax.set_xlabel("阶次（×1X）")
        ax.set_ylabel("转速 (rpm)")
        ax.set_xlim(0, float(omax))
    else:
        y = np.arange(matrix.shape[0]) * float(df) + float(df) / 2.0
        mesh = ax.pcolormesh(centers, y, db, shading="auto", cmap="magma",
                             vmin=np.percentile(db, 60), vmax=float(np.max(db)))
        r = np.linspace(float(np.min(centers)), float(np.max(centers)), 200)
        colors = ["#7fffd4", "#ffffff", "#ffb347", "#87cefa", "#ff69b4"]
        for i, k in enumerate(orders):
            ax.plot(r, k * r / 60.0, color=colors[i % len(colors)], lw=1.0, ls="--")
            yy = k * float(np.max(centers)) / 60.0
            if yy < fmax:
                ax.annotate("%gX" % k, (float(np.max(centers)) * 0.995, yy),
                            color=colors[i % len(colors)], fontsize=9.5, ha="right")
        for ffix in (fixed if fixed is not None else []):
            if ffix <= fmax:
                ax.axhline(ffix, color="#ffffff", lw=0.7, ls=":", alpha=0.75)
                ax.annotate("%.2fHz" % ffix, (float(np.min(centers)), ffix),
                            color="#ffffff", fontsize=9, va="bottom")
        ax.set_xlabel("转速 (rpm)")
        ax.set_ylabel("频率 (Hz)")
        ax.set_ylim(0, float(fmax))
    cb = fig.colorbar(mesh, ax=ax)
    cb.set_label("相对幅值 (dB)", fontsize=9)
    cb.ax.tick_params(labelsize=9)
    # 不画图顶部标题（测点/参数已在窗口标题条和状态栏），坐标字号与主程序时域图一致
    ax.tick_params(axis="both", labelsize=10)
    ax.xaxis.label.set_size(10)
    ax.yaxis.label.set_size(10)
    if out_path:
        fig.savefig(out_path)
    return fig


def run_cli(args):
    records = scan_records(args.dir, args.point, args.date_from, args.date_to,
                           args.min_speed, args.max_records)
    if not records:
        print("没有匹配的记录（检查 --dir/--point/--min-speed）")
        return 2
    recs_pairs = [(s, p) for s, _, p in records]
    if args.precompute:
        lo, hi = args.env_lo, args.env_hi
        done = 0
        for rpm, p in recs_pairs:
            order_curve(p, args.omax, args.dorder, kind="raw")
            order_curve(p, args.omax, args.dorder, kind="envelope", lo=lo, hi=hi)
            done += 1
            if done % 10 == 0:
                print("预计算 %d/%d" % (done, len(recs_pairs)), flush=True)
        print("预计算完成：%d 条" % len(recs_pairs))
        return 0
    centers, matrix, used, total = stack_by_speed(
        [(s, p) for s, _, p in records], bw=args.bin, min_per_bin=args.min_per_bin,
        domain=args.axis, fmax=args.fmax, omax=args.omax, dorder=args.dorder,
        max_per_bin=args.max_per_bin, spectrum=args.spectrum,
        env_lo=args.env_lo, env_hi=args.env_hi)
    _spec = ("包络 %g–%gHz，" % (args.env_lo, args.env_hi)
             if args.spectrum == "envelope" else "")
    title = "%s（%s%s，%d/%d 条，%d 箱，中位数）" % (
        args.point or os.path.basename(args.dir.rstrip("/\\")), _spec,
        "阶次" if args.axis == "order" else "频率", used, total, len(centers))
    out = args.out or os.path.join(APP_DIR, "转速堆叠谱.png")
    fixed = []
    if str(args.fixed).strip().lower() == "auto":
        fixed = detect_fixed(centers, matrix, args.axis, fmax=args.fmax,
                             dorder=args.dorder)
    elif str(args.fixed).strip().lower() not in ("", "none", "0"):
        fixed = [float(x) for x in str(args.fixed).replace("，", ",").split(",")
                 if x.strip()]
    _orders = (auto_orders(args.dir, args.point)
               if str(args.orders).strip().lower() == "auto"
               else parse_orders(args.orders))
    render(centers, matrix, _orders, args.axis, title, out,
           fmax=args.fmax, omax=args.omax, dorder=args.dorder, fixed=fixed)
    print("已保存:", out)
    print("记录 %d 条，可用 %d 条，分箱 %d 个" % (total, used, len(centers)))
    return 0


class StackWindow:
    def __init__(self, root, init=None):
        import tkinter as tk
        from tkinter import ttk, filedialog, messagebox
        self.tk = tk
        self.ttk = ttk
        self.filedialog = filedialog
        self.messagebox = messagebox
        self.root = root
        root.title("转速堆叠谱 / 阶次堆叠图（测试工具）")
        root.geometry("1100x780")
        try:
            # 直接用 Tk 的屏幕尺寸开一个接近全屏的窗口：
            # Windows 的“最大化”在这台机器上不会把 resize 传给 Tk（内容仍按 1100x780 排，
            # 右边参数和下半屏全是空白），所以默认就开大，不依赖最大化按钮。
            sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
            w = max(1000, min(sw - 40, 1800))
            h = max(700, min(sh - 90, 1100))
            root.geometry("%dx%d+%d+%d" % (w, h, max(0, (sw - w) // 2),
                                           max(0, (sh - h) // 2 - 10)))
        except Exception:
            pass

        # 图标（窗口/任务栏）
        try:
            _ico = os.path.join(HERE, "转速堆叠谱.ico")
            _png = os.path.join(HERE, "转速堆叠谱.png")
            if os.path.exists(_ico):
                root.iconbitmap(default=_ico)
            if os.path.exists(_png):
                self._icon_img = tk.PhotoImage(file=_png)
                root.iconphoto(True, self._icon_img)
        except Exception:
            pass

        self.var_dir = tk.StringVar(value=r"D:\数据\府谷6")
        self.var_point = tk.StringVar(value="121#_齿轮箱_中部径向")
        self.var_from = tk.StringVar(value="")
        self.var_to = tk.StringVar(value="")
        self.var_min = tk.StringVar(value="1500")
        self.var_bin = tk.StringVar(value="20")
        self.var_axis = tk.StringVar(value="阶次")
        self.var_fmax = tk.StringVar(value="900")
        self.var_omax = tk.StringVar(value="28")
        self.var_orders = tk.StringVar(value="1,2,23")
        self.var_fixed_on = tk.BooleanVar(value=True)
        self.var_maxbin = tk.StringVar(value="10")
        self.var_binmax = tk.StringVar(value="20/10")
        self.var_spectrum = tk.StringVar(value="原始幅值谱")
        self.var_env_lo = tk.StringVar(value="1000")
        self.var_env_hi = tk.StringVar(value="4000")
        if init:
            self.var_dir.set(str(init.get("dir") or self.var_dir.get()))
            self.var_point.set(str(init.get("point") or self.var_point.get()))
            self.var_from.set(str(init.get("date_from") or ""))
            self.var_to.set(str(init.get("date_to") or ""))
            try:
                _ms = float(init.get("min_speed") or 0)
            except (TypeError, ValueError):
                _ms = 0.0
            if _ms > 0:
                self.var_min.set("%g" % _ms)
            if init.get("bin") is not None:
                self.var_bin.set("%g" % float(init["bin"]))
            if init.get("axis") == "order":
                self.var_axis.set("阶次")
            if init.get("orders"):
                self.var_orders.set(str(init["orders"]))
            try:
                self.var_fmax.set("%g" % float(init.get("fmax") or 900))
                self.var_omax.set("%g" % float(init.get("omax") or 28))
            except Exception:
                pass

        # 标题条：从主程序打开时直接显示测点，不再让用户填“测点关键字”
        head = ttk.Frame(root, padding=(12, 10, 12, 2))
        head.pack(fill="x")
        ttk.Label(head, text="转速堆叠谱 / 阶次堆叠图",
                  font=("Microsoft YaHei", 11, "bold")).pack(side="left")
        self._hide_point = bool(init and init.get("parent_pid"))
        self.lbl_point = ttk.Label(head, text="", foreground="#1f4e79")
        self.lbl_point.pack(side="left", padx=12)
        if self._hide_point:
            self.lbl_point.config(text="测点：" + self.var_point.get())

        box = ttk.LabelFrame(root, text="参数", padding=(10, 6, 10, 8))
        box.pack(anchor="w", padx=10, pady=(2, 6))

        row = ttk.Frame(box)
        row.pack(anchor="w")
        ttk.Label(row, text="谱类型").pack(side="left", padx=(0, 4))
        ttk.Combobox(row, textvariable=self.var_spectrum,
                     values=("原始幅值谱", "包络谱"), width=10,
                     state="readonly").pack(side="left", padx=(0, 16))
        ttk.Label(row, text="最低转速").pack(side="left", padx=(0, 4))
        ttk.Entry(row, textvariable=self.var_min, width=7).pack(side="left", padx=(0, 16))
        ttk.Label(row, text="解调带").pack(side="left", padx=(0, 4))
        ttk.Entry(row, textvariable=self.var_env_lo, width=6).pack(side="left")
        ttk.Label(row, text="–").pack(side="left", padx=2)
        ttk.Entry(row, textvariable=self.var_env_hi, width=6).pack(side="left")
        ttk.Label(row, text="Hz", foreground="#666666").pack(side="left", padx=(3, 16))
        ttk.Label(row, text="分箱/每箱").pack(side="left", padx=(0, 4))
        ttk.Entry(row, textvariable=self.var_binmax, width=9).pack(side="left")

        bar = ttk.Frame(box)
        bar.pack(anchor="w", pady=(6, 0))
        ttk.Checkbutton(bar, text="自动标注固定频率曲线",
                        variable=self.var_fixed_on).pack(side="left")
        self.btn_run = ttk.Button(bar, text="生成堆叠图", width=14, command=self.run)
        self.btn_run.pack(side="left", padx=(16, 0))
        self.btn_pre = ttk.Button(bar, text="预计算缓存", width=12, command=self.precompute)
        self.btn_pre.pack(side="left", padx=(8, 0))

        # 窗口宽度 = 参数行宽度；画布/图同宽
        try:
            self.root.update_idletasks()
            sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
            # 默认宽而矮（16:9 左右），避免图又细又长；用户可自行拉伸
            _w = max(min(sw - 120, 1500), row.winfo_reqwidth() + 40)
            _h = min(sh - 80, int(_w * 0.56) + 230)
            self.root.geometry("%dx%d+%d+%d" % (
                _w, _h, max(0, (sw - _w) // 2), 50))
            self.root.resizable(True, True)
        except Exception:
            pass

        self.status = ttk.Label(root, text="就绪", relief="sunken", anchor="w",
                                padding=(10, 4))
        self.status.pack(fill="x", side="bottom")
        body_box = ttk.Frame(root, padding=(10, 0, 10, 6))
        body_box.pack(fill="both", expand=True)
        self.body = ttk.Frame(body_box)
        self.body.pack(fill="both", expand=True)
        self.placeholder = ttk.Label(
            self.body, text="设置好参数后点「生成堆叠图」",
            foreground="#8a96a6", font=("Microsoft YaHei", 12))
        self.placeholder.place(relx=0.5, rely=0.45, anchor="center")
        self.body.rowconfigure(0, weight=1)
        self.body.columnconfigure(0, weight=1)
        self._canvas = None
        self._resize_job = None
        self._busy = False
        self._q = queue.Queue()
        self._status_base = "就绪"
        try:
            self.auto_orders = auto_orders(self.var_dir.get(), self.var_point.get())
        except Exception:
            self.auto_orders = [1.0, 2.0]
        self._parent_pid = int((init or {}).get("parent_pid") or 0)
        if self._parent_pid:
            try:
                root.protocol("WM_DELETE_WINDOW", self._on_close)
            except Exception:
                pass
            root.after(1500, self._watch_parent)

    def _status(self, text):
        self._status_base = text
        self.status.config(text=text)

    def _on_close(self):
        try:
            self.root.destroy()
        except Exception:
            pass

    @staticmethod
    def _pid_alive(pid):
        if not pid:
            return False
        try:
            import ctypes
            k32 = ctypes.windll.kernel32
            SYNCHRONIZE = 0x00100000
            h = k32.OpenProcess(SYNCHRONIZE, False, int(pid))
            if not h:
                return False
            try:
                return k32.WaitForSingleObject(h, 0) == 0x102  # WAIT_TIMEOUT
            finally:
                k32.CloseHandle(h)
        except Exception:
            try:
                os.kill(int(pid), 0)
                return True
            except Exception:
                return False

    def _watch_parent(self):
        """主程序退出后自动关闭本工具（父进程还在就继续等）。"""
        if not self._parent_pid:
            return
        if not self._pid_alive(self._parent_pid):
            self._on_close()
            return
        try:
            self.root.after(2000, self._watch_parent)
        except Exception:
            pass

    def _on_canvas_resize(self, event=None):
        """画布尺寸变化：TkAgg 会自动把 Figure 设成画布大小，这里只更新状态栏。"""
        if self._canvas is None or event is None:
            return
        try:
            if getattr(self, "_status_job", None):
                self.root.after_cancel(self._status_job)
        except Exception:
            pass
        self._status_job = self.root.after(400, self._update_size_status)

    def _update_size_status(self):
        self._status_job = None
        try:
            cw = self._canvas.get_tk_widget()
            fig = self._canvas.figure
            fw, fh = fig.get_size_inches() * fig.get_dpi()
            self.status.config(text="%s | 画布 %dx%d / 图 %dx%d" % (
                self._status_base, cw.winfo_width(), cw.winfo_height(),
                round(fw), round(fh)))
        except Exception:
            pass

    def _browse(self):
        d = self.filedialog.askdirectory(initialdir=self.var_dir.get() or APP_DIR)
        if d:
            self.var_dir.set(d)

    def run(self):
        if self._busy:
            return
        axis = "order"
        try:
            _bm = str(self.var_binmax.get() or "20/10").replace("，", "/").split("/")
            bw = float(_bm[0])
            mpb = int(float(_bm[1])) if len(_bm) > 1 else 10
        except Exception:
            bw, mpb = 20.0, 10
        args = (self.var_dir.get().strip(), self.var_point.get().strip(),
                self.var_from.get().strip(), self.var_to.get().strip(),
                float(self.var_min.get() or 0), bw, 900.0, 28.0, mpb,
                "envelope" if self.var_spectrum.get() == "包络谱" else "raw",
                float(self.var_env_lo.get() or 1000), float(self.var_env_hi.get() or 4000))
        self._spec_mode = "envelope" if self.var_spectrum.get() == "包络谱" else "raw"
        self._spec_lo = float(self.var_env_lo.get() or 1000)
        self._spec_hi = float(self.var_env_hi.get() or 4000)
        self._busy = True
        self.btn_run.config(state="disabled")
        self._status("扫描/计算中…（窗口可拖动，计算在后台）")
        self.root.update_idletasks()

        def work():
            # 后台线程只算数据、不碰 Tk；结果放队列，由主线程轮询取出
            try:
                root_dir, point, d0, d1, vmin, bw, fmax, omax, mpb, spec, elo, ehi = args
                records = scan_records(root_dir, point, d0, d1, vmin)
                if not records:
                    self._q.put(("empty",))
                    return
                centers, matrix, used, total = stack_by_speed(
                    [(s, p) for s, _, p in records], bw=bw, min_per_bin=2,
                    domain=axis, fmax=fmax, omax=omax, max_per_bin=mpb,
                    spectrum=spec, env_lo=elo, env_hi=ehi)
                self._q.put(("ok", centers, matrix, used, total, axis))
            except Exception as e:
                self._q.put(("err", str(e)))

        threading.Thread(target=work, daemon=True).start()
        self.root.after(100, self._poll_queue)

    def _poll_queue(self):
        try:
            msg = self._q.get_nowait()
        except queue.Empty:
            if self._busy:
                self.root.after(100, self._poll_queue)
            return
        if msg[0] == "pre":
            self._status("预计算 %d/%d …" % (msg[1], msg[2]))
            self.root.after(200, self._poll_queue)
            return
        if msg[0] == "pre_done":
            self._busy = False
            self.btn_run.config(state="normal")
            self.btn_pre.config(state="normal")
            self._status("预计算完成：%d 条记录已入缓存" % msg[1])
            return
        if msg[0] == "empty":
            self._done(None, None, 0, 0, "order")
        elif msg[0] == "err":
            self._fail(msg[1])
        else:
            _, centers, matrix, used, total, axis = msg
            self._done(centers, matrix, used, total, axis)

    def precompute(self):
        """把当前测点的原始+包络阶次曲线都算一遍并写缓存（后台）。"""
        if self._busy:
            return
        records = scan_records(self.var_dir.get().strip(), self.var_point.get().strip(),
                               self.var_from.get().strip(), self.var_to.get().strip(),
                               float(self.var_min.get() or 0))
        if not records:
            self.messagebox.showinfo("提示", "没有匹配的记录")
            return
        self._busy = True
        self.btn_run.config(state="disabled")
        self.btn_pre.config(state="disabled")
        lo = float(self.var_env_lo.get() or 1000)
        hi = float(self.var_env_hi.get() or 4000)
        total = len(records)
        self._status("预计算 0/%d …" % total)

        def work():
            try:
                done = 0
                for rpm, p in records:
                    order_curve(p, 28.0, 0.02, kind="raw")
                    order_curve(p, 28.0, 0.02, kind="envelope", lo=lo, hi=hi)
                    done += 1
                    if done % 5 == 0:
                        self._q.put(("pre", done, total))
                self._q.put(("pre_done", total))
            except Exception as e:
                self._q.put(("err", str(e)))

        threading.Thread(target=work, daemon=True).start()
        self.root.after(200, self._poll_queue)

    def _fail(self, msg):
        self._busy = False
        self.btn_run.config(state="normal")
        self.messagebox.showerror("出错", msg)
        self._status("出错：" + msg)

    def _done(self, centers, matrix, used, total, axis):
        self._busy = False
        self.btn_run.config(state="normal")
        if centers is None:
            self.messagebox.showinfo("提示", "没有匹配的记录")
            self._status("没有匹配记录")
            return
        try:
            _spec = ("包络 %g–%gHz，" % (self._spec_lo, self._spec_hi)
                     if self._spec_mode == "envelope" else "")
            title = "%s（%s%s，%d/%d 条，%d 箱，中位数）" % (
                self.var_point.get() or "测点", _spec,
                "阶次" if axis == "order" else "频率", used, total, len(centers))
            fixed = detect_fixed(centers, matrix, axis,
                                 fmax=float(self.var_fmax.get() or 900))                 if self.var_fixed_on.get() else []
            fig = render(centers, matrix, self.auto_orders, axis, title,
                         fmax=float(self.var_fmax.get() or 900),
                         omax=float(self.var_omax.get() or 28), fixed=fixed)
            from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
            try:
                self.placeholder.place_forget()
            except Exception:
                pass
            if self._canvas is not None:
                self._canvas.get_tk_widget().destroy()
            self._canvas = FigureCanvasTkAgg(fig, master=self.body)
            self._canvas.draw()
            _w = self._canvas.get_tk_widget()
            try:
                _w.configure(bg="#e2e7ed", highlightthickness=0)
            except Exception:
                pass
            _w.grid(row=0, column=0, sticky="nsew")
            _w.bind("<Configure>", self._on_canvas_resize, add="+")
            self._status("记录 %d 条，可用 %d 条，分箱 %d 个" % (
                total, used, len(centers)))
        except Exception as e:
            self._fail(str(e))


def main():
    ap = argparse.ArgumentParser(description="转速堆叠谱 / 阶次堆叠图（独立小工具）")
    ap.add_argument("--dir", default=r"D:\数据\府谷\2026\06")
    ap.add_argument("--point", default="121#_齿轮箱_中部径向")
    ap.add_argument("--date-from", default="")
    ap.add_argument("--date-to", default="")
    ap.add_argument("--min-speed", type=float, default=1500.0)
    ap.add_argument("--bin", type=float, default=20.0)
    ap.add_argument("--min-per-bin", type=int, default=2)
    ap.add_argument("--axis", choices=("freq", "order"), default="order")
    ap.add_argument("--fmax", type=float, default=900.0)
    ap.add_argument("--omax", type=float, default=28.0)
    ap.add_argument("--dorder", type=float, default=0.02)
    ap.add_argument("--orders", default="auto",
                    help="auto=按机型库自动生成；也可写 1,2,23")
    ap.add_argument("--precompute", action="store_true",
                    help="只预计算缓存，不出图")
    ap.add_argument("--fixed", default="auto", help="固定频率：auto / none / 100,200")
    ap.add_argument("--out", default="")
    ap.add_argument("--max-records", type=int, default=3000)
    ap.add_argument("--max-per-bin", type=int, default=10,
                    help="每个转速箱最多取几条记录（0=不限）")
    ap.add_argument("--spectrum", choices=("raw", "envelope"), default="raw",
                    help="raw=原始幅值谱；envelope=带通+Hilbert 包络谱")
    ap.add_argument("--env-lo", type=float, default=1000.0)
    ap.add_argument("--env-hi", type=float, default=4000.0)
    ap.add_argument("--gui", action="store_true", help="带参打开图形界面（默认参数预填）")
    ap.add_argument("--parent-pid", type=int, default=0,
                    help="父进程 PID：父进程退出时本窗口自动关闭")
    args = ap.parse_args()
    if args.gui:
        _set_app_id()
        import tkinter as tk
        root = tk.Tk()
        StackWindow(root, init=vars(args))
        root.mainloop()
        return 0
    if len(sys.argv) > 1:
        return run_cli(args)
    _set_app_id()
    import tkinter as tk
    root = tk.Tk()
    StackWindow(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
