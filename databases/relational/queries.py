# TASK 6 EXTENSION: added query_active_delays function and delay_records query support
"""
TransitFlow — PostgreSQL / Relational Database Layer
=====================================================
This module handles all queries to PostgreSQL.

TWO ROLES ARE SERVED HERE:
  1. Relational  → dual-network transit (metro + national rail),
                   availability, fares, bookings, seat selection
  2. Vector      → policy document similarity search (pgvector)

STUDENT TASK
------------
Design your schema in databases/relational/schema.sql, seed it with
skeleton/seed_postgres.py, then implement the query functions below.

Functions prefixed with `query_`  are read-only lookups called by the agent.
Functions prefixed with `execute_` are write operations (booking/cancellation).

The vector functions (query_policy_vector_search, store_policy_document)
are already implemented — do not modify them.
"""

from __future__ import annotations

import json
import random
import string
from datetime import datetime, timezone
from typing import Optional

import bcrypt
import psycopg2
import psycopg2.extras

from skeleton.config import PG_DSN, VECTOR_TOP_K, VECTOR_SIMILARITY_THRESHOLD


def _hash_password(plain: str) -> str:
    """Hash a plain-text password using bcrypt. Returns the hashed string."""
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _verify_password(plain: str, hashed: str) -> bool:
    """Verify a plain-text password against a bcrypt hash."""
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


def _connect():
    """Return a new psycopg2 connection with autocommit enabled."""
    conn = psycopg2.connect(PG_DSN)
    conn.autocommit = True
    return conn


def _gen_booking_id() -> str:
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
    return f"BK-{suffix}"


def _gen_payment_id() -> str:
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
    return f"PM-{suffix}"


# ── Example ───────────────────────────────────────────────────────────────────

def example_query() -> dict:
    """Example: returns the name of the connected database."""
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT current_database() AS db;")
            return dict(cur.fetchone())


# ── NATIONAL RAIL AVAILABILITY ────────────────────────────────────────────────

