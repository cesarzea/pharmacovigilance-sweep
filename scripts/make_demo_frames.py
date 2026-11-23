"""Render the slide frames of the demo (docs/demo/script.md) in the visual style of cesarzea.com:
near-black background with a faint grid, light serif display type with one italic line in gold, small
mono labels with a gold dot, and a footer with a round portrait, the site URL and the frame caption.

    uv run --no-project --with pillow python -I scripts/make_demo_frames.py [--frames 0,1] [--portrait path]

Fonts: Fraunces, Inter Tight and JetBrains Mono when installed (the site's fonts); otherwise the site's
own fallbacks (Iowan Old Style / Georgia, Inter, Menlo). Output: docs/demo/frames/NN-*.png at 1920x1080.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 1920, 1080
BG = (11, 11, 14)
INK = (232, 229, 221)
GOLD = (232, 182, 107)
MUTED = (160, 156, 146)
GREEN = (62, 207, 142)
GRID = (26, 26, 32)
CARD = (21, 21, 26)
SITE = "cesarzea.com"
OUT = Path("docs/demo/frames")


def font_file(candidates: list[str], style: str = "") -> tuple[str, int] | None:
    """First installed font among the candidates (fc-list) as (file, face index); the style word is tried
    first (e.g. "Light Italic"), then "Italic" alone when the style asked for one, then any face."""
    styles = [style] if style else []
    if "Italic" in style:
        styles.append("Italic")
    styles.append("")
    for family in candidates:
        for st in styles:
            pattern = f"{family}:style={st}" if st else family
            try:
                out = subprocess.run(["fc-list", pattern, "file", "index"], capture_output=True, text=True, check=False).stdout
            except FileNotFoundError:
                return None
            rows = []
            for ln in out.splitlines():
                if ":" not in ln:
                    continue
                path, _, rest = ln.partition(":")
                idx = 0
                for part in rest.split(":"):
                    if part.strip().startswith("index="):
                        idx = int(part.strip()[6:])
                rows.append((path, idx))
            if rows:
                rows.sort(key=lambda r: (r[0].lower().endswith(".ttc"), r[0], r[1]))
                return rows[0]
    return None


def load(candidates: list[str], size: int, style: str = "", index: int = 0) -> ImageFont.FreeTypeFont:
    found = font_file(candidates, style)
    if found is None:
        return ImageFont.load_default(size=size)
    path, idx = found
    try:
        return ImageFont.truetype(path, size=size, index=idx)
    except OSError:
        return ImageFont.truetype(path, size=size)


SERIF = ["Fraunces", "Iowan Old Style", "Georgia"]
SANS = ["Inter Tight", "Inter", "Helvetica Neue"]
MONO = ["JetBrains Mono", "IBM Plex Mono", "Menlo"]


def canvas() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    for x in range(0, W, 120):
        d.line([(x, 0), (x, H)], fill=GRID, width=1)
    for y in range(0, H, 120):
        d.line([(0, y), (W, y)], fill=GRID, width=1)
    return im, d


def label(d: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, size: int = 22, color=INK) -> None:
    x, y = xy
    d.ellipse([x, y + size // 2 - 5, x + 10, y + size // 2 + 5], fill=GOLD)
    d.text((x + 24, y), text.upper(), font=load(MONO, size), fill=color)


def footer(im: Image.Image, d: ImageDraw.ImageDraw, caption: str, portrait: Path | None, frame_no: int, total: int) -> None:
    y0 = H - 150
    d.line([(0, y0), (W, y0)], fill=(40, 40, 46), width=1)
    r = 48
    cx, cy = 96 + r, y0 + 75
    if portrait and portrait.is_file():
        p = Image.open(portrait).convert("RGB")
        side = min(p.size)
        p = p.crop(((p.width - side) // 2, 0, (p.width - side) // 2 + side, side)).resize((2 * r, 2 * r), Image.LANCZOS)
        mask = Image.new("L", (2 * r, 2 * r), 0)
        ImageDraw.Draw(mask).ellipse([0, 0, 2 * r - 1, 2 * r - 1], fill=255)
        im.paste(p, (cx - r, cy - r), mask)
    else:
        d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=GOLD, width=2)
        d.text((cx, cy), "CZ", font=load(SERIF, 34), fill=GOLD, anchor="mm")
    d.ellipse([cx - r - 3, cy - r - 3, cx + r + 3, cy + r + 3], outline=GOLD, width=2)
    d.text((cx + r + 28, cy - 26), "César Zea", font=load(SANS, 30), fill=INK)
    d.text((cx + r + 28, cy + 10), SITE, font=load(MONO, 22), fill=GOLD)
    cap_font = load(SANS, 30)
    d.text((W - 96, cy), caption, font=cap_font, fill=INK, anchor="rm")
    d.text((W - 96, 48), f"{frame_no:02d} / {total:02d}", font=load(MONO, 22), fill=MUTED, anchor="ra")


def wrap(d: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_w: int) -> list[str]:
    words, lines, line = text.split(), [], ""
    for w_ in words:
        probe = (line + " " + w_).strip()
        if d.textlength(probe, font=font) <= max_w:
            line = probe
        else:
            lines.append(line)
            line = w_
    if line:
        lines.append(line)
    return lines


def frame_00(portrait: Path | None, total: int) -> Image.Image:
    im, d = canvas()
    label(d, (96, 120), "Proof of concept · Pharmacovigilance · EU")
    big = load(SERIF, 150, "Light")
    d.text((96, 220), "Pharmacovigilance", font=big, fill=INK)
    d.text((96, 380), "Sweep.", font=big, fill=INK)
    ital = load(SERIF, 112, "Light Italic")
    d.text((96, 560), "Models propose.", font=ital, fill=GOLD)
    d.text((96, 680), "A person decides.", font=ital, fill=GOLD)
    small = load(MONO, 24)
    d.text((96, 840), "MICROSOFT FOUNDRY  ·  SNOWFLAKE  ·  AZURE DATABRICKS  ·  GPT AND CLAUDE", font=small, fill=MUTED)
    footer(im, d, "An agentic sweep for adverse events pharmacovigilance never received", portrait, 0, total)
    return im


def frame_01(portrait: Path | None, total: int) -> Image.Image:
    im, d = canvas()
    label(d, (96, 120), "The problem")
    head = load(SERIF, 92, "Light")
    d.text((96, 190), "Side effects are mentioned", font=head, fill=INK)
    ital = load(SERIF, 92, "Light Italic")
    d.text((96, 300), "where pharmacovigilance does not look.", font=ital, fill=GOLD)
    channels = [("MI", "Medical", "information calls"), ("CRM", "Field force", "visit notes"),
                ("PSP", "Patient support", "nurse notes"), ("PQC", "Quality", "complaints"), ("SOCIAL", "Social", "listening")]
    x, y, cw, ch, gap = 96, 470, 268, 250, 20
    for code, line1, line2 in channels:
        d.rounded_rectangle([x, y, x + cw, y + ch], radius=14, fill=CARD, outline=(44, 44, 52), width=1)
        d.text((x + 24, y + 22), code, font=load(MONO, 22), fill=GOLD)
        d.text((x + 24, y + 100), line1, font=load(SANS, 30), fill=INK)
        d.text((x + 24, y + 142), line2, font=load(SANS, 30), fill=MUTED)
        x += cw + gap
    # the regulatory clock, in the space left on the right
    cx, cy, r = x + (W - 96 - x) // 2, 470 + ch // 2, 110
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=GOLD, width=4)
    d.text((cx, cy - 30), "15", font=load(SERIF, 96, "Light"), fill=INK, anchor="mm")
    d.text((cx, cy + 50), "DAYS", font=load(MONO, 22), fill=GOLD, anchor="mm")
    body = load(SANS, 34)
    text = ("Under GVP Module VI the company answers for every one of these channels. The 15-day clock for a serious case "
            "starts the day anyone in the company, or a vendor working for it, first hears of it.")
    yy = 790
    for ln in wrap(d, text, body, 1560):
        d.text((96, yy), ln, font=body, fill=INK)
        yy += 46
    footer(im, d, "Records that stay in those channels are late, or missing, when an inspector asks", portrait, 1, total)
    return im


FRAMES = {0: frame_00, 1: frame_01}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", default=",".join(str(k) for k in FRAMES))
    ap.add_argument("--portrait", default="docs/demo/portrait.png", help="square-ish photo; a placeholder is drawn when missing")
    ap.add_argument("--total", type=int, default=11)
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    portrait = Path(args.portrait)
    for n in [int(x) for x in args.frames.split(",") if x.strip()]:
        im = FRAMES[n](portrait if portrait.is_file() else None, args.total)
        path = OUT / f"{n:02d}.png"
        im.save(path, optimize=True)
        print(path, im.size)
    return 0


if __name__ == "__main__":
    sys.exit(main())
