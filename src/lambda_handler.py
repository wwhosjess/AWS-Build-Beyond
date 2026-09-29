"""AWS Lambda entry point for Telegram webhooks and EventBridge Scheduler."""

import base64
import hmac
import json
import logging
import os

import boto3

try:
    from .daily_brief import run_daily_briefing
    from .telegram_bot import handle_callback, handle_command
    from .telegram_sender import answer_callback_query
except ImportError:  # Supports local Lambda handler tests
    from daily_brief import run_daily_briefing
    from telegram_bot import handle_callback, handle_command
    from telegram_sender import answer_callback_query


logger = logging.getLogger(__name__)
DAILY_EVENT_ACTION = "daily_briefing"
TELEGRAM_JOB_ACTION = "telegram_job"


def _http_response(status_code: int, body: dict) -> dict:
    """Create an API Gateway HTTP API-compatible JSON response."""
    return {
        "statusCode": status_code,
        "headers": {"content-type": "application/json"},
        "body": json.dumps(body),
    }


def _is_api_gateway_event(event: dict) -> bool:
    """Recognise API Gateway HTTP API proxy events without logging their body."""
    return isinstance(event.get("requestContext"), dict) and "http" in event["requestContext"]


def _webhook_request_details(event: dict) -> tuple[object, object]:
    """Read HTTP API v2 request details, tolerating equivalent path fields."""
    http = event.get("requestContext", {}).get("http", {})
    method = http.get("method")
    path = event.get("rawPath") or http.get("path") or event.get("path")
    return method, path


def _parse_webhook_update(event: dict) -> dict | None:
    """Parse an API Gateway body into a Telegram update dictionary."""
    body = event.get("body", "")
    if body is None:
        return None
    if event.get("isBase64Encoded") and isinstance(body, str):
        try:
            body = base64.b64decode(body).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            logger.warning("Could not base64-decode the API Gateway webhook body.")
            return None

    try:
        update = json.loads(body) if isinstance(body, str) else body
    except json.JSONDecodeError:
        logger.warning("Could not JSON-decode the API Gateway webhook body.")
        return None
    return update if isinstance(update, dict) else None


def _valid_telegram_webhook_secret(event: dict) -> bool:
    """Validate the configured Telegram webhook secret without logging it."""
    expected_secret = os.getenv("TELEGRAM_WEBHOOK_SECRET")
    if not expected_secret:
        logger.error("TELEGRAM_WEBHOOK_SECRET is not configured; rejecting webhook request.")
        return False

    headers = event.get("headers")
    normalized_headers = {
        str(name).lower(): value
        for name, value in headers.items()
    } if isinstance(headers, dict) else {}
    received_secret = normalized_headers.get("x-telegram-bot-api-secret-token")

    return isinstance(received_secret, str) and hmac.compare_digest(
        received_secret, expected_secret
    )


def _telegram_job(update: dict) -> dict | None:
    """Extract a safe command job from a Telegram message or inline button."""
    callback_query = update.get("callback_query")
    if isinstance(callback_query, dict):
        logger.info("Callback query received.")
        callback_message = callback_query.get("message")
        chat = callback_message.get("chat") if isinstance(callback_message, dict) else None
        chat_id = chat.get("id") if isinstance(chat, dict) else None
        callback_data = callback_query.get("data")
        callback_id = callback_query.get("id")
        logger.info("Callback data: %s", callback_data)
        if callback_id:
            if answer_callback_query(callback_id):
                logger.info("Callback acknowledged.")
            else:
                logger.error("Callback acknowledgement failed.")
        else:
            logger.warning("Callback query did not include an acknowledgement ID.")
        if chat_id and isinstance(callback_data, str):
            return {"kind": "callback", "chat_id": chat_id, "data": callback_data}
        logger.warning("Callback query did not include usable chat or callback data.")
        return None

    message = update.get("message")
    chat = message.get("chat") if isinstance(message, dict) else None
    chat_id = chat.get("id") if isinstance(chat, dict) else None
    text = message.get("text") if isinstance(message, dict) else None
    if chat_id and isinstance(text, str) and text.startswith("/"):
        return {"kind": "command", "chat_id": chat_id, "text": text}
    return None


