# -*- coding: utf-8 -*-
"""量级异常（传感器饱和/触顶）的数据拒收，正常数据照收。"""
import os
import shutil
import importlib.util

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("vib", os.path.join(ROOT, "振动分析.py"))
vib = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vib)

RESULTS = []


def check(ok, msg):
    RESULTS.append(bool(ok))
    print(("  PASS  " if ok else "  FAIL  ") + msg)


d = os.path.join(ROOT, ".tmptest", "abn")
os.makedirs(d, exist_ok=True)
fs, n = 40000.0, 131172


def write(name, x):
    p = os.path.join(d, name)
    with open(p, "w", encoding="utf-8") as f:
        for v in x:
            f.write("%.6f\n" % v)
    return p


t = np.arange(n) / fs
# 正常：0.5 m/s² 正弦 + 少量噪声
good = write("中节能五峰北风垭风电场_4_主轴轴承_40000Hz_3.28s_加速度值_1200_20260601010101.csv",
             0.5 * np.sin(2 * np.pi * 30 * t) + 0.02 * np.random.RandomState(0).randn(n))
# 异常：1% 采样顶到 ±245（饱和），其余正常
x = 0.5 * np.sin(2 * np.pi * 30 * t)
idx = np.random.RandomState(1).randint(0, n, size=n // 100)
x[idx] = np.sign(x[idx] + 1e-9) * 245.0
x[idx[: len(idx) // 2]] *= -1
bad = write("中节能五峰北风垭风电场_4_发电机前轴_40000Hz_3.28s_加速度值_1200_20260601010101.csv", x)

print("[正常数据]")
out, err = vib.process_one_csv(good)
check(out is not None, f"正常数据入库（err={err}）")

print("[饱和数据]")
out2, err2 = vib.process_one_csv(bad)
check(out2 is None, "饱和数据被拒收")
check(err2 and "量级异常" in err2, f"原因写明量级异常（{err2}）")

print("[阈值]")
check(vib.ABNORMAL_PEAK == 200.0 and vib.ABNORMAL_RMS == 20.0, "阈值 200 / 20")

print("[清空缓存只删异常]")
where, args = vib.VibGUI._cache_where("", "", "", "", True)
check("peak >= ?" in where and "rms >= ?" in where, f"WHERE 带异常条件（{where}）")
check(args[:2] == [200.0, 20.0], f"参数为阈值（{args}）")

shutil.rmtree(d, ignore_errors=True)

print()
failed = [x for x in RESULTS if not x]
print(f"共 {len(RESULTS)} 项断言，失败 {len(failed)} 项")
print("RESULT:", "ALL PASS" if not failed else "FAIL")
