"""Durable records; consuming an approval and its audit event share one transaction."""

from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
from typing import Iterator

from .models import NetworkChange


class ApprovalStore:
    def __init__(self, path: str | Path):
        self.path = str(path)
        if self.path == ":memory:":
            raise ValueError("Use a file-backed SQLite database for shared durable state")
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS approvals (
                    request_id TEXT PRIMARY KEY,
                    change_json TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('pending','approved','denied')),
                    created_at REAL NOT NULL,
                    expires_at REAL NOT NULL,
                    approver_id TEXT,
                    decided_at REAL,
                    consumed_at REAL
                );
                CREATE TABLE IF NOT EXISTS audit_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    request_id TEXT NOT NULL,
                    event TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    timestamp REAL NOT NULL,
                    detail TEXT NOT NULL
                );
            """)

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            yield db
        finally:
            db.close()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise

    @staticmethod
    def _event(db, request_id, event, actor, now, detail):
        db.execute(
            "INSERT INTO audit_events(request_id,event,actor,timestamp,detail) VALUES(?,?,?,?,?)",
            (request_id, event, actor, now, detail),
        )

    def create(self, request_id, change: NetworkChange, reason, now, expires_at):
        with self._transaction() as db:
            db.execute(
                """INSERT INTO approvals
                (request_id,change_json,fingerprint,reason,status,created_at,expires_at)
                VALUES(?,?,?,?,'pending',?,?)""",
                (request_id, change.canonical_json, change.fingerprint, reason, now, expires_at),
            )
            self._event(db, request_id, "requested", "mcp-requester", now, change.fingerprint)

    def get(self, request_id):
        with self._connection() as db:
            row = db.execute("SELECT * FROM approvals WHERE request_id=?", (request_id,)).fetchone()
            return dict(row) if row else None

    def decide(self, request_id, approver, approve, clock) -> str:
        with self._transaction() as db:
            now = clock()
            row = db.execute("SELECT * FROM approvals WHERE request_id=?", (request_id,)).fetchone()
            if not row:
                result = "not_found"
            elif row["expires_at"] <= now:
                result = "expired"
            elif row["status"] != "pending":
                result = "already_decided"
            else:
                result = "approved" if approve else "denied"
                db.execute(
                    "UPDATE approvals SET status=?,approver_id=?,decided_at=? WHERE request_id=?",
                    (result, approver, now, request_id),
                )
            self._event(db, request_id, "decision", approver, now, result)
            return result

    def reject_identity(self, request_id, now, reason):
        with self._transaction() as db:
            self._event(db, request_id, "decision_rejected", "unverified-or-unauthorized", now, reason)

    def consume(self, request_id, change: NetworkChange, clock, *, actor="mock-policy-adapter") -> str:
        with self._transaction() as db:
            now = clock()
            row = db.execute("SELECT * FROM approvals WHERE request_id=?", (request_id,)).fetchone()
            if not row:
                result = "not_found"
            elif row["change_json"] != change.canonical_json or row["fingerprint"] != change.fingerprint:
                result = "change_mismatch"
            elif row["consumed_at"] is not None:
                result = "already_consumed"
            elif row["expires_at"] <= now:
                result = "expired"
            elif row["status"] != "approved" or not row["approver_id"]:
                result = "not_approved"
            else:
                changed = db.execute(
                    """UPDATE approvals SET consumed_at=? WHERE request_id=? AND status='approved'
                    AND consumed_at IS NULL AND expires_at>?""",
                    (now, request_id, now),
                ).rowcount
                result = "consumed" if changed == 1 else "already_consumed"
            self._event(db, request_id, "consume", actor, now, result)
            return result

    def events(self, request_id):
        with self._connection() as db:
            return [dict(row) for row in db.execute(
                "SELECT * FROM audit_events WHERE request_id=? ORDER BY event_id", (request_id,)
            )]


def public_record(row, now):
    status = row["status"]
    if status in {"pending", "approved"} and row["consumed_at"] is None and row["expires_at"] <= now:
        status = "expired"
    return {
        "request_id": row["request_id"], "status": status,
        "change": json.loads(row["change_json"]), "fingerprint": row["fingerprint"],
        "reason": row["reason"], "expires_at": row["expires_at"],
        "approver_id": row["approver_id"], "consumed": row["consumed_at"] is not None,
        "consumed_at": row["consumed_at"],
    }
