# -*- coding: utf-8 -*-
"""转速堆叠谱小工具：分箱中位数、阶次解析、筛选逻辑（不读真实数据）"""
import importlib.util
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
spec = importlib.util.spec_from_file_location(
    "stacktool", os.path.join(APP, "tools", "转速堆叠谱.py"))
T = importlib.util.module_from_spec(spec)
spec.loader.exec_module(T)

RESULTS = []


def check(ok, msg):
    RESULTS.append(bool(ok))
    print(("  PASS  " if ok else "  FAIL  ") + msg)


print("[阶次解析]")
check(T.parse_orders("1, 2, 23") == [1.0, 2.0, 23.0], "1,2,23 正常解析")
check(T.parse_orders(" 3.187，6.374 ") == [3.187, 6.374], "中文逗号/空格/小数")
check(T.parse_orders("x,,-1,0") == [], "非法值全部丢弃")
check(T.parse_orders("") == [], "空串返回空列表")

print("[分箱 + 中位数]")
FMAX, DF = 900.0, 2.0
nb = int(FMAX / DF)
freq = np.arange(nb) * DF + DF / 2.0


def curve(peak_hz, amp=1.0):
    a = np.zeros(nb)
    i = int(np.argmin(np.abs(freq - peak_hz)))
    a[max(0, i - 1):i + 2] = amp
    return a


curves = []
for rpm in (1520, 1525, 1530):
    curves.append((rpm, curve(4 * rpm / 60.0)))      # 4X≈101Hz
for rpm in (1740, 1745, 1750):
    curves.append((rpm, curve(4 * rpm / 60.0)))      # 4X≈116Hz
centers, matrix, used = T.stack_curves(curves, bw=20.0, min_per_bin=2)
check(len(centers) >= 2, f"两个转速段各成一个箱（{list(centers)}）")
check(matrix.shape[0] == nb, "频率轴长度不变")
i1 = int(np.argmin(np.abs(centers - 1520)))
i2 = int(np.argmin(np.abs(centers - 1750)))
peak1 = freq[int(np.argmax(matrix[:, i1]))]
peak2 = freq[int(np.argmax(matrix[:, i2]))]
check(abs(peak1 - 4 * 1525 / 60.0) < 3, f"1520rpm 箱峰值 ≈4X（{peak1:.0f}Hz）")
check(abs(peak2 - 4 * 1745 / 60.0) < 3, f"1750rpm 箱峰值 ≈4X（{peak2:.0f}Hz）")
check(used == 6, f"用到的记录数正确（{used}）")

print("[样本不足的箱丢弃]")
c2 = [(1000, curve(100.0)), (1010, curve(100.0)), (2000, curve(200.0))]
centers2, matrix2, used2 = T.stack_curves(c2, bw=20.0, min_per_bin=2)
check(len(centers2) == 1 and abs(centers2[0] - 1010) < 1e-6,
      f"2000rpm 箱只有 1 条被丢弃（{list(centers2)}）")

print("[空输入]")
c3, m3, u3 = T.stack_curves([], bw=20.0)
check(c3.size == 0 and m3.size == 0 and u3 == 0, "空列表安全返回")


print("[阶次重采样]")
fr = 25.0
f = np.arange(0.0, 1200.0, 0.5)
amp = np.zeros_like(f)
for hz in (3.187 * fr, 100.0):
    i = int(np.argmin(np.abs(f - hz)))
    amp[i] = 1.0
orders, a_o = T.resample_to_order(f, amp, fr, 10.0, 0.01)
check(len(orders) == 1000, f"阶次轴点数正确（{len(orders)}）")
peak = float(orders[int(np.argmax(a_o))])
check(abs(peak - 3.187) < 0.03, f"BPFO 3.187X 重采样到 {peak:.2f}X")
amp2 = amp.copy(); amp2[:] = 0
i = int(np.argmin(np.abs(f - 100.0))); amp2[i] = 1.0
o2, a2 = T.resample_to_order(f, amp2, fr, 10.0, 0.01)
check(abs(float(o2[int(np.argmax(a2))]) - 4.0) < 0.03, "固定 100Hz 在阶次图上落到 4X（25Hz 时）")
o3, a3 = T.resample_to_order(f, amp2, 28.0, 10.0, 0.01)
check(abs(float(o3[int(np.argmax(a3))]) - 100.0 / 28.0) < 0.03,
      "同一固定 100Hz 换转速后阶次位置变化（双曲线）")


