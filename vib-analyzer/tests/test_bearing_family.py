# -*- coding: utf-8 -*-
"""轴承阶次“谐波族”匹配：别把 2×BSF 认成 BPFI。"""
import os
import importlib.util

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("vib", os.path.join(ROOT, "振动分析.py"))
vib = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vib)

RESULTS = []


def check(ok, msg):
    RESULTS.append((bool(ok), msg))
    print(("  PASS  " if ok else "  FAIL  ") + msg)


if not vib.BEARING_LIB:
    vib.load_bearing_lib()

RPM = 1746
FR = RPM / 60.0
PROJ = "田家寨"
PT = "发电机_后轴承径向"
sh = vib.shaft_freqs(RPM, vib.profile_for_project(PROJ))
names = vib.report_bearing_names(PROJ, PT)
print("候选轴承:", names, " 转频 %.2fHz" % FR)


def spectrum(peaks, fmax=500.0, base=0.01):
    f = np.arange(0.0, fmax, 0.05)
    a = np.full_like(f, base)
    for hz, amp in peaks:
        a = a + amp * np.exp(-((f - hz) ** 2) / (2 * 0.12 ** 2))
    return f, a


print("\n[BSF 族 vs BPFI]")
bsf = 2.360 * FR
f, a = spectrum([(bsf * k, v) for k, v in
                 ((1, 0.35), (2, 0.40), (3, 0.17), (4, 0.19), (5, 0.13), (6, 0.12))])
best = vib.bearing_family_match(f, a, sh, names)
check(best is not None, "能给出匹配")
check(best["key"] == "BSF", f"选 BSF 而不是 BPFI（实际 {best['key']}）")
check("6332" in best["bearing"], f"选 6332MC4（实际 {best['bearing']}）")
check(best["hits"] >= 5, f"谐波族命中 {best['hits']} 阶（≥5）")
check(abs(best["dev"]) < 0.02, f"偏差 {best['dev'] * 100:+.1f}%（<2%）")
check(not best["ambiguous"], "证据差得开，不标两解")

print("\n[BPFO 族]")
bpfo = 3.187 * FR
f2, a2 = spectrum([(bpfo * k, v) for k, v in ((1, 0.30), (2, 0.12), (3, 0.06))])
best2 = vib.bearing_family_match(f2, a2, sh, names)
check(best2 is not None and best2["key"] == "BPFO", f"选 BPFO（实际 {best2['key'] if best2 else None}）")

print("\n[单点提示 bearing_hint]")
h = vib.bearing_hint(69.28, sh, names)
check(h is not None and h[1] == "BSF", f"69.28Hz → BSF（实际 {h[1] if h else None}）")
check(h is not None and abs(h[2] - bsf) < 0.5, f"理论 %.2fHz（实际 %.2f）" % (bsf, h[2] if h else 0))
h2 = vib.bearing_hint(66.3, sh, names)
check(h2 is not None and "6334" in h2[0], f"66.3Hz → 6334（实际 {h2[0] if h2 else None}）")

print("\n[没有轴承时]")
check(vib.bearing_family_match(f, a, sh, []) is None, "候选为空 → None")

print()
failed = [m for ok, m in RESULTS if not ok]
print(f"共 {len(RESULTS)} 项断言，失败 {len(failed)} 项")
print("RESULT:", "ALL PASS" if not failed else "FAIL")
