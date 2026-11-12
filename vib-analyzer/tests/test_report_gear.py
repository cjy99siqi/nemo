"""回归测试：把齿轮啮合判读写进报告。

覆盖：
  1. report_gear_scan 能从一个合成 CSV 里认出「一级行星 GMF÷4」的边带；
  2. report_apply_faults 把齿轮结论写回 agg（gear / gear_lab / 等级提升）；
  3. tpl_fill._fill_conclusions 在两种情形下都写出齿轮文字（有条目/只有齿轮）；
  4. report_fault_figure 能出图（含 GMF 标线）。
运行：python tests/test_report_gear.py
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path
import importlib.util

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("vib", ROOT / "振动分析.py")
vib = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vib)

spec2 = importlib.util.spec_from_file_location("tpl_fill", ROOT / "tpl_fill.py")
tpl = importlib.util.module_from_spec(spec2)
spec2.loader.exec_module(tpl)

RESULTS = []


def check(cond, msg):
    RESULTS.append((bool(cond), msg))
    print(("  PASS  " if cond else "  FAIL  ") + msg)


def tmpdir():
    try:
        d = tempfile.mkdtemp(prefix="vibrep_")
        open(os.path.join(d, "x"), "w").close()
        return Path(d)
    except Exception:
        d = ROOT / ".tmprep"
        d.mkdir(exist_ok=True)
        return d


# 合成一条「一级行星 GMF 被 GMF/4 调制」的信号；文件名按现场规范拼，parse_filename 才认
print("[合成数据]")
prof = vib.profile_for_project("五峰")
g1 = prof["gears"][0]
sh = vib.shaft_freqs(1800, prof)
GMF = g1["teeth"] * sh["L"]
STEP = GMF / g1["gcd"]
fs, dur = 20000, 2.0
t = np.arange(int(fs * dur)) / fs
sig = (1.0 + 0.9 * np.cos(2 * np.pi * STEP * t)) * np.sin(2 * np.pi * GMF * t)
sig = sig + 0.01 * np.random.RandomState(0).randn(sig.size)

d = tmpdir()
name = "五峰_13#_齿轮箱_一级齿圈径向_%dHz_%.2fs_加速度值_1800_20250504090029.csv" % (fs, dur)
csv = d / name
np.savetxt(csv, sig, fmt="%.6f")
info = vib.parse_filename(name)
check(bool(info.get("speed")) and info.get("project") == "五峰",
      f"文件名可解析（project={info.get('project')}, rpm={info.get('speed')}）")
check(abs(GMF - 21.14) < 0.05, f"一级行星 GMF = {GMF:.2f}Hz（附件2 为 21.13）")

# 1. 判读
print("\n[report_gear_scan]")
g = vib.report_gear_scan(str(csv), "齿轮箱_一级齿圈径向", "五峰")
check(g is not None, "能给出齿轮判读结论")
if g:
    print(f"      stage={g['stage']}  GMF={g['mesh']:.2f}  间隔={g['spacing']:.2f}  "
          f"match={g['match']}  ratio={g['ratio']:.2f}  level={g['level']}")
    check(g["match"] == "GMF/%d" % g1["gcd"], f"命中 GMF/{g1['gcd']}（实际 {g['match']}）")
    check(abs(g["spacing"] - STEP) < 0.4, f"边带间隔 ≈ {STEP:.2f}Hz（实际 {g['spacing']:.2f}）")
    check(g["level"] in ("关注", "警告"), f"等级被抬高（{g['level']}）")
    check("一级行星" in g["stage"], f"指认到一级行星（{g['stage']}）")

# 2. 写回 agg
print("\n[report_apply_faults]")
agg = {"13#": {"齿轮箱_一级齿圈径向": {"max": 1.0, "peer_med": 1.0, "grade": "正常"}}}
fi = {("13#", "齿轮箱_一级齿圈径向"): {"alarm": False, "gear": g, "gear_csv": str(csv),
                                   "label": "", "hz": 0.0, "thr": 0.0, "ts": ""}}
vib.report_apply_faults(agg, fi)
d0 = agg["13#"]["齿轮箱_一级齿圈径向"]
check(d0.get("gear") is g, "gear 结论写进 agg")
check(bool(d0.get("gear_lab")), f"gear_lab 非空（{d0.get('gear_lab')}）")
check(d0.get("grade") == g["level"], f"等级取齿轮结论（{d0.get('grade')}）")
check(d0.get("csv") == str(csv), "没有轴承命中时用齿轮那条记录作图")

# 3. 报告结论段
print("\n[tpl_fill._fill_conclusions]")
from docx import Document
doc = Document()
doc.add_paragraph("1 1#机组")
p = doc.add_paragraph("机组传动链运行正常。")
agg2 = {"1#": {"齿轮箱_一级齿圈径向": {"grade": "关注", "gear_lab": d0["gear_lab"]}}}
tpl._fill_conclusions(doc, agg2)
check("齿轮啮合" in p.text, f"关注时写出齿轮文字：{p.text[:60]}")

doc = Document()
doc.add_paragraph("1 1#机组")
p = doc.add_paragraph("机组传动链运行正常。")
agg3 = {"1#": {"齿轮箱_一级齿圈径向": {"grade": "警告", "gear_lab": d0["gear_lab"]}}}
tpl._fill_conclusions(doc, agg3)
check("齿轮啮合异常" in p.text, f"警告时写出齿轮异常：{p.text[:60]}")

# 4. 出图
print("\n[report_fault_figure]")
png = str(d / "repfig.png")
out = vib.report_fault_figure(str(csv), "齿轮箱_一级齿圈径向", "五峰", "13#", png)
check(out and os.path.exists(png) and os.path.getsize(png) > 5000,
      "报告插图生成成功（含 GMF 标线）")

# 5. 扫描缓存：第二次应命中缓存且结果一致
print("\n[扫描缓存]")
import time as _time

rows = [{"point": "齿轮箱_一级齿圈径向", "unit": "13", "project": "五峰",
         "rms": 1.0, "ge": 0.0, "csv_path": str(csv),
         "dt_str": "2025-05-04T09:00"}]
cache_path = str(d / "vib_scan_cache.json")

t0 = _time.perf_counter()
fi1 = vib.report_scan_faults({}, rows, "五峰", cache_path=cache_path)
t1 = _time.perf_counter()
fi2 = vib.report_scan_faults({}, rows, "五峰", cache_path=cache_path)
t2 = _time.perf_counter()

check(os.path.exists(cache_path), "缓存文件已写入")
check(vib.REPORT_SCAN_STAT.get("scanned", 0) == 0
      and vib.REPORT_SCAN_STAT.get("cached", 0) >= 2,
      f"第二次全部命中缓存（stat={vib.REPORT_SCAN_STAT}）")
check(t2 - t1 < t1 - t0, f"第二次更快：{t1 - t0:.3f}s → {t2 - t1:.3f}s")
k1, k2 = list(fi1), list(fi2)
check(k1 == k2, f"两次结论的测点集合一致（{k1}）")

# 文件变了要重扫
_os_utime = os.utime
_os_utime(str(csv), None)
vib.report_scan_faults({}, rows, "五峰", cache_path=cache_path)
check(vib.REPORT_SCAN_STAT.get("scanned", 0) >= 1, "文件 mtime 变了会重扫（缓存失效正常）")

shutil.rmtree(d, ignore_errors=True)
print()
failed = [m for ok, m in RESULTS if not ok]
print(f"共 {len(RESULTS)} 项断言，失败 {len(failed)} 项")
print("RESULT:", "ALL PASS" if not failed else "FAIL")
sys.exit(0 if not failed else 1)
