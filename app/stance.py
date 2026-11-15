"""S3: "you at the crease" - find the moments the head-cam sees what it sees when you face up.

Prep writes small frames of the lower 60% of the picture (the pitch strip and your feet), 36x38 RGB at 4 fps,
to work/stance.u8 (about 1 MB a minute). A reference frame - by default 1.5 s before your tagged first shot -
is compared with every frame (brightness plus colour, normalised correlation). Runs of high similarity are
stance moments; each of your balls should come just after one, your partner's shouldn't (you're at the other
end). No AI and no ball or bat detection: only how much the view looks like your stance.

Tested on the 04/11/2026 match: all 11 other balls of yours scored 0.83-0.91 just before the hit, your
partner's about 0.39, and every moment above 0.75 led to one of your balls.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from . import config, media

W, H, ROW0 = 36, 38, 26          # lower 60% of a 36x64 frame
FPS = 4
FRAME = W * H * 3
FILE = "stance.u8"
THRESHOLD = 0.75                 # moments: score above this for at least MIN_FRAMES frames
MIN_FRAMES = 2
BEFORE = (6.0, 0.3)              # a ball "has a stance moment" if one is in [t - 6 s, t - 0.3 s]
REF_LEAD = 1.5                   # default reference: this long before the tagged first shot
CHUNK = 2000


def filter_branch(label_in: str, label_out: str) -> str:
    """The FFmpeg filter that makes the stance frames during prep."""
    return f"{label_in}fps={FPS},scale={W}:64,crop={W}:{H}:0:{ROW0},format=rgb24{label_out}"


def ensure_frames(work: Path, cancel=None) -> Path:
    """work/stance.u8, made from the proxy if this match was prepared before stance frames existed."""
    out = work / FILE
    if out.exists() and out.stat().st_size >= FRAME:
        return out
    proxy = work / "proxy.mp4"
    if not proxy.exists():
        raise media.MediaError("No preview video yet - run the sync first.")
    tmp = work / (FILE + ".part")
    try:
        media.run([media.ffmpeg(), "-v", "error", "-y", "-i", str(proxy), "-vf", filter_branch("", ""),
                   "-f", "rawvideo", str(tmp)], cancel=cancel, timeout=1800)
        config.replace_with_retry(tmp, out)
    finally:
        tmp.unlink(missing_ok=True)
    return out


def _frames(path: Path) -> np.ndarray:
    n = path.stat().st_size // FRAME
    return np.memmap(path, np.uint8, "r", shape=(n, H, W, 3))


def _features(fr: np.ndarray) -> np.ndarray:
    """Grey level plus red/green share per pixel, normalised per frame (so overall brightness doesn't matter)."""
    f = fr.astype(np.float32)
    grey = f.mean(axis=3)
    chroma = f / (f.sum(axis=3, keepdims=True) + 1)
    x = np.concatenate([grey.reshape(len(f), -1), (chroma[..., :2] * 255).reshape(len(f), -1)], axis=1)
    x -= x.mean(axis=1, keepdims=True)
    x /= x.std(axis=1, keepdims=True) + 1e-6
    return x


def scores(path: Path, ref_t: float) -> np.ndarray:
    """Similarity (-1..1) of every frame to the frame at ref_t, computed in chunks."""
    fr = _frames(path)
    if not len(fr):
        return np.zeros(0, np.float32)
    ref = _features(fr[min(len(fr) - 1, max(0, int(round(ref_t * FPS)))):][:1])[0]
    out = np.empty(len(fr), np.float32)
    for a in range(0, len(fr), CHUNK):
        out[a:a + CHUNK] = _features(fr[a:a + CHUNK]) @ ref / len(ref)
    return out


def moments(sc: np.ndarray, start_t: float = 0.0) -> list[list[float]]:
    """[[from, to], ...] seconds where the score stays above THRESHOLD for at least MIN_FRAMES frames."""
    on = sc > THRESHOLD
    out, i, n = [], 0, len(sc)
    while i < n:
        if on[i]:
            j = i
            while j < n and on[j]:
                j += 1
            if j - i >= MIN_FRAMES and i / FPS >= start_t:
                out.append([round(i / FPS, 2), round((j - 1) / FPS, 2)])
            i = j
        else:
            i += 1
    return out


def before(sc: np.ndarray, t: float) -> float:
    """0..1: how clearly you were at the crease in the few seconds before t."""
    a, b = int((t - BEFORE[0]) * FPS), int((t - BEFORE[1]) * FPS)
    a, b = max(0, a), min(len(sc), b)
    if b <= a:
        return 0.0
    return float(np.clip((sc[a:b].max() - 0.5) / 0.4, 0, 1))


def reference_time(match: dict) -> float | None:
    """The chosen reference, else 1.5 s before the tagged first shot, else none (stance not used)."""
    ref = match.get("stance_ref") or {}
    if ref.get("off"):
        return None
    if ref.get("t") is not None:
        return float(ref["t"])
    first = (match.get("sync_anchors") or {}).get("first")
    return max(0.0, float(first) - REF_LEAD) if first is not None else None


def annotate(cands: list[dict], sc: np.ndarray) -> list[dict]:
    """Copies of the candidates with a 'stance' value for the alignment."""
    return [{**c, "stance": round(before(sc, c["t"]), 3)} for c in cands]
