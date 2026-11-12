# -*- coding: utf-8 -*-
"""自相关标频：先锚到谱峰定支，再用多周期细化；不能把 164.1 标成 1/τ 的 160。"""
import os
import importlib.util

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("vib", os.path.join(ROOT, "振动分析.py"))
vib = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vib)
SW = vib.SpectrumWindow

RESULTS = []


def check(ok, msg):
    RESULTS.append(bool(ok))
    print(("  PASS  " if ok else "  FAIL  ") + msg)


class S:
    fs = 25600.0
    sig = None
    _signal_fft_peaks = SW._signal_fft_peaks
    _autocorr_label_freq = SW._autocorr_label_freq


def autocorr(x, fs):
    n = len(x)
    m = 1 << int(np.ceil(np.log2(2 * n)))
    x = x - x.mean()
    F = np.fft.rfft(x, m)
    ac = np.fft.irfft(F * np.conj(F), m)[:n]
    ac = ac / ac[0]
    return np.arange(n) / fs, ac


fs = 25600.0
t = np.arange(int(fs * 5.12)) / fs
rng = np.random.RandomState(0)
# 164.1Hz 最强 + 156.9Hz 次强 + 少量噪声：真实数据里自相关在 6.25ms 处也会起峰
x = (1.0 * np.sin(2 * np.pi * 164.13 * t) + 0.62 * np.sin(2 * np.pi * 156.91 * t)
     + 0.02 * rng.randn(len(t)))
tau, ac = autocorr(x, fs)

s = S(); s.sig = x
ff, fa = s._signal_fft_peaks()
top = ff[np.argsort(fa)[::-1][:3]]
check(any(abs(f - 164.13) < 0.5 for f in top), f"谱峰里有 164.1（{np.round(top,1)}）")

print("[自相关峰 → 标注频率]")
f_625 = s._autocorr_label_freq(0.00625, tau, ac)
check(abs(f_625 - 164.13) < 0.6, f"τ=6.25ms（裸 1/τ=160Hz）→ 标成 {f_625:.2f}Hz")
check(abs(f_625 - 160.0) > 2.0, "不再标成 160Hz")

f_607 = s._autocorr_label_freq(0.00607, tau, ac)
check(abs(f_607 - 164.13) < 0.6, f"τ=6.07ms → {f_607:.2f}Hz（同一支）")

f_656 = s._autocorr_label_freq(0.00656, tau, ac)
check(abs(f_656 - 156.91) < 0.6, f"τ=6.56ms（1/τ=152.4Hz）→ 锚到次强峰 {f_656:.2f}Hz")

print("[纯净信号：多周期细化]")
t2 = np.arange(int(fs * 5.0)) / fs
x2 = np.sin(2 * np.pi * 50.0 * t2) + 0.01 * rng.randn(len(t2))
tau2, ac2 = autocorr(x2, fs)
s2 = S(); s2.sig = x2
f50 = s2._autocorr_label_freq(0.02, tau2, ac2)
check(abs(f50 - 50.0) < 0.1, f"50Hz → {f50:.2f}Hz（多周期细化后误差 <0.1Hz）")

print("[无对应谱峰：保留 1/τ]")
f_odd = s2._autocorr_label_freq(0.0123, tau2, ac2)   # 81.3Hz，50Hz 的谐波外
check(abs(f_odd - 1 / 0.0123) < 3.0, f"找不到谱峰时仍用 1/τ（{f_odd:.1f}Hz）")

print()
failed = [x for x in RESULTS if not x]
print(f"共 {len(RESULTS)} 项断言，失败 {len(failed)} 项")
print("RESULT:", "ALL PASS" if not failed else "FAIL")
