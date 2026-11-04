"""Put page screenshots into a Kindle-style bezel, side by side (prototype).

usage: python device_frame.py out.png page1.png page2.png ...
Screens are converted to grayscale with a paper tint to approximate e-ink.
"""
import sys
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps


def device(path):
    sc = ImageOps.autocontrast(Image.open(path).convert("L"))
    sc = Image.composite(Image.new("RGB", sc.size, (236, 235, 229)), Image.new("RGB", sc.size, (22, 22, 24)), sc)
    w, h = sc.size
    bz = bot = 110
    dw, dh = w + 2 * bz, h + bz + bot
    dev = Image.new("RGBA", (dw + 80, dh + 80), (0, 0, 0, 0))
    sh = Image.new("RGBA", dev.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle((40, 55, 40 + dw, 55 + dh), 90, fill=(0, 0, 0, 120))
    dev.alpha_composite(sh.filter(ImageFilter.GaussianBlur(28)))
    d = ImageDraw.Draw(dev)
    d.rounded_rectangle((40, 40, 40 + dw, 40 + dh), 90, fill=(28, 28, 30))
    d.rounded_rectangle((44, 44, 36 + dw, 36 + dh), 86, outline=(55, 55, 58), width=3)
    dev.paste(sc, (40 + bz, 40 + bz))
    d.rectangle((40 + bz - 2, 40 + bz - 2, 40 + bz + w + 1, 40 + bz + h + 1), outline=(10, 10, 10), width=3)
    try:
        f = ImageFont.truetype("DejaVuSans.ttf", 34)
    except OSError:
        f = ImageFont.load_default()
    d.text((40 + dw / 2, 40 + dh - bot / 2), "kindle", font=f, fill=(120, 120, 124), anchor="mm")
    return dev


out, pages = sys.argv[1], sys.argv[2:]
devs = [device(p) for p in pages]
w, h = devs[0].size
canvas = Image.new("RGB", (w * len(devs) + 40 + 5 * (len(devs) - 1), h + 40), (246, 246, 244))
for i, dv in enumerate(devs):
    canvas.paste(dv, (20 + i * (w + 5), 20), dv)
canvas.resize((canvas.width // 2, canvas.height // 2), Image.LANCZOS).save(out)
print("wrote", out)
