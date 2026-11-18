"""Authenticated loopback inference using the actually selected MLX adapter."""
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import hmac
import json
from pathlib import Path
import threading
import time

import mlx.core as mx
from mlx_lm import load,generate
from mlx_lm.sample_utils import make_sampler

CACHE=Path.home()/'Library/Caches/UltimateOpenAI'
CONFIG=json.loads((CACHE/'active-model.json').read_text())
KEY=(CACHE/'model-key.txt').read_text().strip()
LOCK=threading.Lock()
mx.set_memory_limit(3*1024**3);mx.set_cache_limit(128*1024**2)
MODEL,TOKENIZER=load(CONFIG['model_path'],adapter_path=CONFIG.get('adapter_path'),trust_remote_code=False)
mx.eval(MODEL.parameters())

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def reply(self,data,code=200):
        raw=json.dumps(data,ensure_ascii=False).encode();self.send_response(code)
        self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)))
        self.end_headers();self.wfile.write(raw)
    def do_GET(self):
        if self.path=='/health':self.reply(dict(status='ok',engine='mlx',adapter_sha256=CONFIG.get('adapter_sha256')))
        else:self.reply(dict(error='Not found'),404)
    def do_POST(self):
        if not hmac.compare_digest(self.headers.get('Authorization',''),'Bearer '+KEY):
            self.reply(dict(error='Unauthorized'),401);return
        if self.path!='/v1/chat/completions':self.reply(dict(error='Not found'),404);return
        try:
            size=int(self.headers.get('Content-Length','0'))
            if not 0<size<=32000:raise ValueError('Invalid input size')
            data=json.loads(self.rfile.read(size));messages=data.get('messages',[])
            if not messages or len(messages)>8:raise ValueError('Invalid messages')
            if any(r.get('role') not in {'user','assistant','system'} or not isinstance(r.get('content'),str) for r in messages):
                raise ValueError('Invalid message format')
            prompt=TOKENIZER.apply_chat_template(messages,tokenize=False,add_generation_prompt=True)
            if len(TOKENIZER.encode(prompt))>4096:raise ValueError('Please shorten this conversation')
            with LOCK:
                text=generate(MODEL,TOKENIZER,prompt=prompt,max_tokens=min(1024,max(1,int(data.get('max_tokens',800)))),sampler=make_sampler(temp=0),verbose=False)
                mx.clear_cache()
            self.reply(dict(model=CONFIG['label'],choices=[dict(index=0,message=dict(role='assistant',content=text),finish_reason='stop')],
                weight_adapter_sha256=CONFIG.get('adapter_sha256')))
        except Exception as error:self.reply(dict(error=str(error)),400)

if __name__=='__main__':
    print('MLX coding model ready; selected adapter:',CONFIG.get('adapter_sha256','base only'),flush=True)
    ThreadingHTTPServer(('127.0.0.1',CONFIG['port']),Handler).serve_forever()
