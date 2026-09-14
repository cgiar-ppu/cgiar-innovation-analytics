"""Runs inside deployed app. Uses labelled synthetic identities, never prints tokens.
SSO browser federation is separately verified by unauthenticated redirect probes.
"""
import asyncio,json,os,secrets,time,io,zipfile
import httpx
from synapsis.auth.tokens import create_access_token
from synapsis import config
from synapsis.database.connection import get_db,close_db
from synapsis.exporters.watermark import WATERMARK_BANNER

async def main():
 run_id='release-qa-'+str(int(time.time()))
 admin_token=create_access_token(run_id,'Release QA operator','admin',auth_source='sso',lifetime_seconds=300)
 other_token=create_access_token(run_id+'-other','Release QA other','researcher',auth_source='sso',lifetime_seconds=300)
 headers={'Origin':config.SSO_ORIGIN,'Authorization':'Bearer '+admin_token}
 results=[]
 async with httpx.AsyncClient(base_url='http://localhost:7780',timeout=90) as c:
  for path in ('/api/sessions','/api/auth/invitations'):
   assert (await c.get(path)).status_code in (401,403);results.append('anonymous '+path+' denied')
  # An administrator must not inherit any old or other-user history.
  r=await c.get('/api/sessions',headers=headers);assert r.status_code==200 and r.json()['sessions']==[]
  async with get_db() as db:
   legacy=run_id+'-legacy';unowned=run_id+'-unowned'
   for sid,owner in ((legacy,config.LEGACY_USER_ID),(unowned,None)):
    await db.execute('INSERT INTO sessions(session_id,title,created_at,updated_at,model,user_id) VALUES(?,?,?,?,?,?)',(sid,'[QA] inaccessible ownership fixture',time.time(),time.time(),config.MODEL,owner))
    await db.execute('INSERT INTO messages(session_id,type,data,ts) VALUES(?,?,?,?)',(sid,'text',json.dumps({'content':run_id+' PRIVATE_OWNERSHIP_FIXTURE'}),time.time()))
   await db.commit()
  for sid in (legacy,unowned):
   assert (await c.get('/api/history/'+sid,headers=headers)).status_code==404
   assert (await c.get('/api/export/'+sid,params={'token':admin_token})).status_code==404
  assert (await c.get('/api/search',params={'q':run_id},headers=headers)).json()['results']==[]
  assert (await c.get('/api/search',params={'q':run_id})).status_code==401
  assert (await c.get('/api/files/.synapsis/chat.db',headers=headers)).status_code==404
  results.append('admin cannot list/search/read/export legacy or unowned chats; hidden database blocked')
  email=run_id+'@example.com';body={'email':email,'name':'Release QA (synthetic, revoked after test)'}
  r=await c.post('/api/auth/invitations',headers=headers,json=body);assert r.status_code==200,r.status_code
  invite=r.json()['invitation_url'].split('#invite=')[1]
  pw=secrets.token_urlsafe(24)
  r=await c.post('/api/auth/invitation/accept',headers={'Origin':config.SSO_ORIGIN},json={'token':invite,'password':pw});assert r.status_code==200
  auth=r.json();user=auth['user']['user_id'];token=auth['token'];uh={'Authorization':'Bearer '+token,'Origin':config.SSO_ORIGIN}
  try:
   assert (await c.post('/api/auth/invitation/accept',headers={'Origin':config.SSO_ORIGIN},json={'token':invite,'password':pw})).status_code==410
   assert (await c.get('/api/sessions',headers=uh)).json()['sessions']==[]
   assert (await c.post('/api/auth/login',headers={'Origin':config.SSO_ORIGIN},json={'email':email,'password':pw})).status_code==200
   results.append('invitation activation, single-use, email login and empty private history')
   r=await c.get('/api/voice/status',headers=uh);assert r.status_code==200,('voice origin',r.status_code)
   assert r.json()['enabled'] and r.json()['configured']
   assert (await c.get('/api/voice/status',headers={**uh,'Origin':'https://untrusted.example'})).status_code==403
   results.append('voice enabled/configured for target origin; foreign origin rejected')
   # Synthetic fixture only; exercise real export and privacy routes against it.
   session=run_id
   async with get_db() as db:
    await db.execute('INSERT INTO sessions(session_id,title,created_at,updated_at,model,user_id) VALUES(?,?,?,?,?,?)',(session,'[QA] release watermark verification',time.time(),time.time(),config.MODEL,user))
    await db.execute('INSERT INTO messages(session_id,type,data,ts) VALUES(?,?,?,?)',(session,'text',json.dumps({'content':'Synthetic release verification. No portfolio claim.'}),time.time()))
    await db.commit()
   for fmt in ('md','html','docx','pdf'):
    r=await c.get('/api/export/'+session,params={'format':fmt,'token':token});assert r.status_code==200,(fmt,r.status_code)
    if fmt=='docx':
     z=zipfile.ZipFile(io.BytesIO(r.content));text=''.join(z.read(n).decode() for n in z.namelist() if n.endswith('.xml'))
     assert WATERMARK_BANNER in text and 'w:header' in text
    elif fmt=='pdf' and r.content.startswith(b'%PDF'):
     import pypdf
     text=''.join(p.extract_text() or '' for p in pypdf.PdfReader(io.BytesIO(r.content)).pages)
     assert 'REQUIRES HUMAN VALIDATION' in text
    else:
     assert WATERMARK_BANNER in r.text
     if fmt=='pdf' and 'claude-sonnet-5' in config.AVAILABLE_MODELS:
      raise AssertionError('Updated release must return a real PDF, not HTML fallback')
    results.append(fmt+' export watermark verified ('+r.headers.get('content-type','')+')')
   assert (await c.get('/api/history/'+session,headers={'Authorization':'Bearer '+other_token})).status_code==404
   assert (await c.get('/api/export/'+session,params={'token':other_token})).status_code==404
   results.append('second synthetic user denied history and export')
  finally:
   r=await c.post('/api/auth/invitations/revoke',headers=headers,json=body);assert r.status_code==200
   assert (await c.get('/api/sessions',headers=uh)).status_code==401
   results.append('QA invitation revoked; issued token rejected')
 await close_db()
 print(json.dumps({'checks':results,'synthetic_session':run_id,'real_sso_login':'not exercised; requires Microsoft user/MFA'}))
asyncio.run(main())
