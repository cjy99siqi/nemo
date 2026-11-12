# -*- coding: utf-8 -*-
"""同一测点切换数据：不带上一份的基频/标线（标注按“测点 + 记录时间”存）。"""
import os
import io
import json
import shutil
import datetime
import importlib.util

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("vib", os.path.join(ROOT, "振动分析.py"))
vib = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vib)
SW = vib.SpectrumWindow

RESULTS = []


def check(ok, msg):
    RESULTS.append(bool(ok))
    print(("  PASS  " if ok else "  FAIL  ") + msg)


d = os.path.join(ROOT, ".tmptest", "annot")
shutil.rmtree(d, ignore_errors=True)
os.makedirs(d)
p = os.path.join(d, "案.json")


class S:
    _load_point_annotations = SW._load_point_annotations
    _point_key = SW._point_key

    def __init__(self, dt, active=None):
        self.info = {"project": "田家寨", "unit": "113#", "point": "发电机_后轴承径向", "dt": dt}
        self.csv_path = os.path.join(d, "x.csv")
        self.active_mark_x = active
        self._single_start_t = None
        self._freq_confirmed = False
        self.manual_marks = []
        self._bandwidth_regions = []
        self._base_colors = {}
        self._sideband_params = {}

    def _annot_path(self):
        return p


A = S(datetime.datetime(2026, 6, 15, 19, 3, 15), active=123.4)
B = S(datetime.datetime(2026, 6, 16, 8, 0, 0))
keyA = A._point_key()
json.dump({"points": {keyA: {
    "active_mark_x": 123.4,
    "single_start_t": 1.5,
    "freq_confirmed": True,
    "manual_marks": [[50.0, "f0", 1, 2.0]],
    "bandwidth_regions": [],
    "base_colors": {"50.0": "#ff0000"},
    "sideband_params": {"50.0": 2.0},
}}}, io.open(p, "w", encoding="utf-8"))

print("[同一测点，不同记录]")
check(keyA != B._point_key(), "两份记录的标注键不同（含采集时间）")
B._load_point_annotations()
check(B.active_mark_x is None, f"换数据后不带上一份的基频（{B.active_mark_x}）")
check(B.manual_marks == [], f"换数据后不带上一份的标线（{B.manual_marks}）")
check(B._freq_confirmed is False, "换数据后不继承“基频已确认”")

print("[回到原记录仍能恢复]")
A._load_point_annotations()
check(A.active_mark_x == 123.4, f"原记录恢复基频（{A.active_mark_x}）")
check(len(A.manual_marks) == 1, "原记录恢复标线")
check(A._freq_confirmed is True, "原记录恢复确认状态")

shutil.rmtree(d, ignore_errors=True)

print()
failed = [x for x in RESULTS if not x]
print(f"共 {len(RESULTS)} 项断言，失败 {len(failed)} 项")
print("RESULT:", "ALL PASS" if not failed else "FAIL")
