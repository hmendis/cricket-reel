"""Paths, settings and secrets.

Development (start.bat): everything lives next to start.bat — config/, matches/, .env.
Desktop app (packaged): settings, scoring rules and the API key live in %APPDATA%\\CricketReel; matches
default to Videos\\Cricket Reels (changeable in Settings). Nothing is stored in the install folder, so
updating the app never wipes anything.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
FROZEN = bool(getattr(sys, "frozen", False))
DESKTOP = FROZEN or os.environ.get("CRICKET_REEL_DESKTOP") == "1"
RES = Path(getattr(sys, "_MEIPASS", ROOT))      # read-only bundled resources (static/, default config, ffmpeg)
STATIC_DIR = RES / "static"

if DESKTOP:
    _appdata = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    _default_config = _appdata / "CricketReel"
    _default_matches = Path.home() / "Videos" / "Cricket Reels"
else:
    _default_config = ROOT / "config"
    _default_matches = ROOT / "matches"
CONFIG_DIR = Path(os.environ.get("CRICKET_REEL_CONFIG", _default_config))
TOKENS_FILE = CONFIG_DIR / "tokens.json"
SETTINGS_FILE = CONFIG_DIR / "settings.json"
KEY_FILE = CONFIG_DIR / "api_key.bin"

MODELS = {
    "claude-opus-5-5": "Claude Opus 5.5 (default, most accurate)",
    "claude-sonnet-5-5": "Claude Sonnet 5.5 (cheaper)",
}
DESCRIBE_PROMPTS = {
    # 2.1: the description prompt in parts, editable in Settings. Follows the indoor-cricket-socials skill: no hashtags,
    # no call to action, "indoor cricket" in the first 125 characters. Best practice per platform (2026 guides): the
    # platforms read the first words most, so every text opens with the searchable phrase.
    "shared": (
        "You write social media descriptions for indoor cricket highlight videos. They are POV videos from a head camera worn by the player.\n\n"
        "Context: the player plays eight-a-side indoor cricket at {venue} in Melbourne. Each video is one kind of highlight: batting, bowling, "
        "fielding, bowling and fielding, or all-round (bat and ball). The facts say which.\n\n"
        "Audience: Instagram and TikTok drive discovery. Facebook has a loyal male 35-44 community. The player has a large audience in South "
        "Africa, India and the UK, so use local terms (top net, back net, 7-pointer) only when a global cricket fan can still follow the line.\n\n"
        "Search: people find these by searching, and the platforms read the first words most. Open every caption, title and description with "
        "the searchable phrase: \"indoor cricket\", the highlight type and \"POV\", written naturally, e.g. \"Indoor cricket bowling POV at "
        "{venue}\". All of it must be in the first 125 characters. Name the venue as {venue} and say eight-a-side at least once per file, where "
        "it reads naturally. Use the words people search for (wicket, caught, bowled, run out, stumped, six, four), never stuff keywords, and "
        "use the sheet's terms for dismissals.\n\n"
        "Style: the player's own voice, first person, plain words, short sentences. Say what happened with the real numbers (the score, the "
        "figures, the over and ball) instead of hype words. Match the moment the video opens on.\n\n"
        "Rules: no hashtags anywhere. No call to action (no questions or prompts to comment, follow or share). Emojis are optional and sparing, "
        "and never in the YouTube title. Never invent scores, dismissals, player names or outcomes: use only the facts and the player's own "
        "words. Write each platform fresh, not a trimmed copy of another."),
    "meta": ("Meta (Instagram + Facebook Reels): one shared caption, 25-35 words. The first line must work on its own before \"more\": the "
             "searchable phrase and the best moment. Then one line of context: the score or figures, the result, the venue. Confident and "
             "story-led, readable by an older Facebook audience and younger Instagram viewers."),
    "tiktok": ("TikTok: 10-20 words. Casual, punchy, conversational, a bit of banter. The searchable phrase goes in the first few words, "
               "because TikTok search weighs early words more. One idea only."),
    "yt_title": ("YouTube Shorts title: at most 50 characters so phones show it whole. Headline style in Title Case, no emojis, no clickbait. "
                 "Start with \"Indoor Cricket\", then the highlight type, then the moment, e.g. \"Indoor Cricket Bowling POV: Bowled in Over "
                 "12\". It must match what happens in the first seconds. Check the length before answering."),
    "yt_desc": ("YouTube Shorts description: 20-30 words. The first sentence repeats the searchable phrase and adds what the title left "
                "out: eight-a-side, {venue}, the score or result."),
    "user": "Facts (use only these):\n{facts}\n\nWhat the player wants to say about this video:\n{prompt}",
}
OLD_QUICK_LINKS = {"https://business.facebook.com/latest/home", "https://studio.youtube.com"}  # 2.0 defaults, replaced in 2.1

DEFAULT_SETTINGS = {
    "batter_name": "",
    "other_names": [],
    "venue": "",   # 2.1: named in the descriptions
    "describe_prompts": {},                  # 2.1: your changes to DESCRIBE_PROMPTS (empty = the defaults)
    # 2.1: shown next to the Spawtz link on New match, to find the fixture quickly
    "standings_url": "",   # 2.1: other ways score sheets write my name ("A Carter", "Al C"); tried after batter_name
    "model": "claude-opus-5-5",
    "clip_before": 1.0,
    "clip_after": 2.0,
    "encoder": "auto",   # auto = Intel Quick Sync when it works, else libx264; "x264" = always software
    "matches_dir": "",   # "" = the default folder
    "auto_drop": {"dot": True, "ls": True, "nb": False},  # K2: these start as "not kept" in Review
    # U2: the camera and lens mode, asked once on Import and remembered (the lens isn't in the file)
    "camera": "Insta360 GO Ultra",
    "lens": "action",
    # E4: shown after the descriptions; editable in Settings
    "quick_links": [
        {"name": "Facebook / Meta", "url": "https://business.facebook.com/latest/reels_composer/?asset_id=532570773268055&business_id=851631076917091&ir_qe_exposed=1&ref=biz_web_content_manager_published_posts&context_ref=POSTS"},
        {"name": "YouTube", "url": "https://studio.youtube.com/channel/UCUCFraVV_vDKIW3LdBTTDRw/videos/short?filter=%5B%5D&sort=%7B%22columnType%22%3A%22date%22%2C%22sortOrder%22%3A%22DESCENDING%22%7D"},
        {"name": "TikTok", "url": "https://www.tiktok.com/tiktokstudio/upload"},
    ],
}

if not FROZEN:
    load_dotenv(ROOT / ".env")

# Bundled FFmpeg (desktop app) goes first on PATH so every subprocess finds it.
_ff = RES / "ffmpeg"
if (_ff / "ffmpeg.exe").exists():
    os.environ["PATH"] = str(_ff) + os.pathsep + os.environ.get("PATH", "")


def ensure_user_files() -> None:
    """First run of the desktop app: create the settings folder and copy the default scoring rules."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    src = RES / "config" / "tokens.json"
    if not src.exists() or src.resolve() == TOKENS_FILE.resolve():
        return
    if not TOKENS_FILE.exists():
        shutil.copyfile(src, TOKENS_FILE)
        return
    # 2.1: add wicket codes that are new in this version (e.g. 'st') to an existing copy. Never change the user's values.
    try:
        mine, bundled = read_json(TOKENS_FILE, {}) or {}, read_json(src, {}) or {}
    except ValueError:
        return
    new = {k: v for k, v in (bundled.get("dismissals") or {}).items() if k not in (mine.get("dismissals") or {})}
    if new and isinstance(mine.get("dismissals"), dict):
        mine["dismissals"].update(new)
        write_json_atomic(TOKENS_FILE, mine)


