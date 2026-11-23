"""Assemble the demo (docs/demo/script.md) from the rendered slides, the screenshots and the recorded
clip into a silent GIF for the README and an MP4 (narration is added by scripts/make_demo_audio.py when
an ElevenLabs key is available; without audio the MP4 is silent).

    uv run --no-project --with pillow python -I scripts/make_demo_video.py [--seconds 6] [--gif-width 1280]

Inputs (docs/demo/frames/): NN.png slides from make_demo_frames.py; shots/NN-*.jpg screenshots and
shots/07-decision-flow.gif. Screenshots are placed on the slide background with the same footer and
caption as the slides. A missing screenshot renders a placeholder slide so the pipeline can run before
every capture exists. Outputs: docs/demo/frames/NN.png for every frame, docs/demo/demo.gif, docs/demo/demo.mp4.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from make_demo_frames import GOLD, MUTED, SANS, SERIF, W, H, canvas, footer, label, load  # noqa: E402

FRAMES = Path("docs/demo/frames")
SHOTS = Path("docs/demo/frames/shots")
OUT = Path("docs/demo")
SCRIPT = Path("docs/demo/script.md")

# frame number -> (screenshot glob, section label)
SHOT_FRAMES = {
    3: ("03-*.jpg", "Microsoft Foundry · model deployments"),
    4: ("04-*.jpg", "Microsoft Foundry · hosted agents"),
    5: ("05-*.jpg", "Snowflake · the agent's views"),
    6: ("06-*.jpg", "Snowflake · review app"),
    7: ("07-decision-flow.gif", "Snowflake · recording a decision"),
    8: ("08-*.jpg", "Microsoft Foundry · evaluation"),
    9: ("09b-*.jpg", "Azure Databricks · same app, same numbers"),
}


def captions() -> dict[int, str]:
    """Frame number -> caption, from the table in docs/demo/script.md."""
    out = {}
    for line in SCRIPT.read_text().splitlines():
        m = re.match(r"\|\s*(\d+)\s*\|([^|]*)\|([^|]*)\|", line)
        if m:
            out[int(m.group(1))] = m.group(3).strip()
    return out


def place_shot(n: int, shot: Image.Image, section: str, caption: str, total: int) -> Image.Image:
    im, d = canvas()
    label(d, (96, 60), section)
    from make_demo_frames import FOOTER_H

    box_w, box_h = W - 192, H - FOOTER_H - 130
    shot = shot.convert("RGB")
    scale = min(box_w / shot.width, box_h / shot.height)
    shot = shot.resize((int(shot.width * scale), int(shot.height * scale)), Image.LANCZOS)
    x = (W - shot.width) // 2
    y = 110 + (box_h - shot.height) // 2
    d.rounded_rectangle([x - 2, y - 2, x + shot.width + 2, y + shot.height + 2], radius=10, outline=(60, 60, 68), width=2)
    im.paste(shot, (x, y))
    footer(im, d, caption, None, n, total)
    return im


def placeholder(n: int, section: str, caption: str, total: int) -> Image.Image:
    im, d = canvas()
    label(d, (96, 60), section)
    d.text((96, 420), "Screenshot pending", font=load(SERIF, 72, "Light Italic"), fill=GOLD)
    d.text((96, 520), section, font=load(SANS, 34), fill=MUTED)
    footer(im, d, caption, None, n, total)
    return im


def render_frames(total: int, shots: bool = True) -> list[Path]:
    caps = captions()
    paths = []
    for n in range(total):
        target = FRAMES / f"{n:02d}.png"
        if shots and n in SHOT_FRAMES:
            pattern, section = SHOT_FRAMES[n]
            files = sorted(SHOTS.glob(pattern))
            if files:
                src = Image.open(files[0])
                if pattern.endswith(".gif"):
                    src.seek(src.n_frames - 1)   # the GIF's last frame is the recorded end state
                im = place_shot(n, src, section, caps.get(n, ""), total)
            else:
                im = placeholder(n, section, caps.get(n, ""), total)
            im.save(target, optimize=True)
        elif not target.is_file():
            raise SystemExit(f"slide {target} missing: run scripts/make_demo_frames.py")
        paths.append(target)
    return paths


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=6.0, help="seconds per frame in the silent GIF")
    ap.add_argument("--gif-width", type=int, default=1280)
    ap.add_argument("--gif-fps", type=int, default=4, help="frames per second in the GIF (only the progress line moves)")
    ap.add_argument("--bar-height", type=int, default=8, help="height in pixels of the progress line at 1920x1080")
    ap.add_argument("--total", type=int, default=11)
    ap.add_argument("--script", default=None, help="script file with the captions (default docs/demo/script.md)")
    ap.add_argument("--frames-dir", default=None, help="where the NN.png frames are (default docs/demo/frames)")
    ap.add_argument("--name", default="demo", help="output base name: <name>.gif and <name>.mp4 in docs/demo")
    ap.add_argument("--no-shots", action="store_true", help="frames are complete already; do not compose screenshots")
    args = ap.parse_args()
    global FRAMES, SCRIPT
    if args.script:
        SCRIPT = Path(args.script)
    if args.frames_dir:
        FRAMES = Path(args.frames_dir)
    paths = render_frames(args.total, shots=not args.no_shots)
    concat = OUT / f"{args.name}-frames.txt"
    with concat.open("w") as f:
        for p in paths:
            f.write(f"file '{p.resolve()}'\nduration {args.seconds}\n")
        f.write(f"file '{paths[-1].resolve()}'\n")
    total_s = args.seconds * len(paths)
    bh = args.bar_height
    # A thin gold progress line along the bottom edge that fills with elapsed time: the frames are stills,
    # and without it the GIF looks frozen. A full-width gold strip slides in from the left; `overlay`
    # evaluates its x expression per frame with t = seconds (drawbox has no time variable).
    def graph(fps: int, tail: str) -> str:
        return (f"[0:v]fps={fps}[v];color=c=0xE8B66B:s={W}x{bh}:r={fps}:d={total_s}[bar];"
                f"[v][bar]overlay=x='-main_w+main_w*t/{total_s}':y=main_h-{bh}:eval=frame:shortest=1{tail}")
    # MP4 (silent): slides at the frame rate of a video, H.264, web-friendly
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(concat),
                    "-filter_complex", graph(30, ",format=yuv420p[out]"), "-map", "[out]",
                    "-c:v", "libx264", "-crf", "20", "-movflags", "+faststart", str(OUT / f"{args.name}.mp4")], check=True)
    # GIF with one palette, reduced width, a few frames per second so the progress line moves
    tail = (f",scale={args.gif_width}:-1:flags=lanczos,split[s0][s1];[s0]palettegen=max_colors=128[p];"
            "[s1][p]paletteuse=dither=bayer:bayer_scale=5[out]")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(concat),
                    "-filter_complex", graph(args.gif_fps, tail), "-map", "[out]", "-loop", "0", str(OUT / f"{args.name}.gif")], check=True)
    for p in (OUT / f"{args.name}.mp4", OUT / f"{args.name}.gif"):
        print(p, f"{p.stat().st_size / 1e6:.1f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
