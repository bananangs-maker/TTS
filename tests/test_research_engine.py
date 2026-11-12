"""Synthetic fixtures are isolated in pytest tmp_path and never shipped as data."""
import json,uuid,math,csv,io,hashlib
from datetime import datetime,timedelta,timezone
import pytest
from fastapi.testclient import TestClient
from test_research_os import database,sample
from research_os.collector import store_entries,collect_series,safe_error
from research_os.research.engine import extract_features,contains,event_candidates,process,trends,VERSION,KST,now
from research_os.research.empirical import oos,trading_metrics,monthly_news,backtest
from research_os.research.reports import generate,render_report
from research_os.research.pipeline import detect
from research_os.core import title_key
from research_os.app import app


def item(title='HBM 증설',days_old=0,source=None):
 row=sample(source)[0];col=datetime.now(timezone.utc);pub=col-timedelta(days=days_old,hours=1);row.update(id=uuid.uuid4().hex,url='https://example.org/'+uuid.uuid4().hex,title=title,title_key=title_key(title),published_at=pub.isoformat(),collected_at=col.isoformat());return row

def live_source(d):
 sid=sample()[0]['source_id'];t=now();d.execute('UPDATE sources SET first_success=?,last_success=?,last_attempt=?,status=? WHERE id=?',(t,t,t,'success',sid));d.execute('INSERT INTO runs(id,source_id,started_at,finished_at,status) VALUES(?,?,?,?,?)',(uuid.uuid4().hex,sid,t,t,'success'));return sid

def login(c):
 r=c.post('/api/login',json={'username':'researcher','password':'only-for-tests-long-password'});assert r.status_code==200;return {'X-CSRF-Token':r.json()['csrf']}

def test_synonyms_boundaries_and_conservative_sentiment():
 f=extract_features(item('고대역폭 메모리 공급 부족 · 증설'))
 assert 'HBM' in f['keywords']['반도체'] and f['label']=='positive'
 assert not contains('revenue never notepad','EV') and not contains('notepad','not')
 assert extract_features(item('반도체 증설 계획 없다'))['label']=='uncertain'
 assert extract_features(item('반도체 증설 및 감산'))['label']=='mixed'
 assert extract_features(item('"반도체 증설" 발표'))['label']=='uncertain'
 assert extract_features(item('반도체 가격 상승'))['label']=='neutral' # Prices alone do not imply industrial expansion.
 assert extract_features(item('HBM 증설',30))['backfill']==1


def test_incremental_processing_backfill_exclusion_and_null_gaps(database):
 live_source(database);data=[item('HBM 증설 신규 프로젝트'),item('HBM 감산 기존 생산 라인'),item('DRAM 공급 부족 과거 보도',40)];store_entries(database,data)
 before=database.one('SELECT count(*) AS n FROM items')['n'];first=process(database);second=process(database)
 assert first['processed']==3 and second['processed']==0
 assert database.one('SELECT count(*) AS n FROM items')['n']==before
 end=datetime.now(KST).date();r=trends(database,'반도체',90,end=end)
 assert r['summary']['n']==2 and r['quality']['backfill']==1
 assert r['summary']['value']==0 and r['timeline'][-1]['value']==2
 assert r['timeline'][0]['value'] is None and r['eligible_sources']==[]
 assert all(k['status']=='insufficient_history' for k in r['keywords'])
 # Positive-only zero denominator is never fabricated when there are no classified articles.
 empty=trends(database,'2차전지',90,end=end);assert empty['summary']['value'] is None


def test_event_unknowns_and_multiple_origins_survive_dedup(database):
 a=item('TSMC HBM 공장 증설 100억 투자');b={**a,'id':uuid.uuid4().hex,'url':'https://other.example.org/same'}
 assert store_entries(database,[a,b])==(1,1);assert database.one('SELECT count(*) AS n FROM duplicate_origins')['n']==1
 process(database);e=database.one("SELECT * FROM industry_events WHERE event_type='factory_expansion'")
 assert e['company']=='TSMC' and e['country'] is None and e['event_date'] is None and e['verification_status']=='unverified'
 assert e['amount_text']=='100억 '
 with TestClient(app) as c:
  rows=c.get('/api/research/event/'+e['id']+'/sources').json()['items'];assert len(rows)==2
  assert c.get('/api/research/events').status_code==200
 # A duplicate of a very old canonical URL still resolves its real stored id.
 database.execute('UPDATE items SET collected_at=?',( '2000-01-01T00:00:00+00:00',))
 assert store_entries(database,[a,{**b,'url':'https://third.example.org/same','id':uuid.uuid4().hex}])==(0,2)


