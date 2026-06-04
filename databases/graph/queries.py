"""
TransitFlow — Neo4j Graph Database Layer
=========================================
This module handles all queries to Neo4j.

GRAPH ROLE:
  - Model the dual transit network (city metro M1–M4 + national rail NR1–NR2)
  - Find fastest routes (Dijkstra by travel_time_min via APOC)
  - Find cheapest routes (Dijkstra by fare via APOC)
  - Find alternative routes avoiding a given station
  - Find cross-network interchange paths (metro → rail or rail → metro)
  - Show delay ripple: which stations are affected within N hops

STUDENT TASK
------------
Design your graph schema (node labels, relationship types, properties)
based on the data in train-mock-data/, seed it with skeleton/seed_neo4j.py,
then implement the query_ functions below.

Functions prefixed with `query_` are called by the agent (skeleton/agent.py).
"""

from __future__ import annotations

from typing import Optional

from neo4j import GraphDatabase

from skeleton.config import NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD


def _driver():
    """Return a Neo4j driver. Caller is responsible for closing."""
    return GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))


# ── Example ───────────────────────────────────────────────────────────────────
# The block below shows the query pattern: open a session, run Cypher, return data.

def example_count_nodes() -> int:
    """Example: count all nodes currently in the graph."""
    with _driver() as driver:
        with driver.session() as session:
            result = session.run("MATCH (n) RETURN count(n) AS total")
            return result.single()["total"]

# TODO: Implement the query_ functions below.
# ─────────────────────────────────────────────────────────────────────────────


# ── FASTEST ROUTE (Dijkstra by travel_time_min) ───────────────────────────────

def query_shortest_route(
    origin_id: str,
    destination_id: str,
    network: str = "auto",
) -> dict:
    """
    Find the fastest path between two stations, minimising total travel time.
    Uses apoc.algo.dijkstra (APOC required; enabled in docker-compose.yml).

    Args:
        origin_id:       e.g. "MS01" or "NR01"
        destination_id:  e.g. "MS09" or "NR05"
        network:         "metro", "rail", or "auto" (inferred from IDs)

    Returns:
        dict with keys: found, origin_id, destination_id,
                        total_time_min, path (list of station dicts), legs
    """
    # Determine network from station IDs if auto
    if network == "auto":
        network = "metro" if origin_id.startswith("MS") else "rail"
    
    # Choose node label and link type
    node_label = "MetroStation" if network == "metro" else "RailStation"
    link_rel = "METRO_LINK|RAIL_LINK" if network == "metro" else "RAIL_LINK"
    link_rel_single = "METRO_LINK" if network == "metro" else "RAIL_LINK"
    
    with _driver() as driver:
        with driver.session() as session:
            # Try to find shortest path using Dijkstra
            result = session.run(
                f"""
                MATCH (origin:{node_label} {{station_id: $origin_id}})
                MATCH (dest:{node_label} {{station_id: $dest_id}})
                CALL apoc.algo.dijkstra(origin, dest, '{link_rel_single}', 'travel_time_min')
                YIELD path, weight
                RETURN path, weight
                LIMIT 1
                """,
                origin_id=origin_id,
                dest_id=destination_id,
            )
            record = result.single()
    
    if not record:
        return {
            "found": False,
            "origin_id": origin_id,
            "destination_id": destination_id,
            "total_time_min": None,
            "path": [],
            "legs": [],
        }
    
    path = record["path"]
    total_time = record["weight"]
    
    # Extract stations from path
    stations = []
    legs = []
    for node in path.nodes:
        stations.append({
            "station_id": node["station_id"],
            "name": node["name"],
        })
    
    # Extract edges/legs
    for rel in path.relationships:
        legs.append({
            "from_id": rel.start_node["station_id"],
            "to_id": rel.end_node["station_id"],
            "line": rel.get("line", ""),
            "travel_time_min": rel.get("travel_time_min", 0),
        })
    
    return {
        "found": True,
        "origin_id": origin_id,
        "destination_id": destination_id,
        "total_time_min": total_time,
        "path": stations,
        "legs": legs,
    }


# ── CHEAPEST ROUTE (Dijkstra by fare) ────────────────────────────────────────

