# MEV Report Demo

AI-powered MEV analysis report generator. Enter a transaction hash, pick an LLM provider, and receive a structured report — **Conclusion**, **Token Flow Chart**, and **EigenTx Mermaid diagram** — streamed live in the browser.

## How it works

```
Browser (tx hash + LLM config)
  │
  ▼
app.py (local Python server)
  ├─► MEVScan MCP (SSE)  ──►  raw MEV JSON
  └─► LLM API (streaming) ──► markdown report
  │
  ▼
Browser renders report (marked.js + mermaid.js)
```

1. The browser sends a `POST /report` with the tx hash and LLM credentials.
2. The server fetches MEV detail from the MEVScan MCP endpoint via SSE protocol.
3. The raw MEV JSON is forwarded to the chosen LLM, which generates a structured report.
4. The LLM response is streamed back to the browser via SSE and rendered as markdown.

## Requirements

- Python 3.10+
- A **MEVScan API Key** (set in `.env`)
- An API key for at least one LLM provider (entered in the browser UI at runtime)

## Quick start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Configure environment
cp .env.example .env
# Edit .env — set MEVSCAN_URL and MEVSCAN_TOKEN

# 3. Start the server
python app.py
# → http://localhost:5001
```

Open `http://localhost:5001` in your browser, enter a tx hash and your LLM API key, then click **Generate Report**.

## Environment variables

| Variable       | Default                  | Description                        |
|----------------|--------------------------|------------------------------------|
| `MEVSCAN_URL`  | `https://eigenphi.com`   | MEVScan server base URL            |
| `MEVSCAN_TOKEN`| *(required)*             | Your MEVScan API key               |
| `LOCAL_HOST`   | `127.0.0.1`              | Server bind address                |
| `LOCAL_PORT`   | `5001`                   | Server port                        |

## Supported LLM providers

| Provider  | Default model        | API base URL                                                    |
|-----------|----------------------|-----------------------------------------------------------------|
| `claude`  | claude-opus-4-5      | https://api.anthropic.com                                       |
| `gpt`     | gpt-4o               | https://api.openai.com/v1                                       |
| `gemini`  | gemini-2.0-flash     | https://generativelanguage.googleapis.com/v1beta/openai/        |
| `deepseek`| deepseek-chat        | https://api.deepseek.com                                        |
| `qwen`    | qwen-plus            | https://dashscope.aliyuncs.com/compatible-mode/v1               |

You can override the model name and base URL in the browser UI.

## Report format

The generated report contains three sections:

**Conclusion** — 2-4 sentences covering MEV type, profit/cost ratio, protocols involved, and notable observations.

**Facts**
- *Summary table* — block, timestamp, tx hash, from/to, revenue, cost, profit.
- *Token Flow Chart* — per-address net balance changes as a pivot table, with roles tagged (Searcher / Pool / Builder).

**EigenTx** — a `graph LR` Mermaid diagram visualising token transfers between addresses.

## Project structure

```
mev-report/
├── app.py            # Starlette server: MCP fetch + LLM streaming
├── index.html        # Single-page browser UI
├── requirements.txt  # Python dependencies
├── SKILL.md          # LLM system-prompt / report format spec
└── .env.example      # Environment variable template
```

## API endpoints

| Method | Path        | Description                                      |
|--------|-------------|--------------------------------------------------|
| GET    | `/`         | Browser UI                                       |
| GET    | `/providers`| Returns default model/base_url per provider      |
| POST   | `/report`   | Streams MEV fetch + LLM report as SSE            |
| GET    | `/health`   | Health check → `{"status":"ok"}`                 |

### POST /report — request body

```json
{
  "tx_hash":  "0xabc...",
  "provider": "claude",
  "api_key":  "sk-...",
  "model":    "claude-opus-4-5",
  "base_url": ""
}
```

### POST /report — SSE event types

| Event type | Payload                        |
|------------|--------------------------------|
| `mev_data` | `{ "data": { ... } }` — raw MEV JSON |
| `delta`    | `{ "text": "..." }` — LLM token chunk |
| `done`     | `{}` — stream finished         |
| `error`    | `{ "message": "..." }` — error |
