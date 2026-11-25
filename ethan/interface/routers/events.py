"""Dedicated external webhook endpoints, independent of Web/Lark authentication."""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException, Request

from ethan.core.event_producer import start_event
from ethan.core.event_triggers import DeliveryLedger, EventError, EventSettings, authenticate, normalize_event

router = APIRouter(prefix="/events", tags=["events"])
logger = logging.getLogger(__name__)
_inbound = 0
_MAX_INBOUND = 8


@router.post("/{source}", status_code=202)
async def receive_event(source: str, request: Request):
    global _inbound
    # No await between check/increment: atomic on a worker's asyncio loop.
    if _inbound >= _MAX_INBOUND:
        raise HTTPException(429, "Event ingress busy")
    _inbound += 1
    try:
        return await _receive_event(source, request)
    finally:
        _inbound -= 1


async def _receive_event(source: str, request: Request):
    settings = EventSettings.from_env()
    ledger = DeliveryLedger(settings)
    claimed = False
    delivery = ""
    try:
        if not settings.enabled:
            raise EventError(404, "Event ingress disabled")
        if source not in {"github", "alert"}:
            raise EventError(400, "Unsupported event source")
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                length = int(content_length)
            except ValueError:
                raise EventError(400, "Invalid content length") from None
            if length < 0:
                raise EventError(400, "Invalid content length")
            if length > settings.max_body:
                raise EventError(413, "Event body too large")
        body = bytearray()
        async with asyncio.timeout(10):
            async for chunk in request.stream():
                if len(body) + len(chunk) > settings.max_body:
                    raise EventError(413, "Event body too large")
                body.extend(chunk)
        delivery = authenticate(settings, source, bytes(body), request.headers)
        event = normalize_event(settings, source, bytes(body), request.headers)
        duplicate = await asyncio.to_thread(ledger.claim, source, delivery)
        if duplicate:
            return duplicate
        claimed = True
        sid = await start_event(settings, event, source, delivery)
        return {"status": "accepted", "session_id": sid}
    except EventError as exc:
        raise HTTPException(exc.status, exc.detail) from None
    except TimeoutError:
        raise HTTPException(408, "Event body read timed out") from None
    except Exception:
        if claimed:
            try:
                await asyncio.to_thread(ledger.update, source, delivery, "failed")
            except Exception:
                logger.exception("Event admission failure persistence failed")
        logger.exception("Event admission failed")
        raise HTTPException(503, "Event ingress unavailable") from None
