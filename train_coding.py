"""Actual local QLoRA optimization, held-out evaluation and candidate artifact."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
import math
from pathlib import Path
import random
import shutil
import time

HOME=Path.home()/'Library/Application Support/UltimateOpenAI'
CACHE=Path.home()/'Library/Caches/UltimateOpenAI'
MODEL=CACHE/'mlx-qwen2.5-coder-1.5b-4bit'
LORA=dict(rank=4,scale=8.0,dropout=0.0,keys=['self_attn.q_proj','self_attn.v_proj'])

def atomic_json(path,value):
    temp=path.with_suffix('.tmp');temp.write_text(json.dumps(value,ensure_ascii=False,indent=2));temp.replace(path)

def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()

def build_windows(records,tokenizer,length=128):
    """Split whole documents before token windows. Stable source IDs survive commits."""
    sets={name:[] for name in ['train','valid','audit']};manifest=[]
    for record in records:
        tokens=tokenizer.encode(record['text'])
        positions=list(range(0,max(1,len(tokens)-length),length))
        rng=random.Random(record['id']);rng.shuffle(positions)
        limit=48 if record['split']=='train' else 16
        chosen=[]
        for offset in positions[:limit]:
            seq=tokens[offset:offset+length+1]
            if len(seq)<32:continue
            item=dict(tokens=seq,source=record['id'],kind=record['kind'])
            sets[record['split']].append(item);chosen.append(offset)
            # Equalize code versus the much longer prose/style guides.
            if record['split']=='train' and record['kind']=='code':sets['train'].append(item)
        manifest.append({k:record[k] for k in ['id','revision','url','license','license_notice','sha256','split','kind']}|dict(attribution=record.get('attribution',record['repository'])))
    if any(not values for values in sets.values()):raise ValueError('Incomplete document-separated datasets')
    return sets,manifest

def policy(before,after,coding_before,coding_after,changed):
    reasons=[]
    if not changed:reasons.append('Adapter weights did not change')
    if not math.isfinite(after['valid']) or after['valid']>before['valid']*.995:
        reasons.append('Held-out validation loss did not improve by at least 0.5%')
    if not math.isfinite(after['audit']) or after['audit']>before['audit']*1.01:
        reasons.append('Second held-out document loss regressed by more than 1%')
    if coding_after['passes']<coding_before['passes']:reasons.append('Executable Python coding score regressed')
    return not reasons,reasons

def main():
    p=argparse.ArgumentParser();p.add_argument('--round',required=True);p.add_argument('--steps',type=int,default=100)
    p.add_argument('--learning-rate',type=float,default=.00001);p.add_argument('--resume-adapter')
    args=p.parse_args()
    if not 1<=args.steps<=120 or not 0<args.learning_rate<=.00005:raise ValueError('Training budget exceeded')
    import mlx.core as mx
    import mlx.nn as nn
    import mlx.optimizers as optim
    from mlx.utils import tree_flatten
    from mlx_lm import load,generate
    from mlx_lm.sample_utils import make_sampler
    from mlx_lm.tuner.utils import linear_to_lora_layers
    from coding_bench import evaluate as coding_evaluate

    mx.set_memory_limit(3*1024**3);mx.set_cache_limit(128*1024**2);mx.random.seed(42)
    target=Path(args.round);target.mkdir(parents=True,exist_ok=True)
    corpus=json.loads((HOME/'coding-corpus/manifest.json').read_text())
    model,tokenizer=load(str(MODEL),trust_remote_code=False)
    model.freeze();linear_to_lora_layers(model,4,LORA)
    if args.resume_adapter:model.load_weights(str(Path(args.resume_adapter)/'adapters.safetensors'),strict=False)
    mx.eval(model.parameters())
    sets,source_manifest=build_windows(corpus['records'],tokenizer)
    atomic_json(target/'sources.json',dict(sources=source_manifest,corpus_digest=corpus['digest'],
        counts={k:len(v) for k,v in sets.items()},notices=corpus['notices'],excluded=corpus['excluded']))
    (target/'notices').mkdir(exist_ok=True)
    for notice in corpus['notices']:
        shutil.copy2(HOME/'coding-corpus'/notice['file'],target/'notices'/notice['file'])
    config=dict(fine_tune_type='lora',num_layers=4,lora_parameters=LORA,base_model=str(MODEL))
    atomic_json(target/'adapter_config.json',config)
    original={k:mx.array(v) for k,v in tree_flatten(model.trainable_parameters())};mx.eval(original)
    mx.save_safetensors(str(target/'initial.safetensors'),original)
    count=sum(v.size for v in original.values());print('Actual trainable adapter parameters:',count,flush=True)

    def batch(row):
        seq=row['tokens'];n=len(seq)-1;pad=129-len(seq)
        data=mx.array([seq+[tokenizer.eos_token_id]*pad])
        return data[:,:-1],data[:,1:],mx.array([[1.0]*n+[0.0]*(128-n)])
    def loss_fn(net,x,y,mask):return (nn.losses.cross_entropy(net(x),y)*mask).sum()/mask.sum()
    def losses():
        model.eval();values={}
        for name in ['valid','audit']:
            measured=[]
            for row in sets[name]:
                loss=loss_fn(model,*batch(row));mx.eval(loss);measured.append(float(loss))
            values[name]=sum(measured)/len(measured)
        return values
    def answer(prompt):
        model.eval();text=tokenizer.apply_chat_template([dict(role='user',content=prompt)],tokenize=False,add_generation_prompt=True)
        return generate(model,tokenizer,prompt=text,max_tokens=320,sampler=make_sampler(temp=0),verbose=False)

    print('Evaluating baseline held-out source loss and executable coding tests',flush=True)
    before=losses();coding_before=coding_evaluate(answer)
    atomic_json(target/'before.json',dict(losses=before,coding=coding_before))
    print('Baseline losses:',before,flush=True)
    optimizer=optim.Adam(learning_rate=args.learning_rate)
    gradient=nn.value_and_grad(model,loss_fn);rng=random.Random(42);history=[];started=time.monotonic()
    train_tokens=0;seen_sources=set()
    for step in range(args.steps):
        if step%10==0:
            from knowledge import Knowledge
            if Knowledge().state('enabled')!='true':raise RuntimeError('Paused by user; candidate not deployed')
        model.train();row=rng.choice(sets['train']);seen_sources.add(row['source']);x,y,mask=batch(row)
        loss,grads=gradient(model,x,y,mask);optimizer.update(model,grads)
        mx.eval(model.trainable_parameters(),optimizer.state,loss)
        train_tokens+=len(row['tokens'])-1
        if (step+1)%10==0 or step+1==args.steps:
            item=dict(step=step+1,train_loss=float(loss),seconds=time.monotonic()-started,training_tokens=train_tokens,
                active_gb=mx.get_active_memory()/1024**3,peak_gb=mx.get_peak_memory()/1024**3)
            history.append(item);atomic_json(target/'progress.json',item);print(json.dumps(item),flush=True)
            mx.clear_cache()
    trained=dict(tree_flatten(model.trainable_parameters()));mx.eval(trained)
    changed=sum(bool(mx.any(v!=original[k]).item()) for k,v in trained.items())
    delta=sum(float(mx.sum((v-original[k]).astype(mx.float32)**2)) for k,v in trained.items())**.5
    mx.save_safetensors(str(target/'adapters.safetensors'),trained)
    after=losses();coding_after=coding_evaluate(answer)
    passed,reasons=policy(before,after,coding_before,coding_after,changed>0)
    report=dict(state='accepted' if passed else 'rejected',reasons=reasons,steps=args.steps,
        learning_rate=args.learning_rate,trainable_parameters=count,changed_tensors=changed,delta_l2=delta,
        initial_sha256=sha(target/'initial.safetensors'),trained_sha256=sha(target/'adapters.safetensors'),
        before=before,after=after,coding_before=coding_before,coding_after=coding_after,history=history,
        training_tokens=train_tokens,training_seconds=time.monotonic()-started,peak_memory_gb=mx.get_peak_memory()/1024**3,
        sampled_training_documents=sorted(seen_sources),
        corpus_digest=corpus['digest'],timestamp=datetime.now(timezone.utc).isoformat(),
        source_scope='Selected licensed official coding guidance/source/tests. No generated answers or private files.',
        limitation='Small local held-out text and Python checks, not broad capability proof. Base quantized weights frozen; trained LoRA weights alter effective model weights.')
    atomic_json(target/'report.json',report)
    print('Candidate:',report['state'],'changed tensors:',changed,'loss:',before,'->',after,flush=True)

if __name__=='__main__':main()