def query_national_rail_availability(
    origin_id: str,
    destination_id: str,
    travel_date: Optional[str] = None,
) -> list[dict]:
    """
    Return national rail schedules that serve both origin and destination stations
    in the correct order, along with seat occupancy for the requested travel date.

    Args:
        origin_id:       e.g. "NR01"
        destination_id:  e.g. "NR05"
        travel_date:     e.g. "2025-06-01" — used to count bookings; omit for general info
    """
    # We JOIN the stops table twice (once for origin, once for destination) so we can
    # compare stop_order values in a single query — this ensures origin comes before
    # destination on the route and avoids returning reverse-direction schedules.
    # is_pass_through = FALSE filters out stations the train passes without stopping.
    # Fare is computed inline in SQL to avoid a second round-trip to the database.
    sql = """
        SELECT
            s.schedule_id,
            s.line,
            s.service_type,
            s.direction,
            s.first_train_time::text AS first_train_time,
            s.last_train_time::text  AS last_train_time,
            s.frequency_min,
            s.operates_on,
            orig.name  AS origin_name,
            dest.name  AS destination_name,
            o_stop.stop_order          AS origin_stop_order,
            d_stop.stop_order          AS destination_stop_order,
            d_stop.stop_order - o_stop.stop_order AS stops_travelled,
            s.standard_base_fare_usd,
            s.standard_per_stop_rate_usd,
            s.first_base_fare_usd,
            s.first_per_stop_rate_usd,
            ROUND(
                s.standard_base_fare_usd
                + s.standard_per_stop_rate_usd * (d_stop.stop_order - o_stop.stop_order),
            2) AS standard_fare_usd,
            ROUND(
                s.first_base_fare_usd
                + s.first_per_stop_rate_usd * (d_stop.stop_order - o_stop.stop_order),
            2) AS first_fare_usd
        FROM national_rail_schedules s
        JOIN national_rail_schedule_stops o_stop
            ON o_stop.schedule_id = s.schedule_id
           AND o_stop.station_id  = %s
           AND o_stop.is_pass_through = FALSE
        JOIN national_rail_schedule_stops d_stop
            ON d_stop.schedule_id = s.schedule_id
           AND d_stop.station_id  = %s
           AND d_stop.is_pass_through = FALSE
        JOIN national_rail_stations orig ON orig.station_id = %s
        JOIN national_rail_stations dest ON dest.station_id = %s
        WHERE d_stop.stop_order > o_stop.stop_order
        ORDER BY s.first_train_time
    """
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (origin_id, destination_id, origin_id, destination_id))
            rows = [dict(row) for row in cur.fetchall()]

    if travel_date and rows:
        # Count confirmed bookings and derive available_seats for each schedule on that date.
        # Total capacity is estimated as coaches * rows * columns (standard layout).
        TOTAL_SEATS = 80  # 4 coaches × 10 rows × 4 columns = 160, use 80 per fare class
        for row in rows:
            with _connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT COUNT(*) FROM national_rail_bookings
                        WHERE schedule_id = %s AND travel_date = %s AND status = 'confirmed'
                        """,
                        (row["schedule_id"], travel_date),
                    )
                    booked = cur.fetchone()[0]
                    row["bookings_on_date"] = booked
                    row["available_seats"] = max(0, TOTAL_SEATS - booked)

    return rows


def query_national_rail_fare(
    schedule_id: str,
    fare_class: str,
    stops_travelled: int,
) -> Optional[dict]:
    """
    Calculate the fare for a national rail journey.

    Args:
        schedule_id:     e.g. "NR_SCH01"
        fare_class:      "standard" or "first"
        stops_travelled: number of stops between origin and destination (inclusive)

    Returns:
        dict with fare_class, base_fare_usd, per_stop_rate_usd, total_fare_usd
    """
    sql = """
        SELECT
            schedule_id,
            standard_base_fare_usd,
            standard_per_stop_rate_usd,
            first_base_fare_usd,
            first_per_stop_rate_usd
        FROM national_rail_schedules
        WHERE schedule_id = %s
    """
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (schedule_id,))
            row = cur.fetchone()
    if not row:
        return None

    row = dict(row)
    # Fare model: total = base_fare + (per_stop_rate × stops_travelled).
    # Both fare classes share the same formula but use different rate columns,
    # so we select the correct pair here rather than duplicating the arithmetic.
    if fare_class == "first":
        base = float(row["first_base_fare_usd"])
        rate = float(row["first_per_stop_rate_usd"])
    else:
        base = float(row["standard_base_fare_usd"])
        rate = float(row["standard_per_stop_rate_usd"])

    total = round(base + rate * stops_travelled, 2)
    return {
        "schedule_id": schedule_id,
        "fare_class": fare_class,
        "base_fare_usd": base,
        "per_stop_rate_usd": rate,
        "stops_travelled": stops_travelled,
        "total_fare_usd": total,
    }


# ── METRO SCHEDULES & FARE ────────────────────────────────────────────────────

def query_metro_schedules(origin_id: str, destination_id: str) -> list[dict]:
    """
    Return metro schedules that serve both origin and destination in the correct order.

    Args:
        origin_id:       e.g. "MS01"
        destination_id:  e.g. "MS09"
    """
    sql = """
        SELECT
            s.schedule_id,
            s.line,
            s.direction,
            s.first_train_time::text AS first_train_time,
            s.last_train_time::text  AS last_train_time,
            s.frequency_min,
            s.operates_on,
            s.base_fare_usd,
            s.per_stop_rate_usd,
            orig.name AS origin_name,
            dest.name AS destination_name,
            o_stop.stop_order AS origin_stop_order,
            d_stop.stop_order AS destination_stop_order,
            d_stop.stop_order - o_stop.stop_order AS stops_travelled,
            ROUND(
                s.base_fare_usd
                + s.per_stop_rate_usd * (d_stop.stop_order - o_stop.stop_order),
            2) AS total_fare_usd
        FROM metro_schedules s
        JOIN metro_schedule_stops o_stop
            ON o_stop.schedule_id = s.schedule_id
           AND o_stop.station_id  = %s
        JOIN metro_schedule_stops d_stop
            ON d_stop.schedule_id = s.schedule_id
           AND d_stop.station_id  = %s
        JOIN metro_stations orig ON orig.station_id = %s
        JOIN metro_stations dest ON dest.station_id = %s
        WHERE d_stop.stop_order > o_stop.stop_order
        ORDER BY s.line, s.first_train_time
    """
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (origin_id, destination_id, origin_id, destination_id))
            return [dict(row) for row in cur.fetchall()]


def query_metro_fare(schedule_id: str, stops_travelled: int) -> Optional[dict]:
    """
    Calculate the metro fare for a single-ticket journey.

    Args:
        schedule_id:     e.g. "MS_SCH01"
        stops_travelled: number of stops between origin and destination

    Returns:
        dict with base_fare_usd, per_stop_rate_usd, total_fare_usd
    """
    sql = """
        SELECT base_fare_usd, per_stop_rate_usd
        FROM metro_schedules
        WHERE schedule_id = %s
    """
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (schedule_id,))
            row = cur.fetchone()
    if not row:
        return None

    base = float(row["base_fare_usd"])
    rate = float(row["per_stop_rate_usd"])
    return {
        "schedule_id": schedule_id,
        "base_fare_usd": base,
        "per_stop_rate_usd": rate,
        "stops_travelled": stops_travelled,
        "total_fare_usd": round(base + rate * stops_travelled, 2),
    }


# ── SEAT SELECTION ────────────────────────────────────────────────────────────

def query_available_seats(
    schedule_id: str,
    travel_date: str,
    fare_class: str,
) -> list[dict]:
    """
    Return available seats for a national rail journey on a given date.

    Args:
        schedule_id:  e.g. "NR_SCH01"
        travel_date:  e.g. "2025-06-01"
        fare_class:   "standard" or "first"

    Returns:
        List of dicts: {seat_id, coach, row, column}
    """
    # We query already-booked seats first, then subtract them from a generated
    # seat map. This approach avoids relying on the seat_layouts table being
    # fully seeded — the coach/row/column layout is deterministic so we can
    # regenerate it on the fly. First-class uses coaches A-B, standard uses C-F.
    booked_sql = """
        SELECT seat_id FROM national_rail_bookings
        WHERE schedule_id = %s AND travel_date = %s
          AND fare_class = %s AND status = 'confirmed'
    """
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(booked_sql, (schedule_id, travel_date, fare_class))
            booked = {r[0] for r in cur.fetchall()}

    # Generate a standard seat map: coaches A-D, rows 1-10, columns 1-4
    coaches = ["A", "B"] if fare_class == "first" else ["C", "D", "E", "F"]
    seats = []
    for coach in coaches:
        for row in range(1, 11):
            for col in range(1, 5):
                seat_id = f"{coach}{row:02d}{col}"
                if seat_id not in booked:
                    seats.append({
                        "seat_id": seat_id,
                        "coach": coach,
                        "row": row,
                        "column": col,
                    })
    return seats


def auto_select_adjacent_seats(available_seats: list[dict], count: int) -> list[str]:
    """
    Select `count` seats that are as close together as possible (same row preferred,
    then adjacent rows). Returns a list of seat_ids.

    Args:
        available_seats: output of query_available_seats()
        count:           number of seats needed
    """
    if not available_seats or count <= 0:
        return []
    if count >= len(available_seats):
        return [s["seat_id"] for s in available_seats[:count]]

    from collections import defaultdict
    rows: dict[int, list[dict]] = defaultdict(list)
    for seat in available_seats:
        rows[seat["row"]].append(seat)

    for row_seats in sorted(rows.values(), key=lambda s: s[0]["row"]):
        if len(row_seats) >= count:
            return [s["seat_id"] for s in row_seats[:count]]

    sorted_seats = sorted(available_seats, key=lambda s: (s["row"], s["column"]))
    return [s["seat_id"] for s in sorted_seats[:count]]


# ── USER & BOOKING QUERIES ────────────────────────────────────────────────────

def query_user_profile(user_email: str) -> Optional[dict]:
    """Return a user's profile by email."""
    sql = """
        SELECT user_id, full_name, email, phone,
               date_of_birth::text,
               EXTRACT(YEAR FROM date_of_birth)::int AS year_of_birth,
               registered_at::text, is_active
        FROM registered_users
        WHERE email = %s
    """
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (user_email,))
            row = cur.fetchone()
    return dict(row) if row else None


