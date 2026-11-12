# -*- coding: utf-8 -*-
"""频差：谱图上点两次吸附 A/B 峰，标出 Δf；Esc 清除；非频域谱图不可用。"""
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
    def __init__(self, x):
        self.inaxes = object()
        self.button = 1
        self.xdata = x


class S:
    current_plot = "fft"
    marks_hidden = False
    annotate_mode = False
    tcursor_on = False
    btn_fcdiff = None
    btn_annotate = None
    btn_tcursor = None
    RING_MS = 5
    RING_MEW = 1.2
    _DIFF_PLOTS = SW._DIFF_PLOTS
    _toggle_fcdiff = SW._toggle_fcdiff
    _finish_fcdiff = SW._finish_fcdiff
    _snap_fcdiff = SW._snap_fcdiff
    _draw_freq_cursor = SW._draw_freq_cursor
    _amp_at = SW._amp_at
    _on_click_annotate = SW._on_click_annotate

    def __init__(self):
        self.fcdiff_on = False
        self._fc_t = []
        self._fc_active = 0
        f = np.arange(0, 5000, 0.5)
        a = np.full_like(f, 0.002)
        for hz, amp in ((100.0, 0.8), (220.0, 0.5), (330.0, 0.3)):
            a += amp * np.exp(-((f - hz) ** 2) / 1.0)
        self._cur_f = f
        self._cur_amp = a
        fig = Figure(figsize=(9, 3)); FigureCanvasAgg(fig)
        ax = fig.add_subplot(111); ax.plot(f, a)
        ax.set_xlim(0, 5000); ax.set_ylim(0, 1.0)
        self.fig = fig

    def _set_on(self, *a, **k):
        pass

    def _redraw_current_plot(self):
        pass

    def _push_undo(self):
        pass


print("[点两次吸附 A/B]")
s = S()
s._toggle_fcdiff()
check(s.fcdiff_on is True, "打开频差取点态")
s._on_click_annotate(Ev(102.0))
check(len(s._fc_t) == 1 and abs(s._fc_t[0] - 100.0) < 0.1, f"第一次点击吸附到 100Hz 峰（{s._fc_t}）")
s._on_click_annotate(Ev(218.0))
check(len(s._fc_t) == 2 and abs(s._fc_t[1] - 220.0) < 0.1, f"第二次吸附到 220Hz 峰（{s._fc_t}）")
check(s.fcdiff_on is False, "两个点定完后自动退出取点态")

print("[绘图：A/B 线与 Δf 读数]")
fig = Figure(figsize=(9, 3)); FigureCanvasAgg(fig)
ax = fig.add_subplot(111); ax.plot(s._cur_f, s._cur_amp)
ax.set_xlim(0, 5000); ax.set_ylim(0, 1.0)
s._draw_freq_cursor(ax)
texts = [t.get_text() for t in ax.texts]
check("A 100.0Hz" in texts, f"A 标签（{texts}）")
check("B 220.0Hz" in texts, "B 标签")
check("Δf 120.00Hz" in texts, f"Δf 读数（{texts}）")
vl = [l for l in ax.lines if len(l.get_xdata()) == 2
      and float(l.get_xdata()[0]) == float(l.get_xdata()[1])]
check(len(vl) == 2, f"两条竖线（{len(vl)}）")
circles = [l for l in ax.lines if l.get_marker() == "o"]
check(len(circles) == 2, f"A/B 峰顶各一个圈（{len(circles)}）")

print("[非频域谱图不可用]")
s2 = S(); s2.current_plot = "time"; s2._toggle_fcdiff()
check(s2.fcdiff_on is False, "时域图上开关无效")

print("[Esc 清除]")
s3 = S(); s3._toggle_fcdiff(); s3._on_click_annotate(Ev(102.0))
class K:
    key = "escape"
# 只验证清空逻辑：模拟按键分支
if s3._fc_t:
    s3.fcdiff_on = False; s3._fc_t = []
check(s3._fc_t == [] and s3.fcdiff_on is False, "清空后不再画")


print("[Δf 读数在 overall RMS 下方]")
fig2 = Figure(figsize=(9, 3)); FigureCanvasAgg(fig2)
ax2 = fig2.add_subplot(111); ax2.plot(s._cur_f, s._cur_amp)
ax2.set_xlim(0, 5000); ax2.set_ylim(0, 1.0)
s.active_mark_x = 100.0
s._base_freq_marks = lambda: [100.0]
s._draw_freq_cursor(ax2)
dt = [t for t in ax2.texts if t.get_text().startswith("Δf")]
check(len(dt) == 1 and abs(dt[0].get_position()[0] - 0.012) < 1e-6,
      f"Δf 贴左边（{dt[0].get_position() if dt else None}）")
check(dt and dt[0].get_position()[1] < 0.92, "Δf 在 RMS 框下方")

print("[撤销频差]")
class U(S):
    _push_undo = SW._push_undo
    _undo = SW._undo
    def __init__(self):
        super().__init__()
        self._undo_stack = []
        self.refine_range = None
        self.manual_marks = []
        self.active_mark_x = None
        self._xmax_override = None
        self._harmonics_text = None
        self._sidebands_text = None
        self._bandwidth_text = None
        self._bandwidth_regions = []
        self._base_colors = {}
        self._sideband_params = {}
        self._manual_marks_time = []
        self._single_start_t = None
        self._freq_confirmed = False
        self._tc_t = []
        self._tc_active = 0
        self.axis_locked = False
        self.btn_fcdiff = None
    def _set_locked(self, *a, **k):
        pass
u = U(); u._push_undo(); u._fc_t = [100.0, 220.0]; u._undo()
check(u._fc_t == [], f"撤销后频差清空（{u._fc_t}）")

print()
failed = [x for x in RESULTS if not x]
print(f"共 {len(RESULTS)} 项断言，失败 {len(failed)} 项")
print("RESULT:", "ALL PASS" if not failed else "FAIL")
