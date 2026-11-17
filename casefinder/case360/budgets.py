"""Per-tester local budget, shared by installed releases and retained after cleanup."""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from pathlib import Path

from .preferences import data_root

DEFAULT_TOTAL = 500
DEFAULT_REQUEST = 50
PICO = 10**12


def account_key(principal: str) -> str:
    return hashlib.sha256(principal.strip().lower().encode()).hexdigest()


def database() -> Path:
    return data_root() / "tester-budget.sqlite"


def _connect() -> sqlite3.Connection:
    file = database()
    file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    for suffix in ("", "-journal", "-wal", "-shm"):
        if Path(str(file) + suffix).is_symlink():
            raise ValueError("The budget file must be local to this installation.")
    db = sqlite3.connect(file, timeout=10)
    file.chmod(0o600)
    db.executescript("""
        PRAGMA synchronous=FULL;
        CREATE TABLE IF NOT EXISTS accounts (
          principal TEXT PRIMARY KEY, limit_pico INTEGER NOT NULL, request_pico INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS charges (
          principal TEXT NOT NULL, id TEXT NOT NULL, charge_pico INTEGER NOT NULL,
          uncertain INTEGER NOT NULL, PRIMARY KEY(principal,id));
    """)
    return db


def _row_id(row: dict) -> str:
    if row.get("id"):
        return row["id"]  # Content-erasure accounting retains the same call identity.
    identity = [row.get(k) for k in ("session_id", "body_sha256", "at", "attempt")]
    return hashlib.sha256(json.dumps(identity, separators=(",", ":")).encode()).hexdigest()


def _import_history(db: sqlite3.Connection, principal: str) -> None:
    """Adopt existing paid ledgers, including erased runs; never alter run artifacts."""
    root = data_root()
    contexts = set((root / "installations").glob("*/context.json"))
    if (root / "context.json").is_file():
        contexts.add(root / "context.json")
    runs_roots = set()
    for context_file in contexts:
        context = json.loads(context_file.read_text())
        if context.get("runs_root"):
            runs_roots.add(Path(context["runs_root"]))

    def adopt(rows: list) -> None:
        for row in rows:
            if row.get("simulated"):
                continue
            charge = row["charge_pico"]
            if not isinstance(charge, int) or not 0 <= charge <= 2**53 - 1:
                raise ValueError("Saved budget accounting needs review.")
            uncertain = int(row["charge_basis"] == "full_reservation_uncertain")
            db.execute(
                """INSERT INTO charges VALUES(?,?,?,?) ON CONFLICT(principal,id)
                DO UPDATE SET charge_pico=excluded.charge_pico, uncertain=excluded.uncertain
                WHERE charges.uncertain=1 AND excluded.uncertain=0""",
                (principal, _row_id(row), charge, uncertain),
            )

    for runs in runs_roots:
        for approval in runs.glob("*/evidence/authorization.json"):
            if account_key(json.loads(approval.read_text())["principal"]) != principal:
                continue
            run = approval.parent.parent
            for state in [
                run / "execution/case_state.json",
                *run.glob("attempts/*/case_state.json"),
            ]:
                if state.is_file():
                    adopt(json.loads(state.read_text())["ledger"])
        controller = runs / "controller.sqlite"
        if controller.is_file():
            source = sqlite3.connect(controller.as_uri() + "?mode=ro", uri=True)
            try:
                for (raw,) in source.execute("SELECT data FROM accounting"):
                    entry = json.loads(raw)
                    if (entry.get("approval") or {}).get("principal_sha256") == principal:
                        adopt(entry["ledger"])
            finally:
                source.close()


def ensure(principal: str, request_default: float = DEFAULT_REQUEST) -> dict:
    key = account_key(principal)
    db = _connect()
    try:
        with db:
            db.execute(
                "INSERT OR IGNORE INTO accounts VALUES(?,?,?)",
                (key, DEFAULT_TOTAL * PICO, round(request_default * PICO)),
            )
            _import_history(db, key)
        row = db.execute(
            "SELECT limit_pico,request_pico FROM accounts WHERE principal=?", (key,)
        ).fetchone()
        used = db.execute(
            "SELECT COALESCE(SUM(charge_pico),0) FROM charges WHERE principal=?", (key,)
        ).fetchone()[0]
        return {
            "total_usd": row[0] / PICO,
            "request_usd": row[1] / PICO,
            "used_usd": used / PICO,
            "remaining_usd": max(0, (row[0] - used) / PICO),
        }
    finally:
        db.close()


def save(principal: str, total: float, request: float) -> dict:
    if not (
        math.isfinite(total)
        and math.isfinite(request)
        and 0 <= total <= 9000
        and 0 <= request <= min(total, 1000)
    ):
        raise ValueError(
            "Enter a total from $0 to $9,000 and a request limit up to $1,000 within that total."
        )
    ensure(principal)
    db = _connect()
    try:
        with db:
            db.execute("BEGIN IMMEDIATE")
            key = account_key(principal)
            used = db.execute(
                "SELECT COALESCE(SUM(charge_pico),0) FROM charges WHERE principal=?", (key,)
            ).fetchone()[0]
            if round(total * PICO) < used:
                raise ValueError(
                    "The total cannot be lower than usage already charged or reserved."
                )
            db.execute(
                "UPDATE accounts SET limit_pico=?,request_pico=? WHERE principal=?",
                (round(total * PICO), round(request * PICO), key),
            )
    finally:
        db.close()
    return ensure(principal)
