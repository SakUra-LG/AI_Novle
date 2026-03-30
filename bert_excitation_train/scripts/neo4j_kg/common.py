import os
from typing import Optional
from neo4j import GraphDatabase, Driver


def get_env(name: str, default: Optional[str] = None) -> str:
    value = os.getenv(name, default)
    if value is None or value == "":
        raise RuntimeError(f"Missing required env var: {name}")
    return value


def get_neo4j_driver() -> Driver:
    """
    Create a Neo4j driver from environment variables:
      NEO4J_URI      e.g. bolt://localhost:7687
      NEO4J_USER     e.g. neo4j
      NEO4J_PASSWORD e.g. password
    """
    uri = get_env("NEO4J_URI")
    user = get_env("NEO4J_USER")
    password = get_env("NEO4J_PASSWORD")
    return GraphDatabase.driver(uri, auth=(user, password))


def normalize_character_id(name: str) -> str:
    """
    Return a stable Character node id. We directly embed the name to avoid extra deps.
    """
    return f"char:{name}"


def run_write(tx, cypher: str, **params):
    tx.run(cypher, **params)

