"""Deterministic, title-only research features and conservative event candidates."""
import hashlib,json,re,unicodedata,uuid,statistics,math
from collections import Counter,defaultdict
from datetime import datetime,timedelta,timezone
from pathlib import Path
from ..core import now,importance,RULES,title_key
KST=timezone(timedelta(hours=9))
CONFIG=json.loads((Path(__file__).resolve().parents[2]/'config/research.json').read_text())
ALGORITHM_HASH=hashlib.sha256(b''.join(Path(__file__).with_name(n).read_bytes() for n in ['engine.py','empirical.py','pipeline.py','reports.py'])).hexdigest()
VERSION=CONFIG['version']+'-'+hashlib.sha256(json.dumps([CONFIG,RULES,ALGORITHM_HASH],sort_keys=True,ensure_ascii=False).encode()).hexdigest()[:10]
INDUSTRIES=tuple(CONFIG['keywords'])
def dump(v):return json.dumps(v,ensure_ascii=False,sort_keys=True,allow_nan=False)
def digest(v):return hashlib.sha256(dump(v).encode()).hexdigest()
def stamp(s):
 d=datetime.fromisoformat(s.replace('Z','+00:00'))
 return d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d

def day(s):return stamp(s).astimezone(KST).date().isoformat()
def contains(text,term):
 text=unicodedata.normalize('NFKC',text).casefold();term=unicodedata.normalize('NFKC',term).casefold()
 # ASCII acronyms must not match arbitrary word substrings (EV != revenue).
 pattern=re.escape(term)
 if term and term[0].isascii() and term[0].isalnum():pattern=r'(?<![a-z0-9])'+pattern
 if term and term[-1].isascii() and term[-1].isalnum():pattern+=r'(?![a-z0-9])'
 return bool(re.search(pattern,text))
def matching(text,terms):return [w for w in terms if contains(text,w)]
def extract_features(item):
 text=item['title'];tags=json.loads(item.get('tags','[]'));industries=[x for x in INDUSTRIES if x in tags or item['category']==x]
 # Explicit issuer names provide an industry context; do not infer from general investment wording.
 companies=[name for name,aliases in CONFIG['companies'].items() if matching(text,aliases)]
 if any(c in companies for c in ['삼성전자','SK하이닉스','TSMC','Intel','Micron']) and '반도체' not in industries:industries.append('반도체')
 if any(c in companies for c in ['삼성SDI','LG에너지솔루션','CATL','Panasonic']) and '2차전지' not in industries:industries.append('2차전지')
 kws={industry:[concept for concept,aliases in concepts.items() if matching(text,aliases)] for industry,concepts in CONFIG['keywords'].items()}
 # Unambiguous domain acronyms can establish context; generic terms cannot.
 for industry,anchors in [('반도체',['HBM','DRAM','NAND','웨이퍼','포토레지스트']),('2차전지',['EV','ESS','LFP','NCM','NMP','전해액'])]:
  if any(k in kws[industry] for k in anchors) and industry not in industries:industries.append(industry)
 if not industries and kws['거시경제']:industries.append('거시경제')
 positive=matching(text,CONFIG['positive']);negative=matching(text,CONFIG['negative']);uncertainty=[]
 if positive or negative:
  # Only inspect the clause containing the matched phrase. Negation/hypotheticals
  # never silently reverse a signal; mixed and ambiguous records stay out of P,N.
  clauses=re.split(r'[.!?…;]|(?:지만)|(?:however)',text,flags=re.I)
  for clause in clauses:
   if matching(clause,positive+negative):uncertainty.extend(matching(clause,CONFIG['uncertain']))
  if any(q in text for q in ['"','“','”','‘','’']):uncertainty.append('quoted_statement')
 if positive and negative:label='mixed'
 elif uncertainty:label='uncertain'
 elif positive:label='positive'
 elif negative:label='negative'
 else:label='neutral'
 pub=item.get('published_at');col=item['collected_at'];available=max(stamp(col),stamp(pub)) if pub else stamp(col)
 backfill=int(not pub or stamp(pub)>stamp(col) or (stamp(col)-stamp(pub)).total_seconds()>48*3600)
 score,detail=importance(text,pub,item['kind'],at=stamp(col))
 return dict(industries=industries,keywords={i:kws[i] for i in industries},label=label,positive=positive,negative=negative,uncertainty=sorted(set(uncertainty)),available_at=available.isoformat(),published_day=day(pub) if pub else None,collected_day=day(available.isoformat()),backfill=backfill,score=score,score_detail=detail,evaluated_at=col)

