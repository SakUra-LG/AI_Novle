"""Generate evidence-only reports for isolated two-chapter candidate clusters."""
from __future__ import annotations
import argparse, hashlib, json, re, sys
from datetime import date
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from scripts.v2.generate_pop_king_body_v5 import (_load_character_bible,_character_identity_failures,_hard_metadata_leak_failures,_paragraph_quality_failures,_rebirth_subject_failures)
from scripts.v2.pop_king_plan_compiler import validate_trial_cluster_card,trial_timeline_failures
def parse_date(s):
 m=re.search(r"(1993|1994)年0?([1-9]|1[0-2])月(\d{1,2})日",s[:240]); return date(int(m.group(1)),int(m.group(2)),int(m.group(3))) if m else None
def report(out:Path, trial:Path)->dict:
 plan=json.loads(next(trial.glob("*candidate_cards.json")).read_text(encoding='utf-8')); cards=plan['chapter_cards']; registry=trial/'trial_character_registry.json'; extras=[]
 if registry.exists(): extras=json.loads(registry.read_text(encoding='utf-8')).get('characters',[])
 validation_plan=dict(plan); validation_plan.setdefault('chapter_span',[int(x['chapter_id']) for x in cards]); validation_plan['canonical_cast']=list(plan.get('canonical_cast',[]))+extras
 bible=_load_character_bible(); ids={str(x.get('character_id')):x for x in bible.get('characters',[]) if isinstance(x,dict)}; cast=[ids[x] for x in plan.get('main_character_ids',[])+plan.get('participant_ids',[]) if x in ids]+extras; issues=list(validate_trial_cluster_card(validation_plan,cards)); rows=[]; dates={}; prior=date(1993,9,17)
 for card in cards:
  cid=int(card['chapter_id']); p=trial/'chapters'/f'chapter_{cid:03d}.txt'; body=p.read_text(encoding='utf-8') if p.exists() else ''; dt=parse_date(body); dates[cid]=dt; fs=[]
  if not p.exists(): fs.append('MISSING')
  if not dt or dt.isoformat()!=card['timeline_start']: fs.append('chapter date differs from card')
  if dt and dt<=prior: fs.append('timeline not after prior chapter')
  fs += _character_identity_failures(body,{'cast':cast,'canonical_cast':cast})+_rebirth_subject_failures(body)+_hard_metadata_leak_failures(body)+_paragraph_quality_failures(body)
  issues += [f'chapter_{cid}: {x}' for x in fs]; prior=dt or prior
  rows.append({'chapter_id':cid,'event_cluster_id':plan['cluster_id'],'expected_progress_point':plan['irreplaceable_progress_point'],'actual_progress_point':'candidate prose present; evidence checks applied','plan_binding_status':'PASS' if not fs else 'FAIL','timeline':'PASS' if dt and not any('timeline' in x for x in fs) else 'FAIL','character_consistency':'PASS' if not _character_identity_failures(body,{'cast':cast,'canonical_cast':cast}) else 'FAIL','rebirth_boundary':'PASS' if not _rebirth_subject_failures(body) else 'FAIL','metadata_leak':'PASS' if not _hard_metadata_leak_failures(body) else 'FAIL','paragraph_repetition':'PASS' if not _paragraph_quality_failures(body) else 'FAIL','sha256':hashlib.sha256(body.encode()).hexdigest()})
 issues += trial_timeline_failures(dates,formal_prior_date=date(1993,9,17)); return {'version':'isolated_trial_report_v1','status':'trial_only_not_accepted','formal_story_memory_write':False,'neo4j_write':False,'external_semantic_critic':'not_run','cluster_id':plan['cluster_id'],'chapters':rows,'formal_continuity_anchor':{'chapter_id':270,'date':'1993-09-17'},'overall':'PASS_WITHOUT_ACCEPTANCE' if not issues else 'REVISE_REQUIRED','issues':issues}
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--output-dir',type=Path,required=True); ap.add_argument('--trial-dir',action='append',required=True); a=ap.parse_args(); out=a.output_dir.resolve()
 for name in a.trial_dir:
  trial=out/'body_generation'/name; payload=report(out,trial); (trial/'rewrite_trial_quality_report.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n',encoding='utf-8'); (trial/'rewrite_trial_quality_report.md').write_text('# '+payload['cluster_id']+'隔离试写质量报告（证据自动生成）\n\n状态：trial_only_not_accepted；未写入正式StoryMemory、Neo4j，未标记accepted。\n\n'+json.dumps(payload,ensure_ascii=False,indent=2)+'\n',encoding='utf-8'); print(name,payload['overall'],payload['issues'])
if __name__=='__main__': main()