def query_user_bookings(user_email: str) -> dict:
    """
    Return a user's combined booking history (national rail + metro).

    Returns:
        dict with keys 'national_rail' (list) and 'metro' (list)
    """
    user = query_user_profile(user_email)
    if not user:
        return {"national_rail": [], "metro": []}

    user_id = user["user_id"]

    nr_sql = """
        SELECT
            b.booking_id,
            b.schedule_id,
            b.travel_date::text,
            b.departure_time::text,
            b.ticket_type,
            b.fare_class,
            b.coach,
            b.seat_id,
            b.stops_travelled,
            b.amount_usd,
            b.status,
            b.booked_at::text,
            orig.name AS origin_name,
            dest.name AS destination_name,
            b.origin_station_id,
            b.destination_station_id
        FROM national_rail_bookings b
        JOIN national_rail_stations orig ON orig.station_id = b.origin_station_id
        JOIN national_rail_stations dest ON dest.station_id = b.destination_station_id
        WHERE b.user_id = %s
        ORDER BY b.travel_date DESC, b.booked_at DESC
    """
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(nr_sql, (user_id,))
            national_rail = [dict(row) for row in cur.fetchall()]

    return {"national_rail": national_rail, "metro": []}


def query_payment_info(booking_id: str) -> Optional[dict]:
    """Return payment record for a booking or metro trip."""
    sql = """
        SELECT payment_id, booking_id, amount_usd, method, status, paid_at::text
        FROM payments
        WHERE booking_id = %s
    """
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (booking_id,))
            row = cur.fetchone()
    return dict(row) if row else None


