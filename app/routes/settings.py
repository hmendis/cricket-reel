"""Status, settings, the API key and scoring codes."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import __version__, config, usage
from ..scorecard import load_tokens

router = APIRouter()


@router.get("/api/status")
def status():
    s = config.load_settings()
    return {"api_key": config.api_key() is not None, "api_key_source": config.api_key_source(),
            "ffprobe": config.ffprobe_path() is not None, "desktop": config.DESKTOP, "version": __version__,
            "model": s["model"], "models": config.MODELS, "settings": s, "describe_defaults": config.DESCRIBE_PROMPTS, "cameras": config.CAMERAS, "lenses": config.LENSES,
            "estimates": {
                "sheet": usage.estimate("sheet", s["model"]), "describe": usage.estimate("describe", s["model"])},
            "matches_dir": str(config.MATCHES_DIR), "config_dir": str(config.CONFIG_DIR), "tokens_file": str(config.TOKENS_FILE)}


class KeyIn(BaseModel):
    key: str


@router.put("/api/settings/api-key")
def put_api_key(body: KeyIn):
    try:
        config.set_api_key(body.key)
    except (ValueError, OSError) as e:
        raise HTTPException(400, str(e)) from e
    return {"api_key": True, "api_key_source": config.api_key_source()}


@router.delete("/api/settings/api-key")
def delete_api_key():
    config.clear_api_key()
    return {"api_key": config.api_key() is not None, "api_key_source": config.api_key_source()}


class SettingsIn(BaseModel):
    batter_name: str | None = None
    other_names: list[str] | None = None
    standings_url: str | None = None
    venue: str | None = None
    describe_prompts: dict[str, str] | None = None
    model: str | None = None
    encoder: str | None = None
    matches_dir: str | None = None
    clip_before: float | None = None
    clip_after: float | None = None
    auto_drop: dict[str, bool] | None = None
    quick_links: list[dict] | None = None
    camera: str | None = None
    lens: str | None = None


@router.put("/api/settings")
def put_settings(body: SettingsIn):
    try:
        return config.save_settings({k: v for k, v in body.model_dump().items() if v is not None})
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.get("/api/tokens")
def tokens():
    return load_tokens()


@router.post("/api/test-key")
def test_key():
    """Cheap check that the key works (lists models; no tokens used)."""
    import anthropic
    key = config.api_key()
    if not key:
        raise HTTPException(400, "No API key yet. Paste your key in Settings first.")
    try:
        anthropic.Anthropic(api_key=key).models.retrieve(config.load_settings()["model"])
    except anthropic.AuthenticationError as e:
        raise HTTPException(400, "The API key was rejected.") from e
    except anthropic.APIConnectionError as e:
        raise HTTPException(400, "Couldn't reach the Claude API. Check the internet connection.") from e
    except anthropic.APIStatusError as e:
        raise HTTPException(400, f"Claude API error ({e.status_code}).") from e
    return {"ok": True}
