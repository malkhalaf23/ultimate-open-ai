"""Launch the persistent local runtime; API and model remain loopback-only."""
import json
from pathlib import Path
import secrets
import subprocess
import sys
import time
import urllib.request
import webbrowser

ROOT=Path(__file__).resolve().parent
CACHE=Path.home()/'Library/Caches/UltimateOpenAI'
HOME=Path.home()/'Library/Application Support/UltimateOpenAI'

def healthy(port,path='/health'):
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}'+path,timeout=2) as r:return r.status==200
    except OSError:return False

def main():
    CACHE.mkdir(parents=True,exist_ok=True);HOME.mkdir(parents=True,exist_ok=True)
    conf=json.loads((CACHE/'active-model.json').read_text())
    key=CACHE/'model-key.txt'
    if not key.exists():key.write_text(secrets.token_hex(32));key.chmod(0o600)
    model=Path(conf['model_path']) if conf.get('engine')=='mlx' else CACHE/'models'/conf['file']
    runtime=CACHE/'llama-runtime/llama-server'
    if not model.exists() or (conf.get('engine')!='mlx' and not runtime.exists()):raise SystemExit('Local model/runtime missing. See README.md.')
    training=HOME/'weight-learning/status.json'
    busy=False
    if training.exists():
        status=json.loads(training.read_text())
        if status.get('phase') in {'training','evaluating'} and status.get('pid'):
            import os
            try:os.kill(status['pid'],0);busy=True
            except ProcessLookupError:pass
    if not healthy(conf['port']) and not busy:
        if conf.get('engine')=='mlx':
            command=[str(CACHE/'training-venv/bin/python'),str(ROOT/'mlx_model_service.py')]
        else:command=[str(runtime),'--model',str(model),'--host','127.0.0.1','--port',str(conf['port']),
            '--ctx-size','4096','--batch-size','128','--ubatch-size','64','--threads','4',
            '--n-gpu-layers','0','--parallel','1','--no-warmup','--alias','ultimate-local',
            '--api-key-file',str(key),'--cors-origins','http://127.0.0.1:8877']
        with (HOME/'model.log').open('ab') as log:p=subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
        (HOME/'model.pid').write_text(str(p.pid));deadline=time.monotonic()+45
        while time.monotonic()<deadline and not healthy(conf['port']):
            if p.poll() is not None:raise SystemExit('Model exited. See model.log.')
            time.sleep(.5)
        if not healthy(conf['port']):raise SystemExit('Model still starting. Retry the launcher shortly.')
    if not healthy(8877,'/api/status'):
        with (HOME/'assistant.log').open('ab') as log:
            p=subprocess.Popen([sys.executable,str(ROOT/'assistant.py')],stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
        (HOME/'assistant.pid').write_text(str(p.pid));deadline=time.monotonic()+10
        while time.monotonic()<deadline and not healthy(8877,'/api/status'):time.sleep(.2)
    if not healthy(8877,'/api/status'):raise SystemExit('Assistant did not start. See assistant.log.')
    print('Assistant ready: http://127.0.0.1:8877')
    if '--no-browser' not in sys.argv:webbrowser.open('http://127.0.0.1:8877')

if __name__=='__main__':main()