# ── TRANSACTIONAL OPERATIONS ──────────────────────────────────────────────────

def execute_booking(
    user_id: str,
    schedule_id: str,
    origin_station_id: str,
    destination_station_id: str,
    travel_date: str,
    fare_class: str,
    seat_id: str,
    ticket_type: str = "single",
) -> tuple[bool, dict | str]:
    """
    Create a national rail booking for a logged-in user.

    Args:
        user_id:                e.g. "RU01" — must match the logged-in user
        schedule_id:            e.g. "NR_SCH01"
        origin_station_id:      e.g. "NR01"
        destination_station_id: e.g. "NR05"
        travel_date:            e.g. "2025-06-01"
        fare_class:             "standard" or "first"
        seat_id:                e.g. "C0101" (or "any" to auto-assign)
        ticket_type:            "single" (default) or "return"

    Returns:
        (True, booking_dict)   on success
        (False, error_message) on failure
    """
    # Get stop orders to calculate stops_travelled
    stops_sql = """
        SELECT o.stop_order AS o_order, d.stop_order AS d_order,
               s.first_train_time::text AS departure_time,
               s.service_type
        FROM national_rail_schedules s
        JOIN national_rail_schedule_stops o
            ON o.schedule_id = s.schedule_id AND o.station_id = %s
        JOIN national_rail_schedule_stops d
            ON d.schedule_id = s.schedule_id AND d.station_id = %s
        WHERE s.schedule_id = %s
          AND d.stop_order > o.stop_order
    """
    conn = psycopg2.connect(PG_DSN)
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(stops_sql, (origin_station_id, destination_station_id, schedule_id))
            stop_row = cur.fetchone()
            if not stop_row:
                return False, "Route not found for the given schedule and stations."

            stops_travelled = stop_row["d_order"] - stop_row["o_order"]
            departure_time = stop_row["departure_time"]

            fare = query_national_rail_fare(schedule_id, fare_class, stops_travelled)
            if not fare:
                return False, "Could not calculate fare."
            amount = fare["total_fare_usd"]

            # Auto-assign seat if requested
            if seat_id.lower() == "any":
                available = query_available_seats(schedule_id, travel_date, fare_class)
                if not available:
                    return False, "No available seats."
                seat_id = available[0]["seat_id"]

            coach = seat_id[0] if seat_id else "C"
            booking_id = _gen_booking_id()
            payment_id = _gen_payment_id()

            cur.execute(
                """
                INSERT INTO national_rail_bookings
                    (booking_id, user_id, schedule_id, origin_station_id,
                     destination_station_id, travel_date, departure_time,
                     ticket_type, fare_class, coach, seat_id, stops_travelled,
                     amount_usd, status)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'confirmed')
                """,
                (booking_id, user_id, schedule_id, origin_station_id,
                 destination_station_id, travel_date, departure_time,
                 ticket_type, fare_class, coach, seat_id, stops_travelled, amount),
            )
            cur.execute(
                """
                INSERT INTO payments (payment_id, booking_id, amount_usd, method, status)
                VALUES (%s, %s, %s, 'card', 'completed')
                """,
                (payment_id, booking_id, amount),
            )
        conn.commit()
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()

    return True, {
        "booking_id": booking_id,
        "payment_id": payment_id,
        "user_id": user_id,
        "schedule_id": schedule_id,
        "origin_station_id": origin_station_id,
        "destination_station_id": destination_station_id,
        "travel_date": travel_date,
        "departure_time": departure_time,
        "fare_class": fare_class,
        "seat_id": seat_id,
        "coach": coach,
        "ticket_type": ticket_type,
        "stops_travelled": stops_travelled,
        "amount_usd": amount,
        "status": "confirmed",
    }


