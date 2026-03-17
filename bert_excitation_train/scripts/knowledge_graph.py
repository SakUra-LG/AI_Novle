#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
重生复仇小说知识图谱模块
用于前后一致性、伏笔回收。本地 JSON 存储，支持按章节追溯与回滚。
"""

import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Set, Any

# 特殊来源：梗概预构建
SOURCE_OUTLINE = "outline"

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GRAPH_PATH = PROJECT_ROOT / "outputs" / "knowledge_graph.json"


class RebirthKnowledgeGraph:
    """重生小说知识图谱"""

    def __init__(self, graph_path: Optional[Path] = None):
        self.graph_path = Path(graph_path) if graph_path else DEFAULT_GRAPH_PATH
        # 实体: id -> {name, type, source_chapters: [ch|"outline"], desc?}
        self.entities: Dict[str, Dict[str, Any]] = {}
        # 关系: [{subject_id, predicate, object_id, source_chapters, desc?}]
        self.relationships: List[Dict[str, Any]] = []
        # 伏笔: [{content, plant_chapter, recover_chapter?, source_chapters, desc?}]
        self.foreshadowing: List[Dict[str, Any]] = []
        # 实体名到 id 的映射，便于去重
        self._name_to_id: Dict[str, str] = {}

    def _norm_source(self, ch: Any) -> str:
        return str(ch) if ch != SOURCE_OUTLINE else SOURCE_OUTLINE

    def _entity_id(self, name: str, etype: str = "person") -> str:
        key = f"{etype}:{name}"
        if key in self._name_to_id:
            eid = self._name_to_id[key]
            if eid in self.entities:
                return eid
            del self._name_to_id[key]
        eid = f"e{len(self.entities)}"
        self._name_to_id[key] = eid
        return eid

    def add_entity(self, name: str, etype: str, source: Any, desc: str = "") -> str:
        """添加实体，source 为章节号或 SOURCE_OUTLINE。返回实体 id。"""
        if not name or len(name.strip()) < 2:
            return ""
        name = name.strip()
        eid = self._entity_id(name, etype)
        src = self._norm_source(source)
        if eid in self.entities:
            rec = self.entities[eid]
            if src not in rec.get("source_chapters", []):
                rec.setdefault("source_chapters", []).append(src)
            if desc and desc not in (rec.get("desc") or ""):
                rec["desc"] = (rec.get("desc") or "") + (" " + desc if rec.get("desc") else desc)
        else:
            self.entities[eid] = {
                "name": name,
                "type": etype,
                "source_chapters": [src],
                "desc": desc or "",
            }
        return eid

    def add_relationship(
        self,
        subject: str,
        predicate: str,
        obj: str,
        source: Any,
        desc: str = "",
    ) -> None:
        """添加关系。subject/obj 为实体名，predicate 如 被陷害、信任、仇恨。"""
        if not (subject and predicate and obj):
            return
        subj_id = self._entity_id(subject, "person")
        obj_id = self._entity_id(obj, "person")
        src = self._norm_source(source)
        for r in self.relationships:
            if r["subject_id"] == subj_id and r["predicate"] == predicate and r["object_id"] == obj_id:
                if src not in r.get("source_chapters", []):
                    r.setdefault("source_chapters", []).append(src)
                return
        self.relationships.append({
            "subject_id": subj_id,
            "subject": subject,
            "predicate": predicate,
            "object_id": obj_id,
            "object": obj,
            "source_chapters": [src],
            "desc": desc or "",
        })

    def add_foreshadowing(
        self,
        content: str,
        source: Any,
        plant_chapter: Optional[int] = None,
        recover_chapter: Optional[int] = None,
        desc: str = "",
    ) -> None:
        """添加伏笔。content 为伏笔内容，plant_chapter 埋下章节，recover_chapter 待回收章节。"""
        if not content or len(content.strip()) < 2:
            return
        src = self._norm_source(source)
        for f in self.foreshadowing:
            if f.get("content", "").strip() == content.strip():
                if src not in f.get("source_chapters", []):
                    f.setdefault("source_chapters", []).append(src)
                if recover_chapter is not None:
                    f["recover_chapter"] = recover_chapter
                return
        self.foreshadowing.append({
            "content": content.strip(),
            "plant_chapter": plant_chapter,
            "recover_chapter": recover_chapter,
            "source_chapters": [src],
            "desc": desc or "",
        })

    def _has_source_in(self, source_chapters: List[str], to_remove: Set[str]) -> bool:
        return any(s in to_remove for s in source_chapters)

    def remove_records_by_chapters(self, chapters: List[int]) -> int:
        """
        删除来源包含指定章节的所有记录。
        多来源记录：只删除对应来源，若删光则移除整条。
        返回删除的记录条数。
        """
        to_remove = {str(c) for c in chapters}
        removed = 0

        # 实体
        to_del = []
        for eid, ent in list(self.entities.items()):
            srcs = ent.get("source_chapters", [])
            if not srcs:
                continue
            new_srcs = [s for s in srcs if s not in to_remove]
            if not new_srcs:
                to_del.append(eid)
                removed += 1
            elif len(new_srcs) < len(srcs):
                ent["source_chapters"] = new_srcs
        for eid in to_del:
            del self.entities[eid]
            for k, v in list(self._name_to_id.items()):
                if v == eid:
                    del self._name_to_id[k]
                    break

        # 关系
        new_rel = []
        for r in self.relationships:
            srcs = r.get("source_chapters", [])
            new_srcs = [s for s in srcs if s not in to_remove]
            if not new_srcs:
                removed += 1
            else:
                r["source_chapters"] = new_srcs
                new_rel.append(r)
        self.relationships = new_rel

        # 伏笔
        new_f = []
        for f in self.foreshadowing:
            srcs = f.get("source_chapters", [])
            new_srcs = [s for s in srcs if s not in to_remove]
            if not new_srcs:
                removed += 1
            else:
                f["source_chapters"] = new_srcs
                new_f.append(f)
        self.foreshadowing = new_f

        return removed

    def query_relevant_for_chapter(self, chapter_num: int) -> str:
        """
        查询与第 chapter_num 章相关的知识，返回可拼入 prompt 的文本。
        设计原则：图谱只提供「全局设定 + 关键伏笔」，避免噪音。
        """
        lines = []
        ch_str = str(chapter_num)
        # 1）全局设定：时代 / 背景 / 主角名（写死或从实体中提取）
        world_line = "【世界观】现代都市背景；主线为职场+医疗复仇；女主：沈清欢。"
        lines.append(world_line)

        # 2）伏笔：只展示尚未回收的关键伏笔；若当前章 >= recover_chapter，则认为已回收并移除
        new_foreshadowing = []
        for f in self.foreshadowing:
            rc = f.get("recover_chapter")
            srcs = f.get("source_chapters", [])
            # 已到或超过回收章节：认为伏笔已回收，从图谱中删除
            if rc is not None and str(rc).isdigit() and chapter_num >= int(rc):
                continue
            new_foreshadowing.append(f)
            # 与当前章相关的伏笔：埋下章节 == 当前章 或 recover_chapter == 当前章 或 来源包含当前章
            plant = f.get("plant_chapter")
            if (
                plant == chapter_num
                or (rc is not None and str(rc).isdigit() and int(rc) == chapter_num)
                or ch_str in srcs
            ):
                lines.append(f"【关键伏笔】{f.get('content', '')}")
        # 持久更新：移除已回收伏笔，避免图谱越来越乱
        self.foreshadowing = new_foreshadowing

        # 不再把所有实体/关系都塞进提示词，只依赖上面的全局设定 + 关键伏笔
        if not lines:
            return ""
        # 限制输出条数，避免提示词过长
        return "【知识图谱-本章相关】\n" + "\n".join(lines[:15])

    def save(self) -> Path:
        """保存到 JSON 文件"""
        self.graph_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "entities": self.entities,
            "relationships": self.relationships,
            "foreshadowing": self.foreshadowing,
            "name_to_id": self._name_to_id,
        }
        with open(self.graph_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return self.graph_path

    def load(self) -> bool:
        """从 JSON 文件加载，若文件不存在返回 False"""
        if not self.graph_path.exists():
            return False
        with open(self.graph_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.entities = data.get("entities", {})
        self.relationships = data.get("relationships", [])
        self.foreshadowing = data.get("foreshadowing", [])
        self._name_to_id = data.get("name_to_id", {})
        return True

    def extract_from_outline(self, text: str, chapter: Any) -> None:
        """从梗概文本中抽取实体与关系。chapter 为章节号或 SOURCE_OUTLINE。"""
        # 常见人物
        chars = [
            "沈清欢", "林修远", "赵明轩", "陈主任", "张主任", "王秘书", "主治医师",
            "护士长", "经理", "院长", "丈夫", "男友", "未婚夫", "女主", "同事",
            "主管", "陷害者", "旧友", "IT高手",
        ]
        for c in chars:
            if c in text:
                self.add_entity(c, "person", chapter)
        # 常见地点
        places = ["ICU", "病房", "医院", "公司", "会议室", "办公室", "茶水间", "咖啡厅", "年会", "法庭"]
        for p in places:
            if p in text:
                self.add_entity(p, "place", chapter)
        # 简单关系：从"被XX" "XX陷害"等
        patterns = [
            (r"(\S+)\s*陷害\s*(\S+)", "陷害"),
            (r"(\S+)\s*被\s*(\S+)\s*", "被陷害"),
            (r"(\S+)\s*背叛\s*(\S+)", "背叛"),
        ]
        for pat, pred in patterns:
            for m in re.finditer(pat, text):
                g = m.groups()
                if len(g) >= 2 and len(g[0]) >= 2 and len(g[1]) >= 2:
                    self.add_relationship(g[0], pred, g[1], chapter)

    def extract_from_outline_json(self, card: Dict, chapter: int) -> None:
        """从 master_ctx_final 的 JSON 卡中抽取"""
        present = card.get("present") or {}
        binding = card.get("binding") or {}
        if isinstance(present, str):
            present = {}
        if isinstance(binding, str):
            binding = {}
        mainline = str(present.get("present_mainline", ""))
        trigger = str(present.get("flashback_trigger", ""))
        revenge = str(present.get("revenge_action", "") or present.get("revenue_action", ""))
        text = mainline + " " + trigger + " " + revenge
        self.extract_from_outline(text, chapter)
        past_harm = str(binding.get("past_core_harm", ""))
        counter = str(binding.get("present_counterstrike", ""))
        if past_harm:
            self.add_foreshadowing(past_harm[:80], chapter, plant_chapter=chapter, desc="上一世受害")
        if counter:
            self.add_foreshadowing(counter[:80], chapter, desc="今生反制")

    def extract_from_chapter_body(self, text: str, chapter: int) -> None:
        """规则抽取（备用）。建议使用 extract_from_chapter_body_with_llm。"""
        chars = [
            "沈清欢", "林修远", "赵明轩", "陈主任", "张主任", "王秘书", "主治医师",
            "护士长", "经理", "院长", "丈夫", "男友", "未婚夫", "女主",
        ]
        for c in chars:
            if c in text:
                self.add_entity(c, "person", chapter)
        places = ["ICU", "病房", "医院", "公司", "会议室", "办公室", "茶水间", "咖啡厅"]
        for p in places:
            if p in text:
                self.add_entity(p, "place", chapter)
        for m in re.finditer(r"[^。！？]*?(留下|记录|保存|证据|备份)[^。！？]*[。！？]", text):
            s = m.group(0).strip()
            if len(s) > 10:
                self.add_foreshadowing(s[:100], chapter, plant_chapter=chapter)

    def _parse_llm_json(self, raw: str) -> Optional[Dict]:
        """从大模型输出中解析 JSON，支持 ```json ... ``` 包裹"""
        s = (raw or "").strip()
        m = re.search(r"```(?:json)?\s*([\s\S]*?)```", s)
        if m:
            s = m.group(1).strip()
        try:
            return json.loads(s)
        except json.JSONDecodeError:
            pass
        # 尝试找 { ... }
        m = re.search(r"\{[\s\S]*\}", s)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
        return None

    def extract_from_outline_with_llm(
        self, text: str, chapter: Any, call_api_fn, prev_life_text: str = ""
    ) -> bool:
        """
        用大模型从梗概/线索文本中抽取**全局设定 + 关键伏笔**。
        目标：减少噪音，只记录对全书长期有效、可能影响前后一致性的内容。
        call_api_fn(prompt: str) -> str，返回模型输出。
        """
        prompt = f"""你是一个知识图谱抽取专家。请从下面第{chapter}章的梗概及对应上一世线索中，只抽取：
