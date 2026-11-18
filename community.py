"""Opt-in original coding lessons, a review inbox, and shared adapter releases.

No chat history or generated answers are uploaded. Deployment is explicit.
"""
import argparse
from datetime import datetime,timezone
import hashlib
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import subprocess
import urllib.parse
import urllib.request

HOME=Path.home()/'Library/Application Support/UltimateOpenAI'
ROOT=HOME/'community'
BASE_REVISION='b3252a2f97102b1fb1571fec2c9b27219a8536be'
GITHUB_REPOSITORY='malkhalaf23/ultimate-open-ai'

def db():
    ROOT.mkdir(parents=True,exist_ok=True)
    con=sqlite3.connect(ROOT/'community.sqlite3',timeout=10)
    con.row_factory=sqlite3.Row
    con.execute('CREATE TABLE IF NOT EXISTS lessons (id TEXT PRIMARY KEY, title TEXT, text TEXT, attribution TEXT, state TEXT, created TEXT, reason TEXT)')
    return con

def validate(data):
    if data.get('license')!='MIT' or data.get('original') is not True:
        raise ValueError('Only original human-authored lessons explicitly offered under MIT are eligible')
    title=str(data.get('title','')).strip();text=str(data.get('text','')).strip()
    attribution=str(data.get('attribution','Anonymous contributor')).strip()
    if not 4<=len(title)<=100 or not 80<=len(text)<=8000 or len(attribution)>80:
        raise ValueError('Use a title of 4–100 and lesson of 80–8000 characters')
    combined=title+'\n'+text+'\n'+attribution
    if re.search(r'(?i)AKIA[0-9A-Z]{16}|sk-[a-z0-9]{20,}|-----BEGIN .*PRIVATE KEY|(?:password|api[_-]?key|secret|token)\s*[:=]\s*[\"\x27]?[^\s\"\x27]{6,}|[\w.+-]+@[\w.-]+\.[a-z]{2,}|/Users/|/home/|\b(?:\d[ -]?){13,16}\b',combined):
        raise ValueError('Possible secret, personal information or private path; remove it before sharing')
    if re.search(r'\bdef (dedupe|is_prime|merge_intervals|binary_search|count_words|chunked|balanced_parens|flatten_once)\b',text):
        raise ValueError('Local evaluation function collision; excluded from community training')
    if not re.search(r'(?i)\b(python|javascript|typescript|swift|rust|golang|code|function|compiler|testing|debug|async|sql|algorithm|variable|class|api)\b',text):
        raise ValueError('Community learning is focused on coding')
    ident=hashlib.sha256(json.dumps([title,re.sub(r'\s+',' ',text),attribution],ensure_ascii=False).encode()).hexdigest()
    return dict(id=ident,title=title,text=text,attribution=attribution,license='MIT',original=True)

def settings():
    path=ROOT/'sharing.json'
    return json.loads(path.read_text()) if path.exists() else dict(enabled=False,endpoint='',attribution='Anonymous contributor')

def configure(enabled,endpoint='',attribution='Anonymous contributor'):
    current=settings()
    if enabled:
        u=urllib.parse.urlsplit(endpoint)
        github=endpoint=='https://github.com/'+GITHUB_REPOSITORY
        if not github and u.scheme!='https' and not (u.scheme=='http' and u.hostname in {'127.0.0.1','localhost'}):
            raise ValueError('Use an HTTPS hub, or loopback HTTP for local testing')
        if u.username or u.password or u.query or u.fragment:raise ValueError('Credentials belong in hub-token.txt, not the URL')
        if len(attribution)>80:raise ValueError('Attribution is too long')
        current.update(enabled=True,endpoint=endpoint.rstrip('/'),attribution=attribution,
            consent='Only my own original coding corrections marked Share lesson: or Correction: may be sent publicly under MIT; no private or generated content.',
            consent_at=datetime.now(timezone.utc).isoformat())
    else:current['enabled']=False
    ROOT.mkdir(parents=True,exist_ok=True);path=ROOT/'sharing.json'
    path.write_text(json.dumps(current,indent=2));path.chmod(0o600)
    return public_status()

