"""Remove secrets and private paths from text before it is written to a log or shared (R39, G4).

- The Claude API key in use, and anything that looks like an Anthropic key (sk-ant-...), bearer tokens and
  long random-looking strings: replaced by [removed].
- Values of fields named like password, token, secret, api_key, authorization (JSON or key=value): [removed].
- Windows paths outside the app's own folders (the app, its settings folder, the matches folder): [outside path].
  Paths inside them are kept, written relative to that folder, e.g. <matches>\\2026-11-04_...\\match.json.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

REMOVED, OUTSIDE = "[removed]", "[outside path]"
SECRET_KEYS = re.compile(r"(pass(word|wd)?|token|secret|api[_-]?key|authori[sz]ation|cookie|credential)", re.I)
KEY_LIKE = [
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{12,}"),
    # long random-looking strings: 32+ letters and digits with upper case, lower case and a digit, no separators
    re.compile(r"\b(?=[A-Za-z0-9]*\d)(?=[A-Za-z0-9]*[a-z])(?=[A-Za-z0-9]*[A-Z])[A-Za-z0-9]{32,}\b"),
]
PAIR = re.compile(r"(?i)\b([\w\-]*(?:pass(?:word|wd)?|token|secret|api[_-]?key|authori[sz]ation)[\w\-]*)\s*[=:]\s*(\"[^\"]*\"|'[^']*'|[^\s,;&]+)")
# C:\..., C:/..., \\server\share\...: folders may contain spaces, the last part (file name) ends at a space.
WIN_PATH = re.compile(r"(?:(?<![A-Za-z0-9])[A-Za-z]:[\\/](?![\\/])|\\\\[^\\/\s]+[\\/])(?:[^\\/:*?\"<>|\r\n]+[\\/])*[^\\/:*?\"<>|\r\n\s]*")


def _roots() -> list[tuple[str, str]]:
    from . import config
    roots = [("<matches>", config.MATCHES_DIR), ("<settings>", config.CONFIG_DIR), ("<app>", config.ROOT)]
    out = []
    for label, p in roots:
        try:
            out.append((label, str(Path(p).resolve())))
        except OSError:
            pass
    return sorted(out, key=lambda r: -len(r[1]))  # the longest (most specific) root first


def _path(m: re.Match) -> str:
    raw = m.group(0).rstrip(" .,;:)")
    tail = m.group(0)[len(raw):]
    norm = raw.replace("/", "\\").lower()
    for label, root in _roots():
        r = root.replace("/", "\\").lower().rstrip("\\")
        if norm == r or norm.startswith(r + "\\"):
            return label + raw[len(r):] + tail
    return OUTSIDE + tail


def text(s: str, extra_secrets: list[str] | None = None) -> str:
    """Redact one piece of text."""
    if not s:
        return s
    from . import config
    secrets = [x for x in [config.api_key(), os.environ.get("ANTHROPIC_API_KEY", "")] + (extra_secrets or []) if x and len(x) >= 6]
    for sec in secrets:
        s = s.replace(sec, REMOVED)
    for rx in KEY_LIKE:
        s = rx.sub(REMOVED, s)
    s = PAIR.sub(lambda m: f"{m.group(1)}={REMOVED}", s)
    return WIN_PATH.sub(_path, s)


def data(obj):
    """Redact a JSON-like structure: secret-looking keys lose their values, every string is cleaned."""
    if isinstance(obj, dict):
        return {k: (REMOVED if isinstance(k, str) and SECRET_KEYS.search(k) and obj[k] not in (None, "", False) else data(v))
                for k, v in obj.items()}
    if isinstance(obj, list):
        return [data(v) for v in obj]
    if isinstance(obj, str):
        return text(obj)
    return obj


def json_file(path: Path) -> str:
    try:
        return json.dumps(data(json.loads(path.read_text(encoding="utf-8"))), indent=2, ensure_ascii=False)
    except (OSError, ValueError):
        return text(path.read_text(encoding="utf-8", errors="replace"))
