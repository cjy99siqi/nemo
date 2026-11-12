# -*- coding: utf-8 -*-
"""read_signal_csv：单列/多列/带表头/时间轴/非数值 的容错（沙箱内可用）。"""
import os
import importlib.util


import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("vib", os.path.join(ROOT, "振动分析.py"))
vib = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vib)

RESULTS = []


def check(ok, msg):
    RESULTS.append((bool(ok), msg))
    print(("  PASS  " if ok else "  FAIL  ") + msg)


def _tmpdir():
    # 沙箱里 tempfile.mkdtemp 的目录可能不可写，统一放到工作区下的 .tmptest
    d = os.path.join(ROOT, ".tmptest", "csvread_%d" % os.getpid())
    os.makedirs(d, exist_ok=True)
    return d


d = _tmpdir()
rs = np.random.RandomState(0)
N = 5000
acc = rs.randn(N) * 0.5

p1 = os.path.join(d, "single.csv")
open(p1, "w").write("\n".join("%.6f" % x for x in acc))

p2 = os.path.join(d, "time_acc.csv")
open(p2, "w").write("time,acc\n" + "\n".join(
    "%.6f,%.6f" % (i / 25600.0, x) for i, x in enumerate(acc)))

p3 = os.path.join(d, "space2.csv")
open(p3, "w").write("\n".join(
    "%.6f %.6f" % (i / 25600.0, x) for i, x in enumerate(acc)))

p4 = os.path.join(d, "header.csv")
open(p4, "w").write("acc\n" + "\n".join("%.6f" % x for x in acc))

p5 = os.path.join(d, "text.csv")
open(p5, "w").write("acc\n" + "\n".join("abc" for _ in range(100)))

p6 = os.path.join(d, "acc_time.csv")
open(p6, "w").write("acc,time\n" + "\n".join(
    "%.6f,%.6f" % (x, i / 25600.0) for i, x in enumerate(acc)))

print("[单列 / 带表头]")
v, m = vib.read_signal_csv(p1)
check(len(v) == N and not m["multi"], f"单列 {len(v)} 点")
v, m = vib.read_signal_csv(p4)
check(len(v) == N and not m["multi"], f"带表头单列 {len(v)} 点")

print("\n[多列]")
v, m = vib.read_signal_csv(p2)
check(len(v) == N and m["multi"], f"逗号两列 {len(v)} 点")
check(m.get("col") == 1, f"时间在前时取幅值列（实际 col={m.get('col')}）")
check(abs(float(np.std(v)) - float(np.std(acc))) < 0.05,
      f"取到的是幅值列（std={np.std(v):.3f} vs {np.std(acc):.3f}）")
v, m = vib.read_signal_csv(p3)
check(len(v) == N and m.get("col") == 1, f"空格两列取幅值列（实际 col={m.get('col')}）")
v, m = vib.read_signal_csv(p6)
check(len(v) == N and m.get("col") == 0, f"幅值在前时取第 1 列（实际 col={m.get('col')}）")

print("\n[非数值]")
v, m = vib.read_signal_csv(p5)
check(len(v) == 0, f"纯文本返回 0 点（实际 {len(v)}）")

print("\n[数据体检]")
_w = vib.data_health_warnings(131072, 25600, "发电机_前轴承径向")
check(_w == [], f"正常数据不出提示（{len(_w)} 条）")
_w = vib.data_health_warnings(5000, 25600, "发电机_前轴承径向")
check(any("采样点数不足" in x for x in _w), "点数/时长不足 → 提示")
_w = vib.data_health_warnings(131072, 2500, "发电机_前轴承径向")
check(any("采样率偏低" in x for x in _w), "fs/2.56 低于分析频带上限 → 提示")
_w = vib.data_health_warnings(131072, 25600, "齿轮箱_高速轴径向",
                              {"multi": True, "ncols": 2, "col": 1})
check(any("多列" in x for x in _w), "多列 CSV → 提示取了哪一列")

print()
failed = [m for ok, m in RESULTS if not ok]
print(f"共 {len(RESULTS)} 项断言，失败 {len(failed)} 项")
try:
    import shutil; shutil.rmtree(d, ignore_errors=True)
except Exception:
    pass
print("RESULT:", "ALL PASS" if not failed else "FAIL")
