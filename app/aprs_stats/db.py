"""Datenbankverbindung und Schema."""
import os
import time
from contextlib import contextmanager
from importlib.resources import files

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://aprs:aprs@localhost:5432/aprs")

_pool: ConnectionPool | None = None


def pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            DATABASE_URL,
            min_size=1,
            max_size=8,
            kwargs={"row_factory": dict_row, "autocommit": False},
            open=True,
        )
    return _pool


@contextmanager
def conn():
    """Verbindung aus dem Pool; Commit bei Erfolg, Rollback bei Fehler."""
    with pool().connection() as c:
        yield c


def connect() -> psycopg.Connection:
    """Einzelne Verbindung (für den Collector), mit Wiederholung beim Start."""
    delay = 1
    while True:
        try:
            return psycopg.connect(DATABASE_URL, row_factory=dict_row, autocommit=True)
        except psycopg.OperationalError:
            time.sleep(delay)
            delay = min(delay * 2, 30)


def init_schema() -> None:
    sql = files("aprs_stats").joinpath("schema.sql").read_text(encoding="utf-8")
    with conn() as c:
        # Advisory-Lock, damit Web und Collector das Schema nicht gleichzeitig anlegen
        c.execute("SELECT pg_advisory_xact_lock(4711)")
        c.execute(sql)
