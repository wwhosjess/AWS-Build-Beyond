# Cyber Intelligence Assistant

Cybersecurity news moves quickly, but not every headline deserves the same attention.

I built a Telegram-based cyber intelligence assistant that collects current security news, prioritises the most relevant updates, and turns them into short, actionable briefings.

Users can request 3, 5, or 10 updates on demand, while an AWS serverless workflow automatically delivers a daily briefing at 07:30 Singapore time.

When OpenAI is available, the assistant produces AI-assisted analysis. If the AI service fails or returns invalid output, the system falls back to deterministic rule-based analysis instead of failing completely.

Built for the **AWS Build Beyond: Student AI Demo Challenge 2026**.

## Participant

Jesslyn Tan

## Demo

▶️ **[AWS Build Beyond - Cyber Intelligence Assistant](https://youtu.be/SuqBCV1xUqA)**

The demo shows:

- an on-demand `/brief 3` request
- AI-assisted analysis
- 3 / 5 / 10 update controls
- the scheduled briefing workflow
- rule-based fallback when the AI service is unavailable
- the AWS architecture behind the workflow

## Why I built it

Security information is spread across many sources, and the challenge is deciding what deserves attention before spending time on every article.

The goal is to reduce first-pass reading time by turning several RSS items into a source-linked Telegram brief.

## What it does

- Collects and normalises recent cybersecurity articles from The Hacker News and BleepingComputer RSS feeds.
- Builds a candidate pool from fetched articles, then uses AI selection or deterministic fallback ranking.
- Produces AI-assisted analysis with OpenAI `gpt-4.1-mini` through the Responses API.
- Validates AI entry count and required fields before accepting model output.
- Uses deterministic `Rule-based Fallback` when OpenAI is unavailable or returns invalid output.
- Delivers concise Telegram briefings with source links.
- Supports `/start`, `/help`, `/brief`, `/brief 3`, `/brief 5`, `/brief 10`, and inline controls.
- Runs an automatic 07:30 Asia/Singapore briefing through EventBridge Scheduler.
- Uses DynamoDB state to reduce repeated articles in scheduled briefings.
- Produces CloudWatch diagnostics for operational and AI-stage failures.

## Architecture

```text
Telegram
   │
   ▼
API Gateway HTTP API
POST /telegram/webhook
   │
   ▼
AWS Lambda
   │
   ├── RSS → normalise → candidate pool
   │                                │
   │                 AI selection / fallback ranking
   │                                      │
   └──────────────────────────────────────▼
                                      Telegram

EventBridge Scheduler
        │
        ▼
      Lambda
        │
        ▼
    DynamoDB
```

The same Lambda supports both interactive and scheduled workflows.

### Interactive path

```text
Telegram
→ API Gateway
→ Lambda
→ RSS collection
→ candidate pool
→ AI selection or fallback ranking
→ Telegram
```

### Scheduled path

```text
EventBridge Scheduler
→ Lambda
→ RSS collection
→ duplicate filtering with DynamoDB
→ AI selection or fallback ranking
→ Telegram
→ persist delivered article state
```

See [`docs/architecture.md`](docs/architecture.md) for the detailed flows.

### Why these AWS services

| Service | Why it is used |
| --- | --- |
| API Gateway HTTP API | Provides the public HTTPS webhook endpoint Telegram can call. |
| AWS Lambda | Runs the workflow only when triggered, avoiding a continuously running server. |
| EventBridge Scheduler | Triggers the daily briefing automatically at 07:30 Asia/Singapore. |
| DynamoDB | Stores sent-article state for scheduled duplicate prevention. |
| CloudWatch Logs | Provides operational visibility and AI-stage diagnostics. |

The target runtime is Python 3.11 x86_64.

Lambda handler:

```text
src.lambda_handler.lambda_handler
```

## Intelligence pipeline

```text
RSS
→ Normalise
→ Candidate Pool
→ Prioritise
→ Analyse
→ Actionable Brief
```

### RSS

Raw cybersecurity articles are collected from configured feeds.

### Normalise

Different RSS feeds structure their content differently, so each article is converted into a common internal format.

### Candidate pool

The system collects more articles than it ultimately returns.

For example:

```text
/brief 3  → fetch 10 candidates → return top 3
/brief 5  → fetch 15 candidates → return top 5
/brief 10 → fetch 30 candidates → return top 10
```

This keeps the requested output count separate from the amount of material considered.

### Selection and fallback ranking

The candidate pool is the set of fetched, normalised articles. OpenAI receives that pool and selects the requested briefing entries; it does not search the wider internet.

If OpenAI is unavailable or its output fails validation, the deterministic fallback orders the same candidate pool with keyword indicators such as critical vulnerability, active exploitation, ransomware, malware, breach, and credentials.

### Analyse

Selected articles are converted into concise intelligence containing:

- severity
- what happened
- why it matters
- recommended action
- source link

## Responsible AI and resilience

OpenAI is an optional analysis layer, not a delivery dependency. The model is instructed to use only the supplied candidate pool. Its output is accepted only when it is non-empty, returns the requested number of entries, and includes every required field.

Empty, malformed, wrong-count, or failed API responses—including HTTP 429—use the keyword-based deterministic fallback instead. Telegram labels validated model output as `AI-assisted` and fallback output as `Rule-based Fallback`. The application does not invent additional articles to satisfy a requested count, and source links remain available for verification.

## Security

Telegram webhook requests are authenticated before their content is processed.

- Secrets are provided through environment variables rather than committed files.
- Telegram requests require `TELEGRAM_WEBHOOK_SECRET`.
- The `X-Telegram-Bot-Api-Secret-Token` header is validated before parsing the request body.
- Secret comparison uses `hmac.compare_digest`.
- Missing or invalid webhook secrets return HTTP 403.
- The webhook fails closed if its expected secret is not configured.
- `.env`, deployment ZIPs, local state, logs, and credentials are excluded from Git.
- Diagnostic logging avoids printing API keys, Telegram tokens, webhook secrets, or full payloads.

See [`docs/security.md`](docs/security.md) for the threat surface, controls, and current limitations.

## Telegram commands

| Input | Result |
| --- | --- |
| `/start` | Displays controls for 3, 5, 10, or refreshed updates. |
| `/brief` | Generates the default three priority updates. |
| `/brief 3` | Generates three updates. |
| `/brief 5` | Generates five updates. |
| `/brief 10` | Generates ten updates. |
| `/brief 1-10` | Generates a chosen number of priority updates. |
| `/help` | Displays available commands. |

Inline buttons use:

```text
brief:3
brief:5
brief:10
brief:refresh
```

Callback queries are acknowledged before longer briefing work is processed.

## Engineering lessons

Getting the first briefing to work was only part of the project. Most of the useful engineering work came from integration failures across service boundaries.

| Issue | What changed |
| --- | --- |
| Telegram buttons kept spinning | Added explicit callback acknowledgement and callback-query handling. |
| Button events were not reaching Lambda | Added `callback_query` to Telegram `allowed_updates`. |
| `/brief 10` returned only five articles | Separated candidate-pool size from requested output size. |
| OpenAI returned HTTP 429 | Added deterministic fallback so delivery still succeeds. |
| Webhook endpoint accepted unauthenticated Telegram-shaped requests | Added Telegram secret-token validation before body processing. |
| Lambda deployment issues were hard to diagnose | Added explicit runtime and AI-stage diagnostics in CloudWatch. |

These failures shaped the final design more than the happy path did.

## Testing

The unittest suite covers:

- valid Telegram webhook secret;
- missing webhook secret;
- incorrect webhook secret;
- callback-query acknowledgement after validation;
- EventBridge scheduled events remaining outside webhook validation;
- valid AI output labelled as AI-assisted;
- OpenAI 429 fallback;
- empty AI output fallback;
- malformed AI output fallback;
- wrong-count AI output fallback.

Run:

```powershell
python -m unittest discover -s tests -v
```

## Local setup

1. Create and activate a virtual environment.

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

2. Install local development dependencies.

   ```powershell
   pip install -r requirements-dev.txt
   ```

3. Copy `.env.example` to `.env` and replace placeholders with your own values. Do not commit `.env`.

4. Run tests.

   ```powershell
   python -m unittest discover -s tests -v
   ```

5. Optionally run a scheduled briefing locally.

   ```powershell
   python -m src.daily_brief
   ```

This sends a real Telegram message when configured with valid credentials.

## Environment variables

```text
TELEGRAM_BOT_TOKEN=<your-telegram-bot-token>
TELEGRAM_CHAT_ID=<your-chat-id>
TELEGRAM_WEBHOOK_SECRET=<generate-a-random-secret>
SENT_ARTICLES_TABLE=<your-dynamodb-table-name>

# Optional: rule-based fallback remains available without this.
OPENAI_API_KEY=<your-openai-api-key>

DEFAULT_BRIEF_COUNT=3
TIMEZONE=Asia/Singapore
```

For Lambda deployment, use the runtime-provided boto3 SDK rather than bundling it into the deployment package. `requirements-dev.txt` includes boto3 for local testing only.

## Deployment outline

This repository contains application code rather than infrastructure-as-code.

1. Create a Python 3.11 x86_64 Lambda.
2. Set the handler to:

   ```text
   src.lambda_handler.lambda_handler
   ```

3. Create an API Gateway HTTP API route:

   ```text
   POST /telegram/webhook
   ```

4. Create a DynamoDB table with `article_id` as the String partition key.
5. Configure EventBridge Scheduler:

   ```text
   cron(30 7 * * ? *)
   ```

   with timezone `Asia/Singapore` and target input:

   ```json
   {"action":"daily_briefing"}
   ```

6. Configure the required environment variables.
7. Register Telegram's webhook with `message` and `callback_query` in `allowed_updates`, plus a matching `secret_token`.

The Lambda execution role requires CloudWatch Logs permissions, DynamoDB `GetItem` and `PutItem` permissions scoped to the configured table, and permission to invoke the Lambda asynchronously. The EventBridge Scheduler execution role requires permission to invoke the Lambda.

## Current limitations

This is a working student prototype, not a full threat-intelligence platform.

- RSS coverage is limited to two sources.
- Threat ranking is heuristic and keyword-based before AI analysis.
- Duplicate prevention is URL-based and intentionally simple.
- AI quality and availability depend on an external API.
- No infrastructure-as-code is included yet.
- No CI/CD pipeline is included yet.
- No direct CVE, CVSS, or CISA KEV enrichment is currently performed.

## Possible next iteration

- Add CISA KEV enrichment.
- Add CVE and CVSS context.
- Introduce source-trust scoring.
- Add more RSS and advisory sources.
- Use structured AI output with schema validation.
- Add SAM, CDK, or Terraform.
- Add CI/CD, dependency scanning, and automated secret scanning.
- Add CloudWatch metrics and alarms.

## Repository structure

```text
cyber-intelligence-assistant/
├── assets/
├── docs/
│   ├── architecture.md
│   └── security.md
├── src/
├── tests/
├── .env.example
├── .gitignore
├── LICENSE
├── README.md
├── requirements-dev.txt
└── requirements.txt
```

## License

MIT License.

Copyright (c) 2026 Jesslyn Tan
