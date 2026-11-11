import os,secrets,hashlib,hmac,json,re
from pathlib import Path
from datetime import datetime,timezone,timedelta
from contextlib import asynccontextmanager
from fastapi import FastAPI,Request,HTTPException,Depends,Query
from fastapi.responses import FileResponse,JSONResponse,Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel,Field
from .db import DB
from .core import now,RULES
from .catalog import initialize,PENDING
from .analytics import keyword_signals,indicator_stats
STATIC=Path(__file__).parent/'static'
def db():return DB()
def password_hash(password,salt=None):
 salt=salt or secrets.token_hex(16);iterations=600000
 return f'pbkdf2_sha256${iterations}${salt}${hashlib.pbkdf2_hmac("sha256",password.encode(),salt.encode(),iterations).hex()}'
def verify_password(password,encoded):
 try:
  algorithm,iterations,salt,expected=encoded.split('$')
  if algorithm!='pbkdf2_sha256' or not 200000<=int(iterations)<=2000000:return False
  return hmac.compare_digest(hashlib.pbkdf2_hmac('sha256',password.encode(),salt.encode(),int(iterations)).hex(),expected)
 except (ValueError,AttributeError):return False
@asynccontextmanager
async def lifespan(app):
 if os.getenv('RENDER') and not os.getenv('TURSO_DATABASE_URL'):raise RuntimeError('Render requires Turso. Refusing ephemeral SQLite storage.')
 if not os.getenv('ADMIN_PASSWORD_HASH'):raise RuntimeError('Set ADMIN_PASSWORD_HASH. No default password.')
 d=db();d.migrate();initialize(d);d.index_missing();yield
