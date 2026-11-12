"""Read-only storage verification for CI; never prints credentials or DB URLs."""
import argparse,json
from .db import DB

def snapshot(db):
 results=db.execute_many([("SELECT count(*) AS n FROM items WHERE kind='news'",()),("SELECT count(*) AS n FROM items WHERE kind='report'",()),('SELECT count(*) AS n FROM observations',())])
 return dict(storage_id=db.storage_id(),news=results[0]['rows'][0]['n'],reports=results[1]['rows'][0]['n'],observations=results[2]['rows'][0]['n'])

if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--require-remote',action='store_true');args=parser.parse_args();db=DB()
 if args.require_remote and not db.remote:raise SystemExit('Persistent Turso configuration required; refusing local fallback')
 print(json.dumps(snapshot(db)),flush=True)
