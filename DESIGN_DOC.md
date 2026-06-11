# Team[ID]_DESIGN_DOC.md
# TransitFlow — Database Design Document
**Team:** Team[ID]  
**Members:** [Member 1], [Member 2], [Member 3]  
**Date:** June 2026

---

## Section 1 — Entity-Relationship Diagram

The ER diagrams are split into three parts for readability. All three PDFs are included in the repository root.

**Part 1 — Users & Transactions** (`ERD_1_Users_Transactions.pdf`)  
Covers: `registered_users`, `national_rail_bookings`, `payments`, `metro_travels`, `feedback`

**Part 2 — Schedules & Stops** (`ERD_2_Schedules_Stops.pdf`)  
Covers: `metro_schedules`, `metro_schedule_stops`, `national_rail_schedules`, `national_rail_schedule_stops`, `seat_layouts`, `seat_layout_seats`

**Part 3 — Stations & Infrastructure** (`ERD_3_Stations_Infrastructure.pdf`)  
Covers: `metro_stations`, `national_rail_stations`

### Entity Summary

The relational schema covers six domains:

| Domain | Tables |
|--------|--------|
| Infrastructure | `metro_stations`, `national_rail_stations` |
| Schedules | `metro_schedules`, `metro_schedule_stops`, `national_rail_schedules`, `national_rail_schedule_stops` |
| Users & Transactions | `registered_users`, `national_rail_bookings`, `payments` |
| Seat Inventory | `seat_layouts`, `seat_layout_seats` |
| Metro Travel | `metro_travels` |
| Feedback | `feedback` |

### Key Relationships and Cardinality

| Relationship | Cardinality | Notes |
|---|---|---|
| `metro_schedules` → `metro_schedule_stops` | 1:N | One schedule has many stops |
| `national_rail_schedules` → `national_rail_schedule_stops` | 1:N | One schedule has many stops |
| `registered_users` → `national_rail_bookings` | 1:N | One user can have many bookings |
| `national_rail_schedules` → `national_rail_bookings` | 1:N | One schedule can have many bookings |
| `national_rail_bookings` → `payments` | 1:N | One booking can have multiple payments (original + refund) |
| `seat_layouts` → `seat_layout_seats` | 1:N | One layout contains many seats |
| `metro_stations` ↔ `national_rail_stations` | 1:1 (optional) | Interchange stations only |

---

## Section 2 — Normalisation Justification

### 2.1 Third Normal Form (3NF) Design Decision — Schedule Stops

The most significant normalisation decision was separating schedule stop sequences into dedicated junction tables (`metro_schedule_stops` and `national_rail_schedule_stops`) rather than storing them as an array column on the schedule table.

**Why this achieves 3NF:**

If stops were stored as a JSONB array in `metro_schedules`, the `stop_order` and `travel_time_from_origin_min` for each station would be functionally dependent on both `(schedule_id, station_id)` — a composite key — not on `schedule_id` alone. Storing them inline would violate 2NF because the stop attributes cannot be keyed on the schedule alone.

By creating a separate table:
```sql
CREATE TABLE metro_schedule_stops (
    schedule_id VARCHAR(20) REFERENCES metro_schedules(schedule_id),
    station_id  VARCHAR(20) REFERENCES metro_stations(station_id),
    stop_order  INTEGER NOT NULL,
    travel_time_from_origin_min INTEGER NOT NULL,
    PRIMARY KEY (schedule_id, station_id)
);
```
Each non-key attribute (`stop_order`, `travel_time_from_origin_min`) depends on the full composite key `(schedule_id, station_id)`, satisfying 2NF and 3NF.

This design also enables efficient SQL queries that check whether origin appears before destination on a route by comparing `stop_order` values directly, without parsing JSON arrays.

### 2.2 Deliberate De-normalisation — Fare Rates on Schedule Table

Fares are stored directly on `national_rail_schedules` (`standard_base_fare_usd`, `standard_per_stop_rate_usd`, `first_base_fare_usd`, `first_per_stop_rate_usd`) rather than in a separate `fare_rules` table.

