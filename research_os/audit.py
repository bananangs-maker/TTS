"""Check official candidate pages once, without implying an automated collector works."""
import json,requests,concurrent.futures,hashlib
from pathlib import Path
from urllib.parse import urlparse
from .catalog import PENDING,initialize
from .core import now,robots_allowed
from .db import DB

def check(entry):
 name,note,url=entry;p=urlparse(url);headers={'User-Agent':'ResearchOS/1.0 (personal source availability check)'};result={'name':name,'url':url,'checked_at':now(),'collector_verified':False}
 try:
  r=requests.get(p.scheme+'://'+p.netloc+'/robots.txt',headers=headers,timeout=18,allow_redirects=False)
  if r.status_code==200:
   if '<html' in r.text.lower():raise ValueError('robots returned HTML')
   if not robots_allowed(r.text,url):result.update(status='restricted',error='robots.txt disallows official listing');return result
  elif r.status_code!=404:result.update(status='robots_unverified',error='robots HTTP '+str(r.status_code));return result
  r=requests.get(url,headers=headers,timeout=18,allow_redirects=False,stream=True)
  result.update(status='page_http_'+str(r.status_code),content_type=r.headers.get('Content-Type'),error=None if r.ok else 'HTTP '+str(r.status_code));r.close()
 except Exception as e:result.update(status='unreachable',error=type(e).__name__+': '+str(e)[:150])
 return result
if __name__=='__main__':
 db=DB();db.migrate();initialize(db)
 with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:results=list(pool.map(check,PENDING))
 for i,r in enumerate(results):db.execute('UPDATE source_candidates SET status=?,checked_at=?,error=? WHERE id=?',(r['status'],r['checked_at'],r.get('error'),'candidate-'+hashlib.sha256(r['name'].encode()).hexdigest()[:16]))
 Path('docs').mkdir(exist_ok=True);Path('docs/source-audit.json').write_text(json.dumps(results,ensure_ascii=False,indent=2));print(json.dumps(results,ensure_ascii=False,indent=2))
