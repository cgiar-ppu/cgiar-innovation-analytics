"""Runs inside the deployed app (release-smoke.yml -> run-release-smoke.py, smoke-request.json "invitations").

Creates invited-account links on a release target with a short-lived synthetic administrator token, the same
pattern as release-smoke.py. The repository is PUBLIC, so:
  * links are never printed: they are returned only encrypted to the requester's RSA public key
    (RSA-OAEP-SHA256 wrapping an AES-256-GCM key, as in dev-chat-e2e.py);
  * names/e-mails of real invitees never appear in the repository: the requester encrypts them to a one-off
    key pair generated on the host by the "prepare" step (private key kept in the container's /tmp, 0600,
    deleted after use); the log shows only that public key, counts, roles and statuses.

Operations (request["op"]):
  prepare  - optional QA invitation (synthetic address) + one-off key pair; returns the QA link encrypted.
  invite   - optional cohort revocation, then one bulk invitation round from the encrypted invitee list;
             returns the links encrypted and verifies the stored rows (role / activation / expiry).
  set_role - access-level change for an encrypted list of e-mails (each must currently have the expected role
             and be enabled); verifies that nothing else changed on any account; returns the new list encrypted.
  prepare with "list_all": also returns every invited account (encrypted) with its last chat activity.
"""
import asyncio,base64,json,os,time,zlib
from datetime import datetime,timezone
from pathlib import Path
import httpx
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import padding,rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from synapsis import config
from synapsis.auth.tokens import create_access_token

KEY_PATH=Path('/tmp/ia-release-invite-key.pem')
OAEP=padding.OAEP(mgf=padding.MGF1(hashes.SHA256()),algorithm=hashes.SHA256(),label=None)

def b64(b):return base64.b64encode(b).decode()

def seal(obj,public_pem):
 pub=serialization.load_pem_public_key(public_pem.encode());assert pub.key_size>=3072
 key=AESGCM.generate_key(256);nonce=os.urandom(12)
 ct=AESGCM(key).encrypt(nonce,zlib.compress(json.dumps(obj).encode(),9),None)
 return {'alg':'RSA-OAEP-SHA256+AES-256-GCM+zlib','wrapped_key':b64(pub.encrypt(key,OAEP)),'nonce':b64(nonce),'ciphertext':b64(ct)}

def unseal(env,private_key):
 key=private_key.decrypt(base64.b64decode(env['wrapped_key']),OAEP)
 return json.loads(zlib.decompress(AESGCM(key).decrypt(base64.b64decode(env['nonce']),base64.b64decode(env['ciphertext']),None)))

def utc(ts):return datetime.fromtimestamp(ts,tz=timezone.utc).isoformat(timespec='seconds') if ts else None

def quiet():
 import logging
 for n in ('httpx','httpcore'):logging.getLogger(n).setLevel(logging.WARNING)

async def rows_for(c,h,cohort):
 r=await c.get('/api/auth/invitations',headers=h);assert r.status_code==200,('list',r.status_code)
 return [a for a in r.json() if a.get('cohort')==cohort]

def counts(rows):
 out={}
 for a in rows:
  k=a['role']+('' if a['enabled'] else ' (revoked)');out[k]=out.get(k,0)+1
 return dict(sorted(out.items()))

async def full_accounts(c,h):
 """Every invited account (admin list) plus its last chat activity from the chat DB. Passwords never read."""
 from synapsis.database.connection import get_db
 r=await c.get('/api/auth/invitations',headers=h);assert r.status_code==200,('list',r.status_code);rows=r.json()
 async with get_db() as db:
  meta={x[0]:x[1:] for x in await (await db.execute("SELECT email,user_id,created_at,credential_version FROM invited_accounts")).fetchall()}
  act={x[0]:x[1:] for x in await (await db.execute("SELECT user_id,MAX(updated_at),COUNT(*) FROM sessions WHERE user_id LIKE 'invited:%' GROUP BY user_id")).fetchall()}
 out=[]
 for a in rows:
  uid,created,cv=meta.get(a['email'],(None,None,None));last,n=act.get(uid,(None,0))
  out.append({'email':a['email'],'name':a['name'],'role':a['role'],'cohort':a['cohort'],'enabled':bool(a['enabled']),'activated':bool(a['activated']),
   'link_expires_utc':utc(a['expires_at']),'created_utc':utc(created),'credential_version':cv,'last_chat_activity_utc':utc(last),'chats':n})
 return out

