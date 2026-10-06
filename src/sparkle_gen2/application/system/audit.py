from __future__ import annotations
import hashlib,json,sqlite3,uuid
from contextlib import contextmanager
from pathlib import Path
from ...core_time import now

class AuditLog:
    def __init__(self,path):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.connect() as db:db.execute('CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY AUTOINCREMENT,event_id TEXT UNIQUE,created_at TEXT,kind TEXT,payload TEXT,prev_hash TEXT,event_hash TEXT)')
    @contextmanager
    def connect(self):
        db=sqlite3.connect(self.path)
        try:
            yield db;db.commit()
        except Exception:
            db.rollback();raise
        finally:
            db.close()
    def append(self,kind,payload):
        raw=json.dumps(payload,sort_keys=True,separators=(',',':'),ensure_ascii=False)
        with self.connect() as db:
            row=db.execute('SELECT event_hash FROM audit ORDER BY id DESC LIMIT 1').fetchone();prev=row[0] if row else ''
            event_id=uuid.uuid4().hex;created=now();digest=hashlib.sha256((prev+'|'+event_id+'|'+created+'|'+kind+'|'+raw).encode()).hexdigest()
            db.execute('INSERT INTO audit(event_id,created_at,kind,payload,prev_hash,event_hash) VALUES(?,?,?,?,?,?)',(event_id,created,kind,raw,prev,digest))
        return {'event_id':event_id,'hash':digest}
    def verify(self):
        with self.connect() as db:rows=db.execute('SELECT event_id,created_at,kind,payload,prev_hash,event_hash FROM audit ORDER BY id').fetchall()
        prev=''
        for event_id,created,kind,payload,prev_hash,event_hash in rows:
            if prev_hash!=prev:return False
            digest=hashlib.sha256((prev+'|'+event_id+'|'+created+'|'+kind+'|'+payload).encode()).hexdigest()
            if digest!=event_hash:return False
            prev=event_hash
        return True
