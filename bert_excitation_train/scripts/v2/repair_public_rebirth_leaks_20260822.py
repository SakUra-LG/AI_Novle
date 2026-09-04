from pathlib import Path
import re

ROOT = Path(r"D:\Study\College\Scientific research\张颖——AI小说自动生成\张颖——AI小说自动生成\bert_excitation_train\AI_Novle\bert_excitation_train\outputs_pop_king_v6_compiled_story_first_500\chapters")
repls = {
    "\u4e0a\u4e00\u4e16": "\u8fc7\u53bb\u90a3\u6b21",
    "\u524d\u4e16": "\u8fc7\u53bb\u7684\u8bb0\u5f55",
    "\u8fd9\u8f88\u5b50": "\u8fd9\u4e00\u6b21",
    "\u91cd\u751f": "\u91cd\u65b0\u5f00\u59cb",
}
changed = []
for no in range(21, 201):
    p = ROOT / f"chapter_{no:03d}.txt"
    t = p.read_text(encoding="utf-8")
    lines = []
    dirty = False
    for line in t.splitlines(keepends=True):
        if "\u201c" in line and any(k in line for k in repls):
            old = line
            for a, b in repls.items():
                line = line.replace(a, b)
            dirty |= line != old
        lines.append(line)
    if dirty:
        p.write_text("".join(lines), encoding="utf-8", newline="\n")
        changed.append(no)
print("public rebirth leaks repaired:", changed)
