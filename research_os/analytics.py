import json,math,statistics,calendar
from datetime import datetime,timezone,timedelta
from .core import RULES

def keyword_signals(db,at=None):
 """Compare only a stable source cohort with complete 35-day collection coverage.
Daily >=1 successful/not-modified run is required in >=70% days of each window.
No claim of industry volume changes from initial RSS backfill or new sources.
"""
 at=at or datetime.now(timezone.utc);s=RULES['signal'];day=at.date();cut=at-timedelta(days=35);recent=at-timedelta(days=7)
 sources=db.all("SELECT id,first_success FROM sources WHERE enabled=1 AND kind='news'")
 eligible=[];excluded=[]
 for source in sources:
  first=source['first_success']
  if not first or datetime.fromisoformat(first)>cut:excluded.append(source['id']);continue
  runs=db.all("SELECT DISTINCT substr(started_at,1,10) AS day FROM runs WHERE source_id=? AND started_at>=? AND status IN ('success','not_modified')",(source['id'],cut.isoformat()))
  days={r['day'] for r in runs};before=sum((day-timedelta(days=i)).isoformat() in days for i in range(8,36))/28;after=sum((day-timedelta(days=i)).isoformat() in days for i in range(1,8))/7
  if min(before,after)>=s['min_source_coverage']:eligible.append(source['id'])
  else:excluded.append(source['id'])
 output=[]
 for word in RULES['tracked_keywords']:
  if not eligible:
   descriptive=db.one("SELECT count(*) AS n FROM items WHERE kind='news' AND published_at>=? AND published_at<? AND lower(title) LIKE ?",(recent.isoformat(),at.isoformat(),'%'+word.lower()+'%'))['n']
   output.append(dict(keyword=word,status='insufficient_history',reason='35일 이상 운영한 고정 정보원과 양 기간 70% 이상 일별 수집 성공이 필요합니다.',recent=descriptive,baseline=None,growth=None,z=None,source_count=0));continue
  marks=','.join('?' for _ in eligible)
  rows=db.all(f'SELECT published_at,title FROM items WHERE kind=\'news\' AND source_id IN ({marks}) AND published_at>=? AND published_at<?',(*eligible,cut.isoformat(),at.isoformat()))
  buckets=[0]*35
  for r in rows:
   if word.lower() not in r['title'].lower():continue
   age=(day-datetime.fromisoformat(r['published_at']).date()).days
   if 1<=age<=35:buckets[age-1]+=1
  weekly=sum(buckets[:7]);historic=buckets[7:35];baseline=sum(historic)/4;std=statistics.pstdev(historic)*math.sqrt(7) if len(historic)>1 else 0
  growth=weekly/baseline-1 if baseline>0 else None;z=(weekly-baseline)/std if std>0 else None
  status='new_topic' if baseline==0 and weekly>=s['min_weekly_articles'] else 'surge' if weekly>=s['min_weekly_articles'] and growth is not None and growth>=s['growth_threshold'] and z is not None and z>=s['z_threshold'] else 'normal'
  output.append(dict(keyword=word,status=status,recent=weekly,baseline=round(baseline,2),growth=growth,z=round(z,3) if z is not None else None,source_count=len(eligible),reason='최근 완료된 7일 / 직전 28일 주간 평균. 고정 소스, 수집 커버리지 보정. Z=(최근7일-기준주간평균)/(과거 일별 표준편차×√7).'))
 return {'keywords':output,'eligible_sources':eligible,'excluded_sources':excluded,'observed_at':at.isoformat(),'warning':'저장된 RSS 메타데이터의 빈도이며 전체 시장 뉴스량이 아닙니다.'}

def indicator_stats(points,sid,frequency):
 if not points:return {'status':'no_data','reason':'실제 관측값이 없습니다.'}
 points=sorted(points,key=lambda p:p['date']);last=points[-1];prev=points[-2] if len(points)>1 else None;latest=datetime.fromisoformat(last['date']);values=[p['value'] for p in points[-30:]];changes=[b['value']-a['value'] for a,b in zip(points[-31:-1],points[-30:])] if len(points)>30 else [b['value']-a['value'] for a,b in zip(points,points[1:])]
 def reference(days):
  target=(latest-timedelta(days=days)).date().isoformat();prior=[p for p in points if p['date']<=target];return prior[-1] if prior else None
 def delta(p):return {'reference_date':p['date'],'change':last['value']-p['value'],'percent_change':(last['value']/p['value']-1)*100 if p['value']!=0 else None} if p else None
 daily=delta(prev) if frequency=='daily' else None;week=delta(reference(7)) if frequency=='daily' else None;month_num=latest.month-1 or 12;month_year=latest.year-(latest.month==1);month_day=min(latest.day,calendar.monthrange(month_year,month_num)[1]);month_cut=latest.replace(year=month_year,month=month_num,day=month_day).date().isoformat();monthly_prior=[p for p in points if p['date']<=month_cut];month=delta(monthly_prior[-1] if monthly_prior else None) if frequency!='quarterly' else None
 # Rate thresholds are percentage-point deltas; price/FX thresholds are ratios.
 threshold=RULES['indicator_thresholds'].get(sid);rate=sid.startswith(('DGS','DFED','IRLTLT')) or sid=='A191RL1Q225SBEA';measure=(last['value']-prev['value']) if prev and rate else (last['value']/prev['value']-1) if prev and prev['value'] else None
 return dict(status='ok',change_unit='%p' if rate else None,latest=last,previous=prev,previous_observation=delta(prev),day=daily,week=week,month=month,moving_average_30=statistics.mean(values),volatility_30=statistics.pstdev(changes) if len(changes)>1 else None,window_observations=len(values),high_30=max(values),low_30=min(values),threshold=threshold,threshold_unit='percentage_points' if rate else 'ratio',threshold_exceeded=bool(threshold is not None and measure is not None and abs(measure)>threshold),formula='전일은 직전 유효 관측(휴일 제외), 전주는 7일 전, 전월은 달력상 한 달 전 이하의 가장 가까운 관측. 금리·성장률 차이는 %p. 이동평균·고저는 최근 30관측, 변동성은 관측 차분 모집단 표준편차. 월·분기 자료에 일별 변화를 계산하지 않습니다.')