def event_candidates(item,feature):
 text=item['title'];companies=[k for k,v in CONFIG['companies'].items() if matching(text,v)];countries=[k for k,v in CONFIG['countries'].items() if matching(text,v)];company=companies[0] if len(companies)==1 else None;country=countries[0] if len(countries)==1 else None
 dt=re.search(r'(?<!\d)(20\d{2})[년./-]\s*(\d{1,2})[월./-]\s*(\d{1,2})(?:일)?',text);event_date=None
 if dt:
  try:event_date=datetime(*map(int,dt.groups())).date().isoformat()
  except ValueError:pass
 amount=re.search(r'(?:\d[\d,.]*\s*(?:조|억|만|billion|million)\s*(?:원|달러|弗|USD|dollars)?|[$₩]\s*\d[\d,.]*)',text,re.I)
 for kind,terms in CONFIG['events'].items():
  words=matching(text,terms)
  if not words:continue
  # Narrow identity only: same normalized title/type. Similar company/day alone
  # is insufficient evidence that two investments are the same real-world event.
  eid=digest([kind,title_key(text)])[:32]
  yield dict(id=eid,event_type=kind,event_date=event_date,announcement_date=day(item['published_at']) if item.get('published_at') else None,company=company,country=country,industry=','.join(feature['industries']) or item['category'],title=text,description='제목의 명시적 표현으로 탐지한 미검증 후보. '+('인용·가정·부정문 가능성.' if feature['uncertainty'] else ''),detected_keywords=dump(words),source_url=item['url'],source_id=item['source_id'],confidence_level='explicit_entity_and_rule' if company and not feature['uncertainty'] else 'rule_match_only',verification_status='unverified',amount_text=amount[0] if amount else None,version=VERSION,detected_at=now())

def batched(db,queries,size=60):
 for i in range(0,len(queries),size):db.execute_many(queries[i:i+size])

