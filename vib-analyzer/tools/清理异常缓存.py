# -*- coding: utf-8 -*-
"""清理量级异常（传感器饱和/触顶）的缓存记录。

用法：
    python tools\清理异常缓存.py                 # 只统计，不改库
    python tools\清理异常缓存.py --apply         # 备份后删除
    python tools\清理异常缓存.py --apply --dirs "D:\数据\五峰" "D:\数据\府谷\2026\06"

默认目录取 gui_state.json 里登记的 project_dirs（去重后存在的目录）。
判据与主程序一致：peak >= ABNORMAL_PEAK 或 rms >= ABNORMAL_RMS。
"""
import argparse
import json
import os
import shutil
import sqlite3
import sys
import time

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, APP_DIR)

import importlib.util
spec = importlib.util.spec_from_file_location("vib", os.path.join(APP_DIR, "振动分析.py"))
vib = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vib)

WHERE = "(peak >= ? OR rms >= ?)"
ARGS = [vib.ABNORMAL_PEAK, vib.ABNORMAL_RMS]


def default_dirs():
    try:
        with open(os.path.join(APP_DIR, "gui_state.json"), encoding="utf-8") as f:
            st = json.load(f)
    except Exception:
        return []
    out = []
    for d in st.get("project_dirs") or []:
        if os.path.isdir(d) and os.path.exists(os.path.join(d, vib.DB_FILE)):
            out.append(os.path.normpath(d))
    return list(dict.fromkeys(out))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="真正删除（默认只统计）")
    ap.add_argument("--dirs", nargs="*", default=None, help="项目目录（默认取 gui_state.json）")
    a = ap.parse_args()
    dirs = a.dirs or default_dirs()
    if not dirs:
        print("没有可处理的目录（先在上传里选过项目）")
        return 1
    total = 0
    for d in dirs:
        db = os.path.join(d, vib.DB_FILE)
        if not os.path.exists(db):
            continue
        conn = sqlite3.connect(db, timeout=30)
        try:
            n_all = conn.execute("SELECT COUNT(*) FROM records").fetchone()[0]
            n_bad = conn.execute("SELECT COUNT(*) FROM records WHERE " + WHERE, ARGS).fetchone()[0]
            print("%s\n  记录 %d，异常 %d" % (d, n_all, n_bad))
            if not n_bad:
                continue
            for pt, c in conn.execute(
                    "SELECT point, COUNT(*) FROM records WHERE " + WHERE +
                    " GROUP BY point ORDER BY COUNT(*) DESC", ARGS):
                print("    %-16s %d" % (pt, c))
            if a.apply:
                bak = db + time.strftime(".bak_%Y%m%d_%H%M%S")
                shutil.copy2(db, bak)
                for suf in ("-wal", "-shm"):
                    if os.path.exists(db + suf):
                        shutil.copy2(db + suf, bak + suf)
                cur = conn.execute("DELETE FROM records WHERE " + WHERE, ARGS)
                conn.commit()
                print("    已删除 %d 条（备份 %s）" % (cur.rowcount, os.path.basename(bak)))
                total += cur.rowcount
        finally:
            conn.close()
    print("\n合计删除 %d 条" % total if a.apply else "\n（只统计，未修改；加 --apply 执行删除）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
