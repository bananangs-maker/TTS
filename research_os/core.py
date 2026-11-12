import re,json,html,hashlib,unicodedata,math
from pathlib import Path
from urllib.parse import urlparse,urlunparse,parse_qsl,urlencode
from datetime import datetime,timezone
from difflib import SequenceMatcher
ROOT=Path(__file__).resolve().parent.parent
RULES=json.loads((ROOT/'config/rules.json').read_text())
def now():return datetime.now(timezone.utc).isoformat(timespec='seconds')
def clean(value):return re.sub(r'\s+',' ',html.unescape(re.sub(r'<[^>]*>',' ',value or ''))).strip()
def title_key(title):return re.sub(r'[^\w]','',unicodedata.normalize('NFKC',title).lower()).replace('_','')
def canonical_url(url):
 p=urlparse(html.unescape(url.strip()))
 if p.scheme not in ('http','https') or not p.hostname or p.username or p.password:raise ValueError('Unsafe article URL')
 # Reject private IPs as stored links too; never fetch article bodies.
 import ipaddress
 try:
  if not ipaddress.ip_address(p.hostname).is_global:raise ValueError('Private URL')
 except ValueError as e:
  if str(e)=='Private URL':raise
 q=sorted((k,v) for k,v in parse_qsl(p.query,keep_blank_values=True) if not k.lower().startswith(('utm_','fbclid','gclid','mc_')))
 return urlunparse((p.scheme,p.netloc.lower(),p.path or '/',p.params,urlencode(q),''))
def word_match(text,term):
 term=unicodedata.normalize('NFKC',term).casefold();text=unicodedata.normalize('NFKC',text).casefold();pattern=re.escape(term)
 if term and term[0].isascii() and term[0].isalnum():pattern=r'(?<![a-z0-9])'+pattern
 if term and term[-1].isascii() and term[-1].isalnum():pattern+=r'(?![a-z0-9])'
 return bool(re.search(pattern,text))

def classify(title,fallback='기타'):
 t=title.lower();matches={k:[w for w in words if word_match(t,w)] for k,words in RULES['categories'].items()};tags=[k for k,v in matches.items() if v]
 category=max(matches,key=lambda k:len(matches[k])) if tags else fallback
 keywords=sorted(set(w for words in matches.values() for w in words))
 return category,tags or [fallback],keywords

def importance(title,published_at,source_kind,novel=True,at=None):
 at=at or datetime.now(timezone.utc);_,tags,words=classify(title)
 w=RULES['weights'];age=None
 if published_at:
  try:age=max(0,(at-datetime.fromisoformat(published_at)).total_seconds()/86400)
  except ValueError:pass
 factors={'relevance':min(1,len([t for t in tags if t!='기타'])/2),'keywords':min(1,len(words)/4),'event':float(any(word_match(title,x) for x in RULES['event_words'])),'source':1.0 if source_kind=='report' else .6,'freshness':math.exp(-age/3) if age is not None else 0,'novelty':float(novel)}
 detail={k:round(w[k]*v,3) for k,v in factors.items()};return round(min(100,sum(detail.values())),2),detail

def similar(a,b):
 ka,kb=title_key(a),title_key(b)
 if min(len(ka),len(kb))<15:return ka==kb
 if min(len(ka),len(kb))/max(len(ka),len(kb))<.85:return False
 # Different numeric claims or key entities must not collapse as wire duplicates.
 if re.findall(r'\d+(?:\.\d+)?',a)!=re.findall(r'\d+(?:\.\d+)?',b):return False
 return SequenceMatcher(None,ka,kb,autojunk=False).ratio()>=RULES['duplicate_similarity']

def related_key(title):
 t=re.sub(r'\d{2,4}년|\d{1,2}월|\d{1,2}분기|\d{4}[-.]\d{1,2}','',title)
 return title_key(t)[:120]

def robots_allowed(body,url,agent='ResearchOS'):
 """RFC9309 longest-path matching including Allow specificity and wildcard rules.
 urllib.robotparser is retained for crawl-delay only (it uses first-match paths).
 """
 from urllib.parse import urlparse,unquote
 groups=[];agents=[];rules=[];seen_rule=False
 for line in body.splitlines():
  cleanline=line.split('#',1)[0].strip()
  if ':' not in cleanline:continue
  key,value=map(str.strip,cleanline.split(':',1));key=key.lower()
  if key=='user-agent':
   if seen_rule:
    groups.append((agents,rules));agents=[];rules=[];seen_rule=False
   agents.append(value.lower())
  elif key in ('allow','disallow'):
   seen_rule=True
   if value:rules.append((key=='allow',value))
 if agents:groups.append((agents,rules))
 exact=[(max(len(a) for a in names if a!='*' and a in agent.lower()),rules) for names,rules in groups if any(a!='*' and a in agent.lower() for a in names)]
 if exact:
  best=max(x[0] for x in exact);selected=[rules for length,rules in exact if length==best]
 else:selected=[rules for names,rules in groups if '*' in names]
 p=urlparse(url);path=p.path+('?' +p.query if p.query else '');matches=[]
 for rules in selected:
  for allow,rule in rules:
   pattern='^'+re.escape(rule).replace(r'\*','.*').replace(r'\$','$')
   if re.search(pattern,path):matches.append((len(rule.replace('*','').replace('$','')),allow))
 return max(matches,default=(0,True))[1]
