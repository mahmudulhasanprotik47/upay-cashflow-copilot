# SQLite storage for the Cash-Flow Copilot: accounts, sessions, API keys, consents, live transactions,
# budgets, feedback, prediction and audit logs, settings and event batches. All data is simulated.
# Standard library only. Every query uses ? placeholders, never string formatting with user input.

import contextlib  # The transaction() helper.
import sqlite3  # The database engine.
import threading  # One lock so uvicorn's worker threads take turns on the connection.
import time  # Timestamps.

from src import config as cfg  # Central settings.

# The full schema. Created once on an empty database; the version is kept in PRAGMA user_version.
SCHEMA = """
CREATE TABLE accounts (
    id INTEGER PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    pw_hash TEXT NOT NULL,                       -- scrypt hash with its own salt, never the password
    role TEXT NOT NULL CHECK (role IN ('admin', 'analyst', 'customer')),
    user_id INTEGER,                             -- the simulated user a customer account belongs to
    disabled INTEGER NOT NULL DEFAULT 0,
    failed_count INTEGER NOT NULL DEFAULT 0,     -- wrong passwords in a row
    locked_until REAL NOT NULL DEFAULT 0,        -- epoch seconds; 0 = not locked
    created_at REAL NOT NULL
);
CREATE UNIQUE INDEX accounts_one_per_user ON accounts(user_id) WHERE user_id IS NOT NULL;
CREATE TABLE sessions (
    token_hash TEXT PRIMARY KEY,                 -- SHA-256 of the cookie value, never the value
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    expires_at REAL NOT NULL
);
CREATE TABLE api_keys (
    id INTEGER PRIMARY KEY,
    key_hash TEXT NOT NULL UNIQUE,               -- SHA-256 of the key, never the key
    prefix TEXT NOT NULL,                        -- first characters, so an admin can tell keys apart
    label TEXT NOT NULL,
    created_by INTEGER REFERENCES accounts(id),
    revoked INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL
);
CREATE TABLE consents (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    notice_version TEXT NOT NULL,
    given_at REAL NOT NULL,
    withdrawn_at REAL
);
CREATE INDEX consents_user ON consents(user_id);
CREATE TABLE live_transactions (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    month INTEGER NOT NULL,
    day INTEGER NOT NULL,
    type TEXT NOT NULL,
    direction TEXT NOT NULL CHECK (direction IN ('in', 'out')),
    amount INTEGER NOT NULL CHECK (amount > 0),
    fee INTEGER NOT NULL CHECK (fee >= 0),
    idempotency_key TEXT NOT NULL,
    batch_id TEXT,                               -- set when the row came through the event bus
    created_at REAL NOT NULL,
    UNIQUE (user_id, idempotency_key)
);
CREATE INDEX live_user_month ON live_transactions(user_id, month);
CREATE TABLE budgets (
    user_id INTEGER NOT NULL,
    type TEXT NOT NULL,
    amount_bdt INTEGER NOT NULL CHECK (amount_bdt > 0),
    updated_at REAL NOT NULL,
    PRIMARY KEY (user_id, type)
);
CREATE TABLE feedback (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    suggestion_type TEXT NOT NULL,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    ab_group TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE predictions_log (
    id INTEGER PRIMARY KEY,
    created_at REAL NOT NULL,
    user_id INTEGER,
    month INTEGER,
    source TEXT NOT NULL,                        -- 'live' (page) or 'integration' (event bus)
    outcome TEXT NOT NULL CHECK (outcome IN ('scored', 'rejected')),
    error_code TEXT,                             -- why a transaction was rejected
    band TEXT,                                   -- low / medium / high; no probability is stored
    alert INTEGER,
    unusual INTEGER,
    budget_warnings INTEGER,
    ms REAL                                      -- scoring time in milliseconds
);
CREATE TABLE audit_log (
    id INTEGER PRIMARY KEY,
    at REAL NOT NULL,
    actor_account_id INTEGER,
    actor TEXT NOT NULL,                         -- username, 'api-key:<id>' or 'anonymous'
    role TEXT NOT NULL,
    action TEXT NOT NULL,
    target_user_id INTEGER,
    detail TEXT NOT NULL DEFAULT ''
);
CREATE INDEX audit_target ON audit_log(target_user_id);
CREATE TABLE settings (
    scope TEXT NOT NULL,                         -- 'global' or 'user:<user_id>'
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    updated_at REAL NOT NULL,
    PRIMARY KEY (scope, key)
);
CREATE TABLE event_batches (
    id TEXT PRIMARY KEY,
    api_key_id INTEGER,
    status TEXT NOT NULL,                        -- queued / running / done
    total INTEGER NOT NULL,
    accepted INTEGER NOT NULL DEFAULT 0,
    rejected INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    finished_at REAL
);
"""


