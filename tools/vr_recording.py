"""Export a completed native stereo recording without touching the live renderer.

The lossless .rgbz pairs and their actual capture timestamps remain authoritative.
Video uses variable frame timestamps, holding the preceding frame across gaps;
it never interpolates motion. No third-party Python packages are required.
"""
from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
import shutil
import struct
import subprocess
import zlib


def png(rgb: bytes, width: int, height: int) -> bytes:
    """RGB24 bottom-up input, ordinary top-down lossless PNG output."""
    row = width * 3
    if width <= 0 or height <= 0 or len(rgb) != row * height:
        raise ValueError("Incorrect eye buffer dimensions")

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    scan = b"".join(b"\0" + rgb[y * row:(y + 1) * row] for y in reversed(range(height)))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">2I5B", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(scan, 1)) + chunk(b"IEND", b""))


def frame_durations(frames: list[dict], duration: float) -> list[float]:
    """Keep real sample spacing and the fixed five-second viewing interval."""
    times = [float(f["elapsed_seconds"]) for f in frames]
    if not times or not 0 <= times[0] < duration:
        raise ValueError("No frame inside the recording interval")
    if any(not a < b < duration for a, b in zip(times, times[1:])):
        raise ValueError("Frame timestamps must increase within the recording interval")
    # The first available picture covers the short lead-in; disclose it in the report.
    return [b - a for a, b in zip([0.0, *times[1:]], [*times[1:], duration])]


def export(directory: Path) -> dict:
    directory = directory.resolve(strict=True)
    manifest = json.loads((directory / "recording.json").read_text())
    if manifest.get("schema") != 1 or manifest.get("format") != "zlib-rgb24-left-then-right-bottom-up":
        raise ValueError("Unknown native recording format")
    width, height = int(manifest["width"]), int(manifest["height"])
    eye_size = width * height * 3
    if not 0 < eye_size * 2 <= 48 * 1024 * 1024:
        raise ValueError("Recording exceeds the supported eye dimensions")
    frames = []
    for path in directory.glob("*.json"):
        if not path.stem.isdigit():
            continue
        frame = json.loads(path.read_text())
        if frame.get("frame") != int(path.stem) or not frame.get("xr_end_frame_succeeded"):
            raise ValueError("Unsubmitted or mismatched frame")
        if sorted(e["eye"] for e in frame["eyes"]) != [0, 1]:
            raise ValueError("Incomplete stereo pair")
        frames.append(frame)
    frames.sort(key=lambda f: f["elapsed_seconds"])
    durations = frame_durations(frames, float(manifest["duration_seconds"]))
    scratch = directory / ".encoding"
    scratch.mkdir(exist_ok=False)
    try:
        for frame in frames:
            # Bound decompression even if a recording is corrupt or user-provided.
            decoder = zlib.decompressobj()
            raw = decoder.decompress((directory / f'{frame["frame"]}.rgbz').read_bytes(), eye_size * 2 + 1)
            if len(raw) != eye_size * 2 or not decoder.eof or decoder.unused_data:
                raise ValueError("Invalid compressed stereo pair")
            for eye in range(2):
                data = png(raw[eye * eye_size:(eye + 1) * eye_size], width, height)
                (scratch / f'{frame["frame"]}-{eye}.png').write_bytes(data)
        for eye, name in enumerate(("left", "right")):
            lines = ["ffconcat version 1.0"]
            for frame, length in zip(frames, durations, strict=True):
                lines += [f"file '{frame['frame']}-{eye}.png'", "option framerate 1000", f"duration {length:.9f}"]
            # concat needs an endpoint image for the final requested duration.
            lines += [f"file '{frames[-1]['frame']}-{eye}.png'", "option framerate 1000"]
            concat = scratch / (name + ".ffconcat")
            concat.write_text("\n".join(lines) + "\n")
            with (directory / (name + "-export.log")).open("w") as log:
                subprocess.run([
                    "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "warning", "-y",
                    "-f", "concat", "-safe", "0", "-i", str(concat), "-an",
                    "-t", str(manifest["duration_seconds"]), "-fps_mode", "vfr",
                    "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2", "-c:v", "libx264",
                    "-preset", "ultrafast", "-crf", "12", "-threads", "2",
                    "-pix_fmt", "yuv420p", "-video_track_timescale", "1000000",
                    "-movflags", "+faststart", str(directory / (name + ".mp4")),
                ], stdout=log, stderr=subprocess.STDOUT, check=True, timeout=180)
        summary = {**manifest, "video_exported": True, "frames": frames,
                   "first_frame_seconds": frames[0]["elapsed_seconds"],
                   "maximum_frame_gap_seconds": max(durations),
                   "video_timing": "variable frame rate; holds sampled pictures, no interpolation",
                   "capture_rate_hz": len(frames) / manifest["duration_seconds"]}
        (directory / "timeline.json").write_text(json.dumps(summary, indent=2))
        report(directory, summary)
        return summary
    finally:
        shutil.rmtree(scratch)


def report(directory: Path, summary: dict) -> None:
    skipped = summary["dropped_pairs"]
    menus = {tuple(f["menus_open"]) for f in summary["frames"]}
    states = ", ".join(f"left {'open' if a else 'closed'}, right {'open' if b else 'closed'}" for a, b in sorted(menus))
    text = f"""<!doctype html><meta charset="utf-8"><title>VR stereo recording</title>
<style>body{{background:#10151f;color:#edf2fa;font:16px/1.5 system-ui;max-width:1200px;margin:35px auto;padding:0 20px}}a{{color:#88caff}}.eyes{{display:flex;gap:16px}}video{{width:100%;max-height:65vh}}.eyes>div{{width:50%}}button{{padding:10px;margin:8px}}small{{color:#b7c4d8}}</style>
<h1>Five-second VR recording</h1><p>Both application eyes, including menus. These images precede the compositor and physical headset display.</p>
<p>{summary['saved_frames']} stereo pairs · {summary['capture_rate_hz']:.1f} captured pairs/s · {skipped} capture skips · maximum sample gap {summary['maximum_frame_gap_seconds']*1000:.1f} ms.</p>
<p>Menus observed: {html.escape(states)}. Skips describe the recorder; application/compositor frame repeats require separate timing evidence.</p>
<div class="eyes"><div><h2>Left eye</h2><video id="left" controls src="left.mp4"></video></div><div><h2>Right eye</h2><video id="right" controls src="right.mp4"></video></div></div>
<button id="play">Play both</button><button id="pause">Pause both</button>
<p><a href="left.mp4">Left video</a> · <a href="right.mp4">Right video</a> · <a href="timeline.json">Frame timing, menu states and eye poses</a></p>
<p>Video holds each captured picture until the next sample; it does not invent intermediate motion. The first available picture covers the initial {summary['first_frame_seconds']*1000:.1f} ms. Lossless paired RGB data is retained in the numbered .rgbz files.</p>
<small>Capture can affect performance. Compare recording off/on using the same scene and menu state before attributing a motion artifact to the application.</small>
<script>const l=document.getElementById('left'),r=document.getElementById('right');document.getElementById('play').onclick=()=>{{r.currentTime=l.currentTime;l.play();r.play()}};document.getElementById('pause').onclick=()=>{{l.pause();r.pause()}};l.onseeked=()=>{{r.currentTime=l.currentTime}};</script>"""
    (directory / "index.html").write_text(text)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    try:
        export(args.directory)
    except Exception as error:
        (args.directory / "export-error.txt").write_text(str(error) + "\n")
        raise
