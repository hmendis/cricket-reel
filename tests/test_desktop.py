import os

import pytest
from fastapi.testclient import TestClient

from app import config, main


@pytest.fixture
def keyfile(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "KEY_FILE", tmp_path / "api_key.bin")
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    return tmp_path / "api_key.bin"


def test_api_key_saved_encrypted(keyfile):
    assert config.api_key() is None and config.api_key_source() is None
    config.set_api_key("  sk-ant-test-123  ")
    assert config.api_key() == "sk-ant-test-123" and config.api_key_source() == "settings"
    if os.name == "nt":
        assert b"sk-ant" not in keyfile.read_bytes()  # DPAPI-encrypted on disk
    config.clear_api_key()
    assert config.api_key() is None


def test_env_key_wins(keyfile, monkeypatch):
    config.set_api_key("sk-ant-stored")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-env")
    assert config.api_key() == "sk-ant-env" and config.api_key_source() == "env"


def test_bad_key_rejected(keyfile):
    with pytest.raises(ValueError):
        config.set_api_key("hello")
    with pytest.raises(ValueError):
        config.set_api_key(" ")


def test_key_endpoints(tmp_data, keyfile):
    c = TestClient(main.app)
    assert c.put("/api/settings/api-key", json={"key": "nope"}).status_code == 400
    r = c.put("/api/settings/api-key", json={"key": "sk-ant-abc"}).json()
    assert r["api_key"] and r["api_key_source"] == "settings"
    s = c.get("/api/status").json()
    assert s["api_key"] and "desktop" in s and s["config_dir"]
    assert c.delete("/api/settings/api-key").json()["api_key"] is False


def test_matches_dir_setting(tmp_data, monkeypatch):
    monkeypatch.delenv("CRICKET_REEL_MATCHES", raising=False)
    c = TestClient(main.app)
    new = tmp_data / "elsewhere" / "Cricket Reels"
    s = c.put("/api/settings", json={"matches_dir": str(new)}).json()
    assert s["matches_dir"] == str(new) and new.is_dir()
    assert config.MATCHES_DIR == new
    m = c.post("/api/matches", json={"batter": "Alex"}).json()
    assert (new / m["id"] / "match.json").exists()
    bad = c.put("/api/settings", json={"matches_dir": "Z:\\no\\such\\drive\\here"})
    assert bad.status_code == 400


def test_desktop_paths_when_frozen(monkeypatch, tmp_path):
    """In desktop mode settings go to %APPDATA%\\CricketReel and matches to Videos\\Cricket Reels."""
    import importlib
    monkeypatch.setenv("CRICKET_REEL_DESKTOP", "1")
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    monkeypatch.delenv("CRICKET_REEL_CONFIG", raising=False)
    monkeypatch.delenv("CRICKET_REEL_MATCHES", raising=False)
    cfg = importlib.reload(config)
    try:
        assert cfg.CONFIG_DIR == tmp_path / "Roaming" / "CricketReel"
        assert cfg.MATCHES_DIR.parts[-2:] == ("Videos", "Cricket Reels")
        cfg.ensure_user_files()
        assert (cfg.CONFIG_DIR / "tokens.json").exists()
    finally:
        monkeypatch.delenv("CRICKET_REEL_DESKTOP")
        importlib.reload(config)


def test_startup_check_reaches_the_server_with_the_token_on(monkeypatch):
    """The window waits for the server by loading the page: /api/ answers 403 until the page has set the
    token cookie, so polling the API would leave the window on the splash."""
    import inspect

    from fastapi.testclient import TestClient

    from app import desktop, main
    monkeypatch.setattr(main, "APP_TOKEN", "launch-token")
    c = TestClient(main.app)
    assert c.get("/api/status", cookies={}).status_code == 403
    r = c.get("/")
    assert r.status_code == 200 and main.TOKEN_COOKIE in r.headers.get("set-cookie", "")  # the page hands the token over
    src = inspect.getsource(desktop.main)
    assert 'urlopen(url, timeout=1)' in src and 'url + "api/' not in src
    assert "#07080B" in desktop.SPLASH and "__VERSION__" in desktop.SPLASH and "<svg" not in desktop.SPLASH
