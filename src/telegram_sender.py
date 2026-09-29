"""Create and send concise cyber intelligence briefs to Telegram."""

import html
import json
import logging
import os
import re
from datetime import date
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv


TELEGRAM_MESSAGE_LIMIT = 4000
SEVERITY_ICONS = {"Critical": "🔴", "High": "🟠", "Medium": "🟡", "Low": "🟢"}
SEVERITY_SCORES = {"Critical": "9/10", "High": "8/10", "Medium": "5/10", "Low": "2/10"}
BRIEFING_CONTROLS = {
    "inline_keyboard": [
        [
            {"text": "📰 3 Updates", "callback_data": "brief:3"},
            {"text": "📰 5 Updates", "callback_data": "brief:5"},
            {"text": "📰 10 Updates", "callback_data": "brief:10"},
        ],
        [{"text": "🔄 Refresh Latest", "callback_data": "brief:refresh"}],
    ]
}


def _parse_briefing(briefing):
    """Read the existing Markdown briefing without changing its content."""
    threats = []
    sections = re.split(r"(?m)^###\s+", briefing)

    for section in sections[1:]:
        lines = section.strip().splitlines()
        if not lines:
            continue

        title = re.sub(r"^\d+\.\s*", "", lines[0]).strip()
        fields = {}
        for line in lines[1:]:
            match = re.match(r"- \*\*(.+?):\*\*\s*(.*)", line)
            if match:
                fields[match.group(1).strip()] = match.group(2).strip()

        threats.append({"title": title, "fields": fields})

    return threats


def _field(fields, *names):
    """Return the first matching briefing field."""
    for name in names:
        if name in fields:
            return fields[name]
    return ""


def _complete_sentences(text, max_length=320, max_sentences=2):
    """Return one or two complete sentences, never a cut-off excerpt."""
    plain_text = re.sub(r"<[^>]+>", "", text or "")
    plain_text = re.sub(r"\*\*", "", plain_text).strip()
    sentences = re.findall(r"[^.!?]+[.!?]+(?=\s|$)", plain_text)
    sentences = [sentence.strip() for sentence in sentences if not sentence.strip().endswith("...")]

    selected = []
    for sentence in sentences[:max_sentences]:
        proposed = " ".join(selected + [sentence])
        if len(proposed) <= max_length or not selected:
            selected.append(sentence)
        else:
            break

    if selected:
        return " ".join(selected)
    return "The source provides limited detail; review the linked article for the full update."


def _severity(fields):
    """Read a score and level from either AI or fallback briefing fields."""
    value = _field(fields, "Severity Level", "Severity")
    level_match = re.search(r"Critical|High|Medium|Low", value)
    level = level_match.group() if level_match else "Low"

    score = _field(fields, "Severity Score")
    score_match = re.search(r"\d+/10", score or value)
    return level, score_match.group() if score_match else SEVERITY_SCORES[level]


def _fallback_action(title, happened):
    """Choose a useful but cautious action from the reported threat category."""
    text = f"{title} {happened}".lower()

    if any(term in text for term in ("actively exploited", "active exploitation", "zero-day", "zero day")):
        return "Identify potentially affected products, review vendor or CISA guidance, and prioritise applicable remediation."
    if any(term in text for term in ("credential", "password", "account compromise")):
        return "Rotate potentially exposed credentials, review authentication activity, and strengthen MFA where applicable."
    if any(term in text for term in ("ransomware", "malware")):
        return "Review affected systems and available indicators, then follow relevant containment guidance."
    if any(term in text for term in ("supply chain", "dependency", "package", "repository")):
        return "Review affected dependencies or packages and relevant software supply-chain security controls."
    if re.search(r"\b(ai|soc)\b", text) or "artificial intelligence" in text:
        return "Review AI usage, access controls, logging, and monitoring relevant to this risk."
    return "Review the source and assess whether your organisation has relevant exposure."


def _safe_source_link(source):
    """Return a Telegram HTML source link only for valid web URLs."""
    match = re.search(r"\((https?://[^)\s]+)\)", source or "")
    url = match.group(1) if match else ""
    parsed_url = urlparse(url)
    if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
        return "Source link unavailable."
    return f'🔗 <a href="{html.escape(url, quote=True)}">Read source</a>'


def _threat_section(threat, is_fallback):
    """Create one mobile-friendly HTML threat section."""
    fields = threat["fields"]
    title = html.escape(threat["title"])
    level, score = _severity(fields)
    icon = SEVERITY_ICONS[level]
    happened = _complete_sentences(_field(fields, "What Happened"))
    why = _complete_sentences(_field(fields, "Why It Matters", "Why it matters"), max_length=220, max_sentences=1)

    if is_fallback:
        action = _fallback_action(threat["title"], happened)
    else:
        action = _complete_sentences(
            _field(fields, "Recommended Action", "Recommended action"),
            max_length=220,
            max_sentences=1,
        )

    return "\n\n".join(
        [
            f"{icon} <b>{level.upper()} · {score}</b>",
            f"<b>{title}</b>",
            f"<b>What happened</b>\n{html.escape(happened)}",
            f"<b>Why it matters</b>\n{html.escape(why)}",
            f"<b>Action</b>\n{html.escape(action)}",
            _safe_source_link(_field(fields, "Source Link", "Original source link")),
        ]
    )


