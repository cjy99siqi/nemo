# -*- coding: utf-8 -*-
"""树形图：机型规定但当前没有数据的测点也要灰字占位显示（不计入勾选）。"""
import os
import tkinter as tk
from tkinter import ttk
import importlib.util

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("vib", os.path.join(ROOT, "振动分析.py"))
vib = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vib)
GUI = vib.VibGUI

RESULTS = []


def check(ok, msg):
    RESULTS.append(bool(ok))
    print(("  PASS  " if ok else "  FAIL  ") + msg)


PROJ = "中节能五峰北风垭风电场"
rows = []
for unit, pts in (("4", ["主轴轴承", "齿轮箱一级齿圈", "发电机前轴", "发电机后轴"]),
                  ("5", ["主轴轴承", "齿轮箱输入端", "齿轮箱一级齿圈",
                         "齿轮箱高速轴", "发电机前轴", "发电机后轴"])):
    for pt in pts:
        rows.append({"project": PROJ, "unit": unit, "point": pt,
                     "dt_date": "2026-06-01", "dt_ts": 1.0, "speed": 1200})


class Stub:
    build_tree = GUI.build_tree
    _expected_points = GUI._expected_points
    _refresh_check_marks = GUI._refresh_check_marks

    def __init__(self, root):
        self.tree = ttk.Treeview(root, columns=("check",), show="tree headings")
        self.tree.tag_configure("nodata", foreground="#9e9e9e")
        self.tree_node_map = {}
        self.checked_points = set()
        self.all_data = rows


print("[机型测点表]")
expect = GUI._expected_points(Stub.__new__(Stub), PROJ)
check(len(expect) == 6, f"五峰机型 6 个测点（{expect}）")
check(expect[0] == "主轴轴承" and expect[1] == "齿轮箱输入端", "顺序按机型库排列")

print("[树节点]")
root = tk.Tk(); root.withdraw()
s = Stub(root)
GUI.build_tree(s)

proj_iid = s.tree.get_children()[0]
units = {s.tree.item(u, "text"): u for u in s.tree.get_children(proj_iid)}
check(set(units) == {"4", "5"}, f"两个机组（{sorted(units)}）")

u4 = s.tree.get_children(units["4"])
texts4 = [s.tree.item(i, "text") for i in u4]
check(len(texts4) == 6, f"机组 4 显示 6 行（{texts4}）")
nodata4 = [s.tree.item(i, "text") for i in u4 if "nodata" in s.tree.item(i, "tags")]
check(nodata4 == ["齿轮箱输入端（无数据）", "齿轮箱高速轴（无数据）"],
      f"缺数据的两个测点灰字占位（{nodata4}）")
check(texts4[1] == "齿轮箱输入端（无数据）", "占位按机型顺序插在中间（不是堆在末尾）")

u5 = s.tree.get_children(units["5"])
check(len(u5) == 6, "机组 5 六个测点都有数据 → 6 行")
check(not any("nodata" in s.tree.item(i, "tags") for i in u5), "机组 5 没有灰字占位")
check(len(s.tree_node_map) == 10, f"可勾选节点 = 有数据的 10 行（{len(s.tree_node_map)}）")
check(all("（无数据）" not in k for k in s.tree_node_map), "占位行不进入勾选映射")

print("[机型名字和现场不同名：不按机型表占位]")
FG = "府谷"
fg_pts = ["主轴承_前轴径向", "主轴承_后轴径向", "齿轮箱_一级内齿圈径向", "齿轮箱_中部径向",
          "齿轮箱_高速轴径向", "齿轮箱_高速轴轴向", "发电机_前轴承径向", "发电机_前轴承轴向",
          "发电机_后轴承径向"]
rows2 = []
for unit, pts in (("101", fg_pts), ("102", fg_pts[:-1])):
    for pt in pts:
        rows2.append({"project": FG, "unit": unit, "point": pt,
                      "dt_date": "2026-06-01", "dt_ts": 1.0, "speed": 1500})
s2 = Stub(root)
s2.all_data = rows2
GUI.build_tree(s2)
proj2 = s2.tree.get_children()[0]
units2 = {s2.tree.item(u, "text"): u for u in s2.tree.get_children(proj2)}
t101 = [s2.tree.item(i, "text") for i in s2.tree.get_children(units2["101"])]
check(t101 == fg_pts, f"101# 只显示实际 9 个测点（{t101}）")
check(not any("行星轮" in t or "低速轴" in t for t in t101), "没有机型表里那堆同名字段")
t102 = [s2.tree.item(i, "text") for i in s2.tree.get_children(units2["102"])]
check(t102 == fg_pts[:-1] + ["发电机_后轴承径向（无数据）"],
      f"102# 缺 1 个测点 → 只补那 1 个占位（{t102[-2:]}）")
check(len(s2.tree_node_map) == 17, f"可勾选 17 行（{len(s2.tree_node_map)}）")

root.destroy()

print()
failed = [x for x in RESULTS if not x]
print(f"共 {len(RESULTS)} 项断言，失败 {len(failed)} 项")
print("RESULT:", "ALL PASS" if not failed else "FAIL")
