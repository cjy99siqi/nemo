"""回归测试：SpectrumWindow._bearing_dialog 的"自定义倍数"路径。

背景：该对话框的 ok() 曾引用只在 _gear_dialog 里存在的 v_cust，
点「确定」必抛 NameError（pythonw 下静默）。见 项目说明.md §6.2。

做法：不实例化整个 GUI，把 _bearing_dialog 当作未绑定方法，
用一个 Tk 根窗口充当下拉 self，并把它真正依赖的方法挂上去。
运行：python tests/test_bearing_dialog.py   （需要图形环境，Windows 本机即可）
"""
import sys
import tkinter as tk
from pathlib import Path
from tkinter import ttk
import importlib.util

ROOT = Path(__file__).resolve().parents[1]          # vib-analyzer/
TARGET = ROOT / "振动分析.py"

spec = importlib.util.spec_from_file_location("vib", TARGET)
vib = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vib)

ERRORS = []
_root = None


def _fake_error(title, msg, **kw):
    """替身 messagebox：记录错误并关闭对话框，避免弹窗阻塞测试。"""
    ERRORS.append((title, msg))
    for w in _root.winfo_children():
        if isinstance(w, tk.Toplevel):
            w.destroy()


vib.messagebox.showerror = _fake_error


def descendants(w, cls):
    out = []
    for c in w.winfo_children():
        if isinstance(c, cls):
            out.append(c)
        out.extend(descendants(c, cls))
    return out


def run_case(rpm_text, custom):
    global _root
    ERRORS.clear()
    root = tk.Tk(); root.withdraw(); _root = root
    root._bearing_sel = None
    root.info = {"project": "田家寨"}                # 机型按项目名匹配（数据\机型库.json）
    root._machine_name = None
    root.current_machine = lambda: vib.machine_for_project("田家寨")
    root._get_rot_hz = lambda: 25.0                  # 1500 rpm
    root._redraw_current_plot = lambda: None
    root._bearing_shaft_freqs = lambda f: vib.SpectrumWindow._bearing_shaft_freqs(root, f)

    def drive():
        dlgs = [w for w in root.winfo_children() if isinstance(w, tk.Toplevel)]
        if not dlgs:
            root.after(100, drive); return
        dlg = dlgs[0]
        # Combobox 是 Entry 的子类，只取普通 Entry：0=转速，1..4=自定义倍数
        edits = [e for e in descendants(dlg, ttk.Entry) if not isinstance(e, ttk.Combobox)]
        assert len(edits) == 5, f"期望 5 个输入框（转速+4 自定义），实际 {len(edits)}"
        edits[0].delete(0, "end"); edits[0].insert(0, rpm_text)
        for i, key in enumerate(("BPFI", "BPFO", "BSF", "FTF")):
            if key in custom:
                edits[1 + i].delete(0, "end"); edits[1 + i].insert(0, custom[key])
        [b for b in descendants(dlg, ttk.Button) if b.cget("text") == "确定"][0].invoke()

    root.after(300, drive)
    vib.SpectrumWindow._bearing_dialog(root)
    marks = getattr(root, "_bearing_marks", None)
    sel = getattr(root, "_bearing_sel", None)
    root.destroy()
    return marks, sel


def main():
    lib_before = {k: dict(v[1]) for k, v in vib.BEARING_LIB.items()}
    marks1, _ = run_case("1500", {})
    marks2, sel = run_case("1500", {"BPFI": "8.5"})

    probe = tk.Tk(); probe.withdraw()
    probe.info = {"project": "田家寨"}
    probe.current_machine = lambda: vib.machine_for_project("田家寨")
    shaft, mult = vib.BEARING_LIB[sel]
    base = vib.SpectrumWindow._bearing_shaft_freqs(probe, 1500 / 60.0)[shaft]
    probe.destroy()

    d1 = {m["label"]: m["hz"] for m in (marks1 or [])}
    d2 = {m["label"]: m["hz"] for m in (marks2 or [])}
    print(f"轴承={sel}  轴={shaft}  base={base:.4f} Hz  库倍数={mult}")
    print("用例1(库值)   :", {k: round(v, 4) for k, v in d1.items()})
    print("用例2(BPFI=8.5):", {k: round(v, 4) for k, v in d2.items()})

    checks = [
        (not ERRORS, f"点确定没弹错误框（实际 {ERRORS}）"),
        (bool(d1), "用例1 产出标注"),
        (abs(d1.get("BPFI", -1) - mult["BPFI"] * base) < 1e-9, "用例1 BPFI = 库值×base"),
        (abs(d2.get("BPFI", -1) - 8.5 * base) < 1e-9, "用例2 BPFI = 8.5×base（自定义生效）"),
        (abs(d2.get("BPFO", -1) - mult["BPFO"] * base) < 1e-9, "用例2 BPFO 仍用库值（未被误覆盖）"),
        ({k: dict(v[1]) for k, v in vib.BEARING_LIB.items()} == lib_before,
         "BEARING_LIB 未被污染"),
    ]
    ok = True
    for cond, msg in checks:
        print(("  PASS  " if cond else "  FAIL  ") + msg)
        ok = ok and cond
    print("\nRESULT:", "ALL PASS" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
