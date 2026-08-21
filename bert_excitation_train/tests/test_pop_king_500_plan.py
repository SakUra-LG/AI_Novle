from bert_excitation_train.scripts.v2.generate_pop_king_500_plan import (
    RESEARCH_ANCHORS,
    SOURCES,
    build,
)


def test_curated_plan_covers_exactly_five_hundred_chapters():
    clusters, cards, bible = build()
    assert len(clusters) == 250
    assert len(cards) == 500
    assert [card["chapter_id"] for card in cards] == list(range(1, 501))
    assert [chapter for cluster in clusters for chapter in range(
        cluster["chapter_span"][0], cluster["chapter_span"][1] + 1
    )] == list(range(1, 501))
    assert bible["target_total_chinese_chars"] == 500_000
    assert bible["structure"]["macro_groups"] == 50
    assert bible["structure"]["chapters_per_event"] == 2
    assert all(cluster["chapter_span"][1] - cluster["chapter_span"][0] == 1 for cluster in clusters)


def test_rebirth_moves_to_debut_and_keeps_previous_death_prologue():
    _, cards, bible = build()
    assert cards[0]["chapter_role_v2"] == "previous_life_death"
    assert cards[1]["chapter_role_v2"].startswith("rebirth_confirmation")
    assert "1969" in cards[1]["chapter_goal"]
    assert "十一岁" in cards[1]["chapter_goal"]
    assert "出道" in bible["rebirth_anchor"]["rebirth"]


def test_every_cluster_has_rebirth_flywheel_and_prevents_repeat_harm():
    clusters, cards, _ = build()
    for cluster in clusters:
        assert len(cluster["rebirth_flywheel"]) == 3
        assert cluster["fictional_obstacle"]
        assert cluster["preemptive_avoidance"]
        assert cluster["ascension_gain"]
        assert len(cluster["chapter_milestones"]) == 2
        assert "两章一事" in cluster["summary"]
    assert all(card["cluster_chapter_total"] == 2 for card in cards)
    assert all(cards[index]["cluster_id"] == cards[index + 1]["cluster_id"] for index in range(0, 500, 2))


def test_minor_romance_guard_and_adult_relationship_progression():
    clusters, cards, _ = build()
    assert all("未成年" in card["romance_state"] for card in cards[:90])
    assert "成年" in cards[90]["romance_state"]
    assert "艾琳" in clusters[-1]["romance_state"]


def test_research_has_sources_and_full_career_anchors():
    source_ids = {source["source_id"] for source in SOURCES}
    assert len(SOURCES) >= 8
    assert RESEARCH_ANCHORS[0]["years"].startswith("1969")
    assert RESEARCH_ANCHORS[-1]["years"] == "2008—2009"
    assert all(set(anchor["source_ids"]) <= source_ids for anchor in RESEARCH_ANCHORS)
