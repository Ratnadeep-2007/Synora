from app.services.speaker_identity_resolver import (
    SpeakerIdentityResolver,
    is_generic_speaker,
    roster_names_from_vexa,
)


def _segments():
    return [
        {
            "id": "s0",
            "text": "Hi, I'm Siddhi. Let's start with the database.",
            "speaker": "SPEAKER_00",
            "start_seconds": 0.0,
            "end_seconds": 3.0,
        },
        {
            "id": "s1",
            "text": "Hello, my name is Neha. I'll handle the frontend.",
            "speaker": "SPEAKER_01",
            "start_seconds": 3.0,
            "end_seconds": 6.0,
        },
        {
            "id": "s2",
            "text": "Hi, mera naam Ratnadeep hai. I will handle deployment.",
            "speaker": "SPEAKER_02",
            "start_seconds": 6.0,
            "end_seconds": 10.0,
        },
        {
            "id": "s3",
            "text": "Main Omesh hoon. I'll take Redis.",
            "speaker": "SPEAKER_03",
            "start_seconds": 10.0,
            "end_seconds": 13.0,
        },
        {
            "id": "s4",
            "text": "Hi, I'm Brajesh. I'll review the API.",
            "speaker": "SPEAKER_04",
            "start_seconds": 13.0,
            "end_seconds": 16.0,
        },
        {
            "id": "s5",
            "text": "Let's keep the meeting focused.",
            "speaker": "SPEAKER_02",
            "start_seconds": 16.0,
            "end_seconds": 18.0,
        },
    ]


def test_five_person_self_introduction_maps_each_speaker_once():
    resolved, summary = SpeakerIdentityResolver().resolve(
        _segments(),
        known_names=["Siddhi", "Neha", "Ratnadeep", "Omesh", "Brajesh"],
    )

    assert [item["speaker"] for item in resolved] == [
        "Siddhi",
        "Neha",
        "Ratnadeep",
        "Omesh",
        "Brajesh",
        "Ratnadeep",
    ]
    assert summary["confirmed_speakers"] == 5
    assert summary["unresolved_speakers"] == 0

    for item in resolved:
        assert item["raw_speaker"].startswith("SPEAKER_")
        assert item["speaker_identity_status"] == "confirmed"
        assert item["speaker_identity_confidence"] >= 0.92


def test_unresolved_speaker_is_not_guessed():
    segments = [{
        "id": "s0",
        "text": "We should use PostgreSQL.",
        "speaker": "SPEAKER_00",
        "start_seconds": 0.0,
        "end_seconds": 1.0,
    }]

    resolved, summary = SpeakerIdentityResolver().resolve(
        segments,
        known_names=["Siddhi", "Neha"],
    )

    assert resolved[0]["speaker"] == "SPEAKER_00"
    assert resolved[0]["speaker_identity_status"] == "unresolved"
    assert resolved[0]["speaker_identity_confidence"] == 0.0
    assert summary["confirmed_speakers"] == 0
    assert summary["unresolved_speakers"] == 1


def test_same_name_claimed_by_two_speakers_stays_unresolved():
    segments = [
        {
            "id": "s0",
            "text": "Hi, I'm Alex.",
            "speaker": "SPEAKER_00",
            "start_seconds": 0.0,
            "end_seconds": 1.0,
        },
        {
            "id": "s1",
            "text": "Hello, I am Alex.",
            "speaker": "SPEAKER_01",
            "start_seconds": 1.0,
            "end_seconds": 2.0,
        },
    ]

    resolved, summary = SpeakerIdentityResolver().resolve(segments)

    assert all(item["speaker_identity_status"] == "unresolved" for item in resolved)
    assert all(item["speaker"].startswith("SPEAKER_") for item in resolved)
    assert summary["confirmed_speakers"] == 0
    assert summary["unresolved_speakers"] == 2


def test_hindi_name_phrase_maps_against_known_roster():
    segments = [{
        "id": "s0",
        "text": "Namaste, mera naam Siddhi Shendge hai.",
        "speaker": "SPEAKER_00",
        "start_seconds": 0.0,
        "end_seconds": 2.0,
    }]

    resolved, _ = SpeakerIdentityResolver().resolve(
        segments,
        known_names=["Siddhi Shendge", "Neha"],
    )

    assert resolved[0]["speaker"] == "Siddhi Shendge"
    assert resolved[0]["speaker_identity_source"] == "self_introduction"


def test_vexa_roster_filters_bot_and_duplicates():
    payload = {
        "participants": [
            {"name": "Siddhi", "source": "invite"},
            {"name": "Neha", "source": "invite"},
            {"name": "Siddhi", "source": "speaker"},
            {"name": "Synora", "source": "speaker"},
            {"name": "SPEAKER_00", "source": "speaker"},
            {"name": None, "source": "invite"},
        ]
    }

    assert roster_names_from_vexa(payload, bot_name="Synora") == ["Siddhi", "Neha"]


def test_generic_speaker_labels_are_detected():
    assert is_generic_speaker("SPEAKER_00")
    assert is_generic_speaker("Unknown Speaker")
    assert not is_generic_speaker("Siddhi")

def test_self_introduction_without_roster_is_provisional_and_clean():
    segments = [{
        "id": "s0",
        "text": "Hi, I'm Siddhi. Let's start the meeting.",
        "speaker": "SPEAKER_00",
        "start_seconds": 0.0,
        "end_seconds": 2.0,
    }]

    resolved, summary = SpeakerIdentityResolver().resolve(segments)

    assert resolved[0]["speaker"] == "Siddhi"
    assert resolved[0]["speaker_identity_status"] == "provisional"
    assert resolved[0]["speaker_identity_confidence"] >= 0.92
    assert summary["provisional_speakers"] == 1


def test_hinglish_self_introduction_without_roster_is_provisional():
    segments = [{
        "id": "s0",
        "text": "Hi, mera naam Ratnadeep hai. Aaj deployment discuss karte hain.",
        "speaker": "SPEAKER_00",
        "start_seconds": 0.0,
        "end_seconds": 2.0,
    }]

    resolved, _ = SpeakerIdentityResolver().resolve(segments)

    assert resolved[0]["speaker"] == "Ratnadeep"
    assert resolved[0]["speaker_identity_status"] == "provisional"
