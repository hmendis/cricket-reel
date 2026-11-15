"""Reads a score sheet photo with Claude (vision) and returns structured JSON.

Only the sheet image is sent. The response is constrained to the SheetRead JSON schema via
structured outputs, then validated again locally with Pydantic.
"""
from __future__ import annotations

import base64
import io
import json
from pathlib import Path
from typing import TYPE_CHECKING

from .scorecard import SheetRead

if TYPE_CHECKING:  # imported where used: `anthropic` alone takes ~5 s to import, and only sheet reading needs it
    import anthropic
    from PIL import Image

MAX_EDGE = 2400  # long edge in px sent to the API; keeps handwriting legible and the upload small


class SheetReadError(Exception):
    """Raised with a user-facing message and a short machine code for the UI."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


# ---------- Image preparation ----------
def load_sheet_image(path: Path) -> Image.Image:
    from PIL import Image, ImageOps
    if path.suffix.lower() == ".pdf":
        import pypdfium2 as pdfium

        pdf = pdfium.PdfDocument(str(path))
        if len(pdf) == 0:
            raise SheetReadError("unreadable", "The PDF has no pages.")
        img = pdf[0].render(scale=2.5).to_pil()
        pdf.close()
    else:
        try:
            img = Image.open(path)
            img.load()
        except Exception as e:  # noqa: BLE001 - Pillow raises many types
            raise SheetReadError("unreadable", f"Couldn't open the image ({e}).") from e
        img = ImageOps.exif_transpose(img)  # phone photos are often stored rotated
    return img.convert("RGB")


def prepare_image(path: Path, display_copy: Path | None = None) -> bytes:
    """Return JPEG bytes ready for the API; optionally save the same image for the UI."""
    from PIL import Image
    img = load_sheet_image(path)
    img.thumbnail((MAX_EDGE, MAX_EDGE), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=90)
    data = buf.getvalue()
    if display_copy:
        display_copy.write_bytes(data)
    return data


# ---------- Prompt ----------
SYSTEM = """You read indoor cricket score sheets from photos and transcribe them exactly.

Sheet layout:
- Each over is a block of ball columns. Each ball is written in the row of the batter who faced it.
  A blank cell in one batter's row means their partner faced that ball (it is written in the partner's row).
- Batters bat in pairs; a pair bats several consecutive overs.
- Deliveries are read left to right in the order bowled. An over usually has 6 deliveries (extras are
  not re-bowled), but a sheet may have a spare extra-ball column that is sometimes used.

Rules:
- Transcribe codes exactly as written. Keep superscripts as superscript characters (², ³) or plain
  digits directly after the letters (nb2) - never drop them.
- Never invent or "fix" a value to make totals add up. If a cell is ambiguous, give your best reading,
  set unsure=true and say what else it could be in note.
- Use null for any total that is not written on the sheet.
- In `overs`, report only the overs batted by the named batter's pair. `innings` holds both innings in full."""


def build_prompt(batter_name: str, tokens: dict, aliases: list[str] | None = None) -> str:
    dismissals = ", ".join(f"{k} = {v}" for k, v in tokens.get("dismissals", {}).items())
    extras = ", ".join(f"{k} = {v.get('label', k)}" for k, v in tokens.get("extras", {}).items())
    r = tokens.get("runs", {"min": 0, "max": 7})
    return (
        f"The batter I care about is named \"{batter_name}\" on this sheet (match the closest spelling)"
        + (f"; it may also be written as {', '.join(repr(a) for a in aliases)}" if aliases else "") + ".\n"
        f"Find the overs that {batter_name}'s pair batted. For each over give the over number, the bowler, "
        f"the over total written on the sheet, and every delivery in order with who faced it: "
        f"'me' for {batter_name}, 'partner' for the other batter in the pair.\n\n"
        f"Scorer's codes: runs {r['min']}-{r['max']}; dismissals: {dismissals} "
        f"(a wicket is scored {tokens.get('wicket_penalty', -5)} runs); extras: {extras}. "
        f"Extras may carry a superscript or trailing number (e.g. nb²) for extra runs.\n\n"
        f"Also fill in the match details (team names, innings totals, result, player of the match, date) "
        f"and both batters' run and ball totals as written. Put anything I should double-check in notes.\n\n"
        f"Then transcribe both innings in full in `innings`, the one batted first first: every over with its number, "
        f"bowler, footer (written 'wickets/runs', e.g. 2/-3: wkts=2, runs=-3) and every delivery with the name of the "
        f"batter who faced it. side='batting' for {batter_name}'s team, 'fielding' for the other team. If the sheet has "
        f"a bowling or player summary table for {batter_name}'s team (OB, RC, Wkts), copy it into `bowling`. "
        f"Leave `innings` or `bowling` empty if that part isn't on the photo."
    )


