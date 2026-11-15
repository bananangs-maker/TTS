"""Read-only DB/production verification. Never outputs credentials or database URLs."""
import argparse,json,os
from datetime import datetime,timezone,timedelta
import requests
from .db import DB

PRODUCTION='https://research-os-gd1l.onrender.com'

def snapshot(db):
 queries=[("SELECT count(*) AS n FROM items WHERE kind='news'",()),("SELECT count(*) AS n FROM items WHERE kind='report'",()),('SELECT count(*) AS n FROM observations',()),('SELECT source_id,count(*) AS count,max(published_at) AS latest_published,max(collected_at) AS latest_collected FROM items GROUP BY source_id',()),('SELECT o.series_id,s.unit,count(*) AS count,max(o.date) AS latest_observation,(SELECT value FROM observations v WHERE v.series_id=o.series_id ORDER BY date DESC LIMIT 1) AS latest_value FROM observations o JOIN series s ON s.id=o.series_id GROUP BY o.series_id',()),('SELECT id,enabled,interval_minutes,last_success,last_attempt,error FROM sources',())]
 results=db.execute_many(queries);stamp=datetime.now(timezone.utc);sources=results[5]['rows']
 for s in sources:
  s['collection_delayed']=bool(s['enabled'] and (not s['last_success'] or stamp-datetime.fromisoformat(s['last_success'])>timedelta(minutes=max(720,s['interval_minutes']*2))))
 return dict(storage_id=db.storage_id(),news=results[0]['rows'][0]['n'],reports=results[1]['rows'][0]['n'],observations=results[2]['rows'][0]['n'],by_source=results[3]['rows'],by_series=results[4]['rows'],sources=sources,checked_at=stamp.isoformat())

def verify_production(db,origin):
 if origin.rstrip('/')!=PRODUCTION:raise ValueError('Production verification origin not approved')
 def read(path):
  response=requests.get(PRODUCTION+path,timeout=(10,45));response.raise_for_status();return response.json()
 health=read('/healthz')
 if health.get('storage')!='turso' or health.get('storage_id')!=db.storage_id():raise ValueError('Actions and Render storage identities differ')
 state=snapshot(db);api=read('/api/sources');records=api['system']['records']
 if api['system']['storage_id']!=state['storage_id']:raise ValueError('Production API storage identity differs')
 for key in ('news','reports'):
  if records[key]!=state[key]:raise ValueError('Production count differs: '+key)
 if api['system']['observations']!=state['observations']:raise ValueError('Production observation count differs')
 for kind in ('news','report'):
  page=read('/api/items?kind='+kind+'&limit=1')
  if page['total']!=state['news' if kind=='news' else 'reports']:raise ValueError('Item API count differs: '+kind)
  expected=max((r['latest_published'] for r in state['by_source'] if r['latest_published'] and any(s['id']==r['source_id'] and s['kind']==kind for s in api['sources'])),default=None)
  actual=page['items'][0]['published_at'] if page['items'] else None
  if actual!=expected:raise ValueError('Latest publication differs: '+kind)
 economy=read('/api/economy');points={s['id']:s['points'] for s in economy['series']}
 if sum(map(len,points.values()))!=state['observations']:raise ValueError('Economy API observation count differs')
 for series in state['by_series']:
  actual=points.get(series['series_id'],[])
  if not actual or actual[-1]['date']!=series['latest_observation'] or actual[-1]['value']!=series['latest_value']:raise ValueError('Economy latest date/value differs: '+series['series_id'])
  if next(s['unit'] for s in economy['series'] if s['id']==series['series_id'])!=series['unit']:raise ValueError('Economy unit differs: '+series['series_id'])
 return dict(verified=True,commit=health.get('commit'),snapshot=state)

if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--require-remote',action='store_true');parser.add_argument('--identity-only',action='store_true');parser.add_argument('--production-url');args=parser.parse_args();db=DB()
 if args.require_remote and not db.remote:raise SystemExit('Persistent Turso configuration required; refusing local fallback')
 expected=os.getenv('EXPECTED_STORAGE_ID')
 if expected and db.storage_id()!=expected:raise SystemExit('Database identity differs from approved production identity; refusing collection')
 result={'storage_id':db.storage_id()} if args.identity_only else verify_production(db,args.production_url) if args.production_url else snapshot(db)
 print(json.dumps(result,ensure_ascii=False),flush=True)
