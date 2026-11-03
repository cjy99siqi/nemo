"""回归测试：时间文本解析（不补零 / 中文分隔 / ISO），以及"丢行"不再静默。

背景：parse_datetime_text 原先只认零填充格式，现场导出的 `2026/9/5 8:05`
被判为无效直接丢行；丢光后 analyze_wear 的 days 回落到 28，浓度口径随之变化，
而整个过程没有任何提示。另有 _wear_time 是它的残缺副本（少认 %Y/%m/%d）。

运行：python tests/test_time_parse.py
"""
import sys
from datetime import datetime
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


print("[能解析的写法]")
cases = {
    "2026-09-05 08:05:00": datetime(2026, 9, 5, 8, 5, 0),
    "2026/09/05 08:05:00": datetime(2026, 9, 5, 8, 5, 0),
    "2026-09-05 08:05": datetime(2026, 9, 5, 8, 5),
    "2026-09-05": datetime(2026, 9, 5),
    "2026/9/5 8:05": datetime(2026, 9, 5, 8, 5),          # 不补零（原实现失败）
    "2026/9/5": datetime(2026, 9, 5),                      # 不补零（原实现失败）
    "2026-9-5 8:5:3": datetime(2026, 9, 5, 8, 5, 3),       # 时分秒都不补零
    "2026.9.5 8:05": datetime(2026, 9, 5, 8, 5),           # 点号分隔
    "2026年9月5日 8:05": datetime(2026, 9, 5, 8, 5),        # 中文分隔
    "2026年9月5日": datetime(2026, 9, 5),
    "2026-09-05T08:05:00": datetime(2026, 9, 5, 8, 5, 0),  # ISO
    "2026-09-05 08:05:00.123456": datetime(2026, 9, 5, 8, 5, 0, 123456),
}
for text, want in cases.items():
    got = oil.parse_datetime_text(text)
    check(got == want, f"'{text}' -> {got}")

print("[无效输入]")
oil.PARSE_STATS["unparsed"] = 0
check(oil.parse_datetime_text("") is None, "空串 -> None 且不计数")
check(oil.PARSE_STATS["unparsed"] == 0, "空串不增加 unparsed")
for bad in ("不是时间", "2026-13-45", "2026/9/5 25:00"):
    check(oil.parse_datetime_text(bad) is None, f"'{bad}' -> None")
check(oil.PARSE_STATS["unparsed"] == 3, f"无效输入计数 = 3（实际 {oil.PARSE_STATS['unparsed']}）")

print("[_wear_time 与 parse_datetime_text 同源]")
same = all(oil._wear_time(t) == want for t, want in cases.items())
check(same, "所有格式 _wear_time 结果一致（不再缺 %Y/%m/%d）")

print("[analyze_wear：非补零日期能算出真实天数]")
head = ["时间"] + ["c%d" % i for i in range(10)]
rows = [head,
        ["2026/9/5 8:05"] + [0, 0, 0, 0, 0, 0, 0, 0, 0, 1],
        ["2026/9/7 9:00"] + [0, 0, 0, 0, 0, 0, 0, 0, 0, 5],
        ["2026/9/9 7:30"] + [0, 0, 0, 0, 0, 0, 0, 0, 0, 9]]
a = oil.analyze_wear(rows)
check(a["days"] == 5, f"9/5–9/9 含首尾应为 5 天（实际 {a['days']}）")
check(a["days_estimated"] is False, "days_estimated=False（用的是真实首末日）")

print("[analyze_wear：时间全坏时标记估算，不再静默]")
oil.PARSE_STATS["unparsed"] = 0
rows_bad = [head,
            ["坏时间1"] + [0, 0, 0, 0, 0, 0, 0, 0, 0, 1],
            ["坏时间2"] + [0, 0, 0, 0, 0, 0, 0, 0, 0, 5],
            ["坏时间3"] + [0, 0, 0, 0, 0, 0, 0, 0, 0, 9]]
b = oil.analyze_wear(rows_bad)
check(b["days"] == 28, f"回落默认 28 天（实际 {b['days']}）")
check(b["days_estimated"] is True, "days_estimated=True（报告侧可据此提示）")
check(oil.PARSE_STATS["unparsed"] == 3, f"计数到 3 处无法解析（实际 {oil.PARSE_STATS['unparsed']}）")

print()
failed = [m for ok, m in RESULTS if not ok]
print(f"共 {len(RESULTS)} 项断言，失败 {len(failed)} 项")
for m in failed:
    print("  FAILED:", m)
print("RESULT:", "ALL PASS" if not failed else "FAILED")
sys.exit(0 if not failed else 1)
