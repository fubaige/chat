import os
import sys
import asyncio
from langchain_neo4j import Neo4jGraph

# Add project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.core.config import settings

def test_conn():
    print(f"Testing connection to: {settings.NEO4J_URL}")
    try:
        graph = Neo4jGraph(
            url=settings.NEO4J_URL,
            username=settings.NEO4J_USERNAME,
            password=settings.NEO4J_PASSWORD,
            database=settings.NEO4J_DATABASE
        )
        print("Neo4jGraph initialized successfully.")
        
        # Try a simple query
        schema = graph.schema
        print("Schema retrieved successfully.")
        print(f"Schema length: {len(schema)}")
        
        result = graph.query("MATCH (n) RETURN count(n) as count")
        print(f"Query result: {result}")
        
    except Exception as e:
        print(f"Failed to connect via Neo4jGraph: {e}")

if __name__ == "__main__":
    test_conn()
