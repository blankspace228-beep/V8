import os, re

_ACTIVE=False

class HybridRow(dict):
    def __init__(self, columns, values):
        super().__init__(zip(columns, values))
        self._values=list(values)
    def __getitem__(self, key):
        if isinstance(key, int): return self._values[key]
        return super().__getitem__(key)

class MemoryCursor:
    def __init__(self, rows): self._rows=rows
    def fetchone(self): return self._rows[0] if self._rows else None
    def fetchall(self): return list(self._rows)

class PGCursor:
    def __init__(self, cursor): self.cursor=cursor
    def _row(self, raw):
        if raw is None: return None
        cols=[d.name if hasattr(d,'name') else d[0] for d in (self.cursor.description or [])]
        return HybridRow(cols, raw)
    def fetchone(self): return self._row(self.cursor.fetchone())
    def fetchall(self): return [self._row(x) for x in self.cursor.fetchall()]

class PGConnection:
    def __init__(self, conn):
        self.conn=conn
        self.last_id=None
    def _translate(self, sql):
        s=sql.strip()
        s=re.sub(r'(\b[\w.]+)\s*=\s*\?\s+COLLATE\s+NOCASE', r'\1 ILIKE ?', s, flags=re.I)
        s=re.sub(r'\s+COLLATE\s+NOCASE\b','',s,flags=re.I)
        s=re.sub(r"date\('now'\s*,\s*'\+30 day'\)", "(CURRENT_DATE + INTERVAL '30 day')", s, flags=re.I)
        s=re.sub(r"date\('now'\)", "CURRENT_DATE", s, flags=re.I)
        s=re.sub(r'INTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT', 'BIGSERIAL PRIMARY KEY', s, flags=re.I)
        s=re.sub(r'\bBLOB\b', 'BYTEA', s, flags=re.I)
        s=s.replace('?', '%s')
        return s
    def execute(self, sql, params=()):
        stripped=sql.strip()
        if re.match(r'^SELECT\s+last_insert_rowid\s*\(\s*\)\s*;?$', stripped, flags=re.I):
            return MemoryCursor([HybridRow(['last_insert_rowid()'], [self.last_id])])
        q=self._translate(sql)
        cur=self.conn.cursor()
        is_insert=bool(re.match(r'^\s*INSERT\s+INTO\s+', q, flags=re.I))
        if is_insert and not re.search(r'\bRETURNING\b',q,flags=re.I):
            q=q.rstrip().rstrip(';')+' RETURNING id'
            cur.execute(q, params)
            row=cur.fetchone()
            self.last_id=row[0] if row else None
            return MemoryCursor([])
        cur.execute(q, params)
        return PGCursor(cur)
    def executescript(self, script):
        for part in script.split(';'):
            if part.strip(): self.execute(part)
        return self
    def commit(self): self.conn.commit()
    def rollback(self): self.conn.rollback()
    def close(self): self.conn.close()


def pg_db():
    import psycopg
    url=os.environ.get('DATABASE_URL','').strip()
    if not url: raise RuntimeError('DATABASE_URL is not configured')
    conn=psycopg.connect(url)
    schema=os.environ.get('PG_SCHEMA','high_desert_fire').strip() or 'high_desert_fire'
    if not re.match(r'^[A-Za-z_][A-Za-z0-9_]*$',schema): raise RuntimeError('Invalid PG_SCHEMA')
    cur=conn.cursor(); cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'); cur.execute(f'SET search_path TO "{schema}"'); conn.commit(); cur.close()
    return PGConnection(conn)


def activate():
    global _ACTIVE
    if _ACTIVE or not os.environ.get('DATABASE_URL'): return False
    import app as base
    import sitecustomize as ops
    import auth_upgrade as auth
    base.db=pg_db; ops.db=pg_db; auth.db=pg_db
    base.init_db(); ops.init_ops(); auth.init_upgrade()
    _ACTIVE=True
    return True
