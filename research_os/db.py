"""SQLite for development; official Turso SQL-over-HTTP for deployment.
No dependency on a native or deprecated Python SDK. Same parameterized SQL.
"""
import os,sqlite3,base64,threading
from pathlib import Path
from urllib.parse import urlparse
import requests
class DB:
 def __init__(self,path=None,url=None,token=None):
  self.url=url if url is not None else os.getenv('TURSO_DATABASE_URL','')
  self.token=token if token is not None else os.getenv('TURSO_AUTH_TOKEN','')
  self.path=path or os.getenv('LOCAL_DB_PATH','data/research.db')
  self.remote=bool(self.url)
  if self.remote:
   p=urlparse(self.url.replace('libsql://','https://',1).replace('turso://','https://',1))
   if p.scheme!='https' or not p.hostname or not p.hostname.endswith(('.turso.io','.turso.tech')) or p.username or p.password:raise ValueError('Expected official HTTPS Turso endpoint')
   if not self.token:raise ValueError('TURSO_AUTH_TOKEN missing')
   self.endpoint='https://'+p.netloc+'/v2/pipeline'
  else:Path(self.path).parent.mkdir(parents=True,exist_ok=True)
 def execute(self,sql,args=()):
  if not self.remote:
   with sqlite3.connect(self.path,timeout=30) as c:
    c.row_factory=sqlite3.Row;c.execute('PRAGMA foreign_keys=ON');c.execute('PRAGMA journal_mode=WAL')
    cur=c.execute(sql,args);rows=[dict(r) for r in cur.fetchall()] if cur.description else []
    return {'rows':rows,'changes':max(0,cur.rowcount)}
  def encode(v):
   if v is None:return {'type':'null'}
   if isinstance(v,(int,bool)):return {'type':'integer','value':str(int(v))}
   if isinstance(v,float):return {'type':'float','value':v}
   return {'type':'text','value':str(v)}
  payload={'requests':[{'type':'execute','stmt':{'sql':sql,'args':[encode(v) for v in args]}},{'type':'close'}]}
  r=requests.post(self.endpoint,headers={'Authorization':'Bearer '+self.token,'Content-Type':'application/json'},json=payload,timeout=45);r.raise_for_status()
  result=r.json()['results'][0]
  if result['type']=='error':raise RuntimeError('Database query failed: '+result.get('error',{}).get('message','unknown'))
  result=result['response']['result'];cols=[c['name'] for c in result['cols']]
  def decode(v):
   if v['type']=='null':return None
   if v['type']=='integer':return int(v['value'])
   if v['type']=='float':return float(v['value'])
   return v.get('value')
  return {'rows':[dict(zip(cols,map(decode,row))) for row in result['rows']],'changes':result.get('affected_row_count',0)}
 def all(self,sql,args=()):return self.execute(sql,args)['rows']
 def one(self,sql,args=()):
  rows=self.all(sql,args);return rows[0] if rows else None
 def migrate(self):
  for statement in Path(__file__).with_name('schema.sql').read_text().split(';'):
   if statement.strip():self.execute(statement)
  from .core import now
  self.execute('INSERT OR IGNORE INTO schema_versions VALUES(1,?)',(now(),))
 def index_missing(self):
  self.execute('INSERT INTO item_search(rowid,id,title,summary) SELECT i.rowid,i.id,i.title,i.summary FROM items i WHERE NOT EXISTS(SELECT 1 FROM item_search s WHERE s.rowid=i.rowid)')
