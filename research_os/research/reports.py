"""Immutable report snapshots from measured records; templates only, never AI."""
import html,json,uuid,calendar
from datetime import datetime,timedelta
from .engine import VERSION,CONFIG,KST,now,dump,digest,sentiment_summary

def report_period(kind,at=None):
 today=(at or datetime.now(KST)).astimezone(KST).date()
 if kind=='daily':start=end=today-timedelta(days=1)
 elif kind=='weekly':end=today-timedelta(days=today.weekday()+1);start=end-timedelta(days=6)
 elif kind=='monthly':end=today.replace(day=1)-timedelta(days=1);start=end.replace(day=1)
 else:raise ValueError('Unknown report period')
 return start.isoformat(),end.isoformat()

def generate(db,kind='daily',start=None,end=None):
 start,end=(start,end) if start and end else report_period(kind)
 res=db.execute_many([('SELECT * FROM research_daily WHERE version=? AND day>=? AND day<=? ORDER BY industry,day',(VERSION,start,end)),('SELECT i.id,i.title,i.url,i.kind,i.source_id,s.name AS source_name,i.published_at,i.collected_at,i.score,i.score_detail,i.rule_version FROM items i JOIN sources s ON s.id=i.source_id WHERE date(i.collected_at,\'+9 hours\')>=? AND date(i.collected_at,\'+9 hours\')<=? ORDER BY i.score DESC LIMIT 80',(start,end)),('SELECT * FROM industry_events WHERE announcement_date>=? AND announcement_date<=? ORDER BY detected_at DESC LIMIT 30',(start,end)),("SELECT source_id,count(DISTINCT CASE WHEN status IN ('success','not_modified') THEN date(started_at,'+9 hours') END) AS days,sum(status IN ('success','not_modified')) AS successes,count(*) AS attempts FROM runs WHERE date(started_at,'+9 hours')>=? AND date(started_at,'+9 hours')<=? GROUP BY source_id",(start,end)),('SELECT s.id,s.name,s.unit,s.url,o.date,o.value,o.collected_at FROM observations o JOIN series s ON s.id=o.series_id WHERE o.date>=? AND o.date<=? ORDER BY s.id,o.date',(start,end))]);daily,articles,events,sources,observations=[r['rows'] for r in res]
 industries={}
 for industry in CONFIG['keywords']:
  rows=[r for r in daily if r['industry']==industry and r['keyword']==''];counts=sentiment_summary(rows);keys={}
  for r in daily:
   if r['industry']==industry and r['keyword']:keys[r['keyword']]=keys.get(r['keyword'],0)+r['n']
  industries[industry]={**counts,'keywords':sorted(keys.items(),key=lambda x:-x[1])[:8]}
 econ={}
 for r in observations:
  if r['id'] not in econ:econ[r['id']]={'name':r['name'],'unit':r['unit'],'url':r['url'],'first':r,'last':r}
  else:econ[r['id']]['last']=r
 days=(datetime.fromisoformat(end)-datetime.fromisoformat(start)).days+1
 payload=dict(status='partial' if end>=datetime.now(KST).date().isoformat() else 'insufficient_data' if not sources else 'snapshot',period=kind,start=start,end=end,version=VERSION,industries=industries,articles=articles,events=events,sources=sources,indicators=list(econ.values()),coverage=dict(calendar_days=days,source_count=len(sources),complete_sources=sum(s['days']==days for s in sources)),method='기사 빈도: 48시간 내 수집된 뉴스의 KST 이용가능일. 심리지수=100×(확장-위축)/(확장+위축), 혼합·불확실·중립 제외, 분모 0은 결측. 뉴스 수와 보고서 목록은 수집일 기준. 경제지표는 관측일 기준 최신 수집 빈티지로 개정 가능.',warning='고정 정보원 비교 이력이 충분하지 않으면 증가·감소의 유의성을 주장하지 않습니다. 보고서 수치는 제공한 RSS 표본의 관측값입니다. 표본외 예측력·JANUS 전략의 유효성은 별도 검증 전입니다.')
 h=digest(payload);rid=digest([kind,start,end,VERSION,h])[:32]
 db.execute('INSERT OR IGNORE INTO generated_reports VALUES(?,?,?,?,?,?,?,?)',(rid,kind,start,end,VERSION,h,dump(payload),now()))
 return db.one('SELECT * FROM generated_reports WHERE id=?',(rid,))

def render_report(row):
 p=json.loads(row['payload']);e=lambda x:html.escape(str(x if x is not None else '결측'));body=[]
 for industry,v in p['industries'].items():
  body.append(f'<section><h2>{e(industry)}</h2><p>분석 뉴스 {v["n"]}건 · 확장 {v["positive"]} · 위축 {v["negative"]} · 혼합 {v["mixed"]} · 불확실 {v["uncertain"]} · 중립 {v["neutral"]}</p><p>규칙 기반 확장·위축 지수: <strong>{e(round(v["value"],2) if v["value"] is not None else None)}</strong> / −100~100</p><p>키워드 빈도: '+', '.join(e(k)+' '+str(n)+'건' for k,n in v['keywords'])+'</p></section>')
 for v in p['indicators']:
  body.append(f'<p><a href="{e(v["url"])}">{e(v["name"])}</a>: {e(v["first"]["value"])} → {e(v["last"]["value"])} {e(v["unit"])} · 관측 {e(v["first"]["date"])}~{e(v["last"]["date"])} · 최종 수집 {e(v["last"]["collected_at"])}</p>')
 body.append('<h2>주요 수집 자료 · 원문 근거</h2>')
 for i,a in enumerate(p['articles'],1):body.append(f'<article><a href="{e(a["url"])}" rel="noreferrer">[{i}] {e(a["title"])}</a><p>{e(a["source_name"])} · 발행 {e(a["published_at"])} · 수집 {e(a["collected_at"])} · 수집 시점 우선순위 {e(a["score"])} / 100</p></article>')
 body.append('<h2>산업 이벤트 · 검증 전 후보</h2>')
 for v in p['events']:body.append(f'<p><a href="{e(v["source_url"])}">{e(v["title"])}</a> · {e(v["event_type"])} · 발생일 {e(v["event_date"])} · {e(v["verification_status"])}</p>')
 c=p['coverage'];return f'''<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>TTS {e(p['period'])} {e(p['end'])}</title><link rel="stylesheet" href="/static/report.css"><script src="/static/report.js" defer></script></head><body><header><img src="/static/tts-mark.svg" alt="TTS"><span>RESEARCH / {e(p['period']).upper()}</span><button id="print-report">PDF 저장 / 인쇄</button></header><h1>{e(p['period']).title()} Intelligence</h1><p>{e(p['start'])} — {e(p['end'])} · KST</p><aside>자료 상태 {e(p['status'])} · 기준기간 {c['calendar_days']}일 · 실행 정보원 {c['source_count']}개 · 매일 수집된 정보원 {c['complete_sources']}개. {e(p['warning'])}</aside>{''.join(body)}<footer><h2>계산·출처 메타데이터</h2><p>{e(p['method'])}</p><p>규칙 버전 {e(p['version'])} · 스냅샷 생성 {e(row['generated_at'])}</p><p>데이터 SHA-256 {e(row['data_hash'])}</p><a href="/api/research/report/{e(row['id'])}/json">정형 데이터 JSON</a></footer></body></html>'''
