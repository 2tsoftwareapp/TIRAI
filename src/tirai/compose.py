"""Compose the final evidence video from a recorded timeline.

timeline.json (from `tirai run --record`) -> per-step clips cut from the per-tab recordings
-> header bar (tab, step, PASS/FAIL) -> title card -> concat -> burned subtitles.
Writes final.mp4, subtitles.srt, report.md/.html/.xlsx, timeline.final.json and manifest.sha256 next to the timeline.
"""

import json
import os
import re
import shutil
import tempfile
from pathlib import Path

from tirai import export, report
from tirai.system import ffmpeg_bin, ffprobe_bin, find_font, run_text, subtitle_font_name  # noqa: F401

FPS = 30
TOP, BOTTOM = 40, 84  # header bar (tab/step/status) and subtitle band (fits 2 lines cleanly)
DEFAULT_SIZE = (1280, 720)
DRIVER_NAMES = {"agent-browser": "agent-browser", "bsk": "BrowserSkill", "agent-desktop": "agent-desktop"}
TAB_COLORS = ["0x1f6feb", "0x7c3aed", "0x0e7490", "0xb45309"]
THEME_DEFAULTS = {
    "header_size": 20,
    "header_height": TOP,
    "subtitle_size": 24,
    "subtitle_height": BOTTOM,
    "subtitle_bg": "#0f172a",
    "subtitle_color": "#ffffff",
    "tab_colors": ["#1f6feb", "#7c3aed", "#0e7490", "#b45309"],
    "pass_color": "#16a34a",
    "fail_color": "#dc2626",
    "accent": "#e5252a",
    "spotlight_opacity": 0.30,
}


def resolve_theme(tl: dict | None = None) -> dict:
    th = {**THEME_DEFAULTS, **((tl or {}).get("theme") or {})}
    th["header_height"] = int(th["header_height"]) - int(th["header_height"]) % 2
    th["subtitle_height"] = int(th["subtitle_height"]) - int(th["subtitle_height"]) % 2
    return th


def _hex_to_ff(color: str) -> str:
    c = str(color or "#0f172a").strip()
    if c.startswith("0x"):
        return c
    return "0x" + c.lstrip("#")


def _hex_to_ass(color: str) -> str:
    c = str(color or "#ffffff").strip().lstrip("#")
    if len(c) != 6:
        return "&H00FFFFFF"
    r, g, b = c[0:2], c[2:4], c[4:6]
    return f"&H00{b}{g}{r}".upper()


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


def ass_ts(sec):
    """ASS timestamp h:mm:ss.cc (centiseconds)."""
    cs = max(0, int(round(sec * 100)))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, c = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{c:02d}"


def ass_escape(text):
    return str(text).replace("\r", " ").replace("\n", "\\N")


def _ass_style(name, font, size, bold, outline, align, ml, mr, mv, color="&H00FFFFFF"):
    return (
        f"Style: {name},{font},{size},{color},&H000000FF,&H00000000,&H80000000,{bold},0,0,0,100,100,0,0,1,"
        f"{outline},0,{align},{ml},{mr},{mv},1"
    )


def _ass_doc(play_x, styles, events):
    """PlayResY stays 288 so the subtitle style renders exactly like the old SRT force_style."""
    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {play_x}",
        "PlayResY: 288",
        "WrapStyle: 0",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, "
        "Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
        "MarginL, MarginR, MarginV, Encoding",
        *styles,
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    lines += [f"Dialogue: 0,{a},{b},{style},,0,0,0,,{text}" for a, b, style, text in events]
    return "\n".join(lines) + "\n"


