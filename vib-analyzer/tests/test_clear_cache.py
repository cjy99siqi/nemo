# -*- coding: utf-8 -*-
"""清空缓存：按项目 + 年/月/日 选择性删除（只删 DB 记录，不动 CSV）。"""
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


d = os.path.join(ROOT, ".tmptest", "cache_scope")
os.makedirs(d, exist_ok=True)
dbp = vib.get_db_path(d)
for suf in ("", "-wal", "-shm"):
    try:
        os.remove(dbp + suf)
    except OSError:
        pass

conn = vib.db_connect(d)
rows = [
    ("/x/a.csv", "田家寨", "2026-06-03"),
    ("/x/b.csv", "田家寨", "2026-06-05"),
    ("/x/c.csv", "田家寨", "2026-07-01"),
    ("/x/d.csv", "五峰", "2026-06-03"),
]
for p, proj, dt in rows:
    conn.execute("INSERT INTO records(csv_path, project, dt_date) VALUES(?,?,?)", (p, proj, dt))
conn.commit()
conn.close()


class Stub:
    project_dirs = [d]
    _cache_where = staticmethod(vib.VibGUI._cache_where)

    def _cache_dirs(self):
        return [x for x in self.project_dirs if os.path.isdir(x)]

    def _reload_after_cache_clear(self):
        pass


def count():
    conn = vib.db_connect(d)
    try:
        return int(conn.execute("SELECT COUNT(*) FROM records").fetchone()[0])
    finally:
        conn.close()


infos = []
vib.messagebox.askyesno = lambda *a, **k: True
vib.messagebox.showinfo = lambda *a, **k: infos.append(a)

print("[WHERE 条件]")
c = vib.VibGUI._cache_where
check(c() == ("", []), "全空 → 无 WHERE")
check(c("田家寨")[0].count("?") == 1, "只按项目")
check(c("", "2026")[0].count("?") == 1, "只按年")
check(c("田家寨", "2026", "06")[0].count("?") == 3, "项目+年+月")
check(c("田家寨", "2026", "06", "03")[0].count("?") == 4, "项目+年+月+日")

print("[按日删除]")
before = count()
vib.VibGUI._clear_cache_apply(Stub(), "田家寨", "2026", "06", "03")
check(count() == before - 1, f"只删 1 条（{before} → {count()}）")
check(any("已删除 1 条" in str(x) for x in infos), f"提示删除条数（{infos[-1] if infos else None}）")

print("[按月删除]")
vib.VibGUI._clear_cache_apply(Stub(), "田家寨", "2026", "06")
check(count() == 2, f"田家寨 2026-06 全删（剩 {count()}：五峰1 + 田家寨7月1）")

print("[按项目删除]")
vib.VibGUI._clear_cache_apply(Stub(), "田家寨")
check(count() == 1, f"田家寨全删，五峰保留（剩 {count()}）")

print("[没有匹配]")
n = len(infos)
vib.VibGUI._clear_cache_apply(Stub(), "不存在的项目")
check(len(infos) == n + 1 and "没有匹配" in str(infos[-1]), "无匹配时只提示、不删除")
check(count() == 1, "记录数不变")

try:
    shutil.rmtree(d, ignore_errors=True)
except Exception:
    pass

print()
failed = [x for x in RESULTS if not x]
print(f"共 {len(RESULTS)} 项断言，失败 {len(failed)} 项")
print("RESULT:", "ALL PASS" if not failed else "FAIL")
