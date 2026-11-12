"""Independent deterministic collector: python -m research_os.collector.
No web process, AI, article-body scraping, or browser required.
"""
import argparse,calendar,csv,io,json,time,uuid,logging,math,os,re
from datetime import datetime,timezone,timedelta
from urllib.parse import urlparse,urljoin,urlencode
from urllib.robotparser import RobotFileParser
import requests,feedparser
from .db import DB
from .catalog import SOURCES,SERIES,initialize
from .core import now,clean,canonical_url,title_key,classify,importance,similar,related_key,RULES,robots_allowed
UA='ResearchOS/1.0 (personal noncommercial RSS reader)'
ALLOWED={urlparse(s['url']).hostname for s in SOURCES}|{'fred.stlouisfed.org','api.stlouisfed.org'}
def safe_error(error):
 text=f'{type(error).__name__}: {str(error)}'
 key=os.getenv('FRED_API_KEY','')
 if key:text=text.replace(key,'[REDACTED]')
 return re.sub(r'(?i)(api_key=)[^&\s\"\']+',r'\1[REDACTED]',text)[:300]

class Fetcher:
 def __init__(self):self.session=requests.Session();self.robots={};self.last={};self.retry_count=0;self.unavailable={}
 def raw(self,url,headers=None):
  p=urlparse(url)
  if p.scheme!='https' or p.hostname not in ALLOWED or p.port not in (None,443) or p.username:raise ValueError('URL outside allowlist')
  for retry in range(3):
   r=self.session.get(url,headers={'User-Agent':UA,**(headers or {})},timeout=(10,25),allow_redirects=False,stream=True)
   if r.status_code in (429,502,503,504) and retry<2:
    delay=min(30,max(1,int(r.headers.get('Retry-After','1'))) if r.headers.get('Retry-After','1').isdigit() else 3);r.close();time.sleep(delay*(retry+1));self.retry_count+=1;continue
   if r.status_code==304:r.close();return 304,b'',dict(r.headers)
   r.raise_for_status()
   if 300<=r.status_code<400:raise ValueError(f'Redirect requires source review: HTTP {r.status_code}')
   content=bytearray()
   for part in r.iter_content(65536):
    content.extend(part)
    if len(content)>3_000_000:r.close();raise ValueError('Response exceeds 3MB')
   r.close();return r.status_code,bytes(content),dict(r.headers)
 def get(self,url,headers=None):
  p=urlparse(url);origin=p.scheme+'://'+p.netloc
  if origin in self.unavailable:raise ValueError('Host unavailable earlier in this run: '+self.unavailable[origin])
  if origin not in self.robots:
   try:_,body,_=self.raw(origin+'/robots.txt')
   except (requests.Timeout,requests.ConnectionError) as e:
    self.unavailable[origin]=safe_error(e);raise
   except requests.HTTPError as e:
    if e.response.status_code!=404:raise ValueError('robots.txt cannot be verified') from e
    body=b'User-agent: *\nAllow: /'
   if b'<html' in body.lower():raise ValueError('robots.txt returned HTML')
   robot=RobotFileParser();robot.parse(body.decode('utf-8-sig',errors='replace').splitlines());self.robots[origin]=(robot,body.decode('utf-8-sig',errors='replace'))
  robot,robots_body=self.robots[origin]
  if not robots_allowed(robots_body,url,UA):raise ValueError('robots.txt disallows endpoint')
  delay=max(1,robot.crawl_delay(UA) or robot.crawl_delay('*') or 1)
  time.sleep(max(0,delay-(time.monotonic()-self.last.get(origin,0))))
  try:return self.raw(url,headers)
  except (requests.Timeout,requests.ConnectionError) as e:
   self.unavailable[origin]=safe_error(e);raise
  finally:self.last[origin]=time.monotonic()
