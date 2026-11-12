"""Independent scheduled post-collection processing and versioned reports."""
import argparse,json,uuid,statistics,math
from datetime import datetime,timedelta
from .engine import process,trends,VERSION,CONFIG,INDUSTRIES,dump,digest,now,KST
from .reports import generate
from ..db import DB
from ..analytics import indicator_stats

def detect(db):
 before=db.one('SELECT count(*) AS n FROM detected_signals')['n'];candidates=[];date=(datetime.now(KST).date()-timedelta(days=1)).isoformat()
 for industry in INDUSTRIES:
  d=trends(db,industry,90)
  for k in d['keywords']:
   if k['status'] in ['surge','new_topic']:candidates.append(dict(signal_type='keyword_'+k['status'],industry=industry,subject=k['keyword'],period_end=date,value=k['z'],threshold=CONFIG['signal_z'],comparison='최근 완료 7일 / 직전 28일; 고정 정보원; 일별 결측 없음',evidence=dump(k)))
  timeline=d['timeline'];latest=timeline[-7:];prev=timeline[-14:-7]
  def weekly_score(rows):
   if any(p['cohort_value'] is None for p in rows):return None
   P=sum(p['cohort_positive'] for p in rows);N=sum(p['cohort_negative'] for p in rows)
   return 100*(P-N)/(P+N) if P+N>=CONFIG['min_sentiment_sample'] else None
  a,b=weekly_score(latest),weekly_score(prev)
  if a is not None and b is not None and abs(a-b)>=CONFIG['sentiment_jump']:
   candidates.append(dict(signal_type='sentiment_shift',industry=industry,subject=industry,period_end=date,value=a-b,threshold=CONFIG['sentiment_jump'],comparison='고정 정보원의 주간 합산 심리지수 차이; 양 주 분류 표본 20 이상',evidence=dump({'recent':a,'previous':b,'dates':[p['date'] for p in latest+prev]})))
  volumes=[p['cohort_value'] for p in timeline[-35:]]
  if len(volumes)==35 and all(v is not None for v in volumes):
   recent=sum(volumes[-7:]);base=sum(volumes[:-7])/4;sd=statistics.pstdev(volumes[:-7])*math.sqrt(7);z=(recent-base)/sd if sd else None;growth=recent/base-1 if base else None
   if recent>=CONFIG['signal_min_count'] and growth is not None and growth>=CONFIG['signal_growth'] and z is not None and z>=CONFIG['signal_z']:
    candidates.append(dict(signal_type='industry_volume_surge',industry=industry,subject=industry,period_end=date,value=z,threshold=CONFIG['signal_z'],comparison='고정 정보원 최근7일/직전28일, 빠진 수집일 없음',evidence=dump({'recent':recent,'baseline':base,'growth':growth,'z':z,'sources':d['eligible_sources']})))
 result=db.execute_many([('SELECT * FROM series',()),('SELECT * FROM observations ORDER BY series_id,date',())]);by={}
 for p in result[1]['rows']:by.setdefault(p['series_id'],[]).append(p)
 for s in result[0]['rows']:
  points=by.get(s['id'],[]);a=indicator_stats(points,s['id'],s['frequency'])
  if not points:continue
  changes=[b['value']-a['value'] for a,b in zip(points[-61:-1],points[-60:])] if len(points)>60 else [b['value']-a['value'] for a,b in zip(points,points[1:])];past=changes[:-1];sd=statistics.pstdev(past) if len(past)>=30 else None;z=(changes[-1]-statistics.mean(past))/sd if sd else None
  ewma=points[0]['value']
  for point in points[1:]:ewma=.2*point['value']+.8*ewma
  p95=statistics.quantiles([abs(x) for x in past],n=20,method='inclusive')[18] if len(past)>=30 else None
  if a['threshold_exceeded'] or (z is not None and abs(z)>3):
   candidates.append(dict(signal_type='indicator_threshold' if a['threshold_exceeded'] else 'indicator_z',industry='거시경제',subject=s['id'],period_end=points[-1]['date'],value=(a['previous_observation']['change'] if a['threshold_unit']=='percentage_points' else a['previous_observation']['percent_change']/100) if a['threshold_exceeded'] else z,threshold=a['threshold'] if a['threshold_exceeded'] else 3,comparison='직전 실제 관측 대비. Z는 현재를 제외한 최근 최대 59개 차분 기준.',evidence=dump({'analysis':a,'z':z,'ewma_alpha_0_2':ewma,'absolute_change_p95':p95,'source_url':s['url'],'unit':s['unit'],'observation_date':points[-1]['date']})))
 # Timely, explicit event candidates are observations, never validated facts.
 event_rows=db.all("SELECT DISTINCT e.* FROM industry_events e JOIN event_sources es ON es.event_id=e.id JOIN article_features f ON f.item_id=es.item_id WHERE f.version=? AND f.backfill=0 AND e.event_type IN ('policy_announcement','subsidy_tariff','investment_announcement','capex_increase','capex_cut','factory_expansion','investment_delay')",(VERSION,))
 existing={r['id'] for r in db.all("SELECT id FROM detected_signals WHERE signal_type='event_candidate'")}
 for event in event_rows:
  rid=digest(['event_candidate',event['id']])[:32]
  if rid in existing:continue
  candidates.append(dict(id=rid,signal_type='event_candidate',industry=event['industry'],subject=event['title'],period_end=event['announcement_date'] or date,value=None,threshold=None,comparison='수집 제목에 명시된 정책·투자 표현; 검증 전 후보이며 통계적 급증 판정이 아님',evidence=dump(event)))
 operations=[]
 for c in candidates:
  rid=c.pop('id',None) or digest([VERSION,c['signal_type'],c['industry'],c['subject'],c['period_end']])[:32];values={'id':rid,**c,'version':VERSION,'detected_at':now()};cols=list(values);operations.append(('INSERT OR IGNORE INTO detected_signals('+','.join(cols)+') VALUES('+','.join('?' for _ in cols)+')',list(values.values())))
 for offset in range(0,len(operations),60):db.execute_many(operations[offset:offset+60])
 return db.one('SELECT count(*) AS n FROM detected_signals')['n']-before

def run(db):
 db.migrate();processed=0
 while True:
  d=process(db);processed+=d['processed']
  if not d['remaining']:break
 signals=detect(db);reports=[generate(db,period)['id'] for period in ['daily','weekly','monthly']];today=datetime.now(KST).date().isoformat();reports.append(generate(db,'daily',today,today)['id'])
 return dict(version=VERSION,processed=processed,signals=signals,reports=reports)
if __name__=='__main__':print(json.dumps(run(DB()),ensure_ascii=False))
