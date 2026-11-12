# -*- coding: utf-8 -*-
"""单窗口约束：主程序只跑一个进程；「图谱分析」只保留一个窗口（复用+前置）。"""
import os
import importlib.util

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("vib", os.path.join(ROOT, "振动分析.py"))
vib = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vib)

RESULTS = []


def check(ok, msg):
    RESULTS.append(bool(ok))
    print(("  PASS  " if ok else "  FAIL  ") + msg)


print("[单实例互斥]")
h1, dup1 = vib._single_instance_guard()
h2, dup2 = vib._single_instance_guard()
if os.name == "nt":
    # 机器上可能已经开着 VibSpec（用户在用），所以第一次的判断要以“有没有窗口”为准
    _existing = vib._activate_existing_window("VibSpec")
    check(h1 is not None, "拿到了互斥量句柄")
    if _existing:
        check(dup1 is True, f"已有实例在跑 → 本次启动即检测到（dup={dup1}）")
    else:
        check(dup1 is False, f"没有实例 → 第一次启动不报重（dup={dup1}）")
    check(dup2 is True, f"同一进程再取一次一定检测到已有实例（dup={dup2}）")
else:
    check(h1 is None and dup1 is False, "非 Windows 不做互斥（不阻塞）")

print("[图谱分析单窗口]")
calls = {"n": 0, "opened": []}


class FakeWin:
    def __init__(self, master=None, init_dir="", auto_load=None):
        calls["n"] += 1
        calls["opened"].append(auto_load)
        self.auto_load = auto_load
        self.loaded = []
        self.alive = True

    def winfo_exists(self):
        return self.alive

    def deiconify(self):
        pass

    def lift(self):
        pass

    def focus_force(self):
        pass

    def load_file(self, p):
        self.loaded.append(p)


class Stub:
    _spectrum_window = vib.VibGUI._spectrum_window

    def __init__(self):
        self.root = None
        self.main_dir = r"D:\数据\府谷\2026\06"
        self._spec_win = None


_orig = vib.SpectrumWindow
vib.SpectrumWindow = FakeWin
try:
    s = Stub()
    w1 = s._spectrum_window()
    w2 = s._spectrum_window()
    check(calls["n"] == 1 and w1 is w2, f"连点两次只开一个窗口（创建 {calls['n']} 次）")

    w3 = s._spectrum_window(r"/fake/a.csv")
    check(w3 is w1 and w3.loaded == ["/fake/a.csv"], "已开窗口时直接载入新文件（不新开）")
    check(calls["n"] == 1, "仍是同一个窗口")

    w3.alive = False                    # 用户关掉了
    w4 = s._spectrum_window(r"/fake/b.csv")
    check(w4 is not w3 and calls["n"] == 2, "窗口关掉后再点会重新创建")
    check(calls["opened"][-1] == "/fake/b.csv", "新窗口带上要看的文件")
finally:
    vib.SpectrumWindow = _orig


print()
print("[关窗后强制退出进程]")
_calls = {}


class _FakeOS:
    @staticmethod
    def _exit(code):
        _calls["exit"] = code


class _StubGUI:
    _trend_resize_job = None
    fig = None
    on_close = vib.VibGUI.on_close

    class _R:
        def destroy(self):
            _calls["destroyed"] = True

    root = _R()

    def save_state(self):
        _calls["saved"] = True


_orig_os = vib.os
vib.os = _FakeOS
try:
    _StubGUI().on_close()
finally:
    vib.os = _orig_os
check(_calls.get("saved") and _calls.get("destroyed"), "先保存状态、再销毁窗口")
check(_calls.get("exit") == 0, "最后 os._exit(0)，不留隐形进程")

print("[等待已有窗口]")
_orig_act = vib._activate_existing_window
_seq = [False, False, True]
vib._activate_existing_window = lambda title="VibSpec": _seq.pop(0) if _seq else False
check(vib._wait_for_window("VibSpec", tries=3, delay=0) is True, "第三次才找到窗口也算成功")
vib._activate_existing_window = lambda title="VibSpec": False
check(vib._wait_for_window("VibSpec", tries=2, delay=0) is False, "始终没有窗口返回 False")
vib._activate_existing_window = _orig_act

print()
failed = [x for x in RESULTS if not x]
print(f"共 {len(RESULTS)} 项断言，失败 {len(failed)} 项")
print("RESULT:", "ALL PASS" if not failed else "FAIL")
