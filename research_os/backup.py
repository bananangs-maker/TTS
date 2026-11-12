"""Portable full database JSON export; contains private notes. Never commit output."""
import argparse,json,os
from pathlib import Path
from .db import DB
from .core import now
TABLES=['schema_versions','source_candidates','sources','items','runs','series','observations','indicator_runs','records','forecast_releases','article_features','article_keywords','research_daily','research_dictionary','industry_events','event_sources','event_reviews','observation_vintages','detected_signals','analysis_runs','research_projects','research_hypotheses','research_experiments','research_notes','generated_reports','janus_datasets','janus_observations','duplicate_origins','event_links','feature_completion']
def backup(db,path):
 available={r['name'] for r in db.all("SELECT name FROM sqlite_master WHERE type='table'")}
 payload={'format':'research-os-backup-v1','exported_at':now(),'tables':{t:db.all('SELECT * FROM '+t) for t in TABLES if t in available}}
 p=Path(path);p.parent.mkdir(parents=True,exist_ok=True)
 with open(p,'w',encoding='utf-8') as f:json.dump(payload,f,ensure_ascii=False)
 os.chmod(p,0o600)
def restore(db,path):
 p=json.loads(Path(path).read_text())
 if p.get('format')!='research-os-backup-v1':raise ValueError('Unknown backup')
 db.migrate()
 if db.one('SELECT count(*) AS n FROM items')['n']:
  raise ValueError('Restore requires an empty database; existing research is never overwritten')
 for t in TABLES:
  rows=p['tables'].get(t,[])
  # Columns come from the actual schema, never use SQL identifiers from backup.
  columns=[r['name'] for r in db.all('PRAGMA table_info('+t+')')]
  for row in rows:
   selected=[c for c in columns if c in row]
   if not selected:continue
   db.execute('INSERT OR REPLACE INTO '+t+'('+','.join(selected)+') VALUES('+','.join('?' for _ in selected)+')',[row[c] for c in selected])
 db.index_missing()
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('action',choices=['export','restore']);p.add_argument('path');a=p.parse_args()
 (backup if a.action=='export' else restore)(DB(),a.path)
