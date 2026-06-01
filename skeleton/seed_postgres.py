"""
Seed PostgreSQL with all TransitFlow mock data from train-mock-data/.

Usage:
    python skeleton/seed_postgres.py

Run AFTER docker-compose up -d.
You must first design and create your tables in databases/relational/schema.sql.
Safe to re-run: implement your inserts with ON CONFLICT DO NOTHING.
"""

import json
import os
import sys

import psycopg2
from psycopg2.extras import execute_values

# ── resolve paths ────────────────────────────────────────────────────────────
SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
DATA_DIR    = os.path.join(PROJECT_DIR, "train-mock-data")

sys.path.insert(0, PROJECT_DIR)
from skeleton import config as cfg


def load(filename):
    with open(os.path.join(DATA_DIR, filename), encoding="utf-8") as f:
        return json.load(f)


def connect():
    return psycopg2.connect(
        host=cfg.PG_HOST,
        port=cfg.PG_PORT,
        dbname=cfg.PG_DB,
        user=cfg.PG_USER,
        password=cfg.PG_PASSWORD,
    )


def insert_many(cur, table, columns, rows):
    """Bulk insert with ON CONFLICT DO NOTHING. Returns row count inserted."""
    if not rows:
        return 0
    sql = (
        f"INSERT INTO {table} ({', '.join(columns)}) VALUES %s "
        f"ON CONFLICT DO NOTHING"
    )
    execute_values(cur, sql, rows)
    return cur.rowcount


# ── seeders ──────────────────────────────────────────────────────────────────
#
# Notes on conventions used below:
#   * JSONB columns (lines, operates_on, ...) are passed as json.dumps(...) text;
#     PostgreSQL accepts a valid JSON string when writing to a jsonb column.
#   * metro_stations <-> national_rail_stations have a CIRCULAR foreign key
#     (each can be the other's interchange). We insert metro_stations first with
#     interchange_nr_station_id = NULL, then fill it in after the national-rail
#     rows exist (see the UPDATE at the end of seed_national_rail_stations).
#   * Schedules store their stop list in a nested structure, so each scheduler
#     seeds BOTH the header table and its *_schedule_stops detail table.


def seed_metro_stations(cur):
    data = load("metro_stations.json")
    rows = [
        (
            s["station_id"],
            s["name"],
            json.dumps(s.get("lines", [])),
            s.get("is_interchange_metro", False),
            json.dumps(s["interchange_metro_lines"]) if s.get("interchange_metro_lines") is not None else None,
            s.get("is_interchange_national_rail", False),
            # circular FK: set later, once national_rail_stations exist
            None,
        )
        for s in data
    ]
    n = insert_many(
        cur, "metro_stations",
        ["station_id", "name", "lines", "is_interchange_metro",
         "interchange_metro_lines", "is_interchange_national_rail",
         "interchange_nr_station_id"],
        rows,
    )
    print(f"  metro_stations: {n} rows")


def seed_national_rail_stations(cur):
    data = load("national_rail_stations.json")
    rows = [
        (
            s["station_id"],
            s["name"],
            json.dumps(s.get("lines", [])),
            s.get("is_interchange_national_rail", False),
            json.dumps(s["interchange_national_rail_lines"]) if s.get("interchange_national_rail_lines") is not None else None,
            s.get("is_interchange_metro", False),
            s.get("interchange_metro_station_id"),
        )
        for s in data
    ]
    n = insert_many(
        cur, "national_rail_stations",
        ["station_id", "name", "lines", "is_interchange_national_rail",
         "interchange_national_rail_lines", "is_interchange_metro",
         "interchange_metro_station_id"],
        rows,
    )
    print(f"  national_rail_stations: {n} rows")

    # Now that NR stations exist, complete the circular interchange link on the
    # metro side (metro_stations.interchange_nr_station_id -> NR station).
    metro = load("metro_stations.json")
    linked = 0
    for s in metro:
        nr_id = s.get("interchange_national_rail_station_id")
        if nr_id:
            cur.execute(
                "UPDATE metro_stations "
  