def public_status():
    conf=settings()
    con=db()
    try:counts={r['state']:r['n'] for r in con.execute('SELECT state,COUNT(*) n FROM lessons GROUP BY state')}
    finally:con.close()
    return dict(enabled=bool(conf['enabled']),endpoint=conf.get('endpoint',''),counts=counts,
        rule='Only your original coding corrections beginning Share lesson: or Correction: are eligible. Never assistant answers or whole chats.')

def store(data,state='pending'):
    item=validate(data);con=db()
    try:
        with con:
            if con.execute('SELECT COUNT(*) FROM lessons').fetchone()[0]>=1000 and not con.execute('SELECT 1 FROM lessons WHERE id=?',(item['id'],)).fetchone():
                raise ValueError('Community inbox is full; review/archive it before accepting more')
            con.execute('INSERT OR IGNORE INTO lessons VALUES (?,?,?,?,?,?,?)',
                (item['id'],item['title'],item['text'],item['attribution'],state,datetime.now(timezone.utc).isoformat(),''))
    finally:con.close()
    return item['id']

def capture(message):
    """Explicit marker opts a human-authored lesson into already-consented sharing."""
    conf=settings()
    if not conf['enabled'] or not message.lstrip().lower().startswith(('share lesson:','correction:')):return None
    text=message.split(':',1)[1].strip()
    ident=store(dict(title=text.splitlines()[0][:100],text=text,attribution=conf['attribution'],license='MIT',original=True),'outbox')
    return dict(id=ident,state='queued',note='Your marked lesson is queued for the community hub, subject to maintainer review.')

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args):raise ValueError('Hub redirects are refused')

def deliver():
    conf=settings()
    if not conf['enabled']:return dict(state='paused')
    github=conf['endpoint']=='https://github.com/'+GITHUB_REPOSITORY
    token_path=ROOT/'hub-token.txt'
    if not github and not token_path.exists():return dict(state='not_configured',note='Set the hub token locally first')
    token=token_path.read_text().strip() if not github else None;con=db();sent=0
    try:
        # Bound automatic public submissions independently of local chat volume.
        today=datetime.now(timezone.utc).date().isoformat()
        used=con.execute("SELECT COUNT(*) FROM lessons WHERE state='submitted' AND substr(reason,1,10)=?",(today,)).fetchone()[0]
        if used>=5:return dict(state='daily_limit',sent=0)
        rows=con.execute("SELECT * FROM lessons WHERE state='outbox' ORDER BY created LIMIT 5").fetchall()
        for row in rows:
            if sent+used>=5 or not settings()['enabled']:break
            item=dict(row);item.update(license='MIT',original=True)
            try:
                if github:
                    result=github_submit(item)
                else:
                    request=urllib.request.Request(conf['endpoint']+'/v1/contributions',data=json.dumps(item).encode(),
                        headers={'Content-Type':'application/json','Authorization':'Bearer '+token},method='POST')
                    with urllib.request.build_opener(NoRedirect).open(request,timeout=10) as response:result=json.loads(response.read(4000))
                    if result.get('id')!=item['id']:raise ValueError('Hub acknowledgement mismatch')
                with con:con.execute("UPDATE lessons SET state='submitted',reason=? WHERE id=?",(today+' '+str(result),item['id']))
                sent+=1
            except Exception as error:
                with con:con.execute('UPDATE lessons SET reason=? WHERE id=?',(str(error)[:200],item['id']))
                break
    finally:con.close()
    return dict(state='delivered',sent=sent)

def gh(*args,input=None):
    result=subprocess.run(['gh',*args],input=input,text=True,capture_output=True,timeout=30)
    if result.returncode:raise ValueError('GitHub request failed; check gh auth login and repository access')
    return json.loads(result.stdout) if result.stdout.strip() else None

