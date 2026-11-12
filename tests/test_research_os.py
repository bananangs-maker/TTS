import json,os,math
from datetime import datetime,timezone,timedelta
import pytest
from fastapi.testclient import TestClient
from research_os.db import DB
from research_os.core import canonical_url,importance,similar
from research_os.collector import parse_feed,store_entries,collect_source
from research_os.analytics import keyword_signals,indicator_stats
from research_os.catalog import initialize,SOURCES
from research_os.app import app,password_hash
from research_os.backup import backup,restore
@pytest.fixture
def database(tmp_path,monkeypatch):
 monkeypatch.setenv('LOCAL_DB_PATH',str(tmp_path/'test.db'));monkeypatch.delenv('TURSO_DATABASE_URL',raising=False);monkeypatch.delenv('RENDER',raising=False);monkeypatch.setenv('ADMIN_PASSWORD_HASH',password_hash('only-for-tests-long-password'));monkeypatch.setenv('ADMIN_USERNAME','researcher')
 d=DB();d.migrate();initialize(d);return d

def sample(source=None):
 s=source or SOURCES[0]
 return parse_feed(b'<rss version="2.0"><channel><title>Test fixture</title><item><title>HBM investment grows 20 percent</title><link>https://example.org/test?utm_source=x</link><pubDate>Tue, 10 Nov 2026 00:00:00 GMT</pubDate><description>BODY MUST NOT BE STORED</description></item></channel></rss>',s)[0]

def test_url_security_and_tracking():
 assert canonical_url('https://example.org/path?z=1&utm_source=test&a=2#x')=='https://example.org/path?a=2&z=1'
 for value in ['javascript:alert(1)','http://127.0.0.1/a','https://user:pass@example.org/']:
  with pytest.raises(ValueError):canonical_url(value)

def test_rss_atom_and_dates():
 item=sample()[0];assert item['summary']=='';assert item['published_at']=='2026-11-10T00:00:00+00:00'
 atom=b'<feed xmlns="http://www.w3.org/2005/Atom"><title>Test</title><entry><title>Battery news</title><id>urn:1</id><link href="https://example.org/atom"/><updated>2026-11-10T00:00:00Z</updated></entry></feed>'
 entries,_,_=parse_feed(atom,SOURCES[0]);assert entries[0]['published_at'] is None # updated is not a publication date
 with pytest.raises(ValueError):parse_feed(b'<html>blocked</html>',SOURCES[0])

def test_duplicate_storage_and_fts(database):
 data=sample();assert store_entries(database,data)==(1,0);assert store_entries(database,data)==(0,1)
 assert database.one('SELECT count(*) AS n FROM items')['n']==1
 assert database.all('SELECT id FROM item_search WHERE item_search MATCH ?',( 'HBM',))
 assert not similar('HBM investment grows 20 percent','HBM investment grows 30 percent')

def test_reproducible_score():
 at=datetime(2026,11,11,tzinfo=timezone.utc);a=importance('HBM CAPEX investment',at.isoformat(),'news',at=at)
 assert a==importance('HBM CAPEX investment',at.isoformat(),'news',at=at)
 assert 0<=a[0]<=100;assert round(sum(a[1].values()),2)==a[0]
 old=importance('HBM CAPEX investment',(at-timedelta(days=30)).isoformat(),'news',at=at)
 assert old[0]<a[0]

def test_new_sources_do_not_create_surge(database):
 store_entries(database,sample());signals=keyword_signals(database)
 assert all(k['status']=='insufficient_history' for k in signals['keywords'])

def test_fixed_cohort_surge_and_outage_exclusion(database):
 at=datetime(2026,11,11,tzinfo=timezone.utc);source=SOURCES[0]['id'];database.execute('UPDATE sources SET first_success=? WHERE id=?',((at-timedelta(days=50)).isoformat(),source))
 for day in range(1,36):
  stamp=(at-timedelta(days=day)).isoformat();database.execute('INSERT INTO runs(id,source_id,started_at,finished_at,status) VALUES(?,?,?,?,?)',(str(day),source,stamp,stamp,'success'))
 entries=sample();base=entries[0]
 # Enough independent dated fixtures to exercise a 7-day pulse against a stable source.
 for i in range(7):
  entry={**base,'id':'spike'+str(i),'url':'https://example.org/spike'+str(i),'title':'HBM pulse '+str(i),'title_key':'hbmpulse'+str(i),'published_at':(at-timedelta(days=1)).isoformat()}
  store_entries(database,[entry])
 signal=next(k for k in keyword_signals(database,at)['keywords'] if k['keyword']=='HBM')
 assert signal['status']=='new_topic'
 database.execute('DELETE FROM runs WHERE source_id=?',(source,));assert not keyword_signals(database,at)['eligible_sources']

