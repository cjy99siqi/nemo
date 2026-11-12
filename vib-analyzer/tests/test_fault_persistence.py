# -*- coding: utf-8 -*-
"""报告判读：阈值按实测标定 + 复现才算警告（单次尖峰最多“关注”）。"""
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


PT = "发电机_前轴承径向"
AMI = 0.1


def mkrows(unit, amps, key="BPFO×1"):
    rows = []
    for i, a in enumerate(amps):
        rows.append({"point": PT, "unit": unit, "project": "田家寨", "rms": 1.0, "ge": 0.0,
                     "csv_path": "/fake/%s_%02d.csv" % (unit, i),
                     "dt_str": "2026-06-%02dT00:00" % (i + 1), "dt_ts": 1000.0 + i})
    return rows


ENV = {}          # csv -> env dict


def fake_scan(csv, point, project, cache, want_gear=False):
    e = ENV.get(csv)
    return (e, None, False)


vib._scan_file = fake_scan
vib._scan_cache_load = lambda p: None
vib._scan_cache_save = lambda p, c: None


def key_of(unit):
    """报告里的键是 report_unit_label 归一化后的机组名（如 105#）。"""
    return (vib.report_unit_label(unit, "田家寨"), PT)


def run(rows):
    return vib.report_scan_faults({}, rows, "田家寨")


def set_env(csv, amp, label="BPFO×1", bearing="6332M C4"):
    ENV[csv] = {"amp": amp, "label": label, "hz": 164.2, "bearing": bearing,
                "order": 3.2, "family_hits": 3, "dev": 0.004, "ambiguous": False}


print("[阈值常量]")
check(abs(vib.ENV_FAULT_AMP_FLOOR - 0.2) < 1e-9, f"绝对下限 0.2（{vib.ENV_FAULT_AMP_FLOOR}）")
check(vib.ENV_SCAN_FILES == 5 and vib.ENV_MIN_HITS == 2, "回看 5 次、至少复现 2 次")

print("[持续出现 → 警告]")
ENV.clear()
rows = []
for u in ("101", "102", "103", "104"):
    for r in mkrows(u, [0.1]):
        set_env(r["csv_path"], 0.1)
        rows.append(r)
for r in mkrows("105", [0.6] * 5):
    set_env(r["csv_path"], 0.6)
    rows.append(r)
fi = run(rows)
k = key_of("105")
check(fi[k]["level"] == "警告" and fi[k]["alarm"] is True,
      f"5 次都命中且超阈值 → 警告（{fi[k]['level']}, amp={fi[k]['amp']:.2f}, thr={fi[k]['thr']:.2f}）")
check(fi[k]["hits_n"] == 5 and fi[k]["files_n"] == 5, f"复现计数 5/5（{fi[k]['hits_n']}/{fi[k]['files_n']}）")
check(fi[k]["amp"] < 0.61, f"幅值取中位数而不是最大值（{fi[k]['amp']:.3f}）")
check(fi[key_of("101")]["level"] == "正常", "低幅值机组保持正常")

print("[单次尖峰 → 只给关注]")
ENV.clear()
rows2 = mkrows("201", [0.9, 0.05, 0.05, 0.05, 0.05])
for i, r in enumerate(rows2):
    # 只有第一条是同一阶次，其它换成别的阶次，模拟“偶发一次”
    set_env(r["csv_path"], 0.9 if i == 0 else 0.05, label="BPFO×1" if i == 0 else "BSF×1")
for u in ("202", "203", "204"):
    for r in mkrows(u, [0.05]):
        set_env(r["csv_path"], 0.05)
fi2 = run(rows2 + [r for u in ("202", "203", "204") for r in mkrows(u, [0.05])])
k2 = key_of("201")
check(fi2[k2]["alarm"] is False, "单次峰值不判警告")
check(fi2[k2]["level"] == "关注", f"降级为关注（{fi2[k2]['level']}）")

print("[只有一条记录：要明显超阈值才报]")
ENV.clear()
rows3 = mkrows("301", [0.35])
for u in ("302", "303", "304"):
    for r in mkrows(u, [0.1]):
        set_env(r["csv_path"], 0.1)
set_env(rows3[0]["csv_path"], 0.35)
fi3 = run(rows3 + [r for u in ("302", "303", "304") for r in mkrows(u, [0.1])])
k3 = key_of("301")
check(fi3[k3]["files_n"] == 1, "只有 1 条记录")
check(abs(fi3[k3]["thr"] - 0.5) < 0.01, f"阈值 = 5×同型中位（{fi3[k3]['thr']:.2f}）")
check(fi3[k3]["alarm"] is False, "1 条记录 + 0.35 幅值 → 不报警（需 1.5×阈值）")

print()
failed = [x for x in RESULTS if not x]
print(f"共 {len(RESULTS)} 项断言，失败 {len(failed)} 项")
print("RESULT:", "ALL PASS" if not failed else "FAIL")
