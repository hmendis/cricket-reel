import shutil
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config  # noqa: E402

SAMPLE = {
    "match": {"team_us": "X-RAYTED", "team_them": "Lions", "total_us": 142, "total_them": 118,
              "result": "X-RAYTED won by 24 runs", "player_of_match": "A. Carter", "date": "2026-11-06"},
    # nb² (4) counts toward the batter's row total and as a ball faced, as on Spawtz sheets.
    "batter": {"name": "Alex", "runs_sheet": 30, "balls_sheet": 14},
    "partner": {"name": "Kavin", "runs_sheet": 12, "balls_sheet": 11},
    "overs": [
        {"number": 9, "bowler": "J. Moore", "total_sheet": 9, "balls": [
            ["me", "2"], ["me", "0"], ["partner", "2"], ["partner", "1"], ["me", "4"], ["partner", "0"]]},
        {"number": 10, "bowler": "T. Nguyen", "total_sheet": 7, "balls": [
            ["me", "4"], ["me", "0"], ["partner", "c"], ["partner", "1"], ["me", "5"], ["me", "2"]]},
        {"number": 11, "bowler": "R. Patel", "total_sheet": 13, "balls": [
            ["partner", "0"], ["partner", "3"], ["me", "nb²"], ["me", "1"], ["me", "c"], ["partner", "2"], ["me", "6"]]},
        {"number": 12, "bowler": "S. Clarke", "total_sheet": 13, "balls": [
            ["me", "2"], ["partner", "1"], ["partner", "4"], ["me", "0"], ["partner", "1"], ["me", "5"]]},
    ],
    "notes": "",
}


def sample_sheet(fix_misread: bool = False) -> dict:
    """The design-prototype game as a scorecard. Over 11 ball 2 is misread as 3 (should be 5)."""
    import copy
    s = copy.deepcopy(SAMPLE)
    for o in s["overs"]:
        o["balls"] = [{"facer": f, "code": c, "unsure": False, "note": ""} for f, c in o["balls"]]
    s["overs"][2]["balls"][1].update(unsure=True, note="could be 5")
    if fix_misread:
        s["overs"][2]["balls"][1].update(code="5", unsure=False, note="")
    return s


ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    """Every test gets its own config folder, so local config/*.json overrides or a saved API key never change results."""
    from app import media
    cfg = tmp_path / "config"
    cfg.mkdir()
    shutil.copyfile(ROOT / "config" / "tokens.json", cfg / "tokens.json")
    monkeypatch.setattr(config, "CONFIG_DIR", cfg)
    monkeypatch.setattr(config, "TOKENS_FILE", cfg / "tokens.json")
    monkeypatch.setattr(config, "KEY_FILE", cfg / "api_key.bin")
    monkeypatch.setattr(config, "SETTINGS_FILE", cfg / "settings.json")
    # The API only answers its own host names (R37); TestClient calls itself "testserver".
    from app import main
    monkeypatch.setattr(main, "ALLOWED_HOSTS", main.ALLOWED_HOSTS | {"testserver"})
    monkeypatch.setattr(main, "APP_TOKEN", None)
    # Same encoder on every machine: tests never depend on whether Quick Sync works here.
    monkeypatch.setitem(media._encoder_cache, "h264", "libx264")
    return cfg


@pytest.fixture
def tmp_data(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "MATCHES_DIR", tmp_path / "matches")
    return tmp_path


def wait_for_job(client, job_id: str, timeout: float = 300.0) -> dict:
    """Poll a background job until it stops running. Generous timeout: a busy laptop must not fail the suite."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        j = client.get(f"/api/jobs/{job_id}").json()
        if j["status"] not in ("running", "waiting"):
            return j
        time.sleep(0.1)
    raise AssertionError(f"job {job_id} still running after {timeout:.0f} s")


def make_av(path, dur: float, size: str = "270x480", src: str = "testsrc") -> None:
    """A small test video with a tone, encoded as fast as possible."""
    import subprocess
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"{src}=size={size}:rate=25:duration={dur}",
                    "-f", "lavfi", "-i", f"sine=frequency=500:duration={dur}", "-shortest", "-pix_fmt", "yuv420p",
                    "-c:v", "libx264", "-preset", "ultrafast", str(path)], check=True)


def squeeze_clips(mid, start=3.0, step=1.8):
    """Move every clip inside the first 30 s so the test video can be short."""
    from app import matches
    m = matches.load(mid)
    for k, cl in enumerate(m["clips"]):
        cl["t"] = start + k * step
    matches.save(m)
