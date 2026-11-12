# -*- coding: utf-8 -*-
"""“缩小”逐级生效：每次在细化基础上放大 1.5 倍，不是一下跳回全图。"""
import os
import importlib.util

import numpy as np
import matplotlib
matplotlib.use("Agg")
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("vib", os.path.join(ROOT, "振动分析.py"))
vib = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vib)
SW = vib.SpectrumWindow

RESULTS = []


def check(ok, msg):
    RESULTS.append(bool(ok))
    print(("  PASS  " if ok else "  FAIL  ") + msg)


class Z:
    current_plot = "fft"
    sig = None
    fs = 25600.0
    axis_locked = False
    refine_range = (2000.0, 2500.0)
    _refine_saved = {}
    _xmax_override = None
    _cur_f = np.arange(0.0, 5001.0, 1.0)
    _wf3d_active = lambda self: False
    _full_xlim = None
    _zoom_hi = None
    _zoom_bounds = SW._zoom_bounds
    _set_locked = lambda self, on, redraw=False: None
    _redraw_current_plot = lambda self: None
    _set_view_range = SW._set_view_range
    _zoom_out = SW._zoom_out

    def __init__(self):
        self.fig = Figure(figsize=(6, 3))
        FigureCanvasAgg(self.fig)
        self.ax = self.fig.add_subplot(111)
        self.ax.set_xlim(*self.refine_range)


print("[逐级缩小]")
z = Z()
SW._zoom_out(z)
check(z.refine_range is not None, "第一次缩小仍保留细化（不直接跳回全图）")
w1 = z.refine_range[1] - z.refine_range[0]
check(w1 > 500 * 1.35, f"宽度按 1.5 倍扩大（500 → {w1:.0f}）")

z.ax.set_xlim(*z.refine_range)
SW._zoom_out(z)
w2 = z.refine_range[1] - z.refine_range[0]
check(z.refine_range is not None and w2 > w1 * 1.3,
      f"第二次继续扩大（{w1:.0f} → {w2:.0f}）")

print("\n[逐步到底才回全图]")
z = Z()
steps = 0
while z.refine_range is not None and steps < 20:
    if steps:
        z.ax.set_xlim(*z.refine_range)
    SW._zoom_out(z)
    steps += 1
check(z.refine_range is None, f"{steps} 步后才回到全图（不是 1 步）")
check(steps >= 2, f"步数 ≥ 2（实际 {steps}）")

print("\n[已全图再点无效]")
z = Z()
z.refine_range = None
z.ax.set_xlim(0.0, 5000.0)
SW._zoom_out(z)
check(z.refine_range is None and abs(z.ax.get_xlim()[1] - 5000) < 1e-6, "全图状态下点击不再变化")

print("\n[缩到完整视图为止，不越界到 Nyquist]")
z = Z()
z._cur_f = np.arange(0.0, 10001.0, 1.0)     # 分析上限 fs/2.56
z._full_xlim = ("fft", (0.0, 750.0))        # 带通默认只显示 0~750
z.refine_range = (2000.0, 2500.0)
z.ax.set_xlim(2000.0, 2500.0)
for _ in range(14):
    SW._zoom_out(z)
    if z.refine_range is None:
        break
    _r0, _r1 = z.refine_range
    _pad = (_r1 - _r0) * 0.05
    z.ax.set_xlim(max(0.0, _r0 - _pad), _r1 + _pad)
check(z.refine_range is None, "多步后回到完整视图")
check(z.ax.get_xlim()[1] <= 10000.5, f"右边界不超过 10000（实际 {z.ax.get_xlim()[1]:.0f}）")


print()
print("[自相关 5 周期视图下缩小仍可用]")
z = Z()
z.current_plot = "time"
z.sig = np.zeros(5 * 25600)
z._full_xlim = ("time", (0.0, 0.2737))      # 5 周期视图被 _post_draw 误记成 full 的情形
z._zoom_full_override = (0.0, 4.9999)       # 联动时记下的整段记录
z.refine_range = None
z.ax.set_xlim(0.0, 0.2737)
check(abs(SW._zoom_bounds(z)[1] - 4.9999) < 1e-3, "完整视图取整段记录，不是 5 周期窗口")
SW._zoom_out(z)
check(z.refine_range is not None and z.refine_range[1] > 0.30,
      f"点缩小后视图扩大（{z.refine_range[1]:.3f}s）")

z2 = Z()
z2.current_plot = "time"
z2.sig = np.zeros(5 * 25600)
z2._zoom_full_override = None
z2.refine_range = None
z2._full_xlim = ("time", (0.0, 4.9999))
z2.ax.set_xlim(0.0, 4.9999)
SW._zoom_out(z2)
check(z2.refine_range is None, "没有 override 时，全图状态点击不再变化")


print()
print("[频域谱图：缩小可扩展到最高分析频率]")
z = Z()
z.current_plot = "fft"
z._cur_f = np.arange(0.0, 10001.0, 1.0)
z._full_xlim = ("fft", (0.0, 750.0))
z.refine_range = None
z._zoom_hi = None
z.ax.set_xlim(0.0, 750.0)
check(abs(SW._zoom_bounds(z)[1] - 10000.0) < 1e-6,
      f"完整视图按数据上限（fs/2.56），不是带通 750（{SW._zoom_bounds(z)}）")
for _ in range(12):
    SW._zoom_out(z)
    if z.refine_range is not None:
        _r0, _r1 = z.refine_range
        _pad = (_r1 - _r0) * 0.05
        z.ax.set_xlim(max(0.0, _r0 - _pad), _r1 + _pad)
    elif z._zoom_hi:
        z.ax.set_xlim(0.0, z._zoom_hi)
check(z._zoom_hi is not None and abs(z._zoom_hi - 10000.0) < 1e-6,
      f"最终扩到最高分析频率（{z._zoom_hi}）")
check(z.refine_range is None, "扩到上限后清掉细化状态")

print()
failed = [x for x in RESULTS if not x]
print(f"共 {len(RESULTS)} 项断言，失败 {len(failed)} 项")
print("RESULT:", "ALL PASS" if not failed else "FAIL")
