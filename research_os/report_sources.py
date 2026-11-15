"""Bounded official report-list metadata parsers. No PDF or article body fetches."""
import re
from datetime import datetime,timezone,timedelta
from urllib.parse import urljoin
from xml.sax.saxutils import escape
from .core import clean,canonical_url

KITA_PATHS={'TRADE_FOCUS':'tradeFocus/tradeFocusDetail.do','TRADE_BRIEF':'tradeBrief/tradeBriefDetail.do','TRADE_REPORT':'commerceReport/commerceReportDetail.do','ISSUE_BRIEF':'issueBrief/issueBriefDetail.do'}

def parse_report_list(body,source):
 text=body.decode('utf-8-sig');rows=[];seen=set()
 for block in re.findall(r'<li\b[^>]*>(.*?)</li>',text,re.S|re.I):
  if source['method']=='kiet_list':
   link=re.search(r'<a\s+[^>]*href="([^"]*issueView\?[^\"]+)"[^>]*>\s*<strong>(.*?)</strong>',block,re.S|re.I)
   date=re.search(r'<span\s+class="date"[^>]*>\s*(\d{4}\.\d{2}\.\d{2})',block)
   if not link:continue
   url=urljoin(source['url'],link[1]);title=clean(link[2])
   # Keep only the stable document identity, not list pagination/search parameters.
   ident=re.search(r'issue_no=(\d+)',url)
   if not ident:raise ValueError('KIET document identity missing')
   url='https://www.kiet.re.kr/research/issueView?issue_no='+ident[1]
  else:
   link=re.search(r'<div\s+class="subject"[^>]*>\s*<a\b[^>]*onclick="goDetailPage\(\s*\'(\d+)\'\s*,\s*\'([A-Z_]+)\'\);"[^>]*>(.*?)</a>',block,re.S)
   if not link:continue
   date=re.search(r'<i\s+class="icon-clock1"[^>]*>.*?</i>\s*(\d{4}\.\d{2}\.\d{2})',block,re.S)
   if link[2] not in KITA_PATHS:raise ValueError('Unknown KITA report type')
   url='https://www.kita.net/researchTrade/report/'+KITA_PATHS[link[2]]+'?no='+link[1];title=clean(link[3])
  if not date or not title:raise ValueError('Official report list is missing title/date; refusing partial success')
  if url in seen:continue
  seen.add(url);canonical_url(url)
  # Official lists supply a date, not a time. Preserve its Korean calendar day.
  stamp=datetime.strptime(date[1],'%Y.%m.%d').replace(tzinfo=timezone(timedelta(hours=9)))
  rows.append((title,url,stamp.strftime('%a, %d %b %Y %H:%M:%S %z')))
 if not rows:raise ValueError('No official report-list entries; page layout may have changed')
 rss='<rss version="2.0"><channel><title>Official report metadata</title>'+''.join('<item><title>'+escape(title)+'</title><link>'+escape(url)+'</link><pubDate>'+day+'</pubDate></item>' for title,url,day in rows)+'</channel></rss>'
 return rss.encode('utf-8')
