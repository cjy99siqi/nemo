# -*- coding: utf-8 -*-
"""时域「时间游标」：点两次定 A/B、方向键在峰间跳、Δt/1÷Δt 标注。"""
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


class Ev:
    def __init__(self, x=None, key=None):
        self.xdata = x
        self.key = key
        self.inaxes = object()
        self.button = 1


class Stub:
    current_plot = "time"
    fs = 25600.0
    refine_range = None
    _freq_confirmed = False
    _single_start_t = None
    marks_hidden = False
    _manual_marks_time = []
    single_line_on = False
    mark_time_on = False
    annotate_mode = False
    axis_locked = True          # 默认锁轴；时间游标应不受影响
    sig = np.zeros(25600)
    BW_COLOR = "#ffe082"
    RING_MS = 5
    RING_MEW = 1.2
    btn_tcursor = None
    _tc_peaks = None

    # ---- 交互相关 ----
    _redraw_current_plot = lambda self: None
    _wf3d_active = lambda self: False
    _set_locked = lambda self, on, redraw=False: setattr(self, "axis_locked", bool(on))
    _refine_saved = {}
    _xmax_override = None
    _harmonics_text = None
    _sidebands_text = None
    _bandwidth_text = None
    _bandwidth_regions = []
    rs = None
    _push_undo = lambda self: None
    _set_on = lambda self, *a, **k: None
    _period_source = SW._period_source
    _fund_freq = lambda self: 0.0
    _toggle_time_cursor = SW._toggle_time_cursor
    _finish_time_cursor = SW._finish_time_cursor
    _on_click_annotate = SW._on_click_annotate
    _on_key_press = SW._on_key_press

    def _get_sig(self):
        t = np.arange(25600) / 25600.0
        return 0.6 * np.sin(2 * np.pi * 28.0 * t)

    def _decimate_xy(self, x, y, view=None):
        return x, y

    def _fresh_ax(self, title):
        self.fig = Figure(figsize=(6, 3))
        FigureCanvasAgg(self.fig)
        self.ax = self.fig.add_subplot(111)
        return self.ax

    def _post_draw(self):
        pass

    plot_time = SW.plot_time


print("[开关]")
s = Stub()
s._toggle_time_cursor()
check(s.tcursor_on and s._tc_t == [], "打开后处于取点状态、无游标")
s._on_click_annotate(Ev(x=0.100))
check(len(s._tc_t) == 1 and abs(s._tc_t[0] - 0.100) < 1e-9, f"第一次点 → A（{s._tc_t}）")
s._on_click_annotate(Ev(x=0.135))
check(len(s._tc_t) == 2 and abs(s._tc_t[1] - 0.135) < 1e-9, f"第二次点 → B（{s._tc_t}）")
check(not s.tcursor_on, "第二条定好后自动退出取点态")
s._on_click_annotate(Ev(x=0.132))
check(abs(s._tc_t[1] - 0.135) < 1e-9, f"退出后鼠标点击不再改游标（{s._tc_t}）")
s._toggle_time_cursor()
check(s.tcursor_on and s._tc_t == [], "再次点「时间游标」→ 清空重来")

print("[键盘移动：普通方向微调，Shift+方向找峰]")
s = Stub()
s._tc_peaks = np.array([0.080, 0.100, 0.135, 0.170, 0.205])
s._toggle_time_cursor()
s._on_click_annotate(Ev(x=0.100))
s._on_click_annotate(Ev(x=0.135))
_dt = 1.0 / 25600.0          # 一个采样点
s._on_key_press(Ev(key="right"))
check(abs(s._tc_t[1] - (0.135 + _dt)) < 1e-9, f"普通 → 只走 1 个采样点（{s._tc_t[1]:.4f}）")
s._on_key_press(Ev(key="left"))
check(abs(s._tc_t[1] - 0.135) < 1e-9, f"普通 ← 只走 1 个采样点（{s._tc_t[1]:.4f}）")
s._on_key_press(Ev(key="shift+right"))
check(abs(s._tc_t[1] - 0.205) < 1e-9,
      f"Shift+→ 找峰、跳 10 个（钳到末尾 0.205，实际 {s._tc_t[1]:.3f}）")
