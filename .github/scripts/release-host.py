"""Runs on the target EC2 via Actions SSM. Secrets never leave the host."""
import json,os,subprocess as sp,sys,time,urllib.request,urllib.error,shlex
from pathlib import Path
cfg=json.loads(sys.argv[1]); stage=cfg['stage']; account=cfg['account']; sha=cfg['sha']
assert stage in ('dev','staging','prod') and len(sha)==40
name='cgiar-innovation-analytics'
def run(args,**kwargs): return sp.check_output(args,text=True,**kwargs).strip()
def secret(key):
 try: return run(['aws','ssm','get-parameter','--region','eu-central-1','--name',f'/cgiar-ia-{stage}/{key}','--with-decryption','--query','Parameter.Value','--output','text'],stderr=sp.DEVNULL)
 except sp.CalledProcessError: return ''
env={'AWS_REGION':'eu-central-1','LITESTREAM_S3_BUCKET':f'cgiar-ia-artifacts-{account}',
 'ANTHROPIC_API_KEY':secret('anthropic-api-key'),'OPENAI_API_KEY':secret('openai-api-key'),
 'IA_JWT_SECRET':secret('jwt-secret'),'IA_AUTH_DISABLED':'false','IA_SELF_SIGNUP':'false',
 'IA_PASSWORD_LOGIN_ENABLED':'false','IA_INVITED_LOGIN_ENABLED':'true','IA_SSO_ENABLED':'true',
 'IA_SSO_ISSUER':cfg['issuer'],'IA_SSO_CLIENT_ID':cfg['client'],'IA_SSO_DOMAIN':cfg['domain'],
 'IA_SSO_ORIGIN':cfg['origin'],'IA_SSO_ADMIN_SUBJECTS':cfg['admins'],
 'IA_VOICE_ENABLED':'true','IA_VOICE_ORIGINS':cfg['origin'],'SYNAPSIS_PORT':'7780','SYNAPSIS_HOST':'0.0.0.0','SYNAPSIS_PLATFORM':'linux',
 'PRMS_DB_PATH':'/app/data/prdb.sqlite','SYNAPSIS_WORKSPACE':'/workspace','SYNAPSIS_MAX_TURNS':'200',
 'SYNAPSIS_MODEL':cfg.get('model','claude-sonnet-4-6'),
 'SYNAPSIS_FALLBACK_MODEL':cfg.get('fallback','claude-opus-4-8'),
 'SYNAPSIS_AVAILABLE_MODELS':cfg.get('models','claude-sonnet-4-6,claude-opus-4-8[1m]')}
assert env['IA_JWT_SECRET'] and env['ANTHROPIC_API_KEY'], 'Missing required target secrets'
image=f'{account}.dkr.ecr.eu-central-1.amazonaws.com/cgiar-ia-service:{sha}'
password=run(['aws','ecr','get-login-password','--region','eu-central-1'])
sp.run(['docker','login','--username','AWS','--password-stdin',image.split('/')[0]],input=password,text=True,check=True,stdout=sp.DEVNULL);del password
sp.run(['docker','pull',image],check=True,stdout=sp.DEVNULL)
try: old=json.loads(run(['docker','inspect',name]))[0]
except sp.CalledProcessError: old=None
root=Path('/opt/cgiar-ia'); backup=root/'release-backups'/time.strftime('%Y%m%dT%H%M%SZ',time.gmtime());backup.mkdir(parents=True)
# Keep metadata for operator rollback only, without serializing secrets.
(backup/'release.json').write_text(json.dumps({'new_sha':sha,'old_image':old['Config']['Image'] if old else None}))
for folder in ('synapsis','workspace-files/uploads','workspace-files/outputs','workspace-files/exports','workspace-files/analysis'):
 p=root/folder;p.mkdir(parents=True,exist_ok=True);os.chown(p,1000,1000)
# Safeguard files that the legacy production container kept only in its writable layer.
if old:
 mounted={m['Destination'] for m in old['Mounts']}
 for folder in ('uploads','outputs','exports','analysis'):
  if '/workspace/'+folder not in mounted:
   sp.run(['docker','cp',name+':/workspace/'+folder+'/.',str(root/'workspace-files'/folder)],stderr=sp.DEVNULL,stdout=sp.DEVNULL)
