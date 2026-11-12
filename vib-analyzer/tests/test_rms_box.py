# -*- coding: utf-8 -*-
"""谱图左上角信息：overall RMS + 各基频有效值，无边框（与倍频面板同款样式）。"""
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
    current_plot = "fft"
    _cur_f = None
    _cur_amp = None
    active_mark_x = None
    manual_marks = []
    _plot_rms_unit = SW._plot_rms_unit
    _spectrum_rms = SW._spectrum_rms
    _rms_spectrum = SW._rms_spectrum
    _base_freq_marks = SW._base_freq_marks
    _draw_rms_box = SW._draw_rms_box


f = np.arange(0.0, 1000.0, 0.25)
a = np.zeros_like(f)
a[np.argmin(np.abs(f - 50.0))] = 1.0     # 50Hz 幅值 1.0 → 有效值 0.707
a[np.argmin(np.abs(f - 120.0))] = 0.5    # 120Hz 幅值 0.5 → 有效值 0.354

s = S(); s._cur_f = f; s._cur_amp = a

print("[有效值计算]")
tot = s._spectrum_rms()
check(abs(tot - np.sqrt((1.0 ** 2 + 0.5 ** 2) / 2)) < 1e-3, f"overall RMS = sqrt(Σa²/2)（{tot:.3f}）")
r50 = s._spectrum_rms(50 - 0.75, 50 + 0.75)
check(abs(r50 - 0.7071) < 5e-3, f"50Hz 基频有效值 0.707（{r50:.3f}）")
r120 = s._spectrum_rms(120 - 1.8, 120 + 1.8)
check(abs(r120 - 0.3536) < 5e-3, f"120Hz 基频有效值 0.354（{r120:.3f}）")
check(s._spectrum_rms(2000, 3000) is None, "超出频率范围返回 None")

print("[基频列表]")
s.active_mark_x = 50.0
s.manual_marks = [(50.0, "f0"), (120.0, "f0"), (50.0, "f0"), (100.0, "2X")]
check(s._base_freq_marks() == [50.0, 120.0], f"去重且只取基频（{s._base_freq_marks()}）")

print("[绘图位置与内容]")
fig = Figure(figsize=(9, 4)); FigureCanvasAgg(fig)
ax = fig.add_subplot(111)
ax.plot(f, a); ax.set_xlim(0, 1000)
s._draw_rms_box(ax)
head = [t for t in ax.texts if "overall RMS" in t.get_text()]
check(len(ax.texts) == 1 and len(head) == 1,
      f"只写 overall RMS 一行，不写各基频（共 {len(ax.texts)}）")
check(all("f1 " not in t.get_text() for t in ax.texts), "不再出现 f1/f2 明细")
check("m/s$^2$" in head[0].get_text(), f"单位用 mathtext（{head[0].get_text()}）")
check(head[0].get_bbox_patch() is None, "无边框、无背景")
check(abs(head[0].get_position()[0] - 0.012) < 1e-6
      and abs(head[0].get_position()[1] - 0.975) < 1e-6,
      f"位于坐标区左上（{head[0].get_position()}）")
check(head[0].get_fontweight() == "bold" and abs(head[0].get_fontsize() - 7.8) < 0.01,
      "7.8pt 加粗（同倍频面板）")
check(head[0].get_clip_on() is True, "文字裁剪在坐标区内")

print("[不和其他频率标注重叠]")
check(head[0].get_position()[1] <= 0.98, "顶边 ≤0.98，低于坐标区外的频率标签带（y>1.0）")
check(head[0].get_position()[0] < 0.05, "贴左边，右侧不侵占倍频面板区域")

print("[没有基频时只写 overall RMS]")
s2 = S(); s2._cur_f = f; s2._cur_amp = a; s2.active_mark_x = None; s2.manual_marks = []
fig2 = Figure(); FigureCanvasAgg(fig2); ax2 = fig2.add_subplot(111)
ax2.plot(f, a); ax2.set_xlim(0, 1000)
s2._draw_rms_box(ax2)
body2 = [t.get_text() for t in ax2.texts]
check(len(body2) == 1 and "overall RMS" in body2[0], f"只有 overall RMS 一行（{body2}）")

print("[时域/自相关等不画]")
s3 = S(); s3.current_plot = "time"; s3._cur_f = f; s3._cur_amp = a
fig3 = Figure(); FigureCanvasAgg(fig3); ax3 = fig3.add_subplot(111)
s3._draw_rms_box(ax3)
check(len(ax3.texts) == 0, "时域图不画该信息（量纲不同）")

print("[瀑布图：用全记录 FFT 算 overall RMS]")
fs = 25600.0
tt = np.arange(int(fs * 2)) / fs
sig = 0.5 * np.sin(2 * np.pi * 98.2 * tt) + 0.2 * np.sin(2 * np.pi * 457.9 * tt)


class S4:
    current_plot = "stft"
    fs = 25600.0
    sig = None
    _cur_f = None
    _cur_amp = None
    active_mark_x = None
    manual_marks = []
    _plot_rms_unit = SW._plot_rms_unit
    _spectrum_rms = SW._spectrum_rms
    _rms_spectrum = SW._rms_spectrum
    _base_freq_marks = SW._base_freq_marks
    _draw_rms_box = SW._draw_rms_box


s4 = S4(); s4.sig = sig
# 假一个“STFT 平均谱”，幅值口径完全不同；overall RMS 必须来自信号本身
s4._cur_f = np.arange(0, 5000, 12.5)
s4._cur_amp = np.full_like(s4._cur_f, 0.001)
r = s4._spectrum_rms()
want = np.sqrt((0.5 ** 2 + 0.2 ** 2) / 2)
check(abs(r - want) < 0.02, f"瀑布图 overall 来自信号 FFT（{r:.3f} ≈ {want:.3f}）")
fig4 = Figure(); FigureCanvasAgg(fig4); ax4 = fig4.add_subplot(111)
ax4.plot([0, 1], [0, 1]); ax4.set_xlim(0, 5000)
s4._draw_rms_box(ax4)
heads = [t.get_text() for t in ax4.texts]
check(any("overall RMS" in t and "m/s" in t for t in heads), f"瀑布图也带单位（{heads}）")

print()
failed = [x for x in RESULTS if not x]
print(f"共 {len(RESULTS)} 项断言，失败 {len(failed)} 项")
print("RESULT:", "ALL PASS" if not failed else "FAIL")
