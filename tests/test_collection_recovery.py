"""Regression coverage for the production collection failures."""
import json
from datetime import datetime,timezone,timedelta
import pytest,requests
from research_os.db import DB
from research_os.catalog import SOURCES,initialize
from research_os.collector import Fetcher,parse_feed,collect_source,store_entries

@pytest.fixture
def db(tmp_path):
 d=DB(path=str(tmp_path/'recovery.db'),url='');d.migrate();initialize(d);return d

def feed(title='A new semiconductor factory investment 123'):
 return ('<rss version="2.0"><channel><title>fixture</title><item><title>'+title+'</title><link>https://example.org/recovery</link><pubDate>Sun, 15 Nov 2026 00:00:00 GMT</pubDate></item></channel></rss>').encode()

def test_force_bypasses_conditional_headers_and_counts_readback(db):
 db.execute('UPDATE sources SET etag=?,last_modified=? WHERE id=?',('old','old',SOURCES[0]['id']))
 class Source:
  def get(self,url,headers):
   assert headers=={};return 200,feed(),{}
 first=collect_source(db,Source(),SOURCES[0],True)
 assert (first['fetched'],first['new'],first['inserted'],first['duplicates'])==(1,1,1,0)
 second=collect_source(db,Source(),SOURCES[0],True)
 assert (second['new'],second['inserted'],second['duplicates'])==(0,0,1)
 assert second['latest_stored']=='2026-11-15T00:00:00+00:00'
 assert len(db.all('SELECT * FROM collection_diagnostics'))==2

def test_url_duplicates_older_than_similarity_window_are_not_new(db):
 entry=parse_feed(feed(),SOURCES[0])[0][0]
 entry['collected_at']=(datetime.now(timezone.utc)-timedelta(days=90)).isoformat()
 store_entries(db,[entry]);metrics={}
 assert store_entries(db,parse_feed(feed(),SOURCES[0])[0],metrics)==(0,1)
 assert metrics['new']==0

def test_retry_is_bounded_and_next_series_can_recover(monkeypatch):
 f=Fetcher();calls=[]
 class Response:
  status_code=200;headers={}
  def iter_content(self,n):return iter([b'ok'])
  def raise_for_status(self):pass
  def close(self):pass
 def get(*args,**kwargs):
  calls.append(args)
  if len(calls)<=3:raise requests.ReadTimeout('temporary endpoint timeout')
  return Response()
 monkeypatch.setattr(f.session,'get',get);monkeypatch.setattr('research_os.collector.time.sleep',lambda _:None)
 with pytest.raises(requests.ReadTimeout):f.raw('https://fred.stlouisfed.org/graph/fredgraph.csv?id=DEXKOUS')
 assert len(calls)==3
 assert f.raw('https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10')[1]==b'ok'

def test_unverified_robots_never_requests_feed(monkeypatch):
 f=Fetcher();calls=[]
 def raw(url,headers=None):
  calls.append(url)
  response=requests.Response();response.status_code=403
  raise requests.HTTPError(response=response)
 monkeypatch.setattr(f,'raw',raw)
 with pytest.raises(ValueError,match='robots.txt cannot be verified'):f.get(next(s['url'] for s in SOURCES if s['id']=='storage'))
 assert calls==['https://www.energy-storage.news/robots.txt']

def test_parse_failure_has_stage_and_preserves_existing_items(db):
 store_entries(db,parse_feed(feed(),SOURCES[0])[0])
 class Bad:
  def get(self,*args):return 200,b'<html>unavailable</html>',{}
 result=collect_source(db,Bad(),SOURCES[0],True)
 assert result['status']=='failed' and result['error_stage']=='parse'
 assert db.one('SELECT count(*) AS n FROM items')['n']==1


def test_missing_database_write_cannot_report_success(db,monkeypatch):
 original=db.execute
 def dropped(sql,args=()):
  if sql.startswith('INSERT OR IGNORE INTO items('):return {'rows':[],'changes':0}
  return original(sql,args)
 monkeypatch.setattr(db,'execute',dropped)
 class Source:
  def get(self,*args):return 200,feed(),{}
 result=collect_source(db,Source(),SOURCES[0],True)
 assert result['status']=='failed' and result['error_stage']=='store_verify'
 assert 'read-back mismatch' in result['error']

