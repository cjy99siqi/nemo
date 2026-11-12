# -*- coding: utf-8 -*-
"""判读复核表：agg + fault_info → CSV（Excel 直接打开、列齐全）。"""
import io
import os
import shutil
import importlib.util

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("vib", os.path.join(ROOT, "振动分析.py"))
vib = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vib)

RESULTS = []


def check(ok, msg):
    RESULTS.append(bool(ok))
    print(("  PASS  " if ok else "  FAIL  ") + msg)


agg = {
    "2#": {
        "发电机前轴承径向": {"grade": "警告", "fault_lab": "BPFO×1 61.0Hz 幅值 0.52，近 5 次中 3 次命中",
                             "gear_lab": "", "csv": "/x.csv", "ts": "2026-06-11T07:04:50"},
        "齿轮箱一级齿圈径向": {"grade": "关注", "gear_lab": "GMF/3，边带/主峰 0.18"},
    },
    "1#": {
        "主轴承前轴径向": {"grade": "正常"},
    },
}
fi = {
    ("2#", "发电机前轴承径向"): {
        "level": "警告", "alarm": True, "bearing": "6332M C4", "label": "BPFO×1",
        "hz": 61.03, "amp": 0.5215, "thr": 0.5, "hits_n": 3, "files_n": 5,
        "weak": False, "conflict": "", "runner": "6334M C3 BPFI×1",
        "ts": "2026-06-11T07:04:50", "fs": 25600.0, "demod": (1000.0, 8000.0),
        "csv": "/x.csv",
    },
    ("2#", "齿轮箱一级齿圈径向"): {"level": "关注", "amp": 0.1, "thr": 0.2, "files_n": 5},
}

print("[行整理]")
rows = vib.review_rows_from(agg, fi)
check(len(rows) == 3, f"每个机组/测点一行（{len(rows)}）")
check([r["机组"] for r in rows] == ["1#", "2#", "2#"], f"按机组排序（{[r['机组'] for r in rows]}）")
r = [x for x in rows if x["测点"].startswith("发电机")][0]
check(r["等级"] == "警告", "等级带出来")
check(r["轴承"] == "6332M C4" and r["阶次"] == "BPFO×1", "轴承/阶次带出来")
check(r["频率(Hz)"] == "61.0" and r["幅值"] == "0.521" and r["阈值"] == "0.500",
      f"数值格式（{r['频率(Hz)']}/{r['幅值']}/{r['阈值']}）")
check(r["复现(命中/回看)"] == "3/5", f"复现次数（{r['复现(命中/回看)']}）")
check(r["候选(需复核)"] == "6334M C3 BPFI×1", "候选轴承带出来")
check(r["采样率(Hz)"] == "25600" and r["解调带(Hz)"] == "1000–8000", "分析参数带出来")
check(r["文件时间"] == "2026-06-11 07:04:50", f"文件时间（{r['文件时间']}）")
check("BPFO×1" in r["判读说明"], "判读说明带出来")
g = [x for x in rows if x["测点"].startswith("齿轮箱")][0]
check("GMF/3" in g["齿轮结论"], "齿轮结论带出来")

print("[CSV 写出]")
d = os.path.join(ROOT, ".tmptest", "review")
shutil.rmtree(d, ignore_errors=True)
os.makedirs(d)
p = os.path.join(d, "复核表.csv")
n = vib.write_review_csv(p, rows)
check(n == 3, f"写入 3 行（{n}）")
raw = io.open(p, "rb").read()
check(raw.startswith(b"\xef\xbb\xbf"), "UTF-8 BOM（Excel 双击不乱码）")
text = raw.decode("utf-8-sig")
lines = text.splitlines()
check(lines[0].split(",")[0] == "机组" and "解调带(Hz)" in lines[0], "表头列齐全")
check(len(lines) == 4, f"表头 + 3 行（{len(lines)}）")
check("6332M C4" in text and "1000–8000" in text, "内容写入")

print("[空数据]")
check(vib.review_rows_from({}, {}) == [], "空 agg 返回空表")
conn = vib.db_connect(d)
conn.close()
check(vib.report_review_rows(d, None, None, "测试") == [], "库里没数据时返回空表")

shutil.rmtree(d, ignore_errors=True)

print()
failed = [x for x in RESULTS if not x]
print(f"共 {len(RESULTS)} 项断言，失败 {len(failed)} 项")
print("RESULT:", "ALL PASS" if not failed else "FAIL")
