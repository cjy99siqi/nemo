"""回归测试：数据\机型库.json + 各项目自己的齿轮比（不再套明阳）。

覆盖：
  1. 机型库能被 load_machine_lib 读入且无 warning；H 恒为 1，齿轮/测点引用都能对上；
  2. 按项目名能匹配到机型（田家寨/五峰/岑港…），匹配不到的返回 None；
  3. 明阳 2.0MW 的轴转频比与迁移前代码内置值一致（行为不变）；
  4. 运达 2.0MW（五峰）用附件2 的齿轮比，算出的 Hz 与附件2 原表一致——这是这次改动的核心：
     同一轴承在不同项目下必须给出不同频率；
  5. 未识别机型时只给高速轴，不瞎猜；
  6. 机型库字段非法时只记 warning、不崩。
运行：python tests/test_machine_lib.py
"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
import importlib.util

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("vib", ROOT / "振动分析.py")
vib = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vib)

RESULTS = []


def check(cond, msg):
    RESULTS.append((bool(cond), msg))
    print(("  PASS  " if cond else "  FAIL  ") + msg)


def tmpdir():
    """优先系统临时目录；沙箱里 mkdtemp 可能被 ACL 挡住时退回仓库内。"""
    try:
        d = tempfile.mkdtemp(prefix="vibtest_")
        probe = os.path.join(d, "x")
        open(probe, "w").close()
        return Path(d)
    except Exception:
        d = ROOT / ".tmptest"
        d.mkdir(exist_ok=True)
        return d


print(f"机型库：{len(vib.MACHINE_LIB)} 个机型\n")

# 1. 加载与结构
print("[加载与结构]")
check(not vib.MACHINE_LIB_WARNINGS, f"load_machine_lib 无 warning（实际 {vib.MACHINE_LIB_WARNINGS[:3]}）")
check(len(vib.MACHINE_LIB) >= 3, f"至少有明阳/运达/其它机型（实际 {len(vib.MACHINE_LIB)} 个）")
bad_h = [n for n, m in vib.MACHINE_LIB.items() if abs(m["shafts"].get("H", 0) - 1.0) > 1e-9]
check(not bad_h, f"每个机型的 shafts.H 都是 1.0（异常 {bad_h[:3]}）")
bad_gear = [(n, g["name"]) for n, m in vib.MACHINE_LIB.items()
            for g in m["gears"] if g["shaft"] not in m["shafts"] or g["sideband"] not in m["shafts"]]
check(not bad_gear, f"齿轮引用的轴都在 shafts 里（异常 {bad_gear[:3]}）")
missing_b = [(n, b) for n, m in vib.MACHINE_LIB.items()
             for _kw, names in m["points"] for b in names if b not in vib.BEARING_LIB]
check(not missing_b, f"测点映射引用的轴承都在轴承库里（缺 {missing_b[:3]}）")

# 2. 项目 -> 机型
print("\n[项目名匹配]")
CASES = [("田家寨_101#_主轴承_前轴径向", "明阳2.0MW"),
         ("五峰_13#_齿轮箱_高速轴径向", "运达2.0MW（五峰）"),
         ("岑港_3#_主轴承_前轴径向", "岑港")]
for proj, expect in CASES:
    got = vib.machine_for_project(proj)[0]
    check(got == expect, f"{proj.split('_')[0]} -> {got}（期望 {expect}）")
check(vib.machine_for_project("没听说过的项目") == (None, None), "未登记项目返回 (None, None)")

# 3. 明阳口径不变（等价于迁移前的 GB_I1/I2/I3 公式）
print("\n[明阳：与迁移前公式一致]")
f = vib.shaft_freqs(1800, vib.profile_for_project("田家寨"))
GB_I3, GB_I2, GB_I1, ZR, ZP = 112.0 / 23, 113.0 / 24, 1 + 109.0 / 23, 109.0, 43.0
fH = 30.0
fM, fS, fL = fH / GB_I3, fH / GB_I3 / GB_I2, fH / GB_I3 / GB_I2 / GB_I1
expect = {"H": fH, "M": fM, "S": fS, "L": fL, "P": fL * ZR / ZP}
for k, v in expect.items():
    check(abs(f[k] - v) / v < 1e-6, f"明阳 {k} 轴 {f[k]:.5f} Hz / 旧公式 {v:.5f} Hz")

# 4. 五峰：附件2 的齿轮比 + 附件2 的绝对频率
print("\n[五峰：用附件2 自己的齿轮比]")
prof = vib.profile_for_project("五峰")
check(prof is not None, "五峰 匹配到机型")
f = vib.shaft_freqs(29.989791 * 60.0, prof)     # 附件2 额定高速轴转速
check(abs(f["L"] - 0.229709) < 2e-4, f"行星架转频 {f['L']:.5f} ≈ 附件2 0.229709")
check(abs(f["S"] - 1.286371) < 2e-3, f"低速轴转频 {f['S']:.5f} ≈ 附件2 1.286371")
check(abs(f["M"] - 5.75804) < 5e-3, f"中速轴转频 {f['M']:.5f} ≈ 附件2 5.75804")
# 附件2「中速轴后轴承1 30244」外圈 49.4Hz、内圈 65.8Hz
b = vib.BEARING_LIB["五峰中速轴后轴承1 30244"]
base = f["M"]
check(abs(b[1]["BPFO"] * base - 49.4) / 49.4 < 1e-3,
      f"30244 BPFO {b[1]['BPFO'] * base:.2f} Hz ≈ 附件2 49.4 Hz")
check(abs(b[1]["BPFI"] * base - 65.8) / 65.8 < 1e-3,
      f"30244 BPFI {b[1]['BPFI'] * base:.2f} Hz ≈ 附件2 65.8 Hz")
# 行星架轴承 6.31Hz 挂在「主轴/行星架」轴，而不是行星轮
b = vib.BEARING_LIB["五峰行星架前轴承 NCF28/750"]
check(b[0] == "L", f"行星架前轴承轴代号为 L（实际 {b[0]}）")
check(abs(b[1]["BPFO"] * f["L"] - 6.31) / 6.31 < 1e-3,
      f"行星架前 BPFO {b[1]['BPFO'] * f['L']:.2f} Hz ≈ 附件2 6.31 Hz")

# 核心对比：同一个轴承（发电机 6332）在明阳/运达下都用 H，频率应一致；
# 而中速轴轴承在两套齿轮比下必须不同。
mg = vib.shaft_freqs(1800, vib.profile_for_project("田家寨"))
wf = vib.shaft_freqs(1800, prof)
check(abs(mg["M"] - wf["M"]) > 0.1,
      f"中速轴转频两机型不同：明阳 {mg['M']:.3f} vs 运达 {wf['M']:.3f}")

# 5. 未识别机型：只给高速轴
print("\n[未知项目不猜轴]")
u = vib.shaft_freqs(1800, None)
check(u == {"H": 30.0}, f"未知机型只返回 H（实际 {u}）")


# 5.5 自动标注（不建 Tk，直接驱动 SpectrumWindow 的两个方法）
print("\n[自动标注：项目+测点 -> 轴承 -> 频率]")


class _Stub:
    def __init__(self, proj, pt, rpm):
        self.info = {"project": proj, "point": pt, "speed": rpm}
        self._auto_bearing_on = True
        self._machine_name = None
        self._bearing_marks = []
        self._auto_bearing_used = False

    current_machine = vib.SpectrumWindow.current_machine
    _bearing_shaft_freqs = vib.SpectrumWindow._bearing_shaft_freqs


def auto_marks(proj, pt, rpm=1800):
    s = _Stub(proj, pt, rpm)
    vib.SpectrumWindow._apply_auto_bearing_marks(s)
    # 多轴承的测点会加 "2236-" 这类前缀，这里按特征名归组
    out = {}
    for x in s._bearing_marks:
        out.setdefault(x["label"].split("-")[-1], []).append(x["hz"])
    return out


m = auto_marks("五峰_13#_齿轮箱_高速轴径向_20250504090029", "齿轮箱_高速轴径向")
check(any(abs(hz - 7.64927 * 30.0) < 0.05 for hz in m.get("BPFO", [])),
      f"五峰 高速轴前轴承 BPFO 在 {m.get('BPFO')} 里（=7.64927×30=229.5）")
check(len(m.get("BPFO", [])) == 2, f"五峰 高速轴测点标了前后两个轴承（实际 {m.get('BPFO')}）")
m = auto_marks("田家寨_101#_齿轮箱_高速轴径向", "齿轮箱_高速轴径向")
check(abs(m.get("BPFO", [0])[0] - 7.667 * 30.0) < 0.05,
      f"明阳 高速轴径向 BPFO={m.get('BPFO')} Hz（=7.667×30）")
check(not auto_marks("没听说过的项目_1#_齿轮箱_高速轴径向", "齿轮箱_高速轴径向"),
      "未登记项目不自动标注")

# 5.6 齿轮啮合：各级齿数取当前机型
print("\n[齿轮啮合频率]")


def mesh_hz(proj, stage, rpm=1800):
    s = _Stub(proj, "齿轮箱_一级内齿圈径向", rpm)
    marks = vib.SpectrumWindow._gear_marks_for(s, stage, rpm / 60.0, 1, 0)
    return marks[0]["hz"] if marks else 0.0


check(abs(mesh_hz("五峰_13#_x", 0) - 92 * 30 * 0.007659574) < 0.05,
      f"五峰 一级行星啮合 {mesh_hz('五峰_13#_x', 0):.2f} Hz（92齿×行星架）")
check(abs(mesh_hz("田家寨_101#_x", 0) - 109 * 30 * 0.007599701) < 0.05,
      f"明阳 一级行星啮合 {mesh_hz('田家寨_101#_x', 0):.2f} Hz（109齿×行星架）")
check(abs(mesh_hz("五峰_13#_x", 2) - 125 * 30 * 0.192) < 0.5,
      f"五峰 三级啮合 {mesh_hz('五峰_13#_x', 2):.1f} Hz（125齿×中速轴）")
check(mesh_hz("没听说过的项目_x", 0) == 0.0, "未登记机型算不出啮合，返回空")

# 6. 非法字段只告警
print("\n[非法字段容错]")
d = tmpdir()
path = d / "机型库.json"
doc = {"machines": {
    "坏机型": {"shafts": {"M": 0.2}, "gears": [], "points": []},          # 缺 H
    "轴非法": {"shafts": {"H": 1.0, "X": 0.5}, "gears": [], "points": []},
    "齿轮坏": {"shafts": {"H": 1.0, "M": 0.2},
              "gears": [{"teeth": 0, "shaft": "M"}, {"teeth": 10, "shaft": "Z"}],
              "points": [["x", []]]},
    "好机型": {"projects": ["测试场"], "shafts": {"H": 1.0, "M": 0.2},
              "gears": [{"name": "三级", "teeth": 20, "shaft": "M"}],
              "points": [["高速轴", ["电机 SKF6334"]]]},
}}
path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
saved = dict(vib.MACHINE_LIB)
vib.MACHINE_LIB.clear()
vib.MACHINE_LIB_WARNINGS.clear()
try:
    n, warns = vib.load_machine_lib(path)
    check(n == 3, f"3 个机型入库、1 个因缺 H 被拒（实际 {n}）")
    check("坏机型" not in vib.MACHINE_LIB, "缺 H 的机型没有入库")
    check(vib.MACHINE_LIB.get("轴非法", {}).get("shafts") == {"H": 1.0},
          f"非法轴代号被丢掉，只剩 H（实际 {vib.MACHINE_LIB.get('轴非法', {}).get('shafts')}）")
    check(not vib.MACHINE_LIB.get("齿轮坏", {}).get("gears"), "齿数/轴非法的齿轮条目被丢掉")
    check(any("H" in w for w in warns), f"缺 H 有 warning（{warns[:2]}）")
    check(any("轴代号" in w for w in warns), "非法轴代号有 warning")
    check(any("齿轮" in w for w in warns), "非法齿轮条目有 warning")
    check(any("测点" in w for w in warns), "空测点映射有 warning")
    check(vib.MACHINE_LIB.get("好机型", {}).get("projects") == ["测试场"], "合法机型正常入库")
    check(vib.shaft_freqs(1800, "好机型")["M"] == 6.0, "好机型 轴转频 = 30 × 0.2")
finally:
    vib.MACHINE_LIB.clear()
    vib.MACHINE_LIB.update(saved)
    vib.MACHINE_LIB_WARNINGS.clear()
    shutil.rmtree(d, ignore_errors=True)

print()
failed = [m for ok, m in RESULTS if not ok]
print(f"共 {len(RESULTS)} 项断言，失败 {len(failed)} 项")
print("RESULT:", "ALL PASS" if not failed else "FAIL")
sys.exit(0 if not failed else 1)