print("[固定频率识别]")
df = 2.0
freqs = np.arange(500) * df + df / 2.0
M = np.zeros((500, 3))
row = int(np.argmin(np.abs(freqs - 100.0)))
M[row - 1:row + 2, :] = 1.0
det = T.detect_fixed(np.array([1500.0, 1600.0, 1700.0]), M, "freq", df=df, fmax=1000)
check(any(abs(x - 100.0) < 4 for x in det), f"频率域识别出 100Hz（{det}）")

dorder = 0.01
orders = np.arange(1000) * dorder + dorder / 2.0
Mo = np.zeros((1000, 3))
for i, rpm in enumerate((1500.0, 1600.0, 1700.0)):
    o = 100.0 / (rpm / 60.0)
    j = int(np.argmin(np.abs(orders - o)))
    Mo[j - 2:j + 3, i] = 1.0
deto = T.detect_fixed(np.array([1500.0, 1600.0, 1700.0]), Mo, "order",
                      dorder=dorder, fmax=1000)
check(any(abs(x - 100.0) < 6 for x in deto), f"阶次域识别出固定 100Hz（{[round(x) for x in deto]}）")

Md = np.zeros((500, 3))
for i, rpm in enumerate((1500.0, 1600.0, 1700.0)):
    r = int(np.argmin(np.abs(freqs - 4 * rpm / 60.0)))
    Md[r - 1:r + 2, i] = 1.0
detd = T.detect_fixed(np.array([1500.0, 1600.0, 1700.0]), Md, "freq", df=df, fmax=1000)
check(not any(abs(x - 4 * 1600 / 60.0) < 4 for x in detd), "纯斜线（4X）不会被当成固定频率")


print("[包络谱]")
fs = 25600.0
t = np.arange(0, 2.0, 1.0 / fs)
sig = (1.0 + 0.6 * np.cos(2 * np.pi * 25.0 * t)) * np.cos(2 * np.pi * 2000.0 * t)
f_env, a_env = T.envelope_from_signal(sig, fs, 1000.0, 4000.0)
m = (f_env > 5) & (f_env < 200)
peak = float(f_env[m][int(np.argmax(a_env[m]))])
check(abs(peak - 25.0) < 1.0, f"AM 信号解调出 25Hz 调制（{peak:.1f}Hz）")
o_env, a_o = T.resample_to_order(f_env, a_env, 25.0, 10.0, 0.01)
check(abs(float(o_env[int(np.argmax(a_o))]) - 1.0) < 0.05,
      "25Hz 调制在 1500rpm 下落到 1X 附近")


print("[自动参考阶次]")
o_gen = T.auto_orders(r"D:\数据\府谷6", "113#_发电机_后轴承径向")
check(any(abs(x - 3.187) < 0.01 for x in o_gen), f"发电机后轴承带 BPFO 3.187X（{[round(x,2) for x in o_gen]}）")
o_hs = T.auto_orders(r"D:\数据\府谷6", "齿轮箱_高速轴径向")
check(any(abs(x - 7.667) < 0.01 for x in o_hs), f"齿轮箱高速轴带 NU234 BPFO 7.667X（{[round(x,2) for x in o_hs]}）")
o_bad = T.auto_orders(r"D:\数据\府谷6", "不存在的测点")
check(o_bad[:2] == [1.0, 2.0] and all(abs(x - 3.187) > 0.01 for x in o_bad),
      f"匹配不到测点时只保留 1X/2X + 机器啮合、无轴承阶次（{[round(x,2) for x in o_bad]}）")

print()
failed = [x for x in RESULTS if not x]
print("共 %d 项断言，失败 %d 项" % (len(RESULTS), len(failed)))
print("RESULT: " + ("ALL PASS" if not failed else "FAIL"))
sys.exit(0 if not failed else 1)
