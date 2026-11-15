"""Builds the reel with one FFmpeg filtergraph.

Per clip (clip_filters): trim → 25 fps, 9:16 → optional punch-in at contact → optional freeze-frame
(hook) → its text overlays (text_overlays). Between clips (join): cut (concat) or xfade/acrossfade. Game audio
kept (2.2: no music). The 540x960 preview and the full-quality export use the same code.

Text (L3): every clip has its own list of text items (reel.texts_for). Each item is drawn with Pillow into a
transparent PNG the size of the video - the exact font, size, colour, background (none, box or pill), shadow
and outline the Arrange screen shows - and laid over the clip. Items are kept inside the frame and out of the
keep-away zones where TikTok, Reels and Shorts put their own interface (L5).
"""
from __future__ import annotations

from pathlib import Path

from . import config, media
from . import reel as reel_mod

FPS = media.FPS
FONT_DIR = config.STATIC_DIR / "fonts"
FONT = FONT_DIR / "BarlowCondensed-SemiBold.ttf"
FONTS = {  # (regular, bold) files in static/fonts; a missing file falls back to Barlow Condensed
    "Barlow Condensed": ("BarlowCondensed-Medium.ttf", "BarlowCondensed-SemiBold.ttf"),
    "Bebas Neue": ("BebasNeue-Regular.ttf", "BebasNeue-Regular.ttf"),
    "Oswald": ("Oswald.ttf", "Oswald.ttf"),                       # variable fonts: weight set below
    "Plus Jakarta Sans": ("PlusJakartaSans.ttf", "PlusJakartaSans.ttf"),
}
# Keep-away zones in % of the frame: (left, top, right, bottom). L5.
ZONES = {"top": (0, 0, 100, 9), "bottom": (0, 80, 100, 100), "right": (85, 45, 100, 80)}
LINE_HEIGHT = 1.05
MAX_WIDTH = 0.80   # a text box is at most this share of the frame width (as on the Arrange screen); longer text wraps


def plan(reel: dict, clips: dict[int, dict], duration: float | None = None) -> list[dict]:
    """The clips in order with their source window and effects - shared by preview and export.

    A window that would start before 0 or end after the video is cut to fit, and the contact point is
    measured from the cut start, so freeze-frame and punch-in land on the right frame (R27)."""
    out = []
    seq = reel_mod.ordered(reel, clips)  # hook, then the clips in play order (2.2: no header cards)
    for i, (_, e) in enumerate(seq):
        c = clips[e["index"]]
        start = max(0.0, c["t"] - c["before"])
        end = c["t"] + c["after"]
        if duration:
            end = min(end, duration)
        out.append({"i": i, "index": c["index"], "start": start, "len": max(0.2, end - start),
                    "contact": max(0.0, c["t"] - start), "kind": c["kind"], "label": (c.get("text") or "").strip(),
                    "default_label": c.get("label", ""), "over": c["over"],
                    "trans": None if i == 0 else (e.get("trans") or reel["trans"]),
                    "freeze": reel["freeze"] and i == 0, "last": i == len(seq) - 1})
    return out


# ---------- text ----------
def font_file(name: str, bold: bool) -> Path:
    files = FONTS.get(name) or FONTS["Barlow Condensed"]
    p = FONT_DIR / files[1 if bold else 0]
    return p if p.exists() else FONT


def _wrap(text: str, font, max_px: float) -> str:
    """Break lines at spaces so no line is wider than max_px (your own line breaks are kept)."""
    out = []
    for para in text.splitlines() or [""]:
        line = ""
        for word in para.split(" "):
            trial = f"{line} {word}".strip()
            if line and font.getlength(trial) > max_px:
                out.append(line)
                line = word
            else:
                line = trial
        out.append(line)
    return chr(10).join(out)