**Justification:** This is a deliberate de-normalisation trade-off. In a production system, fares might vary by season or by individual route segment, requiring a separate table. However, in this system the fare model is uniform per schedule (a simple `base + rate × stops` formula), and splitting it out would add join complexity without any query benefit. The fare columns depend directly on `schedule_id` with no transitive dependency, so 3NF is still satisfied.

### 2.3 Primary Key Design Decision — VARCHAR over SERIAL or UUID

We chose `VARCHAR(20)` primary keys (e.g., `"RU01"`, `"NR_SCH01"`) rather than `SERIAL` or `UUID`.

**Justification:** The mock dataset provides pre-defined string identifiers that carry semantic meaning. Using `SERIAL` would produce auto-incremented integers that mismatch the seed files, breaking idempotent seeding. Using `UUID` would add 128-bit key overhead and complicate human-readable lookups. `VARCHAR` aligns with the natural keys in the source data and preserves semantic readability.

### 2.4 Delete Strategy — ON DELETE RESTRICT

All foreign keys use `ON DELETE RESTRICT` throughout the schema.

**Justification:** For a commercial transit ticketing system, financial records (`payments`), operational records (`bookings`), and infrastructure records (`schedules`, `stations`) must never be silently deleted through cascade. `ON DELETE RESTRICT` enforces explicit cleanup — a parent row cannot be deleted while child records reference it, preventing orphaned financial audit trails or broken schedule references.

### 2.5 Password Hashing — bcrypt

Passwords are hashed using **bcrypt** before storage. The implementation in `register_user()`:

```python
import bcrypt

def _hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

def _verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
```

**Why bcrypt over MD5 or SHA-1:**

MD5 and SHA-1 are general-purpose hash functions designed for speed. An attacker with GPU hardware can compute billions of MD5 hashes per second, making brute-force attacks practical. bcrypt is a **key-derivation function** with an adjustable cost factor that deliberately slows computation — each hash takes ~100ms on modern hardware, making exhaustive attacks infeasible even with powerful hardware.

**How salt prevents rainbow-table attacks:**

`bcrypt.gensalt()` generates a cryptographically random 128-bit salt for every registration. The salt is embedded in the stored hash string. Because two users with the same password produce completely different hashes, pre-computed rainbow tables (which map common passwords to their hashes) are useless — the attacker would need to recompute the entire table for every unique salt. Even if the database is compromised, each password must be cracked individually.

---

## Section 3 — Graph Database Design Rationale

### 3.1 What Is Stored as Nodes, Relationships, and Properties

**Nodes** represent physical entities that exist independently in the real world:

| Label | Properties | Rationale |
|---|---|---|
| `MetroStation` | `station_id`, `name`, `lines`, `is_interchange` | Stations are discrete, identifiable locations — natural graph nodes |
| `NationalRailStation` | `station_id`, `name`, `lines`, `is_interchange` | Same rationale; separate label allows network-specific queries |

Separate labels for metro and rail stations allow queries to be scoped to one network without a property filter. This is more efficient than a single `Station` label with a `network` property.

**Relationships** represent physical connections between stations:

| Type | Properties | Rationale |
|---|---|---|
| `METRO_LINK` | `line`, `travel_time_min` | Directed edge between adjacent metro stations on the same line |
| `RAIL_LINK` | `line`, `travel_time_min` | Directed edge between adjacent national rail stations |
| `INTERCHANGE_TO` | *(none)* | Undirected edge connecting a metro station to its co-located rail station |

`travel_time_min` is stored on the relationship (edge) rather than on nodes because it is a property of the *connection*, not of either station individually.

**Properties** on relationships serve as edge weights for Dijkstra-based routing. Storing `travel_time_min` directly on the edge means the pathfinding algorithm can read it without additional lookups.

### 3.2 Why Graph Database Is Better Than Relational for Routing

**The relational approach to shortest-path would require recursive CTEs:**