def test_official_report_lists_parse_dates_and_fail_closed():
 from research_os.catalog import SOURCES
 kiet=next(s for s in SOURCES if s['id']=='kiet-issues')
 kita=next(s for s in SOURCES if s['id']=='kita-reports')
 body=b'<ul><li><a href="./issueView?issue_no=872&amp;pg=1"><strong>Test report</strong></a><span class="date">2026.10.26</span></li></ul>'
 entries,invalid,_=parse_feed(body,kiet)
 assert len(entries)==1 and invalid==0
 assert entries[0]['published_at']=='2026-10-25T15:00:00+00:00'
 assert entries[0]['url']=='https://www.kiet.re.kr/research/issueView?issue_no=872'
 body=b'''<li><div class="subject"><a onclick="goDetailPage('2993', 'TRADE_FOCUS');" title="Report">Trade report</a></div><i class="icon-clock1">date</i>2026.11.12</li>'''
 entries,invalid,_=parse_feed(body,kita)
 assert len(entries)==1 and entries[0]['url'].endswith('tradeFocusDetail.do?no=2993')
 assert entries[0]['published_at']=='2026-11-11T15:00:00+00:00'
 with pytest.raises(ValueError,match='missing title/date'):parse_feed(body.replace(b'2026.11.12',b''),kita)

def test_production_identity_mismatch_stops_verification(db,monkeypatch):
 from research_os.operations import verify_production
 class Response:
  def raise_for_status(self):pass
  def json(self):return {'storage':'turso','storage_id':'different-db'}
 monkeypatch.setattr('research_os.operations.requests.get',lambda *a,**k:Response())
 with pytest.raises(ValueError,match='storage identities differ'):verify_production(db,'https://research-os-gd1l.onrender.com')

def test_production_numeric_value_mismatch_is_not_accepted(db,monkeypatch):
 from research_os.operations import verify_production
 db.execute("INSERT INTO observations VALUES('DEXKOUS','2026-11-12',1400,'2026-11-13')")
 payloads={
 '/healthz':{'storage':'turso','storage_id':db.storage_id(),'commit':'fixture'},
 '/api/sources':{'system':{'storage_id':db.storage_id(),'records':{'news':0,'reports':0},'observations':1},'sources':[]},
 '/api/items?kind=news&limit=1':{'total':0,'items':[]},
 '/api/items?kind=report&limit=1':{'total':0,'items':[]},
 '/api/economy':{'series':[{'id':'DEXKOUS','unit':'원 / USD','points':[{'date':'2026-11-12','value':1}]}]}}
 class Response:
  def __init__(self,p):self.p=p
  def raise_for_status(self):pass
  def json(self):return self.p
 def get(url,**kwargs):return Response(payloads[url.replace('https://research-os-gd1l.onrender.com','')])
 monkeypatch.setattr('research_os.operations.requests.get',get)
 with pytest.raises(ValueError,match='date/value differs'):verify_production(db,'https://research-os-gd1l.onrender.com')
 payloads['/api/economy']['series'][0]['points'][0]['value']=1400
 assert verify_production(db,'https://research-os-gd1l.onrender.com')['verified']


def test_policy_pause_preserves_articles_and_applies_only_once(db):
 source=next(s for s in SOURCES if s['id']=='storage')
 # Reproduce an existing deployment before the one-time policy hold.
 db.execute('DELETE FROM schema_versions WHERE version=3')
 db.execute("UPDATE sources SET enabled=1,status='failed' WHERE id='storage'")
 store_entries(db,parse_feed(feed(),source)[0])
 initialize(db)
 held=db.one("SELECT * FROM sources WHERE id='storage'")
 assert held['enabled']==0 and held['status']=='disabled'
 assert db.one("SELECT count(*) AS n FROM items WHERE source_id='storage'")['n']==1
 class MustNotFetch:
  def get(self,*args):raise AssertionError('paused source must not make network requests')
 assert collect_source(db,MustNotFetch(),source,True)['status']=='disabled'
 # An administrator can later re-enable after a policy review; startup preserves that.
 db.execute("UPDATE sources SET enabled=1 WHERE id='storage'")
 initialize(db)
 assert db.one("SELECT enabled FROM sources WHERE id='storage'")['enabled']==1
