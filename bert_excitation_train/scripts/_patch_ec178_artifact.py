from pathlib import Path
p=Path("bert_excitation_train/outputs_pop_king_v6_compiled_story_first_500/chapters/chapter_355.txt")
s=p.read_text(encoding="utf8")
s += "\n\n登记册正式创建对象《瑟琳娜独立创作过程实录》，以学院档案中的原名记录，不改变她在项目中的称呼。"
p.write_text(s,encoding="utf8")