def _measure(item: dict, W: int):
    """(font, wrapped text, box width px, box height px, x offset, y offset to draw the text at) for width W."""
    from PIL import ImageDraw, ImageFont, Image
    fs = max(8, round(item["size"] / 100 * W))
    font = ImageFont.truetype(str(font_file(item["font"], item["bold"])), fs)
    try:  # variable fonts (Oswald, Plus Jakarta Sans): pick the weight
        axes = font.get_variation_axes()
        if axes and axes[0].get("minimum") is not None:
            font.set_variation_by_axes([min(axes[0]["maximum"], 700 if item["bold"] else 500)])
    except (OSError, AttributeError, KeyError):
        pass
    text = item["text"].upper() if item["caps"] else item["text"]
    px, py = (0.8, 0.2) if item["bg"] == "pill" else (0.35, 0.15)
    text = _wrap(text, font, MAX_WIDTH * W - 2 * px * fs)
    d = ImageDraw.Draw(Image.new("L", (1, 1)))
    l, t, r, b = d.multiline_textbbox((0, 0), text, font=font, spacing=round(fs * (LINE_HEIGHT - 1)), align="center",
                                      stroke_width=round(fs * 0.04) if item["outline"] else 0)
    # padding minus the bbox origin: the glyphs start (l, t) from where they're drawn
    return font, text, (r - l) + 2 * px * fs, (b - t) + 2 * py * fs, px * fs - l, py * fs - t


def fit_in_safe_area(item: dict, W: int, H: int) -> tuple[float, float]:
    """The item's centre (px), moved so its box stays in the frame and out of the keep-away zones. Same rule as
    the Arrange screen, so what you see there is what's rendered."""
    _, _, bw, bh, _, _ = _measure(item, W)
    w, h = bw / W * 100, bh / H * 100
    x = min(max(item["x"], w / 2 + 2), 100 - w / 2 - 2)
    y = min(max(item["y"], ZONES["top"][3] + h / 2 + 1), ZONES["bottom"][1] - h / 2 - 1)
    rx1, ry1, _, ry2 = ZONES["right"]
    if y + h / 2 > ry1 and y - h / 2 < ry2 and x + w / 2 > rx1:
        x = rx1 - w / 2 - 1
    return x / 100 * W, y / 100 * H


def draw_text_png(item: dict, W: int, H: int, path: Path) -> None:
    """One text item as a transparent W x H PNG, placed and styled exactly."""
    from PIL import Image, ImageColor, ImageDraw, ImageFilter
    font, text, bw, bh, padx, pady = _measure(item, W)
    cx, cy = fit_in_safe_area(item, W, H)
    left, top = cx - bw / 2, cy - bh / 2
    fs = font.size
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    if item["bg"] != "none":
        bg = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        radius = bh / 2 if item["bg"] == "pill" else round(fs * 0.12)
        ImageDraw.Draw(bg).rounded_rectangle((left, top, left + bw, top + bh), radius=radius,
                                             fill=(0, 0, 0, round(255 * item["bo"])))
        img = Image.alpha_composite(img, bg)
    spacing = round(fs * (LINE_HEIGHT - 1))
    stroke = round(fs * 0.04) if item["outline"] else 0
    pos = (left + padx, top + pady)
    if item["shadow"]:
        sh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ImageDraw.Draw(sh).multiline_text((pos[0], pos[1] + fs * 0.06), text, font=font, fill=(0, 0, 0, 205),
                                          spacing=spacing, align="center", stroke_width=stroke, stroke_fill=(0, 0, 0, 205))
        img = Image.alpha_composite(img, sh.filter(ImageFilter.GaussianBlur(fs * 0.12)))
    ImageDraw.Draw(img).multiline_text(pos, text, font=font, fill=ImageColor.getrgb(item["color"]) + (255,),
                                       spacing=spacing, align="center", stroke_width=stroke, stroke_fill=(0, 0, 0, 255))
    img.save(path)


def text_overlays(items_for_clip: list[dict], W: int, H: int, workdir: Path, clip_no: int) -> list[tuple[Path, str]]:
    """(png, enable expression) per text item of one clip."""
    out = []
    for k, item in enumerate(items_for_clip):
        if not item["text"].strip():
            continue
        png = workdir / f"text_{clip_no}_{k}.png"
        draw_text_png(item, W, H, png)
        out.append((png, "lt(t,3.2)" if item.get("show") == "first3" else "1"))
    return out


