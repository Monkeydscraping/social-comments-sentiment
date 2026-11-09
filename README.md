# social-comments-sentiment

What are people *actually* saying under that post? Paste Facebook or Instagram links, get every public comment in a CSV with a sentiment and a topic next to it, plus a short summary per post.

Useful when you want to check how a launch landed, compare your posts with a competitor's, or show your boss something better than "the vibes are mixed".

```
## https://www.instagram.com/p/DDIJAfeyemG/
29 comments: positive 19 (65%), neutral 8 (27%), negative 1 (3%), mixed 1 (3%)
Top topics: emoji reaction (5), laughing emojis (3), heart emojis (2), applause emojis (2), love for instagram (1)
```

That's Claude mode, on a real post. You also get the most liked negative comments, which is usually where the real feedback is. On the same post the free VADER mode found only 9 positives: it reads "❤️🙌🔥" as negative and doesn't speak Spanish.

## How it works

1. The comments come from two Apify Actors: [Facebook Comments Scraper](https://apify.com/monkey.d.scraping/facebook-comments-scraper) and [Instagram Comments Scraper](https://apify.com/monkey.d.scraping/instagram-comments-scraper). Public posts, reels and videos, no login.
2. Each comment gets a sentiment: **Claude** if you have an Anthropic key (any language, sarcasm included, plus a topic), otherwise **VADER**, which is free and runs offline but only really understands English.
3. You get `comments.csv` and `comments-summary.md`.

## Run it

```bash
git clone https://github.com/Monkeydscraping/social-comments-sentiment
cd social-comments-sentiment
pip install -r requirements.txt

export APIFY_TOKEN=...            # apify.com > Settings > API & Integrations
export ANTHROPIC_API_KEY=...      # optional, for Claude

python sentiment.py https://www.instagram.com/p/DDIJAfeyemG/ "https://www.facebook.com/reel/1503751661599810/"
```

Options:

| Flag | Default | What it does |
| --- | --- | --- |
| `--max-comments` | 100 | comments per post |
| `--engine` | `auto` | `claude`, `vader`, or `auto` (Claude when a key is set) |
| `--model` | `claude-opus-5-5` | any Claude model |
| `--out` | `comments.csv` | where to save the CSV |

## What it costs

- **Comments:** $0.18 per 1,000 on the Apify Free plan, less on paid plans. 100 comments ≈ 2 cents. New Apify accounts get free monthly credits, so your first runs are on the house.
- **Claude:** roughly half a dollar per 1,000 comments with the default model, sent 50 at a time. Pick a smaller model with `--model` if you're classifying a lot.
- **VADER:** free.

## CSV columns

`platform`, `post_url`, `sentiment` (positive / neutral / negative / mixed), `topic`, `likes`, `author`, `created_at`, `is_reply`, `text`, `comment_url`.

## FAQ

**Private posts?** No. Only what anyone can see without logging in.

**Can I run it every day?** Yes: schedule it with cron or GitHub Actions, or skip the script and schedule the Actors directly on Apify.

**Does it work with n8n / Make?** The Actors have native n8n, Make and Zapier integrations. An importable n8n workflow is next on the list.

---

Made by [Monkey.D.Scraping](https://github.com/Monkeydscraping). Something broke or you need another platform? Open an issue.
