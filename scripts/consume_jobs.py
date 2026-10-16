"""Example: atomically mirror the v1 changes feed into a separate SQLite DB."""
import argparse
import json
import os
import sqlite3
import requests


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', default='http://127.0.0.1:8016')
    parser.add_argument('--database', default='consumer_jobs.db')
    args = parser.parse_args()
    key = os.environ['JOBAPP_API_KEY']
    with sqlite3.connect(args.database) as destination, requests.Session() as http:
        destination.execute('CREATE TABLE IF NOT EXISTS jobs (id INTEGER PRIMARY KEY, payload TEXT NOT NULL)')
        destination.execute('CREATE TABLE IF NOT EXISTS checkpoint (id INTEGER PRIMARY KEY CHECK(id=1), cursor INTEGER NOT NULL)')
        destination.execute('INSERT OR IGNORE INTO checkpoint VALUES (1,0)')
        destination.commit()
        while True:
            cursor = destination.execute('SELECT cursor FROM checkpoint WHERE id=1').fetchone()[0]
            response = http.get(args.url.rstrip('/')+'/api/v1/jobs/changes', params={'after':cursor,'limit':100},
                headers={'Authorization':'Bearer '+key}, timeout=30)
            response.raise_for_status()
            page = response.json()
            with destination:
                for item in page['items']:
                    if item['operation']=='delete':
                        destination.execute('DELETE FROM jobs WHERE id=?',(item['job_id'],))
                    else:
                        destination.execute('INSERT INTO jobs VALUES (?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload',
                            (item['job_id'],json.dumps(item['job'],ensure_ascii=False)))
                destination.execute('UPDATE checkpoint SET cursor=? WHERE id=1',(page['next_cursor'],))
            if not page['has_more']:
                break
        print('Synced through sequence',page['next_cursor'])


if __name__=='__main__':
    main()
