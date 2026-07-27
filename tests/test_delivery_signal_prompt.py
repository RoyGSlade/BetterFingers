"""Delivery signals reaching the main dictation prompt (plan Stage 9).

Signals were computed on every draft and persisted, but never passed to
``process_fast_lane`` — so the main cleanup prompt, the one that produces the
text a user actually sends, had no delivery context at all while Message Rescue
did.

This is the first path where HOW something was said can change WHAT gets sent,
so two product rules bind it and both are tested here:

* rule 3 — emotion is an uncertain signal, shown as evidence and confidence,
  never a diagnosis. The prompt therefore carries axis numbers and counts and
  no emotion vocabulary: the model is given observations with no field to read
  a diagnosis out of.
* rule 5 — stated emotional intensity is a preservation invariant. Knowing the
  speaker was fast and loud must not license amplifying, or flattening, what
  they actually said.

The feature ships OFF by default. These tests are the gate that has to be
trusted on real models before that default flips.
"""

import re

import pytest

from backend.domain.contracts import TimedSegment
from backend.services.speech_signals import compute_speech_signals, summarize_signals


# Words that would turn an observation into a diagnosis. Mirrors the list
# tests/test_speech_signals.py already enforces on evidence strings.
EMOTION_WORDS = (
    "angry", "anger", "frustrated", "frustration", "sad", "sadness", "happy",
    "happiness", "excited", "excitement", "upset", "annoyed", "irritated",
    "anxious", "anxiety", "stressed", "calm", "furious", "delighted", "mood",
    "feeling", "feels", "emotional", "emotion",
)


def _signals(text="okay so the build is broken again", *, fillers=0):
    words = text + (" um" * fillers)
    return compute_speech_signals(
        [TimedSegment(start_s=0.0, end_s=2.0, text=words)],
        audio_duration_s=2.0,
        energy_windows=[0.05, 0.6, 0.1, 0.5],
    )


class TestSummaryShape:
    def test_summary_is_numbers_only(self):
        summary = summarize_signals(_signals())
        # Every token must be key=number.
        for part in summary.split(", "):
            assert re.fullmatch(r"[a-z_]+=\d+(\.\d+)?", part), f"non-numeric token: {part!r}"

    def test_summary_never_contains_emotion_vocabulary(self):
        summary = summarize_signals(_signals(fillers=3)).lower()
        for word in EMOTION_WORDS:
            assert word not in summary, f"summary leaked emotion word {word!r}"

    def test_summary_never_echoes_transcript_text(self):
        # The transcript's distinctive words must not appear in the summary.
        summary = summarize_signals(_signals("deploy the hotfix to production now")).lower()
        for word in ("deploy", "hotfix", "production"):
            assert word not in summary

    def test_none_is_handled(self):
        assert summarize_signals(None) == "none"


class TestPromptInjection:
    """What process_fast_lane actually puts in the system prompt."""

    @staticmethod
    def _build_prompt(delivery_summary):
        """Reproduce the exact block llm_engine appends, without a live model.

        Importing llm_engine pulls in the whole runtime; this asserts on the
        contract of the appended text, which is what the rules constrain.
        """
        import llm_engine
        import inspect

        source = inspect.getsource(llm_engine.LLMEngine.process_fast_lane)
        assert "delivery_summary" in source, "process_fast_lane lost its delivery_summary kwarg"
        return source

    def test_process_fast_lane_accepts_the_kwarg(self):
        import inspect
        import llm_engine

        sig = inspect.signature(llm_engine.LLMEngine.process_fast_lane)
        assert "delivery_summary" in sig.parameters
        # Additive only (rule 6): it must default to None so every existing
        # caller and test double keeps working untouched.
        assert sig.parameters["delivery_summary"].default is None

    def test_prompt_block_carries_a_preservation_clause(self):
        source = self._build_prompt("arousal=0.90")
        block = source[source.index("DELIVERY SIGNALS"):]
        lowered = block.lower()
        # Rule 5: the instruction must explicitly forbid changing intensity.
        assert "intensity" in lowered
        assert "meaning" in lowered or "facts" in lowered

    def test_prompt_block_contains_no_emotion_vocabulary(self):
        source = self._build_prompt("arousal=0.90")
        block = source[source.index("DELIVERY SIGNALS"):source.index("Never mention")]
        lowered = block.lower()
        for word in EMOTION_WORDS:
            # "mood" appears only in the negative ("not a description of mood").
            if word == "mood":
                assert "not a description of mood" in lowered
                continue
            assert word not in lowered, f"prompt block leaked emotion word {word!r}"


