# Work Allocation Report — 6

> **Instructions:** Complete this document as a team before or alongside your final submission.
> Submit one copy per team via EEClass. This document is shared with all markers.
> Be specific — vague entries ("we all helped") will prevent individual contribution adjustments from being applied in your favour.

---

## 1. Team Members

| Full Name | Student ID | GitHub Username | Email |
|-----------|-----------|----------------|-------|
| 李庭宇|113403523 |TerryLee05666 |terry@abbottlee.com |
| 商逢育|113403513 |adsgg-00 |q0951099000@gmail.com |
| | | | |

---

## 2. Task Ownership

For each task, name the **primary owner** (the person most responsible for delivering it)
and any **supporting members** (who assisted but were not the lead). Leave the Notes column
for anything that deviates from the standard expectation (e.g., task was pair-programmed,
or reassigned mid-project).

### Code Repository

| Task | Primary Owner | Supporting Member(s) | Notes |
|------|--------------|---------------------|-------|
| **Task 1** — Relational schema design (`schema.sql`) | 李庭宇| 商逢育, 張靖賦| Initial setup & schema design|
| **Task 2a** — Core availability & fare queries (`query_national_rail_availability`, `query_metro_schedules`, `query_national_rail_fare`, `query_metro_fare`) | 李庭宇|商逢育 | Auth & logic by Terry; Fixes by 商逢育|
| **Task 2b** — Seat & user queries (`query_available_seats`, `query_user_profile`, `query_user_bookings`, `query_payment_info`) | 李庭宇| 商逢育| Auth & logic by Terry; Fixes by 商逢育|
| **Task 2c** — Write operations (`execute_booking`, `execute_cancellation`) | 李庭宇| 商逢育| Auth & logic by Terry; Fixes by 商逢育|
| **Task 2d** — Authentication queries (`login_user`, `register_user`, `get_user_secret_question`, `verify_secret_answer`, `update_password`) |李庭宇 | 商逢育| Auth & logic by Terry; Fixes by 商逢育|
| **Task 3** — PostgreSQL seeding (`seed_postgres.py`) | 李庭宇| 商逢育| |
| **Task 4** — Neo4j graph design & seeding (`seed_neo4j.py`, `seed.cypher`) | 張靖賦| 商逢育| Jacob led seeding; Eric led label fixes|
| **Task 5** — Neo4j query functions (`graph/queries.py`) | 張靖賦| 商逢育| Jacob implemented; Eric optimized logic|
| **Task 6** *(if attempted)* — Optional extension | 張靖賦| 商逢育|Jacob led implementation; Eric linked tools|

### Design Document

| Section | Primary Author | Supporting Member(s) | Notes |
|---------|--------------|---------------------|-------|
| Section 1 — ER Diagram |李庭宇|商逢育|
| Section 2 — Normalisation Justification |李庭宇|商逢育|
| Section 3 — Graph Database Design Rationale |商逢育|張靖賦|
| Section 4 — Vector / RAG Design |商逢育|張靖賦|
| Section 5 — AI Tool Usage Evidence |張靖賦|商逢育, 李庭宇	|
| Section 6 — Reflection & Trade-offs |張靖賦|商逢育, 李庭宇 |
| Section 7 — Optional Extension *(if applicable)* |張靖賦|商逢育, 李庭宇|Documented Task 6 & AI usage|

---

## 3. Estimated Contribution Percentages

Based on the task allocation above, what percentage of total team effort do you estimate each member contributed?
All members must sum to 100%.

| Member | Estimated % | Brief justification |
|--------|-----------|---------------------|
|李庭宇	| 35% |Architecture, PR management, and core code quality.|
|商逢育	| 35% |Core logic fixes, graph optimizations, and conflict resolution.|
|張靖賦	| 30% |Task 6 extension implementation and design documentation.|
| **Total** | **100%** | |

---

## 4. Mid-Project Changes

| Change | Original plan | Revised plan | Reason |
|--------|--------------|-------------|--------|
|Added Task 6 | Basic requirements only|Implemented delay_records & graph tools | To provide a more robust service disruption tracking system.|

---

## 5. Team Declaration

We confirm that this work allocation accurately reflects how responsibilities were divided within our team.

| Name | Signature / Typed name | Date |
|------|----------------------|------|
|商逢育|商逢育|2026/06/11|
| | | |
| | | |
