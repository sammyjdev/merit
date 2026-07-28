from merit.state import MeritState


def test_state_keys():
    keys = set(MeritState.__annotations__)
    assert keys == {
        "posting_text", "posting_meta", "demands", "verdicts",
        "report_md", "approved", "narrative_md", "profile_hash",
    }
