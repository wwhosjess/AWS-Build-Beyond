"""Analyse cybersecurity articles and create a Markdown threat briefing."""

import json
import logging
import os
import re

from dotenv import load_dotenv
from openai import OpenAI


logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
DEFAULT_MODEL = "gpt-4.1-mini"
DEFAULT_TOP_N = 3

CRITICAL_KEYWORDS = (
    "critical",
    "zero-day",
    "zero day",
    "zero-click",
    "zero click",
    "actively exploited",
    "active exploitation",
)
HIGH_KEYWORDS = (
    "ransomware",
    "malware",
    "data breach",
    "breach",
    "stolen credentials",
    "credential theft",
    "major attack",
    "cyber attack",
)
MEDIUM_KEYWORDS = ("vulnerability", "exploit", "phishing", "attack", "threat")
REQUIRED_AI_FIELDS = (
    "threat / update",
    "severity score",
    "severity level",
    "what happened",
    "why it matters",
    "who is affected",
    "recommended action",
    "source link",
)

BRIEFING_INSTRUCTIONS = """
You are a cybersecurity analyst writing a concise daily threat briefing for
cybersecurity students and non-experts.

Review the supplied RSS articles and select the {top_n} most important
updates. Prioritize critical vulnerabilities, actively exploited
vulnerabilities, data breaches, malware or ransomware, major cyber attacks,
and AI security threats. Ignore low-impact or duplicate news.

Return exactly {top_n} briefing entries, each beginning with a level-three
Markdown heading (`###`). Do not add an introduction entry, conclusion entry,
or extra heading. Do not invent or pad entries beyond the supplied articles.

Write clean Markdown. Start with `## Cyber Intelligence Briefing`. For every
selected update, use this exact structure:

### [Short headline]
- **Threat / Update:**
- **Severity Score:** [number]/10
- **Severity Level:** [Critical, High, Medium, or Low]
- **What Happened:**
- **Why it matters:**
- **Who Is Affected:**
- **Recommended Action:**
- **Source Link:** [Read the source](URL)

Use plain, clear language. A severity score of 9-10 is Critical, 7-8 is High,
4-6 is Medium, and 1-3 is Low. Do not invent facts, affected groups, severity,
or actions. Only use information and links included in the supplied articles.
When the articles do not provide enough information for a field, write
"Insufficient information in the provided article." If fewer than {top_n}
articles are available, analyse only the available articles.
""".strip()


def _selection_limit(articles, top_n):
    """Keep the requested selection size within the available article count."""
    try:
        requested_count = int(top_n)
    except (TypeError, ValueError):
        requested_count = DEFAULT_TOP_N

    return min(max(1, requested_count), len(articles))


def _briefing_instructions(top_n):
    """Insert the requested number of priority updates into the AI prompt."""
    return BRIEFING_INSTRUCTIONS.replace("{top_n}", str(top_n))


def _article_text(article):
    """Return article text used for simple keyword matching."""
    return f"{article.get('title', '')} {article.get('summary', '')}".lower()


def _severity_for(article):
    """Estimate severity from the article's own title and summary."""
    text = _article_text(article)

    if any(keyword in text for keyword in CRITICAL_KEYWORDS):
        return 9, "Critical"
    if any(keyword in text for keyword in HIGH_KEYWORDS):
        return 8, "High"
    if any(keyword in text for keyword in MEDIUM_KEYWORDS):
        return 5, "Medium"
    return 2, "Low"


def _priority_score(article):
    """Rank articles by severity and the number of high-risk keyword matches."""
    text = _article_text(article)
    keyword_matches = sum(keyword in text for keyword in CRITICAL_KEYWORDS)
    keyword_matches += sum(keyword in text for keyword in HIGH_KEYWORDS)
    keyword_matches += sum(keyword in text for keyword in MEDIUM_KEYWORDS)
    return _severity_for(article)[0] + keyword_matches


def _recommended_action(article):
    """Return a cautious action based only on the update category."""
    text = _article_text(article)

    if any(keyword in text for keyword in ("ransomware", "malware")):
        return "Review affected systems for signs of compromise and follow the source's mitigation guidance."
    if any(keyword in text for keyword in ("breach", "credential")):
        return "Review the source, monitor relevant accounts, and rotate credentials if the article applies to your environment."
    return "Review the source, identify potentially affected systems, and apply the recommended updates or mitigations if applicable."


def _why_it_matters(severity):
    """Explain priority without adding facts not present in an article."""
    if severity == "Critical":
        return "The article includes language associated with urgent exploitation or a critical security issue."
    if severity == "High":
        return "The article is related to a potentially high-impact cyber threat that warrants prompt review."
    if severity == "Medium":
        return "The article describes a security issue that may affect relevant systems or users."
    return "The article may still be useful for awareness, but it has fewer high-risk indicators."


