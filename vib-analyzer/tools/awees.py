# -*- coding: utf-8 -*-
"""AWEES —— 自相关加权增强包络谱（复合故障分离）

对应论文图 1 的流程：
    振动信号 + 谱相干 -> 平方自相关定位周期峰 -> PPFM
    -> 谱频率权重 SF / 循环频率权重 CF -> 增强谱相干 SAESCoh
    -> 各频带 EFDSNR + 阈值 -> 按频带聚类得到多个故障模式 -> AWEES

为什么单独放一个模块
--------------------
振动分析.py 是 8000 行单文件 GUI，算法塞进去既难验证也难回滚。
这里做成纯 NumPy/SciPy 的函数库：可单独跑、可单测、可先用仿真验证，
确认有效后再决定是否接进 GUI 的「图谱分析」。

关键约定
--------
* 谱相干内部按 [谱频率带, 循环频率] 存放（与原谱图同向：横轴循环频率）。
* 循环频率分辨率由 帧率/帧数 决定，调用方要保证 >= 2 倍最高关注故障频率。
* 阈值规则带有论文的先验（最多 2 个目标模式 + 1 个干扰模式），
  故障数未知时不要直接沿用，见 `max_modes` 参数。

用法：
    python tools\awees.py --demo            # 跑论文仿真（50/80Hz，-18dB）
    python tools\awees.py --csv a.csv --fs 20000
"""

from __future__ import annotations

import argparse
import sys

import numpy as np


