import argparse
import os
import json
from typing import Dict, Any, List
from neo4j import Driver
from .common import get_neo4j_driver, normalize_character_id

try:
    import yaml  # type: ignore
except Exception:
    yaml = None


def read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def load_clusters_config(path: str) -> Dict[str, Any]:
    if not path or not os.path.isfile(path):
        return {"clusters": []}
    text = read_text(path)
    if yaml is not None:
        try:
            data = yaml.safe_load(text) or {}
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {"clusters": []}


def upsert_plot_clusters(driver: Driver, config_path: str) -> None:
    cfg = load_clusters_config(config_path)
    clusters: List[Dict[str, Any]] = [c for c in (cfg.get("clusters") or []) if isinstance(c, dict)]
    if not clusters:
        print("No clusters found in config.")
        return
    with driver.session() as session:
        def _upsert_cluster(tx, cid: str, props: Dict[str, Any]):
            tx.run(
                """
                MERGE (pc:PlotCluster {id:$id})
                ON CREATE SET
                  pc.label=$label,
                  pc.goal=$goal,
                  pc.mood=$mood,
                  pc.start_chapter=$start_chapter,
                  pc.end_chapter=$end_chapter,
                  pc.plan_relations=$plan_relations,
                  pc.plan_foreshadows=$plan_foreshadows,
                  pc.plan_resolves=$plan_resolves,
                  pc.hard_constraints=$hard_constraints,
                  pc.createdAt=timestamp()
                ON MATCH SET
                  pc.label=$label,
                  pc.goal=$goal,
                  pc.mood=$mood,
                  pc.start_chapter=$start_chapter,
                  pc.end_chapter=$end_chapter,
                  pc.plan_relations=$plan_relations,
                  pc.plan_foreshadows=$plan_foreshadows,
                  pc.plan_resolves=$plan_resolves,
                  pc.hard_constraints=$hard_constraints,
                  pc.updatedAt=timestamp()
                """,
                **props,
            )
        def _link_main_chars(tx, pc_id: str, char_ids: List[str]):
            tx.run(
                """
                MATCH (pc:PlotCluster {id:$id})
                WITH pc
                UNWIND $chars AS cid
                MATCH (c:Character {id:cid})
                MERGE (c)-[:MAJOR_IN]->(pc)
                """,
                id=pc_id,
                chars=char_ids,
            )
        for c in clusters:
            cid = str(c.get("id") or "").strip()
            if not cid:
                continue
            label = str(c.get("title") or cid)
            mains = [normalize_character_id(x) for x in (c.get("main_characters") or [])]
            props = {
                "id": f"plotcluster:{cid}",
                "label": label,
                "goal": c.get("goal"),
                "mood": c.get("mood"),
                "start_chapter": c.get("start_chapter"),
                "end_chapter": c.get("end_chapter"),
                "plan_relations": c.get("plan_relations") or [],
                "plan_foreshadows": c.get("foreshadows") or [],
                "plan_resolves": c.get("resolves") or [],
                "hard_constraints": c.get("hard_constraints") or [],
            }
            session.execute_write(_upsert_cluster, props["id"], props)
            if mains:
                session.execute_write(_link_main_chars, props["id"], mains)
    print(f"Upserted {len(clusters)} plot clusters.")


def main():
    parser = argparse.ArgumentParser(description="Upsert Plot Clusters (情节族) into Neo4j from config.")
    parser.add_argument("--clusters-config", type=str, required=True, help="Path to YAML/JSON plot clusters config.")
    args = parser.parse_args()
    driver = get_neo4j_driver()
    try:
        upsert_plot_clusters(driver, args.clusters_config)
    finally:
        driver.close()


if __name__ == "__main__":
    main()

