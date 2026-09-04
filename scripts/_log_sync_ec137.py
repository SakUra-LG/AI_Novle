from pathlib import Path
out=Path(r"bert_excitation_train/outputs_pop_king_v6_compiled_story_first_500")
p=out/'SECOND_NOVEL_OUTLINE_CODE_IMPROVEMENTS.md'
p.write_text(p.read_text(encoding='utf-8')+'\n\n### 113. 同簇证据术语与最近章重复检测分层\n\n同一证据链相邻事件允许共享必要术语，但应同时比较章节功能与连续片段；相似度保留在审计中，只有达到更强阈值时才阻断，避免把调查链必要名词误判为换词重演。',encoding='utf-8')
p=out/'BODY_BATCH_MANUAL_REVIEW_211_350.md'
p.write_text(p.read_text(encoding='utf-8')+'\n\n### EC137｜第273–274章｜纤维检测与审计阶段结论\n\n- 第273章处理条款驳回、录音记录和取样拒绝；第274章处理专家检测、有限状态变化和报告，未重复EC136开封流程。\n- 已补齐初声基金临时听证室、联邦税务审计局公开听证大厅、斯特林承认原件丢失、纤维检测报告公布、黛安娜晋升及有限否决边界。\n- 逐字通读后删除英文叙述泄漏，状态字段仅保留在任命登记单；报告只对已核副本作欺诈认定，不扩展为全部业务永久失权。\n- 确定性门禁通过；外部语义审稿未运行，原因是无外部模型凭据。EC137正式接受，待同步StoryMemory与Neo4j。',encoding='utf-8')