def format_for_telegram(briefing):
    """Create a concise executive HTML brief from the detailed Markdown briefing."""
    threats = _parse_briefing(briefing)
    is_fallback = "Mode: Fallback Analysis" in briefing
    is_validated_ai = "Mode: AI Analysis" in briefing
    if is_fallback:
        analysis_mode = "Rule-based Fallback"
    elif is_validated_ai:
        analysis_mode = "AI-assisted"
    else:
        analysis_mode = "Analysis unavailable"

    header = "\n".join(
        [
            "<b>🛡️ CYBER INTELLIGENCE BRIEF</b>",
            f"{date.today().strftime('%d %b %Y')} · {len(threats)} priority updates",
            f"<b>Analysis:</b> {analysis_mode}",
        ]
    )

    if not threats:
        return f"{header}\n\nNo priority updates were available."

    sections = [header] + [_threat_section(threat, is_fallback) for threat in threats]
    if is_fallback:
        sections.append("<i>Severity is estimated using rule-based analysis.</i>")

    return "\n\n─────────────\n\n".join(sections)


def _split_message(message, limit=TELEGRAM_MESSAGE_LIMIT):
    """Split messages between threat sections before using line-based fallback."""
    sections = message.split("\n\n─────────────\n\n")
    chunks = []
    current_chunk = ""

    for section in sections:
        proposed = f"{current_chunk}\n\n─────────────\n\n{section}" if current_chunk else section
        if len(proposed) <= limit:
            current_chunk = proposed
            continue

        if current_chunk:
            chunks.append(current_chunk)
            current_chunk = ""

        if len(section) <= limit:
            current_chunk = section
            continue

        # This only applies to an unusually long single section. Split on
        # complete lines so normal briefing content is never cut mid-sentence.
        lines = section.splitlines(keepends=True)
        for line in lines:
            if len(current_chunk) + len(line) > limit and current_chunk:
                chunks.append(current_chunk.strip())
                current_chunk = ""
            current_chunk += line

    if current_chunk:
        chunks.append(current_chunk.strip())

    return chunks


def _bot_token():
    """Load the Telegram bot token without exposing it."""
    load_dotenv()
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not bot_token:
        logging.warning("TELEGRAM_BOT_TOKEN is not configured.")
    return bot_token


def _telegram_settings(chat_id=None):
    """Load Telegram settings without exposing their values."""
    bot_token = _bot_token()
    destination_chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID")
    if not bot_token or not destination_chat_id:
        logging.warning("Telegram environment variables are not configured.")
        return None, None
    return bot_token, destination_chat_id


def _send_html_messages(messages, chat_id=None, reply_markup=None):
    """Send already-formatted HTML messages to a Telegram chat."""
    bot_token, destination_chat_id = _telegram_settings(chat_id)
    if not bot_token:
        return False

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    try:
        for index, message in enumerate(messages):
            payload = {
                "chat_id": destination_chat_id,
                "text": message,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            }
            if reply_markup and index == len(messages) - 1:
                payload["reply_markup"] = reply_markup

            response = requests.post(
                url,
                json=payload,
                timeout=10,
            )
            response.raise_for_status()
            result = response.json()
            if not isinstance(result, dict) or not result.get("ok", False):
                logging.warning("Telegram did not accept a message chunk.")
                return False

        return True
    except (requests.RequestException, json.JSONDecodeError) as error:
        logging.warning("Could not send Telegram message: %s", error)
        return False


def send_status_message(message, chat_id):
    """Send a short, safely escaped status or error message to one chat."""
    return _send_html_messages([html.escape(message)], chat_id)


def send_start_message(chat_id):
    """Send the Telegram-first welcome message and briefing controls."""
    message = (
        "<b>🛡️ Cyber Intelligence Assistant</b>\n\n"
        "Choose the number of priority updates to generate, or send /help "
        "to view available commands."
    )
    return _send_html_messages([message], chat_id, reply_markup=BRIEFING_CONTROLS)


def send_to_telegram(message, chat_id=None, show_controls=False):
    """Format and send a briefing to the configured or supplied Telegram chat."""
    if not message:
        logging.warning("Telegram message is empty.")
        return False

    formatted_messages = _split_message(format_for_telegram(message))
    controls = BRIEFING_CONTROLS if show_controls else None
    return _send_html_messages(formatted_messages, chat_id, reply_markup=controls)


def answer_callback_query(callback_query_id):
    """Dismiss Telegram's inline-button loading indicator."""
    bot_token = _bot_token()
    if not bot_token or not callback_query_id:
        logging.warning("Cannot acknowledge Telegram callback query: configuration or ID is missing.")
        return False

    try:
        response = requests.post(
            f"https://api.telegram.org/bot{bot_token}/answerCallbackQuery",
            json={"callback_query_id": callback_query_id},
            timeout=10,
        )
        response.raise_for_status()
        accepted = bool(response.json().get("ok", False))
        if accepted:
            logging.info("Telegram accepted callback acknowledgement.")
        else:
            logging.error("Telegram rejected callback acknowledgement.")
        return accepted
    except (requests.RequestException, ValueError) as error:
        logging.warning("Could not answer Telegram callback query: %s", error)
        return False


if __name__ == "__main__":
    from news_fetcher import fetch_news
    from ai_summarizer import generate_briefing

    print("Sending a formatted Telegram briefing...")
    if send_to_telegram(generate_briefing(fetch_news())):
        print("Telegram briefing sent successfully.")
    else:
        print("Telegram briefing delivery failed. Check your .env settings.")