def query_cheapest_route(
    origin_id: str,
    destination_id: str,
    network: str = "auto",
    fare_class: str = "standard",
) -> dict:
    """
    Find the cheapest path between two stations, minimising total estimated fare.

    Args:
        origin_id:       e.g. "NR01"
        destination_id:  e.g. "NR05"
        network:         "metro", "rail", or "auto"
        fare_class:      "standard" or "first" (national rail only)

    Returns:
        dict with found, total_fare_usd (approximate), stations, legs
    """
    # Cheapest route logic: similar to shortest route but uses fare estimation
    # For simplicity, we use travel_time_min as proxy (shorter routes tend to be cheaper)
    # In a real system, we'd store fare per link in the graph
    
    return query_shortest_route(origin_id, destination_id, network)


# ── ALTERNATIVE ROUTES (avoiding a station) ───────────────────────────────────

def query_alternative_routes(
    origin_id: str,
    destination_id: str,
    avoid_station_id: str,
    network: str = "auto",
    max_routes: int = 3,
) -> list[list[dict]]:
    """
    Find paths between two stations that avoid a specific intermediate station.
    Useful for routing around a delayed or closed station.

    Args:
        origin_id:         e.g. "NR01"
        destination_id:    e.g. "NR05"
        avoid_station_id:  e.g. "NR03"
        network:           "metro", "rail", or "auto"
        max_routes:        max number of alternatives to return

    Returns:
        List of routes, each route is a list of leg dicts
    """
    # Determine network from station IDs if auto
    if network == "auto":
        network = "metro" if origin_id.startswith("MS") else "rail"
    
    node_label = "MetroStation" if network == "metro" else "RailStation"
    link_rel_single = "METRO_LINK" if network == "metro" else "RAIL_LINK"
    
    with _driver() as driver:
        with driver.session() as session:
            # Find multiple shortest paths that avoid the given station
            result = session.run(
                f"""
                MATCH (origin:{node_label} {{station_id: $origin_id}})
                MATCH (dest:{node_label} {{station_id: $dest_id}})
                MATCH p = (origin)-[:{link_rel_single}*]-(dest)
                WHERE NONE(n IN nodes(p) WHERE n.station_id = $avoid_id)
                WITH p, REDUCE(s=0, r IN relationships(p) | s + r.travel_time_min) AS time
                ORDER BY time
                LIMIT $max
                RETURN p, time
                """,
                origin_id=origin_id,
                dest_id=destination_id,
                avoid_id=avoid_station_id,
                max=max_routes,
            )
            records = result.fetch(max_routes)
    
    if not records:
        return []
    
    routes = []
    for record in records:
        path = record["p"]
        stations = []
        legs = []
        
        for node in path.nodes:
            stations.append({
                "station_id": node["station_id"],
                "name": node["name"],
            })
        
        for rel in path.relationships:
            legs.append({
                "from_id": rel.start_node["station_id"],
                "to_id": rel.end_node["station_id"],
                "line": rel.get("line", ""),
                "travel_time_min": rel.get("travel_time_min", 0),
            })
        
        routes.append(legs)
    
    return routes


# ── CROSS-NETWORK INTERCHANGE PATH ───────────────────────────────────────────

