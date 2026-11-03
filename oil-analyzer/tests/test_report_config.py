"""回归测试：报告配置加载与机组台数决策（load_report_config / report_unit_count）。

背景：原先"营盘梁/岱海按 75 台出报告"是写死的（oil_monitor_gui.py:2639），
项目名改一个字就失效；templates/*_报告配置.json 存在却从未被读取。
现在改为配置优先、历史规则兜底。

运行：python tests/test_report_config.py
"""
import json
import sys
import tempfile
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


def make_dir(files):
    d = Path(tempfile.mkdtemp())
    for name, doc in files.items():
        if isinstance(doc, str):
            (d / name).write_text(doc, encoding="utf-8")
        else:
            (d / name).write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return d


# 1. 真实仓库里已有的两份配置能被匹配到
def case_real_configs():
    d = ROOT / "templates"
    for proj, want in [("岱海一标营盘梁风电场", 75), ("京能岱海旺海装风电场", 75)]:
        n, cfg = oil.report_unit_count(proj, d)
        check(cfg is not None, f"真实配置命中：{proj} -> {cfg and cfg.get('project')}")
        check(n == want, f"真实配置 unit_count={n}（期望 {want}）")
    cfg = oil.load_report_config("营盘梁", d)
    check(cfg is not None and cfg.get("style") == "鑫世达", "按文件名前缀匹配 营盘梁（style=鑫世达）")


# 2. 按 project 字段匹配 + unit_count 生效
def case_by_field():
    d = make_dir({"甲项目_报告配置.json": {"project": "某某风电场", "unit_count": 40}})
    n, cfg = oil.report_unit_count("某某风电场二期", d)
    check(n == 40, f"project 字段包含匹配 → unit_count={n}（期望 40）")
    check(cfg and cfg["_path"].endswith("甲项目_报告配置.json"), "返回配置带 _path")


# 3. 按文件名前缀匹配
def case_by_filename():
    d = make_dir({"乙项目_报告配置.json": {"project": "完全不相干的名字", "unit_count": 12}})
    n, _ = oil.report_unit_count("乙项目风电场", d)
    check(n == 12, f"文件名前缀匹配 → unit_count={n}（期望 12）")


# 4. 无配置时历史规则兜底
def case_fallback():
    d = make_dir({})
    n1, cfg1 = oil.report_unit_count("岱海一标营盘梁风电场", d)
    n2, _ = oil.report_unit_count("宾泉", d)
    check(n1 == 75 and cfg1 is None, f"无配置时 营盘梁/岱海 兜底 75（实际 {n1}）")
    check(n2 == 0, f"无配置时其它项目 0 台（实际 {n2}）")


# 5. unit_count 非法时回落到兜底
def case_bad_count():
    for bad in (None, "", "abc", 0, -3):
        d = make_dir({"丙_报告配置.json": {"project": "丙项目", "unit_count": bad}})
        n, cfg = oil.report_unit_count("丙项目", d)
        check(n == 0 and cfg is not None,
              f"unit_count={bad!r} 非法 → 用兜底 0（实际 {n}），配置本身仍被识别")


# 6. BOM 容忍
def case_bom():
    d = Path(tempfile.mkdtemp())
    (d / "丁_报告配置.json").write_text(
        json.dumps({"project": "丁项目", "unit_count": 9}), encoding="utf-8-sig")
    n, _ = oil.report_unit_count("丁项目", d)
    check(n == 9, f"带 BOM 的配置能读（unit_count={n}）")


# 7. 坏 JSON 被跳过，不影响后续文件
def case_broken():
    d = Path(tempfile.mkdtemp())
    (d / "坏_报告配置.json").write_text("{ 不是 json", encoding="utf-8")
    (d / "好_报告配置.json").write_text(
        json.dumps({"project": "目标项目", "unit_count": 21}, ensure_ascii=False), encoding="utf-8")
    n, cfg = oil.report_unit_count("目标项目", d)
    check(n == 21, f"坏 JSON 被跳过，好配置仍生效（unit_count={n}）")


for fn in (case_real_configs, case_by_field, case_by_filename, case_fallback,
           case_bad_count, case_bom, case_broken):
    print(f"[{fn.__name__}]")
    fn()

print()
failed = [m for ok, m in RESULTS if not ok]
print(f"共 {len(RESULTS)} 项断言，失败 {len(failed)} 项")
for m in failed:
    print("  FAILED:", m)
print("RESULT:", "ALL PASS" if not failed else "FAILED")
sys.exit(0 if not failed else 1)
