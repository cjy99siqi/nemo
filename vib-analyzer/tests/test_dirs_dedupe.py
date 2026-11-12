# -*- coding: utf-8 -*-
"""项目目录去重：父子目录同时登记不会把同一批 CSV 加载两遍。"""
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


D = vib.dedupe_project_dirs
P = r"D:\数据\五峰"
C = r"D:\数据\五峰\2026"
F = r"D:\数据\府谷\2026\06"

print("[目录去重]")
check(D([P, C]) == [P], f"父 + 子 → 只留父（{D([P, C])}）")
check(D([C, P]) == [P], f"子在前也收敛到父（{D([C, P])}）")
check(D([P, C, F]) == [P, F], f"无关目录保留（{D([P, C, F])}）")
check(D([P, P]) == [P], "重复项去掉")
check(D([C + "\\", P]) == [P], "尾部分隔符不影响判断")
check(D([]) == [], "空列表")
check(D([r"D:\数据\五峰2"]) == [r"D:\数据\五峰2"], "『五峰2』不算『五峰』的子目录")

print("[按 csv_path 去重]")
rows = [
    {"csv_path": r"D:\数据\五峰\a.csv", "rms": 1},
    {"csv_path": r"D:\数据\五峰\b.csv", "rms": 2},
    {"csv_path": r"D:\数据\五峰\a.csv", "rms": 3},
]
out = vib.dedupe_rows_by_path(rows)
check(len(out) == 2, f"同一路径只留一条（{len(out)}）")
check(any(r["csv_path"].endswith("a.csv") and r["rms"] == 3 for r in out), "后出现的覆盖前面的")
check(vib.dedupe_rows_by_path([]) == [], "空列表")

print()
failed = [x for x in RESULTS if not x]
print(f"共 {len(RESULTS)} 项断言，失败 {len(failed)} 项")
print("RESULT:", "ALL PASS" if not failed else "FAIL")