```sql
-- Finding shortest path in SQL requires recursive CTEs that accumulate path sets
WITH RECURSIVE paths AS (
    SELECT origin_id, destination_id, travel_time_min, ARRAY[origin_id] AS visited
    FROM rail_links WHERE origin_id = 'NR01'
    UNION ALL
    SELECT p.origin_id, l.destination_id, p.travel_time_min + l.travel_time_min,
           p.visited || l.destination_id
    FROM paths p JOIN rail_links l ON p.destination_id = l.origin_id
    WHERE NOT l.destination_id = ANY(p.visited)
)
SELECT * FROM paths WHERE destination_id = 'NR05' ORDER BY travel_time_min LIMIT 1;
```

This query scales poorly: the database must enumerate all possible paths and maintain growing `visited` arrays in memory, resulting in O(V + E) memory usage and quadratic time in the worst case for dense graphs.

**The graph approach uses APOC Dijkstra natively:**

```cypher
CALL apoc.algo.dijkstra(origin, dest, 'RAIL_LINK', 'travel_time_min')
YIELD path, weight
```

Neo4j's Dijkstra implementation operates directly on the pointer-linked graph structure. Each node stores direct references to its neighbours, so traversal is O(1) per edge rather than requiring a join. The algorithm maintains a priority queue of shortest distances and terminates as soon as the destination is reached — no need to enumerate all paths.

For the delay ripple query (`query_delay_ripple`), a graph naturally expresses "all stations within N hops" as a variable-length pattern `(start)-[*1..N]-(affected)`, whereas SQL would require N self-joins or a deeply nested recursive CTE.

### 3.3 Query Types Enabled by the Graph Model

**Query 1 — Shortest route (Dijkstra by travel time):**
The `METRO_LINK` and `RAIL_LINK` edges store `travel_time_min` as a weight. APOC Dijkstra traverses these edges and returns the minimum-weight path. This is expressed in one `CALL` statement and would require 20+ lines of recursive SQL.

**Query 2 — Cross-network interchange path:**
The `INTERCHANGE_TO` relationship connects `MetroStation` nodes to `NationalRailStation` nodes. A single Cypher pattern `(origin)-[*..20]-(dest)` traverses both network types and both relationship types seamlessly. In a relational model, this would require a union of multiple self-join queries across two separate station tables with a manual interchange join table.

**Query 3 — Alternative routes avoiding a closed station:**
The `NONE(n IN nodes(p) WHERE n.station_id = $avoid_id)` clause filters entire paths in one expression. In SQL, excluding a node from all possible paths would require adding `NOT EXISTS` subqueries for every intermediate step.

### 3.4 Node Identity

Each node is uniquely identified by `station_id` (e.g., `"MS01"`, `"NR03"`). This property was chosen because:
- It matches the primary key in the PostgreSQL relational tables, enabling cross-database lookups
- It carries semantic meaning (prefix `MS` = metro, `NR` = national rail)
- It is stable — station IDs do not change when names are updated

`MERGE` statements in `seed_neo4j.py` use `station_id` as the match key, ensuring idempotent seeding.

---

## Section 4 — Vector / RAG Design

### 4.1 What Is Embedded and Why Cosine Similarity

The four policy document files are embedded and stored in the `policy_documents` table:
- `refund_policy.json` — cancellation and delay compensation rules
- `ticket_types.json` — descriptions of fare types
- `booking_rules.json` — booking terms and conditions
- `travel_policies.json` — luggage, pets, bicycle policies

Each document entry is converted to a dense vector (embedding) using the `nomic-embed-text` model via Ollama and stored in a `vector(768)` column.

**Why cosine similarity is appropriate:**

Cosine similarity measures the angle between two vectors in high-dimensional space, making it **magnitude-independent**. Because embedding vectors represent the directional meaning of text rather than its length or frequency, two documents with the same semantic content will point in the same direction regardless of how long or short they are. A query like "delayed 45 minutes refund" and a document about "compensation for delays over 30 minutes" will have vectors pointing in similar directions, even though no exact keywords are shared. Euclidean distance would be distorted by vector magnitude, producing worse semantic matches.

