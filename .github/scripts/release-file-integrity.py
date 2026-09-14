"""Read-only comparison with retained pre-auth production container; no file content logged."""
import hashlib,json,subprocess as sp,tarfile
from pathlib import Path
old='cgiar-innovation-analytics-before-20260913T235405Z'
sp.run(['docker','inspect',old],check=True,stdout=sp.DEVNULL)
results=[]
for folder in ('uploads','outputs','exports','analysis'):
 root=Path('/opt/cgiar-ia/workspace-files')/folder
 proc=sp.Popen(['docker','cp',old+':/workspace/'+folder+'/.','-'],stdout=sp.PIPE,stderr=sp.PIPE)
 count=0;missing=0;different=0
 try:
  with tarfile.open(fileobj=proc.stdout,mode='r|') as archive:
   for item in archive:
    if not item.isfile():continue
    rel=Path(item.name)
    if rel.parts and rel.parts[0]==folder:rel=Path(*rel.parts[1:])
    assert not rel.is_absolute() and '..' not in rel.parts
    target=root/rel
    expected=hashlib.sha256()
    stream=archive.extractfile(item)
    for chunk in iter(lambda:stream.read(1024*1024),b''):expected.update(chunk)
    count+=1
    if not target.is_file():missing+=1;continue
    actual=hashlib.sha256()
    with target.open('rb') as f:
     for chunk in iter(lambda:f.read(1024*1024),b''):actual.update(chunk)
    if actual.digest()!=expected.digest():different+=1
 except tarfile.ReadError:
  error=proc.stderr.read().decode()
  if 'Could not find' not in error and 'No such' not in error:raise
  results.append({'folder':folder,'legacy_directory':'absent'});proc.wait();continue
 assert proc.wait()==0,'Legacy archive read failed'
 results.append({'folder':folder,'files_compared':count,'missing':missing,'different':different})
 assert not missing and not different,'Legacy workspace file preservation check failed'
code="import os,glob,json; files=glob.glob('/workspace/.synapsis/*.db'); assert files and all(os.access(p,os.W_OK) for p in files); print(json.dumps({'database_files_writable_by_appuser':len(files),'uid':os.getuid()}))"
print(sp.check_output(['docker','exec','cgiar-innovation-analytics','python','-c',code],text=True))
print(json.dumps({'legacy_file_integrity':results}))
