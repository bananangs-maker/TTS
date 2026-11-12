"""Public reproducible measurements; private owner-scoped research mutations."""
import csv,io,json,uuid,math,re
from datetime import datetime,timedelta
from fastapi import Depends,HTTPException,Query
from fastapi.responses import Response,HTMLResponse
from pydantic import BaseModel,Field
from .engine import VERSION,CONFIG,INDUSTRIES,trends,dump,digest,now,stamp,KST
from .empirical import linkage,backtest,trading_metrics
from .reports import generate,render_report
from ..core import canonical_url

class Review(BaseModel):
 event_id:str=Field(max_length=64)
 verification_status:str
 event_date:str|None=Field(default=None,max_length=10)
 company:str|None=Field(default=None,max_length=100)
 country:str|None=Field(default=None,max_length=100)
 note:str=Field(default='',max_length=3000)
class EventLink(BaseModel):
 event_id:str=Field(max_length=64)
 target_event_id:str=Field(max_length=64)
class Project(BaseModel):
 name:str=Field(min_length=1,max_length=100)
 description:str=Field(default='',max_length=3000)
class Hypothesis(BaseModel):
 id:str|None=None
 project_id:str=Field(max_length=64)
 title:str=Field(min_length=1,max_length=300)
 status:str='Proposed'
 specification:dict=Field(default_factory=dict)
class Note(BaseModel):
 project_id:str=Field(max_length=64)
 title:str=Field(min_length=1,max_length=300)
 note:str=Field(default='',max_length=10000)
 item_ids:list[str]=Field(default_factory=list,max_length=100)
 series_ids:list[str]=Field(default_factory=list,max_length=100)
 chart:dict=Field(default_factory=dict)
class Study(BaseModel):
 industry:str='반도체'
 series_id:str=Field(default='DEXKOUS',max_length=100)
 keyword:str=Field(default='',max_length=100)
 metric:str='news_count'
 horizon:int=Field(default=1,ge=1,le=6)
 window:str='expanding'
 train_size:int=Field(default=36,ge=36,le=120)
 hypothesis_id:str|None=None
class DataImport(BaseModel):
 symbol:str
 kind:str
 source_url:str=Field(max_length=2000)
 csv_text:str=Field(max_length=1000000)
class JanusRun(BaseModel):
 price_id:str=Field(max_length=64)
 signal_id:str=Field(max_length=64)
 cost_bps:float=Field(default=10,ge=0,le=100)
class PeriodReport(BaseModel):
 period:str='daily'
 current:bool=False