### 4.2 Full RAG Pipeline

```
User question
     │
     ▼
1. Query Embedding
   llm.embed("delayed 45 minutes refund")
   → 768-dimensional vector [0.12, -0.34, ...]
     │
     ▼
2. Similarity Search (pgvector)
   SELECT title, content,
          1 - (embedding <=> query_vector) AS similarity
   FROM policy_documents
   ORDER BY similarity DESC LIMIT 3
   → Returns top 3 most semantically relevant policy documents
     │
     ▼
3. Context Injection into LLM Prompt
   "Using the following policy documents: [RF005: delays of 30–59 min...]
    Answer the user's question: [delayed 45 minutes refund]"
     │
     ▼
4. LLM Generates Answer
   "Under policy RF005, a 30–59 minute delay entitles you to a 50% refund..."
```

### 4.3 Embedding Dimension and Provider Switching

Our implementation uses **Ollama with `nomic-embed-text`**, which produces **768-dimensional** vectors. The schema declares:

```sql
embedding vector(768)
```

If the provider is switched to Gemini after seeding, the embedding model changes to `text-embedding-004`, which produces **3072-dimensional** vectors. The stored 768-dimension vectors become **incompatible** with new 3072-dimension query vectors — the `<=>` cosine distance operator requires both vectors to have identical dimensions, and pgvector will raise a dimension mismatch error. The entire vector table must be dropped, the schema updated to `vector(3072)`, and all documents re-embedded using the new model before the RAG pipeline can function again.

---

## Section 5 — AI Tool Usage Evidence

### Example 1 — Choosing NULL Sentinel over Status Enum for delay_records

**Context:** While designing the `delay_records` table for the Task 6 extension, we needed a way to distinguish active (unresolved) delays from historical ones. We debated between a `status` VARCHAR column (`'active'` / `'resolved'`) and a nullable `resolved_at` timestamp.

**Prompt:**
> "I'm designing a delay_records table. Should I use a status VARCHAR column with values 'active' and 'resolved', or a resolved_at TIMESTAMPTZ column (NULL = still active)? I need to query only active delays frequently and also record when a delay was resolved."

**Outcome:** The AI recommended `resolved_at TIMESTAMPTZ` with `NULL` representing an active delay. Its key argument was that the timestamp approach stores more information (we get the resolution time for free), and it enables a PostgreSQL partial index `WHERE resolved_at IS NULL` that only indexes active rows. As old delays are resolved, the index shrinks rather than growing without bound. A status enum would require a full-table scan or a standard index on the column, which would include all historical rows. We adopted this design in `schema.sql` and it produced the partial index `idx_delay_records_active`.

---

### Example 2 — Writing the Active-First Ordering in query_active_delays

**Context:** We wanted `query_active_delays` to return active (unresolved) delays before historical ones, so the AI assistant leads with the most urgent information. The challenge was ordering NULL values first in PostgreSQL without a CASE statement.

**Prompt:**
> "In PostgreSQL, I have a column resolved_at TIMESTAMPTZ that is NULL for active records. I want to ORDER BY: NULL rows first, then rows ordered by reported_at descending. What is the most concise way to write this ORDER BY clause?"

**Outcome:** The AI suggested `ORDER BY (d.resolved_at IS NULL) DESC, d.reported_at DESC`. In PostgreSQL, the expression `(d.resolved_at IS NULL)` evaluates to a boolean — TRUE (1) for active records, FALSE (0) for resolved. Ordering DESC puts TRUE first. We adopted this directly in `databases/relational/queries.py:query_active_delays` and confirmed in pgAdmin that active delays always appear at the top of results regardless of their `reported_at` timestamp.

---

### Example 3 — Fixing query_cheapest_route to Respect fare_class

**Context:** The `query_cheapest_route` function accepted a `fare_class` parameter but always returned the same `total_fare_usd` because the graph edges store `travel_time_min` but not fare. The original implementation ignored `fare_class` entirely, so standard and first-class queries returned identical fares.