def parse_feed(body,source):
 parsed=feedparser.parse(body)
 if not parsed.version or not parsed.entries:raise ValueError('No valid RSS/Atom entries')
 entries=[];invalid=0;stamp=now()
 for e in parsed.entries[:250]:
  try:
   title=clean(e.get('title',''))[:1000]
   if not title:raise ValueError('Missing title')
   url=canonical_url(e.get('link',''));date=None
   if e.get('published_parsed'):date=datetime.fromtimestamp(calendar.timegm(e.published_parsed),timezone.utc).isoformat(timespec='seconds')
   category,tags,words=classify(title,source['category']);score,detail=importance(title,date,source['kind'])
   pdf=next((canonical_url(x['href']) for x in e.get('links',[]) if x.get('type')=='application/pdf'),None)
   entries.append(dict(id=uuid.uuid4().hex,source_id=source['id'],title=title,url=url,title_key=title_key(title),summary=clean(e.get('summary',''))[:280] if source['kind']=='report' else '',published_at=date,collected_at=stamp,kind=source['kind'],category=category,tags=json.dumps(tags+words,ensure_ascii=False),score=score,score_detail=json.dumps(detail),rule_version=RULES['version'],pdf_url=pdf,related_key=related_key(title) if source['kind']=='report' else ''))
  except (ValueError,KeyError,OverflowError):invalid+=1
 next_url=next((l.get('href') for l in parsed.feed.get('links',[]) if l.get('rel')=='next'),None)
 return entries,invalid,next_url

def store_entries(db,entries):
 """One bounded existing-row read, conservative similarity, atomic insert batches."""
 if not entries:return 0,0
 earliest=(datetime.now(timezone.utc)-timedelta(days=60)).isoformat()
 recent=db.all('SELECT id,title,title_key,url,category,published_at FROM items WHERE collected_at>=? ORDER BY collected_at DESC LIMIT 10000',(earliest,))
 urls={r['url'] for r in recent};keys={r['title_key'] for r in recent};byurl={r['url']:r for r in recent};bykey={r['title_key']:r for r in recent};buckets={};origins=[]
 for r in recent:buckets.setdefault(r['title_key'][:8],[]).append(r)
 new=[];duplicates=0
 for item in entries:
  canonical=byurl.get(item['url']) or (bykey.get(item['title_key']) if len(item['title_key'])>15 else None)
  dup=canonical is not None
  if not dup:
   for old in buckets.get(item['title_key'][:8],[])[:100]:
    if item['category']!=old['category']:continue
    if item['published_at'] and old['published_at'] and abs((datetime.fromisoformat(item['published_at'])-datetime.fromisoformat(old['published_at'])).total_seconds())>172800:continue
    if similar(item['title'],old['title']):dup=True;canonical=old;break
  if dup:
   duplicates+=1
   if canonical and item['url']!=canonical['url']:origins.append((item['url'],canonical['url'],item['source_id'],item['title'],item['published_at'],item['collected_at']))
   continue
  new.append(item);urls.add(item['url']);keys.add(item['title_key']);byurl[item['url']]=item;bykey[item['title_key']]=item;buckets.setdefault(item['title_key'][:8],[]).append(item)
 columns=['id','source_id','title','url','title_key','summary','published_at','collected_at','kind','category','tags','score','score_detail','rule_version','pdf_url','related_key'];inserted=0
 for o in range(0,len(new),40):
  batch=new[o:o+40];sql='INSERT OR IGNORE INTO items('+','.join(columns)+') VALUES '+','.join('('+','.join('?' for _ in columns)+')' for _ in batch)
  inserted+=db.execute(sql,[r[c] for r in batch for c in columns])['changes']
 for offset in range(0,len(origins),80):
  batch=origins[offset:offset+80];db.execute('INSERT OR IGNORE INTO duplicate_origins VALUES '+','.join('(?,(SELECT id FROM items WHERE url=?),?,?,?,?)' for _ in batch),[v for row in batch for v in row])
 db.index_missing();return inserted,duplicates+len(new)-inserted

