"""Validate the isolated EC136—EC178 replacement synopsis before prose work."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def validate(payload: dict) -> list[str]:
    failures = []
    items = payload.get("items") or []
    if [x.get("cluster_id") for x in items] != [f"EC{i:03d}" for i in range(136, 179)]:
        failures.append("重构梗概必须覆盖EC136—EC178且连续")
    points = [str(x.get("irreplaceable_progress_point") or "") for x in items]
    if len(set(points)) != len(points):
        failures.append("不可替代推进点重复")
    for item in items:
        if item.get("identity_source") != "CHARACTER_BIBLE":
            failures.append(f"{item.get('cluster_id')}身份源不是CHARACTER_BIBLE")
        if len(item.get("canonical_characters") or []) < 8:
            failures.append(f"{item.get('cluster_id')}缺少固定角色清单")
        if len(item.get("forbidden_reuse") or []) < 3:
            failures.append(f"{item.get('cluster_id')}缺少情节族防重复约束")
    return failures


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    args = parser.parse_args()
    payload = json.loads(args.plan.read_text(encoding="utf-8"))
    failures = validate(payload)
    if failures:
        raise SystemExit("\n".join(failures))
    print(json.dumps({"passed": True, "items": len(payload["items"]), "range": [136, 178]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
