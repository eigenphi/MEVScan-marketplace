"""
MEV Report Demo — generate AI-powered analysis reports for MEV transactions.

Flow:
  1. Browser submits tx_hash + LLM config (provider/api_key/model)
  2. Fetch MEV detail from MEVScan via MCP SSE protocol
  3. Build prompt following SKILL.md format
  4. Stream LLM response back to browser via SSE

Supported providers: claude / gpt / gemini / deepseek / qwen

Usage:
  pip install -r requirements.txt
  cp .env.example .env
  python app.py
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import AsyncGenerator

import httpx
import uvicorn
from dotenv import load_dotenv
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, StreamingResponse
from starlette.routing import Route

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# -- MEVScan config (data layer only, no LLM config) --------------------------

MEVSCAN_DATA_URL: str = os.environ.get("MEVSCAN_URL", "").rstrip("/")
MEVSCAN_DATA_API_KEY: str = os.environ.get("MEVSCAN_TOKEN", "")
LOCAL_HOST: str = os.environ.get("LOCAL_HOST", "127.0.0.1")
LOCAL_PORT: int = int(os.environ.get("LOCAL_PORT", "8081"))

if not MEVSCAN_DATA_URL or not MEVSCAN_DATA_API_KEY:
    print("Error: set MEVSCAN_URL and MEVSCAN_TOKEN in .env")
    sys.exit(1)

# -- Provider defaults --------------------------------------------------------

PROVIDER_DEFAULTS: dict[str, dict] = {
    "claude": {
        "base_url": "https://api.anthropic.com",
        "model": "claude-opus-4-5",
    },
    "gpt": {
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o",
    },
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "model": "gemini-2.0-flash",
    },
    "deepseek": {
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-chat",
    },
    "qwen": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-plus",
    },
}

# -- System prompt (full SKILL.md instructions) -------------------------------

_SKILL_SYSTEM = """You are a professional MEV (Maximal Extractable Value) analyst. Produce a structured MEV analysis report strictly following the format below.

## Report Format

Output in **markdown** with these sections in order: Conclusion, Facts (Summary + Token Flow Chart + EigenTx).

### Section 1: Conclusion

Write 2-4 sentences covering:
- MEV type and one-line summary of what happened
- Key characteristics (profit-to-cost ratio, flash loans, number of hops, protocols involved)
- Notable observations (unusually high profit, failed arb, cross-protocol arbitrage)

Base all conclusions strictly on the data — do not speculate beyond what the data shows.

### Section 2: Facts

#### 2.1 Summary Table

Note: The JSON uses camelCase keys.

| Field | Value |
|-------|-------|
| MEV Type | `data.type` (uppercase) |
| Block Number | `data.blockNumber` |
| Block Timestamp | `data.blockTimestamp` (Unix seconds, convert to UTC datetime) |
| Tx Hash | `data.id` (full, never abbreviate) |
| Tx Index | `data.mevTxRelation.primary[0].txIndex` |
| From | `data.mevTxRelation.primary[0].from` (full address) |
| To | `data.mevTxRelation.primary[0].to` (full address) |
| Revenue | `data.pnl.summary.revenueUsd` formatted as USD |
| Cost | `data.pnl.summary.costUsd` formatted as USD |
| **Profit** | **`data.pnl.summary.profitUsd` formatted as USD** |

#### 2.2 Token Flow Chart

Compute per-address net balance changes from `data.mevTxRelation.primary[0].transfers`:
1. For each transfer: from-address subtracts amount, to-address adds amount
2. Group by (address, tokenId), sum all changes
3. Convert with token decimals (ETH/WETH: 18, USDC/USDT: 6, default: 18)

Tag each address:
- **Searcher**: if in `data.mevTxRelation.primary[0].summary.searchers[]` (if present), or inferred as the `from` address of the first transfer
- **Pool(Protocol)**: if appears as poolId in any action in `data.mevTxRelation.primary[0].actions[]` (use protocol name from mapping)
- **Builder**: if receives tip from searcher as last transfer

