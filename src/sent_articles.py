"""Small local store for article identifiers sent by the daily briefing."""

import json
import logging
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable


logger = logging.getLogger(__name__)
STATE_FILE = Path(__file__).resolve().parent.parent / "data" / "sent_articles.json"
MAX_STORED_IDS = 1000


def article_id(article: dict) -> str:
    """Return the stable URL identifier used to prevent repeat sends."""
    return str(article.get("link", "")).strip()


class SentArticleStore:
    """Persist IDs locally when the deployment provides durable disk storage."""

    def __init__(self, path: Path = STATE_FILE):
        self.path = path

    def sent_ids(self) -> set[str]:
        """Read stored article IDs without failing a briefing if state is invalid."""
        if not self.path.exists():
            return set()

        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            ids = data.get("article_ids", [])
            return {item for item in ids if isinstance(item, str) and item}
        except (OSError, json.JSONDecodeError, AttributeError) as error:
            logger.warning("Could not read sent-article state: %s", error)
            return set()

    def unseen_articles(self, articles: Iterable[dict]) -> list[dict]:
        """Return articles whose URL has not been recorded as sent."""
        sent = self.sent_ids()
        return [article for article in articles if article_id(article) not in sent]

    def mark_briefing_articles(self, articles: Iterable[dict], briefing: str) -> None:
        """Record only source URLs that were actually included in a sent briefing."""
        source_urls = set(re.findall(r"\((https?://[^)\s]+)\)", briefing or ""))
        ids_to_add = {article_id(article) for article in articles if article_id(article) in source_urls}
        if not ids_to_add:
            logger.warning("No article source URLs were found to record after delivery.")
            return

        try:
            existing_ids = self.sent_ids()
            updated_ids = sorted(existing_ids | ids_to_add)[-MAX_STORED_IDS:]
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps({"article_ids": updated_ids}, indent=2), encoding="utf-8"
            )
            logger.info("Recorded %s sent article identifier(s).", len(ids_to_add))
        except OSError as error:
            logger.error("Could not persist sent-article state: %s", error)


class DynamoDBSentArticleStore:
    """Persist sent article URLs in DynamoDB for AWS Lambda deployments."""

    def __init__(self, table_name: str):
        import boto3

        self.table = boto3.resource("dynamodb").Table(table_name)

    def sent_ids(self, articles: Iterable[dict]) -> set[str]:
        """Look up only the article IDs relevant to this briefing run."""
        sent = set()
        for article in articles:
            identifier = article_id(article)
            if not identifier:
                continue
            try:
                result = self.table.get_item(Key={"article_id": identifier})
                if result.get("Item"):
                    sent.add(identifier)
            except Exception as error:
                logger.error("Could not read sent article %s from DynamoDB: %s", identifier, error)
        return sent

    def unseen_articles(self, articles: Iterable[dict]) -> list[dict]:
        """Return articles not yet recorded in DynamoDB."""
        article_list = list(articles)
        sent = self.sent_ids(article_list)
        return [article for article in article_list if article_id(article) not in sent]

    def mark_briefing_articles(self, articles: Iterable[dict], briefing: str) -> None:
        """Record successfully delivered article URLs and the delivery time."""
        source_urls = set(re.findall(r"\((https?://[^)\s]+)\)", briefing or ""))
        sent_at = datetime.now(UTC).isoformat()
        for article in articles:
            identifier = article_id(article)
            if not identifier or identifier not in source_urls:
                continue
            try:
                self.table.put_item(
                    Item={
                        "article_id": identifier,
                        "article_url": identifier,
                        "sent_at": sent_at,
                    }
                )
            except Exception as error:
                logger.error("Could not record sent article in DynamoDB: %s", error)


def create_sent_article_store():
    """Use DynamoDB in AWS when configured, otherwise local JSON storage."""
    table_name = os.getenv("SENT_ARTICLES_TABLE")
    if table_name:
        logger.info("Using DynamoDB for sent-article tracking.")
        return DynamoDBSentArticleStore(table_name)

    logger.warning("Using local JSON sent-article tracking; it is not durable in AWS Lambda.")
    return SentArticleStore()