def collect_source(db,fetcher,source,force=False):
 old=db.one('SELECT * FROM sources WHERE id=?',(source['id'],));start=now()
 if not old['enabled']:return {'source':source['id'],'status':'disabled'}
 if not force and old['last_attempt'] and (datetime.now(timezone.utc)-datetime.fromisoformat(old['last_attempt'])).total_seconds()<old['interval_minutes']*60:return {'source':source['id'],'status':'not_due'}
 fetched=inserted=duplicates=invalid=0;error=None;status='success'
 try:
  headers={}
  if old['etag']:headers['If-None-Match']=old['etag']
  if old['last_modified']:headers['If-Modified-Since']=old['last_modified']
  code,body,h=fetcher.get(source['url'],headers)
  if code==304:status='not_modified'
  else:
   page=source['url'];all_entries=[]
   for n in range(3):
    entries,bad,next_url=parse_feed(body,source);all_entries.extend(entries);invalid+=bad
    if not next_url:break
    next_url=urljoin(page,next_url)
    if urlparse(next_url).hostname!=urlparse(source['url']).hostname:raise ValueError('Cross-host pagination denied')
    if n<2:_,body,_=fetcher.get(next_url);page=next_url
   fetched=len(all_entries);inserted,duplicates=store_entries(db,all_entries)
   db.execute('UPDATE sources SET etag=?,last_modified=? WHERE id=?',(h.get('ETag'),h.get('Last-Modified'),source['id']))
 except Exception as e:error=safe_error(e);status='failed'
 end=now();db.execute('INSERT INTO runs(id,source_id,started_at,finished_at,status,fetched,inserted,duplicates,invalid,error) VALUES(?,?,?,?,?,?,?,?,?,?)',(uuid.uuid4().hex,source['id'],start,end,status,fetched,inserted,duplicates,invalid,error))
 db.execute('UPDATE sources SET status=?,last_attempt=?,last_success=CASE WHEN ? IS NULL THEN ? ELSE last_success END,first_success=CASE WHEN ? IS NULL THEN coalesce(first_success,?) ELSE first_success END,error=?,count=(SELECT count(*) FROM items WHERE source_id=?) WHERE id=?',(status,end,error,end,error,end,error,source['id'],source['id']))
 return {'source':source['id'],'status':status,'fetched':fetched,'inserted':inserted,'duplicates':duplicates,'invalid':invalid,'error':error}

