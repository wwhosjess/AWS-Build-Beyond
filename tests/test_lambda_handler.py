"""Unit tests for Lambda webhook routing and secret validation."""

import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from src import lambda_handler as handler_module


TEST_SECRET = "test-webhook-secret"


def api_gateway_event(update, headers=None):
    """Create a realistic API Gateway HTTP API v2 webhook event."""
    return {
        "version": "2.0",
        "rawPath": "/telegram/webhook",
        "requestContext": {
            "http": {"method": "POST", "path": "/telegram/webhook"}
        },
        "headers": headers or {},
        "body": json.dumps(update),
        "isBase64Encoded": False,
    }


def command_update():
    return {"message": {"chat": {"id": 12345}, "text": "/brief 3"}}


def callback_update():
    return {
        "callback_query": {
            "id": "callback-test-id",
            "data": "brief:5",
            "message": {"chat": {"id": 12345}},
        }
    }


class TelegramWebhookSecretTests(unittest.TestCase):
    """Ensure API Gateway events fail closed before their body is parsed."""

    def setUp(self):
        self.environment = patch.dict(
            os.environ, {"TELEGRAM_WEBHOOK_SECRET": TEST_SECRET}
        )
        self.environment.start()
        self.context = SimpleNamespace(
            invoked_function_arn="arn:aws:lambda:ap-southeast-1:123:function:bot"
        )

    def tearDown(self):
        self.environment.stop()

    def test_valid_webhook_secret_accepts_message(self):
        event = api_gateway_event(
            command_update(),
            {"X-Telegram-Bot-Api-Secret-Token": TEST_SECRET},
        )
        with patch.object(handler_module, "_invoke_async", return_value=True) as invoke:
            response = handler_module.lambda_handler(event, self.context)

        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(json.loads(response["body"]), {"status": "accepted"})
        self.assertEqual(invoke.call_args.args[0]["kind"], "command")

    def test_missing_webhook_secret_is_rejected_before_body_parsing(self):
        with patch.object(handler_module, "_parse_webhook_update") as parse_update:
            response = handler_module.lambda_handler(
                api_gateway_event(command_update()), self.context
            )

        self.assertEqual(response["statusCode"], 403)
        parse_update.assert_not_called()

    def test_missing_configured_webhook_secret_fails_closed(self):
        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(handler_module, "_parse_webhook_update") as parse_update,
        ):
            response = handler_module.lambda_handler(
                api_gateway_event(
                    command_update(),
                    {"x-telegram-bot-api-secret-token": TEST_SECRET},
                ),
                self.context,
            )

        self.assertEqual(response["statusCode"], 403)
        parse_update.assert_not_called()

    def test_incorrect_webhook_secret_is_rejected_before_body_parsing(self):
        with patch.object(handler_module, "_parse_webhook_update") as parse_update:
            response = handler_module.lambda_handler(
                api_gateway_event(
                    command_update(),
                    {"x-telegram-bot-api-secret-token": "incorrect-secret"},
                ),
                self.context,
            )

        self.assertEqual(response["statusCode"], 403)
        parse_update.assert_not_called()

    def test_callback_query_is_acknowledged_after_secret_validation(self):
        event = api_gateway_event(
            callback_update(),
            {"X-TELEGRAM-BOT-API-SECRET-TOKEN": TEST_SECRET},
        )
        with (
            patch.object(handler_module, "answer_callback_query", return_value=True) as answer,
            patch.object(handler_module, "_invoke_async", return_value=True) as invoke,
        ):
            response = handler_module.lambda_handler(event, self.context)

        self.assertEqual(response["statusCode"], 200)
        answer.assert_called_once_with("callback-test-id")
        self.assertEqual(invoke.call_args.args[0], {
            "kind": "callback",
            "chat_id": 12345,
            "data": "brief:5",
        })

    def test_scheduled_event_is_unaffected_by_webhook_validation(self):
        with patch.object(handler_module, "run_daily_briefing", return_value=True) as daily:
            response = handler_module.lambda_handler(
                {"action": "daily_briefing"}, SimpleNamespace()
            )

        self.assertEqual(response, {"status": "ok"})
        daily.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