def write_json_atomic(path: Path, data, *, backup: bool = False, indent: int | None = 2) -> None:
    """Write JSON so a crash or power cut never leaves a half-written file.

    A unique temp file in the same folder (two writers never share one), flushed to disk, then renamed over the
    target. With backup=True the previous version is kept as <name>.bak first. On Windows the rename can fail
    briefly while another process has the file open, so it is retried for about a second.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=indent, ensure_ascii=False, separators=None if indent else (",", ":"))
            f.flush()
            os.fsync(f.fileno())
        if backup and path.exists():
            shutil.copyfile(path, path.with_name(path.name + ".bak"))
        replace_with_retry(Path(tmp), path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def replace_with_retry(src: Path, dst: Path, tries: int = 20, wait: float = 0.05) -> None:
    """os.replace, retried briefly: on Windows it fails while another program has the target open."""
    for i in range(tries):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if i == tries - 1:
                raise
            time.sleep(wait)


def read_json(path: Path, default=None):
    """Read a JSON file. A missing file gives `default`; a damaged one raises ValueError."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def load_settings() -> dict:
    s = dict(DEFAULT_SETTINGS)
    s.update(read_json(SETTINGS_FILE, {}) or {})
    # 2.1: the old default upload links become the new ones (links you changed yourself are kept)
    defaults = {x["name"]: x["url"] for x in DEFAULT_SETTINGS["quick_links"]}
    s["quick_links"] = [{**x, "url": defaults[x["name"]]} if x.get("url") in OLD_QUICK_LINKS and x.get("name") in defaults else x
                        for x in s.get("quick_links") or []]
    if s.get("model") not in MODELS:
        s["model"] = DEFAULT_SETTINGS["model"]
    return s


