"""回归测试：磨损 CSV 的 b7/g7 落库（wear_records + Scanner 集成点）。

背景：b7/g7 只在报告链路里算，界面表格看不到磨粒判定。
现在 Scanner 解析磨损 CSV 时额外产出 wear_ferrous / wear_nonferrous 两条 records，
数值来自 analyze_wear，状态来自 judge（同一套 REPORT_LIMITS）。

运行：python tests/test_wear_records.py
"""
import sys
import tempfile
from pathlib import Path
import importlib.util

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("oil", ROOT / "oil_monitor_gui.py")
oil = importlib.util.module_from_spec(spec)
spec.loader.exec_module(oil)

RESULTS = []


def check(cond, msg):
    RESULTS.append((bool(cond), msg))
    print(("  PASS  " if cond else "  FAIL  ") + msg)


BINS = ["40-59", "60-99", "100-299", "300-399", "≥400",
        "135-149", "150-249", "250-349", "350-449", "≥450"]
HEADER = ["时间", "上电时间"] + [
    "%s微米范围微粒数(%s)" % (b, "铁磁性" if i < 5 else "非铁磁性") for i, b in enumerate(BINS)
]


def write_wear_csv(dirpath, rows, name="机组#12_磨损.csv"):
    p = Path(dirpath) / name
    lines = [",".join(HEADER)]
    for t, vals in rows:
        lines.append(",".join([t, t] + [str(v) for v in vals]))
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


d = Path(tempfile.mkdtemp())
rows_ok = [
    ("2026/9/5 8:05", [0] * 10),
    ("2026/9/7 9:00", [100] * 10),
    ("2026/9/9 7:30", [200] * 10),
]
csv_ok = write_wear_csv(d, rows_ok)
vpath = "某项目/机组#12_磨损.csv"

print("[分类]")
check(oil.is_wear_csv(vpath), "文件名 磨损.csv 识别为磨损文件")
check(oil.is_wear_csv("项目/Oil_机组#3_2026-09.csv"), "Oil 开头合并文件识别为磨损文件")
check(not oil.is_wear_csv("项目/机组#3_油品分析.xlsx"), "普通工作簿不算磨损文件")

print("[wear_records 产出]")
recs = oil.wear_records(str(csv_ok), vpath)
check(len(recs) == 2, f"产出 2 条记录（实际 {len(recs)}）")
by_param = {r["param"]: r for r in recs}
check(set(by_param) == {"wear_ferrous", "wear_nonferrous"}, f"参数键正确：{sorted(by_param)}")
for key in ("wear_ferrous", "wear_nonferrous"):
    r = by_param.get(key, {})
    check(r.get("unit") == "mg/kg", f"{key} 单位 mg/kg")
    check(r.get("value", 0) > 0, f"{key} 数值为正（{r.get('value')}）")
    check(r.get("status") == oil.judge(key, r.get("value")),
          f"{key} 状态由 judge 决定（{r.get('status')}）")
    check(r.get("date") == "2026-09-09", f"{key} 日期取末次采集日（{r.get('date')}）")
check(by_param["wear_ferrous"]["device"] == oil.guess_device(vpath),
      f"设备名与常规文件同源（{by_param['wear_ferrous']['device']}）")

print("[与报告数值一致]")
a = oil.analyze_wear(oil.load_wear_csv(str(csv_ok)))
check(abs(by_param["wear_ferrous"]["value"] - round(a["b7"], 4)) < 1e-9, "记录的 b7 == analyze_wear 的 b7")
check(abs(by_param["wear_nonferrous"]["value"] - round(a["g7"], 4)) < 1e-9, "记录的 g7 == analyze_wear 的 g7")

print("[坏文件不影响扫描]")
bad = d / "机组#13_磨损.csv"
bad.write_text("这不是CSV数据", encoding="utf-8")
check(oil.wear_records(str(bad), "项目/机组#13_磨损.csv") == [], "损坏文件返回 []，不抛异常")

print("[状态随阈值联动]")
_orig = oil.analyze_wear
try:
    oil.analyze_wear = lambda rows: {"b7": 30.0, "g7": 5.0, "t1": None, "t0": None,
                                     "ym_trend": "2026.09"}
    fake = {r["param"]: r for r in oil.wear_records(str(csv_ok), vpath)}
    check(fake["wear_ferrous"]["status"] == "异常", f"b7=30 判为异常（实际 {fake['wear_ferrous']['status']}）")
    check(fake["wear_nonferrous"]["status"] == "正常", f"g7=5 判为正常（实际 {fake['wear_nonferrous']['status']}）")
    check(fake["wear_ferrous"]["date"] == "2026-09-01", f"无采集日时退回月份首日（实际 {fake['wear_ferrous']['date']}）")
finally:
    oil.analyze_wear = _orig

print("[落库：replace_records 后能查到]")
db = Path(tempfile.mkdtemp()) / "t.db"
store = oil.Store(str(db))
try:
    info = {"real_path": str(csv_ok), "size": 1, "mtime": 1.0, "status": "ok", "error": "", "sheets": []}
    store.replace_records(vpath, "某项目", recs, info)
    n = store.conn.execute("SELECT COUNT(*) FROM records WHERE vpath=?", (vpath,)).fetchone()[0]
    check(n == 2, f"records 表里 2 行（实际 {n}）")
    got = {r["param"]: r["value"] for r in store.conn.execute(
        "SELECT param,value FROM records WHERE vpath=?", (vpath,)).fetchall()}
    check(abs(got.get("wear_ferrous", -1) - by_param["wear_ferrous"]["value"]) < 1e-9,
          "库里的 wear_ferrous 数值一致")
    # 重复 replace 不应翻倍（按 vpath 整批替换）
    store.replace_records(vpath, "某项目", recs, info)
    n2 = store.conn.execute("SELECT COUNT(*) FROM records WHERE vpath=?", (vpath,)).fetchone()[0]
    check(n2 == 2, f"重复写入后仍是 2 行（实际 {n2}），不会累积")
finally:
    store.conn.close()

print()
failed = [m for ok, m in RESULTS if not ok]
print(f"共 {len(RESULTS)} 项断言，失败 {len(failed)} 项")
for m in failed:
    print("  FAILED:", m)
print("RESULT:", "ALL PASS" if not failed else "FAILED")
sys.exit(0 if not failed else 1)
