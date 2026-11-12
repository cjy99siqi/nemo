# -*- coding: utf-8 -*-
"""趋势图日期：无控件垫片 + 日历只在箭头区弹出"""
import importlib.util
import os
import sys
from datetime import date, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
spec = importlib.util.spec_from_file_location("vib", os.path.join(APP, "振动分析.py"))
v = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v)

R = []


def check(ok, msg):
    R.append(bool(ok))
    print(("  PASS  " if ok else "  FAIL  ") + msg)


print("[日期垫片]")
s = v._DateShim()
check(isinstance(s.get_date(), date), "默认返回 date")
s.set_date(date(2026, 6, 15))
check(s.get_date() == date(2026, 6, 15), "set_date(date)")
s.set_date("2026-06-20")
check(s.get_date() == date(2026, 6, 20) and s.get() == "2026-06-20", "set_date(字符串) + get()")
s.set_date(datetime(2026, 7, 1, 12, 0))
check(s.get_date() == date(2026, 7, 1), "set_date(datetime)")
s.set_date("不是日期")
check(s.get_date() == date(2026, 7, 1), "非法字符串不改原值")

print("[日历只在箭头区弹]")
check(getattr(v.DateEntry, "_on_b1_press", None) is v._safe_dateentry_press,
      "DateEntry._on_b1_press 已换成安全版本")

print()
failed = [x for x in R if not x]
print("共 %d 项断言，失败 %d 项" % (len(R), len(failed)))
print("RESULT: " + ("ALL PASS" if not failed else "FAIL"))
sys.exit(0 if not failed else 1)
