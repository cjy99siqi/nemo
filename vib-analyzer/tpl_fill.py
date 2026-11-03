"""在人工模板上就地刷新：只改数字、换故障图，不动版式。"""
import os, re, shutil, datetime
from docx import Document
from docx.shared import Cm, Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

STATUS_FILL = {"正常": "C6EFCE", "数据异常": "E7E6E6", "警告": "FFEB9C", "危险": "FFC7CE"}


def _shade(cell, color):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = tcPr.find(qn("w:shd"))
    if shd is None:
        shd = OxmlElement("w:shd")
        shd.set(qn("w:val"), "clear")
        shd.set(qn("w:color"), "auto")
        tcPr.append(shd)
    shd.set(qn("w:fill"), color)


def set_cell(cell, text):
    txt = "" if text is None else str(text)
    p = cell.paragraphs[0]
    for extra in cell.paragraphs[1:]:
        extra._element.getparent().remove(extra._element)
    runs = p.runs
    if runs:
        runs[0].text = txt
        for r in runs[1:]:
            r._element.getparent().remove(r._element)
    else:
        p.add_run(txt)
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER


def set_status(cell, text):
    set_cell(cell, text)
    if text in STATUS_FILL:
        _shade(cell, STATUS_FILL[text])


def _repl_para(p, text):
    runs = list(p.runs)
    if not runs:
        p.add_run(text)
        return
    keep = None
    for r in runs:
        if r._element.findall(qn("w:br")):
            keep = r
    runs[0].text = text
    for r in runs[1:]:
        if r is keep:
            continue
        r._element.getparent().remove(r._element)


def unit_no(txt):
    m = re.match(r"\s*(\d+)\s*#", txt or "")
    return int(m.group(1)) if m else None


def _grade_of(agg, u, part_of, order):
    g = {}
    for pt, d in agg[u].items():
        part = part_of(pt)
        if d["grade"] == "数据异常":
            if g.get(part) not in ("警告", "危险"):
                g[part] = "数据异常"
        elif part not in g or order.get(d["grade"], 0) > order.get(g[part], 0):
            g[part] = d["grade"]
    return g


def _fix_lang(doc):
    """把全文语言设为中文，去掉 Word 的红色/蓝色波浪线。"""
    def _set(rPr):
        if rPr is None:
            return
        lang = rPr.find(qn("w:lang"))
        if lang is None:
            lang = OxmlElement("w:lang")
            rPr.append(lang)
        lang.set(qn("w:val"), "en-US")
        lang.set(qn("w:eastAsia"), "zh-CN")
    for st in doc.styles:
        try:
            if st.element.rPr is not None:
                _set(st.element.rPr)
        except Exception:
            pass
    for r in doc.element.body.iter(qn("w:r")):
        rPr = r.find(qn("w:rPr"))
        if rPr is None:
            rPr = OxmlElement("w:rPr")
            r.insert(0, rPr)
        _set(rPr)
    for sec in doc.sections:
        for hf in (sec.header, sec.footer):
            for r in hf._element.iter(qn("w:r")):
                rPr = r.find(qn("w:rPr"))
                if rPr is None:
                    rPr = OxmlElement("w:rPr")
                    r.insert(0, rPr)
                _set(rPr)


def _fill_dates(doc, project, d0):
    month_cn = "%d 年 %d 月" % (d0.year, d0.month)
    month_dot = "%d.%d" % (d0.year, d0.month)
    for sec in doc.sections:
        for hf in (sec.header, sec.footer):
            for p in hf.paragraphs:
                if "振动分析报告" in p.text:
                    _repl_para(p, project + " " + month_cn + "振动分析报告")
    for t in doc.tables[:1]:
        for row in t.rows:
            for c in row.cells:
                s = c.text.strip()
                if re.match(r"^20\d\d\.\d{1,2}(\.\d{1,2})?$", s):
                    set_cell(c, month_dot if s.count(".") == 1 else
                             datetime.date.today().strftime("%Y.%m.%d"))


