"""Narrate and subtitle the demo from a script table (docs/demo/script.md or script-full.md): one audio
clip per frame, word timings, karaoke subtitles (the words light up as they are said), and three outputs:

    <name>-narrated.mp4   frames + narration + burned-in karaoke subtitles
    <name>.mp4            the same without audio
    <name>.gif            the same as a GIF for the README (the subtitles carry the narration, no sound)
    <name>.srt / .ass     the subtitle tracks (captions for players; karaoke narration as burned in)

    uv run --no-project python -I scripts/make_demo_audio.py [--script docs/demo/script-full.md]
        [--frames-dir docs/demo/full/frames] [--name full] [--engine elevenlabs|say] [--voice <id>]

Engines: "elevenlabs" (default when ELEVENLABS_API_KEY is in the environment or in .env; the key never
leaves the machine except in the API call; word timings come from the API's alignment) or "say"
(macOS text-to-speech, free, for drafts; word timings are spread over the clip by word length). Clips
are cached in docs/demo/audio/<engine>/<name>/ and regenerated only when the narration text changes.
"""

from __future__ import annotations

import argparse
import base64
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
SCRIPT = ROOT / "docs/demo/script.md"
DEFAULT_VOICE = "JBFqnCBsd6RMkjVDRZzb"   # ElevenLabs "George": a calm, narrative English voice
W, H = 1920, 1080
# subtitle zone: the footer's right side (the left 440 px hold the name and the site)
SUB_LEFT, SUB_RIGHT, SUB_BOTTOM = 470, 96, 40
CHUNK_CHARS = 210   # about three lines at the default size; longer narrations are shown in successive chunks


def script_rows() -> list[dict]:
    rows = []
    for line in SCRIPT.read_text().splitlines():
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


# ---------------------------------------------------------------- text to speech with word timings

