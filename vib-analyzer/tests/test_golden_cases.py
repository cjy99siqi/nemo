# -*- coding: utf-8 -*-
"""黄金案例回归：把《齿轮啮合图谱经验.md》§6 的可测证据固化成用例。

每个案例只测“图谱证据能否被识别出来”（啮合频率 + 边带间隔 → 命中谁），
拆检结论（剥落/断齿）依赖实物，程序不判，所以不在断言里。

合成谱：中心一根 GMF、两侧各 3 根间隔 s 的边带、2× GMF、低噪声。
这些参数直接取自经验文档里记录的实测值。
"""
import os
import importlib.util

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("vib", os.path.join(ROOT, "振动分析.py"))
vib = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vib)

RESULTS = []


def check(ok, msg):
    RESULTS.append(bool(ok))
    print(("  PASS  " if ok else "  FAIL  ") + msg)


def spec_curve(mesh, spacing, n_side=3, amp_side=0.18, noise=0.004, hi=None, df=0.25):
    hi = hi or max(mesh * 2.5, 200.0)
    f = np.arange(0.0, hi + df, df)
    a = np.full_like(f, noise)

    def g(c, w, h):
        return h * np.exp(-0.5 * ((f - c) / w) ** 2)

    a += g(mesh, 0.6, 1.0)
    a += g(mesh * 2, 0.7, 0.15)
    for k in range(1, n_side + 1):
        a += g(mesh - k * spacing, 0.5, amp_side / k)
        a += g(mesh + k * spacing, 0.5, amp_side / k)
    return f, a


# (编号, 部位, GMF, 边带间隔, 候选表, 期望命中)
CASES = [
    ("1.3", "高速轴齿轮", 526.1, 526.1 / 3,
     [("GMF/3", 526.1 / 3), ("高速轴转频", 9.19)], "GMF/3"),
    ("1.4", "高速轴齿轮", 555.5, 555.5 / 11,
     [("GMF/11", 555.5 / 11), ("2×高速轴", 18.4)], "GMF/11"),
    ("3.1", "中速轴小齿轮", 155.6, 7.178,
     [("中速轴转频", 7.178), ("GMF/3", 155.6 / 3)], "中速轴转频"),
    ("5.1", "行星级太阳轮", 51.71, 7.388,
     [("3×太阳轮", 7.388), ("GMF/3", 51.71 / 3)], "3×太阳轮"),
    ("6.1", "行星级行星轮", 35.82, 35.82 / 3,
     [("GMF/3", 35.82 / 3), ("行星轮通过", 35.82 / 3)], "GMF/3"),
]

print("[18 案例中的图谱证据]")
for num, part, mesh, sp, cands, want in CASES:
    f, a = spec_curve(mesh, sp)
    r = vib.gear_sideband_verdict(f, a, mesh, cands)
    got_sp = float(r.get("spacing") or 0.0)
    check(r.get("match") == want, f"{num} {part}：命中 {want}（实际 {r.get('match')}）")
    check(abs(got_sp - sp) <= 0.03 * sp, f"{num} 间隔 {sp:.2f}Hz（实际 {got_sp:.2f}）")
    check(len(r.get("hits") or []) >= 2, f"{num} 至少 2 处命中（{len(r.get('hits') or [])}）")

print("[阴性：没有边带时不能硬指认]")
f0, a0 = spec_curve(200.0, 5.0)
for k in range(1, 4):                      # 抹掉边带，只留中心峰
    for c in (200.0 - k * 5.0, 200.0 + k * 5.0):
        a0[np.abs(f0 - c) < 1.5] = 0.004
r0 = vib.gear_sideband_verdict(f0, a0, 200.0, [("转频", 5.0), ("GMF/3", 66.7)])
check(r0.get("match") is None or len(r0.get("hits") or []) < 2,
      f"无边带时不判命中（match={r0.get('match')}, hits={len(r0.get('hits') or [])}）")

print("[阴性：候选对不上时如实报未对上]")
f1, a1 = spec_curve(300.0, 12.0)
r1 = vib.gear_sideband_verdict(f1, a1, 300.0, [("错误候选", 40.0)])
check(r1.get("match") is None, f"候选差太远 → 不硬套（match={r1.get('match')}）")

print("[严重度分级口径]")
check(abs(vib.GEAR_WARN_RATIO - 0.30) < 1e-9, f"警告阈值 0.30（{vib.GEAR_WARN_RATIO}）")
check(abs(vib.GEAR_WATCH_RATIO - 0.12) < 1e-9, f"关注阈值 0.12（{vib.GEAR_WATCH_RATIO}）")

print()
failed = [x for x in RESULTS if not x]
print(f"共 {len(RESULTS)} 项断言，失败 {len(failed)} 项")
print("RESULT:", "ALL PASS" if not failed else "FAIL")
