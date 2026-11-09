"""Offline tests: no Apify or Anthropic calls. Run with `python -m pytest -q`."""

import json
import sys
import types

import sentiment


def make_comments(*texts):
    return [{"platform": "instagram", "post_url": "https://www.instagram.com/p/x/", "text": t, "likes": i}
            for i, t in enumerate(texts)]


def fake_anthropic(response):
    """Install a stand-in `anthropic` module whose client returns `response` and records the request."""
    calls = []

    class Messages:
        def create(self, **kwargs):
            calls.append(kwargs)
            return response

    client = types.SimpleNamespace(beta=types.SimpleNamespace(messages=Messages()))
    module = types.ModuleType("anthropic")
    module.Anthropic = lambda: client
    module.RateLimitError = type("RateLimitError", (Exception,), {})
    sys.modules["anthropic"] = module
    return calls


def text_response(payload, stop_reason="end_turn"):
    block = types.SimpleNamespace(type="text", text=json.dumps(payload))
    return types.SimpleNamespace(stop_reason=stop_reason, content=[block])


def test_platform_detection():
    assert sentiment.platform_of("https://www.instagram.com/p/abc/") == "instagram"
    assert sentiment.platform_of("https://www.facebook.com/reel/1/") == "facebook"
    assert sentiment.platform_of("https://fb.watch/xyz/") == "facebook"
    assert sentiment.platform_of("https://example.com/") is None


def test_claude_results_are_applied():
    comments = make_comments("love it", "worst update ever", "ok")
    calls = fake_anthropic(text_response({"results": [
        {"i": 0, "sentiment": "positive", "topic": "Product Love"},
        {"i": 1, "sentiment": "negative", "topic": "app update"},
        {"i": 7, "sentiment": "neutral", "topic": "out of range is ignored"},
    ]}))
    sentiment.classify_with_claude(comments, "claude-opus-5-5")
    assert [c["sentiment"] for c in comments] == ["positive", "negative", "unknown"]
    assert comments[0]["topic"] == "product love"
    request = calls[0]
    assert request["model"] == "claude-opus-5-5"
    assert request["output_config"]["format"]["type"] == "json_schema"
    assert "2. ok" in request["messages"][0]["content"]


def test_claude_refusal_marks_batch_unknown():
    comments = make_comments("a", "b")
    fake_anthropic(text_response({}, stop_reason="refusal"))
    sentiment.classify_with_claude(comments, "claude-opus-5-5")
    assert all(c["sentiment"] == "unknown" for c in comments)


def test_claude_batches_of_fifty():
    comments = make_comments(*[f"comment {n}" for n in range(120)])
    calls = fake_anthropic(text_response({"results": []}))
    sentiment.classify_with_claude(comments, "claude-opus-5-5")
    assert len(calls) == 3


def test_vader_and_summary(tmp_path):
    comments = make_comments("I love this, amazing!", "This is terrible and broken", "It is a phone")
    sentiment.classify_with_vader(comments)
    assert [c["sentiment"] for c in comments] == ["positive", "negative", "neutral"]
    report = sentiment.summary(comments)
    assert "3 comments" in report and "terrible" in report
    out = tmp_path / "c.csv"
    sentiment.write_csv(comments, str(out))
    assert out.read_text(encoding="utf-8").splitlines()[0].startswith("platform,post_url,sentiment")
