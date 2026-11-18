"""Install a source snapshot outside generated Documents; keep data separate."""
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parent
HOME=Path.home()/'Library/Application Support/UltimateOpenAI'
CACHE=Path.home()/'Library/Caches/UltimateOpenAI'

def main():
    spec=json.loads((ROOT/'model.json').read_text());model=CACHE/'models'/spec['file']
    active=CACHE/'active-model.json'
    mlx=active.exists() and json.loads(active.read_text()).get('engine')=='mlx'
    if mlx:
        native=Path(json.loads(active.read_text())['model_path']);manifest=json.loads((native/'download-manifest.json').read_text())
        for record in manifest['files']:
            path=native/record['file'];digest=hashlib.sha256()
            with path.open('rb') as f:
                for chunk in iter(lambda:f.read(1024*1024),b''):digest.update(chunk)
            if digest.hexdigest()!=record['sha256'] or path.stat().st_size!=record['bytes']:raise SystemExit('Native model verification failed')
    else:
        digest=hashlib.sha256()
        with model.open('rb') as f:
            for chunk in iter(lambda:f.read(1024*1024),b''):digest.update(chunk)
        if model.stat().st_size!=spec['bytes'] or digest.hexdigest()!=spec['sha256']:raise SystemExit('Model verification failed')
    release=HOME/'releases'/datetime.now(ZoneInfo('America/Toronto')).strftime('%Y%m%d-%H%M%S')
    release.mkdir(parents=True)
    for name in ['assistant.py','knowledge.py','launch_assistant.py','assistant.html','weight_jobs.py','train_coding.py','mlx_model_service.py','coding_bench.py','coding_corpus.py','coding_sources.json','coding_license_pins.json','community.py','COMMUNITY_LICENSE.txt']:
        shutil.copy2(ROOT/name,release/name)
    (release/'model.json').write_text(json.dumps(spec,indent=2))
    temp=HOME/'runtime-next'
    if temp.is_symlink():temp.unlink()
    temp.symlink_to(release,target_is_directory=True);os.replace(temp,HOME/'runtime')
    CACHE.mkdir(parents=True,exist_ok=True)
    active=CACHE/'active-model.json'
    # Deploying app code must not silently discard an accepted trained adapter.
    if not active.exists() or json.loads(active.read_text()).get('engine')!='mlx':
        active.write_text(json.dumps(spec,indent=2))
    print('Verified model and installed release:',release)

if __name__=='__main__':main()
