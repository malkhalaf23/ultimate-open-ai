"""Bounded official-repository documents for real coding weight training."""
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import re
import time
import urllib.request

ROOT=Path(__file__).resolve().parent
HOME=Path.home()/'Library/Application Support/UltimateOpenAI'
CORPUS=HOME/'coding-corpus'

def fetch(url,cap,budget=None):
    if budget is not None:
        cap=min(cap,budget['limit']-budget['bytes'])
        if cap<=0:raise ValueError('Daily collection byte budget reached')
    req=urllib.request.Request(url,headers={'User-Agent':'UltimateOpenAI-local-training/0.4'})
    remaining=budget.get('deadline',time.monotonic()+25)-time.monotonic() if budget else 25
    if remaining<=0:raise ValueError('Collection time budget reached')
    with urllib.request.urlopen(req,timeout=min(25,remaining)) as response:raw=response.read(cap)
    if budget is not None:budget['bytes']+=len(raw)
    if len(raw)>=cap:raise ValueError('File reaches bounded download cap; excluded rather than truncated')
    return raw

def source_split(key):
    bucket=int(hashlib.sha256(key.encode()).hexdigest()[:8],16)%10
    return 'train' if bucket<7 else ('valid' if bucket<9 else 'audit')

def collect():
    CORPUS.mkdir(parents=True,exist_ok=True)
    records=[];excluded=[];notices=[];downloaded=0
    registry=json.loads((ROOT/'coding_sources.json').read_text())
    pins=json.loads((ROOT/'coding_license_pins.json').read_text())
    budget=dict(limit=3_500_000,bytes=0,deadline=time.monotonic()+180)
    for source in registry[:12]:
        repo=source['repository']
        try:
            # HEAD resolves once, then all files and notices use the exact commit.
            raw=fetch(f'https://api.github.com/repos/{repo}/commits?per_page=1',150_000,budget);downloaded+=len(raw)
            revision=json.loads(raw)[0]['sha'];base=f'https://raw.githubusercontent.com/{repo}/{revision}/'
            raw=fetch(base+source['license_file'],50_000,budget);downloaded+=len(raw)
            notice=raw.decode('utf-8')
            if source['license_marker'] not in notice:raise ValueError('License changed; requires review')
            if pins.get(repo)!=hashlib.sha256(raw).hexdigest():raise ValueError('License notice changed or is unreviewed; requires review')
            notice_file=repo.replace('/','--')+'-LICENSE.txt';(CORPUS/notice_file).write_text(notice)
            notices.append(dict(repository=repo,revision=revision,license=source['license'],file=notice_file,url=base+source['license_file']))
            for name in source['files']:
                try:
                    if downloaded+250_000>3_500_000:raise ValueError('Collection download budget reached')
                    raw=fetch(base+name,250_000,budget);downloaded+=len(raw);text=raw.decode('utf-8')
                    if len(text)<200:raise ValueError('Insufficient text')
                    if re.search(r'AKIA[0-9A-Z]{16}|sk-[A-Za-z0-9]{24,}',text):raise ValueError('Possible credential; excluded')
                    if re.search(r'\bdef (dedupe|is_prime|merge_intervals|binary_search|count_words|chunked|balanced_parens|flatten_once)\b',text):
                        raise ValueError('Exact acceptance-test function collision; excluded from local fine-tuning')
                    key=repo+':'+name;split=source_split(key)
                    record=dict(id=key,repository=repo,provider=source['provider'],path=name,revision=revision,
                        url=base+name,license=source['license'],license_notice=notice_file,text=text,
                        kind='code' if name.endswith(('.py','.ts','.js','.go')) else 'guidance',
                        split=split,sha256=hashlib.sha256(raw).hexdigest())
                    records.append(record);print(repo,name,split,len(raw),flush=True)
                except Exception as error:excluded.append(dict(id=repo+':'+name,reason=str(error)))
        except Exception as error:excluded.append(dict(id=repo,reason=str(error)))
    counts={split:sum(r['split']==split for r in records) for split in ['train','valid','audit']}
    downloaded=budget['bytes']
    if len(records)<20 or len({r['repository'] for r in records})<6:raise ValueError('Insufficient reviewed coding-source coverage; retain previous corpus')
    if any(counts[s]==0 for s in counts):raise ValueError('Need complete document-level train/valid/audit splits')
    from community import records as community_records
    community=community_records()
    if community:
        notice_file='community-MIT.txt'
        notice=(ROOT/'COMMUNITY_LICENSE.txt').read_text()+'\n\nContributors:\n'+'\n'.join(sorted({r['attribution'] for r in community}))
        (CORPUS/notice_file).write_text(notice)
        notices.append(dict(repository='community/reviewed',revision='content-addressed',license='MIT',file=notice_file,url='https://github.com/malkhalaf23/ultimate-open-ai'))
        records.extend(community)
        counts={split:sum(r['split']==split for r in records) for split in ['train','valid','audit']}
    digest=hashlib.sha256(''.join(r['id']+r['sha256'] for r in records).encode()).hexdigest()
    payload=dict(records=records,notices=notices,excluded=excluded,digest=digest,counts=counts,
        downloaded_bytes=downloaded,retrieved=datetime.now(timezone.utc).isoformat(),
        scope='Selected official licensed files only, not every vendor document or repository. No repository code is executed.',
        evaluation='Document-level split stable across future commits. Pretrained model may already have seen public files; no claim of pretraining independence.')
    temp=CORPUS/'manifest.tmp';temp.write_text(json.dumps(payload,ensure_ascii=False));temp.replace(CORPUS/'manifest.json')
    print(json.dumps(dict(counts=counts,excluded=excluded,downloaded_bytes=downloaded),indent=2),flush=True)
    return payload

if __name__=='__main__':collect()