def build_ass(tl, size, title_seconds):
    """One ASS file for the title card, header bar and subtitles; libass font fallback covers CJK."""
    W, H = size
    th = resolve_theme(tl)
    top, bottom = th["header_height"], th["subtitle_height"]
    fh = H + top + bottom
    k = 288 / fh
    play_x = max(16, round(W * k))
    font = th.get("font") or subtitle_font_name()
    sub_color = _hex_to_ass(th["subtitle_color"])
    sub_fs = max(1, round(th["subtitle_size"] * k))
    sub_small_fs = max(1, round(max(16, th["subtitle_size"] - 5) * k))
    sub_mv = max(2, round(max(8, (bottom - th["subtitle_size"] * 2.3) / 2) * k))
    hdr_fs = max(1, round(th["header_size"] * k))
    hdr_mv = max(1, round(max(4, (top - th["header_size"]) / 2) * k))
    passed = sum(s["status"] == "passed" for s in tl["steps"])
    styles = [
        _ass_style("Sub", font, sub_fs, 0, 0.5, 2, max(6, round(24 * k)), max(6, round(24 * k)), sub_mv, sub_color),
        _ass_style(
            "Hdr",
            font,
            hdr_fs,
            -1,
            0,
            7,
            max(2, round(16 * k)),
            max(10, round(110 * k)),
            hdr_mv,
        ),
        _ass_style("T1", font, max(1, round(44 * k)), -1, 0, 5, 0, 0, 0, sub_color),
        _ass_style("T2", font, max(1, round(24 * k)), 0, 0, 5, 0, 0, 0, sub_color),
        _ass_style("T3", font, max(1, round(20 * k)), 0, 0, 5, 0, 0, 0, sub_color),
        _ass_style("Pdf", font, max(1, round(22 * k)), -1, 0, 7, max(2, round(20 * k)), 10, max(1, round(8 * k))),
    ]
    cx = round(play_x / 2)
    end_title = ass_ts(title_seconds)

    def title_line(text, style, dy):
        # drawtext centred with y=(h-text_h)/2+dy; \an5 + \pos does the same in script units.
        y = round((fh / 2 + dy) * k)
        return (ass_ts(0), end_title, style, ass_escape(f"{{\\pos({cx},{y})}}{text}"))

    events = [
        title_line(tl["scenario"], "T1", -60),
        title_line(f"{passed}/{len(tl['steps'])} steps passed  ·  recorded {tl['created']}", "T2", 10),
        title_line(
            f"Evidence: {DRIVER_NAMES.get(tl.get('driver'), 'browser')} recording + TIRAI annotations", "T3", 60
        ),
    ]
    for s in tl["steps"]:
        a, b = ass_ts(s["final_start"]), ass_ts(s["final_end"])
        label = tl["tabs"].get(s["tab"], {}).get("label", s["tab"])
        events.append((a, b, "Hdr", ass_escape(f"{label}   |   {s['id']}  {s.get('title', '')}")))
        sub_a = ass_ts(s["final_start"] + 0.2)
        sub_b = ass_ts(max(s["final_start"] + 0.3, s["final_end"] - 0.1))
        raw_sub = str(s.get("subtitle") or s.get("title", ""))
        sub_txt = ass_escape(raw_sub)
        if len(raw_sub) > 105:
            sub_txt = f"{{\\fs{sub_small_fs}}}{sub_txt}"
        events.append((sub_a, sub_b, "Sub", sub_txt))
    return _ass_doc(play_x, styles, events)


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


def title_card(tmp, out, seconds, frame, tl=None):
    """Plain colour card; its text is burned with the subtitles pass (ASS, so CJK fonts fall back)."""
    W, H = frame
    th = resolve_theme(tl)
    FH = H + th["header_height"] + th["subtitle_height"]
    bg = _hex_to_ff(th["subtitle_bg"])
    ff(
        "-f",
        "lavfi",
        "-i",
        f"color=c={bg}:s={W}x{FH}:d={seconds}:r={FPS}",
        *encode_args(out),
        cwd=tmp,
    )


def _smootherstep(u: str) -> str:
    """Quintic smootherstep 6u^5 - 15u^4 + 10u^3: zero velocity & zero acceleration at endpoints."""
    return f"({u}*{u}*{u}*({u}*(6*{u}-15)+10))"


