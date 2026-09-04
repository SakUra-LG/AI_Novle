# EC142隔离试写质量报告（证据自动生成）

状态：trial_only_not_accepted；未写入正式StoryMemory、Neo4j，未标记accepted。

{
  "version": "isolated_trial_report_v1",
  "status": "trial_only_not_accepted",
  "formal_story_memory_write": false,
  "neo4j_write": false,
  "external_semantic_critic": "not_run",
  "cluster_id": "EC142",
  "chapters": [
    {
      "chapter_id": 283,
      "event_cluster_id": "EC142",
      "expected_progress_point": "追查登记簿缺号前后的借阅人，只获得一次受限开柜许可",
      "actual_progress_point": "candidate prose present; evidence checks applied",
      "plan_binding_status": "PASS",
      "timeline": "PASS",
      "character_consistency": "PASS",
      "rebirth_boundary": "PASS",
      "metadata_leak": "PASS",
      "paragraph_repetition": "PASS",
      "sha256": "5b470844ac910bdd8250e0ca3f460a367a75d145db5a93043f1525ec4449f1d3"
    },
    {
      "chapter_id": 284,
      "event_cluster_id": "EC142",
      "expected_progress_point": "追查登记簿缺号前后的借阅人，只获得一次受限开柜许可",
      "actual_progress_point": "candidate prose present; evidence checks applied",
      "plan_binding_status": "FAIL",
      "timeline": "PASS",
      "character_consistency": "FAIL",
      "rebirth_boundary": "PASS",
      "metadata_leak": "PASS",
      "paragraph_repetition": "PASS",
      "sha256": "463c9c9912062081175339e1f37f9112d470b598e2f066a2558c81a835937843"
    }
  ],
  "formal_continuity_anchor": {
    "chapter_id": 270,
    "date": "1993-09-17"
  },
  "overall": "REVISE_REQUIRED",
  "issues": [
    "chapter_284: 角色姓名未获本章character_id授权：托马斯"
  ]
}