def collect_series(db,fetcher,entry,force=False):
 sid,name,unit,freq,provider=entry;old=db.one('SELECT updated_at FROM series WHERE id=?',(sid,));start=now();count=0;error=None
 if not force and old['updated_at'] and (datetime.now(timezone.utc)-datetime.fromisoformat(old['updated_at'])).total_seconds()<12*3600:return {'series':sid,'status':'not_due'}
 try:
  startdate=(datetime.now(timezone.utc)-timedelta(days=760)).date().isoformat();key=os.getenv('FRED_API_KEY','')
  if key:
   if not re.fullmatch(r'[a-z0-9]{32}',key):raise ValueError('FRED_API_KEY must be a registered 32-character lower-case key')
   url='https://api.stlouisfed.org/fred/series/observations?'+urlencode({'series_id':sid,'api_key':key,'file_type':'json','observation_start':startdate,'sort_order':'asc','limit':10000})
   _,body,_=fetcher.get(url);data=json.loads(body)
   if 'observations' not in data:raise ValueError('Official FRED API returned no observations')
   if data.get('count',0)>10000:raise ValueError('FRED response requires pagination; refusing truncation')
   reader=({'observation_date':r['date'],sid:r['value']} for r in data['observations'])
  else:
   url=f'https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}&cosd={startdate}'
   _,body,_=fetcher.get(url);reader=csv.DictReader(io.StringIO(body.decode('utf-8-sig')))
   if reader.fieldnames not in (['observation_date',sid],['DATE',sid]):raise ValueError('Unexpected CSV header')
  points=[]
  for row in reader:
   day=row.get('observation_date',row.get('DATE'));value=row[sid]
   if not value or value=='.':continue
   datetime.strptime(day,'%Y-%m-%d');v=float(value)
   if not math.isfinite(v) or day>datetime.now(timezone.utc).date().isoformat():raise ValueError('Invalid observation')
   points.append((sid,day,v,start))
  if not points:raise ValueError('No valid observations')
  for o in range(0,len(points),100):
   batch=points[o:o+100];db.execute('INSERT INTO observations(series_id,date,value,collected_at) VALUES '+','.join('(?,?,?,?)' for _ in batch)+' ON CONFLICT(series_id,date) DO UPDATE SET value=excluded.value,collected_at=CASE WHEN observations.value!=excluded.value THEN excluded.collected_at ELSE observations.collected_at END',[v for p in batch for v in p])
  count=len(points);db.execute("UPDATE series SET status='success',updated_at=?,error=NULL WHERE id=?",(start,sid))
 except Exception as e:error=safe_error(e)+(' · 공개 CSV 경로 실패. GitHub Secrets의 FRED_API_KEY로 공식 API 경로를 사용할 수 있습니다.' if not os.getenv('FRED_API_KEY') else '');db.execute("UPDATE series SET status='failed',error=? WHERE id=?",(error,sid))
 db.execute('INSERT INTO indicator_runs VALUES(?,?,?,?,?,?)',(uuid.uuid4().hex,sid,start,'failed' if error else 'success',count,error))
 return {'series':sid,'status':'failed' if error else 'success','count':count,'error':error}

def run(db,mode='all',force=False,source_ids=None):
 db.migrate();initialize(db);owner=uuid.uuid4().hex;stamp=now();expires=(datetime.now(timezone.utc)+timedelta(minutes=25)).isoformat(timespec='seconds')
 lock=db.all("INSERT INTO collection_lock(id,owner,expires_at) VALUES('collector',?,?) ON CONFLICT(id) DO UPDATE SET owner=excluded.owner,expires_at=excluded.expires_at WHERE collection_lock.expires_at<? RETURNING owner",(owner,expires,stamp))
 if not lock:return [{'status':'busy'}]
 results=[];fetcher=Fetcher()
 try:
  if mode in ('all','feeds'):
   for source in SOURCES:
    if source_ids and source['id'] not in source_ids:continue
    result=collect_source(db,fetcher,source,force);results.append(result);print(json.dumps(result,ensure_ascii=False),flush=True)
  if mode in ('all','indicators'):
   for entry in SERIES:
    result=collect_series(db,fetcher,entry,force);results.append(result);print(json.dumps(result,ensure_ascii=False),flush=True)
 finally:db.execute('DELETE FROM collection_lock WHERE owner=?',(owner,))
 return results
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--mode',choices=['all','feeds','indicators'],default='all');p.add_argument('--force',action='store_true');p.add_argument('--sources',nargs='*');a=p.parse_args()
 results=run(DB(),a.mode,a.force,a.sources)
 failures=sum(r.get('status')=='failed' for r in results);executed=sum(r.get('status') in ('failed','success','not_modified') for r in results)
 if os.getenv('GITHUB_STEP_SUMMARY'):
  with open(os.environ['GITHUB_STEP_SUMMARY'],'a') as summary:
   summary.write('## Collection results\n\n| Source / series | Status | Error |\n|---|---|---|\n')
   for r in results:summary.write('| '+str(r.get('source',r.get('series','collector')))+' | '+r.get('status','unknown')+' | '+str(r.get('error') or '').replace('|','/')+' |\n')
 if failures:print(f'::warning::{failures} collection tasks failed. Review source/indicator logs; partial success is not full coverage.')
 if executed and failures==executed:raise SystemExit(1)
