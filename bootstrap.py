"""Explicit free Apple Silicon installation; ~0.9 GB model download."""
import json
from pathlib import Path
import platform
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parent
CACHE=Path.home()/'Library/Caches/UltimateOpenAI'
HOME=Path.home()/'Library/Application Support/UltimateOpenAI'

def main():
    if platform.system()!='Darwin' or platform.machine()!='arm64':raise SystemExit('This MLX runtime currently requires an Apple Silicon Mac.')
    if sys.version_info<(3,11):raise SystemExit('Use Python 3.11 or newer.')
    CACHE.mkdir(parents=True,exist_ok=True)
    if shutil.disk_usage(CACHE).free<2_000_000_000:raise SystemExit('Need at least 2 GB free for initial setup.')
    env=CACHE/'training-venv';python=env/'bin/python'
    if not python.exists():subprocess.run([sys.executable,'-m','venv',str(env)],check=True)
    subprocess.run([str(python),'-m','pip','install','-r',str(ROOT/'requirements-training.txt')],check=True)
    subprocess.run([sys.executable,str(ROOT/'setup_training.py')],check=True)
    config=CACHE/'active-model.json'
    if not config.exists():config.write_text(json.dumps(dict(engine='mlx',label='Qwen2.5 Coder 1.5B · base model',port=18879,model_path=str(CACHE/'mlx-qwen2.5-coder-1.5b-4bit')),indent=2))
    subprocess.run([sys.executable,str(ROOT/'deploy.py')],check=True)
    subprocess.run([sys.executable,str(HOME/'runtime/launch_assistant.py')],check=True)

if __name__=='__main__':main()
