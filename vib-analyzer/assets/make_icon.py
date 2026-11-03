"""生成 VibSpec 的应用图标（与 OilLab 的蓝底圆角 + 金色点睛同一视觉家族）。

输出：
  vib-analyzer/assets/app.png   256x256 预览
  vib-analyzer/assets/app.ico   多尺寸（256/128/64/48/32/16）

设计：深蓝渐变圆角方底 + 白色频谱柱（FFT 形态）+ 一根金色峰值柱 + 细基线。
4x 超采样后缩小，保证小尺寸边缘干净。
"""
from PIL import Image, ImageDraw

S = 4                     # 超采样倍数
W = 256 * S
BG_TOP = (22, 50, 79)     # #16324F
BG_BOT = (38, 106, 160)   # #266AA0
WHITE = (255, 255, 255)
GOLD = (232, 181, 74)     # #E8B54A，与 OilLab 油滴同色
GOLD_DEEP = (198, 148, 52)


def lerp(a, b, t):
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def rounded_mask(size, radius):
    m = Image.new("L", (size, size), 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=255)
    return m


def make(size):
    # 竖向渐变底
    bg = Image.new("RGB", (1, size))
    px = bg.load()
    for y in range(size):
        px[0, y] = lerp(BG_TOP, BG_BOT, y / max(1, size - 1))
    bg = bg.resize((size, size))

    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)

    # 频谱柱：模拟衰减的 FFT（低次谐波高，高频低）
    heights = [0.30, 0.52, 0.86, 0.46, 0.62, 0.38, 0.26, 0.44, 0.20, 0.30, 0.16]
    peak = 2                                  # 金色高峰所在索引
    n = len(heights)
    margin = size * 0.17
    usable = size - 2 * margin
    bar_w = usable / (n * 1.55)
    gap = (usable - bar_w * n) / max(1, n - 1)
    base_y = size * 0.74
    top_lim = size * 0.26

    for i, h in enumerate(heights):
        x0 = margin + i * (bar_w + gap)
        x1 = x0 + bar_w
        y0 = base_y - (base_y - top_lim) * h
        color = GOLD if i == peak else WHITE
        alpha = 255 if i == peak else 232
        d.rounded_rectangle([x0, y0, x1, base_y], radius=bar_w * 0.34,
                            fill=color + (alpha,))

    # 基线
    d.rounded_rectangle([margin * 0.75, base_y, size - margin * 0.75, base_y + max(2, size * 0.012)],
                        radius=size * 0.006, fill=WHITE + (150,))

    # 峰值标记：小圆点 + 细引线（呼应 OilLab 的趋势线）
    px0 = margin + peak * (bar_w + gap)
    py0 = base_y - (base_y - top_lim) * heights[peak]
    cx = px0 + bar_w / 2
    cy = py0 - size * 0.055
    r = size * 0.019
    d.line([(cx, cy + r), (cx, py0)], fill=GOLD + (220,), width=max(2, int(size * 0.008)))
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=GOLD + (255,))

    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(bg, (0, 0))
    out.alpha_composite(layer)
    out.putalpha(rounded_mask(size, int(size * 0.225)))
    return out


def main():
    import os, sys
    outdir = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.abspath(__file__))
    big = make(W)
    png = big.resize((256, 256), Image.LANCZOS)
    png.save(outdir + r"\app.png")
    sizes = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]
    frames = [big.resize(s, Image.LANCZOS) for s in sizes]
    frames[0].save(outdir + r"\app.ico", format="ICO", sizes=sizes,
                   append_images=frames[1:])
    print("written:", outdir + r"\app.png", outdir + r"\app.ico")


if __name__ == "__main__":
    main()
