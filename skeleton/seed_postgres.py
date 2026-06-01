"""
Seed PostgreSQL with all TransitFlow mock data from train-mock-data/.
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
        host="localhost",
        port=5433,               # 這裡已經寫死 5433
        dbname="transitflow",
        user="transitflow",
        password="transitflow"
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
    columns = [
        'station_id', 'name', 'lines', 'is_interchange_metro', 
        'interchange_metro_lines', 'is_interchange_national_rail', 'interchange_nr_station_id'
    ]
    rows = []
    for d in data:
        rows.append((
            d['station_id'], 
            d['name'], 
            json.dumps(d['lines']),
            d.get('is_interchange_metro', False),
            json.dumps(d.get('interchange_metro_lines', [])),
            d.get('is_interchange_national_rail', False),
            d.get('interchange_nr_station_id', None)
        ))
    inserted = insert_many(cur, 'metro_stations', columns, rows)
    print(f"  -> Inserted {inserted} metro_stations")


def seed_national_rail_stations(cur):
    data = load("national_rail_stations.json")
    columns = [
        'station_id', 'name', 'lines', 'is_interchange_national_rail', 
        'interchange_national_rail_lines', 'is_interchange_metro', 'interchange_metro_station_id'
    ]
    rows = []
    for d in data:
        rows.append((
            d['station_id'], 
            d['name'], 
            json.dumps(d['lines']), 
            d.get('is_interchange_national_rail', False),
            json.dumps(d.get('interchange_national_rail_lines', [])),
            d.get('is_interchange_metro', False),
            d.get('interchange_metro_station_id', None)
        ))
    inserted = insert_many(cur, 'national_rail_stations', columns, rows)
    print(f"  -> Inserted {inserted} national_rail_stations")


def seed_metro_schedules(cur):
    data = load("metro_schedules.json")
    sch_cols = [
        'schedule_id', 'line', 'direction', 'origin_station_id', 'destination_station_id',
        'first_train_time', 'last_train_time', 'base_fare_usd', 'per_stop_rate_usd',
        'frequency_min', 'operates_on'
    ]
    sch_rows = []
    stop_cols = ['schedule_id', 'station_id', 'stop_order', 'travel_time_from_origin_min']
    stop_rows = []
    
    for d in data:
        sch_rows.append((
            d['schedule_id'], d['line'], d['direction'], d['origin_station_id'], 
            d['destination_station_id'], d['first_train_time'], d['last_train_time'], 
            d['base_fare_usd'], d['per_stop_rate_usd'], d['frequency_min'], json.dumps(d['operates_on'])
        ))
        for stop in d.get('stops', []):
            stop_rows.append((
                d['schedule_id'], stop['station_id'], stop['stop_order'], stop['travel_time_from_origin_min']
            ))
            
    inserted_sch = insert_many(cur, 'metro_schedules', sch_cols, sch_rows)
    inserted_stops = insert_many(cur, 'metro_schedule_stops', stop_cols, stop_rows)
    print(f"  -> Inserted {inserted_sch} metro_schedules and {inserted_stops} stops")


def seed_national_rail_schedules(cur):
    data = load("national_rail_schedules.json")
    
    sch_cols = [
        'schedule_id', 'line', 'service_type', 'direction', 'origin_station_id', 
        'destination_station_id', 'first_train_time', 'last_train_time', 'frequency_min', 
        'operates_on', 'standard_base_fare_usd', 'standard_per_stop_rate_usd', 
        'first_base_fare_usd', 'first_per_stop_rate_usd'
    ]
    sch_rows = []
    
    stop_cols = ['schedule_id', 'station_id', 'stop_order', 'travel_time_from_origin_min', 'is_pass_through']
    stop_rows = []

    for d in data:
        fare_info = d.get('fare_classes', {})
        std_fare = fare_info.get('standard', {})
        fst_fare = fare_info.get('first', {})
        
        standard_base = std_fare.get('base_fare_usd', 0.0)
        standard_rate = std_fare.get('per_stop_rate_usd', 0.0)
        first_base = fst_fare.get('base_fare_usd', 0.0)
        first_rate = fst_fare.get('per_stop_rate_usd', 0.0)

        sch_rows.append((
            d['schedule_id'], d['line'], d['service_type'], d['direction'], d['origin_station_id'], 
            d['destination_station_id'], d['first_train_time'], d['last_train_time'], d['frequency_min'], 
            json.dumps(d['operates_on']), 
            standard_base, standard_rate, 
            first_base, first_rate
        ))
        
        time_map = d.get('travel_time_from_origin_min', {})
        
        order_idx = 1
        for station in d.get('stops_in_order', []):
            t_time = time_map.get(station, 0)
            stop_rows.append((
                d['schedule_id'], station, order_idx, t_time, False
            ))
            order_idx += 1
            
        for station in d.get('passed_through_stations', []):
            t_time = time_map.get(station, 0)
            stop_rows.append((
                d['schedule_id'], station, order_idx, t_time, True
            ))
            order_idx += 1
            
    inserted_sch = insert_many(cur, 'national_rail_schedules', sch_cols, sch_rows)
    inserted_stops = insert_many(cur, 'national_rail_schedule_stops', stop_cols, stop_rows)
    print(f"  -> Inserted {inserted_sch} national_rail_schedules and {inserted_stops} stops")


def seed_users(cur):
    data = load("registered_users.json")
    columns = [
        'user_id', 'full_name', 'email', 'password', 'phone', 
        'date_of_birth', 'secret_question', 'secret_answer', 'registered_at', 'is_active'
    ]
    rows = []
    for d in data:
        rows.append((
            d['user_id'], d['full_name'], d['email'], d['password'], d.get('phone'), 
            d.get('date_of_birth'), d.get('secret_question'), d.get('secret_answer'), 
            d['registered_at'], d.get('is_active', True)
        ))
    inserted = insert_many(cur, 'registered_users', columns, rows)
    print(f"  -> Inserted {inserted} registered_users")


def seed_national_rail_bookings(cur):
    data = load("bookings.json")
    columns = [
        'booking_id', 'user_id', 'schedule_id', 'origin_station_id', 'destination_station_id', 
        'travel_date', 'departure_time', 'ticket_type', 'fare_class', 'coach', 'seat_id', 
        'stops_travelled', 'amount_usd', 'status', 'booked_at', 'travelled_at'
    ]
    rows = []
    for d in data:
        rows.append((
            d['booking_id'], d['user_id'], d['schedule_id'], d['origin_station_id'], d['destination_station_id'], 
            d['travel_date'], d['departure_time'], d['ticket_type'], d['fare_class'], d['coach'], d['seat_id'], 
            d['stops_travelled'], d['amount_usd'], d['status'], d['booked_at'], d.get('travelled_at')
        ))
    inserted = insert_many(cur, 'national_rail_bookings', columns, rows)
    print(f"  -> Inserted {inserted} national_rail_bookings")


def seed_payments(cur):
    data = load("payments.json")
    columns = ['payment_id', 'booking_id', 'amount_usd', 'method', 'status', 'paid_at']
    rows = []
    for d in data:
        rows.append((
            d['payment_id'], d['booking_id'], d['amount_usd'], d['method'], d['status'], d['paid_at']
        ))
    inserted = insert_many(cur, 'payments', columns, rows)
    print(f"  -> Inserted {inserted} payments")


def seed_seat_layouts(cur):
    pass 

def seed_metro_travels(cur):
    pass

def seed_feedback(cur):
    pass


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    print("Connecting to PostgreSQL...")
    conn = connect()
    conn.autocommit = False
    cur = conn.cursor()

    try:
        cur.execute("SET session_replication_role = 'replica';")
        
        print("Seeding tables (dependency order):")
        seed_metro_stations(cur)
        seed_national_rail_stations(cur)
        seed_metro_schedules(cur)
        seed_national_rail_schedules(cur)
        seed_seat_layouts(cur)
        seed_users(cur)
        seed_national_rail_bookings(cur)
        seed_metro_travels(cur)
        seed_payments(cur)
        seed_feedback(cur)
        
        cur.execute("SET session_replication_role = 'origin';")
        
        conn.commit()
        print("\nAll done. Database seeded successfully. 🚀")
    except Exception as e:
        conn.rollback()
        print(f"\nError: {e}")
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()