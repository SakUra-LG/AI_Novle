import argparse
import time
from typing import Any, Dict, Optional

from neo4j import Driver

from .common import get_neo4j_driver


def _try_query(driver: Driver, query: str) -> Dict[str, Any]:
    with driver.session() as session:
        result = session.run(query)
        row = result.single()
        return dict(row) if row else {}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Test Neo4j connectivity (network + auth + minimal Cypher query). No data is modified."
    )
    parser.add_argument(
        "--query",
        type=str,
        default="RETURN 1 AS ok",
        help='Minimal Cypher to validate query execution (default: "RETURN 1 AS ok").',
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=3,
        help="Retry times when connection/query fails (default: 3).",
    )
    parser.add_argument(
        "--retry-wait-ms",
        type=int,
        default=1500,
        help="Wait time between retries in milliseconds (default: 1500).",
    )
    args = parser.parse_args()

    driver = get_neo4j_driver()
    try:
        last_err: Optional[Exception] = None
        for attempt in range(1, max(1, args.retries) + 1):
            try:
                started = time.time()
                data = _try_query(driver, args.query)
                elapsed_ms = int((time.time() - started) * 1000)

                ok = data.get("ok")
                print(f"NEO4J_OK: {ok} (query_ms={elapsed_ms})")
                return
            except Exception as e:  # noqa: BLE001
                last_err = e
                print(f"[attempt {attempt}/{args.retries}] Neo4j test failed: {e}")
                if attempt < args.retries:
                    time.sleep(args.retry_wait_ms / 1000.0)

        print(f"NEO4J_TEST_FAILED after {args.retries} retries: {last_err}")
        raise SystemExit(1)
    finally:
        driver.close()


if __name__ == "__main__":
    main()

