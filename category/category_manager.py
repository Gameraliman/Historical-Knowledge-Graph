import json,subprocess,sys
from pathlib import Path
BASE_DIR=Path(__file__).resolve().parents[1]; CATEGORIES_FILE=BASE_DIR/'data/categories.json'; OPERATION3=BASE_DIR/'operation3.py'
def _ensure():
 CATEGORIES_FILE.parent.mkdir(parents=True,exist_ok=True)
 if not CATEGORIES_FILE.exists(): CATEGORIES_FILE.write_text('[]',encoding='utf-8')
def normalize_topic(topic): return ' '.join(topic.strip().split())
def load_categories():
 _ensure()
 try:
  d=json.loads(CATEGORIES_FILE.read_text(encoding='utf-8')); return d if isinstance(d,list) else []
 except Exception:return []
def add_category(topic,run_operation=True):
 topic=normalize_topic(topic)
 if not topic: raise ValueError('topic is empty')
 cats=load_categories()
 if any(normalize_topic(str(x)).casefold()==topic.casefold() for x in cats): raise ValueError('topic already registered')
 cats.append(topic); tmp=CATEGORIES_FILE.with_suffix('.tmp'); tmp.write_text(json.dumps(cats,ensure_ascii=False,indent=2),encoding='utf-8'); tmp.replace(CATEGORIES_FILE)
 result=None
 if run_operation and OPERATION3.exists(): result=subprocess.run([sys.executable,str(OPERATION3),topic],cwd=str(BASE_DIR),capture_output=True,text=True,timeout=300)
 return topic,result