def process(db,limit=5000):
 """Incremental immutable feature version; source articles are never rewritten."""
 started=now();run_id=uuid.uuid4().hex
 db.execute('INSERT INTO analysis_runs(id,version,started_at,status) VALUES(?,?,?,?)',(run_id,VERSION,started,'running'))
 try:
  rows=db.all('SELECT i.* FROM items i LEFT JOIN feature_completion f ON f.item_id=i.id AND f.version=? WHERE f.item_id IS NULL ORDER BY i.collected_at,i.id LIMIT ?',(VERSION,limit));ops=[]
  for item in rows:
   f=extract_features(item);vals={'item_id':item['id'],'version':VERSION,'input_hash':digest([item['title'],item['tags'],item['published_at'],item['collected_at']]),**f,'processed_at':started}
   for k in ['industries','keywords','positive','negative','uncertainty','score_detail']:vals[k]=dump(vals[k])
   cols=list(vals);ops.append(('INSERT OR IGNORE INTO article_features('+','.join(cols)+') VALUES('+','.join('?' for _ in cols)+')',list(vals.values())))
   if item['kind']=='news':
    for industry,keys in f['keywords'].items():
     for key in keys:ops.append(('INSERT OR IGNORE INTO article_keywords VALUES(?,?,?,?)',(item['id'],VERSION,key,industry)))
    for event in event_candidates(item,f):
     cols=list(event);ops.append(('INSERT OR IGNORE INTO industry_events('+','.join(cols)+') VALUES('+','.join('?' for _ in cols)+')',list(event.values())));ops.append(('INSERT OR IGNORE INTO event_sources VALUES(?,?)',(event['id'],item['id'])))
   ops.append(('INSERT OR IGNORE INTO feature_completion VALUES(?,?,?)',(item['id'],VERSION,started)))
  batched(db,ops)
  db.execute('INSERT OR IGNORE INTO research_dictionary VALUES(?,?,?,?)',(VERSION,'rules',dump(CONFIG),started))
  # Only non-backfilled news enters operational daily aggregates. An absent
  # source-day remains absent; coverage is evaluated independently of articles.
  sums=','.join("sum(f.label='"+k+"')" for k in ['positive','negative','mixed','uncertain','neutral'])
  base=" FROM article_features f JOIN items i ON i.id=f.item_id "
  for kw,joins,industry,group in [("''",' JOIN json_each(f.industries) g','g.value','g.value'),('k.keyword',' JOIN article_keywords k ON k.item_id=f.item_id AND k.version=f.version','k.industry','k.industry,k.keyword')]:
   sql="INSERT OR REPLACE INTO research_daily SELECT f.collected_day,i.source_id,"+industry+','+kw+',f.version,count(*),'+sums+",sum(f.backfill),?"+base+joins+" WHERE f.version=? AND f.backfill=0 AND i.kind='news' AND EXISTS(SELECT 1 FROM feature_completion c WHERE c.item_id=f.item_id AND c.version=f.version) GROUP BY f.collected_day,i.source_id,"+group+",f.version"
   db.execute(sql,(started,VERSION))
  # Legacy observations are conservatively first available when actually collected,
  # never on their historical observation date. Future collector captures revisions.
  db.execute("INSERT OR IGNORE INTO observation_vintages SELECT series_id,date,collected_at,value,'collector_first_seen_not_official_release' FROM observations")
  db.execute('UPDATE analysis_runs SET finished_at=?,status=?,processed=? WHERE id=?',(now(),'success',len(rows),run_id))
  return dict(version=VERSION,processed=len(rows),run_id=run_id,remaining=db.one('SELECT count(*) AS n FROM items i WHERE NOT EXISTS(SELECT 1 FROM feature_completion f WHERE f.item_id=i.id AND f.version=?)',(VERSION,))['n'])
 except Exception as e:
  db.execute('UPDATE analysis_runs SET finished_at=?,status=?,error=? WHERE id=?',(now(),'failed',str(e)[:500],run_id));raise

def date_range(days=90,end=None):
 end=end or (datetime.now(KST).date()-timedelta(days=1))
 return [(end-timedelta(days=i)).isoformat() for i in range(days-1,-1,-1)]

def coverage(db,dates):
 if not dates:return {},[]
 start,end=dates[0],dates[-1];res=db.execute_many([("SELECT id,name,first_success FROM sources WHERE kind='news' AND enabled=1",()),("SELECT source_id,started_at,status FROM runs WHERE started_at>=? AND started_at<?",((stamp(start+'T00:00:00+09:00')-timedelta(days=1)).isoformat(),(stamp(end+'T00:00:00+09:00')+timedelta(days=2)).isoformat()))]);successful=defaultdict(set);attempts=Counter();success=Counter()
 for row in res[1]['rows']:
  d=day(row['started_at'])
  if start<=d<=end:
   attempts[row['source_id']]+=1
   if row['status'] in ['success','not_modified']:successful[row['source_id']].add(d);success[row['source_id']]+=1
 info={s['id']:{'id':s['id'],'name':s['name'],'first_day':day(s['first_success']) if s['first_success'] else None,'days':sorted(successful[s['id']]),'coverage':len(successful[s['id']])/len(dates),'attempts':attempts[s['id']],'successes':success[s['id']]} for s in res[0]['rows']}
 # Fixed cohort must already exist before the requested start, and meet >=70%
 # successful days separately in each seven-day block (not merely overall).
 eligible=[]
 for sid,s in info.items():
  chunks=[dates[i:i+7] for i in range(0,len(dates),7)]
  if s['first_day'] and s['first_day']<=start and all(sum(d in successful[sid] for d in c)/len(c)>=CONFIG['min_coverage'] for c in chunks):eligible.append(sid)
 return info,eligible

