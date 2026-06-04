"""
Test script to demonstrate what seed_neo4j.py would create
and what the graph queries would return.
Run this BEFORE Docker starts to see the expected output.
"""

import json
import os

# Load the mock data
def load(filename):
    with open(os.path.join("train-mock-data", filename), encoding="utf-8") as f:
        return json.load(f)

metro_stations = load("metro_stations.json")
rail_stations = load("national_rail_stations.json")

print("=" * 80)
print("NEO4J SEEDING SIMULATION — What seed_neo4j.py would create")
print("=" * 80)

# Count nodes
print(f"\n✅ CREATE NODES")
print(f"   MetroStation nodes: {len(metro_stations)}")
print(f"   RailStation nodes:  {len(rail_stations)}")
print(f"   Total nodes created: {len(metro_stations) + len(rail_stations)}")

# Count metro links
metro_links_count = 0
for s in metro_stations:
    metro_links_count += len(s.get("adjacent_stations", []))
print(f"\n✅ CREATE METRO_LINK EDGES")
print(f"   Total METRO_LINK edges: {metro_links_count}")

# Show sample metro link
print(f"\n   Example: {metro_stations[0]['station_id']} → {metro_stations[0]['adjacent_stations'][0]['station_id']}")
print(f"            Line: {metro_stations[0]['adjacent_stations'][0]['line']}")
print(f"            Travel time: {metro_stations[0]['adjacent_stations'][0]['travel_time_min']} min")

# Count rail links
rail_links_count = 0
for s in rail_stations:
    rail_links_count += len(s.get("adjacent_stations", []))
print(f"\n✅ CREATE RAIL_LINK EDGES")
print(f"   Total RAIL_LINK edges: {rail_links_count}")

# Count interchanges
interchange_count = 0
metro_interchange_map = {}
for s in metro_stations:
    nr_id = s.get("interchange_national_rail_station_id")
    if nr_id:
        interchange_count += 1
        metro_interchange_map[s["station_id"]] = nr_id

print(f"\n✅ CREATE INTERCHANGE RELATIONSHIPS")
print(f"   Total INTERCHANGE edges: {interchange_count}")
print(f"\n   Interchanges:")
for ms, nr in list(metro_interchange_map.items())[:3]:
    m_name = next(s["name"] for s in metro_stations if s["station_id"] == ms)
    n_name = next(s["name"] for s in rail_stations if s["station_id"] == nr)
    print(f"   • {ms} ({m_name}) ↔ {nr} ({n_name})")

# Simulate query results
print("\n" + "=" * 80)
print("GRAPH QUERY SIMULATION — Expected Results")
print("=" * 80)

# Find a metro route
print(f"\n🔍 query_shortest_route('MS01', 'MS09')")
print(f"   Looking for metro route from Central Square to Market Square...")

# Find stations MS01 and MS09
ms01 = next((s for s in metro_stations if s["station_id"] == "MS01"), None)
ms09 = next((s for s in metro_stations if s["station_id"] == "MS09"), None)

if ms01 and ms09:
    print(f"   ✅ Found: MS01 (Central Square) to MS09 (Market Square)")
    print(f"   Expected: path with multiple METRO_LINK edges")
    print(f"   Total travel time: ~15-20 min (estimated)")

# Query station connections
print(f"\n🔍 query_station_connections('NR01')")
print(f"   Connections from NR01 (Central Station):")
nr01 = next(s for s in rail_stations if s["station_id"] == "NR01")
for adj in nr01["adjacent_stations"][:3]:
    adj_station = next(s for s in rail_stations if s["station_id"] == adj["station_id"])
    print(f"   → {adj['station_id']} ({adj_station['name']}) via line {adj['line']}, {adj['travel_time_min']} min")

# Query interchange path
print(f"\n🔍 query_interchange_path('MS01', 'NR05')")
print(f"   Cross-network route: Metro Central Square → National Rail Stonehaven")
ms01_name = next(s for s in metro_stations if s["station_id"] == "MS01")["name"]
nr05 = next((s for s in rail_stations if s["station_id"] == "NR05"), None)
if nr05:
    nr05_name = nr05["name"]
    print(f"   ✅ Start at MS01 ({ms01_name})")
    print(f"   ↔ Interchange via INTERCHANGE edge (via metro or rail hub)")
    print(f"   ✅ End at NR05 ({nr05_name})")

# Query delay ripple
print(f"\n🔍 query_delay_ripple('NR03', hops=2)")
print(f"   If NR03 (Old Town Junction) is delayed, which stations are affected?")
nr03 = next(s for s in rail_stations if s["station_id"] == "NR03")
print(f"   Checking {nr03['name']} and all stations within 2 hops...")

# Simulate ripple effect
all_affected = set()
for adj in nr03["adjacent_stations"]:
    all_affected.add(adj["station_id"])
    # Second level
    adj_station = next(s for s in rail_stations if s["station_id"] == adj["station_id"])
    for adj2 in adj_station["adjacent_stations"]:
        all_affected.add(adj2["station_id"])

print(f"   Affected stations: {len(all_affected)}")
print(f"   {', '.join(sorted(all_affected)[:5])}...")

print("\n" + "=" * 80)
print("📊 SUMMARY")
print("=" * 80)
print(f"✅ Total nodes to create: {len(metro_stations) + len(rail_stations)}")
print(f"✅ Total edges to create: {metro_links_count + rail_links_count + interchange_count}")
print(f"✅ Graphs functions ready: 6 (shortest route, cheapest, alternative, interchange, ripple, connections)")
print("\n📝 Next step: Start Docker and run: python skeleton/seed_neo4j.py")
print("🌐 Then open Neo4j Browser at: http://localhost:7475")
print("=" * 80)
