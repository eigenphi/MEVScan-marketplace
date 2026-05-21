# MEV Live Stream — Local Demo

View the MEV event stream in real time on your local machine, powered by the MEVScan SSE push service.

## Features

- Displays the 500 most recent MEV events (Arbitrage / Sandwich / Liquidation / JIT)
- Newest events appear at the top; table updates automatically
- Pause / Resume — events are buffered while paused
- Auto-reconnect with exponential backoff on disconnect
- Address filter — show only events involving specific from/contract addresses

## Prerequisites

- Python 3.10+
- A valid MEVScan API token and server URL

## Quick Start

```bash
# 1. Enter the directory
cd demo/livestream

# 2. Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate      # macOS / Linux
# .venv\Scripts\activate       # Windows

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment variables
cp .env.example .env
# Edit .env and fill in MEVSCAN_URL and MEVSCAN_TOKEN

# 5. Start the local proxy
python app.py

# 6. Open in browser
open http://localhost:5000      # macOS
# start http://localhost:5000   # Windows
```

> On subsequent runs you only need to re-activate the virtual environment (step 2); no need to reinstall dependencies.

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `MEVSCAN_URL` | MEVScan server URL, e.g. `https://your-server.com` | **required** |
| `MEVSCAN_TOKEN` | API Bearer token | **required** |
| `LOCAL_HOST` | Local bind address | `127.0.0.1` |
| `LOCAL_PORT` | Local bind port | `8080` |

## Architecture

```
Browser (index.html)
    ↕ WebSocket  ws://localhost:8080/ws
Python proxy (app.py)
    ↕ SSE + Bearer Token
MEVScan server
```

The Python proxy holds the API token, subscribes to the upstream SSE stream, and broadcasts events to all local WebSocket clients. The browser communicates only with `localhost`, so there are no CORS issues.
