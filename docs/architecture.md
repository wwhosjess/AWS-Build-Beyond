# Architecture

## Components

```text
Telegram user
    │ /start, /brief, inline button callback
    ▼
API Gateway HTTP API
POST /telegram/webhook
    ▼
AWS Lambda: src.lambda_handler.lambda_handler
    ├── validates Telegram webhook secret
    ├── queues command work through an asynchronous Lambda invocation
    ▼
Shared briefing pipeline
RSS feeds → normalisation → candidate pool → prioritisation → analysis → Telegram HTML
                                                    │
                                     OpenAI Responses API or rule-based fallback

EventBridge Scheduler (07:30 Asia/Singapore)
    ▼
Same Lambda → daily workflow → DynamoDB sent-article state → Telegram
```

## User-triggered workflow

1. Telegram delivers a message or `callback_query` to `POST /telegram/webhook`.
2. Lambda verifies `X-Telegram-Bot-Api-Secret-Token` before decoding the body.
3. The webhook path acknowledges an inline callback with `answerCallbackQuery` and asynchronously invokes the same Lambda for the command work.
4. `telegram_bot.py` validates `/brief` counts from 1 to 10 and calls `briefing_service.generate_and_send_briefing`.
5. The service fetches a candidate pool, analyses up to the requested count, formats the result as Telegram HTML, and sends it to the originating chat.

Manual requests intentionally do not filter already-sent scheduled items: they are meant to show the current latest news.

## Scheduled workflow

1. EventBridge Scheduler invokes the Lambda with `{"action":"daily_briefing"}` at 07:30 in the `Asia/Singapore` timezone.
2. `daily_brief.py` fetches a larger candidate pool and asks the sent-article store for unseen URLs.
3. The shared briefing service ranks, analyses, formats, and sends up to `DEFAULT_BRIEF_COUNT` updates, defaulting to three.
4. After Telegram confirms delivery, included source URLs are recorded in DynamoDB.

If fewer than three unseen articles are available, the daily job sends fewer rather than resending prior scheduled items merely to fill the count.

## AI and resilience branch

```text
Articles → OpenAI Responses API (gpt-4.1-mini)
               │
               ├── valid count + required fields → AI-assisted briefing
               └── missing key, API failure, empty/malformed output → Rule-based Fallback
```

AI output must contain the requested number of Markdown entries and the expected briefing fields. The application does not label a result AI-assisted until this validation succeeds.

## DynamoDB state flow

The production store uses a DynamoDB table selected by `SENT_ARTICLES_TABLE`. The partition key is `article_id` (String), using the article URL as a stable identifier. Each successful scheduled item records `article_id`, `article_url`, and `sent_at`.

For local-only use with no table configured, the app falls back to `data/sent_articles.json`. This is deliberately not durable in serverless production and is ignored by Git.
