"""回归测试：磨粒分级 wear_verdict 与报告限值同源。

背景：磨粒报警/预警阈值原先在两处各写一遍——
  REPORT_LIMITS（报告表格判定用 _judge_max）与 analyze_wear 里的字面量 20/25/15/20。
改一处就导致"同一份报告里表格与结论不一致"。现改为只从 REPORT_LIMITS 取值。

本测试做两件事：
  1. 等价性：用**原字面量逻辑**做参照，在全网格上比对，证明重构没改变任何判定；
  2. 同源性：改 REPORT_LIMITS，判定结果必须随之改变（说明没有残留硬编码）。

运行：python tests/test_wear_limits.py
"""
import sys
from pathlib import Path
import importlib.util

ROOT = Path(__file__).resolve().parents[1]          # oil-analyzer/
spec = importlib.util.spec_from_file_location("oil", ROOT / "oil_monitor_gui.py")
oil = importlib.util.module_from_spec(spec)
spec.loader.exec_module(oil)

RESULTS = []


def check(cond, msg):
    RESULTS.append((bool(cond), msg))
    print(("  PASS  " if cond else "  FAIL  ") + msg)


def legacy_verdict(b7, g7):
    """重构前的原始逻辑（字面量 20/25/15/20），作为等价性参照。"""
    if b7 < 1 and g7 < 1:
        return "none"
    if (b7 > 1 or g7 > 1) and (b7 < 20 and g7 < 15):
        return "low"
    if b7 > 25 or g7 > 20:
        return "alarm"
    if b7 > 20 or g7 > 15:
        return "warn"
    return "other"


# 1. 全网格等价性（含边界值）
print("[等价性：与旧字面量逻辑逐点比对]")
grid = [i * 0.5 for i in range(0, 71)]        # 0 ~ 35，步长 0.5
mismatch = []
for b7 in grid:
    for g7 in grid:
        a = oil.wear_verdict(b7, g7)
        b = legacy_verdict(b7, g7)
        if a != b:
            mismatch.append((b7, g7, a, b))
check(not mismatch,
      f"{len(grid)**2} 个网格点全部一致" + ("" if not mismatch else f"，不一致 {len(mismatch)} 处，例: {mismatch[:3]}"))

# 2. 关键边界点单独点名
print("[边界点]")
cases = [
    ((0.5, 0.5), "none"), ((2, 2), "low"),
    ((19.9, 14.9), "low"), ((20, 5), "other"), ((20.1, 5), "warn"),
    ((25, 5), "warn"), ((25.1, 5), "alarm"),
    ((5, 15), "other"), ((5, 15.1), "warn"), ((5, 20), "warn"), ((5, 20.1), "alarm"),
    ((30, 30), "alarm"),
]
bad = [(bg, oil.wear_verdict(*bg), want) for bg, want in cases if oil.wear_verdict(*bg) != want]
check(not bad, "12 个边界点判定符合预期" + ("" if not bad else f"，异常: {bad}"))

# 3. 同源性：改 REPORT_LIMITS，判定必须跟着变
print("[同源性：REPORT_LIMITS 是唯一来源]")
saved = dict(oil.REPORT_LIMITS)
try:
    oil.REPORT_LIMITS.clear()
    oil.REPORT_LIMITS.update({"ferrous": (10.0, 12.0), "nonferrous": (8.0, 10.0)})
    check(oil.wear_verdict(11, 5) == "warn", "收紧限值后 11 变成预警（原为 low）")
    check(oil.wear_verdict(12.5, 5) == "alarm", "收紧限值后 12.5 变成报警")
    check(oil.wear_verdict(9, 5) == "low", "收紧限值后 9 仍是低速率")
    check(oil.wear_verdict(21, 5) == "alarm", "原 21 为预警，收紧后应为报警")
finally:
    oil.REPORT_LIMITS.clear()
    oil.REPORT_LIMITS.update(saved)

# 4. 恢复后行为回到原样
check(oil.wear_verdict(21, 5) == "warn", "还原 REPORT_LIMITS 后判定恢复")
check(oil.REPORT_LIMITS == {"ferrous": (20.0, 25.0), "nonferrous": (15.0, 20.0)},
      "REPORT_LIMITS 未被测试破坏")

# 5. analyze_wear 源码里不应再出现这些阈值字面量
print("[无残留字面量]")
import inspect, re
src = inspect.getsource(oil.analyze_wear)
code_only = "\n".join(line.split("#", 1)[0] for line in src.splitlines())   # 忽略注释里的示例数字
nums = re.findall(r"(?<![\w.])(15|20|25)(?![\w.])", code_only)
check(not nums, f"analyze_wear 代码部分无 15/20/25 字面量（实际 {nums}）")

print()
failed = [m for ok, m in RESULTS if not ok]
print(f"共 {len(RESULTS)} 项断言，失败 {len(failed)} 项")
for m in failed:
    print("  FAILED:", m)
print("RESULT:", "ALL PASS" if not failed else "FAILED")
sys.exit(0 if not failed else 1)
