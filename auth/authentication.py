import hashlib,hmac,json,os,secrets,socket
from pathlib import Path
BASE_DIR=Path(__file__).resolve().parents[1]; USERS_FILE=BASE_DIR/'data/users.json'
ROLE_MAIN_ADMIN='main admin'; ROLE_ADMIN='admin'; ROLE_USER='user'
def _ensure():
 USERS_FILE.parent.mkdir(parents=True,exist_ok=True)
 if not USERS_FILE.exists(): USERS_FILE.write_text('[]',encoding='utf-8')
def load_users():
 _ensure()
 try:
  d=json.loads(USERS_FILE.read_text(encoding='utf-8')); return d if isinstance(d,list) else []
 except Exception:return []
def save_users(users):
 _ensure(); tmp=USERS_FILE.with_suffix('.tmp'); tmp.write_text(json.dumps(users,ensure_ascii=False,indent=2),encoding='utf-8'); tmp.replace(USERS_FILE)
def hash_password(password,salt=None):
 salt=salt or secrets.token_hex(16); digest=hashlib.pbkdf2_hmac('sha256',password.encode(),salt.encode(),200000); return f'pbkdf2_sha256$200000${salt}${digest.hex()}'
def verify_password(password,stored):
 if not stored:return False
 if stored.startswith('pbkdf2_sha256$'):
  try:
   _,it,salt,exp=stored.split('$',3); got=hashlib.pbkdf2_hmac('sha256',password.encode(),salt.encode(),int(it)); return hmac.compare_digest(got.hex(),exp)
  except Exception:return False
 return hmac.compare_digest(hashlib.sha256(password.encode()).hexdigest(),stored)
def main_admin_enabled():
 machine=os.getenv('DEV_MACHINE_NAME','').strip(); u=os.getenv('MAIN_ADMIN_USERNAME','').strip(); p=os.getenv('MAIN_ADMIN_PASSWORD',''); ph=os.getenv('MAIN_ADMIN_PASSWORD_HASH','').strip()
 return bool(machine and u and (p or ph)) and socket.gethostname().lower()==machine.lower()
def authenticate(username,password):
 username=username.strip()
 if main_admin_enabled() and username==os.getenv('MAIN_ADMIN_USERNAME','').strip():
  if hmac.compare_digest(password,os.getenv('MAIN_ADMIN_PASSWORD','')) or verify_password(password,os.getenv('MAIN_ADMIN_PASSWORD_HASH','')): return {'username':username,'role':ROLE_MAIN_ADMIN}
 for u in load_users():
  if u.get('username')==username and u.get('active',True) and verify_password(password,u.get('password_hash','')): return {'username':username,'role':u.get('role',ROLE_USER)}
 return None
def username_exists(username):
 return any(u.get('username')==username for u in load_users()) or (main_admin_enabled() and username==os.getenv('MAIN_ADMIN_USERNAME','').strip())
def create_user(username,password,role=ROLE_USER):
 username=username.strip()
 if not username or not password: raise ValueError('username and password are required')
 if role not in {ROLE_ADMIN,ROLE_USER}: raise ValueError('invalid role')
 if username_exists(username): raise ValueError('username already exists')
 users=load_users(); users.append({'username':username,'password_hash':hash_password(password),'role':role,'active':True}); save_users(users)
def change_role(username,role):
 if role not in {ROLE_ADMIN,ROLE_USER}: raise ValueError('invalid role')
 users=load_users()
 for u in users:
  if u.get('username')==username: u['role']=role; save_users(users); return
 raise ValueError('user not found')
def delete_user(username):
 users=load_users(); new=[u for u in users if u.get('username')!=username]
 if len(new)==len(users): raise ValueError('user not found')
 save_users(new)
