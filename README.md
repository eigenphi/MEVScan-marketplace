# MEVScan Marketplace

> A community-driven collection of apps built on top of the [MEVScan](https://eigenphi.com/) API.

[EigenPhi](https://eigenphi.com/) is a professional MEV (Maximal Extractable Value) intelligence platform that tracks, classifies, and quantifies MEV activity across Ethereum and other EVM chains — including arbitrage, sandwich attacks, liquidations, and JIT liquidity events.

This repository is the **MEVScan Marketplace**: an open collection of demo apps and community-built tools that showcase what you can build with the MEVScan API. Every app here can be run locally within minutes.

---

## License

All apps in this repository are released under the [MIT License](LICENSE).

---

## Contributing

We welcome pull requests!

- **Submit a new app** — add a new directory with a `README.md` and working code.
- **Improve an existing app** — bug fixes, new features, better UX.

Every merged contribution earns **MEVScan points** as a reward. Points are tracked per contributor and redeemable for platform perks.

Please open an issue first if you plan a large change, so we can coordinate before you invest the effort.

---

## Apps

### 1. [MEV Live Stream](./livestream/)

A local Python app that connects to the MEVScan SSE push service and displays real-time MEV events in a browser dashboard.

**Highlights**

| Feature | Detail                                       |
|---------|----------------------------------------------|
| Event types | Arbitrage, Sandwich, Liquidation, JIT        |
| Display | Newest 500 events, auto-updating table       |
| Controls | Pause / Resume (buffers events while paused) |
| Filtering | Address filter for targeted monitoring       |
| Resilience | Auto-reconnect with exponential backoff      |
| Runtime | Python 3.10+ · `localhost:5000`              |

**How it works**

```
Browser (index.html)
    ↕ WebSocket  ws://localhost:8080/ws
Python proxy (app.py)
    ↕ SSE + Bearer Token
MEVScan server
```

→ [Full documentation](./livestream/README.md)

---

### 2. [MEV Report](./mev-report/)

An AI-powered analysis tool: paste a transaction hash, choose an LLM provider, and receive a structured report streamed live in your browser.

**Highlights**

| Feature | Detail |
|---------|--------|
| LLM providers | Claude, GPT, Gemini, DeepSeek, Qwen |
| Report sections | Conclusion · Token Flow Chart · EigenTx Mermaid diagram |
| Raw data | Syntax-highlighted MEV JSON viewer |
| Rendering | Streamed markdown via SSE, rendered with marked.js + mermaid.js |
| Runtime | Python 3.10+ · `localhost:5001` |

**How it works**

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

→ [Full documentation](./mev-report/README.md)

---

### 3. [MEV Leaderboard](./leaderboard/)

A local Python app that fetches and displays the MEV leaderboard via the MEVScan MCP API, showing top bots ranked by PnL.

**Highlights**

| Feature | Detail |
|---------|--------|
| Time ranges | 1d / 7d |
| MEV types | Arbitrage, Sandwich, Liquidation, JIT |
| Filters | Bot address, MEV type, sorting key |
| Columns | Rank · MEV ID · Block · Type · Address (Etherscan link) · PnL (USD) |
| Runtime | Python 3.10+ · `localhost:5002` |

**How it works**

```
Browser → GET /leaderboard?... → app.py
  → MCP SSE GET /sse          (create session)
  → MCP POST /messages/       (initialize)
  → MCP POST /messages/       (tools/call get_leaderboard)
  ← SSE response JSON-RPC
→ JSONResponse → Browser renders table
```

→ [Full documentation](./leaderboard/README.md)

---

## Getting a MEVScan API Key

All apps above require a **MEVScan API key**. Visit [eigenphi.com](https://eigenphi.com/) and sign up to obtain one. You will also need to set the `MEVSCAN_URL` and `MEVSCAN_TOKEN` environment variables as described in each app's `.env.example`.

---
