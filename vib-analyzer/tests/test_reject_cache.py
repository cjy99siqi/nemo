# -*- coding: utf-8 -*-
"""被拒收的文件记进 rejected 表：文件没变就不再重算，文件变了自动重试。"""
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


print("[可缓存的原因]")
for reason, want in (("采样点数不足：100 点（0.00 s @ 25600 Hz），至少需要 12800 点（0.5 s）", True),
                     ("量级异常：峰值 245.0 m/s²、带内 RMS 12.26 m/s²（疑似传感器饱和或单位不对，需现场核实），已跳过", True),
                     ("测点[xxx]不在规则列表", True),
                     ("读csv失败: [Errno 13] Permission denied", False),
                     ("未知原因", False)):
    got = vib.reject_cacheable(reason)
    check(got == want, f"{'缓存' if want else '不缓存'}：{reason[:26]}…")

d = os.path.join(ROOT, ".tmptest", "rej")
shutil.rmtree(d, ignore_errors=True)
os.makedirs(d)
csv = os.path.join(d, "s.csv")
open(csv, "w").write("1\n2\n3\n")
st = os.stat(csv)

print("[读写 rejected 表]")
conn = vib.db_connect(d)
vib.db_save_rejected(conn, [(csv, st.st_mtime, st.st_size, "采样点数不足")])
conn.commit()
m = vib.db_load_rejected(conn)
key = os.path.normcase(csv)
check(key in m, "能读回来")
check(abs(m[key][0] - st.st_mtime) < 1e-6 and int(m[key][1]) == st.st_size, "mtime/size 记对了")
check(m[key][2] == "采样点数不足", "原因记对了")

vib.db_delete_rejected(conn, [csv])
conn.commit()
check(vib.db_load_rejected(conn) == {}, "能删掉（清缓存后可重试）")
conn.close()

print("[表会自动建出来]")
conn = vib.db_connect(d)
n = conn.execute("SELECT COUNT(*) FROM rejected").fetchone()[0]
conn.close()
check(n == 0, "新库自带 rejected 表")

shutil.rmtree(d, ignore_errors=True)

print()
failed = [x for x in RESULTS if not x]
print(f"共 {len(RESULTS)} 项断言，失败 {len(failed)} 项")
print("RESULT:", "ALL PASS" if not failed else "FAIL")