def execute_cancellation(booking_id: str, user_id: str) -> tuple[bool, dict | str]:
    """
    Cancel a national rail booking owned by the given user.

    Calculates the refund amount according to the booking's service type:
      - Normal service: RF001 windows (100% / 75% / 50% / 0%)
      - Express service: RF002 windows (100% / 50% / 0%)

    Args:
        booking_id: e.g. "BK001"
        user_id:    must match the booking's user_id

    Returns:
        (True, result_dict)  with refund_amount_usd and policy note
        (False, error_msg)
    """
    fetch_sql = """
        SELECT b.booking_id, b.user_id, b.amount_usd, b.status,
               b.travel_date, b.booked_at, s.service_type
        FROM national_rail_bookings b
        JOIN national_rail_schedules s ON s.schedule_id = b.schedule_id
        WHERE b.booking_id = %s
    """
    conn = psycopg2.connect(PG_DSN)
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(fetch_sql, (booking_id,))
            booking = cur.fetchone()
            if not booking:
                return False, f"Booking {booking_id} not found."
            if booking["user_id"] != user_id:
                return False, "You are not authorised to cancel this booking."
            if booking["status"] != "confirmed":
                return False, f"Booking is already {booking['status']}."

            amount = float(booking["amount_usd"])
            service_type = booking["service_type"]
            travel_date = booking["travel_date"]
            now = datetime.now(timezone.utc).date()
            days_before = (travel_date - now).days

            # Refund policy differs by service type:
            # - RF002 (express): stricter windows because express seats are harder to resell.
            # - RF001 (normal): more generous because normal services run more frequently.
            # days_before is computed from UTC today to avoid timezone-dependent results.
            if service_type == "express":
                # RF002: express services have tighter cancellation windows
                if days_before >= 7:
                    refund_pct, policy_note = 1.0, "RF002: cancelled 7+ days before travel — 100% refund"
                elif days_before >= 1:
                    refund_pct, policy_note = 0.5, "RF002: cancelled 1–6 days before travel — 50% refund"
                else:
                    refund_pct, policy_note = 0.0, "RF002: cancelled on day of travel — no refund"
            else:
                # RF001: normal services allow partial refunds up to 14 days ahead
                if days_before >= 14:
                    refund_pct, policy_note = 1.0, "RF001: cancelled 14+ days before travel — 100% refund"
                elif days_before >= 7:
                    refund_pct, policy_note = 0.75, "RF001: cancelled 7–13 days before travel — 75% refund"
                elif days_before >= 1:
                    refund_pct, policy_note = 0.5, "RF001: cancelled 1–6 days before travel — 50% refund"
                else:
                    refund_pct, policy_note = 0.0, "RF001: cancelled on day of travel — no refund"

            refund_amount = round(amount * refund_pct, 2)

            cur.execute(
                "UPDATE national_rail_bookings SET status = 'cancelled' WHERE booking_id = %s",
                (booking_id,),
            )
            if refund_amount > 0:
                refund_payment_id = _gen_payment_id()
                cur.execute(
                    """
                    INSERT INTO payments (payment_id, booking_id, amount_usd, method, status)
                    VALUES (%s, %s, %s, 'refund', 'completed')
                    """,
                    (refund_payment_id, booking_id, refund_amount),
                )
        conn.commit()
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()

    return True, {
        "booking_id": booking_id,
        "original_amount_usd": amount,
        "refund_amount_usd": refund_amount,
        "refund_percentage": int(refund_pct * 100),
        "policy_note": policy_note,
        "status": "cancelled",
    }


