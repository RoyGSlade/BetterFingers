"""Audience context reaching the main dictation prompt (Stage 11c).

The second path where something other than the words can change what a user
sends — delivery signals were the first. The same two rules bind it, plus the
one this feature exists under:

* rule 2 — a contact is created, named and selected by the user, and the app
  never infers one. The prompt therefore states the audience as declared
  context, so a model (or a later reader of this code) has nothing to mistake
  for detection.
* rule 5 — stated intensity is a preservation invariant. Knowing who is being
  written to may change register and word choice; it must not change what was
  said, and it must not add greetings or sign-offs the speaker never spoke.

Ships OFF by default, like delivery signals, and for the same reason: the
preservation differential does not yet cover audience as its own axis.
"""

import inspect

import pytest

from backend.services.contacts import audience_block


def _process_fast_lane_source():
    import llm_engine

    return inspect.getsource(llm_engine.LLMEngine.process_fast_lane)


CONTACT = {
    "id": "abc123",
    "name": "Priya Raman",
    "relationship": "my manager",
    "tone_guidance": "Direct, no filler.",
    "notes": "Prefers exact numbers.",
    "preferred_persona": None,
}


class TestAudienceBlock:
    def test_the_block_carries_only_what_the_user_wrote(self):
        block = audience_block(CONTACT)
        assert "my manager" in block
        assert "Direct, no filler." in block
        assert "Prefers exact numbers." in block

    def test_the_block_never_carries_the_name_or_id(self):
        """A rewrite does not need to know WHO someone is to sound right for
        them, and a name in a prompt is a name in whatever the model layer logs
        or caches."""
        block = audience_block(CONTACT)
        assert "Priya" not in block
        assert "Raman" not in block
        assert "abc123" not in block

    def test_an_empty_contact_yields_an_empty_block(self):
        # So callers can treat "no contact" and "a contact with nothing in it"
        # identically, instead of appending an empty AUDIENCE header.
        assert audience_block({"id": "x", "name": "Sam"}) == ""

    def test_junk_input_does_not_raise(self):
        for junk in (None, "nope", 3, []):
            assert audience_block(junk) == ""


class TestPromptContract:
    def test_process_fast_lane_accepts_the_kwarg(self):
        import llm_engine

        sig = inspect.signature(llm_engine.LLMEngine.process_fast_lane)
        assert "audience_summary" in sig.parameters
        # Additive only (rule 6): defaults to None so every existing caller and
        # test double keeps working untouched.
        assert sig.parameters["audience_summary"].default is None

    def test_the_block_states_the_audience_as_declared_not_detected(self):
        """Rule 2's clarification says a contact is available, never applied,
        unless the user applied it. The prompt has to say so: this is the one
        place a future contributor could read audience as a signal the app
        worked out for itself."""
        source = _process_fast_lane_source()
        block = source[source.index("AUDIENCE (") :]
        assert "explicitly selected" in block
        assert "not something detected" in block

    def test_the_block_forbids_changing_meaning_facts_or_intensity(self):
        source = _process_fast_lane_source()
        block = source[source.index("AUDIENCE (") : source.index("PRESERVATION_CLAUSE", source.index("AUDIENCE ("))]
        lowered = block.lower()
        assert "intensity" in lowered
        assert "meaning" in lowered
        assert "facts" in lowered

    def test_the_block_forbids_inventing_greetings_and_sign_offs(self):
        """The most likely way an audience prompt breaks rule 5 in practice:
        the model decides a message to your manager should open with "Hi
        Priya," and close with "Best" -- words the speaker never said."""
        block = _process_fast_lane_source()
        lowered = block[block.index("AUDIENCE (") :].lower()
        assert "greetings" in lowered
        assert "sign-offs" in lowered

    def test_the_block_carries_the_preservation_clause(self):
        # The same clause delivery signals use. Rule 5 does not get a weaker
        # version because the input is prose instead of numbers.
        source = _process_fast_lane_source()
        audience_at = source.index("AUDIENCE (")
        assert "PRESERVATION_CLAUSE" in source[audience_at:]

    def test_a_blank_summary_appends_nothing(self):
        # The guard is `if audience_summary and str(...).strip()`, so an empty
        # contact cannot leave a dangling AUDIENCE header in the prompt.
        source = _process_fast_lane_source()
        assert "if audience_summary and str(audience_summary).strip():" in source


