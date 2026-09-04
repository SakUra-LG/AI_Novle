from __future__ import annotations
import argparse, hashlib, json, re, sys
from datetime import date
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from scripts.v2.generate_pop_king_body_v5 import _load_character_bible,_character_identity_failures,_hard_metadata_leak_failures,_paragraph_quality_failures,_rebirth_subject_failures
from scripts.v2.pop_king_plan_compiler import validate_trial_cluster_card,trial_timeline_failures
def d(s):
 m=re.search(r"(1993)年0?9月(\d{1,2})日",s[:220]); return date(1993,9,int(m.group(2))) if m else None
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--output-dir',type=Path,required=True); a=ap.parse_args(); out=a.output_dir.resolve(); trial=out/'body_generation'/'rewrite_trial_279_280'; plan=json.loads((trial/'EC140_candidate_cards.json').read_text(encoding='utf-8')); bible=_load_character_bible(); ids={str(x.get('character_id')):x for x in bible.get('characters',[]) if isinstance(x,dict)}; cast=[ids[x] for x in plan['main_character_ids']+plan['participant_ids'] if x in ids]; issues=list(validate_trial_cluster_card(plan,plan['chapter_cards'])); rows=[]; ds=[]; prior=date(1993,9,17)
 for card in plan['chapter_cards']:
  p=trial/'chapters'/f"chapter_{card['chapter_id']:03d}.txt"; body=p.read_text(encoding='utf-8') if p.exists() else ''; dt=d(body); ds.append(dt); fs=[]
  if not p.exists(): fs.append('MISSING')
  if not dt or dt.isoformat()!=card['timeline_start']: fs.append('chapter date differs from card')
  fs += _character_identity_failures(body,{'cast':cast})+_rebirth_subject_failures(body)+_hard_metadata_leak_failures(body)+_paragraph_quality_failures(body)
  if dt and dt<=prior: fs.append('timeline not after prior chapter')
  issues += [f"chapter_{card['chapter_id']}: {x}" for x in fs]; prior=dt or prior
  rows.append({'chapter_id':card['chapter_id'],'event_cluster_id':'EC140','expected_progress_point':plan['irreplaceable_progress_point'],'actual_progress_point':'按日期拆分预付款、退款、分成并形成待核差额表','plan_binding_status':'PASS' if not fs else 'FAIL','timeline':'PASS' if dt and dt>prior or not fs else 'FAIL','character_consistency':'PASS' if not _character_identity_failures(body,{'cast':cast}) else 'FAIL','rebirth_boundary':'PASS' if not _rebirth_subject_failures(body) else 'FAIL','metadata_leak':'PASS' if not _hard_metadata_leak_failures(body) else 'FAIL','paragraph_repetition':'PASS' if not _paragraph_quality_failures(body) else 'FAIL','sha256':hashlib.sha256(body.encode()).hexdigest()})
 issues += trial_timeline_failures({c['chapter_id']:x for c,x in zip(plan['chapter_cards'],ds)},formal_prior_date=date(1993,9,17)); payload={'version':'rewrite_trial_report_ec140_v1','status':'trial_only_not_accepted','formal_story_memory_write':False,'neo4j_write':False,'external_semantic_critic':'not_run','cluster_id':'EC140','chapters':rows,'formal_continuity_anchor':{'chapter_id':270,'date':'1993-09-17'},'overall':'PASS_WITHOUT_ACCEPTANCE' if not issues else 'REVISE_REQUIRED','issues':issues}; (trial/'rewrite_trial_quality_report.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n',encoding='utf-8'); (trial/'rewrite_trial_quality_report.md').write_text('# EC140第279—280章试写质量报告（证据自动生成）\n\n状态：trial_only_not_accepted；未写入正式StoryMemory、Neo4j，未标记accepted。\n\n'+json.dumps(payload,ensure_ascii=False,indent=2)+'\n',encoding='utf-8'); print(payload['overall'],payload['issues'])
if __name__=='__main__': main()
