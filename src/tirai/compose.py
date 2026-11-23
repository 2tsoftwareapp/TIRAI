"""Compose the final evidence video from a recorded timeline.

timeline.json (from `tirai run --record`) -> per-step clips cut from the per-tab recordings
-> header bar (tab, step, PASS/FAIL) -> title card -> concat -> burned subtitles.
Writes final.mp4, subtitles.srt, report.md and timeline.final.json next to the timeline.
"""

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

W, H, FPS = 1392, 704, 30
TOP, BOTTOM = 40, 64  # header bar (tab/step/status) and subtitle band
FH = H + TOP + BOTTOM
TAB_COLORS = ["0x1f6feb", "0x7c3aed", "0x0e7490", "0xb45309"]
FONT_CANDIDATES = {
    False: [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/Library/Fonts/Arial Unicode.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ],
    True: [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
    ],
}


def find_font(bold=False):
    """TIRAI_FONT / TIRAI_FONT_BOLD, else a platform default with Vietnamese/Unicode glyphs."""
    env = os.environ.get("TIRAI_FONT_BOLD" if bold else "TIRAI_FONT")
    for p in ([env] if env else []) + FONT_CANDIDATES[bold]:
        if Path(p).is_file():
            return p
    return find_font(False) if bold else None


def _filter_path(p):
    """Escape a path for use inside an ffmpeg filter argument (Windows drive colons, backslashes)."""
    return str(p).replace("\\", "/").replace(":", r"\:")


def ff(*args, cwd=None):
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], check=True, cwd=cwd)


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


def title_card(tmp, tl, out, seconds, fonts):
    passed = sum(s["status"] == "passed" for s in tl["steps"])
    lines = [
        (tl["scenario"], 44, fonts[1], -60),
        (f"{passed}/{len(tl['steps'])} steps passed  ·  recorded {tl['created']}", 24, fonts[0], 10),
        ("Evidence: BrowserSkill recording + TIRAI annotations", 20, fonts[0], 60),
    ]
    draws = []
    for i, (txt, size, font, dy) in enumerate(lines):
        f = text_file(tmp, f"title{i}.txt", txt)
        draws.append(
            f"drawtext=fontfile={_filter_path(font)}:textfile={f}:fontsize={size}:fontcolor=white:"
            f"x=(w-text_w)/2:y=(h-text_h)/2+{dy}"
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


def step_clip(tmp, rec_dir, tl, step, out, lead, fonts):
    seg = rec_dir / step["segment"]
    start = max(0.0, step["start"] - lead)
    dur = step["end"] - start
    label = tl["tabs"][step["tab"]]["label"]
    color = TAB_COLORS[list(tl["tabs"]).index(step["tab"]) % len(TAB_COLORS)]
    status = "PASS" if step["status"] == "passed" else "FAIL"
    hdr = text_file(tmp, f"hdr-{step['id']}.txt", f"{label}   |   {step['id']}  {step['title']}")
    st = text_file(tmp, f"st-{step['id']}.txt", status)
    st_color = "0x16a34a" if status == "PASS" else "0xdc2626"
    bold = _filter_path(fonts[1])
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
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg not found on PATH")
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
        clips, srt, t = [], [], 0.0
        title = tmpd / "00-title.mp4"
        title_card(tmp, tl, title, title_seconds, fonts)
        clips.append(title)
        t += title_seconds
        for i, step in enumerate(tl["steps"], 1):
            clip = tmpd / f"{i:02d}-{step['id']}.mp4"
            dur = step_clip(tmp, rec_dir, tl, step, clip, lead, fonts)
            clips.append(clip)
            srt.append(f"{len(srt) + 1}\n{ts(t + 0.2)} --> {ts(t + dur - 0.1)}\n{step['subtitle']}\n")
            step["final_start"], step["final_end"] = round(t, 3), round(t + dur, 3)
            t += dur
        (tmpd / "list.txt").write_text("".join(f"file '{c.name}'\n" for c in clips))
        ff("-f", "concat", "-safe", "0", "-i", "list.txt", "-c", "copy", "joined.mp4", cwd=tmp)
        srt_text = "\n".join(srt)
        (rec_dir / "subtitles.srt").write_text(srt_text, encoding="utf-8")
        (tmpd / "subs.srt").write_text(srt_text, encoding="utf-8")
        # libass scales SRT styles from a 288px-high canvas: FontSize 10 ~ 28px, MarginV 6 ~ 17px here.
        font_name = "DejaVu Sans" if "DejaVu" in fonts[0] else "Arial"
        style = (
            f"FontName={font_name},FontSize=10,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,"
            "BorderStyle=1,Outline=0.6,Shadow=0,MarginV=6,Alignment=2"
        )
        ff("-i", "joined.mp4", "-vf", f"subtitles=subs.srt:force_style='{style}'", *encode_args(final), cwd=tmp)

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
