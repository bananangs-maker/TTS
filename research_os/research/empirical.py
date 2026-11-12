"""Monthly research with first-seen vintages, purged chronological OOS folds.
No price download, strategy discovery or automatic claim of predictive success.
"""
import calendar,math,json,statistics
from collections import defaultdict
from datetime import datetime,timedelta,timezone
from .engine import CONFIG,VERSION,KST,stamp,digest,now,coverage,date_range

def month_shift(month,n):
 year,m=map(int,month[:7].split('-'));idx=year*12+m-1+n;return f'{idx//12:04d}-{idx%12+1:02d}'
def month_end(month):
 y,m=map(int,month[:7].split('-'));return datetime(y,m,calendar.monthrange(y,m)[1],23,59,59,tzinfo=KST)
def finite(v):
 if isinstance(v,dict):return {k:finite(x) for k,x in v.items()}
 if isinstance(v,(list,tuple)):return [finite(x) for x in v]
 if isinstance(v,float) and not math.isfinite(v):return None
 if hasattr(v,'item'):return finite(v.item())
 return v

def monthly_news(db,industry,keyword='',max_months=120):
 end=(datetime.now(KST).date().replace(day=1)-timedelta(days=1));start=month_shift(end.isoformat(),-max_months+1)+'-01'
 rows=db.all('SELECT * FROM research_daily WHERE version=? AND industry=? AND keyword=? AND day>=? AND day<=? ORDER BY day',(VERSION,industry,keyword,start,end.isoformat()))
 if not rows:return []
 start=max(start,min(r['day'] for r in rows)[:7]+'-01');dates=date_range((end-datetime.fromisoformat(start).date()).days+1,end);sources,_=coverage(db,dates);by=defaultdict(list)
 for row in rows:by[row['day'][:7]].append(row)
 output=[]
 for month,records in sorted(by.items()):
  days=calendar.monthrange(int(month[:4]),int(month[5:]))[1];first=month+'-01';last=month_end(month).date().isoformat();ds=[(datetime.fromisoformat(first)+timedelta(days=i)).date().isoformat() for i in range(days)]
  # Freeze a cohort across the complete available research history, not one
  # newly selected collection of publishers each month.
  first_operation=min((s['first_day'] for s in sources.values() if s['first_day']),default=first);history_start=(first_operation[:7] if first_operation.endswith('-01') else month_shift(first_operation,1))+'-01';eligible=[s['id'] for s in sources.values() if s['first_day'] and s['first_day']<=history_start and all(sum(d in s['days'] for d in ds[i:i+7])/len(ds[i:i+7])>=CONFIG['min_coverage'] for i in range(0,days,7))]
  # Gaps are not zero-filled. A complete monthly feature needs every source-day.
  complete=bool(eligible) and first>=history_start and all(all(d in sources[s]['days'] for d in ds) for s in eligible)
  selected=[r for r in records if r['source_id'] in eligible];p=sum(r['positive'] for r in selected);n=sum(r['negative'] for r in selected)
  output.append(dict(month=month,news_count=sum(r['n'] for r in selected) if complete else None,sentiment=100*(p-n)/(p+n) if complete and p+n else None,available_at=month_end(month).astimezone(timezone.utc).isoformat(),complete=complete,source_ids=eligible))
 # Enforce the same set of publishers in all usable months. Source cohort
 # changes cause a new research cohort rather than a spurious volume change.
 complete=[r for r in output if r['complete']]
 if complete:
  fixed=set.intersection(*(set(r['source_ids']) for r in complete))
  if not fixed:
   for r in output:r.update(complete=False,news_count=None,sentiment=None)
  else:
   for r in output:
    if not r['complete']:continue
    selected=[x for x in by[r['month']] if x['source_id'] in fixed];p=sum(x['positive'] for x in selected);n=sum(x['negative'] for x in selected);r.update(news_count=sum(x['n'] for x in selected),sentiment=100*(p-n)/(p+n) if p+n else None,source_ids=sorted(fixed))
 return output