**Prompt:**
> "My query_cheapest_route function takes fare_class='standard' or 'first' but the Neo4j graph edges only store travel_time_min. The fare is not on the graph. How should I estimate the fare differently for each class, given I know the number of hops in the returned path?"

**Outcome:** The AI suggested applying the TransitFlow linear pricing model post-query: `total = base_fare + per_hop_rate × num_hops`, with different constants per class. It proposed standard: base $1.50, rate $0.75/hop and first: base $3.00, rate $1.50/hop. This made `fare_class` visibly affect the result without requiring fare data on graph edges. We implemented this in `databases/graph/queries.py:query_cheapest_route` and verified that a 4-hop NR01→NR05 journey returns $4.50 standard vs $9.00 first class.

---

### Example 4 — Debugging Cypher Label Filter Syntax in Neo4j 5

**Context:** While implementing `query_interchange_path`, the AI-generated Cypher WHERE clause combined a label check and a property filter inside the same `{}` block, which is invalid in Neo4j 5.

**Prompt:**
> "Write a Cypher query that matches a node which is either a MetroStation or NationalRailStation, filtering by station_id. Here is my attempt: MATCH (station {station_id: $id}) WHERE station:MetroStation OR station:NationalRailStation"

**Outcome:** The AI initially generated:
```cypher
WHERE (station:MetroStation {station_id: $id} OR station:NationalRailStation {station_id: $id})
```
This caused `CypherSyntaxError: Invalid input 'OR'`. The property filter `{station_id: $id}` cannot appear inside a label-OR expression in Neo4j 5. The correct form separates the two concerns:
```cypher
WHERE (station:MetroStation OR station:NationalRailStation)
  AND station.station_id = $id
```
This is used in `query_interchange_path` and `query_delay_ripple` in `databases/graph/queries.py`. The error highlighted that AI-generated Cypher must be tested against the target Neo4j version — syntax rules differ between versions.

---

### Example 5 — bcrypt Password Hashing for seed_users and register_user

**Context:** Initial seeding inserted user passwords as plain text. After reviewing the rubric security requirement, we needed to hash passwords both in `seed_postgres.py` (for seeding from JSON) and in `databases/relational/queries.py` (for the live `register_user` and `login_user` functions).

**Prompt:**
> "We store user passwords from a JSON seed file and also accept new registrations at runtime. Rewrite both the seeder and the register_user/login_user functions to use bcrypt. Show how gensalt and hashpw work together on registration, and how checkpw works on login."

**Outcome:** The AI provided the correct implementation in both files. In `seed_postgres.py:seed_users`, each JSON password is hashed at seed time with `bcrypt.hashpw(u["password"].encode(), bcrypt.gensalt()).decode()`. In `queries.py`, `_hash_password` and `_verify_password` are used by `register_user` and `login_user` respectively. The AI also explained why `gensalt()` must be called once per registration (not reused across users) — reuse would defeat the per-user salt that prevents rainbow table attacks.

---

## Section 6 — Reflection & Trade-offs

### 6.1 Design Decision 1 — VARCHAR Primary Keys

We chose `VARCHAR(20)` primary keys over `SERIAL` integers or `UUID`.

**Reasoning:** The source mock data uses structured string identifiers (`"RU01"`, `"NR_SCH01"`, `"MS01"`) that carry semantic meaning and serve as natural foreign keys across the JSON seed files. Using `SERIAL` would produce auto-incremented integers that mismatch the seed data at insert time, breaking the `ON CONFLICT DO NOTHING` idempotent seeding pattern. Using `UUID` adds 128-bit key overhead and produces opaque identifiers that are harder to trace when debugging pgAdmin output or reading log files. The trade-off is that string comparison is marginally slower than integer comparison at scale, but for a transit system of this size the difference is negligible and the readability benefit is clear.

### 6.2 Design Decision 2 — ON DELETE RESTRICT Throughout

We applied `ON DELETE RESTRICT` to every foreign key rather than `ON DELETE CASCADE`.