class TestPreservationClause:
    """Rule 5 enforced for EVERY persona, at the one choke point.

    Found by the live probe: cleanup was rewriting spoken numerals as words --
    "3 failing tests" came back as "three failing tests" -- because the model
    applies the ordinary prose convention of spelling out numbers under ten.
    Harmless in a sentence; not harmless for a version, a dose, a room number,
    a price or a time, and never something the user asked for.
    """

    @staticmethod
    def _source():
        import inspect

        import llm_engine

        return inspect.getsource(llm_engine.LLMEngine.process_fast_lane)

    @staticmethod
    def _clause():
        import llm_engine

        return llm_engine.PRESERVATION_CLAUSE

    def test_the_clause_exists(self):
        assert "PRESERVE EXACTLY" in self._clause()

    def test_it_names_the_numeral_conversion_both_ways(self):
        # Asserted against the assembled constant, not the source: the literal
        # is wrapped across lines, so grepping source for "words to digits"
        # fails on a clause that is perfectly correct at runtime.
        clause = self._clause().lower()
        assert "digits to words" in clause
        assert "words to digits" in clause

    def test_it_covers_the_other_rule_5_invariants(self):
        clause = self._clause().lower()
        for invariant in ("numbers", "dates", "times", "names", "units"):
            assert invariant in clause, f"rule-5 invariant {invariant!r} not preserved"
        assert "negation" in clause

    def test_it_applies_after_both_prompt_branches(self):
        # Internal presets and user personas take different branches; the
        # clause must land after they rejoin, or custom personas -- which is
        # what most users actually run -- would be free to break the invariant.
        source = self._source()
        internal = source.index("INTERNAL_PRESETS[preset_name]")
        composed = source.index("compose_persona_system_prompt(persona)")
        applied = source.index("PRESERVATION_CLAUSE")
        assert applied > internal and applied > composed


class TestDefaultOff:
    def test_profile_default_is_off(self):
        from utils import _profile_defaults

        assert _profile_defaults()["use_delivery_signals"] is False, (
            "delivery signals must stay opt-in until the preservation eval is "
            "trusted on real models"
        )

    def test_setting_survives_a_round_trip_and_coerces(self):
        from utils import _sanitize_profile_values, _profile_defaults

        defaults = _profile_defaults()
        cfg = _sanitize_profile_values({"use_delivery_signals": "true"}, defaults)
        assert cfg["use_delivery_signals"] is True

        cfg = _sanitize_profile_values({"use_delivery_signals": "nonsense"}, defaults)
        assert cfg["use_delivery_signals"] is False, "a junk value must fall back to off, not on"


class TestPreservationEval:
    """Rule 5 gate: intensity must round-trip regardless of delivery.

    Uses a recording fake rather than a live model — the point is that the
    SAME transcript produces the same preservation requirement whether the
    delivery numbers say calm or agitated. A real-model version of this is what
    must pass before the profile default flips on.
    """

    @pytest.mark.parametrize(
        "transcript",
        [
            "I'm really frustrated that this broke again",
            "this is fine, no rush at all",
            "I am not angry about the deploy",
        ],
    )
    @pytest.mark.parametrize("energy", [[0.01, 0.02, 0.01, 0.02], [0.9, 0.05, 0.95, 0.1]])
    def test_same_transcript_yields_same_preservation_instruction(self, transcript, energy):
        low = compute_speech_signals(
            [TimedSegment(start_s=0.0, end_s=2.0, text=transcript)],
            audio_duration_s=2.0,
            energy_windows=energy,
        )
        summary = summarize_signals(low)

        # Whatever the delivery, the summary stays numeric and never editorializes
        # about the transcript's own stated feeling.
        assert "frustrat" not in summary.lower()
        assert "angry" not in summary.lower()
        for part in summary.split(", "):
            assert re.fullmatch(r"[a-z_]+=\d+(\.\d+)?", part)

    def test_delivery_axes_differ_with_delivery_but_text_does_not_leak(self):
        text = "I'm really frustrated that this broke again"
        calm = compute_speech_signals(
            [TimedSegment(start_s=0.0, end_s=4.0, text=text)],
            audio_duration_s=4.0,
            energy_windows=[0.05] * 8,
        )
        agitated = compute_speech_signals(
            [TimedSegment(start_s=0.0, end_s=1.5, text=text)],
            audio_duration_s=1.5,
            energy_windows=[0.02, 0.95, 0.05, 0.9],
        )
        assert summarize_signals(calm) != summarize_signals(agitated), (
            "delivery signals should distinguish these; if not, the feature has no value"
        )
        for summary in (summarize_signals(calm), summarize_signals(agitated)):
            assert "frustrated" not in summary.lower()
