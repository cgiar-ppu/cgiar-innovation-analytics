"""DEV-ONLY: apply an encrypted table supplement to the published PRMS snapshot.

Why this exists (2026-10-14, ia-use-levels): the PRMS MySQL->SQLite converter
silently dropped every table whose DDL carries a column COMMENT (since the
13 Sep 2026 snapshot), incl. ``results_innovations_use`` (0-9 use level) and
``result_actors`` (use numbers). This script restores those tables for DEV
without changing the data vintage and without touching staging/production:

* reads the GLOBAL pointer ``prdb.manifest.json`` (never writes it);
* downloads the snapshot it points at and checks its sha256;
* downloads + decrypts (AES-256-GCM, key only in the DEV environment secret)
  a small supplement = an SQLite file holding ONLY the missing tables;
* adds those tables, then proves every pre-existing table is unchanged
  (schema SQL + row count + per-table row checksum) and the restored tables
  match the supplement's own fingerprints;
* uploads to a NEW immutable prefix (refuses if it already exists), copies
  the search index server-side, and writes the DEV-only pointer
  ``prdb.manifest.dev.json`` that DEV ``deploy.yml`` / ``ci.yml`` prefer.

Staging/production never read S3 data: they run a promoted DEV image. Nothing
here changes them. Only counts and hashes are printed (the repo is public).
"""
import hashlib, json, os, re, shutil, sqlite3, tarfile, tempfile, time
from pathlib import Path

import boto3, requests
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

BUCKET = 'cgiar-ia-artifacts-972793825893'
GLOBAL_POINTER = 'prdb.manifest.json'
DEV_POINTER = 'prdb.manifest.dev.json'
DEV_BRANCH = 'refs/heads/feature/innovation-platform-foundation'
# Tables this lane may add. otp_challenges (auth data) is never allowed.
ALLOWED = {'results_innovations_use', 'result_actors', 'investment_discontinued_option',
           'result_innovation_merge_split', 'result_ip_step_three_evidence',
           'progress_tracker_indicator_map', 'progress_tracker_result_provenance'}
FORBIDDEN = {'otp_challenges'}
assert DEV_POINTER != GLOBAL_POINTER


