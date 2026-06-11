# TASK 6 EXTENSION — Delay Records Feature

## Overview

This extension adds a **service delay reporting system** to TransitFlow.
Passengers can now ask the AI assistant whether their train is running on time,
and the assistant queries a live `delay_records` table to answer.

Two additional graph tools are also wired up:
- `check_service_delays` — queries PostgreSQL delay records
- `get_station_connections` — surfaces direct graph neighbours (already implemented, now agent-callable)

---

## Files Modified or Added

### New Files

| File | Purpose |
|---|---|
| `train-mock-data/delay_records.json` | 6 sample delay records (mix of active and resolved) |
| `TASK6.md` | This file — required for Task 6 eligibility |

### Modified Files

| File | What changed | Key names |
|---|---|---|
| `databases/relational/schema.sql` | Added `delay_records` table + 3 indexes | Table: `delay_records`; Indexes: `idx_delay_records_schedule`, `idx_delay_records_station`, `idx_delay_records_active` |
| `skeleton/seed_postgres.py` | Added `seed_delay_records()` function; called in `main()` | Function: `seed_delay_records` |
| `databases/relational/queries.py` | Added `query_active_delays()` query function | Function: `query_active_delays` |
| `databases/graph/queries.py` | Fixed `query_cheapest_route()` to use `fare_class` for fare estimation | Function: `query_cheapest_route` |
| `skeleton/agent.py` | Imported `query_active_delays`, `query_station_connections`; added `check_service_delays` and `get_station_connections` tool definitions and execution handlers | Tools: `check_service_delays`, `get_station_connections` |

---

## Example Queries (chat UI)

```
Is the NR_SCH01 service delayed today?
```
→ triggers `check_service_delays(schedule_id="NR_SCH01")`

```
Are there any delays at Maplewood (NR02)?
```
→ triggers `check_service_delays(station_id="NR02")`

```
What stations are directly connected to Central Station (NR01)?
```
→ triggers `get_station_connections(station_id="NR01")`

```
What is the cheapest first-class route from NR01 to NR05?
```
→ triggers `find_route(origin_id="NR01", destination_id="NR05", optimise_by="cost")` with `fare_class="first"` — now returns a different `total_fare_usd` than standard class