class Database:
    """One SQLite connection shared by all threads, guarded by a re-entrant lock.

    ponytail: one global lock serialises every query; fine for one process and a demo load,
    switch to a connection pool or a server database if writes ever queue up.
    """

    def __init__(self, path):
        """Open (or create) the database file, set safe options and create the tables if needed."""
        self.lock = threading.RLock()
        # Autocommit mode; transaction() opens explicit transactions when several writes belong together.
        self.conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        with self.lock:
            self.conn.execute("PRAGMA journal_mode=WAL")  # Readers do not block the writer.
            self.conn.execute("PRAGMA foreign_keys=ON")
            self.conn.execute("PRAGMA busy_timeout=5000")  # Wait up to 5 s for another process's lock.
            self.migrate()

    def migrate(self):
        """Create the schema on an empty database; refuse a database made by a newer version."""
        version = self.conn.execute("PRAGMA user_version").fetchone()[0]
        if version == 0:
            self.conn.executescript("BEGIN;" + SCHEMA + f"PRAGMA user_version={cfg.DB_SCHEMA_VERSION};COMMIT;")
        elif version > cfg.DB_SCHEMA_VERSION:
            raise RuntimeError(f"database schema {version} is newer than this code ({cfg.DB_SCHEMA_VERSION})")

    def query(self, sql, params=()):
        """All rows of a SELECT as plain dicts."""
        with self.lock:
            return [dict(r) for r in self.conn.execute(sql, params).fetchall()]

    def one(self, sql, params=()):
        """The first row of a SELECT as a dict, or None."""
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def execute(self, sql, params=()):
        """Run one write; returns the cursor (lastrowid, rowcount)."""
        with self.lock:
            return self.conn.execute(sql, params)

    @contextlib.contextmanager
    def transaction(self):
        """Hold the lock and run several statements as one all-or-nothing transaction."""
        with self.lock:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                yield self
            except BaseException:
                self.conn.execute("ROLLBACK")
                raise
            self.conn.execute("COMMIT")

    def close(self):
        """Close the connection (used by the self-checks' temporary databases)."""
        with self.lock:
            self.conn.close()


# The database the app uses. Set once by init() at server start (or by the self-checks).
_db = None


def init(path=None):
    """Open the app database (data/copilot.db unless a path is given) and make it the current one."""
    global _db
    if path is None:
        cfg.DATA_DIR.mkdir(exist_ok=True)
        path = cfg.DB_PATH
    _db = Database(path)
    return _db


def get():
    """The current database. Raises if init() was not called."""
    if _db is None:
        raise RuntimeError("database not initialised")
    return _db


def use(db):
    """Make an already-open database the current one (the self-checks use an in-memory one)."""
    global _db
    _db = db


def now():
    """Current time in epoch seconds."""
    return time.time()


def audit(actor, action, target_user_id=None, detail=""):
    """Write one audit entry. actor is a principal dict (or None for an anonymous request)."""
    actor = actor or {}
    get().execute("INSERT INTO audit_log (at, actor_account_id, actor, role, action, target_user_id, detail) "
                  "VALUES (?, ?, ?, ?, ?, ?, ?)",
                  (now(), actor.get("account_id"), actor.get("name", "anonymous"), actor.get("role", "none"),
                   action, target_user_id, str(detail)[:500]))