def test_point_in_time_vintages_and_insufficient_backtest(database):
 database.execute('INSERT INTO observations VALUES(?,?,?,?)',('DEXKOUS','2020-01-01',1100,now()));process(database)
 v=database.one('SELECT * FROM observation_vintages');assert v['observation_date']=='2020-01-01' and v['available_at'][:4]!='2020'
 r=backtest(database,'반도체','DEXKOUS');assert r['status']=='insufficient_data' and 'metrics' not in r and r['predictions']==[]


def test_fred_api_contract_revision_history_and_redaction(database,monkeypatch):
 monkeypatch.setenv('FRED_API_KEY','a'*32)
 class Fetch:
  def get(self,url):
   assert url.startswith('https://api.stlouisfed.org/fred/series/observations?') and 'series_id=DEXKOUS' in url
   return 200,json.dumps({'count':2,'observations':[{'date':'2026-10-01','value':'1300'},{'date':'2026-10-02','value':'.'}]}).encode(),{}
 entry=('DEXKOUS','FX','KRW','daily','Fed');assert collect_series(database,Fetch(),entry,True)['status']=='success'
 before=database.one('SELECT * FROM observations')['collected_at'];process(database)
 assert collect_series(database,Fetch(),entry,True)['count']==1
 assert database.one('SELECT * FROM observations')['collected_at']==before
 process(database);assert database.one('SELECT count(*) AS n FROM observation_vintages')['n']==1
 msg=safe_error(ValueError('https://api.stlouisfed.org/?api_key='+'a'*32+'&x=1'));assert 'a'*32 not in msg and '[REDACTED]' in msg


def test_forecast_train_only_scaling_and_label_purge():
 import numpy as np
 rng=np.random.default_rng(12);rows=[]
 from research_os.research.empirical import month_shift,month_end
 for i in range(90):
  month=month_shift('2010-01',i);origin=month_end(month);x=float(rng.normal());rows.append(dict(month=month,origin_at=origin.isoformat(),feature=x,baseline_level=float(rng.normal()),baseline_change=float(rng.normal()),target=2*x+.01*float(rng.normal()),label_available_at=month_end(month_shift(month,2)).isoformat(),feature_available_at=origin.isoformat(),baseline_available_at=(origin-timedelta(days=1)).isoformat()))
 r=oos(rows);assert r['status']=='evaluated_not_validated' and r['metrics']['enhanced']['rmse']<r['metrics']['baseline']['rmse']
 for pred in r['predictions']:assert datetime.fromisoformat(pred['latest_training_label'])<=datetime.fromisoformat(pred['origin_at'])
 # Altering the distant future cannot alter earlier forecasts or scaling.
 changed=[dict(x) for x in rows];changed[-1]['feature']=1e10;new=oos(changed)
 assert r['predictions'][0]==new['predictions'][0]
 changed[40]['feature_available_at']=(datetime.fromisoformat(changed[40]['origin_at'])+timedelta(days=1)).isoformat()
 with pytest.raises(ValueError,match='Future information'):oos(changed)


def test_janus_future_signals_costs_and_late_price_rejection():
 prices=[]
 for i in range(85):
  t=datetime(2025,1,1,21,tzinfo=timezone.utc)+timedelta(days=i);prices.append(dict(day=t.date().isoformat(),value=100.,available_at=t.isoformat()))
 signal=[dict(day=prices[0]['day'],value=1.,available_at=prices[0]['available_at'])]
 r=trading_metrics(prices,signal,10);assert r['trade_sides']==2 and r['total_return']==pytest.approx((1-.001)**2-1)
 late=[{**signal[0],'available_at':prices[-1]['available_at']}];r=trading_metrics(prices,late,10);assert r['total_return']==0 and r['trade_sides']==0
 corrupt=[{**p,'available_at':prices[-1]['available_at']} for p in prices]
 with pytest.raises(ValueError,match='이용가능'):trading_metrics(corrupt,signal)


