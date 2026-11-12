# -*- coding: utf-8 -*-
"""压缩包扫描：正常包 / 只有本地头的截断包 / 全坏 / 认不出测点 要分开处理。

现场常见的是“拷贝没完成”：中央目录丢了（zipfile 报不是 zip），但本地文件头还在，
WinRAR 能解、Python 不能。程序要能靠本地头把完整的条目救回来，
只有真正解不出来的才报“损坏/解压中断”。
"""
import os
import random
import shutil
import zipfile
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


d = os.path.join(ROOT, ".tmptest", "zips")
os.makedirs(d, exist_ok=True)
csv_name = "中节能五峰北风垭风电场_11_主轴轴承_20000Hz_6.56s_加速度值_1098_20260601130058.csv"
body = "\n".join(["0.1"] * 200) + "\n"

good = os.path.join(d, "good.zip")
with zipfile.ZipFile(good, "w") as z:
    z.writestr("tmp/" + csv_name, body)

# 只保留本地头、砍掉中央目录与结尾记录：模拟拷贝中断
half = os.path.join(d, "half.zip")
with open(good, "rb") as f:
    data = f.read()
with open(half, "wb") as f:
    f.write(data[: int(len(data) * 0.6)])

zero = os.path.join(d, "zero.zip")
open(zero, "wb").close()

unknown = os.path.join(d, "unknown.zip")
with zipfile.ZipFile(unknown, "w") as z:
    z.writestr("tmp/随便什么名字.csv", body)


class S:
    _scan_zips = GUI._scan_zips


print("[扫描分类]")
entries, problems, broken = GUI._scan_zips(S(), [good, half, zero, unknown])
check(len(entries) == 2, f"正常包 + 截断包都能列出来（{len(entries)} 条）")
check(broken == ["zero.zip"], f"0 字节包才归「损坏」（{broken}）")
check(len(problems) == 1, f"认不出测点的归「未识别」（{len(problems)}）")
pts = [e["point"] for e in entries]
check(pts.count("主轴轴承") == 2, f"截断包里的测点也能识别（{pts}）")

print("[体检：快速统计缺中央目录的包]")
total, bad = vib.zip_health([good, half, zero, unknown])
check(total == 4 and bad == 2, f"4 个包里有 2 个缺中央目录（half/zero）（{total},{bad}）")
check(vib.zip_health([good]) == (1, 0), "正常包不算坏")

print("[取数据]")
check(len(vib.zip_read_member(good, "tmp/" + csv_name)) == len(body), "正常包取到完整数据")
check(vib.zip_read_member(half, "tmp/" + csv_name) is None,
      "截断包的数据流不完整 → 返回 None（不写半截文件）")

try:
    shutil.rmtree(d, ignore_errors=True)
except Exception:
    pass

print()
failed = [x for x in RESULTS if not x]
print(f"共 {len(RESULTS)} 项断言，失败 {len(failed)} 项")
print("RESULT:", "ALL PASS" if not failed else "FAIL")