def _run_telegram_job(job: dict) -> None:
    """Run an already-validated Telegram command through existing handlers."""
    if job.get("kind") == "callback":
        logger.info("Processing callback briefing request: %s", job.get("data"))
        handle_callback(job["chat_id"], job["data"])
    elif job.get("kind") == "command":
        logger.info("Processing Telegram command request.")
        handle_command(job["chat_id"], job["text"])


def _invoke_async(job: dict, context) -> bool:
    """Queue a command in the same Lambda so API Gateway can respond quickly."""
    function_arn = getattr(context, "invoked_function_arn", None)
    if not function_arn:
        return False

    try:
        boto3.client("lambda").invoke(
            FunctionName=function_arn,
            InvocationType="Event",
            Payload=json.dumps({"action": TELEGRAM_JOB_ACTION, "job": job}).encode("utf-8"),
        )
        logger.info("Telegram command job queued for asynchronous processing.")
        return True
    except Exception:
        logger.exception("Could not queue Telegram command for asynchronous processing.")
        return False


def _handle_event(event, context):
    """Route API Gateway, EventBridge, and asynchronous command events."""
    if not isinstance(event, dict):
        logger.warning("Received an unsupported Lambda event.")
        return _http_response(400, {"status": "ignored"})

    action = event.get("action")
    if action == DAILY_EVENT_ACTION:
        delivered = run_daily_briefing()
        return {"status": "ok" if delivered else "failed"}

    if action == TELEGRAM_JOB_ACTION:
        job = event.get("job")
        if isinstance(job, dict):
            try:
                _run_telegram_job(job)
                return {"status": "ok"}
            except Exception:
                logger.exception("Telegram command job failed.")
        return {"status": "ignored"}

    if _is_api_gateway_event(event):
        method, path = _webhook_request_details(event)
        logger.info(
            "Webhook invocation received: type=api_gateway_http_api_v2 method=%s path=%s.",
            method,
            path,
        )
        if method != "POST" or path != "/telegram/webhook":
            logger.warning("Ignoring API Gateway request with an unsupported method or path.")
            return _http_response(404, {"status": "not_found"})

        if not _valid_telegram_webhook_secret(event):
            logger.warning("Rejected Telegram webhook with a missing or invalid secret.")
            return _http_response(403, {"status": "forbidden"})

        update = _parse_webhook_update(event)
        if not update:
            logger.warning("Webhook invocation did not contain a usable Telegram update.")
            return _http_response(400, {"status": "ignored"})

        update_type = "callback_query" if isinstance(update.get("callback_query"), dict) else "message" if isinstance(update.get("message"), dict) else "other"
        callback_data = (
            update["callback_query"].get("data")
            if update_type == "callback_query"
            else None
        )
        logger.info(
            "Telegram update parsed: type=%s callback_data=%s.",
            update_type,
            callback_data,
        )

        job = _telegram_job(update)
        if not job:
            return _http_response(200, {"status": "ignored"})

        if getattr(context, "invoked_function_arn", None):
            if _invoke_async(job, context):
                return _http_response(200, {"status": "accepted"})
            return _http_response(500, {"status": "failed"})

        # The synchronous fallback keeps local handler tests usable. In AWS,
        # context contains the function ARN and uses the asynchronous path.
        try:
            _run_telegram_job(job)
            return _http_response(200, {"status": "ok"})
        except Exception:
            logger.exception("Telegram webhook command failed.")
            return _http_response(500, {"status": "failed"})

    logger.warning("Received an unrecognised Lambda event.")
    return {"status": "ignored"}


def lambda_handler(event, context):
    """AWS Lambda entry point: src.lambda_handler.lambda_handler."""
    return _handle_event(event, context)


__all__ = ["lambda_handler"]
