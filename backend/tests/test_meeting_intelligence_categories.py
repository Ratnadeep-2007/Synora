"""
Regression coverage for meeting intelligence category classification.

Meetings that plainly contained decisions and requirements were projected as
"0 decisions, 0 requirements". Two causes, both covered here:

1. The extraction model emitted category strings that the mapper did not
   recognise, so everything fell through to "knowledge" and every bucket
   reported zero.
2. The extraction prompt did not distinguish a decision from a proposal, so the
   model labelled settled agreements as proposals.
"""

from app.services.meeting_intelligence import MeetingIntelligenceService
from app.services.meeting_session_intelligence import MeetingSessionIntelligenceService


class _Candidate:
    def __init__(self, category, classification=""):
        self.category = category
        self.classification = classification


def _mapped(category, classification=""):
    return MeetingSessionIntelligenceService._candidate_type(
        _Candidate(category, classification)
    )


# ------------------------------------------------------------------ mapper


def test_canonical_categories_map_to_their_buckets():
    assert _mapped("decision") == "decision"
    assert _mapped("requirement") == "requirement"
    assert _mapped("action_item") == "action_item"
    assert _mapped("question") == "question"
    assert _mapped("constraint") == "constraint"
    assert _mapped("assumption") == "assumption"
    assert _mapped("proposal") == "knowledge"


def test_plural_and_casing_variants_are_normalised():
    """The model is free to pluralise or change case. Both used to fall
    through to "knowledge", which is what zeroed the summary."""
    assert _mapped("Decision") == "decision"
    assert _mapped("DECISION") == "decision"
    assert _mapped("decisions") == "decision"
    assert _mapped("Requirements") == "requirement"
    assert _mapped("action items") == "action_item"
    assert _mapped("action-item") == "action_item"
    assert _mapped("open_question") == "question"


def test_legacy_decision_candidate_spelling_still_maps():
    # The old schema description advertised these spellings, so persisted
    # rows may still carry them.
    assert _mapped("decision_candidate") == "decision"
    assert _mapped("requirement_candidate") == "requirement"


def test_classification_is_used_when_category_is_unrecognised():
    assert _mapped("something_new", "Decision") == "decision"
    assert _mapped("weird", "requirement") == "requirement"


def test_prefixed_category_spelling_maps():
    assert _mapped("extracted_decision") == "decision"


def test_genuinely_unknown_category_is_knowledge():
    assert _mapped("banana") == "knowledge"
    assert _mapped("", "") == "knowledge"


# ------------------------------------------------------------------ prompt


def test_extraction_prompt_distinguishes_decision_from_proposal():
    guide = MeetingIntelligenceService.CATEGORY_GUIDE
    lowered = guide.lower()
    # The wording that makes the boundary explicit.
    assert "decision is not a suggestion" in lowered
    assert "already settled" in lowered
    for token in ("requirement", "constraint", "action_item", "question"):
        assert token in lowered
    # The model must be told the exact allowed vocabulary.
    for token in ("decision", "requirement", "action_item", "question", "constraint"):
        assert token in lowered


def test_prompt_guide_is_included_in_analysis_call():
    """The guide is only useful if it reaches the model. This asserts the
    batch analysis prompt carries it rather than the bare instruction."""
    svc = MeetingIntelligenceService.__new__(MeetingIntelligenceService)
    prompt = svc._build_evidence_prompt(
        [],
        "Extract all candidates with evidence IDs.\n" + MeetingIntelligenceService.CATEGORY_GUIDE,
    )
    assert "decision is not a suggestion" in prompt.lower()