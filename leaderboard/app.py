"""
MEV Leaderboard Demo - Fetch leaderboard data via MEVScan MCP API.

Flow:
  1. Browser sends filter params (time_range, mev_type, bot, sort, limit)
  2. Call get_leaderboard tool via MCP SSE protocol
  3. Return JSON result and render leaderboard table

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

import httpx
import uvicorn
from dotenv import load_dotenv
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Route

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

MEVSCAN_URL: str = os.environ.get("MEVSCAN_URL", "").rstrip("/")
MEVSCAN_TOKEN: str = os.environ.get("MEVSCAN_TOKEN", "")
LOCAL_HOST: str = os.environ.get("LOCAL_HOST", "127.0.0.1")
LOCAL_PORT: int = int(os.environ.get("LOCAL_PORT", "5002"))

if not MEVSCAN_URL or not MEVSCAN_TOKEN:
    print("Error: set MEVSCAN_URL and MEVSCAN_TOKEN in .env")
    sys.exit(1)


async def fetch_leaderboard(
    time_range: str = "1d",
    mev_type: str = "",
    bot: str = "",
    sort: str = "profit",
    limit: int = 20,
) -> dict:
    """Call get_leaderboard tool via MCP SSE protocol, return tool response dict."""
    auth_headers = {"Authorization": f"Bearer {MEVSCAN_TOKEN}"}
    base = MEVSCAN_URL

    result_future: asyncio.Future = asyncio.get_event_loop().create_future()

    async def _sse_reader(client: httpx.AsyncClient) -> None:
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
                        if data.startswith("/messages/") and session_id is None:
                            session_id = data.split("session_id=")[1]
                            logger.info("sse: got session_id=%s", session_id)
                            asyncio.ensure_future(_do_rpc(client, session_id))
                            continue
                        if data and not result_future.done():
                            try:
                                msg = json.loads(data)
                            except json.JSONDecodeError:
                                continue
                            if msg.get("id") == 2:
                                result_future.set_result(msg)
                                return
        except Exception as exc:
            if not result_future.done():
                result_future.set_exception(exc)

    async def _do_rpc(client: httpx.AsyncClient, session_id: str) -> None:
        url = f"{base}/messages/?session_id={session_id}"
        try:
            await client.post(
                url,
                json={
                    "jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "leaderboard-demo", "version": "1.0"},
                    },
                },
                headers={**auth_headers, "Content-Type": "application/json"},
                timeout=10,
            )
            args: dict = {"time_range": time_range, "sort": sort, "limit": limit}
            if mev_type:
                args["mev_type"] = mev_type
            if bot:
                args["bot"] = bot
            await client.post(
                url,
                json={
                    "jsonrpc": "2.0", "id": 2, "method": "tools/call",
                    "params": {"name": "get_leaderboard", "arguments": args},
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
            raise RuntimeError("MEVScan MCP timeout")

    if "error" in rpc_response:
        err = rpc_response["error"]
        raise RuntimeError(f"RPC error {err.get('code')}: {err.get('message')}")

    result = rpc_response.get("result", {})
    content = result.get("content", [])
    if content and content[0].get("type") == "text":
        parsed = json.loads(content[0]["text"])
        return parsed

    raise RuntimeError(f"Unexpected MCP result format: {result}")


# -- HTTP routes ---------------------------------------------------------------

async def index(request: Request) -> FileResponse:
    return FileResponse(Path(__file__).parent / "index.html")


async def leaderboard(request: Request) -> JSONResponse:
    """GET /leaderboard?time_range=1d&mev_type=&bot=&sort=profit&limit=20"""
    p = request.query_params
    time_range = p.get("time_range", "1d")
    mev_type = p.get("mev_type", "")
    bot = p.get("bot", "")
    sort = p.get("sort", "profit")
    try:
        limit = int(p.get("limit", "20"))
    except ValueError:
        limit = 20

    logger.info("leaderboard: time_range=%s mev_type=%s bot=%s sort=%s limit=%s",
                time_range, mev_type, bot, sort, limit)
    try:
        data = await fetch_leaderboard(
            time_range=time_range,
            mev_type=mev_type,
            bot=bot,
            sort=sort,
            limit=limit,
        )
        return JSONResponse(data)
    except Exception as e:
        logger.error("leaderboard error: %s", e)
        return JSONResponse({"ok": False, "error": {"code": "SERVER_ERROR", "message": str(e)}},
                            status_code=500)


async def health(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


app = Starlette(
    routes=[
        Route("/", index),
        Route("/leaderboard", leaderboard),
        Route("/health", health),
    ]
)

if __name__ == "__main__":
    logger.info("MEV Leaderboard Demo running at http://%s:%d", LOCAL_HOST, LOCAL_PORT)
    uvicorn.run(app, host=LOCAL_HOST, port=LOCAL_PORT, log_level="warning")
