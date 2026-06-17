"""One-time: convert the owner-provided PNG into a multi-resolution Windows .ico.

Run:  python scripts/make_icon.py
Reads  installer/source-icon.png  ->  writes  installer/StockAdvisor.ico
A multi-size .ico lets Windows pick the crisp variant for the taskbar, Start Menu,
desktop shortcut, and Alt-Tab. The .ico is committed so the build needs no Pillow.
"""
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "installer" / "source-icon.png"
OUT = ROOT / "installer" / "StockAdvisor.ico"
SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]


def main() -> None:
    img = Image.open(SRC).convert("RGBA")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUT, format="ICO", sizes=SIZES)
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