def test_monthly_collection_can_start_after_partial_first_month(database):
 from research_os.research.empirical import month_end
 sid=sample()[0]['source_id'];database.execute('UPDATE sources SET first_success=? WHERE id=?',('2025-12-15T01:00:00+00:00',sid))
 for i in range(31):
  t=datetime(2026,1,1,3,tzinfo=timezone.utc)+timedelta(days=i);day=t.date().isoformat();database.execute('INSERT INTO runs(id,source_id,started_at,finished_at,status) VALUES(?,?,?,?,?)',(str(i),sid,t.isoformat(),t.isoformat(),'success'));database.execute('INSERT INTO research_daily VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',(day,sid,'반도체','',VERSION,1,1,0,0,0,0,0,now()))
 m=monthly_news(database,'반도체');assert next(r for r in m if r['month']=='2026-01')['complete'] is True
 database.execute("DELETE FROM runs WHERE id='10'");m=monthly_news(database,'반도체');assert next(r for r in m if r['month']=='2026-01')['complete'] is False


def test_private_research_auth_csrf_and_no_guest_leak(database):
 store_entries(database,[item('HBM 증설 투자 발표')]);process(database)
 with TestClient(app) as c:
  assert c.get('/api/research/trends').status_code==200
  assert c.get('/api/research/archive').status_code==401
  assert c.post('/api/research/project',json={'name':'private'}).status_code==401
  h=login(c);assert c.post('/api/research/project',json={'name':'private'}).status_code==403
  p=c.post('/api/research/project',json={'name':'Secret research','description':'personal research note'},headers=h).json()['id']
  hyp=c.post('/api/research/hypothesis',json={'project_id':p,'title':'Test a public-data hypothesis','specification':{'period':'future'},'status':'Proposed'},headers=h).json()['id']
  assert c.post('/api/research/note',headers=h,json={'project_id':p,'title':'note','note':'private details','chart':{'points':[1]}}).status_code==200
  study=c.post('/api/research/backtest',headers=h,json={'hypothesis_id':hyp}).json();assert study['status']=='insufficient_data'
  a=c.get('/api/research/archive').json();assert len(a['projects'])==1 and len(a['experiments'])==1 and len(a['notes'])==1
  assert c.get('/api/research/archive/export').status_code==200
  e=database.one('SELECT id FROM industry_events')['id'];assert c.post('/api/research/event/review',headers=h,json={'event_id':e,'verification_status':'verified','note':'PRIVATE REVIEW'}).status_code==200
  assert next(x for x in c.get('/api/research/events').json()['events'] if x['id']==e)['my_note']=='PRIVATE REVIEW'
  c.cookies.clear();assert c.get('/api/research/archive').status_code==401
  public=c.get('/api/research/events').json();assert 'PRIVATE REVIEW' not in json.dumps(public)
  assert 'private details' not in c.get('/api/research/export').text


def test_reports_immutable_idempotent_and_escape_html(database):
 live_source(database);store_entries(database,[item('HBM 증설 <script>alert(1)</script>')]);process(database);today=datetime.now(KST).date().isoformat()
 r=generate(database,'daily',today,today);again=generate(database,'daily',today,today);assert r['id']==again['id']
 p=json.loads(r['payload']);assert p['status']=='partial' and p['industries']['반도체']['n']==1
 page=render_report(r);assert '<script>alert(1)</script>' not in page and '&lt;script&gt;' in page and 'PDF 저장' in page
 with TestClient(app) as c:
  assert c.get('/reports/'+r['id']).status_code==200
  assert c.get('/api/research/report/'+r['id']+'/json').json()['version']==VERSION


def test_migration_backup_and_restore_research(database,tmp_path):
 from research_os.backup import backup,restore
 from research_os.db import DB
 store_entries(database,[item('TSMC HBM 증설')]);process(database);database.migrate();database.migrate()
 path=tmp_path/'research-backup.json';backup(database,path);other=DB(path=str(tmp_path/'restore.db'),url='');restore(other,path)
 assert other.one('SELECT count(*) AS n FROM article_features')['n']==1
 assert other.one('SELECT count(*) AS n FROM industry_events')['n']>=1
 assert other.one('SELECT max(version) AS v FROM schema_versions')['v']==2