**Reasoning:** In a commercial ticketing system, cascade deletion is dangerous. If a `national_rail_schedules` row were accidentally deleted, `CASCADE` would silently remove all child `national_rail_bookings` and `payments` rows — destroying the financial audit trail. `RESTRICT` forces explicit cleanup: the application must cancel all associated bookings before a schedule can be removed, making data loss an intentional programmatic choice rather than an accidental side effect. The trade-off is slightly more complex application logic for deletion flows, which is acceptable given the higher data integrity requirement for financial records.

### 6.3 Design Decision 3 — NULL Sentinel for Active Delays

For the `delay_records` table, we chose `resolved_at TIMESTAMPTZ DEFAULT NULL` to represent delay state rather than a `status VARCHAR` enum.

**Reasoning:** A nullable timestamp stores more information than a boolean-equivalent enum — we get the resolution timestamp for free in the same column. It also enables a PostgreSQL partial index `WHERE resolved_at IS NULL` that physically only indexes the active (unresolved) subset of the table. As delays are resolved over time, the index remains small because resolved rows are excluded. A status enum would require a standard full-column index that grows with every historical delay record. The trade-off is that the convention (`NULL = active`) is less immediately obvious to a reader than an explicit `status = 'active'`, which is why we added a comment on the column in `schema.sql`.

### 6.4 What Would Be Different in a Production System

In production, we would replace the single `schema.sql` file with **incremental migration files** managed by Alembic or Flyway. The current approach requires wiping and recreating the entire database on every schema change (`docker compose down -v`), which is only safe in development. In production, schema changes must be applied incrementally without data loss — adding columns with `ALTER TABLE`, creating indexes `CONCURRENTLY` to avoid holding table locks on a live system, and providing a rollback migration for every forward migration.

Additionally, passwords would use **argon2id** instead of bcrypt in a production system. While bcrypt is secure and widely used, argon2id won the Password Hashing Competition (2015) and offers configurable memory hardness, making it resistant to GPU and ASIC-based brute-force attacks in ways bcrypt cannot match. The switch would be a single-library swap (`passlib[argon2]`) with the same hash-and-verify API pattern already in place in `queries.py`.

---

## Section 7 — Task 6 Extension: Delay Records Feature

### 7.1 Motivation

Before this extension, a user asking *"Is the NR_SCH01 service running on time?"* or *"Are there any delays at Maplewood?"* would receive no useful answer — the assistant had no access to operational delay data. The only workaround would be for the LLM to hallucinate a response or deflect entirely, both of which are unacceptable for a transit system.

This extension adds a `delay_records` table that stores operator-reported service disruptions, a `query_active_delays` query function, and two new agent tools (`check_service_delays`, `get_station_connections`). Together they give the assistant the ability to:

1. Answer real-time delay queries per schedule (`"Is NR_SCH01 delayed?"`)
2. Answer station-specific disruption queries (`"Any issues at Maplewood (NR02)?"`)
3. Surface direct station neighbours from the graph (`"What stations connect to Central Station?"`) — a gap in the existing toolset that this extension also closes.

The feature adds value by making the assistant actionable at the moment a passenger most needs help: when something is going wrong with their journey. Without live delay information, the assistant is useful only for planning, not for real-time travel support.

Additionally, `query_cheapest_route` was corrected to apply different pricing constants for `fare_class="first"` versus `fare_class="standard"`, ensuring that a first-class route query returns a meaningfully different `total_fare_usd` than a standard query on the same path.

---

### 7.2 Database Changes

#### New Table — delay_records (schema.sql)

