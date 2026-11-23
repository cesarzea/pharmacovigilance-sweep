"""Narrate the demo: one audio clip per frame from the narration column of docs/demo/script.md, then an
MP4 where each frame lasts as long as its clip (plus a pause), with subtitles from the captions.

    uv run --no-project --with pillow python -I scripts/make_demo_audio.py [--voice <elevenlabs voice id>] [--engine say]

Engines: "elevenlabs" (default when ELEVENLABS_API_KEY is in the environment or in .env; the key never
leaves the machine except in the API call) or "say" (macOS text-to-speech, free, for drafts). Clips are
cached in docs/demo/audio/<engine>/NN.mp3|aiff and regenerated only when the narration text changes.
Output: docs/demo/demo-narrated.mp4 and docs/demo/demo.srt. Frames come from docs/demo/frames/NN.png
(scripts/make_demo_video.py renders them).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRAMES = ROOT / "docs/demo/frames"
OUT = ROOT / "docs/demo"
DEFAULT_VOICE = "JBFqnCBsd6RMkjVDRZzb"   # ElevenLabs "George": a calm, narrative English voice
W, H = 1920, 1080


def script_rows() -> list[dict]:
    rows = []
    for line in (ROOT / "docs/demo/script.md").read_text().splitlines():
        m = re.match(r"\|\s*(\d+)\s*\|([^|]*)\|([^|]*)\|([^|]*)\|", line)
        if m:
            rows.append({"n": int(m.group(1)), "caption": m.group(3).strip(), "narration": m.group(4).strip()})
    return rows


def load_env_key() -> str | None:
    if os.environ.get("ELEVENLABS_API_KEY"):
        return os.environ["ELEVENLABS_API_KEY"]
    env = ROOT / ".env"
    if env.is_file():
        for ln in env.read_text().splitlines():
            if ln.startswith("ELEVENLABS_API_KEY="):
                return ln.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def tts_elevenlabs(text: str, out: Path, voice: str, key: str) -> None:
    req = urllib.request.Request(
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice}?output_format=mp3_44100_128",
        data=json.dumps({"text": text, "model_id": "eleven_multilingual_v2",
                         "voice_settings": {"stability": 0.5, "similarity_boost": 0.75, "style": 0.2}}).encode(),
        headers={"xi-api-key": key, "Content-Type": "application/json", "Accept": "audio/mpeg"})
    with urllib.request.urlopen(req, timeout=120) as r:
        out.write_bytes(r.read())


def tts_say(text: str, out: Path, voice: str) -> None:
    subprocess.run(["say", "-v", voice, "-r", "165", "-o", str(out), text], check=True)


def duration(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True, check=True).stdout.strip()
    return float(out)


def srt_time(t: float) -> str:
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", choices=["elevenlabs", "say"], default=None)
    ap.add_argument("--voice", default=None, help="ElevenLabs voice id, or a macOS voice name for --engine say")
    ap.add_argument("--pause", type=float, default=0.8, help="seconds of silence after each clip")
    ap.add_argument("--lead", type=float, default=0.4, help="seconds before a clip starts on its frame")
    args = ap.parse_args()
    key = load_env_key()
    engine = args.engine or ("elevenlabs" if key else "say")
    if engine == "elevenlabs" and not key:
        raise SystemExit("ELEVENLABS_API_KEY not set (environment or .env); use --engine say for a draft")
    voice = args.voice or (DEFAULT_VOICE if engine == "elevenlabs" else "Samantha")
    audio_dir = OUT / "audio" / engine
    audio_dir.mkdir(parents=True, exist_ok=True)

    rows = script_rows()
    segments = []
    for row in rows:
        n, text = row["n"], row["narration"]
        ext = "mp3" if engine == "elevenlabs" else "aiff"
        clip = audio_dir / f"{n:02d}.{ext}"
        stamp = audio_dir / f"{n:02d}.sha"
        digest = hashlib.sha256(f"{voice}|{text}".encode()).hexdigest()
        if not clip.is_file() or not stamp.is_file() or stamp.read_text() != digest:
            print(f"narrating frame {n} ({engine}, {len(text)} chars)")
            (tts_elevenlabs if engine == "elevenlabs" else tts_say)(text, clip, voice, *([key] if engine == "elevenlabs" else []))
            stamp.write_text(digest)
        frame = FRAMES / f"{n:02d}.png"
        if not frame.is_file():
            raise SystemExit(f"{frame} missing: run scripts/make_demo_video.py first")
        segments.append((n, frame, clip, duration(clip) + args.lead + args.pause, row["caption"]))

    total = sum(s[3] for s in segments)
    # video track: each frame for the length of its clip; audio track: clips delayed by the lead, concatenated
    concat = OUT / "frames-narrated.txt"
    with concat.open("w") as f:
        for _, frame, _, dur, _ in segments:
            f.write(f"file '{frame}'\nduration {dur:.3f}\n")
        f.write(f"file '{segments[-1][1]}'\n")
    inputs, afilters, t = ["-f", "concat", "-safe", "0", "-i", str(concat)], [], 0.0
    for i, (_, _, clip, dur, _) in enumerate(segments):
        inputs += ["-i", str(clip)]
        afilters.append(f"[{i + 1}:a]adelay={int((t + args.lead) * 1000)}|{int((t + args.lead) * 1000)},apad=whole_dur={total:.3f}[a{i}]")
        t += dur
    mix = "".join(f"[a{i}]" for i in range(len(segments))) + f"amix=inputs={len(segments)}:normalize=0,atrim=0:{total:.3f}[aout]"
    bar = f"[0:v]fps=30[v];color=c=0xE8B66B:s={W}x8:r=30:d={total:.3f}[bar];[v][bar]overlay=x='-main_w+main_w*t/{total:.3f}':y=main_h-8:eval=frame:shortest=1,format=yuv420p[vout]"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *inputs, "-filter_complex", ";".join([bar, *afilters, mix]),
                    "-map", "[vout]", "-map", "[aout]", "-c:v", "libx264", "-crf", "20", "-c:a", "aac", "-b:a", "160k",
                    "-movflags", "+faststart", "-t", f"{total:.3f}", str(OUT / "demo-narrated.mp4")], check=True)
    # subtitles from the captions, one per frame
    t, lines = 0.0, []
    for i, (_, _, _, dur, caption) in enumerate(segments, start=1):
        lines += [str(i), f"{srt_time(t)} --> {srt_time(t + dur - 0.2)}", caption, ""]
        t += dur
    (OUT / "demo.srt").write_text("\n".join(lines))
    print(f"{OUT / 'demo-narrated.mp4'}: {total:.0f} s, {(OUT / 'demo-narrated.mp4').stat().st_size / 1e6:.1f} MB; subtitles {OUT / 'demo.srt'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