def tts_elevenlabs(text: str, out: Path, voice: str, key: str) -> list[tuple[float, float]]:
    """Returns (start, end) per word from the API's character alignment."""
    req = urllib.request.Request(
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice}/with-timestamps?output_format=mp3_44100_128",
        data=json.dumps({"text": text, "model_id": "eleven_multilingual_v2",
                         "voice_settings": {"stability": 0.5, "similarity_boost": 0.75, "style": 0.2}}).encode(),
        headers={"xi-api-key": key, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r:
        body = json.load(r)
    out.write_bytes(base64.b64decode(body["audio_base64"]))
    al = body.get("alignment") or body.get("normalized_alignment")
    chars, starts, ends = al["characters"], al["character_start_times_seconds"], al["character_end_times_seconds"]
    joined = "".join(chars)
    timings, i = [], 0
    for w in text.split():
        j = joined.find(w, i)
        if j < 0:  # the API normalised the word (numbers read out): take the next run of non-space characters
            while i < len(chars) and chars[i].isspace():
                i += 1
            j = i
        k = min(j + len(w), len(chars)) - 1
        timings.append((starts[j], ends[k]))
        i = k + 1
    return timings


def tts_say(text: str, out: Path, voice: str) -> list[tuple[float, float]]:
    subprocess.run(["say", "-v", voice, "-r", "165", "-o", str(out), text], check=True)
    total = duration(out)
    ws = text.split()
    weights = [len(w) + 1.5 + (2.5 if w.endswith((".", ",", ";", ":")) else 0) for w in ws]
    scale = (total - 0.15) / sum(weights)
    t, timings = 0.05, []
    for wgt in weights:
        timings.append((t, t + wgt * scale))
        t += wgt * scale
    return timings


def duration(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True, check=True).stdout.strip()
    return float(out)


# ---------------------------------------------------------------- subtitles

def srt_time(t: float) -> str:
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def ass_time(t: float) -> str:
    cs = int(round(t * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def ass_header(font: str, size: int) -> str:
    # colours are &HAABBGGRR: gold for spoken words (Primary), muted grey for the rest (Secondary); karaoke
    # \k moves a word from Secondary to Primary. No border; alignment 3 = bottom right inside the margins.
    return f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Narration,{font},{size},&H006BB6E8,&H00A09C92,&H000E0B0B,&H000E0B0B,0,0,0,0,100,100,0,0,1,0,0,3,{SUB_LEFT},{SUB_RIGHT},{SUB_BOTTOM},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def chunks(words: list[str], timings: list[tuple[float, float]]) -> list[tuple[list[str], list[tuple[float, float]]]]:
    """Split a narration into runs of at most CHUNK_CHARS characters, preferring sentence ends."""
    out, cur_w, cur_t, size = [], [], [], 0
    for w, t in zip(words, timings, strict=True):
        if cur_w and size + len(w) + 1 > CHUNK_CHARS:
            out.append((cur_w, cur_t))
            cur_w, cur_t, size = [], [], 0
        cur_w.append(w)
        cur_t.append(t)
        size += len(w) + 1
        if w.endswith((".", "?", "!")) and size > CHUNK_CHARS * 0.6:
            out.append((cur_w, cur_t))
            cur_w, cur_t, size = [], [], 0
    if cur_w:
        out.append((cur_w, cur_t))
    return out


def ass_events(frame_start: float, frame_end: float, words: list[str], timings: list[tuple[float, float]], lead: float) -> str:
    """Dialogue lines for one frame: successive chunks, each with \\k durations (centiseconds) per word."""
    lines = []
    parts = chunks(words, timings)
    for ci, (cw, ct) in enumerate(parts):
        start = frame_start if ci == 0 else frame_start + lead + ct[0][0] - 0.05
        end = frame_end if ci == len(parts) - 1 else frame_start + lead + parts[ci + 1][1][0][0] - 0.05
        text, t = [], start
        for w, (ws, we) in zip(cw, ct, strict=True):
            begin = frame_start + lead + ws
            if begin > t:
                text.append(f"{{\\k{int(round((begin - t) * 100))}}}")   # the silence before a word stays unlit
                t = begin
            d = max(1, int(round((frame_start + lead + we - t) * 100)))
            text.append(f"{{\\k{d}}}{w} ")
            t += d / 100
        lines.append(f"Dialogue: 0,{ass_time(start)},{ass_time(end)},Narration,,0,0,0,,{''.join(text).rstrip()}\n")
    return "".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", choices=["elevenlabs", "say"], default=None)
    ap.add_argument("--voice", default=None, help="ElevenLabs voice id, or a macOS voice name for --engine say")
    ap.add_argument("--pause", type=float, default=0.8, help="seconds of silence after each clip")
    ap.add_argument("--lead", type=float, default=0.4, help="seconds before a clip starts on its frame")
    ap.add_argument("--script", default=None)
    ap.add_argument("--frames-dir", default=None)
    ap.add_argument("--name", default="demo", help="output base name in docs/demo")
    ap.add_argument("--font", default="Inter Tight", help="subtitle font family (docs/demo/fonts is passed to libass)")
    ap.add_argument("--font-size", type=int, default=34)
    ap.add_argument("--gif-width", type=int, default=1280)
    ap.add_argument("--gif-fps", type=int, default=5)
    args = ap.parse_args()
    global SCRIPT, FRAMES
    if args.script:
        SCRIPT = Path(args.script) if Path(args.script).is_absolute() else ROOT / args.script
    if args.frames_dir:
        FRAMES = Path(args.frames_dir) if Path(args.frames_dir).is_absolute() else ROOT / args.frames_dir
    key = load_env_key()
    engine = args.engine or ("elevenlabs" if key else "say")
    if engine == "elevenlabs" and not key:
        raise SystemExit("ELEVENLABS_API_KEY not set (environment or .env); use --engine say for a draft")
    voice = args.voice or (DEFAULT_VOICE if engine == "elevenlabs" else "Samantha")
    audio_dir = OUT / "audio" / engine / args.name
    audio_dir.mkdir(parents=True, exist_ok=True)

    segments = []   # (frame, clip, dur, caption, words, timings)
    for row in script_rows():
        n, text = row["n"], row["narration"]
        clip = audio_dir / f"{n:02d}.{'mp3' if engine == 'elevenlabs' else 'aiff'}"
        meta = audio_dir / f"{n:02d}.json"
        digest = hashlib.sha256(f"{voice}|{text}".encode()).hexdigest()
        if not (clip.is_file() and meta.is_file() and json.loads(meta.read_text()).get("sha") == digest):
            print(f"narrating frame {n} ({engine}, {len(text)} chars)")
            timings = tts_elevenlabs(text, clip, voice, key) if engine == "elevenlabs" else tts_say(text, clip, voice)
            meta.write_text(json.dumps({"sha": digest, "timings": timings}))
        timings = [tuple(x) for x in json.loads(meta.read_text())["timings"]]
        frame = FRAMES / f"{n:02d}.png"
        if not frame.is_file():
            raise SystemExit(f"{frame} missing: render the frames first")
        segments.append((frame, clip, duration(clip) + args.lead + args.pause, row["caption"], text.split(), timings))

    total = sum(s[2] for s in segments)
    concat = OUT / f"{args.name}-frames-narrated.txt"
    with concat.open("w") as f:
        for frame, _, dur, _, _, _ in segments:
            f.write(f"file '{frame}'\nduration {dur:.3f}\n")
        f.write(f"file '{segments[-1][0]}'\n")

    t, srt, ass = 0.0, [], [ass_header(args.font, args.font_size)]
    for i, (_, _, dur, caption, words, timings) in enumerate(segments, start=1):
        srt += [str(i), f"{srt_time(t)} --> {srt_time(t + dur - 0.2)}", caption, ""]
        ass.append(ass_events(t, t + dur - 0.05, words, timings, args.lead))
        t += dur
    (OUT / f"{args.name}.srt").write_text("\n".join(srt))
    ass_path = OUT / f"{args.name}.ass"
    ass_path.write_text("".join(ass))

    fonts_dir = ROOT / "docs/demo/fonts"
    sub = f"ass={ass_path.as_posix()}" + (f":fontsdir={fonts_dir.as_posix()}" if fonts_dir.is_dir() else "")

    def video_graph(fps: int) -> str:
        return (f"[0:v]fps={fps}[v];color=c=0xE8B66B:s={W}x8:r={fps}:d={total:.3f}[bar];"
                f"[v][bar]overlay=x='-main_w+main_w*t/{total:.3f}':y=main_h-8:eval=frame:shortest=1[vb];[vb]{sub}[vs]")

    inputs, afilters, t = ["-f", "concat", "-safe", "0", "-i", str(concat)], [], 0.0
    for i, (_, clip, dur, _, _, _) in enumerate(segments):
        inputs += ["-i", str(clip)]
        ms = int((t + args.lead) * 1000)
        afilters.append(f"[{i + 1}:a]adelay={ms}|{ms},apad=whole_dur={total:.3f}[a{i}]")
        t += dur
    mix = "".join(f"[a{i}]" for i in range(len(segments))) + f"amix=inputs={len(segments)}:normalize=0,atrim=0:{total:.3f}[aout]"
    narrated = OUT / f"{args.name}-narrated.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *inputs,
                    "-filter_complex", ";".join([video_graph(30), *afilters, mix, "[vs]format=yuv420p[vout]"]),
                    "-map", "[vout]", "-map", "[aout]", "-c:v", "libx264", "-crf", "20", "-c:a", "aac", "-b:a", "160k",
                    "-movflags", "+faststart", "-t", f"{total:.3f}", str(narrated)], check=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(concat),
                    "-filter_complex", ";".join([video_graph(30), "[vs]format=yuv420p[vout]"]), "-map", "[vout]",
                    "-c:v", "libx264", "-crf", "20", "-movflags", "+faststart", "-t", f"{total:.3f}", str(OUT / f"{args.name}.mp4")], check=True)
    gif_tail = (f"[vs]scale={args.gif_width}:-1:flags=lanczos,split[s0][s1];[s0]palettegen=max_colors=128[p];"
                "[s1][p]paletteuse=dither=bayer:bayer_scale=5[gout]")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(concat),
                    "-filter_complex", ";".join([video_graph(args.gif_fps), gif_tail]),
                    "-map", "[gout]", "-loop", "0", "-t", f"{total:.3f}", str(OUT / f"{args.name}.gif")], check=True)
    for p in (narrated, OUT / f"{args.name}.mp4", OUT / f"{args.name}.gif"):
        print(f"{p}: {total:.0f} s, {p.stat().st_size / 1e6:.1f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