def test_indicator_frequency_and_no_zero_division():
 points=[{'date':f'2026-{m:02d}-01','value':float(m)} for m in range(1,11)]
 a=indicator_stats(points,'CPIAUCSL','monthly');assert a['day'] is None and a['week'] is None;assert a['moving_average_30']==5.5
 assert indicator_stats([],'DEXKOUS','daily')['status']=='no_data'
 zero=indicator_stats([{'date':'2026-01-01','value':0},{'date':'2026-01-02','value':1}],'DEXKOUS','daily');assert zero['previous_observation']['percent_change'] is None

def test_feed_failure_is_logged_and_other_sources_continue(database):
 class Broken:
  def get(self,*a):raise ValueError('blocked for test')
 r=collect_source(database,Broken(),SOURCES[0],True);assert r['status']=='failed';assert database.one('SELECT status FROM runs')['status']=='failed'
 assert database.one('SELECT status FROM sources WHERE id=?',(SOURCES[1]['id'],))['status']=='unverified'

def test_auth_csrf_sql_filters_notes_and_persistence(database):
 record=sample()[0];store_entries(database,[record])
 with TestClient(app) as c:
  assert c.get('/api/items').status_code==200;assert c.get('/api/export').status_code==401
  assert c.post('/api/login',json={'username':'researcher','password':'bad'}).status_code==401
  r=c.post('/api/login',json={'username':'researcher','password':'only-for-tests-long-password'});assert r.status_code==200;csrf=r.json()['csrf'];headers={'X-CSRF-Token':csrf}
  assert 'httponly' in r.headers['set-cookie'].lower()
  assert c.post('/api/record',json={'id':record['id'],'bookmarked':True}).status_code==403
  assert c.post('/api/record',headers={**headers,'Origin':'https://evil.invalid'},json={'id':record['id'],'bookmarked':True}).status_code==403
  assert c.post('/api/record',headers=headers,json={'id':record['id'],'bookmarked':True,'note':'한국어 연구 메모','project':'HBM','tags':'CAPEX'}).status_code==200
  assert c.get('/api/items',params={'q':'한국어','saved':True}).json()['total']==1
  assert c.get('/api/items',params={'category':'반도체','language':'ko'}).json()['total']==1
  assert c.get('/api/items',params={'q':"' OR 1=1--"}).status_code==200
  assert c.get('/api/items',params={'start':'not-date'}).status_code==400
  assert c.get('/api/export').json()['items'][0]['note']=='한국어 연구 메모'
  assert c.get('/api/overview').status_code==200;assert c.get('/api/signals').status_code==200
  before=c.get('/api/economy').json();assert len(before['series'])>0
 # New application lifespan / DB object: records persist.
 with TestClient(app) as c:
  c.post('/api/login',json={'username':'researcher','password':'only-for-tests-long-password'})
  assert c.get('/api/items',params={'saved':True}).json()['total']==1

def test_backup_restore_private_records(database,tmp_path):
 data=sample();store_entries(database,data);p=tmp_path/'backup.json';backup(database,p);other=DB(path=str(tmp_path/'restored.db'),url='');restore(other,p)
 assert other.one('SELECT count(*) AS n FROM items')['n']==1
 assert len(other.all('SELECT id FROM item_search WHERE item_search MATCH ? ',('HBM',)))==1

def test_remote_adapter_contract(monkeypatch):
 class Fake:
  def raise_for_status(self):pass
  def json(self):return {'results':[{'type':'ok','response':{'result':{'cols':[{'name':'value'}],'rows':[[{'type':'integer','value':'7'}]],'affected_row_count':0}}}]}
 seen={}
 def post(url,**kw):seen.update(kw);assert url=='https://test-org.turso.io/v2/pipeline';return Fake()
 monkeypatch.setattr('research_os.db.requests.post',post);d=DB(url='libsql://test-org.turso.io',token='test-token-not-live');assert d.one('SELECT ? AS value',(7,))['value']==7
 assert seen['json']['requests'][0]['stmt']['args']==[{'type':'integer','value':'7'}]

def test_production_refuses_ephemeral_db(database,monkeypatch):
 monkeypatch.setenv('RENDER','true')
 with pytest.raises(RuntimeError,match='Turso'):
  with TestClient(app):pass

