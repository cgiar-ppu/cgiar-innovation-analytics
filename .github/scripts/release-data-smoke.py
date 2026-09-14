"""Hosted source/date/index/agent verification with a synthetic private identity."""
import asyncio,json,time,sqlite3
from pathlib import Path
import httpx
from synapsis import config
from synapsis.auth.tokens import create_access_token
from synapsis.prms_snapshot import get_snapshot_info,resolve_db_path
from synapsis.tools.prms_search import prms_search

async def main():
 token=create_access_token('data-qa-'+str(int(time.time())),'Synthetic snapshot QA','researcher',auth_source='sso',lifetime_seconds=600)
 headers={'Authorization':'Bearer '+token,'Origin':config.SSO_ORIGIN}
 async with httpx.AsyncClient(base_url='http://localhost:7780',timeout=240) as c:
  cfg=(await c.get('/api/config')).json();assert cfg['model']=='claude-sonnet-5'
  r=await c.get('/api/prms/snapshot',headers=headers);assert r.status_code==200
  snapshot=r.json();assert snapshot['extracted_on']=='2026-09-13' and snapshot['data_as_of']=='2026-09-12' and snapshot['result_count']==32203
  with sqlite3.connect('file:'+resolve_db_path()+'?mode=ro',uri=True) as db:
   count,last=db.execute('select count(*),max(last_updated_date) from result').fetchone()
  assert count==32203 and str(last).startswith('2026-09-12')
  index=json.loads(Path('/app/data/search_index/prms_vectors_codes.json').read_text())
  assert index['snapshot']=='2026-09-13' and index['count']==23201
  search=await prms_search.handler({'query':'rice','mode':'keyword','top_k':3})
  assert not search.get('isError') and not search.get('is_error')
  text='\n'.join(x.get('text','') for x in search['content']);assert 'rice' in text.lower() and 'not found' not in text.lower()
  r=await c.get('/api/voice/data-catalog',headers=headers);assert r.status_code==200 and r.json()['snapshot_date']=='2026-09-13'
  r=await c.get('/api/dashboard/prms-stats',headers=headers);assert r.status_code==200 and r.json()['snapshot']['extracted_on']=='2026-09-13'
  r=await c.post('/api/query',headers=headers,json={'message':'Release data check. State the configured snapshot extraction date and data-as-of date. Use prms_query to run SELECT COUNT(*) AS raw_result_rows FROM result. Return that raw row count, explicitly not an innovation count. Do not delegate or do any other analysis.'})
  assert r.status_code==200
  answer=r.json()['response'];assert '32,203' in answer or '32203' in answer
  assert '2026-09-13' in answer or '13 September 2026' in answer or 'September 13, 2026' in answer
  print(json.dumps({'snapshot':snapshot,'direct_result_rows':count,'last_result_update':last,'index_records':index['count'],'keyword_search':'passed','voice_catalog':'passed','dashboard_snapshot':'passed','sonnet_query':'passed'}))
asyncio.run(main())