def generate_fallback_briefing(articles, top_n=DEFAULT_TOP_N):
    """Create a rule-based Markdown briefing when AI is unavailable."""
    if not articles:
        return "## Cyber Intelligence Briefing\n\n**Mode: Fallback Analysis**\n\nNo recent articles were available to analyze."

    selected_count = _selection_limit(articles, top_n)
    ranked_articles = sorted(
        articles,
        key=_priority_score,
        reverse=True,
    )[:selected_count]

    sections = ["## Cyber Intelligence Briefing", "**Mode: Fallback Analysis**"]
    for number, article in enumerate(ranked_articles, start=1):
        score, severity = _severity_for(article)
        title = article.get("title", "Untitled update")
        summary = article.get("summary") or "Insufficient information in the provided article."
        link = article.get("link", "")
        source_link = f"[Read the source]({link})" if link else "Source link unavailable."

        sections.append(
            f"""### {number}. {title}
- **Threat / Update:** {title}
- **Severity:** {severity} (estimated {score}/10)
- **What Happened:** {summary}
- **Why It Matters:** {_why_it_matters(severity)}
- **Recommended Action:** {_recommended_action(article)}
- **Source Link:** {source_link}"""
        )

    return "\n\n".join(sections)


def _add_ai_mode(briefing):
    """Ensure every successful AI response clearly identifies its mode."""
    heading = "## Cyber Intelligence Briefing"
    mode = "**Mode: AI Analysis**"

    if mode in briefing:
        return briefing
    if briefing.startswith(heading):
        return f"{heading}\n\n{mode}{briefing[len(heading):]}"
    return f"{heading}\n\n{mode}\n\n{briefing}"


def _valid_ai_briefing(briefing, expected_count):
    """Accept only an AI result with the requested complete entry structure."""
    sections = re.split(r"(?m)^###\s+", briefing)
    entries = sections[1:]
    if len(entries) != expected_count:
        logger.warning(
            "AI stage=validation result=fallback reason=wrong_entry_count "
            "expected_entries=%s parsed_entries=%s.",
            expected_count,
            len(entries),
        )
        return False

    for entry_number, entry in enumerate(entries, start=1):
        lines = entry.strip().splitlines()
        fields = {
            match.group(1).strip().lower()
            for line in lines[1:]
            if (match := re.match(r"- \*\*(.+?):\*\*\s*(.+)", line))
        }
        missing_fields = sorted(set(REQUIRED_AI_FIELDS) - fields)
        if not lines or not lines[0].strip() or missing_fields:
            logger.warning(
                "AI stage=validation result=fallback reason=malformed_entry "
                "entry=%s missing_fields=%s.",
                entry_number,
                ",".join(missing_fields) if missing_fields else "headline",
            )
            return False

    return True


def _openai_error_details(error):
    """Return safe OpenAI error metadata without exposing request credentials."""
    status_code = getattr(error, "status_code", None)
    error_code = getattr(error, "code", None)
    return type(error).__name__, status_code, error_code


def generate_briefing(articles, top_n=DEFAULT_TOP_N, model=DEFAULT_MODEL):
    """Return a Markdown threat briefing generated from RSS article dictionaries.

    Uses OpenAI when available and a rule-based fallback if it is not. The
    number of selected priority updates is controlled by ``top_n``.
    """
    if not articles:
        logger.warning("AI stage=input result=fallback reason=no_articles.")
        return generate_fallback_briefing(articles, top_n)

    selected_count = _selection_limit(articles, top_n)

    load_dotenv()
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        logger.warning("AI stage=configuration result=fallback reason=missing_api_key.")
        return generate_fallback_briefing(articles, selected_count)

    try:
        client = OpenAI(api_key=api_key)
    except Exception as error:
        error_type, status_code, error_code = _openai_error_details(error)
        logger.warning(
            "AI stage=client_initialization result=fallback exception_type=%s "
            "status_code=%s error_code=%s.",
            error_type,
            status_code,
            error_code,
        )
        return generate_fallback_briefing(articles, selected_count)

    try:
        logger.info(
            "AI stage=request model=%s candidate_articles=%s expected_entries=%s.",
            model,
            len(articles),
            selected_count,
        )
        response = client.responses.create(
            model=model,
            instructions=_briefing_instructions(selected_count),
            input="Articles to review:\n" + json.dumps(articles, ensure_ascii=False, indent=2),
            max_output_tokens=max(900, selected_count * 250),
            store=False,
        )
    except Exception as error:
        error_type, status_code, error_code = _openai_error_details(error)
        logger.warning(
            "AI stage=request result=fallback model=%s exception_type=%s "
            "status_code=%s error_code=%s.",
            model,
            error_type,
            status_code,
            error_code,
        )
        return generate_fallback_briefing(articles, selected_count)

    output_text = getattr(response, "output_text", None)
    if not isinstance(output_text, str) or not output_text.strip():
        logger.warning("AI stage=output result=fallback reason=empty_output_text.")
        return generate_fallback_briefing(articles, selected_count)

    briefing = output_text.strip()
    if not _valid_ai_briefing(briefing, selected_count):
        return generate_fallback_briefing(articles, selected_count)

    logger.info(
        "AI stage=validation result=accepted model=%s expected_entries=%s parsed_entries=%s.",
        model,
        selected_count,
        selected_count,
    )
    return _add_ai_mode(briefing)


if __name__ == "__main__":
    from news_fetcher import fetch_news

    print(generate_briefing(fetch_news()))
