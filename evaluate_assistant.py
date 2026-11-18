"""Small reproducible acceptance checks; not a broad capability benchmark."""
import argparse
import json
from pathlib import Path
import re
import time
import urllib.request

ROOT=Path(__file__).resolve().parent
CASES=[
 ('arithmetic','What is 17 multiplied by 19? Answer with the number only.'),
 ('decimals','Which number is larger: 9.9 or 9.11?'),
 ('geography','What is the capital of France?'),
 ('biology','In aerobic cellular respiration, is oxygen consumed or released? What gas is produced?'),
 ('python','In Python, x = [1, 2]; y = x; y.append(3). What is x now?'),
 ('arabic','Translate Good morning into Arabic. Give only the Arabic translation.'),
 ('uncertainty','Use only this text: Luma Lab has three rooms. Who founded Luma Lab? If unstated, say not stated.'),
 ('rate','A car travels 60 km in 1.5 hours. What is its average speed in km/h?')]

def grade(name,answer):
    a=answer.casefold(); compact=re.sub(r'\s','',a)
    checks={
      'arithmetic':lambda:'323' in a,
      'decimals':lambda:bool(re.search(r'9\.9\s*(?:is|>|,?\s*(?:because|since))',a)) or a.strip() in {'9.9','9.9.'},
      'geography':lambda:'paris' in a,
      'biology':lambda:'consum' in a and ('carbon dioxide' in a or 'co2' in a) and not re.search(r'oxygen is (?:also )?released',a),
      'python':lambda:'[1,2,3]' in compact,
      'arabic':lambda:'صباح الخير' in re.sub('[\u064b-\u065f]','',answer),
      'uncertainty':lambda:any(s in a for s in ['not stated','not mentioned','not provided','unknown','cannot be determined']),
      'rate':lambda:bool(re.search(r'\b40\b',a))}
    return bool(checks[name]())

def main():
    p=argparse.ArgumentParser();p.add_argument('--port',type=int,default=18879);p.add_argument('--name',default='qwen2.5-1.5b');args=p.parse_args()
    key=(Path.home()/'Library/Caches/UltimateOpenAI/model-key.txt').read_text().strip()
    rows=[]
    for name,q in CASES:
        start=time.monotonic()
        body=json.dumps(dict(messages=[dict(role='system',content='Answer accurately and briefly. Say when the information is not provided.'),dict(role='user',content=q)],temperature=0,max_tokens=160)).encode()
        req=urllib.request.Request(f'http://127.0.0.1:{args.port}/v1/chat/completions',data=body,
            headers={'Content-Type':'application/json','Authorization':'Bearer '+key})
        with urllib.request.urlopen(req,timeout=180) as r: data=json.load(r)
        answer=data['choices'][0]['message']['content']; passed=grade(name,answer)
        rows.append(dict(name=name,question=q,answer=answer,passed=passed,seconds=time.monotonic()-start))
        print(name,passed,answer[:160],flush=True)
    target=ROOT/'evaluations';target.mkdir(exist_ok=True)
    (target/(args.name+'.json')).write_text(json.dumps(rows,ensure_ascii=False,indent=2))
    old=target/'smollm2-baseline.json'
    if old.exists():
        baseline=json.loads(old.read_text())
        for row in baseline:row['passed']=grade(row['name'],row['answer'])
        comparison=dict(baseline_passes=sum(r['passed'] for r in baseline),candidate_passes=sum(r['passed'] for r in rows),count=len(rows),
          baseline=baseline,candidate=rows,limitation='Eight transparent, narrow acceptance cases with pattern checks and raw outputs; not broad factual accuracy evidence.')
        (target/'comparison.json').write_text(json.dumps(comparison,ensure_ascii=False,indent=2))
        print('Comparison',comparison['baseline_passes'],comparison['candidate_passes'],len(rows),flush=True)

if __name__=='__main__':main()
