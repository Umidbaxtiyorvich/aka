"""JARVIS belgisi (ICO) yasaydi: binafsha-ko'k gradient doira, oq "J" harfi. Pillow kerak.
Ishlatish: python scripts/make_icon.py <chiqish.ico>"""
import sys

from PIL import Image, ImageDraw, ImageFont


def make(path: str) -> None:
    n = 256
    img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    grad = Image.new("RGBA", (n, n))
    px = grad.load()
    a, b = (79, 70, 229), (14, 165, 233)            # indigo → osmon ko'k
    for y in range(n):
        for x in range(n):
            t = (x + y) / (2 * n - 2)
            px[x, y] = tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3)) + (255,)
    mask = Image.new("L", (n, n), 0)
    ImageDraw.Draw(mask).rounded_rectangle([8, 8, n - 8, n - 8], radius=64, fill=255)
    img.paste(grad, (0, 0), mask)
    d = ImageDraw.Draw(img)
    font = None
    for name in ("segoeuib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf"):
        try:
            font = ImageFont.truetype(name, 170)
            break
        except OSError:
            continue
    font = font or ImageFont.load_default()
    box = d.textbbox((0, 0), "J", font=font)
    d.text(((n - (box[2] - box[0])) / 2 - box[0], (n - (box[3] - box[1])) / 2 - box[1]), "J", font=font, fill="white")
    img.save(path, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])


if __name__ == "__main__":
    make(sys.argv[1] if len(sys.argv) > 1 else "jarvis.ico")