def prepare_alignment(db,industry,series_id,keyword=''):
 series=db.one('SELECT * FROM series WHERE id=?',(series_id,))
 if not series:raise ValueError('Unknown economic series')
 news=monthly_news(db,industry,keyword) if series['frequency']!='quarterly' else []
 vintages=db.all('SELECT * FROM observation_vintages WHERE series_id=? ORDER BY observation_date,available_at',(series_id,)) if any(r['complete'] for r in news) else []
 return series,news,vintages

def align(db,industry,series_id,keyword='',metric='news_count',horizon=1,prepared=None):
 if metric not in ['news_count','sentiment']:raise ValueError('Unknown news metric')
 series,news,vintages=prepared if prepared is not None else prepare_alignment(db,industry,series_id,keyword)
 if series['frequency']=='quarterly':return [],{'reason':'분기 지표를 월별 자료로 복제하지 않습니다. 월·일 지표를 선택하세요.','series':series}
 latest={}
 for v in vintages:latest[v['observation_date']]=v
 target={}
 for v in sorted(latest.values(),key=lambda v:v['observation_date']):target[v['observation_date'][:7]]=v
 aligned=[]
 for row in news:
  if not row['complete'] or row[metric] is None:continue
  cutoff=month_end(row['month']);available={}
  for v in vintages:
   if stamp(v['available_at'])<=cutoff and v['observation_date']<=cutoff.date().isoformat():available[v['observation_date']]=v
  known=list(sorted(available.values(),key=lambda x:x['observation_date']));known_months={}
  for v in known:known_months[v['observation_date'][:7]]=v
  last=list(known_months.values())[-2:];future=target.get(month_shift(row['month'],horizon))
  if len(last)<2 or not future:continue
  # Current revised data is a labelled ex-post evaluation target, never a
  # historical predictor. Label maturity purges every training split.
  base,prev=last[-1],last[-2];aligned.append(dict(month=row['month'],origin_at=cutoff.astimezone(timezone.utc).isoformat(),feature=row[metric],baseline_level=base['value'],baseline_change=base['value']-prev['value'],target=future['value']-base['value'],target_level=future['value'],target_date=future['observation_date'],label_available_at=future['available_at'],feature_available_at=row['available_at'],baseline_available_at=base['available_at'],baseline_observation_date=base['observation_date'],source_ids=row['source_ids']))
 return aligned,dict(series=series,months_collected=len(news),complete_months=sum(r['complete'] for r in news),vintage_count=len(vintages),availability='collector_first_seen_not_official_release',target_vintage='latest_collected_ex_post',reason='완료된 KST 월·고정 정보원·모든 일별 수집 성공·시점별 실제 이용가능 경제지표 2개월 이상을 요구합니다. 공식 발표일/과거 빈티지를 추정하지 않습니다.')