class TestDefaultOff:
    def test_profile_default_is_off(self):
        from utils import _profile_defaults

        assert _profile_defaults()["use_audience_context"] is False, (
            "audience context must stay opt-in until the preservation "
            "differential covers audience as its own axis"
        )

    def test_setting_survives_a_round_trip_and_coerces(self):
        from utils import _profile_defaults, _sanitize_profile_values

        defaults = _profile_defaults()
        assert _sanitize_profile_values({"use_audience_context": "true"}, defaults)["use_audience_context"] is True
        assert _sanitize_profile_values({"use_audience_context": "nonsense"}, defaults)["use_audience_context"] is False, (
            "a junk value must fall back to off, not on"
        )


class TestDraftField:
    def test_create_draft_accepts_an_optional_contact_id(self):
        from backend.stores.drafts import DraftStore

        sig = inspect.signature(DraftStore.create_draft)
        assert "contact_id" in sig.parameters
        assert sig.parameters["contact_id"].default is None

    # The behavioural half of this lives in tests/test_draft_store.py, which
    # already has the DraftStore fixture -- reimplementing it here would be a
    # second copy to keep in step.


class TestStickySelection:
    def test_the_selected_contact_lives_in_the_profile(self):
        """Sticky like current_preset, deliberately. Rule 2 is about who
        decides, not how often they are interrupted, and re-confirming a
        standing choice before every utterance is friction with no safety
        benefit (ACCOMPLISH.md §3, design doc §10)."""
        from utils import _profile_defaults

        assert _profile_defaults()["active_contact_id"] is None

    def test_no_selection_normalizes_to_none_not_empty_string(self):
        from utils import _profile_defaults, _sanitize_profile_values

        defaults = _profile_defaults()
        for blank in ("", "   ", None):
            cfg = _sanitize_profile_values({"active_contact_id": blank}, defaults)
            assert cfg["active_contact_id"] is None

    def test_a_selection_round_trips(self):
        from utils import _profile_defaults, _sanitize_profile_values

        cfg = _sanitize_profile_values({"active_contact_id": " abc123 "}, _profile_defaults())
        assert cfg["active_contact_id"] == "abc123"


class TestPipelineWiring:
    """The dictation path, asserted on source. A live end-to-end run needs a
    real model; these pin the two decisions that are easy to get backwards."""

    @staticmethod
    def _server_source():
        import inspect

        import server

        return inspect.getsource(server)

    def test_the_prompt_block_is_gated_on_the_toggle(self):
        source = self._server_source()
        assert 'profile_config.get("use_audience_context") and profile_config.get("active_contact_id")' in source

    def test_the_draft_records_the_selection_regardless_of_the_toggle(self):
        """The toggle governs whether a contact reaches the PROMPT, not whether
        the user's own standing selection is written down -- that is what makes
        Library filtering and retroactive application possible."""
        source = self._server_source()
        start = source.index("def _stage_finalize")
        stamp = source.index('contact_id=profile_config.get("active_contact_id")', start)
        # Everything between entering the stage and stamping the draft. If the
        # toggle appeared here it would be gating the RECORD, not the prompt.
        # (Sliced to the call site rather than a fixed window, because the
        # comment above the line names the toggle while explaining why it is
        # deliberately absent from the condition.)
        preamble = source[start:stamp]
        assert 'use_audience_context") and' not in preamble, (
            "recording the selection must not be gated on the prompt toggle"
        )
        assert "if profile_config" not in preamble

    def test_an_unreadable_contact_does_not_stop_the_dictation(self):
        # A contact that cannot be read must not fail the utterance it was only
        # meant to flavour.
        source = self._server_source()
        block = source[source.index("Audience context unavailable") - 800 :]
        assert "try:" in block
        assert "logging.warning" in block
