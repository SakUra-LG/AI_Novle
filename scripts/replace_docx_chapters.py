from __future__ import annotations

import argparse
import copy
import json
import os
import re
from pathlib import Path

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph


HEADING_RE = re.compile(r"^\s*第\s*(\d+)\s*章(?:\s|[:：]|$)")


def make_paragraph(text: str, template_ppr):
    paragraph = OxmlElement("w:p")
    if template_ppr is not None:
        paragraph.append(copy.deepcopy(template_ppr))
    if text:
        run = OxmlElement("w:r")
        node = OxmlElement("w:t")
        if text[:1].isspace() or text[-1:].isspace():
            node.set(qn("xml:space"), "preserve")
        node.text = text
        run.append(node)
        paragraph.append(run)
    return paragraph


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("docx", type=Path)
    parser.add_argument("replacements", type=Path)
    parser.add_argument("--synopses", type=Path)
    parser.add_argument("--min-chars", type=int, default=1000)
    args = parser.parse_args()

    raw = json.loads(args.replacements.read_text(encoding="utf-8"))
    replacements = {int(k): v for k, v in raw.items()}
    titles = {}
    if args.synopses:
        synopsis_items = json.loads(args.synopses.read_text(encoding="utf-8"))
        titles = {int(item["chapter_id"]): item.get("chapter_title", "") for item in synopsis_items}
    for chapter, paragraphs in replacements.items():
        count = len(re.sub(r"\s+", "", "".join(paragraphs)))
        if count > 1600:
            raise ValueError(f"chapter {chapter} exceeds 1600 Chinese characters: {count}")
        if count < args.min_chars:
            raise ValueError(f"chapter {chapter} is shorter than {args.min_chars} Chinese characters: {count}")

    document = Document(args.docx)
    heading_nodes = {}
    for paragraph in document.paragraphs:
        match = HEADING_RE.match(paragraph.text.strip())
        if match:
            heading_nodes[int(match.group(1))] = paragraph._p

    for chapter in sorted(replacements, reverse=True):
        heading = heading_nodes.get(chapter)
        if heading is None:
            raise KeyError(f"chapter heading not found: {chapter}")
        if chapter in titles and titles[chapter]:
            Paragraph(heading, document._body).text = f"第{chapter}章  {titles[chapter]}"
        sibling = heading.getnext()
        body_nodes = []
        while sibling is not None:
            if sibling.tag == qn("w:p"):
                text = "".join(part.text or "" for part in sibling.iter(qn("w:t"))).strip()
                if HEADING_RE.match(text):
                    break
            body_nodes.append(sibling)
            sibling = sibling.getnext()
        template_ppr = None
        for node in body_nodes:
            if node.tag == qn("w:p"):
                template_ppr = node.find(qn("w:pPr"))
                break
        anchor = body_nodes[-1] if body_nodes else heading
        for node in body_nodes:
            node.getparent().remove(node)
        anchor = heading
        for text in replacements[chapter] + [""]:
            new_node = make_paragraph(text, template_ppr)
            anchor.addnext(new_node)
            anchor = new_node

    temp = args.docx.with_name(args.docx.stem + ".codex-editing.docx")
    document.save(temp)
    os.replace(temp, args.docx)
    print(json.dumps({"updated": sorted(replacements)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
