"""回归测试：数据\轴承库.json（由 tools\build_libs.py 生成）。

覆盖：
  1. 文件能被 load_bearing_lib 读入，不产生 warning；
  2. 每条都进了 BEARING_LIB，shaft 合法、倍数全为正；
  3. 手工挑的若干条，按「轴转频 × 倍数」算出的 Hz 与原表一致；
  4. 来自《C各机组振动诊断参数表》的条目，逐条对原表反算（五峰/明阳另有测试覆盖）。
运行：python tests/test_bearing_import.py
"""
import json
import sys
from pathlib import Path
import importlib.util

ROOT = Path(__file__).resolve().parents[1]          # vib-analyzer/
LIB = ROOT / "数据" / "轴承库.json"
C_XLS = Path(r"D:\振动\调试工具和文档\振动\C各机组振动诊断参数表-dd-3（20140103）.xls")

spec = importlib.util.spec_from_file_location("vib", ROOT / "振动分析.py")
vib = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vib)

RESULTS = []


def check(cond, msg):
    RESULTS.append((bool(cond), msg))
    print(("  PASS  " if cond else "  FAIL  ") + msg)


def hz(name, rpm, machine=None):
    """按程序口径算特征频率：倍数 × 该轴承所在轴转频。本文件里的条目都是相对高速轴(H)。"""
    shaft, mult = vib.BEARING_LIB[name]
    base = vib.shaft_freqs(rpm, machine).get(shaft, 0.0)
    return {k: v * base for k, v in mult.items()}


doc = json.loads(LIB.read_text(encoding="utf-8-sig"))
items = doc["bearings"]
print(f"轴承库：{LIB.name}  {len(items)} 条\n")

# 1. 载入不产生 warning
print("[库文件加载]")
warns = [w for w in vib.BEARING_LIB_WARNINGS if "轴承库" in w]
check(not warns, f"load_bearing_lib 读取本库无 warning（实际 {warns}）")

# 2. 结构检查
print("\n[结构]")
bad_shaft = [k for k, v in items.items() if v.get("shaft") not in vib.BEARING_SHAFTS]
check(not bad_shaft, f"shaft 全部合法（异常 {bad_shaft[:3]}）")
bad_mult = [k for k, v in items.items()
            if not any(k2 in v for k2 in ("BPFI", "BPFO", "BSF", "FTF"))
            or any(v[k2] <= 0 for k2 in ("BPFI", "BPFO", "BSF", "FTF") if k2 in v)]
check(not bad_mult, f"倍数全部为正且至少一项（异常 {bad_mult[:3]}）")
missing = [k for k in items if k not in vib.BEARING_LIB]
check(not missing, f"每条都合并进 BEARING_LIB（缺 {missing[:3]}）")
mismatch = [k for k, v in items.items()
            if k in vib.BEARING_LIB and vib.BEARING_LIB[k][1] != {
                f: v[f] for f in ("BPFI", "BPFO", "BSF", "FTF") if f in v}]
check(not mismatch, f"库内倍数与文件一致（不符 {mismatch[:3]}）")
big = [k for k, v in items.items() if any(x > 100 for x in v.values() if isinstance(x, (int, float)))]
check(not big, f"没有明显跑飞的倍数（>100 的 {big[:3]}）")

# 3. 抽查（期望值 = 原表第 9 列「特征频率」，该页额定转速下）
print("\n[抽查：原表额定转速下的特征频率]")
CASES = [
    # (轴承名, 原表电机转速 rpm, {特征: 原表 Hz})
    ("EN87-1500 高速轴前轴承 B10 NU2326", 1803.003, {"BPFO": 158.7832380952381}),
    ("EN87-1500 主轴前轴承 B1 SKF240/600", 1803.003, {"BPFO": 3.61185825}),
    ("EN70-1500 高速轴前轴承 B10 NCF2232", 1894.6, {"BPFO": 266.19950310559005}),
    ("UP1500 主轴前轴承 B1 239/670-ca-w33", 1708.16, {"BPFO": 3.5940999999999996}),
    ("EHN1500 中速轴前轴承 B8 SKF NU 2236", 1100.1859999999999,
     {"BPFO": 46.390981224489785}) if "EHN1500 中速轴前轴承 B8 SKF NU 2236" in items else None,
    ("皇帝坪 发电机前轴承 B12 SKF 6328M/C3", 1518.062, {"BPFO": 79.19223433333333}),
]
for case in CASES:
    if case is None:
        continue
    name, rpm, expect = case
    got = hz(name, rpm)
    for k, v in expect.items():
        ok = abs(got[k] - v) / v < 5e-4
        check(ok, f"{name} {k}: 程序算 {got[k]:.4f} Hz / 原表 {v:.4f} Hz")

# 4. 全量反算：只处理来自《C各机组振动诊断参数表》的条目（其余机型另有测试）
print("\n[全量反算（需原表）]")
try:
    import xlrd
except ImportError:
    xlrd = None
if not C_XLS.exists() or xlrd is None:
    print("  SKIP  原表或 xlrd 不可用")
else:
    book = xlrd.open_workbook(str(C_XLS))
    sheets = {s.name: s for s in book.sheets()}
    checked = skipped = 0
    problems = []
    for name, spec_ in items.items():
        model, rest = name.split(" ", 1)
        sh = sheets.get(model)
        if sh is None:
            skipped += 1          # 明阳 / 运达（五峰）来自别的数据源
            continue
        parts = rest.split(" ")
        if len(parts) < 2:
            problems.append(f"{name}: 名字无法解析")
            continue
        bgname, code = parts[0], parts[1]
        rows = [[sh.cell_value(r, c) for c in range(sh.ncols)] for r in range(sh.nrows)]
        f_hss, hdr = None, None
        for r in range(0, 40):
            if (str(rows[r][4]).strip() == "名称"
                    and str(rows[r][7]).strip().startswith("特征")):
                hdr = r
                try:
                    f_hss = float(rows[r - 1][3])
                except (TypeError, ValueError, IndexError):
                    pass
                break
        if not hdr or not f_hss:
            problems.append(f"{name}: 页 {model} 无电机转频")
            continue
        cur, found = None, {}
        for r in range(hdr + 1, len(rows)):
            nm = str(rows[r][4]).strip()
            if nm:
                cur = (nm, str(rows[r][5]).strip())
            if cur == (bgname, code):
                feat = str(rows[r][7]).strip().upper()
                if feat in ("BPFI", "BPFO", "BSF", "FTF"):
                    try:
                        found[feat] = float(rows[r][9])
                    except (TypeError, ValueError):
                        pass
        if not found:
            problems.append(f"{name}: 原表里找不到")
            continue
        got = hz(name, f_hss * 60.0)
        for k, v in found.items():
            if v <= 0:
                continue
            if k not in spec_:
                problems.append(f"{name} {k}: 原表有值但库里没有")
            elif abs(got[k] - v) / v > 5e-4:
                problems.append(f"{name} {k}: 库 {got[k]:.4f} vs 原表 {v:.4f}")
            checked += 1
    check(not problems,
          f"全量反算 {checked} 个频率全部吻合（跳过非本表条目 {skipped} 条）"
          + (f"；问题 {problems[:5]}" if problems else ""))

print()
failed = [m for ok, m in RESULTS if not ok]
print(f"共 {len(RESULTS)} 项断言，失败 {len(failed)} 项")
print("RESULT:", "ALL PASS" if not failed else "FAIL")
sys.exit(0 if not failed else 1)