async def main():
 quiet()
 req=json.loads(base64.b64decode(os.environ['IA_RELEASE_INVITE_REQUEST']))
 op=req['op'];requester=req['public_key_pem'];assert op in ('prepare','invite','set_role')
 assert config.INVITED_LOGIN_ENABLED,'invited login is disabled on this target'
 admin=create_access_token('release-invite-'+str(int(time.time())),'Release invitation operator','admin',auth_source='sso',lifetime_seconds=300)
 h={'Authorization':'Bearer '+admin,'Origin':config.SSO_ORIGIN}
 out={'op':op};secret={}
 async with httpx.AsyncClient(base_url='http://localhost:7780',timeout=60) as c:
  if op=='prepare':
   key=rsa.generate_private_key(public_exponent=65537,key_size=3072)
   KEY_PATH.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()));KEY_PATH.chmod(0o600)
   out['one_off_public_key_pem']=key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo).decode()
   r=await c.get('/api/auth/invitations',headers=h);assert r.status_code==200,('list',r.status_code);everyone=r.json()
   if req.get('list_all'):
    secret['accounts']=await full_accounts(c,h);out['accounts_by_role']=counts(secret['accounts'])
   out['accounts_before']={'total':len(everyone),'in_requested_cohorts':{k:sum(1 for a in everyone if a.get('cohort')==k) for k in req.get('report_cohorts',[])}}
   qa=req.get('qa')
   if qa:
    body={'email':qa['email'],'name':qa['name'],'cohort':qa['cohort'],'expires_in_days':int(qa['expires_in_days']),'role':qa['role']}
    r=await c.post('/api/auth/invitations',headers=h,json=body);assert r.status_code==200,('qa invite',r.status_code)
    data=r.json();assert data.get('role')==qa['role'],('role not applied: old build?',data.get('role'))
    rows=await rows_for(c,h,qa['cohort'])
    secret['qa']={'email':qa['email'],'invitation_url':data['invitation_url'],'expires_at_utc':utc(rows[0]['expires_at']) if rows else None}
    out['qa']={'cohort':qa['cohort'],'rows':[{'role':a['role'],'activated':bool(a['activated']),'enabled':bool(a['enabled']),'expires_at_utc':utc(a['expires_at'])} for a in rows]}
  else:
   assert KEY_PATH.exists(),'one-off key missing: run "prepare" first on the same container'
   key=serialization.load_pem_private_key(KEY_PATH.read_bytes(),password=None)
   try:
    for cohort in req.get('revoke_cohorts',[]):
     r=await c.post('/api/auth/invitations/revoke-cohort',headers=h,json={'cohort':cohort});assert r.status_code==200,('revoke',r.status_code)
     out.setdefault('revoked',{})[cohort]=r.json()['revoked']
     out.setdefault('revoked_rows',{})[cohort]=[{'role':a['role'],'enabled':bool(a['enabled']),'link_outstanding':a['expires_at'] is not None} for a in await rows_for(c,h,cohort)]
    inv=req.get('invite')
    if inv:
     invitees=unseal(inv['invitees_sealed'],key);assert invitees and all(set(i)=={'name','email'} for i in invitees)
     r=await c.get('/api/auth/invitations',headers=h);assert r.status_code==200,('list',r.status_code);everyone=r.json()
     wanted={i['email'].strip().lower() for i in invitees}
     clash=[a for a in everyone if a['email'] in wanted]
     out['preexisting_accounts_for_invitees']=[{'role':a['role'],'activated':bool(a['activated']),'cohort':a['cohort']} for a in clash]
     assert not any(a['activated'] for a in clash),'an invitee already has an active account: stop (no link issued)'
     body={'cohort':inv['cohort'],'expires_in_days':int(inv['expires_in_days']),'role':inv['role'],'invitees':invitees}
     r=await c.post('/api/auth/invitations/bulk',headers=h,json=body);assert r.status_code==200,('bulk',r.status_code)
     data=r.json()
     assert data.get('role')==inv['role'] and not data['errors'] and len(data['invitations'])==len(invitees),('bulk result',data.get('role'),len(data['invitations']),[e.get('error') for e in data['errors']])
     rows={a['email']:a for a in await rows_for(c,h,inv['cohort'])}
     secret['invitations']=[{'name':i['name'],'email':i['email'],'invitation_url':i['invitation_url'],'expires_at_utc':utc(rows[i['email']]['expires_at'])} for i in data['invitations']]
     out['invite']={'cohort':inv['cohort'],'requested':len(invitees),'created':len(data['invitations']),'errors':len(data['errors']),'role':data['role'],
      'rows':[{'role':a['role'],'activated':bool(a['activated']),'enabled':bool(a['enabled']),'expires_at_utc':utc(a['expires_at'])} for a in rows.values()]}
     assert len(rows)==len(invitees) and all(a['role']==inv['role'] and not a['activated'] and a['expires_at'] for a in rows.values()),'stored rows do not match'
    change=req.get('set_role')
    if change:
     spec=unseal(change['sealed'],key);role,frm=spec['role'],spec['from_role'];emails=[e.strip().lower() for e in spec['emails']]
     assert role in ('researcher','external') and emails and len(set(emails))==len(emails)
     before={a['email']:a for a in await full_accounts(c,h)}
     for e in emails:
      assert e in before,'target account not found: stop before any change'
      assert before[e]['role']==frm and before[e]['enabled'],('target not in the expected state: stop before any change',before[e]['role'],before[e]['enabled'])
     done=[]
     for e in emails:
      r=await c.post('/api/auth/invitations/role',headers=h,json={'email':e,'role':role});assert r.status_code==200,('role change',r.status_code,len(done),'already changed')
      done.append(e)
     after={a['email']:a for a in await full_accounts(c,h)}
     assert set(after)==set(before),'account set changed'
     same=('name','cohort','enabled','activated','link_expires_utc','created_utc','last_chat_activity_utc','chats')
     other_changed=[1 for e in before if e not in emails and before[e]!=after[e]]
     target_bad=[1 for e in emails if after[e]['role']!=role or not after[e]['enabled'] or any(after[e][k]!=before[e][k] for k in same)]
     out['set_role']={'requested':len(emails),'changed':len(done),'from_role':frm,'to_role':role,'by_role_before':counts(before.values()),'by_role_after':counts(after.values()),
      'targets_now_'+role+'_and_enabled':sum(1 for e in emails if after[e]['role']==role and after[e]['enabled']),
      'targets_sign_in_ended(credential_version+1)':sum(1 for e in emails if (after[e]['credential_version'] or 0)==(before[e]['credential_version'] or 0)+1),
      'other_accounts_changed':len(other_changed),'target_fields_other_than_role_changed':len(target_bad)}
     secret['accounts_after']=list(after.values())
     assert not other_changed and not target_bad,'unexpected change detected (see counts)'
   finally:
    KEY_PATH.unlink(missing_ok=True);out['one_off_key_deleted']=not KEY_PATH.exists()
 if secret:out['sealed']=seal(secret,requester)
 print(json.dumps({'release_invitations':out}))

if __name__=='__main__':asyncio.run(main())
