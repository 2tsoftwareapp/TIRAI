"""Compose the final evidence video from a recorded timeline.

timeline.json (from `tirai run --record`) -> per-step clips cut from the per-tab recordings
-> header bar (tab, step, PASS/FAIL) -> title card -> concat -> burned subtitles.
Writes final.mp4, subtitles.srt, report.md/.html/.xlsx, timeline.final.json and manifest.sha256 next to the timeline.
"""

import json
import os
import shutil
import tempfile
from pathlib import Path

from tirai import report
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


def zoom_filter(step, seg_size):
    """Ease into the step's `zoom` target (rect captured by the runner) and hold; '' when not zoomed."""
    z = step.get("zoom")
    if not z:
        return ""
    sw, sh = seg_size
    x, y, w, h = z["rect"]
    vw, vh = z["viewport"]
    sx, sy = sw / max(vw, 1), sh / max(vh, 1)
    cx, cy = (x + w / 2) * sx * 2, (y + h / 2) * sy * 2  # upscaled 2x below to keep the pan smooth
    fit = min(0.85 * sw / max(w * sx, 1), 0.85 * sh / max(h * sy, 1))
    factor = max(1.0, min(float(z.get("factor", 1.8)), fit))
    if factor <= 1.01:
        return ""
    u = f"clip((on/{FPS}-{z.get('at', 0.4)})/0.6,0,1)"
    zoom = f"1+{factor - 1:.3f}*{u}*{u}*(3-2*{u})"
    return (
        f"scale=iw*2:ih*2,zoompan=z='{zoom}':d=1:fps={FPS}:s={sw}x{sh}:"
        f"x='clip({cx:.1f}-iw/zoom/2,0,iw-iw/zoom)':y='clip({cy:.1f}-ih/zoom/2,0,ih-ih/zoom)',"
    )


def step_clip(tmp, rec_dir, tl, step, out, lead, frame, split_image=None):
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
    cut = (
        f"fps={FPS},tpad=stop_mode=clone:stop_duration=10,"
        f"trim=start={start:.3f}:duration={dur:.3f},setpts=PTS-STARTPTS,{zoom_filter(step, video_size(seg))}"
    )
    chrome = (
        f"pad={W}:{H + TOP}:0:{TOP}:color={color},pad={W}:{FH}:0:0:color=0x0f172a,"
        f"drawtext=fontfile={bold}:textfile={hdr}:fontsize=20:fontcolor=white:x=16:y=10,"
        f"drawbox=x=iw-96:y=6:w=80:h=28:color={st_color}:t=fill,"
        f"drawtext=fontfile={bold}:textfile={st}:fontsize=18:fontcolor=white:x=w-56-text_w/2:y=11"
    )

    def fit(w, h):
        return (
            f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
            f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=0x0f172a,setsar=1"
        )

    if split_image:
        # Left: the last frame of the step being proven; right: this step (e.g. the DB query).
        half = W // 2 - W // 2 % 2
        graph = (
            f"[1:v]{fit(half, H)}[l];[0:v]{cut}{fit(W - half, H)}[r];"
            f"[l][r]hstack=inputs=2:shortest=1,drawbox=x={half - 1}:y=0:w=2:h=ih:color=0x0f172a:t=fill,{chrome}"
        )
        inputs = ["-i", str(seg.resolve()), "-loop", "1", "-framerate", str(FPS), "-i", str(split_image.resolve())]
        ff(*inputs, "-filter_complex", graph, "-t", f"{dur:.3f}", "-an", *encode_args(Path(out).resolve()), cwd=tmp)
    else:
        ff(
            "-i",
            str(seg.resolve()),
            "-vf",
            cut + fit(W, H) + "," + chrome,
            "-an",
            *encode_args(Path(out).resolve()),
            cwd=tmp,
        )
    return dur


def chapters_file(tmp, tl, title_seconds):
    lines = [";FFMETADATA1", f"title={tl['scenario']}", "", "[CHAPTER]", "TIMEBASE=1/1000", "START=0"]
    lines += [f"END={int(title_seconds * 1000)}", "title=Title", ""]
    for s in tl["steps"]:
        lines += ["[CHAPTER]", "TIMEBASE=1/1000", f"START={int(s['final_start'] * 1000)}"]
        lines += [f"END={int(s['final_end'] * 1000)}", f"title={s['id']} {s['title']} ({s['status'].upper()})", ""]
    return text_file(tmp, "chapters.txt", "\n".join(lines))