Display as pivot table — columns are tokens, rows are tagged addresses:

```
| Address | ETH | WETH | TOKEN... |
|---------|-----|------|---------|
| 0xFull (Searcher) | +0.0513 | -0.5000 | |
| 0xFull (Pool UniV3) | | +0.5000 | -1000.00 |
| 0xFull (Builder) | +0.0013 | | |
```

Row order: Searcher(s) first, then Pools, then Builder/others.
Column order: ETH, WETH, USDC, USDT, then others.
Full addresses always — never abbreviate.

#### 2.3 EigenTx (Mermaid)

Generate a `graph LR` Mermaid diagram from `data.mevTxRelation.primary[0].transfers`:

```mermaid
graph LR
    classDef searcher fill:#d4edda,stroke:#28a745
    classDef pool fill:#cce5ff,stroke:#0d6efd
    classDef builder fill:#fff3cd,stroke:#ffc107

    A["Searcher<br/>0xFullAddress"]:::searcher
    B["Pool(UniV3)<br/>0xFullAddress"]:::pool
    D["Builder<br/>0xFullAddress"]:::builder

    A -->|"0.5 WETH"| B
    B -->|"1000.00 USDC"| A
    A -->|"0.0134 ETH"| D
```

Rules:
- One node per unique address, label = role + full address
- One edge per (from, to, token) after deduplication (sum amounts)
- Edge label: human-readable amount + symbol

### Protocol ID Mapping

| ID | Name | | ID | Name |
|----|----- |-|----|----- |
| 0 | ERC20 | | 21 | DODOV2 |
| 2 | UniV2 | | 30 | BalancerV2 |
| 3 | UniV3 | | 31 | Balancer |
| 4 | UniV4 | | 40 | KyberSwap |
| 5 | SushiV2 | | 43 | KyberDMM |
| 6 | SushiV3 | | 50 | Bancor |
| 10 | CurveMain | | 51 | BancorV3 |
| 11 | CurveCrypto | | 60 | PancakeV3 |
| 19 | Curve | | 90 | CowProtocol |
| 20 | DODOV1 | | 520 | UniswapX |

Unknown IDs: display `Protocol({id})`.

### Token Symbol Mapping

| Address (prefix) | Symbol | Decimals |
|-----------------|--------|----------|
| 0xeeee...eeee | ETH | 18 |
| 0xc02a...6cc2 | WETH | 18 |
| 0xa0b8...eb48 | USDC | 6 |
| 0xdac1...31ec7 | USDT | 6 |
| 0x6b17...d0f | DAI | 18 |
| 0x2260...c599 | WBTC | 8 |

Unknown tokens: use full address, assume 18 decimals.

### Edge Cases

- Sandwich type (`frontrun`/`victim`/`backrun` keys in `mevTxRelation`): process each sub-relation separately, label them in the report.
- No transfers: note "No transfers recorded for this event."
- All addresses and tx hashes: FULL — never abbreviate.
"""

_SKILL_USER_TMPL = """Analyze the following MEV event and produce the full report.

## MEV Event Data (JSON)

```json
{mev_json}
```