1）本书在大部分章节都不变的【全局设定】（时代、城市/行业背景、主角姓名、主要势力/机构名等）
2）对后文有长期影响的【关键伏笔】（比如重要证据、神秘组织、隐藏身份、长期悬而未决的问题）
禁止为一次性路人、小地点、小冲突创建实体或关系。

【梗概/线索文本】
{text}
"""
        if prev_life_text:
            prompt += f"""
【上一世对应线索】
{prev_life_text}
"""
        prompt += """
请严格按以下 JSON 格式输出，不要输出其他内容：
```json
{
  "entities": [
    {"name": "实体名（仅限主角/重要反派/关键组织/全书都会出现的地点）", "type": "person/place/org/setting"}
  ],
  "relationships": [
    {"subject": "主语（仅限全局重要人物/组织）", "predicate": "关系词如陷害/隶属/控制", "object": "宾语"}
  ],
  "foreshadowing": [
    {"content": "长期伏笔内容简述（跨多章才会被回收）", "recover_chapter": 待回收章节号或null}
  ]
}
```
要求：
- 实体：只保留**全局稳定**的设定（主角名、核心反派、关键组织、行业/时代设定等），每章最多 5 个。
- 关系：只保留长期不变的关系（如某人是某院长、某组织控制某医院等），不要临时吵架/职场小冲突。
- 伏笔：只记录**跨多章的长期伏笔**（例如某个重要证据、神秘账户、神秘“天启”组织等），不要记录本章就解决的小问题。
"""
        out = call_api_fn(prompt)
        if not out:
            return False
        data = self._parse_llm_json(out)
        if not data or not isinstance(data, dict):
            return False
        src = self._norm_source(chapter)
        for e in data.get("entities") or []:
            if isinstance(e, dict) and e.get("name"):
                self.add_entity(
                    str(e["name"]).strip(),
                    str(e.get("type", "person")).lower() or "person",
                    chapter,
                )
        for r in data.get("relationships") or []:
            if isinstance(r, dict) and r.get("subject") and r.get("object") and r.get("predicate"):
                self.add_relationship(
                    str(r["subject"]).strip(),
                    str(r["predicate"]).strip(),
                    str(r["object"]).strip(),
                    chapter,
                )
        for f in data.get("foreshadowing") or []:
            if isinstance(f, dict) and f.get("content"):
                rc = f.get("recover_chapter")
                rc = int(rc) if rc is not None and str(rc).isdigit() else None
                self.add_foreshadowing(
                    str(f["content"]).strip()[:150],
                    chapter,
                    plant_chapter=int(chapter) if str(chapter).isdigit() else None,
                    recover_chapter=rc,
                )
        return True

    def extract_from_chapter_body_with_llm(self, text: str, chapter: int, call_api_fn) -> bool:
        """
        用大模型从正文中抽取实体、关系、伏笔。
        call_api_fn(prompt: str) -> str，返回模型输出。
        """
        # 限制长度避免超长
        snippet = text[:3000] if len(text) > 3000 else text
        prompt = f"""你是一个知识图谱抽取专家。请从下面第{chapter}章的小说正文中，抽取与「长期一致性」相关的信息。