# --------------------------------------------------------------------------
# 1. 谱相干（谱频率 x 循环频率）
# --------------------------------------------------------------------------
def spectral_coherence(x, fs, win=128, hop=None, n_bands=48):
    """短时傅里叶 + 频带包络谱，得到谱相干矩阵。

    做法与「快速谱相干」一致：把频谱切成若干频带，取每个频带的功率包络，
    再对包络做 FFT 得到循环谱。相比逐点 X(f+a/2)X*(f-a/2)，
    计算量小一个量级，且包络谱正是工程上判故障用的那条谱。

    返回
    ----
    scoh   : ndarray [n_bands, n_alpha]，已按每带均值归一化
    alpha  : ndarray [n_alpha]，循环频率 (Hz)
    freqs  : ndarray [n_bands]，各频带中心频率 (Hz)
    """
    x = np.asarray(x, dtype=float)
    x = x - x.mean()
    if hop is None:
        hop = max(1, win // 4)

    n_frames = 1 + (len(x) - win) // hop
    if n_frames < 8:
        raise ValueError("信号太短：帧数 < 8，无法估计循环频率")

    idx = np.arange(win)[None, :] + hop * np.arange(n_frames)[:, None]
    frames = x[idx] * np.hanning(win)[None, :]
    spec = np.fft.rfft(frames, axis=1)              # [帧, 频率bin]
    power = np.abs(spec) ** 2

    n_bins = power.shape[1]
    bin_hz = fs / win
    # 按频率等分带宽（跳过低频 DC 附近，避免把 0-1 个 bin 当成一个"频带"）
    freqs_hz = np.linspace(0.0, fs / 2.0, n_bins)
    edges_hz = np.linspace(freqs_hz[min(1, n_bins - 1)], fs / 2.0, n_bands + 1)
    env = np.empty((n_frames, n_bands))
    centers = np.empty(n_bands)
    for b in range(n_bands):
        lo = int(np.searchsorted(freqs_hz, edges_hz[b], side="left"))
        hi = int(np.searchsorted(freqs_hz, edges_hz[b + 1], side="right"))
        hi = max(hi, lo + 1)
        lo = min(lo, n_bins - 1)
        hi = min(hi, n_bins)
        env[:, b] = power[:, lo:hi].sum(axis=1)
        centers[b] = 0.5 * (edges_hz[b] + edges_hz[b + 1])

    env = env - env.mean(axis=0)
    cyclic = np.fft.rfft(env, axis=0)                # [→循环频率, 带]
    alpha = np.fft.rfftfreq(n_frames, d=hop / fs)

    scoh = np.abs(cyclic).T                          # [带, 循环频率]
    scale = scoh.mean(axis=1, keepdims=True) + 1e-12
    scoh = scoh / scale
    return scoh, alpha, centers


# --------------------------------------------------------------------------
# 2. PPFM：平方自相关找周期峰，并把谐波位置一起记下来
# --------------------------------------------------------------------------
def ppfm_from_scoh(scoh, min_lag=5, max_lag=None, max_harm=5, peak_ratio=0.05):
    """逐频带对「相干谱能量」做平方自相关，记录基频与整数倍位置。

    直接取最大峰会丢掉倍频信息（论文明确提到这点），所以这里把
    lag = k * lag0（k=1..max_harm）的自相关值都写进 PPFM，其余置 0。

    返回
    ----
    ppfm      : [带, 循环频率] 与 scoh 同形
    base_lag  : [带] 每个带估计出的基频所在滞后（bin），-1 表示没找到
    """
    scoh = np.asarray(scoh, dtype=float)
    n_bands, n_alpha = scoh.shape
    energy = scoh ** 2

    ppfm = np.zeros_like(energy)
    base_lag = np.full(n_bands, -1, dtype=int)

    for b in range(n_bands):
        e = energy[b]
        e = e - e.mean()                       # 去均值：否则自相关被 DC 拖住，首峰落在 2~4 Hz
        if not np.any(e):
            continue
        # 零填充的线性自相关：用 irfft(e, n) 是循环相关，大滞后处会因回绕冒出伪峰
        m = 2 * n_alpha
        spec = np.fft.rfft(e, m)
        ac = np.fft.irfft(spec * np.conj(spec), m)[:n_alpha]
        ac = ac / (n_alpha - np.arange(n_alpha))   # 按重叠点数做无偏归一
        if ac[0] <= 0:
            continue
        ac = ac / ac[0]

        stop = n_alpha // 2 if max_lag is None else min(n_alpha, max_lag)
        seg = ac[min_lag:stop]
        if not seg.size:
            continue
        # 首个过零之后找最大峰：过零之前是主瓣，容易把 DC 泄漏当成周期
        sign = np.sign(seg)
        zero = np.where((sign[:-1] > 0) & (sign[1:] <= 0))[0]
        start = zero[0] + 1 if zero.size else 0
        if start >= seg.size:
            continue
        lag = start + int(np.argmax(seg[start:])) + min_lag
        if lag <= 0 or ac[lag] <= peak_ratio:
            continue
        base_lag[b] = lag

        for k in range(1, max_harm + 1):
            pos = lag * k
            if pos >= n_alpha:
                break
            ppfm[b, pos] = max(ppfm[b, pos], ac[pos])

    return ppfm, base_lag


# --------------------------------------------------------------------------
# 3. 两个方向的权重 -> 增强谱相干
# --------------------------------------------------------------------------
def enhance(scoh, ppfm):
    """谱频率权重（逐带）与循环频率权重（逐循环频率）合成二维权重。

    循环频率一侧用指数变换：自相关有负值、且大量位置被置零，
    线性加权会被大片零压掉，指数变换能把「共同出现的周期峰」抬出来。
    """
    scoh = np.asarray(scoh, dtype=float)
    ppfm = np.asarray(ppfm, dtype=float)
    if scoh.shape != ppfm.shape:
        raise ValueError("scoh 与 ppfm 的形状必须一致")

    sf = ppfm.sum(axis=1)                 # 每个带的周期峰强度
    sf = sf / (sf.sum() + 1e-12)

    cf_raw = ppfm.sum(axis=0)             # 每个循环频率上的周期峰强度
    cf = np.exp(cf_raw - cf_raw.max())
    cf = cf / (cf.sum() + 1e-12)

    enhanced = scoh * np.outer(sf, cf)
    return enhanced, sf, cf


# --------------------------------------------------------------------------
# 4. EFDSNR + 阈值 + 多模式输出
# --------------------------------------------------------------------------
def efdsnr_per_band(enhanced, base_lag, max_harm=5, eps=1e-12):
    """每个频带：目标谐波能量 / 其余循环频率能量。

    用 PPFM 估出来的基频（而不是理论故障频率），所以实际冲击频率有偏移时仍可用。
    """
    enhanced = np.asarray(enhanced, dtype=float)
    n_bands, n_alpha = enhanced.shape
    out = np.zeros(n_bands)

    for b in range(n_bands):
        lag = base_lag[b]
        if lag <= 0:
            continue
        idx = lag * np.arange(1, max_harm + 1)
        idx = idx[idx < n_alpha]
        if idx.size == 0 or idx.size >= n_alpha:
            continue
        target = enhanced[b, idx].mean()
        background = (enhanced[b].sum() - enhanced[b, idx].sum()) / (n_alpha - idx.size)
        out[b] = target / (background + eps)

    return out


def awees(scoh, alpha, centers, ppfm, base_lag, max_harm=5,
          beta=0.5, max_modes=3, tol=0.06):
    """按阈值选频带，再按**估计出的故障频率**把频带聚成故障模式。

    为什么按故障频率分组，而不是按相邻频带
    --------------------------------------
    论文的"模式"对应的是不同故障分量（外圈/内圈/保持架…），它们可能落在
    完全不相邻的共振频带上。按频带相邻聚类会把同一个故障拆成几段，
    反而丢掉"基频 + 倍频成组出现"这个最有诊断价值的证据。

    返回
    ----
    modes : list[dict]，每项含 spectrum / fault_hz / bands / efdsnr
    """
    enhanced, sf, cf = enhance(scoh, ppfm)
    efdsnr = efdsnr_per_band(enhanced, base_lag, max_harm=max_harm)

    positive = efdsnr[efdsnr > 0]
    if positive.size == 0:
        return [], enhanced, efdsnr
    thr = float(np.sqrt(np.mean(positive ** 2)) + beta * np.std(positive))
    mask = (efdsnr >= thr) & (base_lag > 0)
    if not np.any(mask):
        return [], enhanced, efdsnr

    # 按估计故障频率分组：频率相差在 tol 以内、或成整数倍关系，视为同一故障分量。
    # 为什么要处理倍数：PPFM 里记录的是基频的整数倍位置，逐带找峰时可能落到
    # 2×/3× 上（例如 104.5 Hz 其实是 52 Hz 的二倍），不折回就会把同一个故障
    # 拆成多个"模式"。
    cand = np.where(mask)[0]
    cand = cand[np.argsort(efdsnr[cand])[::-1]]        # 强的先占组
    bin_hz = float(alpha[1] - alpha[0])

    def fold_to_base(f_hz, existing):
        best = f_hz
        for g in existing:
            for k in (1, 2, 3, 4, 5):
                if abs(f_hz - k * g[0]) <= tol * k * max(g[0], 1.0):
                    return g[0]
                if abs(k * f_hz - g[0]) <= tol * max(g[0], 1.0):
                    return best if best != f_hz else f_hz / k
        return best

    groups = []                                        # [(fault_hz, [bands])]
    for b in cand:
        f_hz = float(base_lag[b]) * bin_hz
        folded = fold_to_base(f_hz, groups)
        placed = False
        for g in groups:
            if abs(folded - g[0]) <= tol * max(g[0], 1.0):
                g[1].append(int(b))
                placed = True
                break
        if not placed:
            groups.append((folded, [int(b)]))

    groups.sort(key=lambda g: -np.mean([efdsnr[b] for b in g[1]]))
    modes = []
    for f_hz, bands in groups[:max_modes]:
        w = np.zeros(len(efdsnr))
        for b in bands:
            w[b] = efdsnr[b]
        spectrum = (np.abs(enhanced) * w[:, None]).sum(axis=0)
        freqs = [float(centers[b]) for b in bands]
        modes.append({
            "fault_hz": f_hz,
            "bands": bands,
            "freq_range": (min(freqs), max(freqs)),
            "spectrum": spectrum,
            "efdsnr": float(np.mean([efdsnr[b] for b in bands])),
        })

    return modes, enhanced, efdsnr


# --------------------------------------------------------------------------
# 5. 一键入口
# --------------------------------------------------------------------------
def analyze(x, fs, win=128, hop=None, n_bands=48, max_harm=5, beta=0.5, max_modes=3):
    """信号 -> (模式列表, 循环频率轴, 谱相干, EFDSNR)。"""
    scoh, alpha, centers = spectral_coherence(x, fs, win=win, hop=hop, n_bands=n_bands)
    ppfm, base_lag = ppfm_from_scoh(scoh, max_harm=max_harm)
    modes, enhanced, efdsnr = awees(scoh, alpha, centers, ppfm, base_lag,
                                    max_harm=max_harm, beta=beta, max_modes=max_modes)
    return modes, alpha, scoh, efdsnr

def simulate(fs=20000, n=20000, f_outer=50.0, f_inner=80.0,
             res_outer=3500.0, res_inner=5000.0, snr_db=-18.0, seed=0):
    """论文 §3.1 的仿真：两个故障冲击 + 周期谐波干扰 + 高斯白噪声。"""
    rng = np.random.default_rng(seed)
    t = np.arange(n) / fs

    def impulse_train(f0, res, decay=0.01):
        sig = np.zeros(n)
        period = int(round(fs / f0))
        burst_len = int(0.02 * fs)
        tt = np.arange(burst_len) / fs
        burst = np.exp(-decay * fs * tt) * np.sin(2 * np.pi * res * tt)
        for k in range(0, n - burst_len, period):
            s = k + int(rng.integers(-2, 3))
            if 0 <= s < n - burst_len:
                sig[s:s + burst_len] += burst
        return sig

    outer = impulse_train(f_outer, res_outer)
    inner = impulse_train(f_inner, res_inner)
    hum = 0.3 * np.sin(2 * np.pi * 25 * t) + 0.2 * np.sin(2 * np.pi * 100 * t)

    clean = outer + inner + hum
    p_sig = np.mean(clean ** 2)
    p_noise = p_sig / (10 ** (snr_db / 10.0))
    noise = rng.normal(0, np.sqrt(p_noise), n)
    return clean + noise


def _peak_near(spec, alpha, target, tol=2.0):
    lo = np.searchsorted(alpha, target - tol)
    hi = np.searchsorted(alpha, target + tol)
    if hi <= lo:
        return 0.0, float("nan")
    i = lo + int(np.argmax(spec[lo:hi]))
    return float(spec[i]), float(alpha[i])


def main(argv=None):
    ap = argparse.ArgumentParser(description="AWEES 自相关加权增强包络谱")
    ap.add_argument("--demo", action="store_true", help="跑论文仿真并打印结果")
    ap.add_argument("--csv", help="单列振动 CSV")
    ap.add_argument("--fs", type=float, default=20000.0)
    ap.add_argument("--beta", type=float, default=0.5)
    args = ap.parse_args(argv)

    if args.demo:
        x = simulate(fs=args.fs)
        modes, alpha, scoh, efdsnr = analyze(x, args.fs, beta=args.beta)
        print(f"信号: {len(x)} 点 @ {args.fs:.0f} Hz，模式数 {len(modes)}")
        for i, m in enumerate(modes):
            spec = m["spectrum"]
            base = np.median(spec) + 1e-12
            p50, a50 = _peak_near(spec, alpha, 50.0)
            p80, a80 = _peak_near(spec, alpha, 80.0)
            print(f"  模式{i+1}: 估计故障频率 {m['fault_hz']:5.1f} Hz | "
                  f"频带 {m['freq_range'][0]:.0f}-{m['freq_range'][1]:.0f} Hz | "
                  f"50Hz {p50/base:5.1f}x @{a50:.0f}Hz | 80Hz {p80/base:5.1f}x @{a80:.0f}Hz")
        return 0

    if args.csv:
        data = np.loadtxt(args.csv, delimiter=",", ndmin=1)
        x = np.asarray(data, dtype=float).ravel()
        modes, alpha, scoh, efdsnr = analyze(x, args.fs, beta=args.beta)
        for i, m in enumerate(modes):
            top = np.argsort(m["spectrum"])[-5:][::-1]
            print(f"模式{i+1} 频带 {m['freq_range'][0]:.0f}-{m['freq_range'][1]:.0f} Hz  "
                  f"峰: " + ", ".join(f"{alpha[j]:.1f}Hz" for j in top))
        return 0

    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