def split_source(rec_dir, tl, i, step):
    """Screenshot shown beside a `layout: split` step: `split_with` step, else the previous step."""
    if step.get("layout") != "split":
        return None
    ref = step.get("split_with") or (tl["steps"][i - 2]["id"] if i > 1 else None)
    src = next((s for s in tl["steps"] if s["id"] == ref), None)
    path = rec_dir / src["screenshot"] if src and src.get("screenshot") else None
    return path if path and path.is_file() else None


def subtitle_languages(tl, lang=None):
    """Languages found in per-step `subtitle: {en: ..., vi: ...}` maps; the burned one first."""
    langs = list(dict.fromkeys(k for s in tl["steps"] if isinstance(s.get("subtitle"), dict) for k in s["subtitle"]))
    burn = lang or tl.get("lang") or (langs[0] if langs else None)
    if lang and langs and lang not in langs:
        raise ValueError(f"no subtitles in {lang!r}; scenario has {', '.join(langs)}")
    return [burn, *[x for x in langs if x != burn]] if burn else []


def pick_subtitle(step, lang):
    sub = step.get("subtitle", step["title"])
    if not isinstance(sub, dict):
        return str(sub)
    return str(sub.get(lang) or next(iter(sub.values()), step["title"]))


def compose(timeline_path, out=None, lead=0.3, title_seconds=3.0, lang=None):
    """Build final.mp4 (+ subtitles.srt, report.md/html/xlsx, timeline.final.json, manifest.sha256)."""
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
        langs = subtitle_languages(tl, lang) or [None]
        clips, srt, t = [], {x: [] for x in langs}, 0.0
        title = tmpd / "00-title.mp4"
        title_card(tmp, tl, title, title_seconds, size)
        clips.append(title)
        t += title_seconds
        for i, step in enumerate(tl["steps"], 1):
            clip = tmpd / f"{i:02d}-{step['id']}.mp4"
            dur = step_clip(tmp, rec_dir, tl, step, clip, lead, size, split_source(rec_dir, tl, i, step))
            clips.append(clip)
            for x, cues in srt.items():
                cues.append(f"{len(cues) + 1}\n{ts(t + 0.2)} --> {ts(t + dur - 0.1)}\n{pick_subtitle(step, x)}\n")
            if isinstance(step.get("subtitle"), dict):
                step["subtitles"] = step["subtitle"]
            step["subtitle"] = pick_subtitle(step, langs[0])
            step["final_start"], step["final_end"] = round(t, 3), round(t + dur, 3)
            t += dur
        (tmpd / "list.txt").write_text("".join(f"file '{c.name}'\n" for c in clips))
        ff("-f", "concat", "-safe", "0", "-i", "list.txt", "-c", "copy", "joined.mp4", cwd=tmp)
        srt_text = "\n".join(srt[langs[0]])
        (rec_dir / "subtitles.srt").write_text(srt_text, encoding="utf-8")
        for x, cues in srt.items():
            if x and len(srt) > 1:
                (rec_dir / f"subtitles.{x}.srt").write_text("\n".join(cues), encoding="utf-8")
        if langs[0]:
            tl["lang"] = langs[0]
        (tmpd / "subs.srt").write_text(srt_text, encoding="utf-8")
        # libass scales SRT styles from a 288px-high canvas: FontSize 10 ~ 28px, MarginV 6 ~ 17px at 808px.
        font_name = subtitle_font_name()
        style = (
            f"FontName={font_name},FontSize=10,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,"
            "BorderStyle=1,Outline=0.6,Shadow=0,MarginV=6,Alignment=2"
        )
        chapters = chapters_file(tmp, tl, title_seconds)
        ff(
            "-i",
            "joined.mp4",
            "-i",
            chapters,
            "-map",
            "0:v",
            "-map_chapters",
            "1",
            "-vf",
            f"subtitles=subs.srt:fontsdir=.:force_style='{style}'",
            *encode_args(final),
            cwd=tmp,
        )

    (rec_dir / "report.md").write_text(report_md(tl, final.name), encoding="utf-8")
    (rec_dir / "timeline.final.json").write_text(json.dumps(tl, ensure_ascii=False, indent=2), encoding="utf-8")
    report.write_html(rec_dir, tl, final.name)
    report.write_xlsx(rec_dir, tl, final.name)
    report.write_manifest(rec_dir)
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
