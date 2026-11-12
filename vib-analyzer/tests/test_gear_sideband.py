"""回归测试：齿轮啮合边带判读（按《齿轮啮合图谱经验》的规则）。

覆盖：
  1. 候选间隔能否在 GMF 两侧“点到”真实的边带峰（GMF/3 族、轴转频族）；
  2. 对不上任何候选时不硬判；
  3. 机型库里的 gcd / planets 被正确读入；
  4. _gear_marks_for 会画「GMF÷公约数」族与「N×太阳轮自转」；
  5. _gear_diag_block 输出可读的结论行（不再有“窗口内峰 N 根”这种噪声）。
运行：python tests/test_gear_sideband.py
"""
import sys
from pathlib import Path
import importlib.util

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("vib", ROOT / "振动分析.py")
vib = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vib)

RESULTS = []


def check(cond, msg):
    RESULTS.append((bool(cond), msg))
    print(("  PASS  " if cond else "  FAIL  ") + msg)


def make_spectrum(peaks, amps=None, fmax=5000.0, n=40000):
    """合成一根谱线：给定峰位（高斯鼓包）+ 底噪。"""
    f = np.linspace(0.0, fmax, n)
    amp = np.full_like(f, 0.002)
    for i, fp in enumerate(peaks):
        a = (amps[i] if amps else 0.7)
        amp = amp + a * np.exp(-((f - fp) ** 2) / (2 * 0.25 ** 2))
    return f, amp


# 1. GMF/3 族（材料 1.3：GMF 526.1，1/3 GMF = 175.3）
print("[候选命中]")
GMF = 526.1
peaks = [GMF / 3 * k for k in range(1, 29)]
amps = [1.0 if abs(k - 3) < 0.1 else 0.55 for k in range(1, 29)]
f, a = make_spectrum(peaks, amps)
cands = [("高速轴转频", 25.0), ("GMF/3", GMF / 3), ("中速轴转频", 7.16)]
r = vib.gear_sideband_verdict(f, a, GMF, cands)
check(r["match"] == "GMF/3", f"GMF/3 族 → 命中 GMF/3（实际 {r['match']}）")
check(abs(r["spacing"] - GMF / 3) < 1.5, f"实测间隔 {r['spacing']:.2f} ≈ {GMF/3:.2f}")
check(len(r["hits"]) >= 4, f"命中 {len(r['hits'])} 处边带峰")
check(abs(r["ratio"] - 0.55) < 0.25, f"边带/主峰 {r['ratio']:.2f}")

# 2. 轴转频族（材料 1.1：边频簇间隔＝高速轴转频）
f2, a2 = make_spectrum([25.0 * k for k in range(1, 41)], [0.6] * 40)
r2 = vib.gear_sideband_verdict(f2, a2, 525.0, cands)
check(r2["match"] and "高速轴转频" in r2["match"], f"25Hz 族 → 命中高速轴转频（实际 {r2['match']}）")
check(abs(r2["spacing"] - 25.0) < 0.8, f"实测间隔 {r2['spacing']:.2f} ≈ 25Hz")

# 3. 对不上就不硬判
r3 = vib.gear_sideband_verdict(f, a, GMF, [("中速轴转频", 7.16)])
check(r3["match"] is None, "只给一个不相关的候选 → 返回 None")

# 4. 机型库的 gcd / planets
print("\n[机型库参数]")
wf = vib.MACHINE_LIB.get("运达2.0MW（五峰）") or {}
g0 = (wf.get("gears") or [{}])[0]
check(g0.get("planets") == 3, f"五峰行星轮个数 = 3（实际 {g0.get('planets')}）")
check(g0.get("gcd") == 4, f"五峰行星级齿数公约数 = 4（实际 {g0.get('gcd')}）")


# 5. 标线：GMF÷公约数 族 + N×太阳轮
class _Stub:
    info = {"project": "五峰_13#_x", "point": "齿轮箱_一级齿圈", "speed": 1800}
    _machine_name = None
    current_plot = "fft"
    _gear_stage = 0

    current_machine = vib.SpectrumWindow.current_machine
    _bearing_shaft_freqs = vib.SpectrumWindow._bearing_shaft_freqs
    _label_row = staticmethod(vib.SpectrumWindow._label_row)
    _label_half = staticmethod(vib.SpectrumWindow._label_half)


print("\n[标线]")
f_hss = 29.989791
stub = _Stub()
sf = vib.shaft_freqs(f_hss * 60, wf)
mesh = 92.0 * sf["L"]
marks = vib.SpectrumWindow._gear_marks_for(stub, 0, f_hss, 1, 1, spacing="both")
hz = [m["hz"] for m in marks]
labels = [m.get("label", "") for m in marks]
check(any(abs(x - mesh) < 0.01 for x in hz), f"啮合主峰 {mesh:.2f}Hz 在标注里")
check(abs(mesh - 21.13) < 0.1, f"五峰一级行星 GMF = {mesh:.2f} ≈ 附件2 的 21.13")
check(any(abs(x - mesh / 4) < 0.01 for x in hz), "画了 GMF/4（齿数公约数）族线")
check(any(abs(x - 3 * sf["S"]) < 0.01 for x in hz), f"画了 3×太阳轮自转 {3 * sf['S']:.2f}Hz")
check("3×太阳轮" in labels, "3×太阳轮 有标签")
marks_s = vib.SpectrumWindow._gear_marks_for(stub, 0, f_hss, 1, 1, spacing="shaft")
check(not any(abs(x - mesh / 4) < 0.01 for x in [m["hz"] for m in marks_s]),
      "spacing=shaft 时不画 GMF/n 族")

