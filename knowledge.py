"""Source-backed knowledge and bounded autonomous reading, independent of chat weights."""
from contextlib import contextmanager
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import hashlib
import ipaddress
import json
from pathlib import Path
import re
import socket
import sqlite3
import threading
import time
import urllib.parse
import urllib.request

HOME=Path.home()/'Library'/'Application Support'/'UltimateOpenAI'
UA='UltimateOpenAI/0.3 (local personal research assistant)'
STOP=set('what is are the a an how does do why explain tell me about can you please find search internet web latest current simply simple briefly short beginner beginners teach learn of to for in on it this that they'.split())
STOP.update('ما ماذا هو هي كيف لي في من عن هل شو شلون بدي هذا هذه اشرح'.split())
SEEDS=[('en','Python (programming language)'),('en','Photosynthesis'),('en','Solar System'),
       ('en','Artificial intelligence'),('ar','اللغة العربية'),('en','Mathematics'),
       ('en','History'),('en','Statistics'),('ar','علم الحاسوب'),('en','Geography'),
       ('en','Scientific method'),('en','Climate')]

def utc():return datetime.now(timezone.utc).isoformat()
def daykey():return datetime.now(ZoneInfo('America/Toronto')).date().isoformat()
def words(text):
    text=re.sub('[\u064b-\u065f\u0670]','',text.casefold())
    return [w for w in re.findall(r'[^\W_]+',text) if w not in STOP and len(w)>1]

class PublicRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        public_url(newurl);return super().redirect_request(req,fp,code,msg,headers,newurl)

def public_url(url):
    p=urllib.parse.urlsplit(url)
    if p.scheme!='https' or not p.hostname or p.username or p.password or p.port not in (None,443):
        raise ValueError('Only public HTTPS webpages are supported')
    for result in socket.getaddrinfo(p.hostname,443,type=socket.SOCK_STREAM):
        if not ipaddress.ip_address(result[4][0]).is_global:raise ValueError('Private network addresses are blocked')
    return url

def fetch(url,cap=200_000):
    public_url(url)
    req=urllib.request.Request(url,headers={'User-Agent':UA,'Accept':'application/json,text/html,text/plain'})
    with urllib.request.build_opener(PublicRedirect).open(req,timeout=20) as response:
        kind=response.headers.get('Content-Type','')
        if not any(k in kind for k in ('json','html','text/plain')):raise ValueError('Only text documents are supported')
        content=response.read(cap+1)
    if len(content)>cap:raise ValueError('Download exceeded its size limit')
    return content.decode('utf-8',errors='replace'),len(content)

def parse_pages(raw,language):
    if language not in {'en','ar'}:raise ValueError('Unsupported source language')
    pages=[]
    for p in sorted(raw.get('query',{}).get('pages',{}).values(),key=lambda x:x.get('index',0)):
        text=p.get('extract','').strip()
        if len(text)<200 or 'disambiguation' in p.get('pageprops',{}) or 'missing' in p:continue
        revision=p.get('revisions',[{}])[0].get('revid')
        if not revision:continue
        pages.append(dict(title=p['title'],text=text[:10000],url=p.get('fullurl',f"https://{language}.wikipedia.org/wiki/"+urllib.parse.quote(p['title'].replace(' ','_'))),
            language=language,license='CC-BY-SA-4.0',revision=str(revision),
            attribution='Wikipedia contributors',revision_url=f'https://{language}.wikipedia.org/w/index.php?oldid={revision}',
            links=[r['title'] for r in p.get('links',[]) if r.get('ns')==0][:12]))
    return pages

def wiki(title=None,query=None,language='en',links=False):
    if language not in {'en','ar'}:raise ValueError('Unsupported language')
    params=dict(action='query',format='json',prop='extracts|info|revisions|pageprops'+('|links' if links else ''),
        exintro=1,explaintext=1,exlimit='max',inprop='url',rvprop='ids|timestamp',ppprop='disambiguation',redirects=1)
    if title:params['titles']=title
    else:params.update(generator='search',gsrsearch=query,gsrlimit=3)
    if links:params.update(plnamespace=0,pllimit=12)
    text,size=fetch(f'https://{language}.wikipedia.org/w/api.php?'+urllib.parse.urlencode(params))
    return parse_pages(json.loads(text),language),size

def research(question):
    language='ar' if re.search('[\u0600-\u06ff]',question) else 'en'
    terms=words(question);query=' '.join(terms[:10]) or question
    pages,_=wiki(query=query,language=language)
    pages=[p for p in pages if any(t in (p['title']+' '+p['text']).casefold() for t in terms)]
    pages.sort(key=lambda p:p['title'].casefold()!=query.casefold())
    return pages