sp.run(['chown','-R','1000:1000',str(root/'workspace-files')],check=True)
# Stop before backup/snapshot so the migration comparison has a fixed baseline.
if old: sp.run(['docker','stop','--time','45',name],check=True,stdout=sp.DEVNULL)
code='''import sqlite3,json,hashlib,os,glob
p='/workspace/.synapsis/chat.db'
if not os.path.exists(p): print(json.dumps({'sessions':[],'owners':[],'users':[],'messages':0}));raise SystemExit
c=sqlite3.connect('file:'+p+'?mode=ro',uri=True)
tables={r[0] for r in c.execute("select name from sqlite_master where type='table'")}
def hashes(q): return sorted(hashlib.sha256(json.dumps(list(r)).encode()).hexdigest() for r in c.execute(q))
cols={r[1] for r in c.execute('pragma table_info(sessions)')}
users=hashes('select email,name,role from users') if 'users' in tables else []
print(json.dumps({'sessions':hashes('select session_id from sessions'),'owners':hashes('select session_id,user_id from sessions') if 'user_id' in cols else [],'users':users,'messages':c.execute('select count(*) from messages').fetchone()[0]}))
'''
def snapshot(): return json.loads(run(['docker','run','--rm','--entrypoint','python','-v',str(root/'synapsis')+':/workspace/.synapsis:ro',image,'-c',code]))
before=snapshot();(backup/'before.json').write_text(json.dumps(before))
backupcode="""import sqlite3,glob,os
for path in glob.glob('/data/*.db'):
 src=sqlite3.connect('file:'+path+'?mode=ro',uri=True);dst=sqlite3.connect('/backup/'+os.path.basename(path));src.backup(dst);dst.close();src.close()
"""
os.chown(backup,1000,1000)
sp.run(['docker','run','--rm','--user','0:0','--entrypoint','python','-v',str(root/'synapsis')+':/data','-v',str(backup)+':/backup',image,'-c',backupcode],check=True)
if old: sp.run(['docker','rename',name,name+'-before-'+backup.name],check=True)
args=['docker','run','-d','--name',name,'--restart','always','--log-driver=awslogs','--log-opt','awslogs-region=eu-central-1','--log-opt',f'awslogs-group=/cgiar-ia/{stage}','--log-opt','awslogs-stream='+name,'--log-opt','awslogs-create-group=true','--log-opt','mode=non-blocking','--log-opt','max-buffer-size=4m','-p','7780:7780','-v',str(root/'synapsis')+':/workspace/.synapsis']
for folder in ('uploads','outputs','exports','analysis'): args+=['-v',str(root/'workspace-files'/folder)+':/workspace/'+folder]
# Pass only variable names in process argv; values are in child environment.
for key in env: args+=['-e',key]
args.append(image)
sp.run(args,env={**os.environ,**env},check=True,stdout=sp.DEVNULL)
for _ in range(60):
 try:
  health=json.load(urllib.request.urlopen('http://localhost:7780/api/health',timeout=5))
  if health.get('git_sha')==sha:break
 except Exception: pass
 time.sleep(2)
else: raise RuntimeError('New build did not become healthy; retained old stopped container and database backup')
after=snapshot()
for field in ('sessions','owners','users'): assert set(before[field]).issubset(after[field]),'Data continuity failed: '+field
assert after['messages']>=before['messages']
for path in ('/api/sessions','/api/auth/invitations'):
 try: urllib.request.urlopen('http://localhost:7780'+path,timeout=5);raise AssertionError('Anonymous access accepted: '+path)
 except urllib.error.HTTPError as e: assert e.code in (401,403)
print(json.dumps({'sha':sha,'backup':str(backup),'before':{k:len(v) if isinstance(v,list) else v for k,v in before.items()},'after':{k:len(v) if isinstance(v,list) else v for k,v in after.items()},'auth_checks':'passed'}))
