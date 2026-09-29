"""Unit tests for validated OpenAI briefings and safe fallback behaviour."""

import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from src import ai_summarizer
from src.telegram_sender import format_for_telegram


ARTICLES = [
    {
        "title": "Critical vulnerability update",
        "summary": "A critical issue affects a product.",
        "published_date": "2026-09-28",
        "source": "Test source",
        "link": "https://example.test/critical",
    },
    {
        "title": "Ransomware campaign update",
        "summary": "A ransomware campaign was reported.",
        "published_date": "2026-09-28",
        "source": "Test source",
        "link": "https://example.test/ransomware",
    },
    {
        "title": "Credential breach update",
        "summary": "A breach involved stolen credentials.",
        "published_date": "2026-09-28",
        "source": "Test source",
        "link": "https://example.test/credentials",
    },
]


VALID_AI_BRIEFING = """## Cyber Intelligence Briefing

### Critical vulnerability update
- **Threat / Update:** Critical vulnerability update
- **Severity Score:** 9/10
- **Severity Level:** Critical
- **What Happened:** A critical issue affects a product.
- **Why it matters:** It may require urgent review.
- **Who Is Affected:** Users of the affected product.
- **Recommended Action:** Review the source and assess exposure.
- **Source Link:** [Read the source](https://example.test/critical)

### Ransomware campaign update
- **Threat / Update:** Ransomware campaign update
- **Severity Score:** 8/10
- **Severity Level:** High
- **What Happened:** A ransomware campaign was reported.
- **Why it matters:** It can disrupt affected organisations.
- **Who Is Affected:** Organisations exposed to the campaign.
- **Recommended Action:** Review relevant containment guidance.
- **Source Link:** [Read the source](https://example.test/ransomware)

### Credential breach update
- **Threat / Update:** Credential breach update
- **Severity Score:** 8/10
- **Severity Level:** High
- **What Happened:** A breach involved stolen credentials.
- **Why it matters:** Compromised credentials can enable unauthorised access.
- **Who Is Affected:** Relevant account holders.
- **Recommended Action:** Review authentication activity.
- **Source Link:** [Read the source](https://example.test/credentials)"""


def openai_client_with(output=None, error=None):
    """Build a no-network OpenAI client double for Responses API tests."""
    def create(**_kwargs):
        if error:
            raise error
        return SimpleNamespace(output_text=output)

    return SimpleNamespace(responses=SimpleNamespace(create=create))


class SimulatedOpenAiError(RuntimeError):
    """Minimal OpenAI-style error object for safe diagnostic-log coverage."""

    def __init__(self, status_code, code):
        super().__init__(f"HTTP {status_code}")
        self.status_code = status_code
        self.code = code


class AiSummarizerTests(unittest.TestCase):
    def _generate(self, client, top_n=3):
        with (
            patch.dict(os.environ, {"OPENAI_API_KEY": "test-api-key"}),
            patch.object(ai_summarizer, "OpenAI", return_value=client),
        ):
            return ai_summarizer.generate_briefing(ARTICLES, top_n=top_n)

    def test_valid_ai_response_is_labelled_ai_assisted_for_telegram(self):
        briefing = self._generate(openai_client_with(output=VALID_AI_BRIEFING))

        self.assertIn("**Mode: AI Analysis**", briefing)
        self.assertIn("<b>Analysis:</b> AI-assisted", format_for_telegram(briefing))

    def test_openai_429_uses_rule_based_fallback(self):
        with self.assertLogs(ai_summarizer.logger, level="WARNING") as logs:
            briefing = self._generate(
                openai_client_with(
                    error=SimulatedOpenAiError(429, "insufficient_quota")
                )
            )

        self.assertIn("**Mode: Fallback Analysis**", briefing)
        self.assertIn("<b>Analysis:</b> Rule-based Fallback", format_for_telegram(briefing))
        self.assertIn("status_code=429", "\n".join(logs.output))

    def test_empty_ai_response_uses_fallback(self):
        briefing = self._generate(openai_client_with(output=""))

        self.assertIn("**Mode: Fallback Analysis**", briefing)

    def test_wrong_count_ai_response_uses_fallback(self):
        one_entry = VALID_AI_BRIEFING.split("### Ransomware", 1)[0].strip()
        briefing = self._generate(openai_client_with(output=one_entry))

        self.assertIn("**Mode: Fallback Analysis**", briefing)

    def test_malformed_ai_response_uses_fallback(self):
        malformed = """## Cyber Intelligence Briefing

### First update
No structured fields were supplied.

### Second update
No structured fields were supplied.

### Third update
No structured fields were supplied."""
        briefing = self._generate(openai_client_with(output=malformed))

        self.assertIn("**Mode: Fallback Analysis**", briefing)


if __name__ == "__main__":
    unittest.main()