# ── AUTHENTICATION QUERIES ────────────────────────────────────────────────────

def register_user(
    email: str,
    first_name: str,
    surname: str,
    year_of_birth: int,
    password: str,
    secret_question: str,
    secret_answer: str,
) -> tuple[bool, str]:
    """
    Register a new user.
    Returns (True, user_id) on success or (False, error_message) on failure.
    """
    # Check email uniqueness
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM registered_users WHERE email = %s", (email,))
            if cur.fetchone():
                return False, "Email already registered."

    # Generate user_id: find max existing RU number
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT user_id FROM registered_users WHERE user_id LIKE 'RU%' ORDER BY user_id DESC LIMIT 1")
            row = cur.fetchone()
            if row:
                try:
                    last_num = int(row[0][2:])
                    new_num = last_num + 1
                except ValueError:
                    new_num = 100
            else:
                new_num = 1
            user_id = f"RU{new_num:02d}"

    full_name = f"{first_name} {surname}"
    dob = f"{year_of_birth}-01-01"

    # Hash the password with bcrypt before storing — never store plain text
    hashed_password = _hash_password(password)

    insert_sql = """
        INSERT INTO registered_users
            (user_id, full_name, email, password, date_of_birth,
             secret_question, secret_answer, is_active)
        VALUES (%s, %s, %s, %s, %s, %s, %s, TRUE)
    """
    conn = psycopg2.connect(PG_DSN)
    try:
        with conn.cursor() as cur:
            cur.execute(insert_sql, (
                user_id, full_name, email, hashed_password, dob,
                secret_question, secret_answer.lower().strip(),
            ))
        conn.commit()
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()

    return True, user_id


def login_user(email: str, password: str) -> Optional[dict]:
    """
    Verify credentials. Returns a user dict on success or None on failure.
    Dict keys: user_id, email, full_name, first_name, surname, phone, date_of_birth, is_active.

    Password is verified using bcrypt — the stored hash is never compared directly.
    """
    sql = """
        SELECT user_id, email, full_name, phone,
               date_of_birth::text, is_active, password AS hashed_password
        FROM registered_users
        WHERE email = %s AND is_active = TRUE
    """
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (email,))
            row = cur.fetchone()
    if not row:
        return None

    row = dict(row)
    # Verify the plain-text password against the stored bcrypt hash
    if not _verify_password(password, row.pop("hashed_password")):
        return None

    name_parts = row["full_name"].split(" ", 1)
    row["first_name"] = name_parts[0]
    row["surname"] = name_parts[1] if len(name_parts) > 1 else ""
    return row


def get_user_secret_question(email: str) -> Optional[str]:
    """Return the secret question for a registered email, or None if not found."""
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT secret_question FROM registered_users WHERE email = %s",
                (email,),
            )
            row = cur.fetchone()
    return row[0] if row else None


def verify_secret_answer(email: str, answer: str) -> bool:
    """Return True if the provided answer matches the stored secret answer (case-insensitive)."""
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT secret_answer FROM registered_users WHERE email = %s",
                (email,),
            )
            row = cur.fetchone()
    if not row or not row[0]:
        return False
    return row[0].lower().strip() == answer.lower().strip()