def _cnname(pt):
    """测点显示名：去掉下划线，主轴承/发电机补“轴承”。"""
    try:
        import importlib.util as _ilu
    except Exception:
        pass
    t = (pt or "").replace("_", "")
    return t


def _fill_overview(doc, agg, prof, d0, d1, rows, project):
    """重写“1、概述”后的正文段落。"""
    units = list(agg.keys())
    n_pt = sum(len(v) for v in agg.values())
    nd_u = []
    known = prof.get("units_known") or [] if isinstance(prof, dict) else []
    for k in known:
        if k not in agg and k not in nd_u:
            nd_u.append(k)
    bad_pt, alarm, big = [], [], []
    for u in units:
        for pt, d in agg[u].items():
            if d.get("data_bad"):
                bad_pt.append((u, pt, d))
            elif d["grade"] == "警告":
                alarm.append((u, pt, d))
            elif d["ratio"] >= 0.8:
                big.append((u, pt, d))
    def _ts(r):
        for k in ("dt_str", "dt", "ts", "time", "stamp", "datetime"):
            if r.get(k):
                return str(r[k])
        return ""
    dmin = min((_ts(r) for r in rows if _ts(r)), default="")
    dmax = max((_ts(r) for r in rows if _ts(r)), default="")
    sent = []
    sent.append("本报告针对 %d 年 %d 月在线监测数据进行分析，共有 %d 台机组列入报告，测点 %d 个，"
                "有效记录 %d 条，记录时间从 %s 至 %s。"
                % (d0.year, d0.month, len(units), n_pt, len(rows),
                   (dmin[:16] if dmin else "-"), (dmax[:16] if dmax else "-")))
    if nd_u:
        sent.append("%s 机组本期无有效数据" % "、".join(nd_u))
    if bad_pt:
        sent.append("测点数据异常：%s（振动值仅为同型机组的 %.0f%%~%.0f%%，判断为传感器安装或采集通道问题，需现场核查）"
                    % ("、".join("%s%s" % (u, _cnname(pt)) for u, pt, d in bad_pt[:6]),
                       100.0 * min(d["max"] / max(1e-9, d.get("peer_med", 1)) for u, pt, d in bad_pt),
                       100.0 * max(d["max"] / max(1e-9, d.get("peer_med", 1)) for u, pt, d in bad_pt)))
    if alarm:
        sent.append("通过包络谱分析可知，%s 存在轴承故障阶次（%s），等级：警告"
                    % ("、".join("%s%s" % (u, _cnname(pt)) for u, pt, d in alarm),
                       "；".join(d.get("fault_lab", "") for u, pt, d in alarm[:4])))
    if big:
        sent.append("%d 个测点振动值偏大（占第一限度 ≥80%%）但未见故障特征，判为正常" % len(big))
    _clean = [x.rstrip("。；") for x in sent]
    text = "；".join(_clean) + "；其余机组运行正常。"

    # 定位“1、概述”后的第一个正文段落（在信息表末行合并格里）
    for t in doc.tables[:1]:
        for row in t.rows:
            for c in row.cells:
                ps = c.paragraphs
                for i, p in enumerate(ps):
                    if "概述" in p.text.strip()[:4]:
                        cands = [q for q in ps[i + 1:] if q.text.strip()]
                        for q in cands:
                            if "本报告针对" in q.text:
                                _repl_para(q, text)
                                return True
                        if cands:
                            _repl_para(cands[-1], text)
                            return True
    return False


