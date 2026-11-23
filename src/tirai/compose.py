"""Compose the final evidence video from a recorded timeline.

timeline.json (from `tirai run --record`) -> per-step clips cut from the per-tab recordings
-> header bar (tab, step, PASS/FAIL) -> title card -> concat -> burned subtitles.
Writes final.mp4, subtitles.srt, report.md and timeline.final.json next to the timeline.
"""

import json
import os
import shutil
import tempfile
from pathlib import Path

from tirai.system import ffmpeg_bin, ffprobe_bin, find_font, run_text, subtitle_font_name

FPS = 30
TOP, BOTTOM = 40, 64  # header bar (tab/step/status) and subtitle band
DEFAULT_SIZE = (1280, 720)
TAB_COLORS = ["0x1f6feb", "0x7c3aed", "0x0e7490", "0xb45309"]


def ff(*args, cwd=None):
    p = run_text([ffmpeg_bin() or "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], cwd=cwd)
    if p.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {p.stderr.strip()[-600:]}")


def video_size(path):
    """Width/height of a recording (even numbers for yuv420p); falls back to 1280x720."""
    probe = ffprobe_bin()
    if probe:
        p = run_text(
            [
                probe,
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height",
                "-of",
                "csv=p=0:s=x",
                str(path),
            ]
        )
        try:
            w, h = (int(v) for v in p.stdout.strip().split("x")[:2])
            return w - w % 2, h - h % 2
        except ValueError:
            pass
    return DEFAULT_SIZE


def frame_size(tl, rec_dir):
    """Content size: TIRAI_VIDEO_SIZE=WxH, else the largest recorded segment."""
    env = os.environ.get("TIRAI_VIDEO_SIZE")
    if env:
        w, h = (int(v) for v in env.lower().split("x"))
        return w - w % 2, h - h % 2
    sizes = [video_size(rec_dir / s["segment"]) for s in tl["steps"] if s.get("segment")]
    return max(sizes, key=lambda s: s[0] * s[1]) if sizes else DEFAULT_SIZE


def ts(sec):
    ms = int(round(sec * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def text_file(tmp, name, content):
    (Path(tmp) / name).write_text(content, encoding="utf-8")
    return name  # ffmpeg runs with cwd=tmp, so relative names avoid filter-path escaping


def encode_args(out):
    return [
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "20",
        "-pix_fmt",
        "yuv420p",
        "-r",
        str(FPS),
        str(Path(out).resolve()),
    ]


def title_card(tmp, tl, out, seconds, frame):
    W, H = frame
    FH = H + TOP + BOTTOM
    passed = sum(s["status"] == "passed" for s in tl["steps"])
    lines = [
        (tl["scenario"], 44, "font-bold.ttf", -60),
        (f"{passed}/{len(tl['steps'])} steps passed  ·  recorded {tl['created']}", 24, "font.ttf", 10),
        ("Evidence: BrowserSkill recording + TIRAI annotations", 20, "font.ttf", 60),
    ]
    draws = []
    for i, (txt, size, font, dy) in enumerate(lines):
        f = text_file(tmp, f"title{i}.txt", txt)
        draws.append(
            f"drawtext=fontfile={font}:textfile={f}:fontsize={size}:fontcolor=white:x=(w-text_w)/2:y=(h-text_h)/2+{dy}"
        )
    ff(
        "-f",
        "lavfi",
        "-i",
        f"color=c=0x0f172a:s={W}x{FH}:d={seconds}:r={FPS}",
        "-vf",
        ",".join(draws),
        *encode_args(out),
        cwd=tmp,
    )


def step_clip(tmp, rec_dir, tl, step, out, lead, frame):
    W, H = frame
    FH = H + TOP + BOTTOM
    seg = rec_dir / step["segment"]
    start = max(0.0, step["start"] - lead)
    dur = step["end"] - start
    label = tl["tabs"][step["tab"]]["label"]
    color = TAB_COLORS[list(tl["tabs"]).index(step["tab"]) % len(TAB_COLORS)]
    status = "PASS" if step["status"] == "passed" else "FAIL"
    hdr = text_file(tmp, f"hdr-{step['id']}.txt", f"{label}   |   {step['id']}  {step['title']}")
    st = text_file(tmp, f"st-{step['id']}.txt", status)
    st_color = "0x16a34a" if status == "PASS" else "0xdc2626"
    bold = "font-bold.ttf"
    vf = (
        f"fps={FPS},tpad=stop_mode=clone:stop_duration=10,"
        f"trim=start={start:.3f}:duration={dur:.3f},setpts=PTS-STARTPTS,"
        f"scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,"
        f"pad={W}:{H + TOP}:0:{TOP}:color={color},pad={W}:{FH}:0:0:color=0x0f172a,"
        f"drawtext=fontfile={bold}:textfile={hdr}:fontsize=20:fontcolor=white:x=16:y=10,"
        f"drawbox=x=iw-96:y=6:w=80:h=28:color={st_color}:t=fill,"
        f"drawtext=fontfile={bold}:textfile={st}:fontsize=18:fontcolor=white:x=w-56-text_w/2:y=11"
    )
    ff("-i", str(seg.resolve()), "-vf", vf, "-an", *encode_args(Path(out).resolve()), cwd=tmp)
    return dur


def compose(timeline_path, out=None, lead=0.3, title_seconds=3.0):
    """Build final.mp4 (+ subtitles.srt, report.md, timeline.final.json); returns the final video path."""
    if not ffmpeg_bin():
        raise RuntimeError("ffmpeg not found; run `tirai setup` or set FFMPEG_BIN")
    fonts = (find_font(False), find_font(True))
    if not fonts[0]:
        raise RuntimeError("no font found; set TIRAI_FONT to a .ttf file")
    tl_path = Path(timeline_path)
    tl = json.loads(tl_path.read_text(encoding="utf-8"))
    if tl.get("mode") != "record":
        raise ValueError("timeline was not recorded; run `tirai run --record` first")
    rec_dir = tl_path.parent
    final = Path(out) if out else rec_dir / "final.mp4"

    with tempfile.TemporaryDirectory() as tmp:
        tmpd = Path(tmp)
        # Fonts are copied next to the filter inputs so every ffmpeg path is relative (no drive-letter escaping).
        shutil.copyfile(fonts[0], tmpd / "font.ttf")
        shutil.copyfile(fonts[1], tmpd / "font-bold.ttf")
        size = frame_size(tl, rec_dir)
        clips, srt, t = [], [], 0.0
        title = tmpd / "00-title.mp4"
        title_card(tmp, tl, title, title_seconds, size)
        clips.append(title)
        t += title_seconds
        for i, step in enumerate(tl["steps"], 1):
            clip = tmpd / f"{i:02d}-{step['id']}.mp4"
            dur = step_clip(tmp, rec_dir, tl, step, clip, lead, size)
            clips.append(clip)
            srt.append(f"{len(srt) + 1}\n{ts(t + 0.2)} --> {ts(t + dur - 0.1)}\n{step['subtitle']}\n")
            step["final_start"], step["final_end"] = round(t, 3), round(t + dur, 3)
            t += dur
        (tmpd / "list.txt").write_text("".join(f"file '{c.name}'\n" for c in clips))
        ff("-f", "concat", "-safe", "0", "-i", "list.txt", "-c", "copy", "joined.mp4", cwd=tmp)
        srt_text = "\n".join(srt)
        (rec_dir / "subtitles.srt").write_text(srt_text, encoding="utf-8")
        (tmpd / "subs.srt").write_text(srt_text, encoding="utf-8")
        # libass scales SRT styles from a 288px-high canvas: FontSize 10 ~ 28px, MarginV 6 ~ 17px at 808px.
        font_name = subtitle_font_name()
        style = (
            f"FontName={font_name},FontSize=10,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,"
            "BorderStyle=1,Outline=0.6,Shadow=0,MarginV=6,Alignment=2"
        )
        ff(
            "-i",
            "joined.mp4",
            "-vf",
            f"subtitles=subs.srt:fontsdir=.:force_style='{style}'",
            *encode_args(final),
            cwd=tmp,
        )

    (rec_dir / "report.md").write_text(report_md(tl, final.name), encoding="utf-8")
    (rec_dir / "timeline.final.json").write_text(json.dumps(tl, ensure_ascii=False, indent=2), encoding="utf-8")
    return final, t


def report_md(tl, video_name):
    lines = [
        f"# {tl['scenario']}",
        "",
        f"Recorded: {tl['created']}  ",
        f"Video: `{video_name}`",
        "",
        "| Step | Tab | Title | Status | Video time | Checks |",
        "|---|---|---|---|---|---|",
    ]
    for s in tl["steps"]:
        checks = "; ".join(f"{c['type']}: {'OK' if c['ok'] else 'FAIL'}" for c in s["checks"])
        when = f"{ts(s['final_start'])[3:8]}–{ts(s['final_end'])[3:8]}" if "final_start" in s else "-"
        lines.append(
            f"| {s['id']} | {tl['tabs'][s['tab']]['label']} | {s['title']} | {s['status'].upper()} | "
            f"{when} | {checks} |"
        )
    return "\n".join(lines) + "\n"