# ---------- per clip ----------
def clip_filters(it: dict, reel: dict, W: int, H: int) -> tuple[str, list[str], str, float]:
    """(video chain, extra audio filter lines, audio label, output length) for one clip. 2.2: no colour grade; the
    clip goes out as the camera recorded it."""
    i, K = it["i"], round(it["contact"] * FPS)
    v = f"{it['vin']}fps={FPS},scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1"
    if reel["punch"]:
        z, n = reel["punch_zoom"], round(0.3 * FPS)
        v += (f",zoompan=z='if(lt(on,{K}),1,min({z},1+({z}-1)*(on-{K})/{n}))':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
              f":d=1:s={W}x{H}:fps={FPS}")
    a = f"{it['ain']}aresample=48000,aformat=channel_layouts=stereo,asetpts=PTS-STARTPTS"
    length, lines = it["len"], []
    if it["freeze"]:
        F = round(reel["freeze_dur"] * FPS)
        v += f",loop=loop={F}:size=1:start={K},setpts=N/({FPS}*TB)"
        fz = F / FPS
        lines += [f"{a},asplit=2[a{i}x][a{i}y]",
                  f"[a{i}x]atrim=0:{K / FPS:.3f},asetpts=PTS-STARTPTS[a{i}p]",
                  f"anullsrc=r=48000:cl=stereo,atrim=0:{fz:.3f}[a{i}s]",
                  f"[a{i}y]atrim=start={K / FPS:.3f},asetpts=PTS-STARTPTS[a{i}q]",
                  f"[a{i}p][a{i}s][a{i}q]concat=n=3:v=0:a=1[a{i}]"]
        length += fz
    else:
        lines.append(f"{a}[a{i}]")
    return v, lines, f"[a{i}]", length


def join(items: list[dict], trans_dur: float) -> tuple[list[str], str, str, float]:
    """Filter lines that join the clips in order, and the final video/audio labels and length."""
    fc, d = [], trans_dur
    acc_v, acc_a, L = "[v0]", "[a0]", items[0]["out_len"]
    for it in items[1:]:
        i, tr = it["i"], it["trans"]
        if tr == "cut":
            fc.append(f"{acc_v}[v{i}]concat=n=2:v=1:a=0[vj{i}]")
            fc.append(f"{acc_a}[a{i}]concat=n=2:v=0:a=1[aj{i}]")
            L += it["out_len"]
        else:
            fc.append(f"{acc_v}[v{i}]xfade=transition={tr}:duration={d}:offset={L - d:.3f}[vj{i}]")
            fc.append(f"{acc_a}[a{i}]acrossfade=d={d}[aj{i}]")
            L += it["out_len"] - d
        acc_v, acc_a = f"[vj{i}]", f"[aj{i}]"
    return fc, acc_v, acc_a, L