def sentiment_summary(rows):
 counts={k:sum(r.get(k,0) for r in rows) for k in ['n','positive','negative','mixed','uncertain','neutral']};p=counts['positive'];n=counts['negative'];counts['value']=100*(p-n)/(p+n) if p+n else None
 counts['classified_share']=(p+n)/counts['n'] if counts['n'] else None;counts['uncertainty_share']=(counts['uncertain']+counts['mixed'])/counts['n'] if counts['n'] else None
 counts['diagnostic']='small_sample' if p+n<CONFIG['min_sentiment_sample'] else 'rule_based_descriptive_only';return counts

def trends(db,industry='반도체',days=90,keyword='',grain='day',end=None):
 if industry not in INDUSTRIES:raise ValueError('Unknown industry')
 if keyword and keyword not in CONFIG['keywords'][industry]:raise ValueError('Unknown keyword')
 if grain not in ['day','week','month']:raise ValueError('Unknown grain')
 dates=date_range(days,end);info,eligible=coverage(db,dates);start,finish=dates[0],dates[-1]
 res=db.execute_many([('SELECT * FROM research_daily WHERE version=? AND industry=? AND day>=? AND day<=? ORDER BY day',(VERSION,industry,start,finish)),('SELECT count(*) AS n,sum(backfill) AS backfill FROM article_features f JOIN items i ON i.id=f.item_id WHERE f.version=? AND i.kind=\'news\' AND f.collected_day>=? AND f.collected_day<=?',(VERSION,start,finish)),('SELECT * FROM analysis_runs ORDER BY started_at DESC LIMIT 1',()),('SELECT i.id,i.title,i.url,i.source_id,f.keywords,f.label,f.collected_day,f.backfill FROM article_features f JOIN items i ON i.id=f.item_id WHERE f.version=? AND i.kind=\'news\' AND f.collected_day>=? AND f.collected_day<=? AND EXISTS(SELECT 1 FROM json_each(f.industries) WHERE value=?) ORDER BY f.available_at DESC LIMIT 250',(VERSION,start,finish,industry))]);daily=res[0]['rows'];by=defaultdict(list)
 for r in daily:by[(r['day'],r['keyword'])].append(r)
 # Display days only after the first observed successful collection; outages
 # and prehistory are null, never invented zeros.
 total_sources=len(info);timeline=[]
 for d in dates:
  active=[s for s in info.values() if d in s['days']];rows=by[(d,keyword)];den=sum(r['n'] for r in by[(d,'')]);m=sentiment_summary(rows)
  valid=bool(active);cohort_valid=bool(eligible) and all(d in info[s]['days'] for s in eligible)
  fixed=[r for r in rows if r['source_id'] in eligible];fm=sentiment_summary(fixed)
  timeline.append(dict(date=d,value=m['n'] if valid else None,share=m['n']/den if valid and den else None,sentiment=m['value'] if valid else None,**{k:m[k] for k in ['positive','negative','mixed','uncertain','neutral']},source_count=len(active),cohort_value=fm['n'] if cohort_valid else None,cohort_positive=fm['positive'] if cohort_valid else None,cohort_negative=fm['negative'] if cohort_valid else None,cohort_sentiment=fm['value'] if cohort_valid else None))
 selected=[r for r in daily if r['keyword']==keyword];summary=sentiment_summary(selected);summary['sources']=len({r['source_id'] for r in selected});summary['observed_days']=sum(p['value'] is not None for p in timeline)
 def window_count(key,n,offset=0):return sum(r['n'] for r in daily if r['keyword']==key and dates[-1-min(offset,len(dates)-1)]>=r['day']>=(stamp(finish+'T00:00:00+09:00')-timedelta(days=offset+n-1)).date().isoformat())
 keys=[]
 for key in CONFIG['keywords'][industry]:
  vals=[sum(r['n'] for r in by[(d,key)]) if any(d in s['days'] for s in info.values()) else None for d in dates];recent=window_count(key,7);prior=window_count(key,7,7);monthly=window_count(key,30);oldmonth=window_count(key,30,30);n7=[v for v in vals[-7:] if v is not None];n30=[v for v in vals[-30:] if v is not None];base=[sum(r['n'] for r in by[(d,key)] if r['source_id'] in eligible) for d in dates[-35:-7]]
  fixed7=sum(r['n'] for r in daily if r['keyword']==key and r['source_id'] in eligible and r['day']>=dates[-min(7,len(dates))]);baseline=sum(base)/4 if len(base)==28 and eligible else None;sd=statistics.pstdev(base)*math.sqrt(7) if baseline is not None else None;z=(fixed7-baseline)/sd if sd else None;growth=fixed7/baseline-1 if baseline else None
  comparable=bool(finish<datetime.now(KST).date().isoformat() and eligible and len(dates)>=35 and all(all(d in info[s]['days'] for s in eligible) for d in dates[-35:]))
  status='insufficient_history' if not comparable else 'new_topic' if baseline==0 and fixed7>=CONFIG['signal_min_count'] else 'surge' if fixed7>=CONFIG['signal_min_count'] and z is not None and z>=CONFIG['signal_z'] and growth is not None and growth>=CONFIG['signal_growth'] else 'normal'
  denominator=sum(r['n'] for r in daily if r['keyword']=='' and r['day']>=dates[-min(7,len(dates))]);keys.append(dict(keyword=key,day=vals[-1],week=recent,month=monthly,share=recent/denominator if denominator else None,week_growth=recent/prior-1 if prior and comparable else None,month_growth=monthly/oldmonth-1 if oldmonth and comparable and len(dates)>=60 else None,ma7=statistics.mean(n7) if len(n7)==7 else None,ma30=statistics.mean(n30) if len(n30)==30 else None,z=z if comparable else None,status=status,baseline=baseline if comparable else None,cohort_recent=fixed7 if comparable else None,heat=vals[-28:]))
 co=Counter()
 for row in res[3]['rows']:
  if row['backfill']:continue
  words=json.loads(row['keywords']).get(industry,[])
  for i,a in enumerate(words):
   for b in words[i+1:]:co[tuple(sorted([a,b]))]+=1
 # Co-occurrence is deliberately capped and labelled; trend totals use full SQL aggregates.
 buckets=defaultdict(list)
 for p in timeline:
  dt=datetime.fromisoformat(p['date']);key=p['date'] if grain=='day' else (dt-timedelta(days=dt.weekday())).date().isoformat() if grain=='week' else p['date'][:7]+'-01';buckets[key].append(p)
 chart=[]
 for d,points in buckets.items():
  usable=[p for p in points if p['value'] is not None];P=sum(p['positive'] for p in usable);N=sum(p['negative'] for p in usable)
  chart.append(dict(date=d,value=sum(p['value'] for p in usable) if usable else None,sentiment=100*(P-N)/(P+N) if P+N else None,observed_days=len(usable),calendar_days=len(points)))
 return dict(version=VERSION,industry=industry,keyword=keyword,grain=grain,start=start,end=finish,summary=summary,timeline=timeline,chart=chart,keywords=keys,cooccurrence=[dict(a=a,b=b,count=n) for (a,b),n in co.most_common(20)],cooccurrence_scope='최근 최대 250개 비백필 기사 부분집합',sources=list(info.values()),eligible_sources=eligible,quality=res[1]['rows'][0],last_run=res[2]['rows'][0] if res[2]['rows'] else None,evidence=res[3]['rows'][:30],warning='KST 실제 이용가능일(max(발행시각,수집시각)) 기준. 발행일 미상·48시간 초과 백필·미래 발행 기사는 지표에서 제외. 미수집일은 결측. 빈도는 이 시스템의 RSS 표본이며 전체 산업 뉴스량이 아닙니다. 비교·급증 판정은 고정 정보원과 연속 35일 성공 이력이 있을 때만 제공합니다.',computed_at=now())
