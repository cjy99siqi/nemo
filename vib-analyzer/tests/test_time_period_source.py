# -*- coding: utf-8 -*-
"""时域 1T…5T 的周期来源：游标 A/B 优先，没有游标时用自相关选出的基频。"""
import os
import importlib.util

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("vib", os.path.join(ROOT, "振动分析.py"))
vib = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vib)
SW = vib.SpectrumWindow
RESULTS = []


def check(ok, msg):
    RESULTS.append(bool(ok))
    print(("  PASS  " if ok else "  FAIL  ") + msg)


class S:
    _period_source = SW._period_source

    def __init__(self, tc=None, f=0.0, confirmed=False, start=None):
        self._tc_t = list(tc or [])
        self._f0 = f
        self._freq_confirmed = confirmed
        self._single_start_t = start

    def _fund_freq(self):
        return self._f0


print("[时间游标优先]")
p0, T, f = S(tc=[0.2, 0.25], f=20.0, confirmed=True, start=0.0)._period_source()
check(abs(p0 - 0.2) < 1e-9 and abs(T - 0.05) < 1e-9 and abs(f - 20.0) < 1e-9,
      f"用 A/B 间隔（{p0}, {T}, {f}）")
p0, T, f = S(tc=[0.25, 0.2])._period_source()
check(abs(p0 - 0.2) < 1e-9, "A/B 顺序反了也取小的作起点")

print("[没有游标时退回自相关周期]")
p0, T, f = S(f=20.0, confirmed=True, start=0.0)._period_source()
check(p0 == 0.0 and abs(T - 0.05) < 1e-9 and abs(f - 20.0) < 1e-9,
      f"自相关基频 20Hz → 周期 0.05s（{p0}, {T}）")
p0, T, f = S(f=8.0, confirmed=True, start=1.5)._period_source()
check(p0 == 1.5 and abs(T - 0.125) < 1e-9, "起点用 _single_start_t")

print("[都没有时不画]")
check(S()._period_source() == (None, 0.0, 0.0), "没有游标也没有基频")
check(S(f=20.0, confirmed=False, start=0.0)._period_source() == (None, 0.0, 0.0),
      "基频未确认时不画")
check(S(f=20.0, confirmed=True, start=None)._period_source() == (None, 0.0, 0.0),
      "没有起点时不画")
check(S(tc=[0.2, 0.2])._period_source() == (None, 0.0, 0.0), "A/B 重合不算周期")


print("[起点挑幅值高的一段]")
import numpy as _np


class B:
    _best_period_start = SW._best_period_start


b = B()
_fs = 25600.0
_tt = _np.arange(int(_fs * 1.5)) / _fs
_rng = _np.random.RandomState(0)
_yy = 0.5 * _rng.randn(_tt.size)                    # 底噪
# 0.42~0.58s 放一段强的 20Hz 冲击串
_mask = (_tt > 0.42) & (_tt < 0.58)
_yy[_mask] += 12.0 * _np.sin(2 * _np.pi * 20.0 * _tt[_mask]) ** 2
_t0 = b._best_period_start(_tt, _yy, 0.05)
check(0.40 <= _t0 <= 0.60, f"起点落在高幅值段（{_t0:.3f}s）")
check(abs(_yy[int(_np.argmin(_np.abs(_tt - _t0)))]) > 5.0, "起点吸附在波峰上")

_t0b = b._best_period_start(_tt, _yy, 0.0, default=7.0)
check(_t0b == 7.0, "周期非法时用默认值")
_t0c = b._best_period_start(_np.array([0.0, 0.001]), _np.array([1.0, 2.0]), 0.05, default=3.0)
check(_t0c == 3.0, "数据比 1.5 个周期还短时用默认值")


print("[周期性优先于单纯幅值]")
# 0.1~0.35s：幅值很大但完全随机（周期性差）；0.60~0.95s：幅值中等但严格的 20Hz
_tt2 = _np.arange(int(_fs * 1.5)) / _fs
_rng2 = _np.random.RandomState(1)
_y2 = 0.3 * _rng2.randn(_tt2.size)
_mA = (_tt2 > 0.10) & (_tt2 < 0.35)
_y2[_mA] += 25.0 * _rng2.randn(int(_mA.sum()))          # 大冲击、无周期
_mB = (_tt2 > 0.60) & (_tt2 < 0.95)
_y2[_mB] += 6.0 * _np.sin(2 * _np.pi * 20.0 * _tt2[_mB])
_t0b = b._best_period_start(_tt2, _y2, 0.05)
check(0.55 <= _t0b <= 0.95, f"选周期清楚的中等幅值段，而不是最响的随机段（{_t0b:.3f}s）")

print()
failed = [x for x in RESULTS if not x]
print(f"共 {len(RESULTS)} 项断言，失败 {len(failed)} 项")
print("RESULT:", "ALL PASS" if not failed else "FAIL")
