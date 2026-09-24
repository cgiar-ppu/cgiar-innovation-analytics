"""DEV-only live check that Claude Opus 5.5 is usable through the deployed app.

Runs INSIDE the dev container (base64-exec'd via SSM `docker exec` by deploy.yml).
Synthetic work only — no innovation counts, no real user data.

1. /api/config lists claude-opus-5-5 as selectable.
2. Direct SDK call: the API actually serves claude-opus-5-5 (observed model, no fallback)
   through the CLI bundled in the image.
3. App path: WebSocket new session -> switch_model claude-opus-5-5 -> a prms_query tool
   call -> the expected answer.
"""
import asyncio, json, tempfile, time

import httpx, websockets
from claude_agent_sdk import (ClaudeSDKClient, ClaudeAgentOptions, AssistantMessage,
                              ResultMessage, TextBlock, SystemMessage)
from claude_agent_sdk._cli_version import __cli_version__
from synapsis.auth.tokens import create_access_token

MODEL = 'claude-opus-5-5'
BASE = 'http://localhost:7780'


async def sdk_check():
    with tempfile.TemporaryDirectory(prefix='ia-opus55-qa-') as cwd:
        options = ClaudeAgentOptions(model=MODEL, cwd=cwd, setting_sources=[], max_turns=2,
                                     allowed_tools=[], max_budget_usd=1.0,
                                     system_prompt='Synthetic release test. Reply tersely.')
        models, texts, init_model, result = [], [], None, None
        async with ClaudeSDKClient(options=options) as client:
            await client.query('Reply exactly: OPUS55_SDK_OK')
            async for m in client.receive_response():
                if isinstance(m, SystemMessage) and m.subtype == 'init':
                    init_model = m.data.get('model')
                if isinstance(m, AssistantMessage):
                    models.append(m.model)
                    texts += [b.text for b in m.content if isinstance(b, TextBlock)]
                if isinstance(m, ResultMessage):
                    result = m
    assert result and not result.is_error, ('SDK result failed', getattr(result, 'result', None))
    assert set(models) == {MODEL}, ('requested model not (only) observed', models)
    assert 'OPUS55_SDK_OK' in ''.join(texts), texts
    return {'cli': __cli_version__, 'init_model': init_model, 'observed': sorted(set(models)),
            'cost_usd': result.total_cost_usd}


async def app_check():
    owner = 'dev-opus55-qa-' + str(int(time.time()))
    token = create_access_token(owner, 'Synthetic Opus 5.5 QA', 'researcher',
                                auth_source='sso', lifetime_seconds=900)
    async with httpx.AsyncClient() as c:
        cfg = (await c.get(BASE + '/api/config', headers={'Authorization': 'Bearer ' + token})).json()
    ids = [m['id'] for m in cfg.get('selectable_models', [])]
    assert MODEL in ids, ('not selectable in /api/config', ids)

    async with websockets.connect(BASE.replace('http', 'ws') + '/ws/chat?token=' + token,
                                  open_timeout=30, max_size=8 * 1024 * 1024) as ws:
        async def until(kind, timeout=300):
            events = []
            async with asyncio.timeout(timeout):
                while True:
                    e = json.loads(await ws.recv()); events.append(e)
                    if e.get('type') == 'error':
                        raise RuntimeError('Application emitted an error: ' + str(e.get('message', ''))[:400])
                    if e.get('type') == kind:
                        return events

        await ws.send(json.dumps({'type': 'new_session'}))
        sid = (await until('session', 90))[-1]['session_id']
        async with httpx.AsyncClient() as c:
            r = await c.patch(BASE + '/api/sessions/' + sid, headers={'Authorization': 'Bearer ' + token},
                              json={'title': '[QA] Opus 5.5 DEV verification'})
            assert r.status_code == 200, r.status_code
        await ws.send(json.dumps({'type': 'switch_model', 'model': MODEL}))
        switched = (await until('model_switched', 90))[-1]
        assert switched.get('model') == MODEL, switched
        await ws.send(json.dumps({'message': 'Release test: use the prms_query tool to run SELECT 17 * 19 AS qa_product, '
                                             'then reply with the number. This is synthetic arithmetic, not an innovation '
                                             'count. Do not delegate.'}))
        events = await until('result')
    text = ''.join(e.get('content', '') for e in events if e.get('type') == 'text')
    tools = [e.get('tool', '') for e in events if e.get('type') == 'tool_use']
    assert '323' in text, ('expected answer missing', text[-300:])
    assert any('prms_query' in t for t in tools), ('PRMS tool was not called', tools)
    return {'selectable': True, 'switch': 'confirmed', 'tools': tools, 'answer': 'passed',
            'cost_usd': events[-1].get('estimated_cost'), 'synthetic_session': sid}


async def main():
    out = {'sdk': await asyncio.wait_for(sdk_check(), 180),
           'app': await asyncio.wait_for(app_check(), 360)}
    print(json.dumps({'dev_opus55_check': out}))


asyncio.run(main())
