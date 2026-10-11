"""Post-render verification: supported text passes, invented text is flagged."""

from app.services.note_verification_service import verify_scene


def _text_node(id, text, visual_type="note_block"):
    return {
        "id": id,
        "type": "text",
        "width": 300,
        "fontSize": 12,
        "text": text,
        "originalText": text,
        "autoResize": False,
        "customData": {"visual": {"type": visual_type}},
    }


def test_supported_text_verified():
    scene = [_text_node("t1", "Kitchen display tickets must reach the screen in realtime")]
    corpus = ["Decision: CafeFlow kitchen display tickets must reach the screen in realtime during lunch rush."]
    result = verify_scene(scene, corpus)
    assert result["checked"] == 1
    assert result["verified"] == 1
    assert result["unverified_total"] == 0


def test_invented_text_flagged():
    scene = [_text_node("t1", "The cafeteria will install seventeen rooftop swimming pools by Tuesday")]
    corpus = ["Decision: CafeFlow kitchen display tickets must reach the screen in realtime."]
    result = verify_scene(scene, corpus)
    assert result["checked"] == 1
    assert result["verified"] == 0
    assert result["unverified_total"] == 1
    assert result["unverified"][0]["element_id"] == "t1"
    assert result["unverified"][0]["score"] < 0.4


def test_system_chrome_skipped():
    scene = [
        _text_node("f1", "Maintained automatically from project memory, rechecked every 30 seconds", "project_notes_footer"),
        {"id": "r1", "type": "rectangle", "text": "Kitchen display tickets realtime"},
    ]
    result = verify_scene(scene, ["Kitchen display tickets must reach the screen"])
    assert result["checked"] == 0


def test_short_labels_skipped():
    scene = [_text_node("t1", "OK Burritos")]
    result = verify_scene(scene, ["Something entirely different about bridges"])
    assert result["checked"] == 0


def test_hindi_corpus_supported():
    scene = [_text_node("t1", "Kitchen display subah ki bheed mein samay par hona chahiye")]
    corpus = ["किचन डिस्प्ले सुबह की भीड़ में समय पर होना चाहिए"]
    # Different scripts share no word tokens: flagged (honest limitation,
    # translation upstream is what aligns them).
    result = verify_scene(scene, corpus)
    assert result["checked"] == 1
    assert result["unverified_total"] == 1


def test_empty_corpus_flags_everything():
    scene = [_text_node("t1", "Kitchen display tickets must reach the screen")]
    result = verify_scene(scene, [])
    assert result["checked"] == 1
    assert result["unverified_total"] == 1
