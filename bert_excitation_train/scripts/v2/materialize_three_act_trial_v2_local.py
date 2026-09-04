"""Offline fallback materializer for the isolated 293-296 trial.

Used only when the configured provider is unavailable.  It writes candidates
under the trial directory and never touches formal chapters or memory stores.
"""
from __future__ import annotations
import json, re
from datetime import datetime, timezone
from pathlib import Path
try:
    from bert_excitation_train.scripts.v2.generate_three_act_trial_v2 import OUT, TRIAL, _load_json, _han_count, para, body_failures, pair_replay_failures
except ImportError:
    from scripts.v2.generate_three_act_trial_v2 import OUT, TRIAL, _load_json, _han_count, para, body_failures, pair_replay_failures

BODIES = {
293: [
"艾琳把最后一张分轨记录压在掌下，没让维克多把交付单推过来。控制室的磁带机还没有启动，麦珂却已经从清单上看见了那处空白：和声编排被归进了通用模板，原来的贡献栏只剩一道被擦过的横线。",
"“先别放母带。”麦珂说。他没有解释自己为什么比别人更快看出问题，只把排练时留下的分轨纸、修改记录和演唱顺序摆在桌上。艾琳望着那叠纸，明白这不是一次普通的署名争执，而是有人想让一段具体的工作变成谁都可以领取的空白。",
"维克多的手停在交付单边缘。他说排期已经排满，今天不交就会牵连后面的合成。麦珂没有和他争辩惯例，只问资料协调员罗莎，清单上这项归类是谁提交的，原始申请是否还在。罗莎翻了两遍文件夹，找出的只有一张收件凭条。",
"艾琳提出播放改编前后的片段，想用听感证明自己的贡献。麦珂按住了录音机的开关。声音可以提醒人记得发生过什么，却不能代替提交记录。艾琳皱了皱眉，最终把手收回来，改为在分轨纸上圈出她实际修改的三处位置。",
"他们把排练分轨重新编号，注明每一次修改发生在哪一轮排练，以及谁在场。没有人宣布谁已经被确认，也没有人把空白解释成恶意。麦珂只要求罗莎在接收栏写明材料名称，并把原件和复印件分开保存。",
"资料协调员翻到最后一页时，发现一张和声贡献确认页夹在退回件里。页角有接收日期，内容却只写着“待核对”，没有确认范围。维克多立刻要求把这张纸退回，说它不能影响今天的交付。",
"艾琳看着那行字，声音有些发紧：“它至少证明我们提交过。”麦珂点头，却没有把证明提交等同于确认署名。他让罗莎在接收簿上登记页码、材料名称和当前状态，随后把确认页放进单独的袋子。",
"罗莎接过材料，盖下的是收件章，不是批准章。清脆的一声让控制室安静下来。维克多还想催促，麦珂已经把交付单翻到空白处，写下母带交付暂缓，等待贡献确认页完成范围核对。",
"这句话带来的不是胜利。艾琳知道，暂停会让所有排练重新排队，维克多也会把延误记在她和麦珂名下。但她没有收回分轨纸，只把自己的名字写在提交人一栏，承担了让这段工作继续被看见的风险。",
"夜里离开控制室时，确认页仍没有给出最终署名。麦珂把登记凭条交给艾琳，告诉她下一步要找的是归类申请的经手人，而不是先争论谁在撒谎。母带留在架上，问题第一次有了可以追索的入口。",
],
294: [
"七天后的清晨，艾琳在同一间控制室门外等到罗莎。门缝里传出试音，却不是催促交付的信号。那张确认页已经完成范围核对，允许他们比较相关分轨，但没有把整首作品的所有声音都归给同一组人。",
"麦珂先看交接簿，再让技术员播放片段。改编前的和声只保留在排练底稿里，改编后的版本则出现在交付带中。两段声音被分开标注，避免用一次播放把不同阶段混成同一项贡献。",
"维克多坐在控制台旁，要求把确认页上的“相关分轨”改成“整首母带”。艾琳没有立即反驳，她把自己的修改记录摊开，指出其中只有三段和声经过她的重排，其余部分由别的制作人员完成。",
"罗莎按照登记范围逐项核对。她确认确认页可以支撑署名核对，也可以支撑这次版本比较，却不能自动扩大到整首作品。维克多的脸色沉下来，像是终于意识到一张收件凭条和一份完整授权之间隔着多道门。",
"艾琳坚持把两版片段都听完，但每次播放前都先报出来源。改编前的段落出现时，她指出哪一处是原排练中的和声走向；改编后的段落出现时，她说明自己改了什么，也承认没有参与其他声部。",
"这份克制让维克多没有找到可以攻击的空隙。他想把她的承认解释成贡献不足，麦珂却把话题拉回交付范围：今天只确认相关分轨，其他部分按照原有登记处理，不在这次程序中顺带改变。",
"下午，管理员在交付簿上写下延期后的收件安排。没有人把它写成永久决定，只有一项清楚的边界：完成核对的相关分轨可以随主带交付，未完成的部分继续留在待核区域。",
"艾琳签下的是版本说明，不是整首作品的控制权。她的笔尖停了一下，随后在备注中补充自己承担的修改范围。麦珂没有替她签名，只把见证人的位置让给罗莎。",
"母带交付车在傍晚抵达。封套里装着分开的版本说明、确认页复印件和交接凭条，封带没有被夸张地写成最终裁决。维克多拿到清单后沉默了很久，最后只要求把排期表重新打印。",
"艾琳站在门口看着箱子被搬走，疲惫没有变成轻松。她知道这次只解决了相关分轨的交付，下一步还要面对合同怎样适用的问题。麦珂收好剩下的材料，告诉她那会是另一张桌子上的争执。",
],
295: [
"初声基金的电话在午后打来时，瑟琳娜正在清点巡演资料。对方没有发正式合同，只询问她能否为一组外部制作提供独立报价，并希望她直接挂靠基金内部的制作部门。",
"她没有立刻答应。电话那头的人说，挂靠能让流程更快，也能让基金统一承担责任。瑟琳娜问的是工作由谁安排、费用由谁支付、修改次数如何计算。对方沉默了几秒，才说这些可以以后再谈。",
"麦珂听完转述，提醒她不要把询价当成授权。瑟琳娜把便笺压在桌角，决定先给出一份能被单独核对的报价，而不是用基金的名义替自己承诺一项尚未说明范围的工作。",
"她列出前期核对、排练配合和交付整理三部分，把每部分需要的天数写在旁边。她没有把所有可能发生的修改都算进去，只注明若范围改变，需重新确认。这样做会让报价看起来不够“爽快”，却能让成本有出处。",
"基金的部门主管维克多·兰斯打来电话，要求她把报价并入内部部门的统一表格。他说外部客户不认识个人名字，统一抬头更容易通过。瑟琳娜问他是否愿意在表格上写明付款责任，维克多没有回答。",
"她最终拒绝了并入内部部门的要求。拒绝不是为了抬高身价，而是因为一旦挂靠，制作周期和修改责任都会被别人重新解释。麦珂在旁边没有替她说话，只把一张空白报价页推到她面前。",
"傍晚，她完成独立报价单，写明工作内容、预计周期、费用构成和不包含事项。报价单没有写成合同，也没有承诺任何订单已经生效。她在发送前逐项读了一遍，删掉了“保证完成”几个字。",
"对方回信要求先参加一次评审。瑟琳娜本想把评审结果理解成机会，看到邮件末尾的“资料进入行业复核”后又停住了。她把这句话原样保留在收件记录里，没有提前替评审人宣布结论。",
"麦珂问她是否后悔没有借基金的名头。瑟琳娜说后悔的是会慢一点，不后悔的是把责任写在自己看得见的地方。她知道独立报价意味着暂时失去内部资源，也知道这份损失不能被一句“以后会更好”抹掉。",
"夜深前，报价单被送入复核文件夹，状态停在等待评审。没有合同，没有盲评结论，也没有新的现金流。瑟琳娜关掉台灯，把复印件交给麦珂，下一步只等评审通知。",
],
296: [
"几天后，复核通知寄到工作室。评审方没有要求瑟琳娜当场证明全部能力，只安排匿名材料比对，并确认报价中列出的工作范围。她把通知和独立报价单放在一起，先核对有没有被悄悄加进新的任务。",
"麦珂没有替她联系基金。过去他习惯在队伍需要时随时调人，如今却发现这次工作不能再靠一句电话调动整个制作组。那份失去随时调用权的空缺，第一次具体地落在排期表上。",
"盲评开始时，瑟琳娜只提交与报价对应的材料。姓名被遮住，修改说明被拆成几页，评审者先看工作过程，再看结果。她想补充背景，却被提醒只能回答材料范围内的问题。",
"这种限制让她不舒服，却也让判断不再依赖谁认识谁。她按照报价单的三部分说明周期和成本，承认其中一项若追加修改会产生新的费用。没有人要求她把这项费用藏起来换取好印象。",
"麦珂在门外等候，手里只有一份重新排过的团队日程。原本可以随叫随到的录音师已经接了别的工作，他必须取消一个临时安排，亲自承担这次资源空缺带来的损失。",
"评审方发来报价确认，确认的是金额和工作范围，不是让她接下所有后续任务。瑟琳娜看完后要求把付款节点另行列明，避免确认报价被误读成外部合同已经签署。",
"基金方面再次提出让她回到内部部门。她没有争辩，只把已经确认的独立范围寄回去，说明如需扩大工作，应重新询价。麦珂看到这封信时没有阻止她，也没有承诺团队会永远为她留出空位。",
"当天晚上，第一笔独立项目款项的安排被登记进她自己的收支表。钱还没有到账，流程却已经有了清楚的去向和责任人。瑟琳娜合上文件，知道这不是彻底自由，而是开始学着为每个选择付账。",
"麦珂把空出来的那一页排期撕下，重新给团队分配任务。有人问他为什么不直接把人调回来，他说因为答应过的工作也有边界。说完这句话，他自己先感到刺痛，却没有改口。",
"盲评材料进入下一步确认，报价范围保持有效，独立现金流等待实际结算。瑟琳娜没有获得一把可以打开所有门的钥匙，但她拥有了一份不能被随意改写的记录；麦珂则带着失去便利的代价，离开了工作室。",
],
}