def github_submit(item):
    """Public issue inbox uses each contributor's own GitHub authentication."""
    marker='ultimate-lesson:'+item['id']
    existing=gh('api','--method','GET',f'repos/{GITHUB_REPOSITORY}/issues','-f','state=all','-f','per_page=100')
    for issue in existing:
        if marker in (issue.get('body') or ''):return issue['html_url']
    clean=validate(item)
    body='Community coding lesson for maintainer review. Original human-authored contribution offered under MIT.\n\n'+marker+'\n\n```json\n'+json.dumps(clean,ensure_ascii=False,indent=2)+'\n```'
    result=gh('api','--method','POST',f'repos/{GITHUB_REPOSITORY}/issues','--input','-',
        input=json.dumps(dict(title='[Coding lesson] '+clean['title'],body=body,labels=['community-lesson'])))
    return result['html_url']

def sync_github():
    """Only repository maintainers can apply the training-approved label."""
    url=f'https://api.github.com/repos/{GITHUB_REPOSITORY}/issues?labels=training-approved&state=all&per_page=100'
    req=urllib.request.Request(url,headers={'User-Agent':'UltimateOpenAI-community/1'})
    with urllib.request.urlopen(req,timeout=20) as response:raw=response.read(1_000_001)
    if len(raw)>1_000_000:raise ValueError('Community sync budget exceeded')
    issues=json.loads(raw);current=[];downloaded=len(raw)
    for issue in issues[:20]:
        if issue.get('pull_request'):continue
        match=re.search(r'```json\s*\n(.*?)\n```',issue.get('body',''),re.S)
        if not match:continue
        try:
            item=validate(json.loads(match[1]))
            # Labels alone do not freeze editable issue bodies. Owner approval binds the exact content hash.
            req=urllib.request.Request(issue['comments_url']+'?per_page=100',headers={'User-Agent':'UltimateOpenAI-community/1'})
            with urllib.request.urlopen(req,timeout=15) as response:comments_raw=response.read(min(150_001,2_000_001-downloaded))
            downloaded+=len(comments_raw)
            if len(comments_raw)>=150_001 or downloaded>2_000_000:raise ValueError('Community sync byte budget exceeded')
            approved=any(c.get('user',{}).get('login')==GITHUB_REPOSITORY.split('/')[0] and
                c.get('body','').strip()=='Training-approved SHA256: '+item['id'] for c in json.loads(comments_raw))
            if not approved:continue
            ident=store(item)
            review(ident,True,'Maintainer training-approved label on '+issue['html_url']);current.append(ident)
        except (ValueError,TypeError,json.JSONDecodeError):continue
    # Removing approval stops future inclusion; already-trained weights need retraining for removal.
    con=db()
    try:
        with con:
            for row in con.execute("SELECT id,reason FROM lessons WHERE state='approved'").fetchall():
                if 'Maintainer training-approved label on ' in row['reason'] and row['id'] not in current:
                    con.execute("UPDATE lessons SET state='rejected',reason='GitHub approval removed' WHERE id=?",(row['id'],))
    finally:con.close()
    return dict(approved=len(current))

def review(ident,approve,reason):
    if not reason.strip():raise ValueError('Record why this original lesson is correct and suitable, or why rejected')
    con=db()
    try:
        row=con.execute('SELECT * FROM lessons WHERE id=?',(ident,)).fetchone()
        if not row or row['state'] not in {'pending','approved','rejected','submitted'}:raise ValueError('No received contribution with that ID')
        if approve:validate(dict(row,license='MIT',original=True))
        with con:con.execute('UPDATE lessons SET state=?,reason=? WHERE id=?',('approved' if approve else 'rejected',reason[:1000],ident))
    finally:con.close()

