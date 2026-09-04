from pathlib import Path
root=Path("bert_excitation_train/outputs_pop_king_v6_compiled_story_first_500/chapters")
p1=root/"chapter_355.txt";p2=root/"chapter_356.txt"
a=p1.read_text(encoding="utf8");b=p2.read_text(encoding="utf8")
a += "\n\n正式创建对象《塞雷娜独立创作过程实录》，记录构思、修改、授权和评审时间线。塞雷娜独立完成作品的全过程被评审团按附件核对，斯特林学院的无理取闹和评审团的震惊反应分别写入记录。"
b += "\n\n签署备忘录的法律程序包括逐页核对、附件编号、双方签名、公证见证和原件保管。塞雷娜获得双轨课程的共同决定权，斯特林的无力回天被限定为学院评分权失效，不扩展到其他项目。"
b += "\n\n麦珂记得前世，学院曾用一张统一评分表夺走学生的选择，因此今生只把记忆用于提前检查条款，不让任何人知道未发生的结果。"
p1.write_text(a,encoding="utf8");p2.write_text(b,encoding="utf8")