# 5.2 瀑布图基频细化：STFT 谱线宽 12.5Hz 时，1X 不能被吸到相邻谱线
print("\n[瀑布图基频细化]")
_f = np.arange(0, 200.0, 0.195)
# 合成一条 19.13Hz 的 1X（旁边放一根 19.32 的弱峰，模拟泄漏）
_a = (0.02 + 0.27 * np.exp(-((_f - 19.13) ** 2) / (2 * 0.09 ** 2))
      + 0.24 * np.exp(-((_f - 19.32) ** 2) / (2 * 0.09 ** 2)))


class _RefStub:
    def __init__(self, f, a):
        self._f, self._a = f, a

    def _full_fft_for_refine(self):
        return self._f, self._a


_rs = _RefStub(_f, _a)
for f0 in (12.5, 25.0):
    got = vib.SpectrumWindow._refine_peak_hz(_rs, f0, 6.25)
    check(abs(got - 19.13) < 0.2, f"STFT 谱线 {f0}Hz → 细化到 {got:.2f}Hz（真值 19.13）")

# 5.5 标签排版：频率处横排、相邻标签自动错行
print("\n[标签排版]")
import matplotlib
matplotlib.use("Agg")
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg

fig = Figure(figsize=(6, 3))
FigureCanvasAgg(fig)
ax = fig.add_subplot(111)
ax.set_xlim(0, 1000)
stub._gear_marks = [
    {"hz": 100, "label": "啮合 100", "color": "#d35400", "lw": 1.2},
    {"hz": 140, "label": "啮合 140", "color": "#d35400", "lw": 1.2},
    {"hz": 800, "label": "2×啮合 800", "color": "#d35400", "lw": 1.2},
]
stub._bearing_marks = [
    {"hz": 60, "label": "BPFO", "color": "#1565c0"},
    {"hz": 95, "label": "BPFI", "color": "#c62828"},
]
vib.SpectrumWindow._draw_gear_marks(stub, ax)
vib.SpectrumWindow._draw_bearing_marks(stub, ax)
texts = [t for t in ax.texts]
check(len(texts) >= 4, f"画出了标签（{len(texts)} 个）")
check(all(t.get_rotation() == 0 for t in texts), "标签全部横排（rotation=0）")
rows = {round(t.get_position()[1], 3) for t in texts}
check(len(rows) >= 2, f"相邻标签自动错行（y={sorted(rows)}）")

# 6. 判读卡：用只含 GMF±k×(GMF/4) 的干净谱线，避免与轴转频候选混淆
print("\n[判读卡]")
diag = _Stub()
diag._gear_marks = marks
diag._rot_hz = f_hss
s = mesh / 4
diag._cur_f, diag._cur_amp = make_spectrum(
    [mesh] + [mesh + s * k for k in (-3, -2, -1, 1, 2, 3)],
    [1.0] + [0.45] * 6, fmax=120.0)
blk = vib.SpectrumWindow._gear_diag_block(diag)
check(blk is not None, "判读卡有输出")
if blk:
    print("      " + " | ".join(blk[2]))
    check(blk[1] == "齿轮判读", "标题为「齿轮判读」")
    check(any("GMF/4" in x for x in blk[2]), f"结论指到 GMF/4（{blk[2]}）")
    check(len(blk[2]) <= 7, f"卡片不超过 7 行（实际 {len(blk[2])}）")
    check(not any("窗口内峰" in x for x in blk[2]), "不再显示无意义的“窗口内峰 N 根”")

# 7. 故障模式判定（频谱形态 → 疑似故障类型）
print("\n[故障模式]")
prof5 = vib.profile_for_project("五峰")
sh5 = vib.shaft_freqs(1800, prof5)
g5 = prof5["gears"][0]
mesh5 = g5["teeth"] * sh5["L"]
_fm = np.linspace(0, 2000, 200000)


def _mk(peaks, base=0.002):
    a = np.full_like(_fm, base)
    for hz, am in peaks:
        a = a + am * np.exp(-((_fm - hz) ** 2) / (2 * 0.4 ** 2))
    return a


def _top(peaks, base=0.002, sig=None):
    ev = vib.spectrum_evidence(_fm, _mk(peaks, base), prof5, 30.0, sig=sig)
    return [m[0] for m in vib.fault_modes(ev, point="齿轮箱_一级齿圈径向")]


# 均匀磨损：谐波齐升、无边带
top = _top([(mesh5 * k, 0.6) for k in (1, 2, 3, 4)])
check(top and top[0] == "轮齿均匀过度磨损", f"均匀磨损 → {top[:2]}")
# 健康：只有 GMF
check(_top([(mesh5, 0.6)]) == [], "只有 GMF（健康）→ 不出结论")
# 润滑不良：高频底噪抬高、无规整边带
check((_top([(mesh5, 0.6), (mesh5 * 2, 0.12)], base=0.5) or [""])[0] == "润滑不良",
      "高频底噪 → 润滑不良")
# 断齿：密集边带 + 强冲击（时域给冲击）
_t = np.arange(0, 4, 1 / 20000.0)
_sig = np.sin(2 * np.pi * mesh5 * _t) + 0.3 * np.random.RandomState(0).randn(_t.size)
_sig[(np.mod(_t, 1 / (mesh5 / 4)) < 2 / 20000.0)] += 8.0
top = _top([(mesh5 * k, 0.8) for k in (1, 2, 3)]
           + [(mesh5 + mesh5 / 4 * k, 0.3) for k in (-3, -2, -1, 1, 2, 3)], sig=_sig)
check(top and top[0] == "断齿", f"密集边带+强冲击 → {top[:2]}")

print()
failed = [m for ok, m in RESULTS if not ok]
print(f"共 {len(RESULTS)} 项断言，失败 {len(failed)} 项")
print("RESULT:", "ALL PASS" if not failed else "FAIL")
sys.exit(0 if not failed else 1)
