"""Phase 12 (E2, E3, E4): descriptions per exported file, Claude cost per step and session, quick links.
No real API calls: a stand-in client returns fixed answers."""
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import config, describe, main, matches, usage
from conftest import wait_for_job
from test_review import synced_match

GOOD = {"meta": "Indoor cricket batting POV: a tight run-out in our last over, and the team still won by 27 runs.",
        "tiktok": "Indoor cricket POV. Went for the tight second. The throw had other ideas.",
        "youtube_title": "Indoor Cricket POV: Run Out Going for Two",
        "youtube_description": "Indoor cricket batting POV. Going for a tight second in our last over, the throw beats me. Still a 27-run win."}


class FakeClient:
    def __init__(self, answer=GOOD, stop="end_turn", model="claude-opus-5-5"):
        self.calls = []
        self.answer, self.stop, self.model = answer, stop, model
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kw):
        self.calls.append(kw)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=json.dumps(self.answer))], stop_reason=self.stop,
                               model=self.model, usage=SimpleNamespace(input_tokens=1500, output_tokens=600,
                                                                       cache_read_input_tokens=0, cache_creation_input_tokens=0))


def test_costs_use_the_model_prices():
    assert usage.cost("claude-opus-5-5", {"input_tokens": 1_000_000})["usd"] == 4.0
    assert usage.cost("claude-opus-5-5", {"output_tokens": 1_000_000})["usd"] == 20.0
    assert usage.cost("claude-sonnet-5-5", {"input_tokens": 1_000_000, "output_tokens": 1_000_000})["usd"] == 12.0
    assert usage.cost("claude-opus-5-5", {"cache_read_input_tokens": 1_000_000, "cache_creation_input_tokens": 1_000_000})["usd"] == 0.2 + 5.0
    assert 0.005 < usage.estimate("describe", "claude-opus-5-5") < 0.05


def test_write_one_follows_the_skill_and_sends_only_facts():
    c = FakeClient()
    d, served, used = describe.write_one("Run out going for two", ["Night Owls 93 v Lions 66"], "claude-opus-5-5", "k", c)
    assert d == GOOD and served == "claude-opus-5-5" and used.output_tokens == 600
    req = c.calls[0]
    assert "no hashtags" in req["system"].lower() and "Never invent" in req["system"]
    assert "Night Owls 93" in req["messages"][0]["content"] and "Run out going for two" in req["messages"][0]["content"]
    assert req["output_config"]["format"]["type"] == "json_schema" and req["extra_body"] == {"fallbacks": "default"}
    with pytest.raises(describe.DescribeError):
        describe.write_one("x", [], "claude-opus-5-5", "k", FakeClient(stop="refusal"))


def test_rule_checks():
    assert describe.checks(GOOD) == {"keyword": True, "no_hashtags": True, "no_call_to_action": True, "title_length": True,
                                     "lengths": {"meta": 19, "tiktok": 13, "youtube_title": 41, "youtube_description": 21}}
    bad = dict(GOOD, tiktok="Great knock! Follow for more #cricket", youtube_title="X" * 60)
    c = describe.checks(bad)
    assert not c["no_hashtags"] and not c["no_call_to_action"] and not c["title_length"] and not c["keyword"]


def _exported_match(c, tmp_data):
    mid, _ = synced_match(c)
    c.get(f"/api/matches/{mid}/review")
    c.get(f"/api/matches/{mid}/arrange")
    d = matches.match_dir(mid)
    clip = matches.load(mid)["clips"][0]
    from app import export
    names = [export.reel_name(matches.load(mid), config.read_json(d / "scorecard.json")), export.clip_name(clip)]
    (d / "exports").mkdir()
    for n in names:
        (d / "exports" / n).write_bytes(b"video")
    with matches.edit(mid) as m:
        m["exports"] = [{"at": "2026-11-12T10:00:00", "files": names}]
        m["step"] = "exported"
    return mid, names, clip


def test_describe_job_saves_texts_file_and_cost(tmp_data, monkeypatch):
    monkeypatch.setattr(config, "api_key", lambda: "test-key")
    fake = FakeClient()
    real = describe.write_one
    monkeypatch.setattr(describe, "write_one", lambda p, f, model, key, client=None: real(p, f, model, key, fake))
    c = TestClient(main.app)
    mid, names, clip = _exported_match(c, tmp_data)
    ov = c.get(f"/api/matches/{mid}/describe").json()
    assert [f["name"] for f in ov["files"]] == names and ov["files"][1]["index"] == clip["index"]
    assert any("batted" in x for x in ov["files"][0]["facts"]) and ov["estimate_each"] > 0
    assert any("eight-a-side" in x for x in ov["files"][0]["facts"]) and ov["files"][0]["draft"]
    body = {"files": [{"name": names[0], "kind": "reel", "prompt": "Big night of twos"},
                      {"name": names[1], "kind": "clip", "index": clip["index"], "prompt": "First ball"}]}
    j = wait_for_job(c, c.post(f"/api/matches/{mid}/describe", json=body).json()["id"])
    assert j["status"] == "done", j
    assert "This clip: our innings, over" in fake.calls[1]["messages"][0]["content"]  # each file gets its own facts and prompt
    m = matches.load(mid)
    assert m["step"] == "described" and set(m["descriptions"]) == set(names)
    txt = (matches.match_dir(mid) / "exports" / j["result"]["name"]).read_text(encoding="utf-8")
    assert txt.count("=== ") == 2 and "YouTube Shorts title" in txt and GOOD["tiktok"] in txt and "Big night of twos" in txt
    u = c.get("/api/usage", params={"match_id": mid}).json()
    step = next(s for s in u["match"]["steps"] if s["step"] == "describe")
    assert step["calls"] == 2 and step["usd"] == pytest.approx(2 * (1500 * 4 + 600 * 20) / 1e6)
    assert u["session"]["calls"] >= 2
    assert c.get(f"/api/matches/{mid}/describe").json()["files"][0]["saved"]["text"] == GOOD


def test_describe_needs_a_key_and_an_export(tmp_data, monkeypatch):
    c = TestClient(main.app)
    mid, names, _ = _exported_match(c, tmp_data)
    monkeypatch.setattr(config, "api_key", lambda: None)
    assert c.post(f"/api/matches/{mid}/describe", json={"files": [{"name": names[0]}]}).status_code == 400
    monkeypatch.setattr(config, "api_key", lambda: "k")
    assert c.post(f"/api/matches/{mid}/describe", json={"files": [{"name": "missing.mp4"}]}).status_code == 400


def test_quick_links_in_settings(tmp_data):
    c = TestClient(main.app)
    links = c.get("/api/status").json()["settings"]["quick_links"]
    assert [x["name"] for x in links] == ["Facebook / Meta", "YouTube", "TikTok"] and all(x["url"].startswith("https://") for x in links)
    new = links + [{"name": "Strava", "url": "https://www.strava.com"}]
    assert c.put("/api/settings", json={"quick_links": new}).json()["quick_links"][-1]["name"] == "Strava"
    assert c.put("/api/settings", json={"quick_links": [{"name": "x", "url": "javascript:alert(1)"}]}).status_code == 400
    assert c.put("/api/settings", json={"quick_links": [{"name": "", "url": "https://a.b"}]}).status_code == 400
