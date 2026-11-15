"""2.2 (design v4): what the reworked screens must and mustn't contain."""
from app import config

JS = config.STATIC_DIR / "js"
read = lambda f: (JS / f).read_text(encoding="utf-8")  # noqa: E731


def test_arrange_has_no_header_cards_or_music():
    a = "\n".join(l for l in read("arrange.js").splitlines() if not l.lstrip().startswith("//"))  # code, not comments
    for gone in ("hcard", "header_len", "header_text", "A.hdr", "cardsIn", "music", "Set the look"):
        assert gone not in a, gone
    assert "isBowlField" in a and "#export/" in a


def test_screens_ask_reel_kinds():
    for f in ("review.js", "export.js", "sync.js"):
        assert "reelKinds" in read(f), f
    assert "new Set(V.clips.map(role)).size" not in read("review.js")


def test_review_export_flag_and_key():
    r = read("review.js")
    assert "export_clip" in r and "k === 'e' || k === 'E'" in r and "repeat(2" in (config.STATIC_DIR / "styles.css").read_text(encoding="utf-8")
    x = read("export.js")
    assert "Starts with the clips you flagged" in x and "'hl'" in x and "Look" not in x


def test_sync_check_balls_ticks_and_no_dock_nav():
    s = read("sync.js")
    assert "Check balls" in s and "Fix a ball" not in s and "class=\"ballt" in s and "dockheadnav" not in s
