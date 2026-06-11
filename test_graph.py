from neo4j import GraphDatabase
from databases.graph.queries import (
    query_shortest_route,
    query_station_connections,
    query_delay_ripple
)

# Initialize Neo4j connection
uri = "bolt://localhost:7687"
driver = GraphDatabase.driver(uri, auth=("neo4j", "transitflow"))

print("Starting graph database query tests...")

try:
    # Test 1: Shortest Route (Task C1)
    print("\n--- Test 1: Shortest Route (MS01 to MS09) ---")
    result = query_shortest_route("MS01", "MS09") 
    print("Result:", result)

    # Test 2: Station Connections (Task C6)
    print("\n--- Test 2: Station Connections (NR01) ---")
    connections = query_station_connections("NR01")
    print("Result:", connections)

    # Test 3: Delay Ripple (Task C5)
    print("\n--- Test 3: Delay Ripple (NR03, 2 hops) ---")
    affected = query_delay_ripple("NR03", 2)
    print("Result:", affected)

except Exception as e:
    print(f"An error occurred during testing: {e}")
finally:
    driver.close()