def install(app,db,public_session,write_session):
 def private_read(user=Depends(public_session)):
  if not user['authenticated']:raise HTTPException(401,'개인 연구는 로그인이 필요합니다.')
  return user
 def validate(industry,keyword=''):
  if industry not in INDUSTRIES or keyword and keyword not in CONFIG['keywords'][industry]:raise HTTPException(400,'산업·키워드 확인 필요')
 def checked(function,*args,**kwargs):
  try:return function(*args,**kwargs)
  except ValueError as e:raise HTTPException(400,str(e)) from e
 @app.get('/api/research/trends')
 def trend(industry:str='반도체',days:int=Query(90,ge=7,le=730),keyword:str='',grain:str='day',end_date:str='',user=Depends(public_session)):
  validate(industry,keyword);end=datetime.now(KST).date()
  if end_date:
   try:end=datetime.strptime(end_date,'%Y-%m-%d').date()
   except ValueError:raise HTTPException(400,'종료일 형식 오류')
   if end>datetime.now(KST).date():raise HTTPException(400,'미래 종료일은 허용하지 않습니다.')
  return checked(trends,db(),industry,days,keyword,grain,end)
 @app.get('/api/research/features/{item_id}')
 def article_feature(item_id:str,user=Depends(public_session)):
  row=db().one('SELECT * FROM article_features WHERE item_id=? AND version=?',(item_id,VERSION))
  return {'feature':row,'version':VERSION}
 @app.get('/api/research/config')
 def config(user=Depends(public_session)):
  return dict(version=VERSION,industries=CONFIG['keywords'],minimum_history=CONFIG['min_history_days'],sentiment_formula='100 × (P − N) / (P + N); 분모 0은 결측',scope='공식 RSS 제목만 분석. 규칙 기반 확장·위축 표현 지수이며 시장 투자심리 측정치가 아닙니다.')
 @app.get('/api/research/signals')
 def signals(limit:int=Query(100,ge=1,le=300),user=Depends(public_session)):
  d=db();res=d.execute_many([('SELECT * FROM detected_signals ORDER BY detected_at DESC LIMIT ?',(limit,)),('SELECT * FROM analysis_runs ORDER BY started_at DESC LIMIT 5',())]);return dict(signals=res[0]['rows'],runs=res[1]['rows'],version=VERSION)
 @app.get('/api/research/events')
 def events(industry:str='',kind:str='',q:str=Query('',max_length=200),offset:int=Query(0,ge=0,le=100000),user=Depends(public_session)):
  where=['NOT EXISTS(SELECT 1 FROM event_links l WHERE l.user_id=? AND l.event_id=e.id)'];args=[user['user_id'],user['user_id']]
  for value,sql in [(industry,'e.industry LIKE ?'),(kind,'e.event_type=?'),(q,'e.title LIKE ?')]:
   if value:where.append(sql);args.append(value if sql.endswith('=?') else '%'+value+'%')
  base=' FROM industry_events e LEFT JOIN event_reviews r ON r.event_id=e.id AND r.user_id=? WHERE '+' AND '.join(where);d=db();res=d.execute_many([('SELECT e.*,r.verification_status AS my_status,r.event_date AS my_event_date,r.company AS my_company,r.country AS my_country,r.note AS my_note,(SELECT count(*) FROM event_sources es WHERE es.event_id=e.id) +(SELECT count(*) FROM duplicate_origins d WHERE d.canonical_item_id IN (SELECT es.item_id FROM event_sources es WHERE es.event_id=e.id)) AS source_count'+base+' ORDER BY e.detected_at DESC LIMIT 50 OFFSET ?',args+[offset]),('SELECT count(*) AS n'+base,args)])
  return dict(events=res[0]['rows'],total=res[1]['rows'][0]['n'],types=list(CONFIG['events']),version=VERSION,warning='명시적 제목 패턴으로 탐지한 검증 전 후보입니다. 발생일·기업·투자액을 추정하지 않습니다. 중복 제거된 기사의 원문 출처도 보존합니다. 자동 병합은 동일/유사 제목으로 제한하며 다른 후보는 개인 검증 후 연결할 수 있습니다. 개인 검증·수정 내용은 로그인 사용자에게만 표시됩니다.')
 @app.get('/api/research/event/{event_id}/sources')
 def event_sources(event_id:str,user=Depends(public_session)):
  d=db();linked=[event_id]+[r['event_id'] for r in d.all('SELECT event_id FROM event_links WHERE user_id=? AND target_event_id=?',(user['user_id'],event_id))];marks=','.join('?' for _ in linked)
  rows=d.all('SELECT i.id,i.title,i.url,i.source_id,i.published_at,i.collected_at FROM event_sources s JOIN items i ON i.id=s.item_id WHERE s.event_id IN ('+marks+')',linked)
  rows+=d.all('SELECT d.canonical_item_id AS id,d.title,d.url,d.source_id,d.published_at,d.collected_at FROM duplicate_origins d WHERE d.canonical_item_id IN (SELECT item_id FROM event_sources WHERE event_id IN ('+marks+'))',linked)
  return {'items':rows}
 @app.post('/api/research/event/link')
 def event_link(b:EventLink,user=Depends(write_session)):
  if b.event_id==b.target_event_id:raise HTTPException(400,'자기 자신을 연결할 수 없습니다.')
  d=db()
  for rid in [b.event_id,b.target_event_id]:
   if not d.one('SELECT id FROM industry_events WHERE id=?',(rid,)):raise HTTPException(404)
  if d.one('SELECT event_id FROM event_links WHERE user_id=? AND (event_id=? OR target_event_id=?)',(user['user_id'],b.target_event_id,b.event_id)):raise HTTPException(400,'중첩 연결을 피하려면 독립된 대표 사건을 선택하세요.')
  d.execute('INSERT INTO event_links VALUES(?,?,?,?) ON CONFLICT(user_id,event_id) DO UPDATE SET target_event_id=excluded.target_event_id,created_at=excluded.created_at',(user['user_id'],b.event_id,b.target_event_id,now()));return {'ok':True}
 @app.post('/api/research/event/review')
 def review(b:Review,user=Depends(write_session)):
  if b.verification_status not in ['unverified','verified','rejected']:raise HTTPException(400,'검증 상태 오류')
  if b.event_date:
   try:datetime.strptime(b.event_date,'%Y-%m-%d')
   except ValueError:raise HTTPException(400,'날짜 오류')
  if not db().one('SELECT id FROM industry_events WHERE id=?',(b.event_id,)):raise HTTPException(404)
  db().execute('INSERT INTO event_reviews VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(user_id,event_id) DO UPDATE SET verification_status=excluded.verification_status,event_date=excluded.event_date,company=excluded.company,country=excluded.country,note=excluded.note,updated_at=excluded.updated_at',(user['user_id'],b.event_id,b.verification_status,b.event_date,b.company,b.country,b.note,now()));return {'ok':True}
 @app.get('/api/research/linkage')
 def link(industry:str='반도체',series_id:str='DEXKOUS',keyword:str='',metric:str='news_count',user=Depends(public_session)):
  validate(industry,keyword);return checked(linkage,db(),industry,series_id,keyword,metric)
 @app.post('/api/research/backtest')
 def run_backtest(b:Study,user=Depends(write_session)):
  validate(b.industry,b.keyword);result=checked(backtest,db(),b.industry,b.series_id,b.keyword,b.metric,b.horizon,b.window,b.train_size);rid=uuid.uuid4().hex;hypothesis=None
  if b.hypothesis_id:
   hypothesis=db().one('SELECT * FROM research_hypotheses WHERE id=? AND user_id=?',(b.hypothesis_id,user['user_id']))
   if not hypothesis:raise HTTPException(404,'가설을 찾을 수 없습니다.')
  # No retroactive preregistration. These runs are exploratory; a timestamped
  # proposal is stored separately and is not statistical evidence of success.
  result['study_type']='exploratory';result['hypothesis_status']='Inconclusive' if result['status']=='insufficient_data' else 'Testing';result['id']=rid
  db().execute('INSERT INTO research_experiments VALUES(?,?,?,?,?,?,?,?,?)',(rid,user['user_id'],b.hypothesis_id,'forecast_backtest',dump(b.model_dump()),dump(result),result['data_hash'],VERSION,now()));return result
 @app.get('/api/research/export')
 def export(industry:str='반도체',days:int=Query(730,ge=7,le=730),format:str='json',user=Depends(public_session)):
  validate(industry);d=trends(db(),industry,days,end=datetime.now(KST).date());meta={k:d[k] for k in ['version','industry','start','end','warning','sources','eligible_sources','computed_at']};rows=[dict(**p,version=VERSION,industry=industry,time_basis='KST_available_day',backfill_policy='exclude_unknown_or_over_48h') for p in d['timeline']]
  if format=='csv':
   out=io.StringIO();writer=csv.DictWriter(out,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows);content='\ufeff'+out.getvalue();mime='text/csv; charset=utf-8'
  elif format=='json':content=dump(dict(metadata=meta,news=rows,keywords=d['keywords'],keyword_daily=db().all('SELECT day,keyword,sum(n) AS n,sum(positive) AS positive,sum(negative) AS negative,sum(mixed) AS mixed,sum(uncertain) AS uncertain,sum(neutral) AS neutral,count(DISTINCT source_id) AS source_count,max(computed_at) AS computed_at,version FROM research_daily WHERE version=? AND industry=? AND length(keyword)>0 AND day>=? AND day<=? GROUP BY day,keyword,version ORDER BY day,keyword',(VERSION,industry,d['start'],d['end'])),events=db().all('SELECT * FROM industry_events WHERE industry LIKE ? AND announcement_date>=? AND announcement_date<=? ORDER BY detected_at DESC LIMIT 2000',('%'+industry+'%',d['start'],d['end'])),event_export_limit=2000,observations=db().all('SELECT * FROM observations WHERE date>=? AND date<=? ORDER BY series_id,date',(d['start'],d['end'])),observation_vintages=db().all('SELECT * FROM observation_vintages WHERE observation_date>=? AND observation_date<=? ORDER BY series_id,observation_date,available_at',(d['start'],d['end']))));mime='application/json'
  else:raise HTTPException(400,'지원 형식: csv/json')
  return Response(content,media_type=mime,headers={'Content-Disposition':'attachment; filename="tts-janus-data.'+format+'"'})
 @app.get('/api/research/reports')
 def reports(user=Depends(public_session)):
  return {'reports':db().all('SELECT id,period,start_date,end_date,version,data_hash,generated_at FROM generated_reports ORDER BY generated_at DESC LIMIT 60')}
 @app.post('/api/research/report')
 def make_report(b:PeriodReport,user=Depends(write_session)):
  if b.period not in ['daily','weekly','monthly']:raise HTTPException(400,'기간 오류')
  today=datetime.now(KST).date().isoformat();r=generate(db(),b.period,today,today) if b.current and b.period=='daily' else generate(db(),b.period);return {'id':r['id']}
 @app.get('/api/research/report/{report_id}/json')
 def report_json(report_id:str,user=Depends(public_session)):
  r=db().one('SELECT * FROM generated_reports WHERE id=?',(report_id,))
  if not r:raise HTTPException(404)
  return json.loads(r['payload'])
 @app.get('/reports/{report_id}')
 def report_html(report_id:str,user=Depends(public_session)):
  r=db().one('SELECT * FROM generated_reports WHERE id=?',(report_id,))
  if not r:raise HTTPException(404)
  return HTMLResponse(render_report(r))
 @app.get('/api/research/archive')
 def archive(user=Depends(private_read)):
  d=db();result=d.execute_many([(f'SELECT * FROM {t} WHERE user_id=? ORDER BY created_at DESC LIMIT 200',(user['user_id'],)) for t in ['research_projects','research_hypotheses','research_experiments','research_notes','janus_datasets']]);return dict(zip(['projects','hypotheses','experiments','notes','datasets'],[r['rows'] for r in result]))
 @app.post('/api/research/project')
 def project(b:Project,user=Depends(write_session)):
  rid=uuid.uuid4().hex;db().execute('INSERT INTO research_projects VALUES(?,?,?,?,?)',(rid,user['user_id'],b.name,b.description,now()));return {'id':rid}
 def own_project(project_id,user):
  if not db().one('SELECT id FROM research_projects WHERE id=? AND user_id=?',(project_id,user['user_id'])):raise HTTPException(404,'프로젝트를 찾을 수 없습니다.')
 @app.post('/api/research/hypothesis')
 def hypothesis(b:Hypothesis,user=Depends(write_session)):
  own_project(b.project_id,user)
  if b.status not in ['Proposed','Testing','Supported','Not Supported','Inconclusive']:raise HTTPException(400,'가설 상태 오류')
  if len(dump(b.specification))>10000:raise HTTPException(400,'명세가 너무 큽니다.')
  if b.id:
   old=db().one('SELECT * FROM research_hypotheses WHERE id=? AND user_id=?',(b.id,user['user_id']))
   if not old:raise HTTPException(404)
   # Proposal/specification is immutable. Changes create a new hypothesis.
   db().execute('UPDATE research_hypotheses SET status=?,updated_at=? WHERE id=? AND user_id=?',(b.status,now(),b.id,user['user_id']));return {'id':b.id}
  rid=uuid.uuid4().hex;db().execute('INSERT INTO research_hypotheses VALUES(?,?,?,?,?,?,?,?,?)',(rid,user['user_id'],b.project_id,b.title,b.status,dump(b.specification),None,now(),now()));return {'id':rid}
 @app.post('/api/research/note')
 def note(b:Note,user=Depends(write_session)):
  own_project(b.project_id,user)
  if len(dump(b.chart))>100000:raise HTTPException(400,'차트가 너무 큽니다.')
  rid=uuid.uuid4().hex;db().execute('INSERT INTO research_notes VALUES(?,?,?,?,?,?,?,?,?)',(rid,user['user_id'],b.project_id,b.title,b.note,dump(b.item_ids),dump(b.series_ids),dump(b.chart),now()));return {'id':rid}
 @app.get('/api/research/archive/export')
 def export_archive(user=Depends(private_read)):
  d=db();tables=['research_projects','research_hypotheses','research_experiments','research_notes','janus_datasets','event_reviews','event_links'];result=d.execute_many([(f'SELECT * FROM {t} WHERE user_id=?',(user['user_id'],)) for t in tables]+[('SELECT o.* FROM janus_observations o JOIN janus_datasets d ON d.id=o.dataset_id WHERE d.user_id=?',(user['user_id'],)),('SELECT * FROM records WHERE user_id=?',(user['user_id'],))]);payload=dict(zip(['projects','hypotheses','experiments','notes','datasets','event_reviews','event_links','janus_observations','article_records'],[r['rows'] for r in result]));return Response(dump({'exported_at':now(),**payload}),media_type='application/json',headers={'Content-Disposition':'attachment; filename="tts-research-private.json"'})
 @app.post('/api/janus/import')
 def data_import(b:DataImport,user=Depends(write_session)):
  if b.symbol not in ['TQQQ','SOXL','STOCK','NEWS'] or b.kind not in ['adjusted_close','google_trends','divergence','news_signal']:raise HTTPException(400,'지원 유형·심볼 확인 필요')
  url=checked(canonical_url,b.source_url)
  reader=csv.DictReader(io.StringIO(b.csv_text.lstrip('\ufeff')))
  if reader.fieldnames!=['date','value','available_at']:raise HTTPException(400,'CSV 헤더는 date,value,available_at 순서여야 합니다.')
  rows=[];seen=set();rid=uuid.uuid4().hex
  for r in reader:
   if len(rows)>=5000:raise HTTPException(400,'최대 5000행')
   try:
    datetime.strptime(r['date'],'%Y-%m-%d');value=float(r['value']);available=stamp(r['available_at'])
    if not re.search(r'(?:Z|[+-]\d\d:\d\d)$',r['available_at']):raise ValueError()
    if not math.isfinite(value) or r['date'] in seen or available.astimezone(KST).date().isoformat()<r['date'] or available>stamp(now()) or b.kind=='adjusted_close' and value<=0:raise ValueError()
   except (ValueError,TypeError,KeyError):raise HTTPException(400,'중복 날짜·값·이용가능 시각 오류. 시각에는 시간대가 필요합니다.')
   seen.add(r['date']);rows.append((rid,r['date'],value,available.isoformat()))
  if not rows:raise HTTPException(400,'빈 CSV')
  d=db();d.execute('INSERT INTO janus_datasets VALUES(?,?,?,?,?,?,?)',(rid,user['user_id'],b.symbol,b.kind,url,'user_declared_unverified',now()))
  for i in range(0,len(rows),100):
   batch=rows[i:i+100];d.execute('INSERT INTO janus_observations VALUES '+','.join('(?,?,?,?)' for _ in batch),[v for row in batch for v in row])
  return dict(id=rid,rows=len(rows),status='imported_unverified')
 @app.post('/api/janus/backtest')
 def janus_run(b:JanusRun,user=Depends(write_session)):
  d=db();datasets=[]
  for rid in [b.price_id,b.signal_id]:
   row=d.one('SELECT * FROM janus_datasets WHERE id=? AND user_id=?',(rid,user['user_id']))
   if not row:raise HTTPException(404)
   datasets.append(row)
  if datasets[0]['kind']!='adjusted_close' or datasets[1]['kind'] not in ['divergence','news_signal']:raise HTTPException(400,'조정종가 + 명시적 신호 데이터셋을 선택하세요. Google Trends 원자료를 매수 신호로 자동 해석하지 않습니다.')
  rows=[d.all('SELECT day,value,available_at FROM janus_observations WHERE dataset_id=? ORDER BY day',(rid,)) for rid in [b.price_id,b.signal_id]];result=checked(trading_metrics,*rows,b.cost_bps);rid=uuid.uuid4().hex;result['id']=rid;d.execute('INSERT INTO research_experiments VALUES(?,?,?,?,?,?,?,?,?)',(rid,user['user_id'],None,'janus_exploratory',dump(b.model_dump()),dump(result),digest(rows),VERSION,now()));return result
