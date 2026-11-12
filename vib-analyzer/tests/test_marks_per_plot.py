# -*- coding: utf-8 -*-
"""标注显隐按谱图独立：在时域隐藏，不影响 FFT；各图各记各的。"""
import os
import importlib.util

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
    current_plot = "fft"
    _redraw_current_plot = lambda self: None
    marks_hidden = SW.marks_hidden
    _toggle_marks_visible = SW._toggle_marks_visible

    def __init__(self):
        self._hidden_plots = {}


s = S()
check(s.marks_hidden is False, "默认显示")

s._toggle_marks_visible()
check(s.marks_hidden is True, "FFT 上隐藏标注")

s.current_plot = "time"
check(s.marks_hidden is False, "切到时域 → 标注仍显示（不是全局隐藏）")

s._toggle_marks_visible()
check(s.marks_hidden is True, "时域也隐藏")

s.current_plot = "fft"
check(s.marks_hidden is True, "切回 FFT → 保持它自己的隐藏状态")

s.current_plot = "envelope"
check(s.marks_hidden is False, "没动过的谱图默认显示")

s._toggle_marks_visible()
s._toggle_marks_visible()
check(s.marks_hidden is False, "再点两次回到显示")
check(s._hidden_plots == {"fft": True, "time": True, "envelope": False},
      f"按谱图记录（{s._hidden_plots}）")

print()
failed = [x for x in RESULTS if not x]
print(f"共 {len(RESULTS)} 项断言，失败 {len(failed)} 项")
print("RESULT:", "ALL PASS" if not failed else "FAIL")
