"""Run one scheduled Cyber Intelligence Assistant briefing, then exit."""

import logging
import os

from dotenv import load_dotenv

try:
    from .briefing_service import DEFAULT_TOP_N, fetch_articles, generate_and_send_briefing
    from .sent_articles import create_sent_article_store
except ImportError:  # Supports: python src/daily_brief.py
    from briefing_service import DEFAULT_TOP_N, fetch_articles, generate_and_send_briefing
    from sent_articles import create_sent_article_store


logger = logging.getLogger(__name__)


def _daily_candidate_count(default_count: int) -> int:
    """Fetch enough recent RSS items to find unseen daily briefing candidates."""
    return max(default_count * 10, 30)


def configure_logging() -> None:
    """Configure readable daily-job logs."""
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


def run_daily_briefing() -> bool:
    """Run the shared daily workflow once and return whether it was delivered."""
    timezone = os.getenv("TIMEZONE", "Asia/Singapore")
    logger.info("Starting daily cyber briefing for timezone %s.", timezone)

    try:
        candidate_count = _daily_candidate_count(DEFAULT_TOP_N)
        articles = fetch_articles(limit=candidate_count)
    except Exception:
        logger.exception("Daily briefing could not fetch articles.")
        return False

    try:
        store = create_sent_article_store()
    except Exception:
        logger.exception("Daily briefing could not initialise sent-article storage.")
        return False
    unseen_articles = store.unseen_articles(articles)
    logger.info(
        "Daily briefing found %s fetched candidate(s), %s unseen candidate(s), and requests %s update(s).",
        len(articles),
        len(unseen_articles),
        DEFAULT_TOP_N,
    )
    if not unseen_articles:
        logger.info("No unseen articles are available; daily briefing will not be sent.")
        return True

    if len(unseen_articles) < DEFAULT_TOP_N:
        logger.warning(
            "Only %s unseen article(s) are available; sending fewer than the configured %s updates.",
            len(unseen_articles),
            DEFAULT_TOP_N,
        )

    delivered = generate_and_send_briefing(
        top_n=DEFAULT_TOP_N,
        articles=unseen_articles,
        on_delivery=lambda briefing: store.mark_briefing_articles(unseen_articles, briefing),
        show_controls=True,
    )
    if not delivered:
        logger.error("Daily briefing failed to send.")
        return False

    logger.info("Daily briefing completed successfully.")
    return True


def main() -> int:
    """Run the local scheduled command once, then exit."""
    load_dotenv()
    configure_logging()
    return 0 if run_daily_briefing() else 1


if __name__ == "__main__":
    raise SystemExit(main())