```sql
CREATE TABLE delay_records (
    delay_id      VARCHAR(20) PRIMARY KEY,
    -- FK to the affected schedule; RESTRICT prevents deleting a schedule with delay history
    schedule_id   VARCHAR(20) NOT NULL REFERENCES national_rail_schedules(schedule_id) ON DELETE RESTRICT,
    -- FK to the station where the delay was first reported
    station_id    VARCHAR(20) NOT NULL REFERENCES national_rail_stations(station_id) ON DELETE RESTRICT,
    -- Delay length in minutes; must be positive (a 0-minute delay is not a delay)
    delay_minutes INTEGER     NOT NULL CHECK (delay_minutes > 0),
    -- Human-readable cause reported by the operator (nullable — reason may not always be known)
    reason        TEXT,
    reported_at   TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    -- NULL means the delay is still active; set to a timestamp when the disruption is resolved
    resolved_at   TIMESTAMPTZ
);

-- Supports fast lookups of all delays for a given schedule
CREATE INDEX idx_delay_records_schedule ON delay_records(schedule_id);
-- Supports fast lookups of all delays affecting a given station
CREATE INDEX idx_delay_records_station  ON delay_records(station_id);
-- Partial index — only indexes active (unresolved) rows, keeping the index small over time
CREATE INDEX idx_delay_records_active   ON delay_records(reported_at) WHERE resolved_at IS NULL;
```

**Design note:** `resolved_at IS NULL` acts as the active-delay sentinel. This design was chosen over a `status` enum because it stores the resolution timestamp for free and enables the partial index above (see Section 6.3).

#### New Seed Data — delay_records.json (6 records)

Three active delays (DL001, DL003, DL005) and three resolved delays (DL002, DL004, DL006) covering both schedules NR_SCH01–NR_SCH05 and stations NR02–NR08.

#### Modified Graph Query — query_cheapest_route (databases/graph/queries.py)

The fare estimation logic was updated to apply class-specific constants:

```python
if fare_class.lower() == "first":
    base_fare    = 3.00
    per_hop_rate = 1.50
else:                        # standard (default)
    base_fare    = 1.50
    per_hop_rate = 0.75

total_fare = round(base_fare + per_hop_rate * num_hops, 2)
```

---

### 7.3 New Query Functions and Agent Tools

#### query_active_delays (databases/relational/queries.py)

```python
def query_active_delays(
    schedule_id: Optional[str] = None,
    station_id: Optional[str] = None,
) -> list[dict]:
```

Core SQL — active delays returned first via boolean ordering:

```sql
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
    (d.resolved_at IS NULL) DESC,   -- active (NULL) rows first
    d.reported_at DESC
```

The `(%s IS NULL OR d.schedule_id = %s)` pattern allows a single query to handle all four filter combinations (no filter, filter by schedule, filter by station, filter by both) without branching in Python.

#### Agent tools added to skeleton/agent.py

| Tool name | Triggers | Parameters |
|---|---|---|
| `check_service_delays` | "Is my train delayed?", "Any disruptions at NR02?" | `schedule_id?`, `station_id?` |
| `get_station_connections` | "What stations connect to NR01?", "Which lines pass through Maplewood?" | `station_id` |

---

### 7.4 Example Queries with Expected Output

#### Query 1 — Active delays on NR_SCH01

Run in pgAdmin → Query Tool:

```sql
SELECT
    d.delay_id,
    d.schedule_id,
    s.name AS station_name,
    d.delay_minutes,
    d.reason,
    d.reported_at,
    d.resolved_at,
    (d.resolved_at IS NULL) AS is_active
FROM delay_records d
JOIN national_rail_stations s ON s.station_id = d.station_id
WHERE d.schedule_id = 'NR_SCH01'
ORDER BY (d.resolved_at IS NULL) DESC, d.reported_at DESC;
```

**Expected output (2 rows — both active):**

| delay_id | schedule_id | station_name | delay_minutes | reason | reported_at | resolved_at | is_active |
|---|---|---|---|---|---|---|---|
| DL003 | NR_SCH01 | Old Town Junction | 45 | Flooding on track near Old Town Junction | 2026-06-11 07:30:00+00 | `null` | `true` |
| DL001 | NR_SCH01 | Maplewood | 15 | Signal failure at Maplewood | 2026-06-10 08:15:00+00 | `null` | `true` |

Both records are active (`resolved_at IS NULL`). DL003 appears first because it was reported more recently.

---

#### Query 2 — All delays at station NR02 (Maplewood)

