"""Durable intent before external effects; unknown outcomes are never replayed."""
from contextlib import contextmanager
import json
import sqlite3
import threading
import time
import uuid


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
            CREATE TABLE IF NOT EXISTS object_versions (kind TEXT NOT NULL,name TEXT NOT NULL,revision INTEGER NOT NULL,PRIMARY KEY(kind,name));
            CREATE TABLE IF NOT EXISTS state_actions (id TEXT PRIMARY KEY,payload TEXT NOT NULL,result TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS operations (
                id TEXT PRIMARY KEY, payload TEXT NOT NULL, status TEXT NOT NULL,
                result TEXT, created REAL NOT NULL);
        ''')
        row = self.connection.execute("SELECT value FROM metadata WHERE key='role'").fetchone()
        if row and row[0] != role:
            self.connection.close()
            raise ValueError('Persistent state belongs to another role')
        self.connection.execute("INSERT OR IGNORE INTO metadata VALUES ('role', ?)", (role,))
        self.connection.execute("INSERT OR IGNORE INTO metadata VALUES ('object_epoch', ?)", (uuid.uuid4().hex,))
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

    def mutate(self, operation, *, objects=()):
        with self.transaction() as db:
            row = db.execute("SELECT value FROM metadata WHERE key='state'").fetchone()
            state = json.loads(row[0]) if row else {}
            result = operation(state)
            db.execute("INSERT OR REPLACE INTO metadata VALUES ('state', ?)", (canonical(state),))
            self._advance_objects(db,objects)
            return result

    def snapshot(self):
        with self.lock:
            row = self.connection.execute("SELECT value FROM metadata WHERE key='state'").fetchone()
            return json.loads(row[0]) if row else {}

    def execute(self, identifier, payload, effect, *, on_complete=None, objects=()):
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
                if on_complete is not None:
                    row = db.execute("SELECT value FROM metadata WHERE key='state'").fetchone()
                    state = json.loads(row[0]) if row else {}
                    on_complete(state, result)
                    db.execute("INSERT OR REPLACE INTO metadata VALUES ('state', ?)", (canonical(state),))
                    self._advance_objects(db,objects)
                db.execute("UPDATE operations SET status='COMPLETED',result=? WHERE id=?",
                           (canonical(result), identifier))
            return result

    @staticmethod
    def _advance_objects(db,objects):
        from .objects import object_reference
        for kind,name in set(objects):
            object_reference(kind,name,None)
            db.execute('INSERT INTO object_versions VALUES (?,?,1) ON CONFLICT(kind,name) DO UPDATE SET revision=revision+1',(kind,name))

    @staticmethod
    def _object_epoch(db):
        return db.execute("SELECT value FROM metadata WHERE key='object_epoch'").fetchone()[0]

    @staticmethod
    def _object_version(db,kind,name):
        epoch=Journal._object_epoch(db)
        row=db.execute('SELECT revision FROM object_versions WHERE kind=? AND name=?',(kind,name)).fetchone()
        return epoch+':'+str(row[0] if row else 0)

    def observe_object(self,kind,name,select):
        from .objects import make_snapshot
        with self.transaction() as db:
            row=db.execute("SELECT value FROM metadata WHERE key='state'").fetchone()
            state=json.loads(row[0]) if row else {}
            uid,value,observations=select(state)
            return make_snapshot(kind,name,uid,state['owner_id'],self._object_epoch(db),self._object_version(db,kind,name),value,observations)

    def apply_action(self,request,select,transition):
        """Commit a local state transition and its receipt atomically; no external effects."""
        from .objects import validate_action,make_snapshot,request_sha256,ActionConflict,RESULT_SCHEMA
        validate_action(request);payload=canonical(request)
        with self.transaction() as db:
            previous=db.execute('SELECT payload,result FROM state_actions WHERE id=?',(request['operation_id'],)).fetchone()
            if previous:
                if previous[0]!=payload:raise ValueError('Operation identity payload conflict')
                return json.loads(previous[1])
            row=db.execute("SELECT value FROM metadata WHERE key='state'").fetchone()
            state=json.loads(row[0]) if row else {}
            target=request['target'];kind,name=target['kind'],target['name']
            uid,_,_=select(state)
            if (state.get('owner_id')!=request['owner_id'] or self._object_epoch(db)!=request['owner_uid'] or target['uid']!=uid
                    or request['expected_resource_version']!=self._object_version(db,kind,name)):
                raise ActionConflict('Object owner, UID or resource version changed; no action committed')
            result=transition(state,request['parameters'])
            db.execute("INSERT OR REPLACE INTO metadata VALUES ('state', ?)",(canonical(state),))
            self._advance_objects(db,[(kind,name)])
            uid,value,observations=select(state)
            after=make_snapshot(kind,name,uid,state['owner_id'],self._object_epoch(db),self._object_version(db,kind,name),value,observations)
            receipt=dict(schema=RESULT_SCHEMA,operation_id=request['operation_id'],actor_id=request['actor_id'],
                owner_id=state['owner_id'],owner_uid=request['owner_uid'],action=request['action'],target=target,object=after['object'],
                resource_version=after['resource_version'],recorded_at=after['observed_at'],
                before_resource_version=request['expected_resource_version'],request_sha256=request_sha256(request),result=result)
            db.execute('INSERT INTO state_actions VALUES (?,?,?)',(request['operation_id'],payload,canonical(receipt)))
            return receipt

    def read_action(self,identifier):
        from .objects import text
        text(identifier,'operation identity',192)
        with self.lock:
            row=self.connection.execute('SELECT result FROM state_actions WHERE id=?',(identifier,)).fetchone()
            if row is None:raise KeyError('State action receipt not found')
            return json.loads(row[0])

    def completed_operations(self):
        """Committed evidence for deterministic recovery; UNKNOWN is never included."""
        with self.lock:
            return [{'operation_id':row[0], 'payload':json.loads(row[1]), 'result':json.loads(row[2])}
                    for row in self.connection.execute(
                        "SELECT id,payload,result FROM operations WHERE status='COMPLETED' ORDER BY created")]

    def operations(self):
        with self.lock:
            return [{'operation_id': row[0], 'status': row[1]} for row in
                    self.connection.execute('SELECT id,status FROM operations ORDER BY created')]

    def close(self):
        self.connection.close()
