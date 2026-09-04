"""Generate an isolated v11 trial for chapters 201-210.

This intentionally records candidates that fail a gate instead of committing
them to official chapters or StoryMemory. It is used to inspect the effect of
the revised writer contract across the complete ten-chapter sample.
"""
from pathlib import Path
import json
import os
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.v2 import generate_pop_king_body_v5 as gen  # noqa: E402


OUT = ROOT / "outputs_pop_king_v6_compiled_story_first_500"
TRIAL = OUT / "trial_v11_201_210"


def main() -> None:
    events, card_map, outline = gen._load_inputs(OUT)
    planning_id = gen.planning_story_id(outline)
    samples = gen._load_json(gen.DEFAULT_STYLE_SAMPLES)
    trial_chapters = TRIAL / "chapters"
    raw_dir = TRIAL / "raw"
    trial_chapters.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)
    report = {"contract": gen.BODY_GENERATOR_CONTRACT_VERSION, "chapters": {}, "clusters": {}}
    for cluster_number in range(101, 106):
        cluster = events[cluster_number - 1]
        span = [int(v) for v in cluster["chapter_span"]]
        cards = [card_map[v] for v in span]
        graph = {}
        for card in cards:
            cid = int(card["chapter_id"])
            graph[cid] = gen._body_safe_graph_context(
                gen.retrieve_context_for_chapter(
                    chapter_num=cid,
                    allowed_roles=gen._known_names(card),
                    main_opponent=str(card.get("main_opponent") or ""),
                    max_chars=3200,
                    story_id=planning_id,
                ),
                cluster_span=span,
                chapter_id=cid,
            )
        bodies = {}
        previous = ""
        for card in cards:
            cid = int(card["chapter_id"])
            candidates = []
            last_body = ""
            last_failures = []
            for attempt in range(1, 4):
                system, user = gen._build_single_chapter_prompt(
                    cluster=cluster,
                    card=card,
                    graph_context=graph[cid],
                    style_samples=samples,
                    previous_body=previous,
                    prior_failure="\n".join("- " + str(x) for x in last_failures),
                    recent_style_budget={},
                )
                raw, meta = gen._call_qwen(
                    [{"role": "system", "content": system}, {"role": "user", "content": user}],
                    model="qwen-plus", temperature=0.9,
                )
                (raw_dir / f"chapter_{cid:03d}_attempt_{attempt:02d}.txt").write_text(raw, encoding="utf-8")
                try:
                    parsed = gen._parse_json_object(raw, default_chapter_id=cid)
                    body, failures, audit = gen._validate_single_chapter(parsed, card)
                except Exception as exc:  # noqa: BLE001
                    body, audit, failures = "", {}, [f"parse: {exc}"]
                last_body, last_failures = body, failures
                candidates.append({"attempt": attempt, "failures": failures, "audit": audit, "call": meta})
                if body and not failures:
                    break
            if last_body:
                (trial_chapters / f"chapter_{cid:03d}.txt").write_text(last_body + "\n", encoding="utf-8")
                previous = last_body
            bodies[cid] = last_body
            report["chapters"][str(cid)] = {"attempts": candidates, "selected_failures": last_failures}
        recent = {}
        for prior in range(max(1, span[0] - 5), span[0]):
            path = OUT / "chapters" / f"chapter_{prior:03d}.txt"
            if path.is_file():
                recent[prior] = path.read_text(encoding="utf-8").strip()
        combined = {"cluster_id": cluster["cluster_id"], "chapters": [{"chapter_id": k, "body": v} for k, v in bodies.items()]}
        _, joint_failures, joint_audit = gen._validate_candidate(combined, cluster=cluster, cards=cards, recent_bodies=recent)
        try:
            critic, critic_failures, critic_meta = gen._run_semantic_critic(
                cluster=cluster, cards=cards, bodies=bodies, graph_contexts=graph,
                model="qwen-plus", recent_bodies=recent,
            )
        except Exception as exc:  # noqa: BLE001
            critic, critic_failures, critic_meta = {}, [f"critic call: {exc}"], {}
        report["clusters"][cluster["cluster_id"]] = {
            "joint_failures": joint_failures,
            "joint_audit": joint_audit,
            "semantic_critic": critic,
            "semantic_critic_failures": critic_failures,
            "semantic_critic_call": critic_meta,
        }
        print(f"[trial] {cluster['cluster_id']} chapters {span[0]}-{span[1]}", flush=True)
    (TRIAL / "trial_quality_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[trial-complete] {TRIAL}", flush=True)


if __name__ == "__main__":
    main()