def _fill_units(doc, agg, part_of, order):
    pairs = []
    for i, t in enumerate(doc.tables):
        if len(t.rows) == 3 and len(t.columns) == 4 and i + 1 < len(doc.tables) \
                and len(doc.tables[i + 1].rows) == 12:
            pairs.append((t, doc.tables[i + 1]))
    for t_st, t_vdi in pairs:
        # 机组号取自 VDI 表首列（纵向合并格），兼容“1#”“1 ”等写法
        u = None
        for _c in (t_vdi.rows[2].cells[0], t_vdi.rows[1].cells[0], t_st.rows[1].cells[0]):
            m = re.match(r"\s*(\d+)\s*#?", _c.text or "")
            if m:
                u = "%d#" % int(m.group(1))
                break
        if u is None or u not in agg:
            continue
        g = _grade_of(agg, u, part_of, order)
        for j, part in enumerate(("主轴承", "齿轮箱", "发电机"), start=1):
            set_status(t_st.rows[2].cells[j], g.get(part, "正常"))
        for k, pt in enumerate(list(agg[u].keys())):
            r = 2 + k
            if r >= len(t_vdi.rows) - 1:
                break
            d = agg[u][pt]
            v = d["max"]
            set_cell(t_vdi.rows[r].cells[4], ("%.4f" % v) if v < 0.01 else "%.2f" % v)
            set_cell(t_vdi.rows[r].cells[6], "%.1f%%" % (d["ratio"] * 100))
        rs = [d["ratio"] * 100 for d in agg[u].values()]
        set_cell(t_vdi.rows[len(t_vdi.rows) - 1].cells[2],
                 "各测点振动有效值占 VDI3834 标准第一限度比例 %.1f%%~%.1f%%。" % (min(rs), max(rs)))


def _fill_summary(doc, agg, part_of, order):
    for t in doc.tables:
        if len(t.columns) not in (6, 7) or len(t.rows) <= 3:
            continue
        hdr = None
        for _i, _r in enumerate(t.rows[:4]):
            if any("主轴承" in c.text for c in _r.cells):
                hdr = _i
                break
        if hdr is None:
            continue
        hdrmap = {}
        for _j, _c in enumerate(t.rows[hdr].cells):
            for part in ("主轴承", "齿轮箱", "发电机"):
                if part in _c.text and part not in hdrmap:
                    hdrmap[part] = _j
        if len(hdrmap) < 3:
            continue
        for row in t.rows[hdr + 1:]:
            u = None
            for c in row.cells:
                m = re.match(r"^\s*(\d+)\s*#?\s*$", c.text.strip())
                if m:
                    u = "%d#" % int(m.group(1))
                    break
            if not u or u not in agg:
                continue
            g = _grade_of(agg, u, part_of, order)
            for part, j in hdrmap.items():
                set_status(row.cells[j], g.get(part, "正常"))


def _current_unit_before(doc, p):
    idx = list(doc.element.body).index(p._element)
    n = None
    for q in doc.paragraphs:
        m = re.match(r"\s*(\d+)\s+(\d+)#机组", q.text.strip())
        if m and list(doc.element.body).index(q._element) < idx:
            n = int(m.group(2))
    return n


def _fill_counts(doc, agg, total):
    _pat = re.compile(r"共监测[^，]*?\d+\s*台[，,]\s*列入报告\s*\d+\s*台")
    _new = "共监测明阳机组 %d 台，列入报告 %d 台" % (total, len(agg))
    for t in doc.tables:
        for row in t.rows:
            for c in row.cells:
                for p in c.paragraphs:
                    if "列入报告" in p.text:
                        _repl_para(p, _pat.sub(_new, p.text))


def _fill_conclusions(doc, agg):
    for p in doc.paragraphs:
        txt = p.text.strip()
        if not txt or txt.startswith("如图"):
            continue
        if not (txt.startswith("机组传动链") or txt.endswith("等级：警告。") or "额定" in txt
                or "外圈" in txt or "内圈" in txt or "滚动体" in txt):
            continue
        n = _current_unit_before(doc, p)
        if n is None:
            continue
        u = "%d#" % n
        if u not in agg:
            continue
        bad = [pt for pt, d in agg[u].items() if d["grade"] == "警告"]
        if bad:
            _repl_para(p, "%s 存在轴承故障特征（%s），等级：警告。"
                       % (bad[0], agg[u][bad[0]].get("fault_lab", "")))
        else:
            dbs = [pt for pt, d in agg[u].items() if d.get("data_bad")]
            if dbs:
                d = agg[u][dbs[0]]
                _repl_para(p, "机组传动链运行正常；%s（最大 %.4f m/s²，仅为同型机组的 %.0f%%）测点数据异常，"
                              "疑似传感器安装或采集通道问题，建议重新安装并核查该测点。"
                           % (dbs[0], d["max"], 100.0 * d["max"] / max(1e-9, d["peer_med"])))
            else:
                _repl_para(p, "机组传动链运行正常。")


