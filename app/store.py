import contextlib,hashlib,json,secrets,sqlite3,threading,time,uuid
from pathlib import Path
from .authority import PLANS

class Store:
 def __init__(self,path,authority):
  Path(path).parent.mkdir(parents=True,exist_ok=True)
  self.db=sqlite3.connect(path,check_same_thread=False,isolation_level=None);self.db.row_factory=sqlite3.Row
  self.db.execute('PRAGMA journal_mode=WAL');self.db.execute('PRAGMA busy_timeout=10000');self.lock=threading.RLock();self.authority=authority
  self.db.executescript('''
   CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
   CREATE TABLE IF NOT EXISTS orders(id TEXT PRIMARY KEY,user_id INTEGER NOT NULL,chat_id INTEGER NOT NULL,username TEXT,plan TEXT NOT NULL,price INTEGER NOT NULL,duration INTEGER NOT NULL,bank TEXT,state TEXT NOT NULL,receipt_chat INTEGER,receipt_message INTEGER,receipt_unique TEXT,created_at INTEGER NOT NULL,reviewed_at INTEGER,reviewer_id INTEGER,license_id TEXT UNIQUE);
   CREATE UNIQUE INDEX IF NOT EXISTS receipt_once ON orders(receipt_unique) WHERE receipt_unique IS NOT NULL;
   CREATE TABLE IF NOT EXISTS licenses(id TEXT PRIMARY KEY,order_id TEXT UNIQUE NOT NULL,key_hash TEXT UNIQUE NOT NULL,key_encrypted TEXT NOT NULL,plan TEXT NOT NULL,duration INTEGER NOT NULL,device_hash TEXT,activated_at INTEGER,expires_at INTEGER,revoked INTEGER NOT NULL DEFAULT 0,created_at INTEGER NOT NULL);
   CREATE TABLE IF NOT EXISTS updates(id INTEGER PRIMARY KEY,received_at INTEGER NOT NULL);
   CREATE TABLE IF NOT EXISTS outbox(id INTEGER PRIMARY KEY AUTOINCREMENT,dedupe TEXT UNIQUE NOT NULL,kind TEXT NOT NULL,order_id TEXT NOT NULL,state TEXT NOT NULL DEFAULT 'pending',attempts INTEGER NOT NULL DEFAULT 0,next_try INTEGER NOT NULL DEFAULT 0,last_error TEXT);
  ''')
  columns={r['name']for r in self.db.execute('PRAGMA table_info(licenses)')}
  for name,definition in [('frozen_at','INTEGER'),('paused_seconds','INTEGER NOT NULL DEFAULT 0')]:
   if name not in columns:self.db.execute('ALTER TABLE licenses ADD COLUMN '+name+' '+definition)
  self.db.execute('''CREATE TABLE IF NOT EXISTS key_audit(id INTEGER PRIMARY KEY AUTOINCREMENT,license_id TEXT NOT NULL,admin_id INTEGER NOT NULL,action TEXT NOT NULL,created_at INTEGER NOT NULL)''')
 @contextlib.contextmanager
 def transaction(self):
  with self.lock:
   self.db.execute('BEGIN IMMEDIATE')
   try:yield self.db;self.db.execute('COMMIT')
   except BaseException:self.db.execute('ROLLBACK');raise
 def setting(self,key):
  with self.lock:r=self.db.execute('SELECT value FROM settings WHERE key=?',(key,)).fetchone();return r['value']if r else None
 def claim_owner(self,user_id,chat_id):
  with self.transaction()as db:
   old=db.execute("SELECT value FROM settings WHERE key='admin_user_id'").fetchone()
   if old and int(old['value'])!=user_id:return False
   db.execute("INSERT OR IGNORE INTO settings VALUES('admin_user_id',?)",(str(user_id),));db.execute("INSERT OR REPLACE INTO settings VALUES('admin_chat_id',?)",(str(chat_id),));return True
 def admin(self,user_id):return self.setting('admin_user_id')==str(user_id)
 def language(self,user_id):
  value=self.setting('lang:'+str(user_id));return value if value in('ru','en')else None
 def set_language(self,user_id,value):
  if value not in('ru','en'):raise ValueError('language')
  with self.lock:self.db.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',('lang:'+str(user_id),value))
 def owner_order(self,user,plan,request_id):
  if not self.admin(user['id']):raise PermissionError('admin_required')
  p=PLANS[plan];now=int(time.time());oid='O'+hashlib.sha256((str(user['id'])+'|'+request_id).encode()).hexdigest()[:11].upper()
  with self.transaction()as db:
   old=db.execute('SELECT * FROM orders WHERE id=?',(oid,)).fetchone()
   if old:
    if old['user_id']!=user['id']or old['plan']!=plan or old['bank']!='owner':raise ValueError('owner_order_conflict')
    return dict(old)
   key=self.authority.new_key(plan);lid=str(uuid.uuid4())
   db.execute("UPDATE orders SET state='cancelled' WHERE user_id=? AND state IN ('select_bank','await_receipt')",(user['id'],))
   db.execute("INSERT INTO orders(id,user_id,chat_id,username,plan,price,duration,bank,state,created_at,reviewed_at,reviewer_id,license_id)VALUES(?,?,?,?,?,0,?,'owner','approved',?,?,?,?)",(oid,user['id'],user['id'],user.get('username'),plan,p['duration'],now,now,user['id'],lid))
   db.execute('INSERT INTO licenses(id,order_id,key_hash,key_encrypted,plan,duration,created_at)VALUES(?,?,?,?,?,?,?)',(lid,oid,self.authority.digest(key),self.authority.encrypt(key),plan,p['duration'],now))
   db.execute('INSERT INTO outbox(dedupe,kind,order_id)VALUES(?,?,?)',('deliver:'+oid,'license_delivery',oid))
  return self.order(oid)
 def once(self,update_id):
  with self.transaction()as db:
   return db.execute('INSERT OR IGNORE INTO updates VALUES(?,?)',(update_id,int(time.time()))).rowcount==1
 def seen(self,update_id):
  with self.lock:return self.db.execute('SELECT 1 FROM updates WHERE id=?',(update_id,)).fetchone()is not None
 def my_orders(self,user_id):
  with self.lock:return[dict(r)for r in self.db.execute('SELECT * FROM orders WHERE user_id=? ORDER BY created_at DESC LIMIT 10',(user_id,))]
 def new_order(self,user,plan):
  p=PLANS[plan];oid=secrets.token_hex(6).upper()
  with self.transaction()as db:
   db.execute("UPDATE orders SET state='cancelled' WHERE user_id=? AND state IN ('select_bank','await_receipt')",(user['id'],))
   db.execute('INSERT INTO orders(id,user_id,chat_id,username,plan,price,duration,state,created_at)VALUES(?,?,?,?,?,?,?,\'select_bank\',?)',(oid,user['id'],user['id'],user.get('username'),plan,p['price'],p['duration'],int(time.time())))
  return self.order(oid)
 def order(self,oid):
  with self.lock:r=self.db.execute('SELECT * FROM orders WHERE id=?',(oid,)).fetchone();return dict(r)if r else None
 def bank(self,oid,user_id,bank):
  with self.transaction()as db:
   return db.execute("UPDATE orders SET bank=?,state='await_receipt' WHERE id=? AND user_id=? AND state IN ('select_bank','await_receipt')",(bank,oid,user_id)).rowcount==1
 def latest_waiting(self,user_id):
  with self.lock:r=self.db.execute("SELECT * FROM orders WHERE user_id=? AND state='await_receipt' ORDER BY created_at DESC LIMIT 1",(user_id,)).fetchone();return dict(r)if r else None
 def receipt(self,oid,user_id,chat_id,message_id,unique):
  with self.transaction()as db:
   duplicate=db.execute('SELECT id FROM orders WHERE receipt_unique=?',(unique,)).fetchone()
   if duplicate:return False,'duplicate'
   changed=db.execute("UPDATE orders SET state='await_review',receipt_chat=?,receipt_message=?,receipt_unique=? WHERE id=? AND user_id=? AND state='await_receipt'",(chat_id,message_id,unique,oid,user_id)).rowcount
   if not changed:return False,'state'
   db.execute('INSERT OR IGNORE INTO outbox(dedupe,kind,order_id)VALUES(?,?,?)',('receipt:'+oid,'admin_receipt',oid))
   return True,'queued'
 def approve(self,oid,admin_id,now=None):
  if not self.admin(admin_id):raise PermissionError('admin_required')
  now=int(time.time())if now is None else now
  with self.transaction()as db:
   row=db.execute('SELECT * FROM orders WHERE id=?',(oid,)).fetchone()
   if not row:raise ValueError('order_missing')
   if row['state']=='approved':return self.license_for_order(oid)
   if row['state']!='await_review':raise ValueError('order_not_waiting')
   key=self.authority.new_key(row['plan']);lid=str(uuid.uuid4())
   db.execute('INSERT INTO licenses(id,order_id,key_hash,key_encrypted,plan,duration,created_at)VALUES(?,?,?,?,?,?,?)',(lid,oid,self.authority.digest(key),self.authority.encrypt(key),row['plan'],row['duration'],now))
   db.execute("UPDATE orders SET state='approved',reviewed_at=?,reviewer_id=?,license_id=? WHERE id=?",(now,admin_id,lid,oid))
   db.execute('INSERT OR IGNORE INTO outbox(dedupe,kind,order_id)VALUES(?,?,?)',('deliver:'+oid,'license_delivery',oid))
  return self.license_for_order(oid)
 def reject(self,oid,admin_id):
  if not self.admin(admin_id):raise PermissionError('admin_required')
  with self.transaction()as db:
   changed=db.execute("UPDATE orders SET state='rejected',reviewed_at=?,reviewer_id=? WHERE id=? AND state='await_review'",(int(time.time()),admin_id,oid)).rowcount
   if changed:db.execute('INSERT OR IGNORE INTO outbox(dedupe,kind,order_id)VALUES(?,?,?)',('reject:'+oid,'rejection',oid))
   return bool(changed)
 def license_for_order(self,oid):
  with self.lock:r=self.db.execute('SELECT * FROM licenses WHERE order_id=?',(oid,)).fetchone();return dict(r)if r else None
 def admin_keys(self,admin_id,limit=12):
  if not self.admin(admin_id):raise PermissionError('admin_required')
  with self.lock:return[dict(r)for r in self.db.execute('SELECT l.*,o.user_id,o.username FROM licenses l JOIN orders o ON o.id=l.order_id ORDER BY l.created_at DESC,l.rowid DESC LIMIT ?',(limit,))]
 def find_key(self,admin_id,text):
  if not self.admin(admin_id):raise PermissionError('admin_required')
  text=text.strip()
  with self.lock:
   r=self.db.execute('SELECT * FROM licenses WHERE key_hash=? OR order_id=?',(self.authority.digest(text),text.upper())).fetchone();return dict(r)if r else None
 def key_action(self,admin_id,oid,action,now=None):
  if not self.admin(admin_id):raise PermissionError('admin_required')
  now=int(time.time())if now is None else now
  if action not in('reset','freeze','unfreeze','block','unblock'):raise ValueError('key_action')
  with self.transaction()as db:
   r=db.execute('SELECT * FROM licenses WHERE order_id=?',(oid,)).fetchone()
   if not r:raise ValueError('unknown_key')
   changed=False
   if action=='reset':
    changed=db.execute('UPDATE licenses SET device_hash=NULL WHERE id=? AND device_hash IS NOT NULL',(r['id'],)).rowcount>0
   elif action=='freeze'and r['frozen_at']is None:
    if r['expires_at']is not None and now>=r['expires_at']:raise ValueError('expired')
    db.execute('UPDATE licenses SET frozen_at=? WHERE id=?',(now,r['id']));changed=True
   elif action=='unfreeze'and r['frozen_at']is not None:
    elapsed=max(0,now-r['frozen_at'])if r['activated_at']is not None else 0
    db.execute('UPDATE licenses SET frozen_at=NULL,paused_seconds=paused_seconds+?,expires_at=CASE WHEN expires_at IS NULL THEN NULL ELSE expires_at+? END WHERE id=?',(elapsed,elapsed,r['id']));changed=True
   elif action in('block','unblock'):
    value=int(action=='block');changed=db.execute('UPDATE licenses SET revoked=? WHERE id=? AND revoked!=?',(value,r['id'],value)).rowcount>0
   if changed:db.execute('INSERT INTO key_audit(license_id,admin_id,action,created_at)VALUES(?,?,?,?)',(r['id'],admin_id,action,now))
  return self.license_for_order(oid)
 def activate(self,key,device_hash,now=None):
  now=int(time.time())if now is None else now
  with self.transaction()as db:
   r=db.execute('SELECT * FROM licenses WHERE key_hash=?',(self.authority.digest(key),)).fetchone()
   if not r:raise ValueError('unknown_key')
   if r['revoked']:raise ValueError('revoked')
   if r['frozen_at']is not None:raise ValueError('frozen')
   if r['device_hash']and r['device_hash']!=device_hash:raise ValueError('device_mismatch')
   if r['activated_at']is None:
    db.execute('UPDATE licenses SET device_hash=?,activated_at=?,expires_at=? WHERE id=? AND activated_at IS NULL',(device_hash,now,now+r['duration'],r['id']))
    r=db.execute('SELECT * FROM licenses WHERE id=?',(r['id'],)).fetchone()
   if now>=r['expires_at']:raise ValueError('expired')
   if r['device_hash']is None:
    db.execute('UPDATE licenses SET device_hash=? WHERE id=? AND device_hash IS NULL',(device_hash,r['id']))
    r=db.execute('SELECT * FROM licenses WHERE id=?',(r['id'],)).fetchone()
   return dict(r)
 def jobs(self):
  with self.lock:return[dict(r)for r in self.db.execute("SELECT * FROM outbox WHERE state='pending' AND next_try<=? ORDER BY id LIMIT 20",(int(time.time()),))]
 def done(self,jid):
  with self.lock:self.db.execute("UPDATE outbox SET state='done',last_error=NULL WHERE id=?",(jid,))
 def retry(self,jid,error):
  with self.lock:self.db.execute("UPDATE outbox SET attempts=attempts+1,next_try=?,last_error=? WHERE id=?",(int(time.time())+30,error[:80],jid))
 def stats(self):
  with self.lock:return dict(self.db.execute("SELECT COUNT(*) orders,SUM(CASE WHEN state='approved' THEN price ELSE 0 END) revenue,SUM(CASE WHEN state='await_review' THEN 1 ELSE 0 END) pending FROM orders").fetchone())