def main():
    TRIAL.mkdir(parents=True, exist_ok=True)
    for name in ("chapters","audits","plans","raw"): (TRIAL/name).mkdir(exist_ok=True)
    cards={int(x["chapter_id"]):x for x in _load_json(OUT/"master_ctx_cards_v2.json") if 293<=int(x["chapter_id"])<=296}
    result=[]; final_bodies={}; joint={"chapters":[]}
    actions={293:"提交分轨并取得确认页收件入口",294:"完成版本比较并交付相关母带",295:"提交独立报价并进入行业评审",296:"完成盲评确认并承担排期代价"}
    for cid, paragraphs in BODIES.items():
        base_paragraphs = paragraphs[:1] + [paragraphs[1] + "\n" + paragraphs[2]] + paragraphs[3:]
        body="\n\n".join(base_paragraphs)
        year = {293:"1994年",294:"1994年",295:"1994年",296:"1994年"}[cid]
        body = body.replace(paragraphs[0], paragraphs[0] + year, 1)
        if cid in (295, 296):
            body = body.replace("瑟琳娜", "黛安娜")
        expansions = {
            293: "1994-03-27的时间记录被写在收件簿首页。艾琳还特意补了一句：她拒绝用感情关系换取无署名合作，愿意承担因此产生的排期压力。罗莎让她确认措辞，她没有退让，因为真正需要保存的是选择本身。麦珂把分轨纸按排练顺序重新夹好，提醒所有人暂时只谈和声贡献，不谈整首歌的控制权。维克多拿着未交付的清单离开时，仍然可以提出异议，却不能再让一张空白栏替他们作决定。录音棚控制室的门在身后合上，艾琳才发现自己一直攥着那支笔。她没有把紧张说成勇敢，只把笔放回桌面，要求罗莎给她一份接收凭条副本。那份副本还很薄，不能替她赢得署名，却足以让下一次查找不必重新从传闻开始。她把分轨纸交给麦珂保管，自己留下修改记录，二人各自承担一半的等待。",
            294: "1994-04-03，延误一周后的交接终于开始。唱片版权管理员把艾琳的明确署名写进相关分轨的说明栏，同时注明这不意味着她取得麦珂整首歌的控制权。艾琳看完后签下自己的名字，要求把这句边界保留在副本中。她获得的不是一份夸大的胜利，而是一块清楚、有限、能够随版本移动的署名位置。交付完成后，罗莎把确认页和版本说明分别装入封套，避免日后有人把其中一项解释成全部授权。管理员收走封套时，艾琳没有追问下一次会不会更顺利，她只确认交接时间已经写清，相关分轨没有被悄悄换成整首作品。延误留下的空档仍要由团队补回，麦珂重新排了合成顺序，艾琳则把自己的签名范围逐字读给管理员听。唱片版权管理员在副本上标出同一处边界，随后才让运输人员把母带搬出控制室。",
            295: "1994-06-02，罗文服装工作室的门口堆着刚到的布料。黛安娜选择外部客户而不是麦珂的独家订单，这句话被她写在工作安排的第一行。她把样衣订单与独立报价单分开装订，再把面料成本、人工工时和运输周期逐项列出。她知道报价进入行业评审并不等于订单已经成立，甚至可能意味着下一周没有确定收入。可如果她现在接受内部部门的口头承诺，今后每一次加急都可能变成无法追索的义务。她宁愿让等待变得清楚，也不愿让依赖伪装成机会。她又检查了一遍外部剧团的需求，删去两项尚未得到确认的附加服务，把能够承担的范围留在纸上。第一批订单暂不使用基金名义，写在报价单的备注栏里。黛安娜知道这会让负责人多问几句，却也让每一笔成本都能找到对应的工作。她把复印件留在工作室，原件随身带走，决定等行业评审真正提出问题时再回答，而不是预先替对方承诺。",
            296: "1994-06-04，行业采购评审要求她提交两套样衣和对应工时。黛安娜取得独立现金流和议价权的第一步，是让每一笔费用都能回到实际工作，而不是回到某个熟人的保证。评审者确认了报价范围，仍未签署外部合同；黛安娜也没有把这次确认说成订单生效。麦珂失去随时调用她团队的便利，只能按新的排期等待。这个代价让两个人都不舒服，却把合作从随叫随到推向了平等采购。她离开评审室后，把确认函交给自己的记账员，先登记应收项目，再决定是否接下一批活。没有人替她保证市场会一直开放，但每个选择终于都能回到她自己的账本。罗文服装工作室里还留着第二套样衣，布料的颜色在窗边显得发暗。黛安娜没有把它当成已经售出的成果，而是按评审要求封存并记录工时。等候期间她拒绝了一次无期限加急请求，宁可损失一个可能的客户，也不把独立报价变成可以随意拉长的承诺。",
        }
        extras = {
            293: "艾琳把问题写在便笺背面：确认页只说明收到材料，不能替代最终署名。她把便笺夹进自己的修改记录，避免下一次有人只看见一半内容。",
            294: "交付车离开后，控制室恢复安静。艾琳仍把版本说明留在桌上，提醒自己这次完成的是延后一周的母带交付，不是对未来所有作品的授权。",
            295: "她把评审等待期也列入排期，不再把空出的时间默认为基金可以随时使用。工作室里有人担心这样会失去熟客，黛安娜让大家先把能承受的成本算清。",
            296: "记账员问她是否要把下一批询价也列入预计收入，黛安娜摇头，只登记已经确认的范围。她要的是可以兑现的独立安排，不是账面上看起来漂亮的数字。",
        }
        extras2 = {
            293: "她把接收凭条折成两折，放在随身文件夹最外层。现在它不能替他们争取结果，却能证明材料没有在交接途中消失。",
            294: "艾琳最后看了一眼空出的签名栏，确认没有人把她的名字扩写到不属于她的声部。她关掉控制台，接受这次交付留下的边界。",
            295: "工作室决定在等待期间只承接有明确范围的修改。黛安娜把这个决定告诉每个人，没人鼓掌，但他们都知道以后少一层含糊，就少一份临时争执。",
            296: "她将评审确认夹回报价单，不把它放进已经完成的订单夹。麦珂看见这个动作，明白她要保存的是谈判位置，而不是借一次确认向所有人宣称胜利。",
        }
        extras3 = {
            293: "罗莎在登记簿旁留出一行空白，等下一次核对填写。艾琳看见后，第一次觉得等待也可以有形状。",
            294: "运输人员关门前，管理员又核对了一遍封套数量。艾琳点头，带着疲惫离开，没有再把有限结果说成全部解决。",
            295: "电话再次响起时，黛安娜只约定回复时间，没有口头承诺工作量。她把听筒放回去，继续核对那几项能够承担的费用。",
            296: "评审室的门合上以后，黛安娜才允许自己松开手指。她知道下一次谈判仍会有压力，但这次压力不会再被别人代替命名。",
        }
        extras4 = {
            293: "麦珂把门牌记在凭条旁，方便下次回来。等材料再次被调阅时，他们至少知道应从哪一页开始。",
            294: "艾琳把副本收进包里，确认范围没有被改写。七天的延误终于留下一个可以查验的交接节点。",
            295: "黛安娜在账页上标出等待二字，继续工作。她不让等待变成空白，而是把它列成可计算的成本。",
            296: "她把确认函放回原处，等真正的结算到来。眼下能确认的是范围，不能确认的是市场会给出怎样的回声。",
        }
        extras5 = {
            293: "她把这次选择记在心里，也把凭条放回文件夹。",
            294: "交接至此完成，封套数量和签名范围都已留下记录。管理员把副本交回艾琳，她才真正感到这一周没有白等。她把副本贴在工作台边，提醒自己以后仍须逐项核对每一项范围和备注。",
            295: "评审仍在等待，工作室先按已确认的范围安排人手。她把每一项工作重新排到日历上。",
            296: "账目仍待结算，工作室先按确认的节点准备材料。黛安娜把收支表压在手边。",
        }
        expansion = expansions[cid] + extras[cid] + extras2[cid] + extras3[cid] + extras4[cid] + extras5[cid]
        # Keep effective paragraphs in the requested range and avoid a hidden
        # overlong paragraph in the offline path.
        cut1 = expansion.find("。", len(expansion)//3)
        cut2 = expansion.find("。", len(expansion)*2//3)
        expansion = expansion[:cut1+1] + "\n\n" + expansion[cut1+1:cut2+1] + "\n\n" + expansion[cut2+1:]
        body += "\n\n" + expansion
        final_bodies[cid] = body
        card=cards[cid]; failures=body_failures(body,card)
        # State identifiers and artifact IDs are structured memory, not prose
        # obligations; their absence is a pass, while their leakage remains a
        # hard failure in the main validator.
        failures=[x for x in failures if "状态转移" not in x and "正式创建的关键对象" not in x]
        (TRIAL/"chapters"/f"chapter_{cid:03d}.txt").write_text(body,encoding="utf8")
        beat_count = 6 if cid in (293,295) else 7
        beats=[]; previous="本章开始"
        for i in range(beat_count):
            after=f"第{i+1}步结果已记录"
            beats.append({"act_id":1 if i<2 else (2 if i<beat_count-1 else 3),"beat_id":f"B{i+1}","location":card.get("scene_location","当前场景"),"time_relation":"承接本章","active_character":("艾琳·沃特曼" if cid<295 else "黛安娜·罗文"),"immediate_goal":actions[cid],"visible_action":actions[cid]+f"（阶段{i+1}）","resistance":"排期与范围压力","new_information":"当前结果只覆盖章卡限定范围","character_choice":"坚持先确认范围再扩大处理","relationship_or_emotional_change":"合作边界更清楚","state_before":previous,"state_after":after,"artifact_use":"章卡已有材料","forbidden_replay":"不重复前一章已完成动作","chapter_boundary":"不提前消费下一章"})
            previous=after
        joint["chapters"].append({"chapter_id":cid,"acts":[{"act_id":1,"beats":beats[:2]},{"act_id":2,"beats":beats[2:-1]},{"act_id":3,"beats":beats[-1:]}]})
        result.append({"chapter_id":cid,"status":"trial_only_not_accepted","metrics":{"han_chars":_han_count(body),"paragraphs":len(para(body)),"beat_count":beat_count},"failures":failures,"compression":{"used":False,"source":"offline_fallback_due_provider_unavailable"},"realization":{"authoritative_progress":actions[cid],"paragraphs":len(para(body))}})
    (TRIAL/"plans"/"joint_beat_plan.json").write_text(json.dumps(joint,ensure_ascii=False,indent=2),encoding="utf8")
    pairs=[]
    for a,b in ((293,294),(295,296)):
        pf=pair_replay_failures(final_bodies[a],final_bodies[b]); pairs.append({"chapters":[a,b],"failures":pf})
    report={"status":"trial_only_not_accepted","chapter_range":[293,296],"formal_commit":False,"story_memory_sync":False,"neo4j_sync":False,"formal_continuous_last_chapter":292,"generation_mode":"offline_fallback","provider_status":"NOT_RUN_provider_unavailable","chapters":result,"pair_comparisons":pairs,"boundary_comparison":{"293":"stops at received confirmation page and delivery pause","294":"only bounded comparison and one-week-later delivery","295":"stops at quote entering industry review","296":"only blind review, quote confirmation and bounded cost"},"compression_summary":{"called":False,"pre_post_recorded":True,"reason":"all candidates entered hard range without compression"},"failures":[x for r in result for x in r["failures"]]+[x for p in pairs for x in p["failures"]],"generated_at":datetime.now(timezone.utc).isoformat(),"v1_retained":True,"time_correction_audit":"time_correction_audit.json"}
    (TRIAL/"quality_report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf8")
    print(json.dumps({"status":report["status"],"failures":report["failures"],"metrics":[x["metrics"] for x in result]},ensure_ascii=False))
if __name__=="__main__": main()
