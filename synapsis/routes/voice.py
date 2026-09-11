"""Voice APIs reuse app auth; caller never chooses model, prompt or filesystem path."""
import asyncio
import os
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from synapsis.auth.middleware import get_current_user, resolve_user_id
from synapsis.voice import sessions
from synapsis.voice.config import enabled
from synapsis.voice.knowledge import lookup, data_catalog


def require_origin(request: Request):
    origin = request.headers.get('origin')
    allowed = os.getenv('IA_VOICE_ORIGINS', 'https://innovation-analytics-dev.synapsis-analytics.com').split(',')
    if origin and origin not in allowed:
        raise HTTPException(403, 'Voice requests must come from the configured application origin.')


router = APIRouter(prefix='/api/voice', tags=['voice'], dependencies=[Depends(require_origin)])


class Start(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: UUID
    sdp: str = Field(min_length=10, max_length=60000, pattern=r'^v=0')


class Knowledge(BaseModel):
    model_config = ConfigDict(extra='forbid')
    query: str = Field(max_length=300)
    source: str = Field(default='', max_length=40)
    start_line: int = Field(default=0, ge=0, le=10000)


@router.get('/status')
async def status(user=Depends(get_current_user)):
    return {'enabled': enabled(), 'configured': bool(os.getenv('OPENAI_API_KEY')), 'max_seconds': sessions.MAX_SECONDS}


@router.post('/sessions', status_code=201)
async def start(payload: Start, user=Depends(get_current_user)):
    if not enabled() or not os.getenv('OPENAI_API_KEY'):
        raise HTTPException(503, 'Voice is not enabled/configured in this environment.')
    return await sessions.create(resolve_user_id(user), str(payload.request_id), payload.sdp)


@router.post('/sessions/{request_id}/close')
async def close(request_id: UUID, user=Depends(get_current_user)):
    return await sessions.close(resolve_user_id(user), str(request_id))


@router.post('/sessions/{request_id}/heartbeat')
async def heartbeat(request_id: UUID, user=Depends(get_current_user)):
    return await sessions.heartbeat(resolve_user_id(user), str(request_id))


@router.post('/knowledge')
async def knowledge(payload: Knowledge, user=Depends(get_current_user)):
    try:
        return await asyncio.to_thread(lookup, payload.query, payload.source, payload.start_line)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


@router.get('/data-catalog')
async def catalog(user=Depends(get_current_user)):
    return await asyncio.to_thread(data_catalog)
