"""
MEV Live-Stream local proxy server

Responsibilities:
  1. Read MEVSCAN_URL / MEVSCAN_TOKEN from .env
  2. Subscribe to the upstream MEVScan SSE stream and forward events to all local browser WebSocket clients
  3. Serve static files (index.html)
  4. Auto-reconnect with exponential backoff (max 30 s interval)

Usage:
  python app.py
  Open http://localhost:8080 in your browser
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
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Route, WebSocketRoute
from starlette.staticfiles import StaticFiles
from starlette.websockets import WebSocket, WebSocketDisconnect

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# ── Configuration ────────────────────────────────────────────────────────────

MEVSCAN_URL: str = os.environ.get("MEVSCAN_URL", "").rstrip("/")
MEVSCAN_TOKEN: str = os.environ.get("MEVSCAN_TOKEN", "")
LOCAL_HOST: str = os.environ.get("LOCAL_HOST", "127.0.0.1")
LOCAL_PORT: int = int(os.environ.get("LOCAL_PORT", "8080"))

if not MEVSCAN_URL or not MEVSCAN_TOKEN:
    print("Error: set MEVSCAN_URL and MEVSCAN_TOKEN in .env")
    sys.exit(1)

# ── WebSocket client management ──────────────────────────────────────────────

_clients: set[WebSocket] = set()
_clients_lock = asyncio.Lock()


async def broadcast(data: dict) -> None:
    """Broadcast one event to all connected browser WebSocket clients."""
    msg = json.dumps(data, ensure_ascii=False)
    async with _clients_lock:
        dead = set()
        for ws in _clients:
            try:
                await ws.send_text(msg)
            except Exception:
                dead.add(ws)
        _clients.difference_update(dead)


# ── SSE subscription and forwarding ──────────────────────────────────────────

async def _subscribe_once(sub_id: str, sse_url: str, last_seq: int) -> int:
    """
    Open one SSE connection and forward events to browsers.
    Returns the last received seq (for resume on reconnect).
    Returns normally on connection drop or server close event; caller decides whether to retry.
    """
    headers = {
        "Authorization": f"Bearer {MEVSCAN_TOKEN}",
        "Accept": "text/event-stream",
        "Cache-Control": "no-cache",
    }
    if last_seq:
        headers["Last-Event-ID"] = str(last_seq)

    url = f"{MEVSCAN_URL}{sse_url}"
    logger.info("SSE connect: %s (last_seq=%d)", url, last_seq)

    async with httpx.AsyncClient(timeout=None) as client:
        async with client.stream("GET", url, headers=headers) as resp:
            if resp.status_code == 410:
                logger.info("Subscription expired (410)")
                return -410   # sentinel: trigger re-subscribe
            if resp.status_code in (401, 403):
                logger.error("Auth failed (%d) — check MEVSCAN_TOKEN", resp.status_code)
                return -resp.status_code
            if resp.status_code != 200:
                logger.warning("SSE bad status: %d", resp.status_code)
                return last_seq

            await broadcast({"_type": "status", "state": "connected"})

            cur_event = ""
            cur_data  = ""

            async for line in resp.aiter_lines():
                if line == "":
                    # empty line: dispatch event
                    if cur_data:
                        event_type = cur_event or "message"
                        data_str = cur_data.rstrip("\n")
                        if event_type == "error":
                            try:
                                d = json.loads(data_str)
                                reason = d.get("reason", "")
                                logger.info("Server error event: %s", reason)
                                if reason in ("subscription_expired", "insufficient_balance"):
                                    return -410   # triggers re-subscribe
                            except Exception:
                                pass
                        elif event_type in ("mev", "message", ""):
                            try:
                                payload = json.loads(data_str)
                                await broadcast({"_type": "mev", **payload})
                            except Exception as e:
                                logger.debug("JSON parse error: %s", e)
                    cur_event = ""
                    cur_data  = ""
                elif line.startswith("event:"):
                    cur_event = line[6:].strip()
                elif line.startswith("data:"):
                    cur_data += line[5:].strip() + "\n"
                elif line.startswith("id:"):
                    try:
                        last_seq = int(line[3:].strip())
                    except ValueError:
                        pass
                # comment lines are ignored

    return last_seq


async def _create_subscription() -> tuple[str, str] | None:
    """POST /stream/subscribe — returns (subscription_id, sse_url)."""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"{MEVSCAN_URL}/stream/subscribe",
            headers={"Authorization": f"Bearer {MEVSCAN_TOKEN}", "Content-Type": "application/json"},
        )
    if resp.status_code == 201:
        data = resp.json()
        sub_id = data["subscription_id"]
        return sub_id, "/stream/events"
    if resp.status_code == 409:
        # existing active subscription — reuse it
        data = resp.json()
        logger.info("Already subscribed, reusing existing subscription")
        return "existing", "/stream/events"
    logger.error("Subscribe failed: %d %s", resp.status_code, resp.text[:200])
    return None


async def _cancel_subscription(sub_id: str) -> None:
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            await client.delete(
                f"{MEVSCAN_URL}/stream/subscription",
                headers={"Authorization": f"Bearer {MEVSCAN_TOKEN}"},
            )
    except Exception:
        pass


async def stream_loop() -> None:
    """Main loop: subscribe → forward → reconnect on disconnect."""
    sub_id: str | None = None
    sse_url: str | None = None
    last_seq = 0
    retry = 0

    while True:
        await broadcast({"_type": "status", "state": "reconnecting"})

        # (re-)create subscription if needed
        if sub_id is None:
            try:
                result = await _create_subscription()
            except Exception as e:
                logger.warning("Subscribe error: %s", e)
                result = None

            if result is None:
                delay = min(2 * (1.6 ** retry), 30)
                retry += 1
                logger.info("Retry subscribe in %.1fs", delay)
                await asyncio.sleep(delay)
                continue

            sub_id, sse_url = result
            last_seq = 0
            retry = 0
            logger.info("Subscribed: %s", sub_id)

        # open SSE connection
        try:
            result_seq = await _subscribe_once(sub_id, sse_url, last_seq)
        except Exception as e:
            logger.warning("SSE error: %s", e)
            result_seq = last_seq

        if result_seq == -410:
            # subscription expired — re-subscribe
            await _cancel_subscription(sub_id)
            sub_id = None
            sse_url = None
            last_seq = 0
        elif result_seq < -1:
            # auth failed — stop retrying
            await broadcast({"_type": "status", "state": "auth_failed"})
            logger.error("Auth failed, stopping stream loop")
            return
        else:
            last_seq = result_seq
            # normal disconnect — keep sub_id and reconnect (subscription may still be valid)
            delay = min(2 * (1.6 ** retry), 30)
            retry += 1
            logger.info("SSE disconnected, retry in %.1fs", delay)
            await asyncio.sleep(delay)


# ── HTTP / WebSocket routes ──────────────────────────────────────────────────

async def ws_endpoint(ws: WebSocket) -> None:
    """Browser WebSocket endpoint — forwards MEV events to connected clients."""
    await ws.accept()
    async with _clients_lock:
        _clients.add(ws)
    # push current connection state immediately
    await ws.send_text(json.dumps({"_type": "status", "state": "connected"}))
    try:
        while True:
            # keep connection alive, respond to ping
            msg = await ws.receive_text()
            if msg == "ping":
                await ws.send_text("pong")
    except WebSocketDisconnect:
        pass
    finally:
        async with _clients_lock:
            _clients.discard(ws)


async def index(request: Request) -> FileResponse:
    return FileResponse(Path(__file__).parent / "index.html")


async def health(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "clients": len(_clients)})


# ── Application assembly ─────────────────────────────────────────────────────

app = Starlette(
    routes=[
        Route("/", index),
        Route("/health", health),
        WebSocketRoute("/ws", ws_endpoint),
    ]
)


async def main() -> None:
    loop = asyncio.get_running_loop()
    loop.create_task(stream_loop())

    config = uvicorn.Config(
        app,
        host=LOCAL_HOST,
        port=LOCAL_PORT,
        log_level="warning",   # suppress uvicorn access logs; business logging goes through logger
    )
    server = uvicorn.Server(config)
    logger.info("MEV LiveStream running → http://%s:%d", LOCAL_HOST, LOCAL_PORT)
    await server.serve()


if __name__ == "__main__":
    asyncio.run(main())