def sha256(path):
    with open(path, 'rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def table_fingerprints(con, schema='main'):
    """{table: [create_sql, row_count, sha256 of all rows in rowid order]}."""
    out = {}
    names = [r[0] for r in con.execute(
        f"select name from {schema}.sqlite_master where type='table' and name not like 'sqlite_%' order by name")]
    for t in names:
        sql = con.execute(f"select sql from {schema}.sqlite_master where type='table' and name=?", (t,)).fetchone()[0]
        h = hashlib.sha256(); n = 0
        try:
            cur = con.execute(f'select * from {schema}."{t}" order by rowid')
        except sqlite3.OperationalError:  # WITHOUT ROWID table: order by every column
            cols = [r[1] for r in con.execute(f'pragma {schema}.table_info("{t}")')]
            cur = con.execute(f'select * from {schema}."{t}" order by ' + ','.join(f'"{c}"' for c in cols))
        for row in cur:
            h.update(repr(row).encode('utf-8', 'surrogatepass')); n += 1
        out[t] = [sql, n, h.hexdigest()]
    return out


def main():
    assert boto3.client('sts').get_caller_identity()['Account'] == '972793825893', 'not the DEV account'
    assert os.environ.get('GITHUB_REF') == DEV_BRANCH, 'DEV branch only'
    req = json.loads(Path('.github/prms-publish-dev-request.json').read_text())
    assert re.fullmatch(r'\d{8}-r\d+', req['revision']), 'revision must look like 20260913-r2'
    assert re.fullmatch(r'[a-f0-9]{64}', req['base_sha256']) and re.fullmatch(r'[a-f0-9]{64}', req['payload_sha256'])
    prefix = 'snapshots/' + req['revision']
    s3 = boto3.client('s3')

    if s3.list_objects_v2(Bucket=BUCKET, Prefix=prefix + '/', MaxKeys=1).get('KeyCount', 0):
        raise SystemExit(f'{prefix}/ already exists: snapshot prefixes are immutable, pick a new revision')
    base_m = json.loads(s3.get_object(Bucket=BUCKET, Key=GLOBAL_POINTER)['Body'].read())
    assert base_m['sha256'] == req['base_sha256'], 'global pointer moved since the supplement was built'
    base_prefix = base_m['s3_prefix']
    assert base_prefix != prefix

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp); base = root / 'base.sqlite'; out = root / 'prdb.sqlite'
        t0 = time.time()
        s3.download_file(BUCKET, base_prefix + '/prdb.sqlite', str(base))
        assert sha256(base) == base_m['sha256'], 'base snapshot checksum mismatch'

        payload = root / 'payload'; archive = root / 'bundle.tar.gz'
        with requests.get(req['url'], stream=True, timeout=120) as r:
            r.raise_for_status()
            with payload.open('wb') as f:
                for chunk in r.iter_content(1024 * 1024):
                    f.write(chunk)
        assert sha256(payload) == req['payload_sha256'], 'encrypted payload checksum mismatch'
        with payload.open('rb') as src:
            nonce = src.read(12); src.seek(-16, 2); tag = src.read(16); remaining = src.tell() - 28; src.seek(12)
            dec = Cipher(algorithms.AES(bytes.fromhex(os.environ['IA_PRMS_DEV_SUPPLEMENT_KEY'])),
                         modes.GCM(nonce, tag)).decryptor()
            with archive.open('wb') as o:
                while remaining:
                    chunk = src.read(min(4 * 1024 * 1024, remaining)); remaining -= len(chunk); o.write(dec.update(chunk))
                o.write(dec.finalize())
        sup_dir = root / 'sup'; sup_dir.mkdir()
        with tarfile.open(archive) as tar:
            names = sorted(m.name for m in tar.getmembers())
            assert names == ['supplement.json', 'supplement.sqlite'], names
            for m in tar.getmembers():
                assert m.isfile()
            tar.extractall(sup_dir, filter='data')
        meta = json.loads((sup_dir / 'supplement.json').read_text())
        sup = sup_dir / 'supplement.sqlite'
        assert sha256(sup) == meta['sqlite_sha256'], 'supplement checksum mismatch'
        assert meta['base_sha256'] == base_m['sha256'], 'supplement built for another base'
        tables = sorted(meta['tables'])
        assert tables and set(tables) <= ALLOWED and not set(tables) & FORBIDDEN, tables

        # immutable=1: the base is in WAL mode; read it without creating -shm/-wal.
        bcon = sqlite3.connect(f'file:{base}?mode=ro&immutable=1', uri=True)
        before = table_fingerprints(bcon); bcon.close()
        assert not set(tables) & set(before), 'supplement would overwrite an existing table'

        shutil.copyfile(base, out)
        con = sqlite3.connect(str(out))
        con.execute('attach database ? as sup', (f'file:{sup}?mode=ro&immutable=1',))
        sup_tables = {r[0] for r in con.execute("select name from sup.sqlite_master where type='table'")}
        assert sup_tables == set(tables), (sup_tables, tables)
        with con:
            for t in tables:
                ddl = con.execute("select sql from sup.sqlite_master where type='table' and name=?", (t,)).fetchone()[0]
                con.execute(ddl)
                con.execute(f'insert into main."{t}" select * from sup."{t}"')
                for (idx_sql,) in con.execute(
                        "select sql from sup.sqlite_master where type='index' and tbl_name=? and sql is not null", (t,)).fetchall():
                    con.execute(idx_sql)
        sup_fp = table_fingerprints(con, 'sup')
        con.execute('detach database sup')
        con.commit()

        # ---------------- verification
        assert con.execute('pragma quick_check').fetchone()[0] == 'ok'
        after = table_fingerprints(con)
        assert set(after) == set(before) | set(tables), 'unexpected table set'
        changed = [t for t in before if after[t] != before[t]]
        assert not changed, ('pre-existing tables changed', changed)
        restored = {}
        for t in tables:
            assert after[t][1:] == sup_fp[t][1:] == [meta['tables'][t]['rows'], meta['tables'][t]['rows_sha256']], t
            restored[t] = after[t][1]
        count, maxdate = con.execute('select count(*), max(last_updated_date) from result').fetchone()
        assert count == base_m['result_count'] and maxdate == base_m['max_last_updated_date']
        orphans = {}
        if 'results_innovations_use' in tables:
            orphans['results_innovations_use.results_id'] = con.execute(
                'select count(*) from results_innovations_use u left join result r on r.id=u.results_id where r.id is null').fetchone()[0]
            orphans['results_innovations_use_measures.result_innovation_use_id'] = con.execute(
                'select count(*) from results_innovations_use_measures m left join results_innovations_use u '
                'on u.result_innovation_use_id=m.result_innovation_use_id where u.result_innovation_use_id is null').fetchone()[0]
        if 'result_actors' in tables:
            orphans['result_actors.result_id'] = con.execute(
                'select count(*) from result_actors a left join result r on r.id=a.result_id where r.id is null').fetchone()[0]
        table_count = len(after)
        con.close()
        out_sha = sha256(out)

        # ---------------- upload: new immutable prefix, then the DEV-only pointer
        s3.upload_file(str(out), BUCKET, prefix + '/prdb.sqlite', ExtraArgs={'ServerSideEncryption': 'AES256'})
        for name in sorted(base_m['index_sha256']):
            s3.copy_object(Bucket=BUCKET, Key=f'{prefix}/search_index/{name}', ServerSideEncryption='AES256',
                           CopySource={'Bucket': BUCKET, 'Key': f'{base_prefix}/search_index/{name}'})
        m = dict(base_m)
        m.update({'updated_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'sha256': out_sha,
                  'bytes': out.stat().st_size, 'table_count': table_count, 's3_prefix': prefix,
                  'revision': req['revision'], 'scope': 'DEV only (feature/innovation-platform-foundation)',
                  'base_sha256': base_m['sha256'], 'base_s3_prefix': base_prefix,
                  'restored_tables': restored, 'supplement_sha256': meta['sqlite_sha256'],
                  'supplement_source': meta.get('source_label', '')})
        key = DEV_POINTER
        assert key != GLOBAL_POINTER
        s3.put_object(Bucket=BUCKET, Key=key, Body=json.dumps(m, indent=1).encode(), ContentType='application/json',
                      ServerSideEncryption='AES256')
    summary = {'dev_prms_publish': {'revision': req['revision'], 'prefix': prefix, 'pointer': key,
                                    'base_sha256': base_m['sha256'], 'sha256': out_sha, 'table_count': table_count,
                                    'tables_unchanged': len(before), 'restored_rows': restored, 'orphans': orphans,
                                    'result_count': count, 'seconds': round(time.time() - t0)}}
    print(json.dumps(summary))
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as fh:
            fh.write('### DEV PRMS supplement published\n\n```json\n' + json.dumps(summary, indent=1) + '\n```\n')


if __name__ == '__main__':
    main()
