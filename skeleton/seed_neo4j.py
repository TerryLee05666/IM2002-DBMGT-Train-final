"""
TransitFlow — Neo4j Seeder
Run once after starting Docker:
    python skeleton/seed_neo4j.py

Loads station and network data from train-mock-data/:
  - metro_stations.json         — city metro stations and adjacencies
  - national_rail_stations.json — national rail stations and adjacencies

Design your graph schema (node labels, relationship types, properties)
based on the data in these files, then implement the seed() function below.
"""

import json
import os
import sys

sys.path.insert(0, ".")

from neo4j import GraphDatabase
from skeleton.config import NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD

_DATA_DIR = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "train-mock-data")
)


def _load(filename):
    with open(os.path.join(_DATA_DIR, filename), encoding="utf-8") as f:
        return json.load(f)


def seed():
    metro_stations = _load("metro_stations.json")
    rail_stations  = _load("national_rail_stations.json")

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    with driver.session() as session:

        session.run("MATCH (n) DETACH DELETE n")
        print("  Cleared existing graph data")

        # ── Create Metro Station nodes ────────────────────────────────────────

        for s in metro_stations:
            session.run(
                "MERGE (n:MetroStation {station_id: $id}) "
                "SET n.name = $name, n.lines = $lines, "
                "    n.is_interchange = $is_interchange",
                id=s["station_id"],
                name=s["name"],
                lines=s.get("lines", []),
                is_interchange=s.get("is_interchange_metro", False),
            )
        print(f"  Created {len(metro_stations)} MetroStation nodes")

        # ── Create National Rail Station nodes ────────────────────────────────

        for s in rail_stations:
            session.run(
                "MERGE (n:RailStation {station_id: $id}) "
                "SET n.name = $name, n.lines = $lines, "
                "    n.is_interchange = $is_interchange",
                id=s["station_id"],
                name=s["name"],
                lines=s.get("lines", []),
                is_interchange=s.get("is_interchange_national_rail", False),
            )
        print(f"  Created {len(rail_stations)} RailStation nodes")

        # ── Create Metro Links (directed edges) ───────────────────────────────

        metro_links_count = 0
        for s in metro_stations:
            for adj in s.get("adjacent_stations", []):
                session.run(
                    "MATCH (a:MetroStation {station_id: $from_id}) "
                    "MATCH (b:MetroStation {station_id: $to_id}) "
                    "MERGE (a)-[r:METRO_LINK {line: $line}]->(b) "
                    "SET r.travel_time_min = $time",
                    from_id=s["station_id"],
                    to_id=adj["station_id"],
                    line=adj["line"],
                    time=adj["travel_time_min"],
                )
                metro_links_count += 1
        print(f"  Created {metro_links_count} METRO_LINK edges")

        # ── Create Rail Links (directed edges) ────────────────────────────────

        rail_links_count = 0
        for s in rail_stations:
            for adj in s.get("adjacent_stations", []):
                session.run(
                    "MATCH (a:RailStation {station_id: $from_id}) "
                    "MATCH (b:RailStation {station_id: $to_id}) "
                    "MERGE (a)-[r:RAIL_LINK {line: $line}]->(b) "
                    "SET r.travel_time_min = $time",
                    from_id=s["station_id"],
                    to_id=adj["station_id"],
                    line=adj["line"],
                    time=adj["travel_time_min"],
                )
                rail_links_count += 1
        print(f"  Created {rail_links_count} RAIL_LINK edges")

        # ── Create Interchange relationships ──────────────────────────────────

        interchange_count = 0
        for s in metro_stations:
            nr_id = s.get("interchange_national_rail_station_id")
            if nr_id:
                session.run(
                    "MATCH (m:MetroStation {station_id: $metro_id}) "
                    "MATCH (r:RailStation {station_id: $rail_id}) "
                    "MERGE (m)-[link:INTERCHANGE]-(r)",
                    metro_id=s["station_id"],
                    rail_id=nr_id,
                )
                interchange_count += 1
        print(f"  Created {interchange_count} INTERCHANGE relationships")

    driver.close()
    print("\nNeo4j graph seeded successfully.")
    print("   Open http://localhost:7475 to explore the graph.")


if __name__ == "__main__":
    print("Connecting to Neo4j...")
    seed()