Generate the complete MEV Analysis Report following the format in your instructions.
"""

# -- MEVScan data fetch -------------------------------------------------------

async def fetch_mev_detail(tx_hash: str) -> dict | None:
    """
    Full MCP SSE protocol:
      1. GET /sse  — establish SSE connection, read session_id
      2. POST /messages/  — send initialize handshake
      3. POST /messages/  — send tools/call get_mev_detail
      4. Read tool result from SSE stream
    Returns None if not found; raises RuntimeError on other failures.
    """
    auth_headers = {"Authorization": f"Bearer {MEVSCAN_DATA_API_KEY}"}
    base = MEVSCAN_DATA_URL  # e.g. https://eigenphi.com

    result_future: asyncio.Future = asyncio.get_event_loop().create_future()

    async def _sse_reader(client: httpx.AsyncClient) -> None:
        """Hold SSE connection, parse events, write tools/call result into the future."""
        session_id = None
        try:
            async with client.stream(
                "GET",
                f"{base}/sse",
                headers={**auth_headers, "Accept": "text/event-stream"},
                timeout=httpx.Timeout(60, connect=10),
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    if line.startswith("data:"):
                        data = line[5:].strip()
                        # Step 1: extract session_id from endpoint event
                        if data.startswith("/messages/") and session_id is None:
                            session_id = data.split("session_id=")[1]
                            logger.info("sse: got session_id=%s", session_id)
                            # kick off handshake + tool call
                            asyncio.ensure_future(_do_rpc(client, session_id))
                            continue
                        # Step 4: tool result arrives as id=2 JSON-RPC response
                        if data and not result_future.done():
                            try:
                                msg = json.loads(data)
                            except json.JSONDecodeError:
                                continue
                            # MCP pushes tool result as id=2 JSON-RPC response over SSE
                            if msg.get("id") == 2:
                                result_future.set_result(msg)
                                return
        except Exception as exc:
            if not result_future.done():
                result_future.set_exception(exc)

    async def _do_rpc(client: httpx.AsyncClient, session_id: str) -> None:
        """Step 2 + 3: send initialize handshake then invoke the tool."""
        url = f"{base}/messages/?session_id={session_id}"
        try:
            # initialize handshake
            await client.post(
                url,
                json={
                    "jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "mev-report-demo", "version": "1.0"},
                    },
                },
                headers={**auth_headers, "Content-Type": "application/json"},
                timeout=10,
            )
            # tools/call
            await client.post(
                url,
                json={
                    "jsonrpc": "2.0", "id": 2, "method": "tools/call",
                    "params": {
                        "name": "get_mev_detail",
                        "arguments": {"tx_hash": tx_hash},
                    },
                },
                headers={**auth_headers, "Content-Type": "application/json"},
                timeout=10,
            )
        except Exception as exc:
            if not result_future.done():
                result_future.set_exception(exc)

    async with httpx.AsyncClient(timeout=60) as client:
        asyncio.ensure_future(_sse_reader(client))
        try:
            rpc_response = await asyncio.wait_for(result_future, timeout=45)
        except asyncio.TimeoutError:
            raise RuntimeError("MEVScan MCP timeout — no response within 45s")

    logger.info("mcp response id=%s keys=%s", rpc_response.get("id"), list(rpc_response.keys()))

    # JSON-RPC layer error
    if "error" in rpc_response:
        err = rpc_response["error"]
        logger.warning("mcp rpc error: %s", err)
        msg = str(err.get("message", "")).lower()
        if "not found" in msg:
            return None
        raise RuntimeError(f"RPC error {err.get('code')}: {err.get('message')}")

    # MCP tool result is in result.content[0].text (FastMCP standard format)
    result = rpc_response.get("result", {})
    content = result.get("content", [])
    if content and content[0].get("type") == "text":
        text = content[0]["text"]
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            raise RuntimeError(f"Cannot parse tool result: {text[:200]}")
        if not parsed.get("ok", True):
            msg = parsed.get("message", "")
            if "not found" in msg.lower():
                return None
            raise RuntimeError(f"Tool error: {msg}")
        data = parsed.get("data")
        logger.info("fetch_mev_detail ok, data keys=%s", list(data.keys()) if data else None)
        return data

    raise RuntimeError(f"Unexpected MCP result format: {result}")


# -- LLM streaming -----------------------------------------------------------

async def stream_claude(api_key: str, model: str, system: str, user: str) -> AsyncGenerator[str, None]:
    """Stream tokens from Anthropic Claude API."""
    import anthropic
    client = anthropic.Anthropic(api_key=api_key)
    with client.messages.stream(
        model=model,
        max_tokens=4096,
        system=system,
        messages=[{"role": "user", "content": user}],
    ) as stream:
        for text in stream.text_stream:
            yield text


async def stream_openai_compat(
    api_key: str, model: str, base_url: str, system: str, user: str
) -> AsyncGenerator[str, None]:
    """Stream tokens from an OpenAI-compatible API (GPT / Gemini / DeepSeek / Qwen)."""
    from openai import AsyncOpenAI
    client = AsyncOpenAI(api_key=api_key, base_url=base_url)
    stream = await client.chat.completions.create(
        model=model,
        max_tokens=4096,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        stream=True,
    )
    async for chunk in stream:
        delta = chunk.choices[0].delta.content if chunk.choices else None
        if delta:
            yield delta


async def stream_llm(
    provider: str, api_key: str, model: str, base_url: str, mev_data: dict
) -> AsyncGenerator[str, None]:
    """Dispatch to the appropriate SDK based on provider."""
    user_msg = _SKILL_USER_TMPL.format(
        mev_json=json.dumps(mev_data, indent=2, ensure_ascii=False)
    )
    if provider == "claude":
        gen = stream_claude(api_key, model, _SKILL_SYSTEM, user_msg)
    else:
        gen = stream_openai_compat(api_key, model, base_url, _SKILL_SYSTEM, user_msg)

    async for text in gen:
        yield f"data: {json.dumps({'type': 'delta', 'text': text}, ensure_ascii=False)}\n\n"

    yield f"data: {json.dumps({'type': 'done'})}\n\n"


# -- HTTP routes --------------------------------------------------------------

async def index(request: Request) -> FileResponse:
    return FileResponse(Path(__file__).parent / "index.html")


async def providers(request: Request) -> JSONResponse:
    """GET /providers — return default config for each provider (no keys)."""
    return JSONResponse(PROVIDER_DEFAULTS)


async def report(request: Request) -> StreamingResponse | JSONResponse:
    """POST /report  body: {tx_hash, provider, api_key, model, base_url?}"""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid JSON"}, status_code=400)

    tx_hash = (body.get("tx_hash") or "").strip()
    provider = (body.get("provider") or "").strip().lower()
    api_key = (body.get("api_key") or "").strip()
    model = (body.get("model") or "").strip()

    if not tx_hash:
        return JSONResponse({"error": "tx_hash is required"}, status_code=400)
    if provider not in PROVIDER_DEFAULTS:
        return JSONResponse({"error": f"unknown provider: {provider}"}, status_code=400)
    if not api_key:
        return JSONResponse({"error": "api_key is required"}, status_code=400)

    defaults = PROVIDER_DEFAULTS[provider]
    if not model:
        model = defaults["model"]
    base_url = (body.get("base_url") or "").strip() or defaults["base_url"]

    logger.info("report: tx=%s provider=%s model=%s", tx_hash, provider, model)

    try:
        mev_data = await fetch_mev_detail(tx_hash)
    except httpx.HTTPStatusError as e:
        body_text = e.response.text[:200]
        logger.error("upstream HTTP error status=%s body=%s", e.response.status_code, body_text)
        return JSONResponse({"error": f"MEVScan API HTTP {e.response.status_code}: {body_text}"}, status_code=502)
    except Exception as e:
        logger.error("fetch_mev_detail error: %s", e)
        return JSONResponse({"error": str(e)}, status_code=500)

    if mev_data is None:
        return JSONResponse({"error": f"MEV event not found: {tx_hash}"}, status_code=404)

    async def event_stream():
        # push raw MEV data first
        yield f"data: {json.dumps({'type': 'mev_data', 'data': mev_data}, ensure_ascii=False)}\n\n"
        # then stream LLM report
        try:
            async for chunk in stream_llm(provider, api_key, model, base_url, mev_data):
                yield chunk
        except Exception as e:
            logger.error("stream_llm error: %s", e)
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def health(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


# -- App ----------------------------------------------------------------------

app = Starlette(
    routes=[
        Route("/", index),
        Route("/providers", providers),
        Route("/report", report, methods=["POST"]),
        Route("/health", health),
    ]
)

if __name__ == "__main__":
    logger.info("MEV Report Demo → http://%s:%d", LOCAL_HOST, LOCAL_PORT)
    uvicorn.run(app, host=LOCAL_HOST, port=LOCAL_PORT, log_level="warning")
