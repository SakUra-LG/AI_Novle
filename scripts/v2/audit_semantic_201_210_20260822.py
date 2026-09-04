from pathlib import Path
import json
from generate_pop_king_body_v5 import _run_semantic_critic

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs_pop_king_v6_compiled_story_first_500"
events = json.loads((OUT / "event_clusters_v2.json").read_text(encoding="utf-8"))
cards_raw = json.loads((OUT / "master_ctx_cards_v2.json").read_text(encoding="utf-8"))
clusters = {str(x.get("cluster_id")): x for x in events}
cards = {int(x["chapter_id"]): x for x in cards_raw}
rows = []
for n in range(101, 106):
    cluster = clusters[f"EC{n:03d}"]
    span = [int(x) for x in cluster["chapter_span"]]
    bodies = {chapter: (OUT / "chapters" / f"chapter_{chapter:03d}.txt").read_text(encoding="utf-8").strip() for chapter in span}
    result, failures, meta = _run_semantic_critic(
        cluster=cluster,
        cards=[cards[span[0]], cards[span[1]]],
        bodies=bodies,
        graph_contexts={chapter: "" for chapter in span},
        model="qwen-plus",
    )
    rows.append({"cluster_id": cluster["cluster_id"], "chapter_span": span, "critic": result, "failures": failures, "call": meta})
(OUT / "semantic_critic_audit_201_210_20260822.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps([{ "cluster_id": x["cluster_id"], "failures": x["failures"] } for x in rows], ensure_ascii=False))