app=FastAPI(title='RESEARCH OS',docs_url=None,redoc_url=None,openapi_url=None,lifespan=lifespan)
@app.middleware('http')
async def security_headers(request,call_next):
 response=await call_next(request);response.headers.update({'X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer','X-Frame-Options':'DENY','Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; form-action 'self'; base-uri 'self'",'Cache-Control':'no-store'})
 if request.url.scheme=='https':response.headers['Strict-Transport-Security']='max-age=31536000'
 return response
def session(request:Request):
 token=request.cookies.get('research_session','')
 row=db().one('SELECT * FROM sessions WHERE token_hash=? AND expires_at>?',(hashlib.sha256(token.encode()).hexdigest(),now())) if token else None
 if not row:raise HTTPException(401,'로그인이 필요합니다.')
 return row

def origin_ok(request):
 origin=request.headers.get('origin');expected=os.getenv('APP_BASE_URL',str(request.base_url).rstrip('/')).rstrip('/')
 return not origin or origin==expected

def write_session(request:Request,user=Depends(session)):
 if not origin_ok(request) or not hmac.compare_digest(request.headers.get('x-csrf-token',''),user['csrf']):raise HTTPException(403,'CSRF verification failed')
 return user
class Login(BaseModel):
 username:str=Field(min_length=1,max_length=100)
 password:str=Field(min_length=1,max_length=1000)
@app.post('/api/login')
def login(b:Login,request:Request):
 if not origin_ok(request):raise HTTPException(403,'Origin denied')
 key=hashlib.sha256(((request.client.host if request.client else '')+'|'+b.username).encode()).hexdigest();d=db();stamp=now();previous=d.one('SELECT * FROM login_attempts WHERE key_hash=?',(key,))
 window=(datetime.now(timezone.utc)-timedelta(minutes=15)).isoformat(timespec='seconds')
 if previous and previous['window_at']>window and previous['count']>=10:raise HTTPException(429,'15분 뒤 다시 시도하세요.')
 d.execute('INSERT INTO login_attempts VALUES(?,1,?) ON CONFLICT(key_hash) DO UPDATE SET count=CASE WHEN window_at<? THEN 1 ELSE count+1 END,window_at=CASE WHEN window_at<? THEN excluded.window_at ELSE window_at END',(key,stamp,window,window))
 if not hmac.compare_digest(b.username,os.getenv('ADMIN_USERNAME','researcher')) or not verify_password(b.password,os.getenv('ADMIN_PASSWORD_HASH','')):raise HTTPException(401,'아이디 또는 비밀번호를 확인하세요.')
 token=secrets.token_urlsafe(48);csrf=secrets.token_urlsafe(32);expiry=(datetime.now(timezone.utc)+timedelta(days=7)).isoformat(timespec='seconds')
 d.execute('DELETE FROM sessions WHERE expires_at<?',(stamp,));d.execute('INSERT INTO sessions VALUES(?,?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),'owner',expiry,csrf));d.execute('DELETE FROM login_attempts WHERE key_hash=?',(key,))
 response=JSONResponse({'ok':True,'csrf':csrf});response.set_cookie('research_session',token,httponly=True,secure=bool(os.getenv('RENDER')) or os.getenv('COOKIE_SECURE')=='true',samesite='strict',max_age=7*86400);return response
@app.get('/api/me')
def me(user=Depends(session)):return {'authenticated':True,'csrf':user['csrf'],'username':os.getenv('ADMIN_USERNAME','researcher')}
@app.post('/api/logout')
def logout(user=Depends(write_session)):
 db().execute('DELETE FROM sessions WHERE token_hash=?',(user['token_hash'],));r=JSONResponse({'ok':True});r.delete_cookie('research_session');return r
class Record(BaseModel):
 id:str=Field(min_length=1,max_length=100)
 bookmarked:bool|None=None
 read:bool|None=None
 note:str|None=Field(default=None,max_length=10000)
 tags:str|None=Field(default=None,max_length=500)
 project:str|None=Field(default=None,max_length=100)
@app.post('/api/record')
def record(b:Record,user=Depends(write_session)):
 d=db()
 if not d.one('SELECT id FROM items WHERE id=?',(b.id,)):raise HTTPException(404,'자료가 없습니다.')
 old=d.one('SELECT * FROM records WHERE user_id=? AND item_id=?',(user['user_id'],b.id)) or {'bookmarked':0,'read':0,'note':'','tags':'','project':''};old.update(b.model_dump(exclude_none=True))
 d.execute('INSERT INTO records(user_id,item_id,bookmarked,read,note,tags,project,updated_at) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(user_id,item_id) DO UPDATE SET bookmarked=excluded.bookmarked,read=excluded.read,note=excluded.note,tags=excluded.tags,project=excluded.project,updated_at=excluded.updated_at',(user['user_id'],b.id,int(old['bookmarked']),int(old['read']),old['note'],old['tags'],old['project'],now()));return {'ok':True}
@app.get('/api/items')
def items(q:str=Query('',max_length=500),kind:str='',category:str='',source:str='',language:str='',start:str='',end:str='',sort:str='latest',saved:bool=False,unread:bool=False,project:str='',offset:int=Query(0,ge=0,le=1000000),limit:int=Query(50,ge=1,le=100),user=Depends(session)):
 d=db();where=['1=1'];args=[user['user_id']]
 for value,col in [(kind,'i.kind'),(source,'i.source_id'),(language,'s.language'),(project,'r.project')]:
  if value:where.append(col+'=?');args.append(value)
 if category:where.append('(i.category=? OR i.tags LIKE ?)');args.extend([category,'%"'+category+'"%'])
 if q:
  words=re.findall(r'[\w가-힣]+',q)[:12];match=' OR '.join('"'+w.replace('"','""')+'"*' for w in words)
  if match:where.append('(i.id IN (SELECT id FROM item_search WHERE item_search MATCH ?) OR i.title LIKE ? OR r.note LIKE ? OR r.tags LIKE ? OR r.project LIKE ?)');args.extend([match]+['%'+q+'%']*4)
 for value,op in [(start,'>='),(end,'<=')]:
  if value:
   if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',value):raise HTTPException(400,'날짜 형식 오류')
   where.append(f"date(i.published_at,'+9 hours') {op} ?");args.append(value)
 if saved:where.append('r.bookmarked=1')
 if unread:where.append('coalesce(r.read,0)=0')
 base='FROM items i JOIN sources s ON s.id=i.source_id LEFT JOIN records r ON r.item_id=i.id AND r.user_id=? WHERE '+' AND '.join(where)
 order='i.score DESC,i.published_at DESC' if sort=='importance' else 'i.published_at DESC,i.collected_at DESC'
 rows=d.all("SELECT i.*,s.name AS source_name,s.language,coalesce(r.bookmarked,0) AS bookmarked,coalesce(r.read,0) AS read,coalesce(r.note,'') AS note,coalesce(r.tags,'') AS personal_tags,coalesce(r.project,'') AS project "+base+' ORDER BY '+order+' LIMIT ? OFFSET ?',args+[limit,offset])
 return {'items':rows,'total':d.one('SELECT count(*) AS n '+base,args)['n'],'offset':offset,'limit':limit}
@app.get('/api/overview')
def overview(user=Depends(session)):
 d=db();day=datetime.now(timezone(timedelta(hours=9))).date().isoformat()+'T00:00:00+09:00';cut=datetime.fromisoformat(day).astimezone(timezone.utc).isoformat(timespec='seconds')
 counts=d.one("SELECT count(*) AS total,coalesce(sum(kind='news' AND collected_at>=?),0) AS today_news,coalesce(sum(kind='report' AND collected_at>=?),0) AS today_reports FROM items",(cut,cut));counts['saved']=d.one('SELECT count(*) AS n FROM records WHERE user_id=? AND bookmarked=1',(user['user_id'],))['n']
 return {'stats':counts,'sectors':d.all("SELECT category,count(*) AS count FROM items WHERE kind='news' GROUP BY category"),'latest_reports':items(kind='report',limit=4,offset=0,q='',category='',source='',language='',start='',end='',sort='latest',saved=False,unread=False,project='',user=user)['items'],'saved_items':items(saved=True,limit=4,offset=0,q='',kind='',category='',source='',language='',start='',end='',sort='latest',unread=False,project='',user=user)['items'],'projects':d.all("SELECT DISTINCT project FROM records WHERE user_id=? AND project!=''",(user['user_id'],)),'rule_version':RULES['version']}
@app.get('/api/sources')
def sources(user=Depends(session)):
 d=db();rows=d.all('SELECT * FROM sources ORDER BY language DESC,kind,name')
 for s in rows:
  s['reliability']=d.one("SELECT count(*) AS attempts,coalesce(sum(status!='failed'),0) AS successes,sum(fetched) AS fetched,sum(inserted) AS inserted,sum(duplicates) AS duplicates FROM runs WHERE source_id=? AND started_at>=?",(s['id'],(datetime.now(timezone.utc)-timedelta(days=28)).isoformat()))
 return {'sources':rows,'runs':d.all('SELECT r.*,s.name FROM runs r JOIN sources s ON s.id=r.source_id ORDER BY started_at DESC LIMIT 50'),'indicator_runs':d.all('SELECT * FROM indicator_runs ORDER BY started_at DESC LIMIT 20'),'pending':[{**r,'reason':r['note']+(' · 목록 확인 '+r['status'] if r['checked_at'] else '')} for r in d.all('SELECT * FROM source_candidates')]}
class SourceSetting(BaseModel):
 id:str=Field(max_length=100)
 enabled:bool
 interval_minutes:int=Field(ge=60,le=10080)
@app.post('/api/source')
def update_source(b:SourceSetting,user=Depends(write_session)):
 if not db().one('SELECT id FROM sources WHERE id=?',(b.id,)):raise HTTPException(404)
 db().execute('UPDATE sources SET enabled=?,interval_minutes=? WHERE id=?',(int(b.enabled),b.interval_minutes,b.id));return {'ok':True}
@app.get('/api/economy')
def economy(user=Depends(session)):
 d=db();all_series=d.all('SELECT * FROM series')
 for s in all_series:
  s['points']=d.all('SELECT date,value FROM observations WHERE series_id=? ORDER BY date',(s['id'],));s['analysis']=indicator_stats(s['points'],s['id'],s['frequency'])
 return {'series':all_series}
@app.get('/api/signals')
def signals(user=Depends(session)):
 d=db();result=keyword_signals(d);econ=economy(user)['series'];result['indicators']=[dict(id=s['id'],name=s['name'],unit=s['unit'],status=s['status'],analysis=s['analysis']) for s in econ];result['events']=d.all("SELECT i.id,i.title,i.url,i.published_at,i.tags,i.score FROM items i WHERE kind='news' AND (tags LIKE '%기업 투자%' OR tags LIKE '%정책·통상%') ORDER BY published_at DESC LIMIT 12");return result
@app.get('/api/related/{item_id}')
def related(item_id:str,user=Depends(session)):
 d=db();item=d.one('SELECT related_key FROM items WHERE id=?',(item_id,))
 return {'items':d.all('SELECT id,title,published_at,url FROM items WHERE related_key=? AND id!=? ORDER BY published_at DESC LIMIT 12',(item['related_key'],item_id)) if item and item['related_key'] else []}
@app.get('/api/export')
def export(user=Depends(session)):
 d=db();payload={'exported_at':now(),'items':d.all('SELECT i.*,r.note,r.tags AS personal_tags,r.project,r.bookmarked,r.read FROM records r JOIN items i ON i.id=r.item_id WHERE r.user_id=?',(user['user_id'],))}
 return Response(json.dumps(payload,ensure_ascii=False,indent=2),media_type='application/json',headers={'Content-Disposition':'attachment; filename="research-os-archive.json"'})
@app.get('/healthz')
def health():
 try:db().one('SELECT 1 AS ok');return {'status':'ok','storage':'turso' if db().remote else 'local-development'}
 except Exception:raise HTTPException(503,'Database unavailable')
app.mount('/static',StaticFiles(directory=STATIC),name='static')
@app.get('/')
def home():return FileResponse(STATIC/'index.html')