def follow_filter(z, seg_size, clip_start, clip_dur=None):
    """Zoom in and pan smoothly across action targets (`zoom: follow`/`action`), with optional smooth zoom-out."""
    sw, sh = seg_size
    raw_pts = []
    for p in z["follow"]:
        x, y, w, h = p["rect"]
        vw, vh = p["viewport"]
        sx, sy = sw / max(vw, 1), sh / max(vh, 1)
        raw_pts.append((max(0.0, p["t"] - clip_start), (x + w / 2) * sx * 2, (y + h / 2) * sy * 2))
    if not raw_pts:
        return ""
    # Drop micro-jitter waypoints within ~160px of the previous camera center so adjacent fields stay calm.
    pts = [raw_pts[0]]
    for pt in raw_pts[1:]:
        if ((pt[1] - pts[-1][1]) ** 2 + (pt[2] - pts[-1][2]) ** 2) ** 0.5 >= 320.0:
            pts.append(pt)
    factor = max(1.0, float(z.get("factor", 1.35)))
    T = f"(on/{FPS})"

    def track(i):
        # Smooth quintic pan over 0.9s between distinct action regions.
        expr = f"{pts[0][i]:.1f}"
        for (t, *c), (_, *prev) in zip(pts[1:], pts[:-1], strict=True):
            u = f"clip(({T}-{t - 0.35:.3f})/0.90,0,1)"
            expr += f"+({c[i - 1] - prev[i - 1]:.1f})*{_smootherstep(u)}"
        return expr

    in_at = max(0.0, pts[0][0] - 0.55)
    u = f"clip(({T}-{in_at:.3f})/0.80,0,1)"
    ease_in = _smootherstep(u)
    if z.get("out"):
        out_s = max(0.25, float(z.get("out_duration", 0.75)))
        if z.get("out_at") is not None:
            out_at = max(in_at + 0.85, float(z["out_at"]) - clip_start)
        elif clip_dur is not None:
            out_at = max(in_at + 0.85, clip_dur - out_s - 0.2)
        else:
            out_at = None
        if out_at is not None and (clip_dur is None or out_at < clip_dur - 0.05):
            u_out = f"clip(({T}-{out_at:.3f})/{out_s:.3f},0,1)"
            ease = f"({ease_in}*(1-{_smootherstep(u_out)}))"
        else:
            ease = ease_in
    else:
        ease = ease_in
    zoom = f"1+{factor - 1:.3f}*{ease}"
    return (
        f"scale=iw*2:ih*2,zoompan=z='{zoom}':d=1:fps={FPS}:s={sw}x{sh}:"
        f"x='clip({track(1)}-iw/zoom/2,0,iw-iw/zoom)':y='clip({track(2)}-ih/zoom/2,0,ih-ih/zoom)',"
    )


def warp(idle, clip_start):
    """Time-warp for fast-forwarded waits: (setpts filter, new duration delta, [(a', b', speed)])."""
    spans = [(max(0.0, a - clip_start), max(0.0, b - clip_start), s) for a, b, s in idle or [] if b > a]
    if not spans:
        return "", 0.0, []
    terms = [f"{1 - 1 / s:.4f}*clip(T-{a:.3f},0,{b - a:.3f})" for a, b, s in spans]
    saved = sum((1 - 1 / s) * (b - a) for a, b, s in spans)
    shown, cut = [], 0.0
    for a, b, s in spans:
        shown.append((a - cut, a - cut + (b - a) / s, s))
        cut += (1 - 1 / s) * (b - a)
    return f"setpts='(T-({'+'.join(terms)}))/TB',fps={FPS},", saved, shown


STILL_SPEED = 8.0
STILL_MIN = 2.0


def freezes(path, min_seconds=STILL_MIN):
    """[(start, end)] where the recording does not change for `min_seconds` or more (ffmpeg freezedetect)."""
    p = run_text(
        [ffmpeg_bin() or "ffmpeg", "-hide_banner", "-i", str(path), "-map", "0:v",
         "-vf", f"freezedetect=n=-60dB:d={min_seconds}", "-f", "null", "-"]
    )  # fmt: skip
    starts = [float(x) for x in re.findall(r"freeze_start: ([\d.]+)", p.stderr)]
    ends = [float(x) for x in re.findall(r"freeze_end: ([\d.]+)", p.stderr)]
    ends += [video_duration(path)] * (len(starts) - len(ends))  # still frozen when the recording ends
    return list(zip(starts, ends, strict=False))


