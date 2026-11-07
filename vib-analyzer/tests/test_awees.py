# -*- coding: utf-8 -*-
"""AWEES 仿真验证（论文 §3.1：外圈 50 Hz + 内圈 80 Hz，-18 dB）

只验证“能不能把两个故障的周期峰从强噪声里提出来”，
不验证论文的耗时数字（那取决于机器和实现细节）。
"""
import sys
import time
import pathlib

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import awees as A  # noqa: E402

FS = 20000
results = []


def check(cond, msg):
    results.append((bool(cond), msg))
    print(("  PASS  " if cond else "  FAIL  ") + msg)


def peak_ratio(spec, alpha, target, tol=3.0):
    lo = np.searchsorted(alpha, target - tol)
    hi = np.searchsorted(alpha, target + tol)
    local = spec[lo:hi]
    if local.size == 0:
        return 0.0, float("nan")
    base = np.median(spec[:max(len(spec), 1)]) + 1e-12
    i = int(np.argmax(local))
    return float(local[i] / base), float(alpha[lo + i])


print("[仿真信号：两故障 + 谐波干扰 + 白噪声]")
x = A.simulate(fs=FS)
check(len(x) == 20000, f"采样点数 {len(x)}")

t0 = time.perf_counter()
modes, alpha, scoh, efdsnr = A.analyze(x, FS)
elapsed = time.perf_counter() - t0
print(f"  模式数 {len(modes)}，耗时 {elapsed:.2f} s")

check(len(modes) >= 1, f"至少输出一个模式（实际 {len(modes)}）")
check(scoh.shape[0] > 0 and scoh.shape[1] > 0, f"谱相干形状 {scoh.shape}")
check(elapsed < 10.0, f"20k 点耗时 {elapsed:.2f} s < 10 s")

if modes:
    combined = np.sum([m["spectrum"] for m in modes], axis=0)
    r50, f50 = peak_ratio(combined, alpha, 50.0)
    r80, f80 = peak_ratio(combined, alpha, 80.0)
    print(f"  50Hz 峰 {r50:.2f}x @ {f50:.1f}Hz | 80Hz 峰 {r80:.2f}x @ {f80:.1f}Hz")
    check(abs(f50 - 50.0) <= 3.0, f"50 Hz 附近有峰（{f50:.1f} Hz）")
    check(abs(f80 - 80.0) <= 3.0, f"80 Hz 附近有峰（{f80:.1f} Hz）")
    check(r50 > 1.5, f"50 Hz 峰高于中位 1.5 倍（{r50:.2f}x）")
    check(r80 > 1.5, f"80 Hz 峰高于中位 1.5 倍（{r80:.2f}x）")

    for m in modes:
        check(m["fault_hz"] > 0, f"模式故障频率估计 {m['fault_hz']:.1f} Hz > 0")
        check(np.isfinite(m["spectrum"]).all(), "模式谱无 NaN/Inf")

print()
failed = [m for ok, m in results if not ok]
print(f"共 {len(results)} 项断言，失败 {len(failed)} 项")
for m in failed:
    print("  FAILED:", m)
print("RESULT:", "ALL PASS" if not failed else "FAILED")
sys.exit(0 if not failed else 1)
