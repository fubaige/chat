import os
import sys
from neo4j import GraphDatabase

# Add project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Load env variables manually or rely on dotenv if installed
# For simplicity, I will read from the file or use hardcoded values based on previous observation
# NEO4J_URL=bolt://localhost:7687
# NEO4J_USERNAME=neo4j
# NEO4J_PASSWORD=12345678

URI = "bolt://localhost:7687"
AUTH = ("neo4j", "12345678")

try:
    with GraphDatabase.driver(URI, auth=AUTH) as driver:
        driver.verify_connectivity()
        print("Connection successful!")
        
        # Check node count
        result = driver.execute_query("MATCH (n) RETURN count(n) AS count")
        count = result.records[0]["count"]
        print(f"Node count: {count}")
        
except Exception as e:
    print(f"Connection failed: {e}")
