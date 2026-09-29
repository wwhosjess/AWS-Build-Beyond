# Security and Responsible AI

## Threat surface

The service accepts public webhook traffic, calls external RSS, OpenAI, and Telegram APIs, and persists scheduled-delivery state. The main controls are input validation, environment-based secrets, least-privilege IAM, and graceful failure handling.

## Telegram webhook authentication

API Gateway is public by design for Telegram delivery; Lambda validates Telegram’s configured secret header before parsing the request.

Telegram is registered with a webhook secret token. It sends that value in the `X-Telegram-Bot-Api-Secret-Token` header. `lambda_handler.py` lowercases inbound header names and uses `hmac.compare_digest` to compare the supplied and configured values.

Validation happens after confirming `POST /telegram/webhook` and before body parsing. The Lambda fails closed with HTTP 403 if `TELEGRAM_WEBHOOK_SECRET` is missing, absent from the request, or incorrect. EventBridge and internal asynchronous Lambda events do not pass through webhook validation.

## Secrets handling

Production secrets are environment variables, never source-controlled files:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `TELEGRAM_WEBHOOK_SECRET`
- `OPENAI_API_KEY` (optional)
- `SENT_ARTICLES_TABLE`

`.env` is ignored. `.env.example` contains placeholders only. Logging must not include keys, tokens, secret headers, or full webhook bodies.

## Least-privilege considerations

The Lambda execution role should permit CloudWatch log writes, DynamoDB `GetItem`/`PutItem` on the configured sent-articles table, and `lambda:InvokeFunction` on itself for asynchronous command processing. The EventBridge Scheduler role needs permission to invoke that Lambda. Scope these permissions to the specific function and table wherever possible.

## External dependencies and resilience

RSS feeds, OpenAI, and Telegram are external dependencies. A feed failure is isolated per source. OpenAI failures—including a missing key, quota errors, model errors, network errors, empty output, or invalid output structure—fall back to deterministic rule-based analysis. Telegram delivery errors are logged and reported without exposing credentials.

## Responsible AI

The model is instructed to use only supplied article content and not invent missing facts. Its output is checked for the requested number of entries and required fields before it is accepted. Telegram labels validated model output as `AI-assisted`; deterministic results are labelled `Rule-based Fallback`.

## Current security limitations

This repository does not include infrastructure-as-code, CI/CD secret scanning, a formal threat model, source-signature verification, or automated dependency scanning. These are appropriate next steps before a broader production rollout.