class Knowledge:
    def __init__(self,home=None):
        self.home=Path(home) if home else HOME;self.home.mkdir(parents=True,exist_ok=True)
        self.cycle_lock=threading.Lock()
        with self.db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS pages(url TEXT PRIMARY KEY,title TEXT,text TEXT,language TEXT,license TEXT,revision TEXT,revision_url TEXT,sha TEXT,updated TEXT);
                CREATE VIRTUAL TABLE IF NOT EXISTS chunks USING fts5(body,title,url UNINDEXED);
                CREATE TABLE IF NOT EXISTS frontier(language TEXT,title TEXT,depth INTEGER DEFAULT 0,state TEXT DEFAULT 'new',attempts INTEGER DEFAULT 0,UNIQUE(language,title));
                CREATE TABLE IF NOT EXISTS state(key TEXT PRIMARY KEY,value TEXT);
                CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY,at TEXT,kind TEXT,detail TEXT);
                CREATE TABLE IF NOT EXISTS budget(day TEXT PRIMARY KEY,pages INTEGER DEFAULT 0,bytes INTEGER DEFAULT 0,requests INTEGER DEFAULT 0);
            ''')
            db.executemany('INSERT OR IGNORE INTO frontier(language,title) VALUES (?,?)',SEEDS)
            for key,value in [('enabled','true'),('last_cycle','0'),('status','Ready to learn'),('daily_pages','12'),('daily_bytes','2000000')]:
                db.execute('INSERT OR IGNORE INTO state VALUES (?,?)',(key,value))
    @contextmanager
    def db(self):
        db=sqlite3.connect(self.home/'knowledge.sqlite',timeout=15);db.row_factory=sqlite3.Row
        try:
            with db:yield db
        finally:db.close()
    def state(self,key,default=None):
        with self.db() as db:row=db.execute('SELECT value FROM state WHERE key=?',(key,)).fetchone()
        return row['value'] if row else default
    def set_state(self,key,value):
        with self.db() as db:db.execute('INSERT OR REPLACE INTO state VALUES (?,?)',(key,str(value)))
    def event(self,kind,detail):
        with self.db() as db:
            db.execute('INSERT INTO events(at,kind,detail) VALUES (?,?,?)',(utc(),kind,detail))
            db.execute('DELETE FROM events WHERE id NOT IN (SELECT id FROM events ORDER BY id DESC LIMIT 200)')
    def remember(self,pages):
        count=0
        with self.db() as db:
            for page in pages:
                host=urllib.parse.urlsplit(page['url']).hostname
                if page.get('license')!='CC-BY-SA-4.0' or host not in {'en.wikipedia.org','ar.wikipedia.org'}:continue
                if not page.get('revision') or len(page['text'])<200:continue
                sha=hashlib.sha256(page['text'].encode()).hexdigest()
                old=db.execute('SELECT sha FROM pages WHERE url=?',(page['url'],)).fetchone()
                if old and old['sha']==sha:
                    db.execute('UPDATE pages SET updated=?,revision=?,revision_url=? WHERE url=?',
                        (utc(),page['revision'],page['revision_url'],page['url']))
                    db.execute("UPDATE frontier SET state='done' WHERE language=? AND title=?",(page['language'],page['title']))
                    continue
                if not old and db.execute('SELECT COUNT(*) FROM pages').fetchone()[0]>=500:continue
                db.execute('INSERT OR REPLACE INTO pages VALUES (?,?,?,?,?,?,?,?,?)',
                    (page['url'],page['title'],page['text'],page['language'],page['license'],page['revision'],page['revision_url'],sha,utc()))
                db.execute('DELETE FROM chunks WHERE url=?',(page['url'],))
                text=page['text']
                for offset in range(0,len(text),800):
                    db.execute('INSERT INTO chunks VALUES (?,?,?)',(text[offset:offset+1000],page['title'],page['url']))
                # Mark directly learned articles done so they are not needlessly re-read.
                db.execute("INSERT INTO frontier(language,title,state) VALUES (?,?,'done') ON CONFLICT(language,title) DO UPDATE SET state='done'",(page['language'],page['title']))
                count+=1
        return count
    def recall(self,question,limit=4):
        terms=list(dict.fromkeys(words(question)))[:12]
        if not terms:return []
        query=' OR '.join('"'+t+'"' for t in terms)
        with self.db() as db:
            rows=db.execute('SELECT body,title,url,bm25(chunks,1,3,0) AS rank FROM chunks WHERE chunks MATCH ? ORDER BY rank LIMIT 20',(query,)).fetchall()
            selected=[];seen=set()
            for row in rows:
                coverage=len(set(terms)&set(words(row['body']+' '+row['title'])))/len(terms)
                if coverage<.5 or row['url'] in seen:continue
                p=db.execute('SELECT * FROM pages WHERE url=?',(row['url'],)).fetchone()
                selected.append(dict(p,excerpt=row['body'],from_memory=True));seen.add(row['url'])
                if len(selected)>=limit:break
        return selected
    def status(self):
        day=daykey()
        with self.db() as db:
            count=db.execute('SELECT COUNT(*) FROM pages').fetchone()[0]
            budget=db.execute('SELECT * FROM budget WHERE day=?',(day,)).fetchone()
            events=[dict(r) for r in db.execute('SELECT at,kind,detail FROM events ORDER BY id DESC LIMIT 6')]
        return dict(enabled=self.state('enabled')=='true',state=self.state('status'),knowledge_pages=count,
            pages_today=budget['pages'] if budget else 0,daily_page_limit=int(self.state('daily_pages')),
            bytes_today=budget['bytes'] if budget else 0,last_cycle=float(self.state('last_cycle','0')),events=events,
            mode='source knowledge; coding-weight training is tracked separately')
    def cycle(self,force=False,reader=wiki):
        if not self.cycle_lock.acquire(blocking=False):return dict(state='busy',added=0)
        try:
            if self.state('enabled')!='true':return dict(state='paused',added=0)
            if not force and time.time()-float(self.state('last_cycle','0'))<3600:return dict(state='waiting',added=0)
            self.set_state('last_cycle',time.time())
            day=daykey();added=0;attempted=0;read=0
            self.set_state('status','Reading approved sources')
            with self.db() as db:
                stale=db.execute("SELECT language,title FROM pages WHERE julianday(updated)<julianday('now','-7 days')").fetchall()
                for row in stale:
                    db.execute("UPDATE frontier SET state='new',attempts=0 WHERE language=? AND title=?",(row['language'],row['title']))
            for _ in range(2):
                page_limit=int(self.state('daily_pages'));byte_limit=int(self.state('daily_bytes'))
                with self.db() as db:
                    db.execute('INSERT OR IGNORE INTO budget(day) VALUES (?)',(day,))
                    budget=db.execute('SELECT * FROM budget WHERE day=?',(day,)).fetchone()
                    # Reserve the request's full maximum before network I/O, including failures.
                    if budget['pages']>=page_limit or budget['bytes']+200000>byte_limit or budget['requests']>=12:
                        db.execute("UPDATE state SET value='Daily reading limit reached' WHERE key='status'");break
                    topic=db.execute("SELECT * FROM frontier WHERE state='new' AND depth<=2 AND attempts<2 ORDER BY depth,rowid LIMIT 1").fetchone()
                    if not topic:
                        db.execute("UPDATE state SET value='Sources current; weekly refresh pending' WHERE key='status'");break
                    db.execute('UPDATE budget SET bytes=bytes+200000,requests=requests+1 WHERE day=?',(day,))
                    db.execute('UPDATE frontier SET attempts=attempts+1 WHERE language=? AND title=?',(topic['language'],topic['title']))
                attempted+=1
                try:
                    pages,size=reader(title=topic['title'],language=topic['language'],links=True)
                    read+=len(pages)
                    new=self.remember(pages);added+=new
                    with self.db() as db:
                        db.execute('UPDATE budget SET pages=pages+?,bytes=bytes-200000+? WHERE day=?',(len(pages),size,day))
                        db.execute("UPDATE frontier SET state='done' WHERE language=? AND title=?",(topic['language'],topic['title']))
                        if topic['depth']<2:
                            for page in pages:
                                for title in page.get('links',[])[:4]:
                                    if ':' not in title and len(title)<180:
                                        db.execute('INSERT OR IGNORE INTO frontier(language,title,depth) VALUES (?,?,1)',(topic['language'],title))
                    self.event('learned',f"Read {topic['title']}; {new} new or updated source page(s).")
                except Exception as e:
                    # Keep the maximum reserved bytes charged on failures; never retry without a bound.
                    self.event('source_error',f"{topic['title']}: {str(e)[:160]}")
            if self.state('status')=='Reading approved sources':
                self.set_state('status',f'Checked {read} pages; {added} new or updated. Next cycle hourly.' if read else 'No source pages available this cycle; retry bounded.')
            return dict(state='complete',added=added,attempted=attempted,read=read,status=self.status())
        finally:self.cycle_lock.release()
