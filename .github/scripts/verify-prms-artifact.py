"""Validate immutable snapshot bytes, metadata and matching search index before build."""
import hashlib,json,sqlite3
from pathlib import Path
root=Path('data');m=json.loads((root/'prdb.manifest.json').read_text());db=root/'prdb.sqlite'
assert hashlib.file_digest(db.open('rb'),'sha256').hexdigest()==m['sha256'],'Snapshot checksum mismatch'
con=sqlite3.connect('file:'+str(db)+'?mode=ro',uri=True)
assert con.execute('pragma quick_check').fetchone()[0]=='ok'
count,date=con.execute('select count(*),max(last_updated_date) from result').fetchone();assert count==m['result_count'] and date==m['max_last_updated_date']
for name,digest in m['index_sha256'].items():
 assert hashlib.file_digest((root/'search_index'/name).open('rb'),'sha256').hexdigest()==digest,'Search index mismatch'
idx=json.loads((root/'search_index/prms_vectors_codes.json').read_text());assert idx['snapshot'].replace('-','')==m['snapshot_date']
print(json.dumps({'snapshot':m['snapshot_date'],'result_rows':count,'index_records':idx['count'],'checksum':'verified'}))