# ---------- JSON schema for structured outputs ----------
def _strict(node):
    """Add additionalProperties:false to every object (required by structured outputs)."""
    if isinstance(node, dict):
        if node.get("type") == "object" or "properties" in node:
            node["additionalProperties"] = False
            node["required"] = list(node.get("properties", {}).keys())
        for v in node.values():
            _strict(v)
    elif isinstance(node, list):
        for v in node:
            _strict(v)
    return node


def response_schema() -> dict:
    return _strict(SheetRead.model_json_schema())


# ---------- Claude call ----------
def read_sheet(image_jpeg: bytes, batter_name: str, model: str, tokens: dict, api_key: str,
               client: anthropic.Anthropic | None = None, on_usage=None, aliases: list[str] | None = None) -> SheetRead:
    """on_usage(model that answered, usage) is called for every response, including refusals (they're billed)."""
    import anthropic
    client = client or anthropic.Anthropic(api_key=api_key)
    request = dict(
        model=model,
        max_tokens=20000,  # 2.1: both innings in full (about 5k more tokens); stays under the non-streaming limit
        system=SYSTEM,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                             "data": base64.standard_b64encode(image_jpeg).decode("ascii")}},
                {"type": "text", "text": build_prompt(batter_name, tokens, aliases)},
            ],
        }],
        output_config={"effort": "high", "format": {"type": "json_schema", "schema": response_schema()}},
    )
    # Server-side refusal fallback: if a safety classifier declines, the API retries on another model.
    fallback = dict(extra_headers={"anthropic-beta": "server-side-fallback-2026-07-01"},
                    extra_body={"fallbacks": "default"})
    try:
        try:
            resp = client.messages.create(**request, **fallback)
        except anthropic.BadRequestError as e:
            if "fallback" not in str(e).lower():
                raise
            resp = client.messages.create(**request)  # fallback param not accepted: plain request
    except anthropic.AuthenticationError as e:
        raise SheetReadError("auth", "The Claude API key was rejected. Check the key in Settings.") from e
    except anthropic.PermissionDeniedError as e:
        raise SheetReadError("auth", "This API key isn't allowed to use the selected model.") from e
    except anthropic.RateLimitError as e:
        raise SheetReadError("rate_limit", "The Claude API is rate limiting requests. Wait a minute and try again.") from e
    except anthropic.APIConnectionError as e:
        raise SheetReadError("network", "Couldn't reach the Claude API. Check the internet connection.") from e
    except anthropic.BadRequestError as e:
        raise SheetReadError("api", f"The Claude API rejected the request: {e.message}") from e
    except anthropic.APIStatusError as e:
        raise SheetReadError("api", f"Claude API error ({e.status_code}). Try again shortly.") from e

    if on_usage and getattr(resp, "usage", None) is not None:
        on_usage(getattr(resp, "model", model), resp.usage)
    if resp.stop_reason == "refusal":
        raise SheetReadError("refusal", "Claude declined to read this image. Try a different photo of the sheet.")
    if resp.stop_reason == "max_tokens":
        raise SheetReadError("unreadable", "The response was cut off. Try again, or crop the photo to your pair's overs.")
    text = next((b.text for b in resp.content if b.type == "text"), "")
    try:
        result = SheetRead.model_validate_json(text)
    except Exception as e:  # noqa: BLE001
        raise SheetReadError("unreadable", "Claude's answer didn't match the expected format. Try again.") from e
    if not result.overs:
        raise SheetReadError("unreadable", f"Couldn't find any overs for {batter_name} on this sheet. "
                                           "Check the batter name, or use a clearer photo.")
    return result


def dump(result: SheetRead) -> str:
    return json.dumps(result.model_dump(), indent=2, ensure_ascii=False)