s._on_key_press(Ev(key="shift+left"))
check(abs(s._tc_t[1] - 0.080) < 1e-9,
      f"Shift+← 找峰、跳 10 个（钳到开头 0.080，实际 {s._tc_t[1]:.3f}）")
s._on_key_press(Ev(key="tab"))
s._on_key_press(Ev(key="right"))
check(abs(s._tc_t[0] - (0.100 + _dt)) < 1e-9, f"Tab 切到 A 后也是 1 个采样点（{s._tc_t[0]:.4f}）")
s._on_key_press(Ev(key="escape"))
check(s._tc_t == [], "Esc 清除游标")

print("[没有峰数据：1 个采样点 / 10ms]")
s = Stub()
s._tc_peaks = None
s._toggle_time_cursor()
s._on_click_annotate(Ev(x=0.100))
s._on_click_annotate(Ev(x=0.135))
s._on_key_press(Ev(key="right"))
check(abs(s._tc_t[1] - (0.135 + _dt)) < 1e-9, f"方向键 +1 个采样点（{s._tc_t[1]:.5f}）")
s._on_key_press(Ev(key="shift+right"))
check(abs(s._tc_t[1] - (0.135 + _dt + 0.01)) < 1e-9, f"Shift+方向 +10ms（{s._tc_t[1]:.5f}）")

print("[绘制]")
s = Stub()
# 模拟“A/B 已定完、取点态已自动退出”的状态：游标仍必须画出来
s.tcursor_on = False
s._tc_t = [0.100, 0.135]
SW.plot_time(s)
texts = [t.get_text() for t in s.ax.texts]
check(any("A 0.100s" in x for x in texts), f"A 标签（{texts}）")
check(any("B 0.135s" in x for x in texts), "B 标签")
check(not any("Δt " in x for x in texts), f"不再单独显示左上角 Δt 框（{texts}）")
check(getattr(s, "_tc_peaks", None) is not None and len(s._tc_peaks) >= 2,
      "绘制时缓存了波形峰（供方向键吸附）")
# 1T…5T：与自相关一致的填充块
spans = [p for p in s.ax.patches]
check(len(spans) >= 5, f"画出 1T…5T 共 {len(spans)} 个填充块")
check(any("1T  开始 0.100s" in x for x in texts), "右上角 1T 汇总（开始）")
check(any("间隔 0.0350s" in x for x in texts), "右上角 1T 汇总（间隔）")
check(any("频率 28.57Hz" in x for x in texts), "右上角 1T 汇总（频率）")

circles = [ln for ln in s.ax.lines if ln.get_marker() == "o"]
check(len(circles) >= 2, f"A/B 落点画了红圈（{len(circles)} 个）")
# 周期起点（A）本身也要有一个空心红圈
_xs = [float(ln.get_xdata()[0]) for ln in circles]
check(any(abs(x - 0.100) < 1e-6 for x in _xs), f"起点 A 也有红圈（{sorted(round(x, 3) for x in _xs)[:4]}）")

print("[还原原图]")
s2 = Stub()
s2.tcursor_on = True
s2._tc_t = [0.100, 0.135]
SW._reset_view(s2)
check(s2._tc_t == [], "还原原图会清掉时间游标（不再像没生效）")

print("[旧的鼠标标频已移除]")
check(not hasattr(SW, "_onclick_single_line"), "_onclick_single_line 已删除")
check(not hasattr(SW, "_popup_freq"), "_popup_freq 已删除")
check(not hasattr(SW, "_on_press_period"), "_on_press_period 已删除")

print()
failed = [x for x in RESULTS if not x]
print(f"共 {len(RESULTS)} 项断言，失败 {len(failed)} 项")
print("RESULT:", "ALL PASS" if not failed else "FAIL")
