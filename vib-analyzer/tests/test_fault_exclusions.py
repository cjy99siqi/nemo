# -*- coding: utf-8 -*-
"""判读交叉排除：与 1X/啮合频率重合、只命中 1 阶、两只轴承分不清 → 都不给“警告”。"""
import os
import importlib.util

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("vib", os.path.join(ROOT, "振动分析.py"))
vib = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vib)

RESULTS = []


def check(ok, msg):
    RESULTS.append(bool(ok))
    print(("  PASS  " if ok else "  FAIL  ") + msg)


print("[转频/啮合频率重合]")
check(vib.fault_freq_conflict(18.4, 1101, None) == "1X转频", "18.4Hz ≈ 1X")
check(vib.fault_freq_conflict(36.8, 1101, None) == "2X转频", "36.8Hz ≈ 2X")
check(vib.fault_freq_conflict(55.0, 1101, None) == "3X转频", "55.0Hz ≈ 3X")
check(vib.fault_freq_conflict(120.0, 1101, None) == "", "120Hz 不与转频重合")
prof = {"shafts": {"H": 1.0}, "gears": [{"name": "一级", "shaft": "H", "teeth": 30}]}
check(vib.fault_freq_conflict(30.2, 60, prof) == "一级啮合×1", "≈ 啮合频率 1×")
check(vib.fault_freq_conflict(60.3, 60, prof) == "一级啮合×2", "≈ 啮合频率 2×")
check(vib.fault_freq_conflict(0, 1101, None) == "", "无效输入返回空")

PT = "发电机_前轴承径向"
ENV = {}


def fake_scan(csv, point, project, cache, want_gear=False):
    return (ENV.get(csv), None, False)


vib._scan_file = fake_scan
vib._scan_cache_load = lambda p: None
vib._scan_cache_save = lambda p, c: None


def rows_for(unit, amps):
    return [{"point": PT, "unit": unit, "project": "田家寨", "rms": 1.0, "ge": 0.0,
             "csv_path": "/fake/%s_%02d.csv" % (unit, i),
             "dt_str": "2026-06-%02dT00:00" % (i + 1), "dt_ts": 1000.0 + i}
            for i in range(len(amps))]


def env(amp, weak=False, conflict="", ambiguous=False):
    return {"amp": amp, "label": "BPFO×1", "hz": 164.2, "bearing": "6332M C4",
            "order": 3.2, "family_hits": 6, "dev": 0.004, "ambiguous": ambiguous,
            "weak": weak, "conflict": conflict}


def run(rows):
    return vib.report_scan_faults({}, rows, "田家寨")


def build(unit, amp, **kw):
    rs = rows_for(unit, [amp] * 5)
    for r in rs:
        ENV[r["csv_path"]] = env(amp, **kw)
    return rs


def key_of(unit):
    return (vib.report_unit_label(unit, "田家寨"), PT)


print("[有冲突时不给警告]")
ENV.clear()
rows = []
for u in ("101", "102", "103", "104"):
    for r in rows_for(u, [0.1]):
        ENV[r["csv_path"]] = env(0.1)
        rows.append(r)
rows += build("105", 0.6, conflict="1X转频")
fi = run(rows)
k = key_of("105")
check(fi[k]["alarm"] is False, "与 1X 重合 → 不报警告")
check(fi[k]["level"] == "关注", f"降级为关注（{fi[k]['level']}）")
check(fi[k]["conflict"] == "1X转频", "冲突原因写进结果")

print("[只有 1× 命中 → 弱证据]")
ENV.clear()
rows = []
for u in ("201", "202", "203", "204"):
    for r in rows_for(u, [0.1]):
        ENV[r["csv_path"]] = env(0.1)
        rows.append(r)
rows += build("205", 0.6, weak=True)
fi = run(rows)
k = key_of("205")
check(fi[k]["alarm"] is False and fi[k]["weak"] is True, "弱证据不报警告")

print("[两只轴承分不清 → 需复核]")
ENV.clear()
rows = []
for u in ("301", "302", "303", "304"):
    for r in rows_for(u, [0.1]):
        ENV[r["csv_path"]] = env(0.1)
        rows.append(r)
rows += build("305", 0.6, ambiguous=True)
fi = run(rows)
k = key_of("305")
check(fi[k]["alarm"] is False, "ambiguous → 不报警告")

print("[干净命中仍然报警告]")
ENV.clear()
rows = []
for u in ("401", "402", "403", "404"):
    for r in rows_for(u, [0.1]):
        ENV[r["csv_path"]] = env(0.1)
        rows.append(r)
rows += build("405", 0.6)
fi = run(rows)
k = key_of("405")
check(fi[k]["alarm"] is True and fi[k]["level"] == "警告", "无冲突、5/5 复现 → 警告")

print("[报告文字带上排除说明]")
agg = {"405#": {PT: {"grade": "正常", "max": 1.0}}}
fi2 = {("405#", PT): dict(fi[k], alarm=False, level="关注", conflict="1X转频", weak=True,
                          label="BPFO×1", amp=0.6, hz=164.2, bearing="6332M C4",
                          family_hits=6, dev=0.004, files_n=5, hits_n=5, thr=0.5)}
vib.report_apply_faults(agg, fi2)
lab = agg["405#"][PT].get("fault_lab", "")
check("仅 1× 命中" in lab and "临近1X转频" in lab, f"判定依据写进报告（{lab[:60]}）")
check(agg["405#"][PT]["grade"] == "关注", "等级为关注")

print("[判读依据可追溯]")
ev = vib.report_evidence_text(25600, (1000, 8000), 0.5, "2026-06-11 07:04:50")
check("fs 25600Hz" in ev and "解调 1000–8000Hz" in ev and "阈值 0.50" in ev,
      f"依据含 fs/解调带/阈值（{ev}）")
check("2026-06-11 07:04" in ev, "依据含数据时间")
check(vib.report_evidence_text() == "", "无参数时返回空串（不写半句废话）")
agg2 = {"405#": {PT: {"grade": "正常", "max": 1.0}}}
fi3 = {("405#", PT): dict(fi[k], alarm=True, level="警告", fs=25600.0,
                          demod=(1000.0, 8000.0), thr=0.5)}
vib.report_apply_faults(agg2, fi3)
d3 = agg2["405#"][PT]
check(d3.get("env_fs") == 25600.0 and d3.get("env_demod") == (1000.0, 8000.0),
      "采样率/解调带挂到 agg，供报告正文引用")
check(d3.get("env_thr") == 0.5, "阈值也挂上")

print()
failed = [x for x in RESULTS if not x]
print(f"共 {len(RESULTS)} 项断言，失败 {len(failed)} 项")
print("RESULT:", "ALL PASS" if not failed else "FAIL")
