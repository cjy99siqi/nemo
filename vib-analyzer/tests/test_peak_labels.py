# -*- coding: utf-8 -*-
"""峰值标注：频率统一 1 位小数（81.7Hz），和基频标注一致；阶次谱不受影响。"""
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


class S:
    show_peaks = True
    marks_hidden = False


def make(f_hz):
    f = np.arange(0, 5000, 0.25)
    amp = np.zeros_like(f)
    for hz, a in f_hz:
        amp += a * np.exp(-((f - hz) ** 2) / (2 * 1.2 ** 2))
    fig = Figure(figsize=(9, 3.5)); FigureCanvasAgg(fig)
    ax = fig.add_subplot(111); ax.plot(f, amp); ax.set_xlim(0, 5000)
    SW._peak_annotate(S(), ax, f, amp, top_n=5)
    return [t.get_text() for t in ax.texts]


print("[包络/FFT 谱：频率 1 位小数]")
texts = make(((81.72, 0.30), (163.45, 0.19), (245.0, 0.30), (490.7, 0.12), (1305.2, 0.16)))
check(any(t.startswith("81.7Hz") or t.startswith("81.8Hz") for t in texts),
      f"81.7Hz 不再是 82Hz（{texts}）")
check(all("." in t.split("Hz")[0] for t in texts), f"每个峰值都带 1 位小数（{texts}）")
check(not any(t == "82Hz" for t in texts), "没有整数形式的 82Hz")

print("[幅值另起一行]")
check(all(t.count(chr(10)) == 1 for t in texts), f"每个标签都是两行（{texts}）")
check(all(not t.split(chr(10))[1].startswith("A=") for t in texts), "第二行直接写数值（无 A= 前缀）")
_amp_line = texts[0].split(chr(10))[1]
check(_amp_line == "0.300", f"幅值随第一行给出（{_amp_line}）")

print("[阶次谱：保持原格式]")
fig = Figure(); FigureCanvasAgg(fig); ax2 = fig.add_subplot(111)
x = np.linspace(0, 10, 400)
ax2.plot(x, np.abs(np.sin(x))); ax2.set_xlim(0, 10)
SW._peak_annotate(S(), ax2, x, np.abs(np.sin(x)), unit=" Order")
orders = [t.get_text() for t in ax2.texts]
check(orders and all("Order" in t for t in orders), f"阶次谱标签仍带 Order（{orders[:2]}）")

# ---- 标签不重叠（两行标签按屏幕矩形避让）----
print("[标签不互相压字]")
import numpy as np
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg


class S2:
    show_peaks = True
    marks_hidden = False
    current_plot = "envelope"
    _plot_rms_unit = SW._plot_rms_unit
    _rms_spectrum = SW._rms_spectrum
    _spectrum_rms = SW._spectrum_rms
    _base_freq_marks = SW._base_freq_marks
    _draw_rms_box = SW._draw_rms_box


ff = np.arange(0, 2000, 0.25)
aa = np.full_like(ff, 0.002)
for hz, amp in ((0.8, 0.282), (32.6, 0.121), (163.5, 0.139), (457.9, 0.202)):
    aa += amp * np.exp(-((ff - hz) ** 2) / 0.6)
s2 = S2(); s2._cur_f = ff; s2._cur_amp = aa
s2.active_mark_x = None; s2.manual_marks = []
fig2 = Figure(figsize=(9, 3.4), dpi=120); FigureCanvasAgg(fig2)
ax2 = fig2.add_subplot(111); ax2.plot(ff, aa, lw=0.6)
ax2.set_xlim(0, 2000); ax2.set_ylim(0, 0.35)
fig2.canvas.draw()
SW._peak_annotate(s2, ax2, ff, aa, top_n=4)
s2._draw_rms_box(ax2)
fig2.canvas.draw()
ren = fig2.canvas.get_renderer()
rects = [t.get_window_extent(ren) for t in ax2.texts
         if t.get_text() and not t.get_text().startswith("overall")]
check(len(rects) >= 3, f"至少画出 3 个峰值标签（{len(rects)}）")
overlaps = []
for i in range(len(rects)):
    for j in range(i + 1, len(rects)):
        a1, b1 = rects[i], rects[j]
        if not (a1.x1 <= b1.x0 or a1.x0 >= b1.x1 or a1.y1 <= b1.y0 or a1.y0 >= b1.y1):
            overlaps.append((i, j))
check(not overlaps, f"标签矩形互不重叠（重叠对={overlaps}）")

box = [t for t in ax2.texts if t.get_text().startswith("overall")][0].get_window_extent(ren)
bad_box = [r for r in rects
           if not (r.x1 <= box.x0 or r.x0 >= box.x1 or r.y1 <= box.y0 or r.y0 >= box.y1)]
check(not bad_box, f"没有标签压到 overall RMS（{len(bad_box)} 个）")

print()
failed2 = [x for x in RESULTS if not x]
print(f"共 {len(RESULTS)} 项断言，失败 {len(failed2)} 项")
print("RESULT:", "ALL PASS" if not failed2 else "FAIL")
