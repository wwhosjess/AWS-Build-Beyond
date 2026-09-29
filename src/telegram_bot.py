"""Parse Telegram commands and invoke the shared briefing pipeline."""

import logging

try:
    from .briefing_service import (
        DEFAULT_TOP_N,
        MAX_TOP_N,
        MIN_TOP_N,
        generate_and_send_briefing,
    )
    from .telegram_sender import send_start_message, send_status_message
except ImportError:
    # Supports running the file directly with: python src\telegram_bot.py
    from briefing_service import (
        DEFAULT_TOP_N,
        MAX_TOP_N,
        MIN_TOP_N,
        generate_and_send_briefing,
    )
    from telegram_sender import send_start_message, send_status_message


logger = logging.getLogger(__name__)
HELP_MESSAGE = """Cyber Intelligence Assistant commands:
/start - Show briefing buttons
/brief - Generate 3 priority updates
/brief 1-10 - Generate a chosen number of priority updates
/help - Show this help message"""

CALLBACK_COMMANDS = {
    "brief:3": "/brief 3",
    "brief:5": "/brief 5",
    "brief:10": "/brief 10",
    "brief:refresh": "/brief",
}


def _brief_count(command_text):
    """Validate a /brief command and return its requested update count."""
    parts = command_text.strip().split()
    command = parts[0].split("@", 1)[0].lower()

    if command != "/brief":
        return None
    if len(parts) == 1:
        return DEFAULT_TOP_N
    if len(parts) != 2 or not parts[1].isdigit():
        return False

    count = int(parts[1])
    if not MIN_TOP_N <= count <= MAX_TOP_N:
        return False
    return count


def handle_command(chat_id, command_text):
    """Handle one Telegram command without duplicating the backend pipeline."""
    command = command_text.strip().split(maxsplit=1)[0].split("@", 1)[0].lower()
    if command == "/start":
        send_start_message(chat_id)
        return
    if command == "/help":
        send_status_message(HELP_MESSAGE, chat_id)
        return

    top_n = _brief_count(command_text)
    if top_n is False:
        send_status_message("Please choose between 1 and 10 updates.", chat_id)
        return
    if top_n is None:
        send_status_message("Unknown command. Send /help to see available commands.", chat_id)
        return

    logger.info("Requested briefing count: %s", top_n)
    send_status_message("Fetching and analysing the latest cybersecurity updates...", chat_id)
    try:
        delivered = generate_and_send_briefing(
            top_n=top_n, chat_id=chat_id, show_controls=True
        )
        if not delivered:
            logger.error("Briefing generation or delivery failed (top_n=%s).", top_n)
            send_status_message("I could not generate a briefing right now. Please try again later.", chat_id)
            return
        logger.info("Briefing generation and delivery succeeded (top_n=%s).", top_n)
    except Exception:
        logger.exception("Telegram command failed (top_n=%s).", top_n)
        send_status_message("I could not generate a briefing right now. Please try again later.", chat_id)


def handle_callback(chat_id, callback_data):
    """Handle an inline briefing control using the existing command pipeline."""
    logger.info("Callback query received with data: %s", callback_data)
    command_text = CALLBACK_COMMANDS.get(callback_data)
    if not command_text:
        logger.warning("Unsupported callback data: %s", callback_data)
        send_status_message("This button is no longer available. Send /brief instead.", chat_id)
        return

    logger.info("Callback requested briefing count: %s", _brief_count(command_text))
    handle_command(chat_id, command_text)
