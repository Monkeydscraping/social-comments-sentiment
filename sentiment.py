"""Pull public comments from Facebook and Instagram posts and tag each one with a sentiment.

Usage:
    python sentiment.py https://www.instagram.com/p/DC7Q4z5JPMX/ https://www.facebook.com/reel/1503751661599810/

Needs APIFY_TOKEN. With an Anthropic key it uses Claude (any language, plus a short topic per comment);
without one it falls back to VADER, which is free but English-only.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import Counter, defaultdict
from urllib.parse import urlparse

from apify_client import ApifyClient

FACEBOOK_ACTOR = "monkey.d.scraping/facebook-comments-scraper"
INSTAGRAM_ACTOR = "monkey.d.scraping/instagram-comments-scraper"
SENTIMENTS = ["positive", "neutral", "negative", "mixed"]
BATCH_SIZE = 50


def platform_of(url: str) -> str | None:
    host = urlparse(url).netloc.lower()
    if host.endswith("instagram.com"):
        return "instagram"
    if host.endswith(("facebook.com", "fb.watch", "fb.com")):
        return "facebook"
    return None


def fetch_comments(urls: list[str], max_comments: int) -> list[dict]:
    """Run the two comment scrapers on Apify and return one flat list of comments."""
    apify = ApifyClient(os.environ["APIFY_TOKEN"])
    by_platform: dict[str, list[str]] = defaultdict(list)
    for url in urls:
        platform = platform_of(url)
        if platform is None:
            print(f"skipping {url}: not a Facebook or Instagram link", file=sys.stderr)
            continue
        by_platform[platform].append(url)

    comments: list[dict] = []
    for platform, actor in (("facebook", FACEBOOK_ACTOR), ("instagram", INSTAGRAM_ACTOR)):
        if not by_platform[platform]:
            continue
        print(f"reading {platform} comments from {len(by_platform[platform])} post(s)...", file=sys.stderr)
        run_input = {"startUrls": [{"url": u} for u in by_platform[platform]], "maxComments": max_comments}
        run = apify.actor(actor).call(run_input=run_input, logger=None)
        if run is None:
            print(f"{platform}: the run did not start", file=sys.stderr)
            continue
        for item in apify.dataset(run.default_dataset_id).iterate_items():
            if not item.get("text"):
                continue
            comments.append({
                "platform": platform,
                "post_url": item.get("postUrl") or item.get("inputUrl"),
                "comment_url": item.get("commentUrl"),
                "author": item.get("authorName") or item.get("authorUsername"),
                "text": item["text"],
                "created_at": item.get("createdAt"),
                "likes": item.get("reactionCount", item.get("likeCount")) or 0,
                "is_reply": item.get("type") == "reply",
            })
    return comments


def classify_with_claude(comments: list[dict], model: str) -> None:
    import anthropic

    client = anthropic.Anthropic()
    schema = {
        "type": "object",
        "properties": {
            "results": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "i": {"type": "integer"},
                        "sentiment": {"type": "string", "enum": SENTIMENTS},
                        "topic": {"type": "string"},
                    },
                    "required": ["i", "sentiment", "topic"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["results"],
        "additionalProperties": False,
    }
    for start in range(0, len(comments), BATCH_SIZE):
        batch = comments[start:start + BATCH_SIZE]
        numbered = "\n".join(f"{i}. {c['text'][:600]}" for i, c in enumerate(batch))
        prompt = (
            "Below are public social media comments, one per line, numbered from 0. "
            "For each one give its sentiment towards the post or brand (positive, neutral, negative or mixed) "
            "and a topic of two to four English words. Comments can be in any language; sarcasm counts as what it means.\n\n"
            + numbered
        )
        try:
            response = client.beta.messages.create(
                model=model,
                max_tokens=16000,
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                output_config={"effort": "low", "format": {"type": "json_schema", "schema": schema}},
                messages=[{"role": "user", "content": prompt}],
            )
        except anthropic.RateLimitError:
            print("rate limited by Anthropic; try again in a minute or use --engine vader", file=sys.stderr)
            raise
        if response.stop_reason == "refusal":
            for c in batch:
                c["sentiment"], c["topic"] = "unknown", ""
            continue
        text = next(b.text for b in response.content if b.type == "text")
        for row in json.loads(text)["results"]:
            if 0 <= row["i"] < len(batch):
                batch[row["i"]]["sentiment"] = row["sentiment"]
                batch[row["i"]]["topic"] = row["topic"].lower()
        print(f"classified {min(start + BATCH_SIZE, len(comments))}/{len(comments)}", file=sys.stderr)
    for c in comments:
        c.setdefault("sentiment", "unknown")
        c.setdefault("topic", "")


def classify_with_vader(comments: list[dict]) -> None:
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

    analyzer = SentimentIntensityAnalyzer()
    for c in comments:
        score = analyzer.polarity_scores(c["text"])["compound"]
        c["sentiment"] = "positive" if score >= 0.05 else "negative" if score <= -0.05 else "neutral"
        c["topic"] = ""


def write_csv(comments: list[dict], path: str) -> None:
    fields = ["platform", "post_url", "sentiment", "topic", "likes", "author", "created_at", "is_reply", "text", "comment_url"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(comments)


def summary(comments: list[dict]) -> str:
    lines = ["# Comment sentiment", ""]
    posts: dict[str, list[dict]] = defaultdict(list)
    for c in comments:
        posts[c["post_url"]].append(c)
    for post, rows in posts.items():
        counts = Counter(r["sentiment"] for r in rows)
        total = len(rows)
        lines.append(f"## {post}")
        lines.append(f"{total} comments: " + ", ".join(
            f"{s} {counts[s]} ({counts[s] * 100 // total}%)" for s in SENTIMENTS + ["unknown"] if counts[s]))
        topics = Counter(r["topic"] for r in rows if r["topic"])
        if topics:
            lines.append("Top topics: " + ", ".join(f"{t} ({n})" for t, n in topics.most_common(5)))
        loudest = sorted((r for r in rows if r["sentiment"] == "negative"), key=lambda r: -int(r["likes"] or 0))[:3]
        if loudest:
            lines.append("Most liked negative comments:")
            lines += [f"- ({r['likes']} likes) {r['text'][:200]}" for r in loudest]
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("urls", nargs="+", help="public Facebook or Instagram post, reel or video links")
    parser.add_argument("--max-comments", type=int, default=100, help="comments per post (default 100)")
    parser.add_argument("--engine", choices=["auto", "claude", "vader"], default="auto")
    parser.add_argument("--model", default="claude-opus-5-5", help="Claude model for --engine claude")
    parser.add_argument("--out", default="comments.csv", help="CSV output path")
    args = parser.parse_args()

    if not os.environ.get("APIFY_TOKEN"):
        sys.exit("Set APIFY_TOKEN first (Apify console > Settings > API & Integrations).")

    comments = fetch_comments(args.urls, args.max_comments)
    if not comments:
        sys.exit("No comments found. Check that the posts are public.")

    engine = args.engine
    if engine == "auto":
        engine = "claude" if os.environ.get("ANTHROPIC_API_KEY") else "vader"
    print(f"{len(comments)} comments, classifying with {engine}...", file=sys.stderr)
    if engine == "claude":
        classify_with_claude(comments, args.model)
    else:
        classify_with_vader(comments)

    write_csv(comments, args.out)
    report = summary(comments)
    with open(args.out.rsplit(".", 1)[0] + "-summary.md", "w", encoding="utf-8") as f:
        f.write(report)
    print(report)
    print(f"saved {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
