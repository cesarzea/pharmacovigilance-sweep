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
FOOTER_H = 200   # footer band: identity on the left, timed subtitles on the right


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


LOCAL_FONTS = Path("docs/demo/fonts")   # the site's own fonts, converted from woff2 (git-ignored)
LOCAL = {  # (family, style word) -> (file prefix, variation axes)
    ("Fraunces", ""): ("Fraunces-normal", {"wght": 380, "opsz": 72}),
    ("Fraunces", "Italic"): ("Fraunces-italic", {"wght": 380, "opsz": 72}),
    ("Inter Tight", ""): ("InterTight-normal", {"wght": 400}),
    ("JetBrains Mono", ""): ("JetBrainsMono-normal", {"wght": 400}),
}


def load(candidates: list[str], size: int, style: str = "", index: int = 0) -> ImageFont.FreeTypeFont:
    wanted = "Italic" if "Italic" in style else ""
    for family in candidates:
        if (family, wanted) in LOCAL and LOCAL_FONTS.is_dir():
            prefix, axes = LOCAL[(family, wanted)]
            files = sorted(LOCAL_FONTS.glob(prefix + "*.ttf"))
            if files:
                f = ImageFont.truetype(str(files[0]), size=size)
                try:
                    names = [a["name"].decode() if isinstance(a["name"], bytes) else a["name"] for a in f.get_variation_axes()]
                    f.set_variation_by_axes([axes.get(n.lower()[:4], axes.get(n, 400)) if n.lower().startswith(("wght", "weight")) else
                                             (axes.get("opsz", 72) if n.lower().startswith(("opsz", "optical")) else 0) for n in names])
                except Exception:  # noqa: BLE001 - static font or no variation support in this build
                    pass
                return f
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


CAPTIONS = True   # False when the caption is burned in later as timed subtitles (make_demo_audio.py)
HEADER = "A Pharma AI Foundry, Snowflake and Databricks POC"   # running header at the top of every frame


def footer(im: Image.Image, d: ImageDraw.ImageDraw, caption: str, portrait: Path | None, frame_no: int, total: int) -> None:
    if not CAPTIONS:
        caption = ""
    y0 = H - FOOTER_H
    d.line([(0, y0), (W, y0)], fill=(40, 40, 46), width=1)
    r = 48
    cx, cy = 96 + r, y0 + FOOTER_H // 2
    if portrait and portrait.is_file():
        p = Image.open(portrait).convert("RGB")
        # the site's portrait is a wide frame with the face right of centre; crop a square around it
        side = int(p.height * 0.72)
        fx, fy = int(p.width * 0.70), int(p.height * 0.40)
        box = (max(0, fx - side // 2), max(0, fy - side // 2))
        p = p.crop((box[0], box[1], box[0] + side, box[1] + side)).resize((2 * r, 2 * r), Image.LANCZOS)
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
    d.text((96, 48), HEADER.upper(), font=load(MONO, 22), fill=MUTED, anchor="la")


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
    ital = load(SERIF, 104, "Light Italic")
    d.text((96, 560), "A Microsoft AI Foundry,", font=ital, fill=GOLD)
    d.text((96, 675), "Snowflake and Databricks POC.", font=ital, fill=GOLD)
    small = load(MONO, 24)
    d.text((96, 840), "GPT AND CLAUDE  ·  HOSTED AGENTS  ·  MODELS PROPOSE, A PERSON DECIDES", font=small, fill=MUTED)
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


def frame_02(portrait: Path | None, total: int) -> Image.Image:
    im, d = canvas()
    label(d, (96, 120), "What the solution does")
    d.text((96, 190), "Re-read every record.", font=load(SERIF, 92, "Light"), fill=INK)
    d.text((96, 300), "Keep what PV never received.", font=load(SERIF, 92, "Light Italic"), fill=GOLD)
    steps = [("1", "Screen", "adverse event or special situation?"), ("2", "Extract", "case facts with evidence quotes"),
             ("3", "Rules", "ownership, seriousness, day 0, deadlines"), ("4", "Match", "agent checks what PV already holds"),
             ("5", "Finding", "priority and proposed intake package"), ("6", "Reconcile", "vendor logs vs what PV received")]
    x, y, cw, ch, gap = 96, 470, 280, 260, 20
    for n, title, desc in steps:
        d.rounded_rectangle([x, y, x + cw, y + ch], radius=14, fill=CARD, outline=(44, 44, 52), width=1)
        d.text((x + 24, y + 22), n, font=load(SERIF, 56, "Light"), fill=GOLD)
        d.text((x + 24, y + 110), title, font=load(SANS, 34), fill=INK)
        yy = y + 158
        for ln in wrap(d, desc, load(SANS, 26), cw - 48):
            d.text((x + 24, yy), ln, font=load(SANS, 26), fill=MUTED)
            yy += 34
        if n != "6":
            d.text((x + cw + gap // 2, y + ch // 2), "›", font=load(SANS, 30), fill=(70, 70, 78), anchor="mm")
        x += cw + gap
    body = load(SANS, 34)
    for i, ln in enumerate(wrap(d, "A pharmacovigilance reviewer works the prioritised queue in a review app and records the outcome. "
                                   "Nothing is closed by a model.", body, 1560)):
        d.text((96, 790 + i * 46), ln, font=body, fill=INK)
    footer(im, d, "Screen, extract, apply the rules, match, produce the finding, reconcile", portrait, 2, total)
    return im


def frame_10(portrait: Path | None, total: int) -> Image.Image:
    im, d = canvas()
    label(d, (96, 120), "Results · 450 synthetic records · round 3")
    d.text((96, 190), "Measured,", font=load(SERIF, 92, "Light"), fill=INK)
    d.text((96, 300), "not assumed.", font=load(SERIF, 92, "Light Italic"), fill=GOLD)
    rows = [("", "GPT", "Claude on Foundry"), ("Screening recall", "0.997", "0.976"), ("Extraction valid", "0.995", "1.000"),
            ("Causality statement", "0.901", "0.938"), ("Matching outcome", "0.835", "0.954"), ("Model cost per sweep", "about $11", "about $11")]
    x0, y0, rh = 96, 460, 58
    cols = [x0, x0 + 620, x0 + 980]
    for i, (a, b, c) in enumerate(rows):
        yy = y0 + i * rh
        fnt = load(MONO, 24) if i == 0 else load(SANS, 32)
        col = GOLD if i == 0 else INK
        d.text((cols[0], yy), a, font=fnt, fill=col)
        d.text((cols[1], yy), b, font=fnt, fill=col)
        d.text((cols[2], yy), c, font=fnt, fill=col)
        if i == 0:
            d.line([(x0, yy + 44), (x0 + 1300, yy + 44)], fill=(60, 60, 68), width=1)
    d.text((96, 830), "Deployable from scratch by the scripts in the repository.", font=load(SANS, 34), fill=INK)
    d.text((96, 880), "github.com/cesarzea/pharmacovigilance-sweep", font=load(MONO, 30), fill=GOLD)
    footer(im, d, "Models propose. A person decides.", portrait, 10, total)
    return im


FRAMES = {0: frame_00, 1: frame_01, 2: frame_02, 10: frame_10}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", default=",".join(str(k) for k in FRAMES))
    ap.add_argument("--portrait", default="", help="optional photo for the circle; by default the circle shows the initials")
    ap.add_argument("--total", type=int, default=11)
    ap.add_argument("--no-captions", action="store_true", help="leave the footer free for karaoke subtitles")
    args = ap.parse_args()
    global CAPTIONS
    if args.no_captions:
        CAPTIONS = False
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
