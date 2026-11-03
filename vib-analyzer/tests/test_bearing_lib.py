"""回归测试：轴承库 JSON 加载（load_bearing_lib）。

覆盖：文件缺失、覆盖已有轴承、新增轴承、非法 shaft、非法数字、
缺 bearings 键、JSON 损坏。每个用例前后都恢复 BEARING_LIB，避免互相污染。
运行：python tests/test_bearing_lib.py
"""
import json
import sys
import tempfile
from pathlib import Path
import importlib.util

ROOT = Path(__file__).resolve().parents[1]          # vib-analyzer/
spec = importlib.util.spec_from_file_location("vib", ROOT / "振动分析.py")
vib = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vib)

RESULTS = []


def check(cond, msg):
    RESULTS.append((bool(cond), msg))
    print(("  PASS  " if cond else "  FAIL  ") + msg)


def with_lib(fn):
    """在 BEARING_LIB 的副本上跑一个用例，结束后还原并清空 warnings。"""
    saved = {k: (v[0], dict(v[1])) for k, v in vib.BEARING_LIB.items()}
    vib.BEARING_LIB_WARNINGS.clear()
    try:
        return fn()
    finally:
        vib.BEARING_LIB.clear()
        vib.BEARING_LIB.update(saved)
        vib.BEARING_LIB_WARNINGS.clear()


def write_tmp(doc, raw=None):
    f = Path(tempfile.mkdtemp()) / "轴承库.json"
    if raw is not None:
        f.write_text(raw, encoding="utf-8")
    else:
        f.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return f


EXAMPLE = ROOT / "数据" / "轴承库.example.json"
example_doc = json.loads(EXAMPLE.read_text(encoding="utf-8"))
FIRST = next(iter(example_doc["bearings"]))
FIRST_SHAFT = example_doc["bearings"][FIRST]["shaft"]
orig_mult = dict(vib.BEARING_LIB[FIRST][1])

print(f"示例库条目: {len(example_doc['bearings'])}  首条: {FIRST} ({FIRST_SHAFT})")
print()

# 1. 文件缺失 → 静默用内置库
def case_missing():
    path = Path(tempfile.mkdtemp()) / "不存在.json"
    added, over, warns = vib.load_bearing_lib(path)
    check((added, over, warns) == (0, 0, []), "文件缺失：返回 (0,0,[])，不产生 warning")
    check(vib.BEARING_LIB[FIRST][1] == orig_mult, "文件缺失：内置库未被改动")

# 2. 覆盖 + 新增
def case_override_add():
    doc = {"version": 1, "bearings": {
        FIRST: {"shaft": FIRST_SHAFT, "BPFI": 99.9},
        "测试新轴承 X": {"shaft": "H", "BPFO": 3.03, "BSF": 1.5},
    }}
    added, over, warns = vib.load_bearing_lib(write_tmp(doc))
    check((added, over, warns) == (1, 1, []), f"覆盖+新增：计数 (1,1,[])，实际 {(added, over, warns)}")
    check(vib.BEARING_LIB[FIRST][1] == {"BPFI": 99.9}, "覆盖：该轴承倍数整体替换为文件内容")
    check(vib.BEARING_LIB["测试新轴承 X"] == ("H", {"BPFO": 3.03, "BSF": 1.5}), "新增：条目与轴号正确")

# 3. 非法 shaft
def case_bad_shaft():
    doc = {"bearings": {"坏轴轴承": {"shaft": "X", "BPFI": 1.0}}}
    added, over, warns = vib.load_bearing_lib(write_tmp(doc))
    check(added == 0 and len(warns) == 1, f"非法 shaft：不新增，产生 1 条 warning（实际 {warns}）")
    check("坏轴轴承" not in vib.BEARING_LIB, "非法 shaft：未写入库")

# 4. 非法数字（只跳过该字段，其余生效）
def case_bad_number():
    doc = {"bearings": {"半坏轴承": {"shaft": "M", "BPFI": "abc", "BPFO": 5.5}}}
    added, over, warns = vib.load_bearing_lib(write_tmp(doc))
    check(added == 1, "非法数字：条目仍按有效字段新增")
    check(vib.BEARING_LIB["半坏轴承"] == ("M", {"BPFO": 5.5}), "非法数字：只跳过 BPFI，BPFO 生效")
    check(len(warns) == 1 and "BPFI" in warns[0], f"非法数字：warning 指明字段（实际 {warns}）")

# 4.5 带 BOM（记事本 / PowerShell Set-Content -Encoding UTF8 的常见产物）
def case_bom():
    f = Path(tempfile.mkdtemp()) / "轴承库.json"
    f.write_text(json.dumps({"bearings": {"BOM轴承": {"shaft": "M", "BPFI": 7.7}}},
                            ensure_ascii=False), encoding="utf-8-sig")
    assert f.read_bytes()[:3] == b"\xef\xbb\xbf", "用例前提：文件确实带 BOM"
    added, over, warns = vib.load_bearing_lib(f)
    check(added == 1 and not warns,
          f"带 BOM 的 JSON 能正常读取（added={added}, warns={warns}）")

# 5. 缺 bearings 键
def case_missing_key():
    added, over, warns = vib.load_bearing_lib(write_tmp({"version": 1}))
    check((added, over) == (0, 0) and len(warns) == 1, f"缺 bearings 键：返回 (0,0) + 1 warning（实际 {warns}）")

# 6. JSON 损坏
def case_broken_json():
    added, over, warns = vib.load_bearing_lib(write_tmp(None, raw="{ 坏掉的 json "))
    check((added, over) == (0, 0) and len(warns) == 1, f"JSON 损坏：不抛异常，返回 1 warning（实际 {warns}）")

# 7. 全空倍数 → 跳过
def case_no_mult():
    doc = {"bearings": {"空倍数轴承": {"shaft": "L"}}}
    added, over, warns = vib.load_bearing_lib(write_tmp(doc))
    check(added == 0 and len(warns) == 1, f"无有效倍数：跳过并告警（实际 {warns}）")

for fn in (case_missing, case_override_add, case_bad_shaft, case_bad_number, case_bom,
           case_missing_key, case_broken_json, case_no_mult):
    print(f"[{fn.__name__}]")
    with_lib(fn)

print()
failed = [m for ok, m in RESULTS if not ok]
print(f"共 {len(RESULTS)} 项断言，失败 {len(failed)} 项")
print("RESULT:", "ALL PASS" if not failed else "FAILED")
sys.exit(0 if not failed else 1)
