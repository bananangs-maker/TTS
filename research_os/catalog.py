import hashlib
"""Only publisher-documented RSS. Titles/links only for news; no article fetch."""
SOURCES=[
 dict(id='kr-hk-economy',name='한국경제 · 경제',url='https://www.hankyung.com/feed/economy',homepage='https://www.hankyung.com/feed',kind='news',category='거시경제',language='ko',interval_minutes=180),
 dict(id='kr-hk-it',name='한국경제 · IT',url='https://www.hankyung.com/feed/it',homepage='https://www.hankyung.com/feed',kind='news',category='기타',language='ko',interval_minutes=180),
 dict(id='kr-et-electronics',name='전자신문 · 전자·소부장',url='https://rss.etnews.com/06.xml',homepage='https://www.etnews.com/rss/',kind='news',category='기타',language='ko',interval_minutes=180),
 dict(id='kr-et-mobility',name='전자신문 · 모빌리티',url='https://rss.etnews.com/17.xml',homepage='https://www.etnews.com/rss/',kind='news',category='기타',language='ko',interval_minutes=180),
 dict(id='kr-et-economy',name='전자신문 · 경제',url='https://rss.etnews.com/02.xml',homepage='https://www.etnews.com/rss/',kind='news',category='거시경제',language='ko',interval_minutes=180),
 dict(id='bok-issues',name='한국은행 · BOK 이슈노트',url='https://www.bok.or.kr/portal/bbs/P0002353/news.rss?menuNo=200433',homepage='https://www.bok.or.kr/static/guide/portal/popup/rss_popup.html',kind='report',category='거시경제',language='ko',interval_minutes=720),
 dict(id='bok-outlook',name='한국은행 · 경제전망',url='https://www.bok.or.kr/portal/bbs/P0002359/news.rss?menuNo=200066',homepage='https://www.bok.or.kr/static/guide/portal/popup/rss_popup.html',kind='report',category='거시경제',language='ko',interval_minutes=1440),
 dict(id='bok-global',name='한국은행 · 국제경제리뷰',url='https://www.bok.or.kr/portal/bbs/P0000528/news.rss?menuNo=200434',homepage='https://www.bok.or.kr/static/guide/portal/popup/rss_popup.html',kind='report',category='거시경제',language='ko',interval_minutes=720),
 dict(id='fed',name='Federal Reserve',url='https://www.federalreserve.gov/feeds/press_all.xml',homepage='https://www.federalreserve.gov/feeds/feeds.htm',kind='news',category='정책·통상',language='en',interval_minutes=360),
 dict(id='semi-digest',name='Semiconductor Digest',url='https://www.semiconductor-digest.com/feed/',homepage='https://www.semiconductor-digest.com/',kind='news',category='반도체',language='en',interval_minutes=360),
 dict(id='electrive',name='electrive',url='https://www.electrive.com/feed/',homepage='https://www.electrive.com/',kind='news',category='2차전지',language='en',interval_minutes=360),
 dict(id='storage',name='Energy-Storage.news',url='https://www.energy-storage.news/feed/',homepage='https://www.energy-storage.news/',kind='news',category='2차전지',language='en',interval_minutes=360)
]
SERIES=[
 ('DEXKOUS','USD / KRW','원 / USD','daily','Federal Reserve H.10'),
 ('DFEDTARU','미국 정책금리 상단','%','daily','Federal Reserve'),
 ('DFEDTARL','미국 정책금리 하단','%','daily','Federal Reserve'),
 ('DGS10','미국 국채 10년','%','daily','US Treasury'),
 ('DGS2','미국 국채 2년','%','daily','US Treasury'),
 ('DCOILBRENTEU','Brent 현물','USD / 배럴','daily','EIA'),
 ('DCOILWTICO','WTI 현물','USD / 배럴','daily','EIA'),
 ('CPIAUCSL','미국 CPI · 계절조정','1982–84=100','monthly','BLS'),
 ('IRLTLT01KRM156N','한국 장기국채 수익률','%','monthly','OECD'),
 ('A191RL1Q225SBEA','미국 실질 GDP 성장률 · 전기비 연율','%','quarterly','BEA'),
 ('PPIACO','미국 PPI · 비계절조정','1982=100','monthly','BLS'),
 ('INDPRO','미국 산업생산 · 계절조정','2017=100','monthly','Federal Reserve'),
 ('VALEXPKRM052N','한국 상품 수출 · 비계절조정','백만 USD','monthly','IMF IFS'),
 ('VALIMPKRM052N','한국 상품 수입 · 비계절조정','백만 USD','monthly','IMF IFS')]
PENDING=[
 ('한국무역협회 국제무역통상연구원','수집 조건 및 목록 API 미검증','https://www.kita.net/'),
 ('산업연구원','RSS/API와 자동 수집 조건 미검증','https://www.kiet.re.kr/'),
 ('KDI','공식 Open API 인증키 필요','https://www.kdi.re.kr/share/openAPI'),
 ('KOSIS · 한국 수출입·생산','API 키·통계표 코드 검증 필요','https://kosis.kr/openapi/'),
 ('한국 월간 CPI','검토한 FRED 후보 CSV는 404 · ECOS/KOSIS 공식 계열 인증·검증 필요','https://kosis.kr/openapi/'),
 ('한국 기준금리 · ECOS','API 키·계열 코드 검증 필요','https://ecos.bok.or.kr/api/'),
 ('한국석유공사','유가 API 인증·약관 미검증','https://www.opinet.co.kr/'),
 ('EIA 보고서','공식 RSS 경로 robots.txt /rss 제한 확인 · 미수집','https://www.eia.gov/tools/rssfeeds/'),
 ('IEA','보고서 목록 수집 조건 미검증','https://www.iea.org/reports'),
 ('IMF','정형 전망 자료 API 수집 미검증','https://www.imf.org/en/Publications/WEO'),
 ('OECD 보고서','지표 일부 FRED 경유 · 보고서 수집 미검증','https://www.oecd.org/'),
 ('World Bank','API·세계교역 계열 검증 필요','https://data.worldbank.org/'),
 ('SEMI','유료 자료 제외 · 공개 목록 수집 조건 미검증','https://www.semi.org/'),
 ('SIA','RSS 후보가 HTML/302 응답 · 미수집','https://www.semiconductors.org/')]
def initialize(db):
 queries=[]
 for s in SOURCES:
  policy='공식 RSS · 개인 비공개 열람용 · 제목·원문 링크 보존 · 전문 미저장'
  queries.append(('INSERT INTO sources(id,name,url,homepage,kind,category,language,interval_minutes,policy) VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,url=excluded.url,policy=excluded.policy',(s['id'],s['name'],s['url'],s['homepage'],s['kind'],s['category'],s['language'],s['interval_minutes'],policy)))
 for i,n,u,f,p in SERIES:queries.append(('INSERT INTO series(id,name,unit,frequency,provider,url) VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO NOTHING',(i,n,u,f,p,'https://fred.stlouisfed.org/series/'+i)))

 for idx,(n,note,url) in enumerate(PENDING):
  queries.append(('INSERT INTO source_candidates(id,name,url,method,status,note) VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET note=excluded.note',('candidate-'+hashlib.sha256(n.encode()).hexdigest()[:16],n,url,'official_page_review','unverified',note)))
 db.execute_many(queries)