def _fault_blocks(doc):
    """返回 [(unit, [段落...], [图片段落...])] 按 N.3 诊断分析 到 处理建议 之间收集。"""
    blocks = []
    paras = doc.paragraphs
    cur = None
    for p in paras:
        t = p.text.strip()
        m = re.match(r"(\d+)\.3\s*诊断分析", t)
        if m:
            cur = {"unit": int(m.group(1)), "paras": [p], "imgs": []}
            continue
        if cur is None:
            continue
        if re.match(r"\d+\.5\s*处理建议", t):
            cur["paras"].append(p)
            blocks.append(cur)
            cur = None
            continue
        cur["paras"].append(p)
        if p._element.findall(".//" + qn("w:drawing")):
            cur["imgs"].append(p)
    return blocks


IMG_WIDTHS = (15.5, 13.2)


def _replace_image(p, png, width_cm=15.5):
    for r in list(p.runs):
        for dr in r._element.findall(".//" + qn("w:drawing")):
            dr.getparent().remove(dr)
    r = p.runs[0] if p.runs else p.add_run()
    r.add_picture(png, width=Cm(width_cm))


def _delete_para(p):
    p._element.getparent().remove(p._element)


def fill(tpl, out, project, d0, d1, agg, units, part_of, order,
         prof=None, rows=None, fig_cb=None, caption_cb=None, analysis_cb=None):
    """fig_cb(unit, point) -> png 路径；caption_cb(unit, point, png, ts) -> 图注；analysis_cb(unit, point) -> 分析段"""
    shutil.copyfile(tpl, out)
    doc = Document(out)
    _fill_dates(doc, project, d0)
    _fill_overview(doc, agg, prof, d0, d1, rows, project)
    _fill_units(doc, agg, part_of, order)
    _fill_summary(doc, agg, part_of, order)
    try:
        _tot = max([int(u.rstrip("#")) for u in agg if u.rstrip("#").isdigit()] + [len(agg)])
        _fill_counts(doc, agg, _tot)
    except Exception:
        pass
    _fill_conclusions(doc, agg)

    # 故障块：有故障 → 换图换字；无故障 → 整块删除
    for blk in _fault_blocks(doc):
        u = "%d#" % blk["unit"]
        bad = [pt for pt, d in agg.get(u, {}).items() if d["grade"] == "警告"] if u in agg else []
        if bad and fig_cb:
            res = fig_cb(u, bad[0])
            pngs = res if isinstance(res, (list, tuple)) else ([res] if res else [])
            for i, png in enumerate(pngs):
                if png and i < len(blk["imgs"]):
                    _replace_image(blk["imgs"][i], png,
                                   IMG_WIDTHS[i] if i < len(IMG_WIDTHS) else 15.5)
            # 模板里多余的图（本次没有对应图）连同其图注一起删掉
            for j in range(len(pngs), len(blk["imgs"])):
                _delete_para(blk["imgs"][j])
            _ci = 0
            for p in blk["paras"]:
                t = p.text.strip()
                if t.startswith("如图") and analysis_cb:
                    _repl_para(p, analysis_cb(u, bad[0]))
                elif t.startswith("图") and caption_cb:
                    if _ci < len(pngs):
                        _repl_para(p, caption_cb(u, bad[0], pngs[_ci], _ci))
                        _ci += 1
                    else:
                        _delete_para(p)
            # 删掉故障块内的空段落（不含分页符/图片），把结论与建议上提，避免半页空白
            for p in list(blk["paras"]):
                if p.text.strip():
                    continue
                if p._element.findall(".//" + qn("w:drawing")):
                    continue
                if p._element.findall(".//" + qn("w:br")):
                    continue
                _delete_para(p)
        elif not bad:
            for p in blk["paras"]:
                _delete_para(p)

    _fix_lang(doc)
    doc.save(out)
    return out
