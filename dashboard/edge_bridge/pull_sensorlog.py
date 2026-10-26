"""Read MySQL sensorlog into a restartable local SQLite archive."""

import argparse
import datetime
import decimal
import json
import logging
import os
from pathlib import Path
import re
import sqlite3
import time

import pymysql


def identifier(value):
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
        raise ValueError(f"Invalid SQL identifier: {value!r}")
    return f"`{value}`"


def json_value(value):
    if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
        return value.isoformat()
    if isinstance(value, (decimal.Decimal, datetime.timedelta)):
        return str(value)
    if isinstance(value, bytes):
        return {"encoding": "hex", "value": value.hex()}
    raise TypeError(f"Unsupported database value: {type(value).__name__}")


def sync(args, local):
    table = identifier(args.table)
    source = f"{args.host}:{args.port}/{args.database}/{args.table}"
    remote = pymysql.connect(
        host=args.host, port=args.port, user=args.user,
        password=os.environ["SENSORLOG_MYSQL_PASSWORD"], database=args.database,
        charset="utf8mb4", connect_timeout=8, read_timeout=30,
        write_timeout=30, autocommit=True, cursorclass=pymysql.cursors.DictCursor,
    )
    total = 0
    try:
        with remote.cursor() as cursor:
            cursor.execute(f"SHOW COLUMNS FROM {table}")
            columns = cursor.fetchall()
            primary = [c for c in columns if c["Key"] == "PRI"]
            key = args.id_column
            if key is None:
                if len(primary) != 1:
                    raise ValueError("A single integer primary key is required; specify --id-column if appropriate")
                key = primary[0]["Field"]
            column = next((c for c in columns if c["Field"] == key), None)
            if column is None or not re.match(r"^(tinyint|smallint|mediumint|int|bigint)\b", column["Type"], re.I):
                raise ValueError("The cursor column must be an increasing, unique integer")
            cursor.execute(f"SHOW INDEX FROM {table}")
            indexes = {}
            for index in cursor.fetchall():
                if index["Non_unique"] == 0:
                    indexes.setdefault(index["Key_name"], []).append(index["Column_name"])
            if [key] not in indexes.values():
                raise ValueError("The cursor column must have a single-column unique index")
            quoted_key = identifier(key)
            state = local.execute("SELECT key_column, last_id FROM sync_state WHERE source=?", (source,)).fetchone()
            if state and state[0] != key:
                raise ValueError("Cursor column changed; use a separate output database")
            last_id = int(state[1]) if state else None
            while True:
                if last_id is None:
                    cursor.execute(f"SELECT * FROM {table} ORDER BY {quoted_key} LIMIT %s", (args.batch_size,))
                else:
                    cursor.execute(f"SELECT * FROM {table} WHERE {quoted_key} > %s ORDER BY {quoted_key} LIMIT %s", (last_id, args.batch_size))
                rows = cursor.fetchall()
                if not rows:
                    return total
                now = datetime.datetime.now(datetime.timezone.utc).isoformat()
                next_id = int(rows[-1][key])
                # Rows and cursor commit together: a failed batch is safe to retry.
                with local:
                    local.executemany(
                        "INSERT OR IGNORE INTO sensorlog(source, row_id, payload_json, fetched_at) VALUES (?, ?, ?, ?)",
                        [(source, str(row[key]), json.dumps(row, ensure_ascii=False, default=json_value), now) for row in rows],
                    )
                    local.execute(
                        "INSERT INTO sync_state VALUES (?, ?, ?) ON CONFLICT(source) DO UPDATE SET last_id=excluded.last_id",
                        (source, key, str(next_id)),
                    )
                last_id = next_id
                total += len(rows)
                logging.info("Fetched %d rows (batch %d, last_id=%s)", total, len(rows), last_id)
                if len(rows) < args.batch_size:
                    return total
    finally:
        remote.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="3.39.173.120")
    parser.add_argument("--port", type=int, default=3306)
    parser.add_argument("--database", default="vision4")
    parser.add_argument("--table", default="sensorlog")
    parser.add_argument("--user", default="root")
    parser.add_argument("--id-column", help="Increasing unique integer column; defaults to primary key")
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parent / "data/sensorlog.sqlite3")
    parser.add_argument("--interval", type=float, default=30)
    parser.add_argument("--batch-size", type=int, default=1000)
    parser.add_argument("--once", action="store_true", help="Fetch current rows and exit")
    args = parser.parse_args()
    if args.interval <= 0 or args.batch_size <= 0:
        parser.error("interval and batch-size must be positive")
    if "SENSORLOG_MYSQL_PASSWORD" not in os.environ:
        parser.error("Set SENSORLOG_MYSQL_PASSWORD")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    local = sqlite3.connect(args.output)
    local.executescript("""
        CREATE TABLE IF NOT EXISTS sensorlog (
            source TEXT NOT NULL, row_id TEXT NOT NULL, payload_json TEXT NOT NULL,
            fetched_at TEXT NOT NULL, PRIMARY KEY(source, row_id)
        );
        CREATE TABLE IF NOT EXISTS sync_state (
            source TEXT PRIMARY KEY, key_column TEXT NOT NULL, last_id TEXT NOT NULL
        );
    """)
    try:
        while True:
            try:
                count = sync(args, local)
                logging.info("Sync complete: %d rows; output=%s", count, args.output)
            except (pymysql.MySQLError, OSError) as exc:
                logging.error("Connection/read failed (%s); check host, port and MySQL access", type(exc).__name__)
                if args.once:
                    return 1
            except (ValueError, TypeError, sqlite3.Error) as exc:
                logging.error("Sync stopped: %s", exc)
                return 1
            if args.once:
                return 0
            time.sleep(args.interval)
    except KeyboardInterrupt:
        logging.info("Stopped")
        return 0
    finally:
        local.close()


if __name__ == "__main__":
    raise SystemExit(main())
