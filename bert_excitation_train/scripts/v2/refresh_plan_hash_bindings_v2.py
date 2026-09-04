"""Refresh source hash bindings after the audited date-only correction."""
from __future__ import annotations
import hashlib, json
from pathlib import Path
from datetime import datetime, timezone

ROOT=Path.cwd(); OUT=ROOT/"outputs_pop_king_v6_compiled_story_first_500"

def canon(v): return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(",",":" )).encode("utf8")
def digest(v): return hashlib.sha256(canon(v)).hexdigest()
def walk(x):
    if isinstance(x,dict):
        yield x
        for v in x.values(): yield from walk(v)
    elif isinstance(x,list):
        for v in x: yield from walk(v)

def main():
    ep=OUT/"event_clusters_v2.json"; cp=OUT/"master_ctx_cards_v2.json"
    events=json.loads(ep.read_text(encoding="utf8")); cards=json.loads(cp.read_text(encoding="utf8"))
    by_cluster={e["cluster_id"]:e for e in events}; changes=[]
    for c in cards:
        cid=int(c.get("chapter_id",0)); cluster=str(c.get("cluster_id",""))
        if cid not in (293,294,295,296): continue
        event=by_cluster[cluster]; milestones=event.get("two_chapter_structure") or []
        index=cid-int(event["chapter_span"][0])
        old=c.get("source_event_sha256"); new=digest(event)
        if old!=new: c["source_event_sha256"]=new; changes.append({"chapter_id":cid,"field":"source_event_sha256","old":old,"new":new})
        if 0<=index<len(milestones):
            old=c.get("source_milestone_sha256"); new=digest(milestones[index])
            if old!=new: c["source_milestone_sha256"]=new; changes.append({"chapter_id":cid,"field":"source_milestone_sha256","old":old,"new":new})
    cp.write_text(json.dumps(cards,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    audit=OUT/"body_generation/three_act_trial_v2_293_296/time_correction_audit.json"
    d=json.loads(audit.read_text(encoding="utf8")); d["hash_binding_refresh"]={"at":datetime.now(timezone.utc).isoformat(),"plot_fields_changed":False,"changes":changes}
    audit.write_text(json.dumps(d,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print(json.dumps({"hash_changes":len(changes)},ensure_ascii=False))
if __name__=="__main__": main()
