"""Small coding acceptance tests. Generated code runs only in a restricted child."""
import ast
import json
import re
import subprocess
import time

CASES=[
 dict(name='dedupe',task='Return a new list removing duplicate hashable items while preserving their original order.',tests=[([[3,1,3,2,1]],[3,1,2]),([[]],[]),([['b','a','b']],['b','a'])]),
 dict(name='is_prime',task='Return whether integer n is prime. Handle negative integers, zero and one.',tests=[([-5],False),([1],False),([2],True),([97],True),([100],False)]),
 dict(name='merge_intervals',task='Merge overlapping closed intervals and return sorted intervals as lists. Touching endpoints overlap. Do not mutate the input list.',tests=[([[[5,7],[1,3],[2,4]]],[[1,4],[5,7]]),([[]],[]),([[[1,2],[2,3]]],[[1,3]])]),
 dict(name='binary_search',task='Return the index of target in a sorted list values of unique integers, or -1 when absent.',tests=[([[1,3,5,9],5],2),([[1,3,5,9],2],-1),([[],2],-1)]),
 dict(name='count_words',task='Return a dictionary of word counts. Words are whitespace-separated; compare them in lowercase.',tests=[(['A a b'],{'a':2,'b':1}),([''],{}),(['Hello\nhello world'],{'hello':2,'world':1})]),
 dict(name='chunked',task='Return a list of chunks from list items with at most size items each. Raise ValueError for size <= 0.',tests=[([[1,2,3,4,5],2],[[1,2],[3,4],[5]]),([[],2],[]),([[1],0],'raises:ValueError')]),
 dict(name='balanced_parens',task='Return whether parentheses are balanced in a string text. Ignore non-parenthesis characters.',tests=[(['a(b(c)d)'],True),(['())('],False),(['abc'],True),(['(()'],False)]),
 dict(name='flatten_once',task='Flatten exactly one level of a list of lists items. Return a new list. Do not recursively flatten nested inner values.',tests=[([[[1,2],[3]]],[1,2,3]),([[]],[]),([[[1,[2]],[3]]],[1,[2],3])])]

CALLS={'len','range','sorted','sum','min','max','abs','enumerate','zip','reversed','isinstance','int','str','list','set','tuple','dict','bool','all','any','ValueError'}
ATTRS={'append','extend','pop','get','items','keys','values','sort','strip','lower','upper','split','join','count','index','isdigit','isalpha','isspace','add','fromkeys','copy','setdefault','remove','discard'}

def extract(text):
    match=re.search(r'```(?:python)?\s*\n(.*?)```',text,re.S)
    return match[1].strip() if match else text.strip()

def validate(code,name):
    tree=ast.parse(code)
    funcs={n.name for n in tree.body if isinstance(n,ast.FunctionDef)}
    if name not in funcs:raise ValueError('Expected function missing')
    if any(not isinstance(n,ast.FunctionDef) and not (isinstance(n,ast.Expr) and isinstance(n.value,ast.Constant) and isinstance(n.value.value,str)) for n in tree.body):
        raise ValueError('Only pure function definitions allowed at top level')
    for node in ast.walk(tree):
        if isinstance(node,(ast.Import,ast.ImportFrom,ast.ClassDef,ast.Global,ast.Nonlocal,ast.With,ast.AsyncWith)):
            raise ValueError('Unsupported statement')
        if isinstance(node,ast.FunctionDef) and (node.decorator_list or node.name.startswith('_')):raise ValueError('Unsupported function')
        if isinstance(node,ast.Name) and node.id.startswith('__'):raise ValueError('Private runtime access blocked')
        if isinstance(node,ast.Attribute) and node.attr not in ATTRS:raise ValueError('Unsupported attribute')
        if isinstance(node,ast.Call):
            if isinstance(node.func,ast.Name) and node.func.id not in CALLS|funcs:raise ValueError('Unsupported call')
            if not isinstance(node.func,(ast.Name,ast.Attribute)):raise ValueError('Unsupported dynamic call')
    return tree

def run_code(code,case):
    validate(code,case['name'])
    payload=dict(code=code,case=case,calls=sorted(CALLS))
    wrapper=r'''
import builtins,json,sys,resource,copy
resource.setrlimit(resource.RLIMIT_CPU,(2,2))
resource.setrlimit(resource.RLIMIT_FSIZE,(0,0))
p=json.load(sys.stdin)
space={'__builtins__':{k:getattr(builtins,k) for k in p['calls']}}
exec(compile(p['code'],'<candidate>','exec'),space)
results=[]
for args,expected in p['case']['tests']:
 before=copy.deepcopy(args)
 try:
  result=space[p['case']['name']](*args)
  ok=result==expected
  if p['case']['name']=='merge_intervals':ok=ok and args==before
  results.append(bool(ok))
 except Exception as e:results.append(expected=='raises:'+type(e).__name__)
print(json.dumps(results))
'''
    process=subprocess.Popen(['/usr/bin/python3','-I','-S','-c',wrapper],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
        text=True,env={'PATH':'/usr/bin:/bin','PYTHONHASHSEED':'0'})
    start=time.monotonic();input_data=json.dumps(payload)
    try:
        while True:
            try:
                out,err=process.communicate(input_data,timeout=.1);break
            except subprocess.TimeoutExpired:
                input_data=None
                if time.monotonic()-start>5:raise ValueError('Execution time limit exceeded')
                memory=subprocess.run(['/bin/ps','-o','rss=','-p',str(process.pid)],capture_output=True,text=True)
                if memory.stdout.strip() and int(memory.stdout.strip())>256*1024:raise ValueError('Execution memory limit exceeded')
        if process.returncode:raise ValueError('Restricted execution failed: '+err[-180:])
        return json.loads(out)
    finally:
        if process.poll() is None:process.kill();process.communicate()

def evaluate(generate):
    rows=[]
    for case in CASES:
        prompt=f"Write one Python function named {case['name']}. {case['task']} Return only its code, with no imports or type annotations."
        raw=generate(prompt)
        try:
            code=extract(raw);tests=run_code(code,case);error=None;passed=all(tests)
        except Exception as e:code=extract(raw);tests=[];error=str(e);passed=False
        rows.append(dict(name=case['name'],passed=passed,tests=tests,error=error,code=code))
        print('Coding check',case['name'],passed,flush=True)
    return dict(passes=sum(r['passed'] for r in rows),count=len(rows),cases=rows,
        scope='Eight small Python acceptance programs in a restricted child, not broad multi-language correctness.')