def video_duration(path):
    p = run_text([ffprobe_bin() or "ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                  str(path)])  # fmt: skip
    try:
        return float(p.stdout.strip())
    except ValueError:
        return 0.0


def add_still_spans(step, spans, hold):
    """Fast-forward still stretches inside the step, keeping its start and the closing `hold` at normal speed."""
    lo, hi = step["start"] + 0.3, step["end"] - hold - 0.3
    idle = [list(x) for x in step.get("idle") or []]
    for a, b in spans:
        a, b = max(a + 0.3, lo), min(b - 0.3, hi)
        if b - a < 1.0 or any(a < y and x < b for x, y, _ in idle):
            continue
        idle.append([round(a, 3), round(b, 3), STILL_SPEED])
    if idle:
        step["idle"] = sorted(idle)


def zoom_filter(step, seg_size, clip_start=0.0, clip_dur=None):
    """Ease into the step's `zoom` target, hold, and optionally ease back out (`out: true`)."""
    z = step.get("zoom")
    if not z:
        return ""
    if z.get("follow"):
        return follow_filter(z, seg_size, clip_start, clip_dur=clip_dur)
    sw, sh = seg_size
    x, y, w, h = z["rect"]
    vw, vh = z["viewport"]
    sx, sy = sw / max(vw, 1), sh / max(vh, 1)
    cx, cy = (x + w / 2) * sx * 2, (y + h / 2) * sy * 2  # upscaled 2x below to keep the pan smooth
    fit = min(0.85 * sw / max(w * sx, 1), 0.85 * sh / max(h * sy, 1))
    factor = max(1.0, min(float(z.get("factor", 1.8)), fit))
    if factor <= 1.01:
        return ""
    at = float(z.get("at", 0.4))
    in_s = max(0.2, float(z.get("in", 0.75)))
    T = f"(on/{FPS})"
    u_in = f"clip(({T}-{at:.3f})/{in_s:.3f},0,1)"
    ease_in = _smootherstep(u_in)
    if z.get("out") and clip_dur is not None and clip_dur > at + in_s + 0.35:
        out_s = max(0.2, float(z.get("out_duration", 0.70)))
        out_at = max(at + in_s + 0.25, clip_dur - out_s - 0.15)
        u_out = f"clip(({T}-{out_at:.3f})/{out_s:.3f},0,1)"
        ease = f"({ease_in}*(1-{_smootherstep(u_out)}))"
    else:
        ease = ease_in
    zoom = f"1+{factor - 1:.3f}*{ease}"
    return (
        f"scale=iw*2:ih*2,zoompan=z='{zoom}':d=1:fps={FPS}:s={sw}x{sh}:"
        f"x='clip({cx:.1f}-iw/zoom/2,0,iw-iw/zoom)':y='clip({cy:.1f}-ih/zoom/2,0,ih-ih/zoom)',"
    )


def step_clip(tmp, rec_dir, tl, step, out, lead, frame, split_image=None):
    W, H = frame
    th = resolve_theme(tl)
    top, bottom = th["header_height"], th["subtitle_height"]
    FH = H + top + bottom
    bg = _hex_to_ff(th["subtitle_bg"])
    tab_colors = [_hex_to_ff(c) for c in th["tab_colors"]]
    seg = rec_dir / step["segment"]
    start = max(0.0, step["start"] - lead)
    dur = step["end"] - start
    color = tab_colors[list(tl["tabs"]).index(step["tab"]) % len(tab_colors)]
    status = "PASS" if step["status"] == "passed" else "FAIL"
    st = text_file(tmp, f"st-{step['id']}.txt", status)
    st_color = _hex_to_ff(th["pass_color"] if status == "PASS" else th["fail_color"])
    bold = "font-bold.ttf"
    ff_filter, saved, shown = warp(step.get("idle"), start)
    badges = "".join(
        f"drawtext=fontfile={bold}:text='{s:g}x':fontsize=22:fontcolor=white:box=1:boxcolor={bg}cc:boxborderw=8:"
        f"x=w-text_w-24:y=24:enable='between(t,{a:.2f},{b:.2f})',"
        for a, b, s in shown
    )
    eff_dur = max(0.2, dur - saved)
    fade = (
        f"fade=t=in:st=0:d=0.16:color={bg},fade=t=out:st={max(0.1, eff_dur - 0.16):.3f}:d=0.16:color={bg},"
        if eff_dur >= 0.6
        else ""
    )
    cut = (
        f"fps={FPS},tpad=stop_mode=clone:stop_duration=10,"
        f"trim=start={start:.3f}:duration={dur:.3f},setpts=PTS-STARTPTS,"
        f"{zoom_filter(step, video_size(seg), start, clip_dur=eff_dur)}{ff_filter}{badges}{fade}"
    )
    dur -= saved
    # The header text is burned by the subtitles pass (ASS); the clip only draws the bar and badge.
    badge_y = max(2, (top - 28) // 2)
    chrome = (
        f"pad={W}:{H + top}:0:{top}:color={color},pad={W}:{FH}:0:0:color={bg},"
        f"drawbox=x=iw-96:y={badge_y}:w=80:h=28:color={st_color}:t=fill,"
        f"drawtext=fontfile={bold}:textfile={st}:fontsize=18:fontcolor=white:x=w-56-text_w/2:y={badge_y + 5}"
    )

    def fit(w, h):
        return f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color={bg},setsar=1"

    if split_image:
        # Left: the last frame of the step being proven; right: this step (e.g. the DB query).
        half = W // 2 - W // 2 % 2
        graph = (
            f"[1:v]{fit(half, H)}[l];[0:v]{cut}{fit(W - half, H)}[r];"
            f"[l][r]hstack=inputs=2:shortest=1,drawbox=x={half - 1}:y=0:w=2:h=ih:color={bg}:t=fill,{chrome}"
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


def fit_voice(tmpd, clip, dur, step, text, engine, lang):
    """Synthesize the step's narration; hold the clip's last frame until the speech has finished."""
    from tirai import tts

    wav = tts.synth(text, tmpd / f"voice-{step['id']}.wav", lang=lang, engine=engine)
    step["_voice"] = str(wav)
    need = audio_seconds(wav) + 0.6
    if need <= dur:
        return dur
    longer = clip.with_name(clip.stem + "-voiced.mp4")
    ff("-i", clip.name, "-vf", f"tpad=stop_mode=clone:stop_duration={need - dur:.3f}", "-an",
       *encode_args(longer), cwd=tmpd)  # fmt: skip
    shutil.move(longer, clip)
    return need


def add_voiceover(tmpd, final, tl, engine, lang):
    """Mix each step's narration in at the step's place in the final video."""
    from tirai import tts

    clips = []
    for step in tl["steps"]:
        wav = step.pop("_voice")
        clips.append((wav, step["final_start"] + 0.2, step["final_end"] - step["final_start"] - 0.2))
    voiced = tmpd / ("voiced" + final.suffix)
    ff(
        "-i", str(final), *[a for c in clips for a in ("-i", str(c[0]))],
        "-filter_complex", tts.mix_args(clips), "-map", "0:v", "-map", "[voice]",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "128k", "-shortest", "-map_chapters", "0", str(voiced),
    )  # fmt: skip
    shutil.move(voiced, final)
    return {"engine": tts.available(engine)}


def audio_seconds(path):
    p = run_text([ffmpeg_bin(), "-hide_banner", "-i", str(path)])
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", p.stderr)
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else 0.0


def pdf_page_ass(tmpd, d, i, n, W, H, tl=None, duration=4.0, header=None, subtitle=None):
    """ASS overlay for a preview page clip (header strip + optional bottom subtitle)."""
    th = resolve_theme(tl)
    top, bottom = th["header_height"], th["subtitle_height"]
    fh = H + top + bottom
    k = 288 / fh
    play_x = max(16, round(W * k))
    font = th.get("font") or subtitle_font_name()
    hdr_fs = max(1, round(th["header_size"] * k))
    hdr_mv = max(1, round(max(4, (top - th["header_size"]) / 2) * k))
    sub_fs = max(1, round(th["subtitle_size"] * k))
    sub_mv = max(2, round(max(8, (bottom - th["subtitle_size"] * 2.3) / 2) * k))
    styles = [
        _ass_style("Pdf", font, hdr_fs, -1, 0, 7, max(2, round(20 * k)), max(10, round(110 * k)), hdr_mv),
        _ass_style(
            "Sub",
            font,
            sub_fs,
            0,
            0.5,
            2,
            max(6, round(24 * k)),
            max(6, round(24 * k)),
            sub_mv,
            _hex_to_ass(th["subtitle_color"]),
        ),
    ]
    text = ass_escape(header or f"PDF {d['file']} — page {i}/{n}")
    events = [(ass_ts(0), ass_ts(duration), "Pdf", text)]
    if subtitle:
        events.append((ass_ts(0.15), ass_ts(max(0.3, duration - 0.1)), "Sub", ass_escape(subtitle)))
    name = f"preview-{d.get('step', 'p')}-{Path(d['file']).stem}-{i}.ass"
    (tmpd / name).write_text(_ass_doc(play_x, styles, events), encoding="utf-8")
    return name


def _preview_zoom_spec(page_info: dict, W: int, H: int, zoom_cfg):
    """Map an image-space annotation rect into the letterboxed (W, H) frame for zoom-in/out."""
    if not zoom_cfg or not page_info.get("rect"):
        return None
    iw, ih = page_info["size"]
    rx, ry, rw, rh = page_info["rect"]
    scale = min(W / max(iw, 1), H / max(ih, 1))
    off_x = (W - iw * scale) / 2.0
    off_y = (H - ih * scale) / 2.0
    z = zoom_cfg if isinstance(zoom_cfg, dict) else {}
    return {
        "zoom": {
            "rect": [off_x + rx * scale, off_y + ry * scale, rw * scale, rh * scale],
            "viewport": [W, H],
            "factor": float(z.get("factor", 1.7)),
            "at": float(z.get("at", 0.65)),
            "in": float(z.get("in", 0.65)),
            "out": bool(z.get("out", True)),
            "out_duration": float(z.get("out_duration", 0.6)),
        }
    }


def append_pdf_pages(tmpd, final, tl, rec_dir, size):
    """Append rendered (and optionally annotated/zoomed) PDF, Excel, and image previews to final.mp4."""
    from tirai import previews as pv

    th = resolve_theme(tl)
    top, bottom = th["header_height"], th["subtitle_height"]
    bg = _hex_to_ff(th["subtitle_bg"])
    W, H = size
    FH = H + top + bottom

    items = list(tl.get("previews", []))
    covered = {str(p.get("path", "")) for p in items}
    for d in tl.get("downloads", []):
        if d.get("append") and d["path"] not in covered:
            ext = Path(d["file"]).suffix.lower()
            kind = "pdf" if ext == ".pdf" else "xlsx" if ext == ".xlsx" else None
            if kind:
                items.append({**d, "kind": kind})

    if not items:
        return

    clips = []
    for idx, item in enumerate(items, 1):
        src = rec_dir / item["path"]
        if not src.is_file():
            continue
        kind = item.get("kind", "pdf")
        anns = pv.normalize_preview_annotations(item.get("annotate"), item.get("contains"))
        spot = bool(item.get("spotlight", False))
        pdir = tmpd / f"prev-{idx}"
        try:
            if kind == "pdf":
                pages = pv.render_pdf_preview(src, pdir, anns, theme=th, spotlight=spot)
            elif kind == "xlsx":
                pages = pv.render_xlsx_preview(
                    src,
                    pdir,
                    anns,
                    sheet=item.get("sheet"),
                    max_rows=int(item.get("max_rows", 35)),
                    max_cols=int(item.get("max_cols", 14)),
                    theme=th,
                    spotlight=spot,
                )
            else:
                pages = pv.render_image_preview(src, pdir, anns, theme=th, spotlight=spot)
        except RuntimeError as e:
            print(f"warning: {e}; skipping preview for {item['file']}")
            continue

        default_dur = 5.0 if (anns and item.get("zoom")) else 4.0
        dur = float(item.get("hold") or default_dur)
        badge_chrome = ""
        if "ok" in item:
            status = "PASS" if item["ok"] else "FAIL"
            st = text_file(tmpd, f"pv-st-{idx}.txt", status)
            st_color = _hex_to_ff(th["pass_color"] if item["ok"] else th["fail_color"])
            badge_y = max(2, (top - 28) // 2)
            badge_chrome = (
                f",drawbox=x=iw-96:y={badge_y}:w=80:h=28:color={st_color}:t=fill,"
                f"drawtext=fontfile=font-bold.ttf:textfile={st}:fontsize=18:fontcolor=white:"
                f"x=w-56-text_w/2:y={badge_y + 5}"
            )

        for pinfo in pages:
            i, total = pinfo["page"], pinfo["total"]
            img = pinfo["image"]
            kind_lbl = "PDF" if kind == "pdf" else "EXCEL" if kind == "xlsx" else "IMAGE"
            if item.get("title"):
                hdr = f"{item['title']} ({i}/{total})" if total > 1 else item["title"]
            elif kind == "xlsx" and pinfo.get("sheet"):
                hdr = f"EXCEL {item['file']} [{pinfo['sheet']}]"
            elif total > 1 or kind == "pdf":
                hdr = f"{kind_lbl} {item['file']} — page {i}/{total}"
            else:
                hdr = f"{kind_lbl} {item['file']}"
            ass = pdf_page_ass(
                tmpd, item, i, total, W, H, tl=tl, duration=dur, header=hdr, subtitle=item.get("subtitle")
            )
            zstep = _preview_zoom_spec(pinfo, W, H, item.get("zoom"))
            zfilt = zoom_filter(zstep, (W, H), 0.0, clip_dur=dur) if zstep else ""
            clip = tmpd / f"prev-{idx}-{i}.mp4"
            vf = (
                f"fps={FPS},"
                f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
                f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color={bg},setsar=1,"
                f"{zfilt}"
                f"pad={W}:{H + top}:0:{top}:color=0x111827,"
                f"pad={W}:{FH}:0:0:color={bg}"
                f"{badge_chrome},"
                f"subtitles={ass}:fontsdir=."
            )
            ff(
                "-loop",
                "1",
                "-framerate",
                str(FPS),
                "-t",
                f"{dur:.2f}",
                "-i",
                str(img.resolve()),
                "-vf",
                vf,
                *encode_args(clip),
                cwd=tmpd,
            )
            clips.append(clip)

    if not clips:
        return
    listing = "".join(f"file '{final.resolve()}'\n" for _ in [0]) + "".join(f"file '{c.name}'\n" for c in clips)
    (tmpd / "pdf-list.txt").write_text(listing)
    out = tmpd / "final-with-pdf.mp4"
    ff("-f", "concat", "-safe", "0", "-i", "pdf-list.txt", "-c", "copy", out.name, cwd=tmpd)
    shutil.move(out, final)
    if tl.get("downloads"):
        tl["downloads"] = [
            dict(d, pdf_appended=True) if d.get("append") and d["file"].lower().endswith(".pdf") else d
            for d in tl["downloads"]
        ]
    if tl.get("previews"):
        tl["previews"] = [dict(p, appended=True) for p in tl["previews"]]


def ocr_check(final, tl):
    """`privacy.ocr`: warn (default when tesseract is installed), fix (blur hits), fail, or off."""
    from tirai import ocr
    from tirai.system import tesseract_bin

    priv = tl.get("privacy")
    mode = (priv or {}).get("ocr", "warn")
    if not priv or mode == "off" or (mode == "warn" and not tesseract_bin()):
        return
    hits = ocr.scan(final, priv.get("mask"), priv.get("patterns"), priv.get("keep") or ())
    tl["ocr"] = {"mode": mode, "hits": hits}
    for h in hits:
        print(f"ocr: possible PII {h['text']} at {h['t']:.1f}s box {h['box']}")
    if hits and mode == "fix":
        tl["ocr"]["blurred_regions"] = ocr.redact(final, hits)
        print(f"ocr: blurred {tl['ocr']['blurred_regions']} region(s) in {final.name}")
    elif hits and mode == "fail":
        raise RuntimeError(f"ocr found {len(hits)} possible PII hit(s) in {final.name} (privacy.ocr: fail)")


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


def compose(timeline_path, out=None, lead=0.3, title_seconds=3.0, lang=None, voice=None, trim_still=False):
    """Build final.mp4 (+ subtitles.srt, report.md/html/xlsx, timeline.final.json, manifest.sha256)."""
    if not ffmpeg_bin():
        raise RuntimeError("ffmpeg not found; run `tirai setup` or set FFMPEG_BIN")
    tl_path = Path(timeline_path)
    tl = json.loads(tl_path.read_text(encoding="utf-8"))
    if tl.get("mode") != "record":
        raise ValueError("timeline was not recorded; run `tirai run --record` first")
    # Only the ASCII badges still use drawtext; all scenario text (title card, header bar, subtitles,
    # PDF page headers) is burned through libass, whose font fallback covers CJK and Vietnamese mixed text.
    fonts = (find_font(False), find_font(True))
    if not fonts[0] or not fonts[1]:
        raise RuntimeError("no font found; set TIRAI_FONT to a .ttf file")
    rec_dir = tl_path.parent
    final = Path(out) if out else rec_dir / "final.mp4"
    if trim_still or tl.get("trim_still"):
        found = {seg["file"]: freezes(rec_dir / seg["file"]) for seg in tl.get("segments", [])}
        for step in tl["steps"]:
            if step.get("segment") in found and step.get("end") is not None:
                add_still_spans(step, found[step["segment"]], float(tl.get("hold", 2.5)))

    with tempfile.TemporaryDirectory() as tmp:
        tmpd = Path(tmp)
        # Fonts are copied next to the filter inputs so every ffmpeg path is relative (no drive-letter escaping).
        shutil.copyfile(fonts[0], tmpd / "font.ttf")
        shutil.copyfile(fonts[1], tmpd / "font-bold.ttf")
        size = frame_size(tl, rec_dir)
        langs = subtitle_languages(tl, lang) or [None]
        clips, srt, t = [], {x: [] for x in langs}, 0.0
        title = tmpd / "00-title.mp4"
        title_card(tmp, title, title_seconds, size, tl=tl)
        clips.append(title)
        t += title_seconds
        for i, step in enumerate(tl["steps"], 1):
            clip = tmpd / f"{i:02d}-{step['id']}.mp4"
            dur = step_clip(tmp, rec_dir, tl, step, clip, lead, size, split_source(rec_dir, tl, i, step))
            if voice:
                dur = fit_voice(tmpd, clip, dur, step, pick_subtitle(step, langs[0]), voice, langs[0])
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
        (tmpd / "subs.ass").write_text(build_ass(tl, size, title_seconds), encoding="utf-8")
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
            "subtitles=subs.ass:fontsdir=.",
            *encode_args(final),
            cwd=tmp,
        )
        if voice:
            tl["voiceover"] = add_voiceover(tmpd, final, tl, voice, langs[0])
        append_pdf_pages(tmpd, final, tl, rec_dir, size)
    ocr_check(final, tl)

    (rec_dir / "report.md").write_text(report_md(tl, final.name), encoding="utf-8")
    (rec_dir / "timeline.final.json").write_text(json.dumps(tl, ensure_ascii=False, indent=2), encoding="utf-8")
    report.write_html(rec_dir, tl, final.name)
    report.write_xlsx(rec_dir, tl, final.name)
    export.write(rec_dir, tl, ("junit",), video=final.name)
    report.write_manifest(rec_dir)
    _resign(rec_dir)
    return final, t


def _resign(rec_dir):
    """A new manifest invalidates any old signature: re-sign with $TIRAI_SIGN_KEY or drop the stale files."""
    from tirai import sign

    if key := os.environ.get("TIRAI_SIGN_KEY"):
        sign.sign(rec_dir, key, tsa=os.environ.get("TIRAI_TSA_URL"))
        return
    for name in (sign.SIG, sign.PUB, sign.TSR):
        (Path(rec_dir) / name).unlink(missing_ok=True)


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
    return "\n".join(lines + report.extra_md(tl)) + "\n"
