"""Conservative newsroom focus; metadata outside scope is retained, never deleted."""
import re

TERMS = ('반도체','메모리','HBM','DRAM','NAND','파운드리','웨이퍼','TSMC','하이닉스','semiconductor','foundry','배터리','이차전지','2차전지','전기차','전해액','양극재','음극재','리튬','battery','batteries','ESS','LFP','NCM','NMP','금리','환율','물가','성장률','GDP','CPI','PPI','수출','수입','교역','국채','통화정책','재정정책','산업생산','inflation','interest rate','exchange rate','treasury','tariff','관세','수출통제','보조금','산업정책','공급망','원유','유가','에너지','석유','Brent','WTI','oil','energy','CAPEX','설비투자','생산시설','공장','증설','가동률')

def focus_sql(column='i.title'):
 # Identifier is supplied by application code only; all terms are SQL values.
 if column!='i.title':raise ValueError('Unexpected title column')
 predicates=[];values=[]
 for term in TERMS:
  if term.isascii() and term.isalnum():
   predicates.append("(' '||lower(i.title)||' ') GLOB ?")
   values.append('*[^a-z0-9]'+term.lower()+'[^a-z0-9]*')
  else:predicates.append('instr(lower(i.title),lower(?))>0');values.append(term)
 return '('+' OR '.join(predicates)+') AND i.title NOT LIKE ? AND i.title NOT LIKE ? AND i.title NOT LIKE ?',values+['[포토]%','[인사]%','[부고]%']

def candidate_availability(row):
 note=row.get('note','')
 requirement='authentication_required' if '인증' in note or 'API 키' in note else 'access_restricted' if 'robots' in note else 'rss_unverified' if '302' in note else 'official_api_available' if '무인증 Indicators API 확인' in note else 'api_unverified'
 return dict(row,collection_status='not_implemented',requirement=requirement)
