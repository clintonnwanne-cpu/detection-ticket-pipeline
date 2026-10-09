"""Local SQLite ticket simulator with transactional idempotency. No network calls."""
import argparse
import json
import sqlite3
from datetime import datetime


def timestamp(s):
    d = datetime.fromisoformat(s.replace('Z', '+00:00'))
    if d.tzinfo is None: raise ValueError('timezone required')
    return d.timestamp()


def connect(path):
    db = sqlite3.connect(path)
    db.executescript('''CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY, payload TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS tickets(finding TEXT PRIMARY KEY, updated REAL NOT NULL, payload TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY, event_id TEXT, outcome TEXT NOT NULL, detail TEXT);
    CREATE TABLE IF NOT EXISTS dead_letters(id INTEGER PRIMARY KEY, payload TEXT NOT NULL, reason TEXT NOT NULL);''')
    return db


def process(db, event, owners, fail=False):
    payload = json.dumps(event, sort_keys=True, allow_nan=False)
    event_id = event.get('event_id') if isinstance(event, dict) else None
    try:
        if not isinstance(event, dict): raise ValueError('event must be an object')
        for key in ('event_id', 'finding_id', 'asset_id', 'observed_at', 'status'):
            if not isinstance(event.get(key), str) or not event[key].strip(): raise ValueError(f'missing {key}')
        if event['status'] not in ('open', 'resolved'): raise ValueError('invalid status')
        at = timestamp(event['observed_at'])
        owner = owners.get(event['asset_id'])
        if not isinstance(owner, str) or not owner.strip(): raise ValueError('missing owner')
    except (ValueError, TypeError, AttributeError) as e:
        with db:
            db.execute('INSERT INTO dead_letters(payload,reason) VALUES (?,?)', (payload, str(e)))
            db.execute('INSERT INTO audit(event_id,outcome,detail) VALUES (?,?,?)', (event_id, 'dead_letter', str(e)))
        return 'dead_letter'
    # Local mock ticket and dedup record commit together. This is NOT an external API exactly-once guarantee.
    with db:
        db.execute('BEGIN IMMEDIATE')
        prior = db.execute('SELECT payload FROM events WHERE id=?', (event_id,)).fetchone()
        if prior:
            result = 'duplicate' if prior[0] == payload else 'id_collision'
            if result == 'id_collision':
                db.execute('INSERT INTO dead_letters(payload,reason) VALUES (?,?)', (payload, result))
        elif fail:
            result = 'retry'  # Deliberately leave event uncommitted for later replay.
        else:
            ticket = db.execute('SELECT updated FROM tickets WHERE finding=?', (event['finding_id'],)).fetchone()
            if ticket and at <= ticket[0]:
                result = 'out_of_order' if at < ticket[0] else 'same_time_conflict'
                if result == 'same_time_conflict':
                    db.execute('INSERT INTO dead_letters(payload,reason) VALUES (?,?)', (payload, result))
            else:
                value = json.dumps({**event, 'owner': owner}, sort_keys=True)
                db.execute('INSERT INTO tickets VALUES (?,?,?) ON CONFLICT(finding) DO UPDATE SET updated=excluded.updated,payload=excluded.payload', (event['finding_id'], at, value))
                result = 'created' if ticket is None else 'updated'
            db.execute('INSERT INTO events VALUES (?,?)', (event_id, payload))
        db.execute('INSERT INTO audit(event_id,outcome,detail) VALUES (?,?,?)', (event_id, result, 'local mock adapter'))
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('input'); p.add_argument('--db', required=True)
    p.add_argument('--simulate-failure', action='store_true')
    a = p.parse_args()
    with open(a.input) as f: data = json.load(f)
    db = connect(a.db)
    try:
        print(json.dumps([{'event_id': e.get('event_id') if isinstance(e, dict) else None,
                           'outcome': process(db, e, data['owners'], a.simulate_failure)} for e in data['events']], indent=2))
    finally: db.close()

if __name__ == '__main__': main()
