"""Draw the app icon: the letters "CR" on a dark rounded tile (no logo, design v2) → assets/icon.ico + icon.png."""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
S = 1024
CARD, BORDER, TEXT, GREEN = (18, 20, 26, 255), (42, 46, 56, 255), (242, 244, 248, 255), (74, 222, 128, 255)


def font(size: int) -> ImageFont.FreeTypeFont:
    for p in (ROOT / "static" / "fonts" / "PlusJakartaSans.ttf", Path(r"C:\Windows\Fonts\segoeuib.ttf"), Path(r"C:\Windows\Fonts\arialbd.ttf")):
        if p.exists():
            f = ImageFont.truetype(str(p), size)
            try:
                f.set_variation_by_axes([700])  # variable font: bold
            except (OSError, AttributeError):
                pass
            return f
    return ImageFont.load_default(size)


img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
d.rounded_rectangle([40, 40, S - 40, S - 40], radius=220, fill=CARD, outline=BORDER, width=14)
d.rounded_rectangle([200, S - 190, S - 420, S - 160], radius=15, fill=GREEN)  # the design's fading accent line, as a short bar
f = font(470)
l, t, r, b = d.textbbox((0, 0), "CR", font=f)
d.text(((S - (r - l)) / 2 - l, (S - (b - t)) / 2 - t - 30), "CR", font=f, fill=TEXT)

out = ROOT / "assets"
out.mkdir(exist_ok=True)
img.save(out / "icon.png")
img.save(out / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print("wrote", out / "icon.ico")