重点只关注：
1）会在后文回收的伏笔/线索（证据、录音、关键物品、隐秘身份等）
2）极少量的核心人物/组织（如女主、核心反派、关键医院/公司），不要为路人、小配角建实体。

【正文片段】
{snippet}
"""
        prompt += """
请严格按以下 JSON 格式输出，不要输出其他内容：
```json
{
  "entities": [
    {"name": "人物或组织名（仅限女主/核心反派/关键医院或公司）", "type": "person或org"}
  ],
  "relationships": [
    {"subject": "主语（仅限核心人物/组织）", "predicate": "关系词", "object": "宾语"}
  ],
  "foreshadowing": [
    {"content": "埋下的伏笔或线索简述（若本章已经回收则不要算伏笔）", "recover_chapter": null}
  ]
}
```
要求：
- 实体：只保留极少量核心人物/组织，每章不超过 3 个；一般路人、小配角、小地点全部忽略。
- 关系：只保留会多次出现、影响大局的人物/组织关系，不要记录一次性冲突。
- 伏笔：只记录本章新埋下、后文还没回收的线索；若本章已经把线索用完，就不要当作伏笔输出。
"""
        out = call_api_fn(prompt)
        if not out:
            return False
        data = self._parse_llm_json(out)
        if not data or not isinstance(data, dict):
            return False
        # 只添加极少量核心实体/关系：限定在白名单中
        core_names = {"沈清欢", "林修远", "赵明轩"}
        for e in data.get("entities") or []:
            if isinstance(e, dict) and e.get("name"):
                name = str(e["name"]).strip()
                if name in core_names:
                    self.add_entity(
                        name,
                        str(e.get("type", "person")).lower() or "person",
                        chapter,
                    )
        for r in data.get("relationships") or []:
            if isinstance(r, dict) and r.get("subject") and r.get("object") and r.get("predicate"):
                subj = str(r["subject"]).strip()
                obj = str(r["object"]).strip()
                if subj in core_names or obj in core_names:
                    self.add_relationship(
                        subj,
                        str(r["predicate"]).strip(),
                        obj,
                        chapter,
                    )
        for f in data.get("foreshadowing") or []:
            if isinstance(f, dict) and f.get("content"):
                rc = f.get("recover_chapter")
                rc = int(rc) if rc is not None and str(rc).isdigit() else None
                self.add_foreshadowing(
                    str(f["content"]).strip()[:150],
                    chapter,
                    plant_chapter=chapter,
                    recover_chapter=rc,
                )
        return True
