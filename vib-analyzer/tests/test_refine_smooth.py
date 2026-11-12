# -*- coding: utf-8 -*-
"""框选细化用 blit 绘制：拖拽时只重画红框，不整图重绘（避免第一帧卡顿）。"""
import os
import importlib.util

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


class S:
    refine_on = False
    axis_locked = False
    _refine_relock = False
    annotate_mode = False
    btn_refine = None
    rs = None
    _toggle_refine = SW._toggle_refine
    _on_select_refine = lambda self, e1, e2: None

    def __init__(self):
        self.fig = Figure(figsize=(8, 3))
        FigureCanvasAgg(self.fig)
        self.ax = self.fig.add_subplot(111)
        self.canvas = self.fig.canvas

    def _set_on(self, btn, val):
        pass

    def _destroy_selector(self):
        self.rs = None

    def _redraw_current_plot(self):
        pass


print("[框选细化]")
s = S()
SW._toggle_refine(s)
check(s.refine_on is True, "进入细化模式")
check(s.rs is not None, "创建了框选选择器")
check(bool(getattr(s.rs, "useblit", False)) is True, "useblit=True（拖拽只重绘红框）")
check(s.rs.ax is s.ax, "选择器绑在当前坐标轴上")

SW._toggle_refine(s)
check(s.refine_on is False, "再次点击退出细化")
check(s.rs is None, "退出时销毁选择器")

print()
failed = [x for x in RESULTS if not x]
print(f"共 {len(RESULTS)} 项断言，失败 {len(failed)} 项")
print("RESULT:", "ALL PASS" if not failed else "FAIL")
