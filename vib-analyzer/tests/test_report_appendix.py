# -*- coding: utf-8 -*-
"""报告附录：统计时段 ≥3 个月时，把判读复核表写进 Word（横向页、只列需复核行）。"""
import os
import shutil
import datetime
import importlib.util

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("vib", os.path.join(ROOT, "振动分析.py"))
vib = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vib)

from docx import Document

RESULTS = []


def check(ok, msg):
    RESULTS.append(bool(ok))
    print(("  PASS  " if ok else "  FAIL  ") + msg)


D = datetime.date
print("[何时附附录]")
check(vib.review_appendix_needed(D(2026, 1, 1), D(2026, 3, 31)) is False, "90 天以内不附（1/1→3/31 共 89 天）")
check(vib.review_appendix_needed(D(2026, 1, 1), D(2026, 4, 1)) is True, "满 90 天就附")
check(vib.review_appendix_needed(None, D(2026, 4, 1)) is False, "缺日期不附")
check(vib.review_appendix_needed(D(2026, 1, 1), None) is False, "缺日期不附")

d = os.path.join(ROOT, ".tmptest", "appx")
shutil.rmtree(d, ignore_errors=True)
os.makedirs(d)


def make_doc(name):
    p = os.path.join(d, name)
    doc = Document()
    doc.add_paragraph("正文")
    doc.save(p)
    return p


ROWS = [
    {"机组": "1#", "测点": "发电机前轴承径向", "等级": "警告", "轴承": "6332M C4", "阶次": "BPFO×1",
     "频率(Hz)": "61.0", "幅值": "0.521", "阈值": "0.500", "复现(命中/回看)": "3/5",
     "判读说明": "BPFO×1 61.0Hz 幅值 0.52"},
    {"机组": "1#", "测点": "主轴承前轴径向", "等级": "正常", "轴承": "", "阶次": "",
     "频率(Hz)": "", "幅值": "", "阈值": "", "复现(命中/回看)": "", "判读说明": ""},
    {"机组": "2#", "测点": "齿轮箱一级齿圈径向", "等级": "关注", "轴承": "", "阶次": "",
     "频率(Hz)": "", "幅值": "0.100", "阈值": "0.200", "复现(命中/回看)": "1/5",
     "判读说明": "齿轮边带 GMF/3"},
]

print("[写入附录表]")
p = make_doc("mix.docx")
n = vib.append_review_appendix(p, ROWS, D(2025, 12, 1), D(2026, 4, 30))
doc = Document(p)
check(n == 2, f"只列需复核的 2 条（返回 {n}）")
check(len(doc.tables) == 1, "生成 1 张表")
t = doc.tables[0]
check([c.text for c in t.rows[0].cells][:4] == ["序号", "机组", "测点", "等级"], "表头正确")
check(len(t.rows) - 1 == 2, f"数据行 2（{len(t.rows) - 1}）")
check(t.rows[1].cells[3].text in ("警告", "关注"), "按严重度排序（警告在前）")
check("BPFO×1" in t.rows[1].cells[4].text, "轴承/阶次合并成一列")
sec = doc.sections[-1]
check(int(getattr(sec.orientation, "value", sec.orientation)) == 1, "附录页为横向（10 列放得下）")
txt = "\n".join(x.text for x in doc.paragraphs)
check("附录  判读复核表" in txt, "有附录标题")
check("警告 1、关注 1、数据异常 0、正常 1" in txt, f"统计计数正确（{txt[:60]}…）")
check("共 151 天" in txt, "写了统计天数")

print("[全部正常]")
p2 = make_doc("ok.docx")
n2 = vib.append_review_appendix(p2, [ROWS[1]], D(2026, 1, 1), D(2026, 5, 1))
doc2 = Document(p2)
check(n2 == 0 and not doc2.tables, "没有需复核的行就不建表")
check("均为正常" in "\n".join(x.text for x in doc2.paragraphs), "写了一句‘均为正常’")

print("[条数上限]")
many = [dict(ROWS[0], 测点="测点%d" % i) for i in range(305)]
p3 = make_doc("many.docx")
vib.append_review_appendix(p3, many, D(2026, 1, 1), D(2026, 6, 1))
doc3 = Document(p3)
check(len(doc3.tables[0].rows) - 1 == vib.REVIEW_APPENDIX_MAX_ROWS,
      f"表格最多 {vib.REVIEW_APPENDIX_MAX_ROWS} 行（{len(doc3.tables[0].rows) - 1}）")
check("其余 5 条" in "\n".join(x.text for x in doc3.paragraphs), "提示其余条数去看 CSV")

shutil.rmtree(d, ignore_errors=True)

print()
failed = [x for x in RESULTS if not x]
print(f"共 {len(RESULTS)} 项断言，失败 {len(failed)} 项")
print("RESULT:", "ALL PASS" if not failed else "FAIL")
