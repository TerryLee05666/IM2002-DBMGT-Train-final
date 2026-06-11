# Team[ID]_DESIGN_DOC.md
# TransitFlow — Database Design Document
**Team:** Team[ID]  
**Members:** [Member 1], [Member 2], [Member 3]  
**Date:** June 2026

---

## Section 1 — Entity-Relationship Diagram

The ER diagrams are split into three parts for readability. All three PDFs are included in the repository root.

**Part 1 — Users & Transactions** 
**Part 2 — Schedules & Stops** 
**Part 3 — Stations & Infrastructure** 

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

### Example 1 — Schema Design for Schedule Stops

**Context:** We needed to decide whether to store metro schedule stops as a JSONB array inside the `metro_schedules` table or in a separate normalised table.

**Prompt:**
> "I have a metro_schedules table. Each schedule has an ordered list of station stops with travel times. Should I store stops as a JSONB array column or in a separate junction table? My queries need to check whether station A comes before station B on a route."

**Outcome:** The AI recommended a separate junction table with `stop_order` and `travel_time_from_origin_min` columns, explaining that a JSONB array would require expensive array operations to compare positions, whereas a junction table allows a simple `WHERE d_stop.stop_order > o_stop.stop_order` comparison. We adopted this design and it enabled clean, efficient SQL for route queries.

---

### Example 2 — Cypher Syntax Error Correction

**Context:** While implementing `query_station_connections`, the AI generated a Cypher WHERE clause that caused a syntax error in Neo4j 5.

**Prompt:**
> "Implement query_station_connections using this graph schema: MetroStation and NationalRailStation nodes. Find all direct connections from a given station ID."

**Outcome:** The AI generated:
```cypher
WHERE (station:MetroStation {station_id: $id} OR station:RailStation {station_id: $id})
```
This caused `CypherSyntaxError: Invalid input 'OR': expected ')' or 'WHERE'`. The AI had used a syntax pattern not supported in Neo4j 5. We identified the error from the exception message and corrected it to:
```cypher
WHERE (station:MetroStation OR station:NationalRailStation)
  AND station.station_id = $id
```
This is an example where AI output required debugging — the property filter cannot be combined with the OR label check inside a single `{}` block in Neo4j 5.

---

### Example 3 — bcrypt Password Hashing Implementation

**Context:** We needed to replace plain-text password storage with a secure hashing algorithm after reviewing the grading rubric.

**Prompt:**
> "Our register_user and login_user functions store and compare passwords as plain text. Rewrite them to use bcrypt. Show how to hash on registration and verify on login."

**Outcome:** The AI correctly provided the bcrypt implementation using `hashpw` with `gensalt()` for registration and `checkpw` for login verification. The output was accurate and we adopted it directly. We also updated `seed_users` in `seed_postgres.py` to hash the plain-text passwords from the JSON seed files before inserting them.

---

### Example 4 — Debugging Metro Schedule Stops Not Seeding

**Context:** After running `seed_postgres.py`, the `metro_schedule_stops` table had 0 rows despite the schedules table being populated correctly.

**Prompt:**
> "My seed_metro_schedules function inserts 8 metro schedules but 0 stops. The JSON has a 'stops_in_order' field. Here is the seeder code: [pasted code using d.get('stops', [])]"

**Outcome:** The AI immediately identified the bug: the code was looking for a field named `stops` but the JSON used `stops_in_order`. This is the kind of error where the AI's pattern recognition was faster than manual inspection. After the fix, 50 stop rows were correctly inserted.

---

### Example 5 — RAG Pipeline Design

**Context:** We needed to understand how the pgvector similarity search integrated with the LLM to answer policy questions.

**Prompt:**
> "Explain the full RAG pipeline in our system: how does a user's question about refund policy get answered using pgvector and the LLM?"

**Outcome:** The AI described all four stages (embed query → similarity search → inject context → generate answer) clearly. This directly informed Section 4 of this document. The explanation was accurate and matched our implementation in `seed_vectors.py` and `agent.py`.

---

## Section 6 — Reflection & Trade-offs

### 6.1 Design Decision 1 — VARCHAR Primary Keys

We chose `VARCHAR(20)` primary keys over `SERIAL` integers or `UUID`.

**Reasoning:** The source mock data uses structured string identifiers (`"RU01"`, `"NR_SCH01"`, `"MS01"`) that carry semantic meaning and serve as natural foreign keys across the JSON seed files. Using `SERIAL` would produce integers that mismatch the seed data, breaking idempotent re-seeding. Using `UUID` adds 128-bit key overhead and makes human-readable queries (e.g., looking up `"BK001"` in pgAdmin) harder. The trade-off is that string comparison is marginally slower than integer comparison at large scale, but this is negligible for a transit system of this size.

### 6.2 Design Decision 2 — ON DELETE RESTRICT Throughout

We applied `ON DELETE RESTRICT` to every foreign key rather than using `ON DELETE CASCADE`.

**Reasoning:** In a commercial ticketing system, cascade deletion is dangerous. If a schedule were accidentally deleted, `CASCADE` would silently remove all associated bookings and payments — destroying the financial audit trail. `RESTRICT` forces explicit cleanup: the application must cancel bookings before removing a schedule, making data loss an explicit programmatic choice rather than an accidental side effect. The trade-off is slightly more complex application logic for deletion operations, which is acceptable given the higher data integrity requirement.

### 6.3 What Would Be Different in a Production System

In production, we would replace the single `schema.sql` file with **incremental migration files** managed by a tool like Alembic or Flyway. The current approach wipes and recreates the entire database on every schema change (`docker compose down -v`), which is only safe in development. In production with real user data, schema changes must be applied incrementally without data loss — adding columns with `ALTER TABLE`, creating indexes `CONCURRENTLY` to avoid table locks, and rolling back failed migrations safely.

Additionally, passwords would use **argon2id** instead of bcrypt in a production system. While bcrypt is secure, argon2id won the Password Hashing Competition (2015) and offers configurable memory hardness, making it resistant to GPU-based attacks in ways bcrypt is not. The implementation would be a straightforward swap of the hashing library.
