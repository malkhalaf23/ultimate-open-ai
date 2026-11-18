"""Bounded daily coding-weight updates, with durable reports and rollback."""
from datetime import datetime
import fcntl
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parent
HOME=Path.home()/'Library/Application Support/UltimateOpenAI'
CACHE=Path.home()/'Library/Caches/UltimateOpenAI'
STATE=HOME/'weight-learning'

def write(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix('.tmp');temp.write_text(json.dumps(data,indent=2));temp.replace(path)

def status():
    path=STATE/'status.json'
    return json.loads(path.read_text()) if path.exists() else dict(phase='idle',enabled=True)

def public_status():
    current=status();summary={k:current.get(k) for k in ['phase','note','attempt_day','adapter_sha256']}
    progress=Path(current['round'])/'progress.json' if current.get('round') else None
    if progress and progress.exists():summary['progress']=json.loads(progress.read_text())
    report=Path(current['report']) if current.get('report') else None
    if report and report.exists():
        result=json.loads(report.read_text())
        summary.update(steps=result['steps'],changed_tensors=result['changed_tensors'],parameters=result['trainable_parameters'],
            before=result['before'],after=result['after'],coding_before=result['coding_before']['passes'],
            coding_after=result['coding_after']['passes'],coding_total=result['coding_after']['count'])
    corpus=HOME/'coding-corpus/manifest.json'
    if corpus.exists():
        data=json.loads(corpus.read_text());summary['coding_files']=len(data['records'])
        summary['repositories']=len({r['repository'] for r in data['records']})
    return summary

def stop_model():
    path=HOME/'model.pid'
    if not path.exists():return
    pid=int(path.read_text())
    result=subprocess.run(['/bin/ps','-p',str(pid),'-o','command='],capture_output=True,text=True)
    command=result.stdout
    if not any(s in command for s in ['UltimateOpenAI/llama-runtime/llama-server','mlx_model_service.py']):
        if command.strip():raise ValueError('Model PID does not identify this app; stop refused')
        return
    try:os.kill(pid,signal.SIGTERM)
    except ProcessLookupError:return
    for _ in range(100):
        probe=subprocess.run(['/bin/ps','-p',str(pid),'-o','stat='],capture_output=True,text=True)
        if not probe.stdout.strip() or probe.stdout.strip().startswith('Z'):return
        time.sleep(.1)
    raise RuntimeError('Previous model did not stop; refusing overlapping GPU training')

def run():
    STATE.mkdir(parents=True,exist_ok=True)
    with (STATE/'job.lock').open('w') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return dict(phase='busy')
        from knowledge import Knowledge
        if Knowledge().state('enabled')!='true':return dict(phase='paused')
        prior=status();today=datetime.now(ZoneInfo('America/Toronto')).date().isoformat()
        if prior.get('attempt_day')==today or prior.get('last_scan_day')==today:
            return dict(phase='daily_limit',note='At most one automatic training attempt/scan per day')
        if shutil.disk_usage(STATE).free<1_500_000_000:
            prior.update(phase='low_disk',last_scan_day=today,note='Need at least 1.5 GB free before training')
            write(STATE/'status.json',prior);return prior
        model=CACHE/'mlx-qwen2.5-coder-1.5b-4bit/model.safetensors'
        python=CACHE/'training-venv/bin/python'
        if not model.exists() or not python.exists():
            prior.update(phase='not_configured',last_scan_day=today,note='Local training dependencies/model unavailable')
            write(STATE/'status.json',prior);return prior
        from coding_corpus import collect
        try:
            from community import sync_github
            sync_github()
            corpus=collect()
        except Exception as error:
            prior.update(phase='source_failed',last_scan_day=today,note=str(error));write(STATE/'status.json',prior);return prior
        if prior.get('corpus_digest')==corpus['digest']:
            prior.update(phase='unchanged',last_scan_day=today,note='No changed licensed coding sources')
            write(STATE/'status.json',prior);return prior
        round_dir=STATE/'rounds'/datetime.now(ZoneInfo('America/Toronto')).strftime('%Y%m%d-%H%M%S')
        round_dir.mkdir(parents=True)
        config_path=CACHE/'active-model.json';old_config=json.loads(config_path.read_text())
        active_path=STATE/'active.json';active=json.loads(active_path.read_text()) if active_path.exists() else None
        state=dict(phase='training',enabled=True,pid=os.getpid(),attempt_day=today,last_scan_day=today,round=str(round_dir),corpus_digest=corpus['digest'])
        write(STATE/'status.json',state)
        try:
            stop_model()
            command=[str(python),str(ROOT/'train_coding.py'),'--round',str(round_dir),'--steps','100']
            if active:command.extend(['--resume-adapter',active['adapter_path']])
            with (round_dir/'training.log').open('w') as log:
                result=subprocess.run(command,stdout=log,stderr=log,stdin=subprocess.DEVNULL,timeout=900)
            if result.returncode:raise RuntimeError('Training failed. See '+str(round_dir/'training.log'))
            report=json.loads((round_dir/'report.json').read_text())
            if report['state']=='accepted':
                new_config=dict(engine='mlx',label='Ultimate Coder 1.5B + trained LoRA',port=18879,
                    model_path=str(model.parent),adapter_path=str(round_dir),adapter_sha256=report['trained_sha256'])
                write(STATE/'rollback-config.json',old_config)
                write(config_path,new_config);write(active_path,new_config)
                state.update(phase='accepted',adapter_sha256=report['trained_sha256'],note='Real adapter update passed the limited coding gates')
            else:
                state.update(phase='rejected',note='Candidate failed checks; previous serving weights kept',reasons=report['reasons'])
            state['report']=str(round_dir/'report.json')
        except Exception as error:
            write(config_path,old_config)
            state.update(phase='paused' if Knowledge().state('enabled')!='true' else 'failed',note=str(error))
        finally:
            state.pop('pid',None);write(STATE/'status.json',state)
            try:
                result=subprocess.run(['/usr/bin/python3',str(ROOT/'launch_assistant.py'),'--no-browser'],capture_output=True,text=True,timeout=65)
                failed=bool(result.returncode)
            except subprocess.TimeoutExpired:failed=True
            if failed:
                write(config_path,old_config)
                try:
                    stop_model()
                    subprocess.run(['/usr/bin/python3',str(ROOT/'launch_assistant.py'),'--no-browser'],capture_output=True,timeout=65)
                except (subprocess.TimeoutExpired,RuntimeError):pass
                state.update(phase='deployment_failed',note='Could not load candidate; serving configuration rolled back')
                if active:write(active_path,active)
                elif active_path.exists():active_path.unlink()
                write(STATE/'status.json',state)
        print(json.dumps(state,indent=2),flush=True);return state

def maybe_start():
    from knowledge import Knowledge
    if Knowledge().state('enabled')!='true':return dict(phase='paused')
    current=status()
    if current.get('phase') in {'training','evaluating'} and current.get('pid'):
        try:os.kill(current['pid'],0);return current
        except ProcessLookupError:pass
    today=datetime.now(ZoneInfo('America/Toronto')).date().isoformat()
    if current.get('attempt_day')==today or current.get('last_scan_day')==today:return current
    STATE.mkdir(parents=True,exist_ok=True)
    with (STATE/'scheduler.log').open('a') as log:
        p=subprocess.Popen(['/usr/bin/python3',str(ROOT/'weight_jobs.py'),'run'],stdout=log,stderr=log,
            stdin=subprocess.DEVNULL,start_new_session=True)
    return dict(phase='queued',pid=p.pid)

if __name__=='__main__':run()