def update_password(email: str, new_password: str) -> bool:
    """Update the password for a user. Hashes with bcrypt before storing. Returns True if updated."""
    # Hash the new password before storing
    hashed = _hash_password(new_password)
    conn = psycopg2.connect(PG_DSN)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE registered_users SET password = %s WHERE email = %s",
                (hashed, email),
            )
            updated = cur.rowcount
        conn.commit()
    except Exception:
        conn.rollback()
        return False
    finally:
        conn.close()
    return updated > 0


# TASK 6 EXTENSION: DELAY RECORDS QUERY ──────────────────────────────────────

def query_active_delays(
    schedule_id: Optional[str] = None,
    station_id: Optional[str] = None,
) -> list[dict]:
    """
    Return delay records filtered by schedule or station.
    Active delays (resolved_at IS NULL) are always returned first so the
    assistant can lead with the most urgent information.

    Args:
        schedule_id: Filter to a specific schedule e.g. 'NR_SCH01' (optional)
        station_id:  Filter to a specific station e.g. 'NR02' (optional)

    Returns:
        List of dicts with delay_id, schedule_id, station_id, station_name,
        delay_minutes, reason, reported_at, resolved_at, and is_active flag.
    """
    # We JOIN national_rail_stations to surface the human-readable station name
    # alongside the station_id — the LLM can then present "Maplewood (NR02)"
    # rather than a bare ID that means nothing to the user.
    # ORDER BY: active delays (NULL resolved_at) first, then most-recently-reported.
    # COALESCE(resolved_at, 'infinity') puts NULLs at the top when ordering DESC.
    sql = """
        SELECT
            d.delay_id,
            d.schedule_id,
            d.station_id,
            s.name AS station_name,
            d.delay_minutes,
            d.reason,
            d.reported_at::text,
            d.resolved_at::text,
            (d.resolved_at IS NULL) AS is_active
        FROM delay_records d
        JOIN national_rail_stations s ON s.station_id = d.station_id
        WHERE (%s IS NULL OR d.schedule_id = %s)
          AND (%s IS NULL OR d.station_id  = %s)
        ORDER BY
            (d.resolved_at IS NULL) DESC,   -- active (NULL) first
            d.reported_at DESC
    """
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (schedule_id, schedule_id, station_id, station_id))
            return [dict(row) for row in cur.fetchall()]


# ── VECTOR / RAG QUERIES — do not modify ─────────────────────────────────────

def query_policy_vector_search(embedding: list[float], top_k: int = VECTOR_TOP_K) -> list[dict]:
    """
    Find the most relevant policy documents for a given query embedding.

    Args:
        embedding: Query vector from llm.embed(user_question)
        top_k:     Number of results to return

    Returns:
        List of dicts with title, category, content, and similarity score
    """
    sql = """
        SELECT
            title,
            category,
            content,
            1 - (embedding <=> %s::vector) AS similarity
        FROM policy_documents
        WHERE 1 - (embedding <=> %s::vector) > %s
        ORDER BY embedding <=> %s::vector
        LIMIT %s
    """
    vec_str = "[" + ",".join(str(x) for x in embedding) + "]"
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (vec_str, vec_str, VECTOR_SIMILARITY_THRESHOLD, vec_str, top_k))
            return [dict(row) for row in cur.fetchall()]


def store_policy_document(
    title: str,
    category: str,
    content: str,
    embedding: list[float],
    source_file: str = "",
) -> int:
    """
    Insert a policy document with its embedding into the database.
    Used by skeleton/seed_vectors.py — students don't need to call this directly.

    Returns:
        The new document's id
    """
    sql = """
        INSERT INTO policy_documents (title, category, content, embedding, source_file)
        VALUES (%s, %s, %s, %s::vector, %s)
        RETURNING id
    """
    vec_str = "[" + ",".join(str(x) for x in embedding) + "]"
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (title, category, content, vec_str, source_file))
            return cur.fetchone()[0]