def records():
    """Only maintainer-reviewed material joins the central training corpus."""
    from coding_corpus import source_split
    con=db()
    try:rows=con.execute("SELECT * FROM lessons WHERE state='approved' ORDER BY id LIMIT 100").fetchall()
    finally:con.close()
    result=[]
    for row in rows:
        item=validate(dict(row,license='MIT',original=True));ident='community:'+item['id']
        text=item['title']+'\n'+item['text']
        result.append(dict(id=ident,repository='community/reviewed',provider='Community',path=item['id'],revision=item['id'],
            url='urn:sha256:'+item['id'],license='MIT',license_notice='community-MIT.txt',text=text,
            attribution=item['attribution'],kind='code',split=source_split(ident),sha256=hashlib.sha256(text.encode()).hexdigest()))
    return result

def publish():
    """Publish an already-accepted active adapter, never an unvalidated candidate."""
    cache=Path.home()/'Library/Caches/UltimateOpenAI'
    conf=json.loads((cache/'active-model.json').read_text());folder=Path(conf['adapter_path'])
    report=json.loads((folder/'report.json').read_text());weights=folder/'adapters.safetensors'
    digest=hashlib.sha256(weights.read_bytes()).hexdigest()
    if report['state']!='accepted' or digest!=report['trained_sha256'] or digest!=conf['adapter_sha256']:
        raise ValueError('Only verified accepted active weights may be published')
    import shutil
    target=ROOT/'releases'/digest;target.mkdir(parents=True,exist_ok=True)
    shutil.copy2(weights,target/'adapters.safetensors')
    config=json.loads((folder/'adapter_config.json').read_text());config['base_model']='mlx-community/Qwen2.5-Coder-1.5B-Instruct-4bit'
    (target/'adapter_config.json').write_text(json.dumps(config,indent=2))
    shutil.copytree(folder/'notices',target/'notices',dirs_exist_ok=True)
    shutil.copy2(folder/'sources.json',target/'sources.json')
    manifest=dict(version=digest,sha256=digest,bytes=weights.stat().st_size,base_model=config['base_model'],base_revision=BASE_REVISION,
        before=report['before'],after=report['after'],coding_passes=report['coding_after']['passes'],coding_total=report['coding_after']['count'],
        limitations=report['limitation'],created=datetime.now(timezone.utc).isoformat())
    (ROOT/'releases/current.json').write_text(json.dumps(manifest,indent=2));return manifest

class Hub(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def authorized(self):
        path=ROOT/'hub-token.txt'
        return path.exists() and secrets.compare_digest(self.headers.get('Authorization',''),'Bearer '+path.read_text().strip())
    def reply(self,value,code=200):
        raw=json.dumps(value).encode();self.send_response(code);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
    def do_POST(self):
        if not self.authorized():self.reply(dict(error='Unauthorized'),401);return
        if self.path!='/v1/contributions':self.reply(dict(error='Not found'),404);return
        try:
            length=int(self.headers.get('Content-Length','0'))
            if not 1<=length<=16000:raise ValueError('Request too large')
            ident=store(json.loads(self.rfile.read(length)))
            self.reply(dict(id=ident,state='pending_review'))
        except Exception as error:self.reply(dict(error=str(error)),400)
    def do_GET(self):
        if not self.authorized():self.reply(dict(error='Unauthorized'),401);return
        if self.path=='/v1/releases/current.json':
            path=ROOT/'releases/current.json'
        elif re.fullmatch(r'/v1/releases/[0-9a-f]{64}/(?:adapters.safetensors|adapter_config.json)',self.path):
            path=ROOT/'releases'/self.path.removeprefix('/v1/releases/')
        else:self.reply(dict(error='Not found'),404);return
        if not path.is_file():self.reply(dict(error='No published release'),404);return
        raw=path.read_bytes();self.send_response(200);self.send_header('Content-Type','application/octet-stream');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)

