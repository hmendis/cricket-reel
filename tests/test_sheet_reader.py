import io
import json
from types import SimpleNamespace

import anthropic
import httpx
import pytest
from PIL import Image

from app import sheet_reader
from app.scorecard import load_tokens
from conftest import sample_sheet


class FakeMessages:
    def __init__(self, responses):
        self.responses, self.calls = list(responses), []

    def create(self, **kw):
        self.calls.append(kw)
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def reply(text, stop="end_turn"):
    return SimpleNamespace(stop_reason=stop, content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=text)])


def client_with(*responses):
    return SimpleNamespace(messages=FakeMessages(responses))


def jpeg():
    buf = io.BytesIO()
    Image.new("RGB", (40, 60), "white").save(buf, "JPEG")
    return buf.getvalue()


def bad_request(msg):
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return anthropic.BadRequestError(msg, response=httpx.Response(400, request=req), body=None)


def test_read_sheet_parses_structured_output():
    c = client_with(reply(json.dumps(sample_sheet())))
    r = sheet_reader.read_sheet(jpeg(), "Alex", "claude-opus-5-5", load_tokens(), "k", client=c)
    assert r.batter.name == "Alex" and len(r.overs) == 4
    call = c.messages.calls[0]
    assert call["model"] == "claude-opus-5-5"
    assert call["output_config"]["format"]["type"] == "json_schema"
    assert call["extra_body"] == {"fallbacks": "default"}
    assert call["messages"][0]["content"][0]["type"] == "image"
    assert "Alex" in call["messages"][0]["content"][1]["text"]


def test_retries_without_fallback_param_if_rejected():
    c = client_with(bad_request("fallbacks: unknown parameter"), reply(json.dumps(sample_sheet())))
    sheet_reader.read_sheet(jpeg(), "Alex", "claude-opus-5-5", load_tokens(), "k", client=c)
    assert "extra_body" not in c.messages.calls[1]


@pytest.mark.parametrize("resp,code", [
    (reply("", stop="refusal"), "refusal"),
    (reply('{"partial":', stop="max_tokens"), "unreadable"),
    (reply("not json"), "unreadable"),
])
def test_bad_responses_raise_friendly_errors(resp, code):
    with pytest.raises(sheet_reader.SheetReadError) as e:
        sheet_reader.read_sheet(jpeg(), "Alex", "claude-opus-5-5", load_tokens(), "k", client=client_with(resp))
    assert e.value.code == code


def test_no_overs_found_is_unreadable():
    s = sample_sheet()
    s["overs"] = []
    with pytest.raises(sheet_reader.SheetReadError) as e:
        sheet_reader.read_sheet(jpeg(), "Alex", "claude-opus-5-5", load_tokens(), "k", client=client_with(reply(json.dumps(s))))
    assert "Alex" in e.value.message


def test_auth_error_message():
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    err = anthropic.AuthenticationError("bad key", response=httpx.Response(401, request=req), body=None)
    with pytest.raises(sheet_reader.SheetReadError) as e:
        sheet_reader.read_sheet(jpeg(), "Alex", "claude-opus-5-5", load_tokens(), "k", client=client_with(err))
    assert e.value.code == "auth"


def test_prepare_image_handles_png_and_pdf(tmp_path):
    big = tmp_path / "sheet.png"
    Image.new("RGB", (4000, 3000), "white").save(big)
    data = sheet_reader.prepare_image(big, display_copy=tmp_path / "d.jpg")
    img = Image.open(io.BytesIO(data))
    assert max(img.size) == sheet_reader.MAX_EDGE and (tmp_path / "d.jpg").exists()

    pdf = tmp_path / "sheet.pdf"
    Image.new("RGB", (600, 800), "white").save(pdf)
    assert Image.open(io.BytesIO(sheet_reader.prepare_image(pdf))).format == "JPEG"


def test_prepare_image_rejects_garbage(tmp_path):
    p = tmp_path / "sheet.jpg"
    p.write_bytes(b"not an image")
    with pytest.raises(sheet_reader.SheetReadError):
        sheet_reader.prepare_image(p)
