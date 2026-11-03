"""回归测试：磨粒指标进入 PARAMS，且限值只来自 REPORT_LIMITS。

背景：b7/g7（铁磁/非铁磁磨粒，mg/kg）原先只存在于报告链路，
PARAMS 里没有对应参数，界面既看不到、也无法判定。
现在注册为 wear_ferrous / wear_nonferrous，阈值直接取 REPORT_LIMITS。

运行：python tests/test_params_limits.py
"""
import sys
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


print("[参数注册]")
for key, lim_key in (("wear_ferrous", "ferrous"), ("wear_nonferrous", "nonferrous")):
    p = oil.PARAMS.get(key)
    check(p is not None, f"{key} 已注册")
    if not p:
        continue
    warn, alert = oil.REPORT_LIMITS[lim_key]
    check((p["warn"], p["alert"]) == (warn, alert),
          f"{key} 限值 = REPORT_LIMITS[{lim_key}] = ({warn}, {alert})，实际 ({p['warn']}, {p['alert']})")
    check(p["unit"] == "mg/kg", f"{key} 单位是 mg/kg（实际 {p['unit']}）")
    check(p["group"] == "wear", f"{key} 归入 wear 组")

print("[判定边界]")
cases = [
    ("wear_ferrous", 19.9, "正常"), ("wear_ferrous", 20.0, "关注"),
    ("wear_ferrous", 24.9, "关注"), ("wear_ferrous", 25.0, "异常"),
    ("wear_nonferrous", 14.9, "正常"), ("wear_nonferrous", 15.0, "关注"),
    ("wear_nonferrous", 19.9, "关注"), ("wear_nonferrous", 20.0, "异常"),
]
bad = [(k, v, oil.judge(k, v), want) for k, v, want in cases if oil.judge(k, v) != want]
check(not bad, f"8 个边界点判定正确" + ("" if not bad else f"，异常: {bad}"))

print("[界面展示文本]")
t1, t2 = oil.limit_text("wear_ferrous"), oil.limit_text("wear_nonferrous")
check("≤" in t1 and "25" in t1 and "mg/kg" in t1, f"铁磁磨粒限值文本含 ≤25 mg/kg（实际 '{t1}'）")
check("≤" in t2 and "20" in t2 and "mg/kg" in t2, f"非铁磁磨粒限值文本含 ≤20 mg/kg（实际 '{t2}'）")
check(oil.param_name("wear_ferrous") == "铁磁磨粒", "参数名正确")

print("[表头识别]")
for header, want in (("铁磁磨粒", "wear_ferrous"), ("铁磁性磨粒", "wear_ferrous"),
                     ("非铁磁磨粒", "wear_nonferrous"), ("B7", "wear_ferrous"),
                     ("G7", "wear_nonferrous")):
    got = oil.identify_param(header)
    check(got == want, f"identify_param('{header}') = {got}（期望 {want}）")

print("[单一来源：改 REPORT_LIMITS 后判定随动]")
saved = dict(oil.REPORT_LIMITS)
try:
    oil.REPORT_LIMITS.update({"ferrous": (10.0, 12.0)})
    oil.PARAMS["wear_ferrous"]["warn"], oil.PARAMS["wear_ferrous"]["alert"] = 10.0, 12.0  # 模拟重新注册
    check(oil.judge("wear_ferrous", 11.0) == "关注", "收紧后 11 变关注")
finally:
    oil.REPORT_LIMITS.clear(); oil.REPORT_LIMITS.update(saved)
    oil.PARAMS["wear_ferrous"]["warn"], oil.PARAMS["wear_ferrous"]["alert"] = 20.0, 25.0
check(oil.judge("wear_ferrous", 11.0) == "正常", "还原后 11 恢复正常")

print()
failed = [m for ok, m in RESULTS if not ok]
print(f"共 {len(RESULTS)} 项断言，失败 {len(failed)} 项")
for m in failed:
    print("  FAILED:", m)
print("RESULT:", "ALL PASS" if not failed else "FAILED")
sys.exit(0 if not failed else 1)