def test_signal_unit_consistency_and_idempotence(database):
 database.execute('INSERT INTO observations VALUES(?,?,?,?)',('DEXKOUS','2026-10-01',1000,now()));database.execute('INSERT INTO observations VALUES(?,?,?,?)',('DEXKOUS','2026-10-02',1020,now()));process(database)
 detect(database);n=database.one('SELECT count(*) AS n FROM detected_signals')['n'];detect(database)
 assert n==1 and database.one('SELECT count(*) AS n FROM detected_signals')['n']==n
 r=database.one('SELECT * FROM detected_signals');assert r['value']==pytest.approx(.02) and r['threshold']==.01


def test_private_export_keeps_records_beyond_archive_page(database):
 with TestClient(app) as c:
  h=login(c);project=c.post('/api/research/project',json={'name':'Public research'},headers=h).json()['id']
  owner=database.one('SELECT user_id FROM research_projects WHERE id=?',(project,))['user_id']
  rows=[(uuid.uuid4().hex,owner,project,'note '+str(i),'kept','[]','[]','{}',now()) for i in range(205)]
  database.execute_many([('INSERT INTO research_notes VALUES(?,?,?,?,?,?,?,?,?)',r) for r in rows])
  database.execute('INSERT INTO research_notes VALUES(?,?,?,?,?,?,?,?,?)',(uuid.uuid4().hex,'another-owner','other','HIDDEN','private','[]','[]','{}',now()))
  assert len(c.get('/api/research/archive').json()['notes'])==200
  exported=c.get('/api/research/archive/export');assert exported.status_code==200
  assert len(exported.json()['notes'])==205 and 'HIDDEN' not in exported.text
  assert 'janus_observations' in exported.json() and 'article_records' in exported.json()


def test_backup_can_run_before_new_tables_exist(database,tmp_path):
 from research_os.backup import backup
 database.execute('DROP TABLE feature_completion')
 target=tmp_path/'old-schema-backup.json';backup(database,target)
 content=json.loads(target.read_text())
 assert 'items' in content['tables'] and 'feature_completion' not in content['tables']


def test_empty_quant_history_is_bounded_to_two_queries(database,monkeypatch):
 from research_os.research.empirical import linkage
 calls=[];original=database.execute
 def count(sql,args=()):calls.append(sql);return original(sql,args)
 monkeypatch.setattr(database,'execute',count)
 result=linkage(database,'반도체','DEXKOUS')
 assert len(calls)==2 and all(x['status']=='insufficient_data' for x in result['lags'])
 assert not any('FROM runs' in sql for sql in calls) # no ten-year coverage scan without completed news months


def test_collector_preserves_revisions_before_pipeline_runs(database,monkeypatch):
 monkeypatch.delenv('FRED_API_KEY',raising=False)
 class Fetch:
  value=1300
  def get(self,url):return 200,f'observation_date,DEXKOUS\n2026-10-01,{self.value}\n2099-01-01,1\n'.encode(),{}
 f=Fetch();entry=('DEXKOUS','FX','KRW','daily','Fed')
 assert collect_series(database,f,entry,True)['count']==1
 first=database.one('SELECT collected_at FROM observations')['collected_at']
 f.value=1310;assert collect_series(database,f,entry,True)['status']=='success'
 rows=database.all('SELECT * FROM observation_vintages ORDER BY available_at')
 assert [r['value'] for r in rows]==[1300,1310] and rows[0]['available_at']==first
 assert database.one("SELECT count(*) AS n FROM observations WHERE date='2099-01-01'")['n']==0


def test_research_industry_does_not_inherit_general_feed_fallback():
 r=item('[포토] 제6회 스마트금융 대상 수상자');r.update(category='거시경제',tags='["거시경제"]')
 assert extract_features(r)['industries']==[]


def test_successful_rss_without_analysis_is_not_a_zero_news_chart(database):
 live_source(database);store_entries(database,[item('HBM 공장 증설')])
 end=datetime.now(KST).date();d=trends(database,'반도체',7,end=end)
 assert d['processing']['status']=='never_run' and d['processing']['pending_news']==1
 assert all(p['value'] is None for p in d['timeline'])
 process(database);d=trends(database,'반도체',7,end=end)
 assert d['processing']['status']=='ready' and d['timeline'][-1]['value']==1
