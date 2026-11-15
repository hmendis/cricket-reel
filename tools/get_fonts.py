"""Download the UI fonts (SIL Open Font License) into static/fonts. Run once during setup."""
import urllib.request
from pathlib import Path

BASE = "https://raw.githubusercontent.com/google/fonts/main/ofl/"
FILES = {
    "BarlowCondensed-Medium.ttf": "barlowcondensed/BarlowCondensed-Medium.ttf",
    "BarlowCondensed-SemiBold.ttf": "barlowcondensed/BarlowCondensed-SemiBold.ttf",
    "JetBrainsMono.ttf": "jetbrainsmono/JetBrainsMono%5Bwght%5D.ttf",
    # Text you put on the reel (Arrange) and the app's own interface (Plus Jakarta Sans, design v2)
    "BebasNeue-Regular.ttf": "bebasneue/BebasNeue-Regular.ttf",
    "Oswald.ttf": "oswald/Oswald%5Bwght%5D.ttf",
    "PlusJakartaSans.ttf": "plusjakartasans/PlusJakartaSans%5Bwght%5D.ttf",
    "OFL-BebasNeue.txt": "bebasneue/OFL.txt",
    "OFL-Oswald.txt": "oswald/OFL.txt",
    "OFL-PlusJakartaSans.txt": "plusjakartasans/OFL.txt",
    "OFL-Barlow.txt": "barlow/OFL.txt",
    "OFL-JetBrainsMono.txt": "jetbrainsmono/OFL.txt",
}

out = Path(__file__).resolve().parent.parent / "static" / "fonts"
out.mkdir(parents=True, exist_ok=True)
for name, path in FILES.items():
    dest = out / name
    if dest.exists() and dest.stat().st_size > 0:
        print("ok      ", name)
        continue
    urllib.request.urlretrieve(BASE + path, dest)
    print("fetched ", name, dest.stat().st_size, "bytes")
