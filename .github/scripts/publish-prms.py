"""Authorized CI publication from end-to-end encrypted local transfer."""
import hashlib,json,os,sqlite3,tarfile,tempfile
from pathlib import Path
import boto3,requests
from cryptography.hazmat.primitives.ciphers import Cipher,algorithms,modes
assert boto3.client('sts').get_caller_identity()['Account']=='972793825893'
request=json.loads(Path('.github/prms-publish-request.json').read_text())
with tempfile.TemporaryDirectory() as tmp:
 root=Path(tmp);payload=root/'encrypted';archive=root/'bundle.tar.gz'
 with requests.get(request['url'],stream=True,timeout=120) as r:
  r.raise_for_status()
  with payload.open('wb') as f:
   for chunk in r.iter_content(4*1024*1024):f.write(chunk)
 with payload.open('rb') as src:
  nonce=src.read(12);src.seek(-16,2);tag=src.read(16);remaining=src.tell()-28;src.seek(12)
  cipher=Cipher(algorithms.AES(bytes.fromhex(os.environ['IA_PRMS_TRANSFER_KEY'])),modes.GCM(nonce,tag)).decryptor()
  with archive.open('wb') as out:
   while remaining:
    chunk=src.read(min(4*1024*1024,remaining));remaining-=len(chunk);out.write(cipher.update(chunk))
   out.write(cipher.finalize())
 with tarfile.open(archive) as tar:
  for member in tar.getmembers():
   assert member.isfile() and not Path(member.name).is_absolute() and '..' not in Path(member.name).parts
  tar.extractall(root,filter='data')
 db=root/'prdb.sqlite';manifest=json.loads((root/'prdb.manifest.json').read_text())
 assert hashlib.file_digest(db.open('rb'),'sha256').hexdigest()==request['sha256']==manifest['sha256']
 con=sqlite3.connect('file:'+str(db)+'?mode=ro',uri=True);assert con.execute('pragma quick_check').fetchone()[0]=='ok'
 assert con.execute('select count(*) from result').fetchone()[0]==manifest['result_count'];con.close()
 s3=boto3.client('s3');bucket='cgiar-ia-artifacts-972793825893'
 s3.put_bucket_versioning(Bucket=bucket,VersioningConfiguration={'Status':'Enabled'})
 prefix=manifest['s3_prefix']
 for path in [db,*sorted((root/'search_index').iterdir())]:
  key=prefix+'/'+str(path.relative_to(root))
  s3.upload_file(str(path),bucket,key,ExtraArgs={'ServerSideEncryption':'AES256'})
 # Versioned pointer updated only after every immutable artifact uploaded.
 s3.put_object(Bucket=bucket,Key='prdb.manifest.json',Body=json.dumps(manifest).encode(),ContentType='application/json',ServerSideEncryption='AES256')
 print(json.dumps({'published_snapshot':manifest['snapshot_date'],'result_count':manifest['result_count'],'prefix':prefix,'index_records':manifest['index_count'],'checksum':manifest['sha256']}))
