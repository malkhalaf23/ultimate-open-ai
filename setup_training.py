"""Pinned, bounded public model/data downloads for local MLX fine-tuning."""
import concurrent.futures
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import urllib.request

CACHE=Path.home()/'Library/Caches/UltimateOpenAI'
MODEL=CACHE/'mlx-qwen2.5-coder-1.5b-4bit'
REV='b3252a2f97102b1fb1571fec2c9b27219a8536be'
REPO='mlx-community/Qwen2.5-Coder-1.5B-Instruct-4bit'
FILES={'README.md','added_tokens.json','config.json','merges.txt','model.safetensors','model.safetensors.index.json','special_tokens_map.json','tokenizer.json','tokenizer_config.json','vocab.json'}

def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()

def fetch_file(url,path,cap,size=None,expected=None):
    if not path.exists():
        temp=path.with_suffix(path.suffix+'.part');total=0
        with urllib.request.urlopen(url,timeout=60) as r,temp.open('wb') as f:
            while block:=r.read(1024*1024):
                total+=len(block)
                if total>cap:raise ValueError('Download exceeded cap')
                f.write(block)
        temp.replace(path)
    actual=digest(path)
    if path.stat().st_size>cap or (size and path.stat().st_size!=size) or (expected and actual!=expected):
        raise ValueError('Verification failed: '+path.name)
    return dict(file=path.name,bytes=path.stat().st_size,sha256=actual,url=url)

def main():
    MODEL.mkdir(parents=True,exist_ok=True)
    with urllib.request.urlopen(f'https://huggingface.co/api/models/{REPO}/tree/{REV}?recursive=true',timeout=30) as r:rows=json.load(r)
    selected=[r for r in rows if r.get('path') in FILES]
    if sum(r['size'] for r in selected)>1_050_000_000:raise ValueError('Model download budget exceeded')
    def one(row):
        path=MODEL/row['path'];print('Downloading/verifying',path.name,flush=True)
        return fetch_file(f'https://huggingface.co/{REPO}/resolve/{REV}/{path.name}',path,1_000_000_000,
            size=row['size'],expected=row.get('lfs',{}).get('oid'))
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:files=list(pool.map(one,selected))
    manifest=dict(repository=REPO,revision=REV,license='Apache-2.0',files=files,retrieved= datetime.now(timezone.utc).isoformat())
    (MODEL/'download-manifest.json').write_text(json.dumps(manifest,indent=2))
    print('Verified model bytes:',sum(f['bytes'] for f in files),flush=True)

if __name__=='__main__':main()