def test_robots_longest_allow_and_specific_agent():
 from research_os.core import robots_allowed
 assert robots_allowed('User-agent : *\nDisallow: /\nAllow: /portal/','https://www.bok.or.kr/portal/bbs/x')
 assert not robots_allowed('User-agent: *\nDisallow: /rss','https://www.eia.gov/rss/todayinenergy.xml')
 assert not robots_allowed('User-agent: ResearchOS\nDisallow: /\nUser-agent: *\nAllow: /','https://example.org/feed')

def test_calendar_month_reference_not_30_day_alias():
 points=[{'date':'2026-04-30','value':100},{'date':'2026-05-01','value':101},{'date':'2026-05-31','value':104}]
 assert indicator_stats(points,'CPIAUCSL','monthly')['month']['reference_date']=='2026-04-30'

def test_fulltext_korean_and_private_tag_search(database):
 entry=sample()[0];entry.update(title='반도체 투자 증설 공장 공개자료',title_key='반도체투자증설공장공개자료');store_entries(database,[entry])
 with TestClient(app) as c:
  c.post('/api/login',json={'username':'researcher','password':'only-for-tests-long-password'})
  assert c.get('/api/items',params={'q':'반도체'}).json()['total']==1
  assert c.get('/api/items',params={'kind':'report'}).json()['total']==0
  assert c.get('/api/items',params={'source':'kr-hk-economy','category':'반도체'}).json()['total']==1

def test_backup_refuses_nonempty_destination(database,tmp_path):
 store_entries(database,sample());p=tmp_path/'backup.json';backup(database,p)
 with pytest.raises(ValueError,match='empty database'):restore(database,p)

def test_database_failures_return_json_not_html(database,monkeypatch):
 from research_os import app as app_module
 with TestClient(app,raise_server_exceptions=False) as client:
  client.post('/api/login',json={'username':'researcher','password':'only-for-tests-long-password'})
  original=app_module.db
  class Broken:
   def one(self,*args):raise RuntimeError('simulated unavailable database')
  monkeypatch.setattr(app_module,'db',lambda:Broken())
  r=client.get('/api/items')
  assert r.status_code==503
  assert r.headers['content-type'].startswith('application/json')
  assert r.json()['request_id']
  monkeypatch.setattr(app_module,'db',original)

def test_page_queries_are_bounded_without_per_source_or_series_requests(database,monkeypatch):
 from research_os.app import sources,economy
 from research_os import app as app_module
 count=0;original=database.execute
 def counted(*args,**kwargs):
  nonlocal count
  count+=1;return original(*args,**kwargs)
 monkeypatch.setattr(database,'execute',counted);monkeypatch.setattr(app_module,'db',lambda:database)
 sources(user={'user_id':'owner'});assert count<=9 # includes four bounded system-health summaries, still one remote pipeline
 count=0;economy(user={'user_id':'owner'});assert count==2

def test_public_read_does_not_expose_owner_archive(database):
 entry=sample()[0];store_entries(database,[entry])
 database.execute('INSERT INTO records(user_id,item_id,bookmarked,read,note,tags,project,updated_at) VALUES(?,?,?,?,?,?,?,?)',('owner',entry['id'],1,1,'PRIVATE OWNER NOTE','secret tag','secret project','2026-11-11T00:00:00+00:00'))
 with TestClient(app) as c:
  assert c.get('/api/me').json()['authenticated'] is False
  item=c.get('/api/items').json()['items'][0]
  assert item['note']=='' and item['personal_tags']=='' and item['project']=='' and item['bookmarked']==0
  assert c.get('/api/items?saved=true').status_code==401
  assert c.get('/api/overview').json()['saved_items']==[]
  assert c.post('/api/record',json={'id':entry['id'],'bookmarked':True}).status_code==401
  assert c.get('/api/export').status_code==401
  assert c.get('/api/sources').json()['collection_state']=='never_run'

