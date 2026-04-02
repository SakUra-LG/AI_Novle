import logging
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
    # NOTE: Some earlier code versions mistakenly looked up env vars by the URI/user/password
    # *values* (e.g. get_env("neo4j://127.0.0.1:7687")), causing context export/retrieval to
    # fail with "Missing required env var".
    #
    # We now follow the documented standard env var names, while still allowing fallback.
    uri = (
        os.getenv("NEO4J_URI")
        or os.getenv("neo4j://127.0.0.1:7687")
        or "bolt://127.0.0.1:7687"
    )
    user = os.getenv("NEO4J_USER") or "neo4j"
    password = os.getenv("NEO4J_PASSWORD") or "12345678"

    if not uri:
        raise RuntimeError("Missing required env var: NEO4J_URI")
    if not user:
        raise RuntimeError("Missing required env var: NEO4J_USER")
    if not password:
        raise RuntimeError("Missing required env var: NEO4J_PASSWORD")
    # Neo4j 会在查询阶段返回 notifications（例如字段不存在这类 warning）。
    # 这些不影响业务，但会把控制台刷屏，因此通过 driver 参数尽量静默。
    logging.getLogger("neo4j").setLevel(logging.ERROR)
    # Avoid long blocking when Neo4j is down/unreachable; generation should still proceed
    # (upstream callers already wrap Neo4j export/retrieval in try/except).
    try:
        connection_timeout_s = float(os.getenv("NEO4J_CONNECTION_TIMEOUT", "8"))
    except Exception:  # noqa: BLE001
        connection_timeout_s = 8.0

    # Neo4j Python driver 对 notifications_min_severity 的可选值因版本而异；
    # 兼容性处理：默认 NONE，避免初始化阶段直接报错。
    notifications_min_severity = os.getenv("NEO4J_NOTIFICATIONS_MIN_SEVERITY", "NONE")
    try:
        return GraphDatabase.driver(
            uri,
            auth=(user, password),
            notifications_min_severity=notifications_min_severity,
            connection_timeout=connection_timeout_s,
        )
    except TypeError:
        # Fallback for older neo4j driver versions that may not support connection_timeout.
        return GraphDatabase.driver(
            uri,
            auth=(user, password),
            notifications_min_severity=notifications_min_severity,
        )


def normalize_character_id(name: str) -> str:
    """
    Return a stable Character node id. We directly embed the name to avoid extra deps.
    """
    return f"char:{name}"


def run_write(tx, cypher: str, **params):
    tx.run(cypher, **params)