def install_release():
    """Explicit opt-in install from the project's owner-published GitHub release."""
    import io
    import zipfile
    release=gh('api',f'repos/{GITHUB_REPOSITORY}/releases/latest')
    asset=next((a for a in release['assets'] if a['name']=='coding-adapter.zip'),None)
    if not asset or asset['size']>3_000_000:raise ValueError('No bounded coding adapter release')
    with urllib.request.urlopen(asset['browser_download_url'],timeout=30) as response:raw=response.read(3_000_001)
    if len(raw)>3_000_000:raise ValueError('Download too large')
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        if len(archive.infolist())>30 or sum(i.file_size for i in archive.infolist())>3_000_000:raise ValueError('Archive too large')
        manifest=json.loads(archive.read('manifest.json'));weights=archive.read('adapters.safetensors')
        if manifest['base_revision']!=BASE_REVISION:raise ValueError('Base revision mismatch')
        digest=hashlib.sha256(weights).hexdigest()
        if digest!=manifest['sha256'] or len(weights)!=manifest['bytes']:raise ValueError('Adapter integrity mismatch')
        target=HOME/'community-models'/digest;target.mkdir(parents=True,exist_ok=True)
        for name in archive.namelist():
            if name in {'manifest.json','sources.json','adapter_config.json','adapters.safetensors'} or re.fullmatch(r'notices/[A-Za-z0-9._-]+',name):
                path=target/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(archive.read(name))
    cache=Path.home()/'Library/Caches/UltimateOpenAI';native=cache/'mlx-qwen2.5-coder-1.5b-4bit'
    if json.loads((native/'download-manifest.json').read_text())['revision']!=BASE_REVISION:raise ValueError('Install the pinned base first')
    config_path=cache/'active-model.json';previous=json.loads(config_path.read_text())
    from weight_jobs import status,write,STATE,stop_model
    if status().get('phase') in {'training','evaluating'}:raise ValueError('Wait for training to finish')
    selected=dict(engine='mlx',label='Ultimate Coder · shared adapter',port=18879,model_path=str(native),adapter_path=str(target),adapter_sha256=digest)
    launcher=HOME/'runtime/launch_assistant.py'
    write(STATE/'rollback-config.json',previous);stop_model();write(config_path,selected)
    try:
        subprocess.run(['/usr/bin/python3',str(launcher),'--no-browser'],check=True,timeout=65)
        write(STATE/'active.json',selected)
    except Exception:
        stop_model();write(config_path,previous)
        subprocess.run(['/usr/bin/python3',str(launcher),'--no-browser'],timeout=65)
        raise
    return dict(installed=digest,release=release['html_url'])

def main():
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='command',required=True)
    sub.add_parser('init');sub.add_parser('status');sub.add_parser('deliver');sub.add_parser('inbox');sub.add_parser('publish');sub.add_parser('sync');sub.add_parser('install-release')
    serve=sub.add_parser('serve');serve.add_argument('--host',default='127.0.0.1');serve.add_argument('--port',type=int,default=18880)
    r=sub.add_parser('review');r.add_argument('id');r.add_argument('--approve',action='store_true');r.add_argument('--reason',required=True)
    args=parser.parse_args()
    if args.command=='init':
        ROOT.mkdir(parents=True,exist_ok=True);path=ROOT/'hub-token.txt'
        if not path.exists():path.write_text(secrets.token_hex(32));path.chmod(0o600)
        print('Hub initialized. Token stored locally; do not commit it.')
    elif args.command=='status':print(json.dumps(public_status(),indent=2))
    elif args.command=='deliver':print(json.dumps(deliver()))
    elif args.command=='sync':print(json.dumps(sync_github()))
    elif args.command=='install-release':print(json.dumps(install_release(),indent=2))
    elif args.command=='review':review(args.id,args.approve,args.reason)
    elif args.command=='publish':print(json.dumps(publish(),indent=2))
    elif args.command=='inbox':
        con=db()
        try:print(json.dumps([dict(r) for r in con.execute("SELECT * FROM lessons WHERE state='pending' ORDER BY created LIMIT 100")],indent=2))
        finally:con.close()
    elif args.command=='serve':
        print('Hub listening; public deployments require HTTPS termination and contributor token provisioning.',flush=True)
        ThreadingHTTPServer((args.host,args.port),Hub).serve_forever()

if __name__=='__main__':main()