def test_remote_pipeline_batches_startup_and_page_queries(database,monkeypatch,tmp_path):
 import sqlite3
 from research_os import app as app_module
 calls=[];path=str(tmp_path/'remote-simulation.db')
 def post(url,**kwargs):
  requests=kwargs['json']['requests'];calls.append(len(requests)-1);results=[]
  with sqlite3.connect(path) as conn:
   for op in requests:
    if op['type']=='close':results.append({'type':'ok','response':{'type':'close'}});continue
    args=[]
    for arg in op['stmt'].get('args',[]):
     args.append(None if arg['type']=='null' else int(arg['value']) if arg['type']=='integer' else float(arg['value']) if arg['type']=='float' else arg['value'])
    cur=conn.execute(op['stmt']['sql'],args);rows=cur.fetchall() if cur.description else []
    def cell(v):return {'type':'null'} if v is None else {'type':'integer','value':str(v)} if isinstance(v,int) else {'type':'float','value':v} if isinstance(v,float) else {'type':'text','value':str(v)}
    results.append({'type':'ok','response':{'result':{'cols':[{'name':x[0]} for x in cur.description or []],'rows':[[cell(v) for v in row] for row in rows],'affected_row_count':max(0,cur.rowcount)}}})
  class Response:
   def raise_for_status(self):pass
   def json(self):return {'results':results}
  return Response()
 monkeypatch.setattr('research_os.db.requests.post',post)
 remote=DB(url='libsql://example-test.turso.io',token='fake-local-test-only');monkeypatch.setattr(app_module,'db',lambda:remote)
 with TestClient(app) as client:
  assert len(calls)==3 # Schema + catalog + FTS repair, not dozens of round trips.
  for endpoint in ['/api/items','/api/overview','/api/sources','/api/economy']:
   calls.clear();assert client.get(endpoint).status_code==200;assert len(calls)==1,endpoint
  calls.clear();assert client.get('/api/signals').status_code==200;assert len(calls)==3

def test_public_read_can_start_without_password_hash(database,monkeypatch):
 monkeypatch.delenv('ADMIN_PASSWORD_HASH',raising=False)
 with TestClient(app) as c:
  assert c.get('/api/me').status_code==200
  assert c.get('/api/items').status_code==200
  assert c.post('/api/login',json={'username':'researcher','password':'anything'}).status_code==401


def test_public_menu_reads_with_expired_cookie_and_private_writes_stay_closed(database):
 entry=sample()[0];store_entries(database,[entry])
 database.execute('INSERT INTO records VALUES(?,?,?,?,?,?,?,?)',('owner',entry['id'],1,1,'HIDDEN MEMO','private-tag','private-project','2026-11-11T00:00:00+00:00'))
 with TestClient(app) as c:
  c.cookies.set('research_session','expired-or-invalid-session')
  public=['/','/api/me','/api/items?kind=news','/api/items?kind=report','/api/overview','/api/economy','/api/signals','/api/sources','/api/research/config','/api/research/trends','/api/research/events','/api/research/linkage','/api/research/reports','/api/research/signals']
  for path in public:
   r=c.get(path,follow_redirects=False);assert r.status_code==200,(path,r.text[:100]);assert 'HIDDEN MEMO' not in r.text and 'private-tag' not in r.text
  for path in ['/api/items?saved=true','/api/items?project=private-project','/api/export','/api/research/archive','/api/research/archive/export']:
   assert c.get(path,follow_redirects=False).status_code==401
  for path,payload in [('/api/record',{'id':entry['id'],'note':'ATTACK'}),('/api/source',{'id':entry['source_id'],'enabled':False,'interval_minutes':180}),('/api/research/project',{'name':'ATTACK'}),('/api/research/report',{'period':'daily'}),('/api/janus/import',{'symbol':'NEWS','kind':'news_signal','source_url':'https://example.org','csv_text':'date,value,available_at'})]:
   assert c.post(path,json=payload,follow_redirects=False).status_code==401,path
  assert database.one('SELECT note FROM records WHERE user_id=?',('owner',))['note']=='HIDDEN MEMO'


def test_focus_filter_preserves_off_topic_archive_and_english_boundaries(database):
 from research_os.core import classify
 entries=[]
 for number,title in enumerate(['[포토] 스마트금융 대상 수상자','HBM 공장 증설','press conference revenue','ESS battery storage','기준금리 인하']):
  row=sample()[0];row.update(id='focus-'+str(number),url='https://example.org/focus-'+str(number),title=title,title_key=title);entries.append(row)
 store_entries(database,entries)
 with TestClient(app) as c:
  all_items=c.get('/api/items?kind=news').json();focused=c.get('/api/items?kind=news&relevant=true').json()
  assert all_items['total']==5 and focused['total']==3
  assert {r['title'] for r in focused['items']}=={'HBM 공장 증설','ESS battery storage','기준금리 인하'}
  assert database.one('SELECT count(*) AS n FROM items')['n']==5
 assert '2차전지' not in classify('press conference revenue')[1]


def test_health_storage_fingerprint_never_depends_on_token(database,monkeypatch):
 a=DB(url='libsql://fingerprint-test.turso.io',token='secret-one');b=DB(url='https://fingerprint-test.turso.io',token='secret-two')
 assert a.storage_id()==b.storage_id() and len(a.storage_id())==12
 assert a.storage_id()!=DB(url='libsql://other.turso.io',token='secret-one').storage_id()
 with TestClient(app) as c:
  health=c.get('/healthz').json();assert health['storage_id']=='local-development' and 'commit' in health
  assert 'secret-one' not in str(health)