```sql
SELECT d.delay_id, d.schedule_id, d.delay_minutes, d.reason,
       d.reported_at, d.resolved_at,
       (d.resolved_at IS NULL) AS is_active
FROM delay_records d
WHERE d.station_id = 'NR02'
ORDER BY (d.resolved_at IS NULL) DESC, d.reported_at DESC;
```

**Expected output (1 row):**

| delay_id | schedule_id | delay_minutes | reason | reported_at | resolved_at | is_active |
|---|---|---|---|---|---|---|
| DL001 | NR_SCH01 | 15 | Signal failure at Maplewood | 2026-06-10 08:15:00+00 | `null` | `true` |

---

#### Query 3 — get_station_connections for NR01 (Neo4j Browser)

```cypher
MATCH (station)-[r]->(connected)
WHERE (station:MetroStation OR station:NationalRailStation)
  AND station.station_id = 'NR01'
RETURN connected.station_id AS station_id,
       connected.name AS name,
       TYPE(r) AS relationship_type,
       r.line AS line,
       r.travel_time_min AS travel_time_min
ORDER BY travel_time_min
```

**Expected output (2 rows — NR01 is a junction station on both NR1 and NR2):**

| station_id | name | relationship_type | line | travel_time_min |
|---|---|---|---|---|
| NR02 | Maplewood | RAIL_LINK | NR1 | 12 |
| NR06 | Bridgeport | RAIL_LINK | NR2 | 14 |

---

#### Query 4 — Cheapest route NR01 → NR05: standard vs first class (chat UI)

Via the agent `find_route` tool with `optimise_by="cost"`:

- **Standard class** (`fare_class="standard"`): path NR01 → NR02 → NR03 → NR04 → NR05 (4 hops) → `total_fare_usd = $1.50 + 4 × $0.75 = $4.50`
- **First class** (`fare_class="first"`): same path → `total_fare_usd = $3.00 + 4 × $1.50 = $9.00`

The two queries return the same physical route but different fares, confirming that the `fare_class` fix correctly differentiates pricing.

---

### 7.5 Testing Evidence

#### pgAdmin — All 6 delay records seeded correctly

Running `SELECT COUNT(*) FROM delay_records;` after `python skeleton/seed_postgres.py` returns **6**, matching the 6 entries in `train-mock-data/delay_records.json`.

Running `SELECT delay_id, resolved_at IS NULL AS is_active FROM delay_records ORDER BY delay_id;` confirms 3 active (DL001, DL003, DL005) and 3 resolved (DL002, DL004, DL006):

| delay_id | is_active |
|---|---|
| DL001 | `true` |
| DL002 | `false` |
| DL003 | `true` |
| DL004 | `false` |
| DL005 | `true` |
| DL006 | `false` |

#### Partial index confirmed active

Running `\d delay_records` in psql shows all three indexes, including the partial index:

```
Indexes:
  "delay_records_pkey"         PRIMARY KEY, btree (delay_id)
  "idx_delay_records_active"   btree (reported_at) WHERE resolved_at IS NULL
  "idx_delay_records_schedule" btree (schedule_id)
  "idx_delay_records_station"  btree (station_id)
```

#### Chat UI — check_service_delays tool triggered

Typing `"Is the NR_SCH01 service delayed today?"` into the chat with the debug panel open shows:

```
[tool_call] check_service_delays(schedule_id="NR_SCH01")
[tool_result]
  delay_id: DL003  station: Old Town Junction  delay_minutes: 45  is_active: true
  delay_id: DL001  station: Maplewood          delay_minutes: 15  is_active: true
```

The assistant responds: *"The NR_SCH01 service is currently experiencing two active delays: 45 minutes at Old Town Junction (flooding on track) and 15 minutes at Maplewood (signal failure). Both are unresolved as of the latest report."*

#### Chat UI — get_station_connections tool triggered

Typing `"What stations are directly connected to Central Station (NR01)?"` shows:

```
[tool_call] get_station_connections(station_id="NR01")
[tool_result]
  Maplewood (NR02) — RAIL_LINK — NR1 — 12 min
  Bridgeport (NR06) — RAIL_LINK — NR2 — 14 min
```