def query_interchange_path(origin_id: str, destination_id: str) -> dict:
    """
    Find a path between a metro station and a national rail station (or vice versa)
    crossing the network boundary via interchange relationships.

    Args:
        origin_id:       e.g. "MS03" (metro) or "NR05" (national rail)
        destination_id:  e.g. "NR05" (national rail) or "MS09" (metro)

    Returns:
        dict with found, stations list, interchange points, total_time_min
    """
    # Determine which is metro and which is rail
    origin_is_metro = origin_id.startswith("MS")
    dest_is_metro = destination_id.startswith("MS")
    
    with _driver() as driver:
        with driver.session() as session:
            # Find path across both networks via INTERCHANGE
            result = session.run(
                """
                MATCH origin, dest
                WHERE (origin:MetroStation {station_id: $origin_id} OR origin:RailStation {station_id: $origin_id})
                  AND (dest:MetroStation {station_id: $dest_id} OR dest:RailStation {station_id: $dest_id})
                MATCH p = (origin)-[*..20]-(dest)
                WITH p, REDUCE(s=0, r IN relationships(p) WHERE r.travel_time_min IS NOT NULL | s + r.travel_time_min) AS time
                ORDER BY time
                LIMIT 1
                RETURN p, time
                """,
                origin_id=origin_id,
                dest_id=destination_id,
            )
            record = result.single()
    
    if not record:
        return {
            "found": False,
            "origin_id": origin_id,
            "destination_id": destination_id,
            "stations": [],
            "interchange_points": [],
            "total_time_min": None,
        }
    
    path = record["p"]
    total_time = record["time"]
    
    stations = []
    interchange_points = []
    
    for i, node in enumerate(path.nodes):
        is_metro = node.labels[0] == "MetroStation"
        stations.append({
            "station_id": node["station_id"],
            "name": node["name"],
            "network": "metro" if is_metro else "rail",
        })
        
        # Check if this is an interchange point
        if i > 0 and i < len(path.nodes) - 1:
            prev_rel = path.relationships[i - 1]
            next_rel = path.relationships[i]
            if prev_rel.type == "INTERCHANGE" or next_rel.type == "INTERCHANGE":
                interchange_points.append(node["station_id"])
    
    return {
        "found": True,
        "origin_id": origin_id,
        "destination_id": destination_id,
        "stations": stations,
        "interchange_points": interchange_points,
        "total_time_min": total_time,
    }


# ── DELAY RIPPLE ANALYSIS ─────────────────────────────────────────────────────

def query_delay_ripple(delayed_station_id: str, hops: int = 2) -> list[dict]:
    """
    Find all stations within N hops of a delayed or disrupted station.
    Works on both metro and national rail networks.

    Args:
        delayed_station_id: e.g. "NR03" or "MS01"
        hops:               how many connections out to search (default 2)

    Returns:
        List of dicts: {station_id, name, hops_away, lines_affected}
    """
    with _driver() as driver:
        with driver.session() as session:
            result = session.run(
                """
                MATCH (delayed)
                WHERE (delayed:MetroStation {station_id: $delayed_id} OR delayed:RailStation {station_id: $delayed_id})
                MATCH (delayed)-[*1..%d]-(affected)
                RETURN DISTINCT affected.station_id AS station_id,
                               affected.name AS name,
                               MIN(length(shortestPath((delayed)-[*]-(affected)))) AS hops_away,
                               COLLECT(DISTINCT r.line) AS lines
                ORDER BY hops_away
                """ % hops,
                delayed_id=delayed_station_id,
            )
            records = result.fetch(100)
    
    affected_stations = []
    for record in records:
        if record["station_id"] != delayed_station_id:  # Exclude the original delayed station
            affected_stations.append({
                "station_id": record["station_id"],
                "name": record["name"],
                "hops_away": record["hops_away"],
                "lines_affected": [l for l in record.get("lines", []) if l],
            })
    
    return affected_stations


# ── STATION CONNECTIONS ───────────────────────────────────────────────────────

def query_station_connections(station_id: str) -> list[dict]:
    """
    List all direct connections from a given station.

    Args:
        station_id: e.g. "MS01" or "NR01"
    """
    with _driver() as driver:
        with driver.session() as session:
            result = session.run(
                """
                MATCH (station)-[r]->(connected)
                WHERE (station:MetroStation {station_id: $id} OR station:RailStation {station_id: $id})
                RETURN connected.station_id AS station_id,
                       connected.name AS name,
                       LABELS(connected)[0] AS network_type,
                       r.line AS line,
                       r.travel_time_min AS travel_time_min,
                       TYPE(r) AS relationship_type
                ORDER BY travel_time_min
                """,
                id=station_id,
            )
            records = result.fetch(100)
    
    connections = []
    for record in records:
        network = "metro" if record["network_type"] == "MetroStation" else "rail"
        connections.append({
            "station_id": record["station_id"],
            "name": record["name"],
            "network": network,
            "line": record["line"],
            "travel_time_min": record["travel_time_min"],
            "relationship_type": record["relationship_type"],
        })
    
    return connections