def regression(x,y,names):
 import numpy as np
 import statsmodels.api as sm
 from statsmodels.stats.stattools import durbin_watson
 from statsmodels.stats.diagnostic import acorr_ljungbox
 from statsmodels.tsa.stattools import adfuller
 X=np.asarray(x,dtype=float);Y=np.asarray(y,dtype=float);sd=X.std(axis=0)
 if np.any(sd<1e-12):return {'status':'constant_predictor','reason':'상수 설명변수가 있어 회귀를 계산하지 않았습니다.'}
 X=(X-X.mean(axis=0))/sd;design=sm.add_constant(X,has_constant='add')
 if np.linalg.matrix_rank(design)<design.shape[1]:return {'status':'rank_deficient','reason':'설명변수의 완전 다중공선성'}
 fit=sm.OLS(Y,design).fit(cov_type='HAC',cov_kwds={'maxlags':3},use_t=True)
 def adf(a):
  try:return {'p':float(adfuller(a,autolag='AIC')[1]),'null':'unit_root'}
  except ValueError:return {'p':None,'reason':'상수 또는 표본 부족'}
 lb=acorr_ljungbox(fit.resid,lags=[min(6,max(1,len(Y)//5))],return_df=True)
 return finite(dict(status='ok',n=len(Y),r_squared=float(fit.rsquared),coefficients=[dict(name=name,value=float(v),p=float(p),ci=list(map(float,ci))) for name,v,p,ci in zip(['intercept']+names,fit.params,fit.pvalues,fit.conf_int())],covariance='Newey-West HAC maxlags=3; predictors standardized in this descriptive sample',durbin_watson=float(durbin_watson(fit.resid)),ljung_box_p=float(lb['lb_pvalue'].iloc[0]),adf_target=adf(Y),adf_news=adf(X[:,-1]),warning='상관·회귀는 인과관계나 유효한 선행지표의 입증이 아닙니다. ADF 비기각은 단위근 부재를 보장하지 않습니다.'))

def linkage(db,industry,series_id,keyword='',metric='news_count'):
 prepared=prepare_alignment(db,industry,series_id,keyword);results=[];paired=[];meta=None
 for lag in [0,1,3,6]:
  rows,meta=align(db,industry,series_id,keyword,metric,lag,prepared)
  minimum=CONFIG['quant_min_pairs'];entry=dict(lag_months=lag,n=len(rows),required=minimum,status='insufficient_data',correlation=None,p=None,adjusted_p=None)
  if len(rows)>=minimum:
   x=np.array([r['feature'] for r in rows]);y=np.array([r['target'] for r in rows])
   if x.std()>1e-12 and y.std()>1e-12:
    corr=pearsonr(x,y);entry.update(status='exploratory',correlation=float(corr.statistic),p=float(corr.pvalue),regression=regression([[r['baseline_change'],r['feature']] for r in rows],y.tolist(),['baseline_change','news']))
   else:entry.update(status='constant_series')
  results.append(entry)
  if lag==1:paired=rows
 valid=[r for r in results if r['p'] is not None]
 if valid:
  from statsmodels.stats.multitest import multipletests
  adjusted=multipletests([r['p'] for r in valid],method='holm')[1]
  for r,p in zip(valid,adjusted):r['adjusted_p']=float(p)
 return finite(dict(version=VERSION,lags=results,aligned=paired,diagnostics=meta,data_hash=digest(paired),warning='동시/1/3/6개월의 4개 탐색 가설에 Holm 보정. 실행 간 반복 탐색까지 보정한 값은 아닙니다. p값은 시계열 의존성에 취약하며 회귀는 HAC 오차를 함께 제공합니다. 현재 수집값의 최초 이용가능 시점을 적용해 과거 발표일을 만들어내지 않습니다.'))

def oos(rows,window='expanding',train_size=36,min_oos=12):
 """Train-only scaling and label-maturity purge. Never shuffle or tune on OOS."""
 import numpy as np
 predictions=[];minimum=max(CONFIG['quant_train'],train_size)
 for i,test in enumerate(rows):
  training=[r for r in rows[:i] if stamp(r['label_available_at'])<=stamp(test['origin_at'])]
  if window=='rolling':training=training[-minimum:]
  if len(training)<minimum:continue
  if any(stamp(r['feature_available_at'])>stamp(r['origin_at']) or stamp(r['baseline_available_at'])>stamp(r['origin_at']) for r in training+[test]):raise ValueError('Future information in predictor')
  forecasts=[]
  for cols in [('baseline_level','baseline_change'),('baseline_level','baseline_change','feature')]:
   X=np.array([[r[c] for c in cols] for r in training]);Y=np.array([r['target'] for r in training]);mean=X.mean(axis=0);sd=X.std(axis=0);sd[sd<1e-12]=1
   X=np.column_stack((np.ones(len(X)),(X-mean)/sd));beta=np.linalg.lstsq(X,Y,rcond=None)[0];point=np.r_[1,(np.array([test[c] for c in cols])-mean)/sd];forecasts.append(float(point@beta))
  predictions.append(dict(month=test['month'],origin_at=test['origin_at'],train_n=len(training),latest_training_label=max(r['label_available_at'] for r in training),actual=test['target'],baseline=forecasts[0],enhanced=forecasts[1]))
 if len(predictions)<min_oos:return dict(status='insufficient_data',eligible_rows=len(rows),out_of_sample=len(predictions),required_train=minimum,required_oos=min_oos,additional_eligible_months=max(0,minimum+min_oos-len(rows)),predictions=[],reason='최소 36개 성숙한 훈련 월과 12개 표본외 예측 월이 필요합니다. 발표 지연 때문에 추가 기간이 늘어날 수 있습니다.')
 y=np.array([p['actual'] for p in predictions]);metrics={}
 for model in ['baseline','enhanced']:
  pred=np.array([p[model] for p in predictions]);err=y-pred;metrics[model]=dict(mae=float(np.mean(abs(err))),rmse=float(np.sqrt(np.mean(err**2))),direction_accuracy=float(np.mean(np.sign(y)==np.sign(pred))))
 bse=sum((p['actual']-p['baseline'])**2 for p in predictions);ese=sum((p['actual']-p['enhanced'])**2 for p in predictions);br=metrics['baseline']['rmse'];return finite(dict(status='evaluated_not_validated',out_of_sample=len(predictions),metrics=metrics,oos_r2_vs_baseline=1-ese/bse if bse else None,rmse_improvement=1-metrics['enhanced']['rmse']/br if br else None,predictions=predictions,window=window,warning='비용·매매 규칙 없는 거시 예측 비교입니다. 수익률 백테스트와 다릅니다. 단일 실험 성과는 선행성 입증이 아닙니다.'))

def backtest(db,industry,series_id,keyword='',metric='news_count',horizon=1,window='expanding',train_size=36):
 if horizon not in [1,3,6] or window not in ['rolling','expanding']:raise ValueError('Invalid research specification')
 rows,diagnostics=align(db,industry,series_id,keyword,metric,horizon);result=oos(rows,window,train_size,CONFIG['quant_oos']);return dict(version=VERSION,config=dict(industry=industry,series_id=series_id,keyword=keyword,metric=metric,horizon=horizon,window=window,train_size=train_size),diagnostics=diagnostics,data_hash=digest(rows),**result)

def trading_metrics(prices,signals,cost_bps=10,at=None):
 """JANUS plumbing: previous-close signal trades the *next close*. Adjusted
 close input; no same-day execution assumption, no automatic optimisation.
 prices: date/value/available_at; signals: date/value/available_at.
 """
 import numpy as np
 if not 0<=cost_bps<=100:raise ValueError('Cost outside allowed range')
 prices=sorted(prices,key=lambda r:r['day']);signals=sorted(signals,key=lambda r:r['available_at']);
 for i,p in enumerate(prices):
  lag=(stamp(p['available_at']).astimezone(KST).date()-datetime.fromisoformat(p['day']).date()).days
  if lag<0 or lag>1 or i and stamp(p['available_at'])<=stamp(prices[i-1]['available_at']):raise ValueError('조정종가의 실제 이용가능 시각이 관측일 당일/다음날이며 엄격한 시간순이어야 과거 백테스트가 가능합니다.')
 equity=1.;position=0.;returns=[];curve=[];turnover=0.;trades=0
 for i in range(2,len(prices)):
  decision=stamp(prices[i-2]['available_at']);known=[s for s in signals if stamp(s['available_at'])<=decision]
  desired=float(known[-1]['value']>0) if known else 0.;cost=abs(desired-position)*cost_bps/10000;trades+=int(desired!=position);turnover+=abs(desired-position);position=desired
  r=position*(prices[i]['value']/prices[i-1]['value']-1)-cost;equity*=1+r;returns.append(r);curve.append(dict(date=prices[i]['day'],value=equity,position=position,net_return=r))
 if len(returns)<60:return dict(status='insufficient_data',observations=len(returns),required=60)
 # Mark the final close as liquidated, charging terminal turnover once.
 if position:
  fee=cost_bps/10000;equity*=1-fee;returns[-1]=(1+returns[-1])*(1-fee)-1;curve[-1].update(value=equity,net_return=returns[-1],position=0);turnover+=position;trades+=1
 a=np.array(returns);wealth=np.r_[1,np.cumprod(1+a)];dd=wealth/np.maximum.accumulate(wealth)-1;sd=a.std(ddof=1)
 return finite(dict(status='exploratory_unverified_imports',bars=len(a),trade_sides=trades,turnover=turnover,cost_bps=cost_bps,total_return=equity-1,annual_volatility=float(sd*math.sqrt(252)),sharpe=float(a.mean()/sd*math.sqrt(252)) if sd else None,max_drawdown=float(dd.min()),curve=curve,warning='롱/현금, 조정종가, 신호 확인 후 다음 종가 체결. 비용은 편도 bp, 마지막 청산 포함. 무위험금리 0, 연 252일 가정. 수입 데이터의 시점은 사용자 선언으로 미검증입니다.'))
