import argparse
import os
import json
from typing import Dict, Any, List
from neo4j import Driver
from .common import get_neo4j_driver, normalize_character_id
from .story_identity import story_id_for_clusters

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
        if isinstance(data, list):
            return {"clusters": data}
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {"clusters": []}


def upsert_plot_clusters(driver: Driver, config_path: str, story_id: str = "") -> None:
    story_id = story_id or story_id_for_clusters(config_path)
    cfg = load_clusters_config(config_path)
    clusters: List[Dict[str, Any]] = [c for c in (cfg.get("clusters") or []) if isinstance(c, dict)]
    if not clusters:
        print("No clusters found in config.")
        return
    with driver.session() as session:
        session.run("MATCH (pc:PlotCluster {story_id:$story_id}) DETACH DELETE pc", story_id=story_id)
        def _upsert_cluster(tx, cid: str, props: Dict[str, Any]):
            tx.run(
                """
                MERGE (pc:PlotCluster {id:$id})
                ON CREATE SET
                  pc.label=$label,
                  pc.story_id=$story_id,
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
                  pc.story_id=$story_id,
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
                MATCH (pc:PlotCluster {id:$id, story_id:$story_id})
                WITH pc
                UNWIND $chars AS cid
                MATCH (c:Character {id:cid})
                MERGE (c)-[:MAJOR_IN]->(pc)
                """,
                id=pc_id,
                story_id=story_id,
                chars=char_ids,
            )
        for c in clusters:
            cid = str(c.get("id") or c.get("cluster_id") or "").strip()
            if not cid:
                continue
            label = str(c.get("title") or c.get("name") or cid)
            mains = [f"char:{story_id}:{normalize_character_id(x)}" for x in (c.get("main_characters") or c.get("allowed_roles") or [])]
            span = c.get("chapter_span") or [c.get("start_chapter"), c.get("end_chapter")]
            start_chapter = span[0] if isinstance(span, list) and len(span) == 2 else c.get("start_chapter")
            end_chapter = span[1] if isinstance(span, list) and len(span) == 2 else c.get("end_chapter")
            props = {
                "id": f"plotcluster:{story_id}:{cid}",
                "story_id": story_id,
                "label": label,
                "goal": c.get("goal") or c.get("core_payoff") or c.get("cluster_outcome"),
                "mood": c.get("mood"),
                "start_chapter": start_chapter,
                "end_chapter": end_chapter,
                "plan_relations": c.get("plan_relations") or [],
                "plan_foreshadows": c.get("foreshadows") or c.get("notes") or [],
                "plan_resolves": c.get("resolves") or ([c.get("cluster_outcome")] if c.get("cluster_outcome") else []),
                "hard_constraints": c.get("hard_constraints") or c.get("user_extra_constraints") or [],
            }
            session.execute_write(_upsert_cluster, props["id"], props)
            if mains:
                session.execute_write(_link_main_chars, props["id"], mains)
        session.run(
            """
            MATCH (a:PlotCluster {story_id:$story_id}), (b:PlotCluster {story_id:$story_id})
            WHERE b.start_chapter = a.end_chapter + 1
            MERGE (a)-[:PLANNED_BEFORE]->(b)
            """,
            story_id=story_id,
        )
    print(f"Upserted {len(clusters)} plot clusters.")


def main():
    parser = argparse.ArgumentParser(description="Upsert Plot Clusters (情节族) into Neo4j from config.")
    parser.add_argument(
        "--clusters-config",
        type=str,
        default=os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "outputs", "event_clusters_v2.json"),
        help="Path to YAML/JSON plot clusters config (default: outputs/event_clusters_v2.json).",
    )
    args = parser.parse_args()
    driver = get_neo4j_driver()
    try:
        upsert_plot_clusters(driver, args.clusters_config)
    finally:
        driver.close()


if __name__ == "__main__":
    main()

