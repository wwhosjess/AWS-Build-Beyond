"""Fetch recent cybersecurity updates from trusted RSS sources."""

import html
import logging
import re

import feedparser


RSS_SOURCES = (
    ("The Hacker News", "https://feeds.feedburner.com/TheHackersNews"),
    ("BleepingComputer", "https://www.bleepingcomputer.com/feed/"),
)

# Used only when the live RSS feed is unavailable, so the workshop can continue.
FALLBACK_ARTICLES = [
    {
        "title": "Critical vulnerability update",
        "summary": "A critical software vulnerability requires prompt patching.",
        "published_date": "Workshop sample",
        "source": "The Hacker News (sample)",
        "link": "https://www.cisa.gov/news-events/cybersecurity-advisories",
    },
    {
        "title": "Active exploitation warning",
        "summary": "Organisations should review systems for an actively exploited weakness.",
        "published_date": "Workshop sample",
        "source": "The Hacker News (sample)",
        "link": "https://www.cisa.gov/known-exploited-vulnerabilities-catalog",
    },
    {
        "title": "Ransomware defence reminder",
        "summary": "Maintain offline backups and apply security updates to reduce ransomware risk.",
        "published_date": "Workshop sample",
        "source": "The Hacker News (sample)",
        "link": "https://www.cisa.gov/stopransomware",
    },
    {
        "title": "Phishing awareness update",
        "summary": "Users should verify unexpected messages before opening links or attachments.",
        "published_date": "Workshop sample",
        "source": "The Hacker News (sample)",
        "link": "https://www.cisa.gov/topics/cyber-threats-and-advisories/phishing-guidance",
    },
    {
        "title": "Secure configuration guidance",
        "summary": "Review account access, multi-factor authentication, and system configuration.",
        "published_date": "Workshop sample",
        "source": "The Hacker News (sample)",
        "link": "https://www.cisa.gov/topics/cybersecurity-best-practices",
    },
]


def _clean_text(text):
    """Remove HTML tags from RSS summaries so they display cleanly."""
    text_without_tags = re.sub(r"<[^>]+>", "", text or "")
    return html.unescape(text_without_tags).strip()


def _articles_from_source(source_name, feed_url, limit):
    """Fetch a requested number of articles from one source independently."""
    feed = feedparser.parse(feed_url)
    if feed.bozo:
        raise ValueError(f"Unable to read RSS feed: {feed.bozo_exception}")

    articles = []
    for entry in feed.entries[:limit]:
        try:
            articles.append(
                {
                    "title": _clean_text(entry.get("title", "Untitled update")),
                    "summary": _clean_text(entry.get("summary", "No summary available.")),
                    "published_date": entry.get("published", entry.get("updated", "Unknown date")),
                    "source": source_name,
                    "link": entry.get("link", ""),
                }
            )
        except (AttributeError, TypeError) as error:
            logging.warning("Skipping an invalid article from %s: %s", source_name, error)

    return articles


def fetch_news(limit=5):
    """Return recent articles in a consistent format.

    If the RSS feed is unavailable or cannot be parsed, five sample articles
    are returned so the web app can continue running.
    """
    try:
        requested_limit = max(1, int(limit))
    except (TypeError, ValueError):
        requested_limit = 5

    articles = []
    for source_name, feed_url in RSS_SOURCES:
        try:
            articles.extend(_articles_from_source(source_name, feed_url, requested_limit))
        except Exception as error:
            logging.warning("Could not fetch news from %s: %s", source_name, error)

    if articles:
        return articles[:requested_limit]

    logging.warning("All live RSS sources failed; using fallback sample data.")
    return FALLBACK_ARTICLES[:requested_limit].copy()


if __name__ == "__main__":
    articles = fetch_news()
    using_fallback = articles and articles[0]["source"].endswith("(sample)")
    status = "FALLBACK sample data" if using_fallback else "LIVE cybersecurity RSS sources"
    print(f"Data source: {status}\n")

    for number, article in enumerate(articles, start=1):
        print(f"{number}. {article['title']}")
        print(f"   Source: {article['source']}")
        print(f"   Link: {article['link']}\n")