def build_command(reel: dict, clips: dict[int, dict], src, out: Path, workdir: Path,
                  size=(540, 960), music: Path | None = None, quality: str = "proxy",
                  encode_args: list[str] | None = None,
                  audio_args: list[str] | None = None, final_filter: str = "", duration: float | None = None) -> tuple[list[str], float]:
    """Return (ffmpeg args, output duration). Run with cwd=workdir.

    src is a file (the proxy) or a function (start, length) → [(file, start_in_file, length), ...] that maps the
    match timeline onto the source files (a clip can straddle two files)."""
    W, H = size
    workdir.mkdir(parents=True, exist_ok=True)
    for old in workdir.glob("text_*.png"):
        old.unlink(missing_ok=True)
    items = plan(reel, clips, duration)
    if not items:
        raise media.MediaError("The reel is empty. Add at least one clip.")
    texts = reel_mod.texts_for(reel, clips)
    segs = src if callable(src) else (lambda s, n: [(src, s, n)])
    cmd = [media.ffmpeg(), "-v", "error", "-nostats", "-progress", "pipe:2", "-y"]
    fc, n_in, pre = [], 0, []
    for it in items:
        parts = segs(it["start"], it["len"])
        idx = []
        for f, s, n in parts:
            cmd += ([] if not callable(src) else ["-hwaccel", "auto"]) + ["-ss", f"{s:.3f}", "-t", f"{n:.3f}", "-i", str(f)]
            idx.append(n_in)
            n_in += 1
        i = it["i"]
        if len(idx) == 1:
            it["vin"], it["ain"] = f"[{idx[0]}:v]", f"[{idx[0]}:a]"
        else:  # straddles two source files: join the pieces first
            pre.append("".join(f"[{k}:v]fps={FPS},setsar=1[pv{i}_{k}];" for k in idx)
                       + "".join(f"[pv{i}_{k}][{k}:a]" for k in idx) + f"concat=n={len(idx)}:v=1:a=1[jv{i}][ja{i}]")
            it["vin"], it["ain"] = f"[jv{i}]", f"[ja{i}]"
    fc += pre
    overlays = []  # (clip i, png input index, enable)
    for it in items:
        items_txt = texts.get(it["index"], [])
        for png, enable in text_overlays(items_txt, W, H, workdir, it["i"]):
            cmd += ["-loop", "1", "-framerate", str(FPS), "-i", png.name]
            overlays.append((it["i"], n_in, enable))
            n_in += 1
    music_in = n_in
    if music:
        cmd += ["-stream_loop", "-1", "-i", str(music)]
    for it in items:
        i = it["i"]
        v, alines, _, length = clip_filters(it, reel, W, H)
        fc += alines
        mine = [o for o in overlays if o[0] == i]
        if not mine:
            fc.append(f"{v},format=yuv420p,settb=AVTB[v{i}]")
        else:
            fc.append(f"{v},settb=AVTB[vb{i}_0]")
            for k, (_, inp, enable) in enumerate(mine):
                last = k == len(mine) - 1
                fc.append(f"[vb{i}_{k}][{inp}:v]overlay=0:0:shortest=1:enable='{enable}'"
                          + (f",format=yuv420p,settb=AVTB[v{i}]" if last else f"[vb{i}_{k + 1}]"))
        it["out_len"] = length
    jfc, acc_v, acc_a, L = join(items, reel["trans_dur"])
    fc += jfc
    if music:
        vol = reel["music_vol"] / 100
        fc.append(f"[{music_in}:a]aresample=48000,aformat=channel_layouts=stereo,volume={vol:.2f},atrim=0:{L:.3f},"
                  f"afade=t=out:st={max(0.0, L - 1.5):.3f}:d=1.5[mus]")
        fc.append(f"{acc_a}[mus]amix=inputs=2:duration=first:normalize=0[amx]")
        acc_a = "[amx]"
    if final_filter:
        fc.append(f"{acc_v}{final_filter}[vout]")
        acc_v = "[vout]"
    cmd += ["-filter_complex", ";".join(fc), "-map", acc_v, "-map", acc_a, "-r", str(FPS),
            *(encode_args or [*media.h264_args(quality), "-pix_fmt", "yuv420p"]),
            *(audio_args or ["-c:a", "aac", "-b:a", "160k"]), "-movflags", "+faststart", str(out)]
    return cmd, L


def render_preview(match_dir: Path, reel: dict, clips: dict[int, dict], on_progress, cancel) -> dict:
    work = match_dir / "work"
    src = work / "proxy.mp4"
    if not src.exists():
        raise media.MediaError("No preview video yet — run the sync first.")
    rdir = work / "render"
    out = work / "reel_preview.part.mp4"
    duration = (config.read_json(work / "media.json", {}) or {}).get("duration")
    cmd, total = build_command(reel, clips, src, out, rdir, (540, 960), None, duration=duration)  # 2.2: no music
    try:
        media.run(cmd, total=total, on_progress=on_progress, cancel=cancel, cwd=rdir)
        final = work / "reel_preview.mp4"
        config.replace_with_retry(out, final)
    finally:
        out.unlink(missing_ok=True)
    return {"duration": round(total, 2), "file": final.name}

