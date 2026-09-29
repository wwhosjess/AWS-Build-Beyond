"""Shared briefing pipeline for Telegram commands and scheduled delivery."""

import logging
import os
from typing import Callable, Optional

from dotenv import load_dotenv

try:
    from .ai_summarizer import generate_briefing as analyse_articles
    from .news_fetcher import fetch_news
    from .telegram_sender import send_to_telegram
except ImportError:  # Supports: python src/main.py
    from ai_summarizer import generate_briefing as analyse_articles
    from news_fetcher import fetch_news
    from telegram_sender import send_to_telegram


logger = logging.getLogger(__name__)

MIN_TOP_N = 1
MAX_TOP_N = 10


def _default_top_n() -> int:
    """Read a valid default briefing size from the environment."""
    load_dotenv()
    try:
        requested_count = int(os.getenv("DEFAULT_BRIEF_COUNT", "3"))
    except ValueError:
        return 3
    return requested_count if MIN_TOP_N <= requested_count <= MAX_TOP_N else 3


DEFAULT_TOP_N = _default_top_n()


def normalize_top_n(top_n: int = DEFAULT_TOP_N) -> Optional[int]:
    """Return a valid priority-update count, or None when it is invalid."""
    try:
        requested_count = int(top_n)
    except (TypeError, ValueError):
        return None

    if MIN_TOP_N <= requested_count <= MAX_TOP_N:
        return requested_count
    return None


def fetch_articles(limit: int = 5) -> list[dict]:
    """Fetch articles through the single shared RSS collection path."""
    return fetch_news(limit=limit)


def _candidate_count(top_n: int) -> int:
    """Fetch enough current articles to rank a requested briefing size."""
    return max(top_n * 3, 10)


def generate_briefing(
    top_n: int = DEFAULT_TOP_N, articles: Optional[list[dict]] = None
) -> Optional[str]:
    """Fetch news and create one briefing without sending it anywhere."""
    requested_count = normalize_top_n(top_n)
    if requested_count is None:
        logger.error(
            "Invalid priority-update count: %r. Expected %s to %s.",
            top_n,
            MIN_TOP_N,
            MAX_TOP_N,
        )
        return None

    try:
        if articles is None:
            candidate_count = _candidate_count(requested_count)
            available_articles = fetch_articles(limit=candidate_count)
            logger.info(
                "Fetched %s briefing candidate article(s) for requested top_n=%s.",
                len(available_articles),
                requested_count,
            )
        else:
            available_articles = articles
        if not available_articles:
            logger.error("Briefing generation stopped because no articles were returned.")
            return None

        logger.info(
            "Generating briefing from %s articles (top_n=%s).",
            len(available_articles),
            requested_count,
        )
        briefing = analyse_articles(available_articles, top_n=requested_count)
        if not briefing:
            logger.error("Analysis did not return a briefing.")
            return None

        return briefing
    except Exception:
        logger.exception("Unable to generate the cyber intelligence briefing.")
        return None


def generate_and_send_briefing(
    top_n: int = DEFAULT_TOP_N,
    chat_id: Optional[str] = None,
    articles: Optional[list[dict]] = None,
    on_delivery: Optional[Callable[[str], None]] = None,
    show_controls: bool = False,
) -> bool:
    """Generate a briefing and deliver it to Telegram.

    ``chat_id`` is optional so scheduled delivery uses TELEGRAM_CHAT_ID, while a
    Telegram command can reply to the chat that sent the command.
    """
    briefing = generate_briefing(top_n=top_n, articles=articles)
    if not briefing:
        return False

    try:
        if not send_to_telegram(briefing, chat_id=chat_id, show_controls=show_controls):
            logger.error("Telegram did not confirm delivery of the briefing.")
            return False
    except Exception:
        logger.exception("Unable to send the cyber intelligence briefing to Telegram.")
        return False

    logger.info("Cyber intelligence briefing delivered successfully.")
    if on_delivery:
        try:
            on_delivery(briefing)
        except Exception:
            logger.exception("Briefing was delivered, but post-delivery state could not be saved.")
    return True
