import pytest

from app.scorecard import Scorecard, parse_code, validate
from app.sheet_reader import response_schema
from conftest import sample_sheet


@pytest.mark.parametrize("code,kind,team,bat,ball", [
    ("0", "runs", 0, 0, True),
    ("3", "runs", 3, 3, True),
    ("4", "big", 4, 4, True),
    ("7", "big", 7, 7, True),
    ("c", "wicket", -5, -5, True),
    ("r", "wicket", -5, -5, True),
    ("LS", "extra", 2, 2, True),
    ("w", "extra", 2, 2, True),
    ("nb", "extra", 2, 2, True),
    ("nb²", "extra", 4, 4, True),
    ("nb1", "extra", 3, 3, True),
    ("8", "invalid", 0, 0, False),
    ("x", "invalid", 0, 0, False),
    ("", "invalid", 0, 0, False),
])
def test_parse_code(code, kind, team, bat, ball):
    p = parse_code(code)
    assert (p["kind"], p["team"], p["bat"], p["ball"]) == (kind, team, bat, ball)


def test_misread_is_flagged():
    v = validate(sample_sheet())
    assert not v["ok"]
    assert [o["ok"] for o in v["overs"]] == [True, True, False, True]
    assert v["overs"][2]["calc"] == 11 and v["overs"][2]["sheet"] == 13
    assert v["batter"]["ok"] and (v["batter"]["calc_runs"], v["batter"]["calc_balls"]) == (30, 14)
    assert not v["partner"]["ok"] and v["partner"]["calc_runs"] == 10
    assert v["unsure"] == 1


def test_fixed_sheet_adds_up():
    v = validate(sample_sheet(fix_misread=True))
    assert v["ok"], v["errors"]
    assert v["partner"]["calc_runs"] == 12


def test_unknown_code_reported_per_cell():
    s = sample_sheet(fix_misread=True)
    s["overs"][0]["balls"][0]["code"] = "z"
    v = validate(s)
    assert not v["ok"]
    assert v["cells"] == [{"over": 0, "ball": 0, "error": "'z' isn't a known code"}]


def test_missing_sheet_totals_are_not_errors():
    s = sample_sheet(fix_misread=True)
    for o in s["overs"]:
        o["total_sheet"] = None
    s["batter"]["runs_sheet"] = None
    v = validate(s)
    assert v["ok"]
    assert any("No over total" in w for w in v["warnings"])


def test_scorecard_roundtrip():
    sc = Scorecard.model_validate(sample_sheet())
    assert sc.overs[2].balls[2].code == "nb²"


def test_schema_is_strict():
    def walk(n):
        if isinstance(n, dict):
            if "properties" in n:
                assert n["additionalProperties"] is False
                assert set(n["required"]) == set(n["properties"])
            for v in n.values():
                walk(v)
        elif isinstance(n, list):
            for v in n:
                walk(v)
    walk(response_schema())
