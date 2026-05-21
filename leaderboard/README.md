# MEV Leaderboard Demo

MEV leaderboard demo via MEVScan MCP API

## Function
- demo for leaderboard API (https://eigenphi.com/docs.html#api-get-leaderboard) 
- Call `get_leaderboard` MCP tool to fetch MEV leaderboard data
- Support filters: 1d / 7d, MEV Type, Bot Address, Sorting key
- Display rank, MEV ID, block number, MEV type, address (Etherscan link), PnL in USD

## Quick Start

```bash
# 1. Enter the directory
cd leaderboard

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
open http://localhost:5002 # macOS
# start http://localhost:5002   # Windows
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `MEVSCAN_URL` | MEVScan server URL, e.g. `https://your-server.com` | **required** |
| `MEVSCAN_TOKEN` | API Bearer token | **required** |
| `LOCAL_HOST` | Local bind address | `127.0.0.1` |
| `LOCAL_PORT` | Local bind port | `5002` |

## Data Flow

```
Browser → GET /leaderboard?... → app.py
  → MCP SSE GET /sse          (create session)
  → MCP POST /messages/       (initialize)
  → MCP POST /messages/       (tools/call get_leaderboard)
  ← SSE response JSON-RPC 
→ JSONResponse → Browser renders table
```
