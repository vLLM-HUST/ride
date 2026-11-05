"""Durable intent before external effects; unknown outcomes are never replayed."""
from contextlib import contextmanager
import json
import sqlite3
import threading
import time


class UnknownOutcome(RuntimeError):
    pass


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


class Journal:
    def __init__(self, path, role):
        self.lock = threading.RLock()
        self.connection = sqlite3.connect(str(path), check_same_thread=False)
        self.connection.execute('PRAGMA journal_mode=WAL')
        self.connection.execute('PRAGMA synchronous=FULL')
        self.connection.executescript('''
            CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS operations (
                id TEXT PRIMARY KEY, payload TEXT NOT NULL, status TEXT NOT NULL,
                result TEXT, created REAL NOT NULL);
        ''')
        row = self.connection.execute("SELECT value FROM metadata WHERE key='role'").fetchone()
        if row and row[0] != role:
            self.connection.close()
            raise ValueError('Persistent state belongs to another role')
        self.connection.execute("INSERT OR IGNORE INTO metadata VALUES ('role', ?)", (role,))
        self.connection.commit()

    @contextmanager
    def transaction(self):
        with self.lock:
            try:
                self.connection.execute('BEGIN IMMEDIATE')
                yield self.connection
                self.connection.commit()
            except BaseException:
                self.connection.rollback()
                raise

    def mutate(self, operation):
        with self.transaction() as db:
            row = db.execute("SELECT value FROM metadata WHERE key='state'").fetchone()
            state = json.loads(row[0]) if row else {}
            result = operation(state)
            db.execute("INSERT OR REPLACE INTO metadata VALUES ('state', ?)", (canonical(state),))
            return result

    def snapshot(self):
        with self.lock:
            row = self.connection.execute("SELECT value FROM metadata WHERE key='state'").fetchone()
            return json.loads(row[0]) if row else {}

    def execute(self, identifier, payload, effect):
        if not isinstance(identifier, str) or not 0 < len(identifier) <= 256:
            raise ValueError('Explicit bounded operation identifier required')
        serialized = canonical(payload)
        with self.lock:
            with self.transaction() as db:
                row = db.execute('SELECT payload,status,result FROM operations WHERE id=?', (identifier,)).fetchone()
                if row:
                    if row[0] != serialized:
                        raise ValueError('Operation identifier payload conflict')
                    if row[1] != 'COMPLETED':
                        raise UnknownOutcome('Operation outcome unknown; inspect original effect, do not resubmit')
                    return json.loads(row[2])
                db.execute('INSERT INTO operations VALUES (?,?,?,NULL,?)',
                           (identifier, serialized, 'UNKNOWN', time.time()))
            # Intent is committed before the external call. Even BaseException
            # or malformed responses leave an inspectable UNKNOWN record.
            result = effect()
            with self.transaction() as db:
                db.execute("UPDATE operations SET status='COMPLETED',result=? WHERE id=?",
                           (canonical(result), identifier))
            return result

    def operations(self):
        with self.lock:
            return [{'operation_id': row[0], 'status': row[1]} for row in
                    self.connection.execute('SELECT id,status FROM operations ORDER BY created')]

    def close(self):
        self.connection.close()