def _matches_dir(s: dict) -> Path:
    env = os.environ.get("CRICKET_REEL_MATCHES")
    if env:
        return Path(env)
    return Path(s["matches_dir"]).expanduser() if s.get("matches_dir") else _default_matches


CAMERAS = ("Insta360 GO Ultra", "Insta360 GO 3S", "Insta360 X5", "Other")
LENSES = {"action": "Action", "mega": "MegaView", "linear": "Linear", "other": "Other"}


def save_settings(changes: dict) -> dict:
    global MATCHES_DIR
    s = load_settings()
    for k, v in changes.items():
        if k in DEFAULT_SETTINGS:
            s[k] = v
    if s["model"] not in MODELS:
        raise ValueError(f"Unknown model {s['model']!r}")
    names = s.get("other_names") or []
    if not isinstance(names, list) or len(names) > 2:
        raise ValueError("Up to two other names.")
    s["other_names"] = [str(n).strip()[:60] for n in names if str(n).strip()]
    dp = s.get("describe_prompts") or {}
    if not isinstance(dp, dict) or any(k not in DESCRIBE_PROMPTS or not isinstance(v, str) or len(v) > 6000 for k, v in dp.items()):
        raise ValueError("Unknown description prompt part, or one is too long.")
    s["describe_prompts"] = {k: v for k, v in dp.items() if v.strip() and v != DESCRIBE_PROMPTS[k]}
    s["venue"] = str(s.get("venue") or "").strip()[:80] or DEFAULT_SETTINGS["venue"]
    su = str(s.get("standings_url") or "").strip()
    if su and not su.startswith("https://"):
        raise ValueError("The standings link must start with https://")
    s["standings_url"] = su[:500]
    if s["encoder"] not in ("auto", "x264"):
        raise ValueError("Encoder must be 'auto' or 'x264'")
    if s.get("lens") not in LENSES:
        raise ValueError("Lens mode must be one of: " + ", ".join(LENSES))
    s["camera"] = str(s.get("camera") or "").strip()[:60] or DEFAULT_SETTINGS["camera"]
    links = s.get("quick_links") or []
    if not isinstance(links, list) or len(links) > 12 or not all(
            isinstance(x, dict) and str(x.get("name", "")).strip() and str(x.get("url", "")).startswith("https://") for x in links):
        raise ValueError("Each quick link needs a name and an https:// address (12 at most).")
    s["quick_links"] = [{"name": str(x["name"]).strip()[:40], "url": str(x["url"]).strip()[:500]} for x in links]
    if "matches_dir" in changes:
        p = _matches_dir(s)
        try:
            p.mkdir(parents=True, exist_ok=True)
            probe = p / ".write-test"
            probe.write_text("ok")
            probe.unlink()
        except OSError as e:
            raise ValueError(f"Can't use that folder for matches: {e}") from e
    write_json_atomic(SETTINGS_FILE, s)
    if "matches_dir" in changes:
        MATCHES_DIR = _matches_dir(s)
    return s


MATCHES_DIR = _matches_dir(load_settings())


# ---------- API key ----------
# Stored with Windows DPAPI (encrypted for this Windows user only). .env / environment still wins in development.
def _dpapi(data: bytes, protect: bool) -> bytes:
    import ctypes
    from ctypes import wintypes

    class BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    buf = ctypes.create_string_buffer(data, len(data))
    inp, out = BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), BLOB()
    crypt = ctypes.windll.crypt32
    fn = crypt.CryptProtectData if protect else crypt.CryptUnprotectData
    if not fn(ctypes.byref(inp), None, None, None, None, 0, ctypes.byref(out)):
        raise OSError("Windows couldn't encrypt/decrypt the API key")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(out.pbData)


def api_key_source() -> str | None:
    if os.environ.get("ANTHROPIC_API_KEY", "").strip():
        return "env"
    return "settings" if KEY_FILE.exists() else None


def api_key() -> str | None:
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if key:
        return key
    if KEY_FILE.exists():
        try:
            data = KEY_FILE.read_bytes()
            return (_dpapi(data, False) if os.name == "nt" else data).decode("utf-8").strip() or None
        except OSError:
            return None
    return None


def set_api_key(key: str) -> None:
    key = key.strip()
    if not key:
        raise ValueError("Paste the key first.")
    if not key.startswith("sk-ant-"):
        raise ValueError("That doesn't look like a Claude API key (they start with sk-ant-).")
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    data = key.encode("utf-8")
    KEY_FILE.write_bytes(_dpapi(data, True) if os.name == "nt" else data)


def clear_api_key() -> None:
    KEY_FILE.unlink(missing_ok=True)


def ffprobe_path() -> str | None:
    return shutil.which("ffprobe")
