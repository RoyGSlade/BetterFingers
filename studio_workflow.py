import os
import json
import logging
import re
from datetime import datetime, timezone
import studio_capabilities
import studio_memory as memory
import studio_analyzer
import studio_loremaster
import studio_genesis
import studio_taste
import studio_showrunner
import studio_scriptwriter
import studio_render
import studio_audio
import studio_continuity
import studio_prompt_compiler
import studio_image_backend
import studio_repair
import studio_generation
import studio_visual
import studio_blackboard
from llm_engine import get_engine, get_engine_if_initialized

logger = logging.getLogger("studio_workflow")

# Supported production modes.
#   seed     -> invent a brand new story from a short prompt (original behavior)
#   adapt    -> "start from" an existing finished story: storyboard what the user wrote
#   continue -> "continue from" an existing story: treat it as canon and produce what happens next
MODE_SEED = "seed"
MODE_ADAPT = "adapt"
MODE_CONTINUE = "continue"

# How much of a (potentially long) source story we feed to the LLM for grounding.
# The full text is always preserved in project memory; this only bounds the prompt size.
STORY_CONTEXT_CHARS = 6000

# Absolute constraints passed to every LLM stage to prevent hallucination loops and context overflow.
AGENTIC_CONSTRAINTS = (
    "\n\n--- AGENTIC CONSTRAINTS ---\n"
    "1. ABSOLUTE JSON COMPLIANCE: You must return ONLY valid, raw JSON. Do NOT wrap it in ```json blocks. "
    "Do NOT include any conversational filler (e.g., 'Here is the JSON:').\n"
    "2. NO HALLUCINATIONS: Do not invent new characters, locations, or elements that contradict the provided Canon/World State.\n"
    "3. CONCISENESS: Your output MUST NOT exceed 1500 tokens. Be direct and avoid purple prose.\n"
    "4. FAILURE FALLBACK: If you cannot fulfill the request due to logical conflicts, output an empty object {}."
)

# Structured-bible schemas. Each stage asks for one small piece of these shapes; the
# required-keys list is what _generate_structured validates (and retries) against. Richer,
# named fields here are what give downstream dialogue and image prompts something concrete
# to anchor on, instead of a 1-sentence blob.
WORLD_CORE_KEYS = ["setting", "genre_rules", "tone_rules", "palette", "lighting", "danger_level"]
WORLD_LOCATION_KEYS = ["name", "visual_prompt", "mood"]
CHARACTER_BIBLE_KEYS = ["personality", "goals", "speech_style", "visual", "voice_profile"]


def _dossier_grounding(dossier):
    """Render a Loremaster character dossier into a compact grounding string the Character
    Creator expands from (traits, want/need, wound, secret, relationships, real lines)."""
    if not isinstance(dossier, dict):
        return ""
    parts = []
    if dossier.get("traits"):
        parts.append("traits: " + ", ".join(str(t) for t in dossier["traits"]))
    for label, key in (("wants", "want"), ("needs", "need"), ("wound", "wound"), ("secret", "secret"), ("voice", "voice")):
        val = str(dossier.get(key) or "").strip()
        if val:
            parts.append(f"{label}: {val}")
    rels = dossier.get("relationships") or []
    rel_bits = []
    for r in rels:
        if isinstance(r, dict) and (r.get("who") or r.get("bond")):
            rel_bits.append(f"{r.get('who', '')} ({r.get('bond', '')})".strip())
        elif isinstance(r, str) and r.strip():
            rel_bits.append(r.strip())
    if rel_bits:
        parts.append("relationships: " + "; ".join(rel_bits))
    if dossier.get("key_lines"):
        parts.append("real lines: " + " / ".join(f'"{l}"' for l in dossier["key_lines"][:3] if l))
    return ". ".join(parts)


def _normalize_story_plan_shape(plan):
    """Return a storyboard shape downstream agents can depend on."""
    plan = plan if isinstance(plan, dict) else {}
    episodes = plan.get("episodes") if isinstance(plan.get("episodes"), list) else []
    canon_events = plan.get("canon_events") if isinstance(plan.get("canon_events"), list) else []
    return {
        "summary": str(plan.get("summary") or "").strip(),
        "episodes": [
            {
                "name": str(beat.get("name") or f"Beat {idx + 1}").strip(),
                "summary": str(beat.get("summary") or "").strip(),
            }
            for idx, beat in enumerate(episodes)
            if isinstance(beat, dict) and str(beat.get("summary") or beat.get("name") or "").strip()
        ],
        "canon_events": [
            {
                "description": str(event.get("description") or "").strip(),
                "time_index": str(event.get("time_index") or "").strip(),
            }
            for event in canon_events
            if isinstance(event, dict) and str(event.get("description") or "").strip()
        ],
    }


class StudioWorkflowRunner:
    def __init__(self, project_name):
        self.project_name = project_name
        self.project_id = memory.init_project_db(project_name)
        self.state = "idle"
        self.steps_log = []
        # Set once intake runs (or when a pipeline is started); used to ground later stages.
        self.mode = MODE_SEED
        self.source_story = None
        self.model_status = {
            "llm_attempted": False,
            "llm_ready": False,
            "used_fallback": False,
            "model_id": None,
            "messages": [],
        }
        self._profile = None

    @property
    def profile(self):
        """Model-aware generation profile (batch sizes + token budgets). Computed lazily so
        it reflects whichever LLM model is actually selected/loaded for this run."""
        if self._profile is None:
            model_id = self.model_status.get("model_id")
            if not model_id:
                try:
                    engine = get_engine_if_initialized()
                    model_id = getattr(engine, "model_id", None) if engine else None
                except Exception:
                    model_id = None
            self._profile = studio_generation.get_generation_profile(model_id)
        return self._profile

    def _progress(self, agent, message):
        """Post a human-readable progress note to the blackboard so the UI can show, live,
        what the model is chewing on (e.g. 'Writing character 2 of 3'). Best-effort: never
        let a progress post break a production run."""
        try:
            studio_blackboard.post(self.project_name, self.project_id, agent, "progress", agent, message)
        except Exception:
            pass

    def _log_step(self, stage, status, message, details=None):
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "stage": stage,
            "status": status,
            "message": message,
            "details": details or {}
        }
        self.steps_log.append(entry)
        memory.log_tool_call(
            self.project_name,
            self.project_id,
            f"stage_{stage}",
            {"status": status, "message": message},
            details or {}
        )
        logger.info(f"[Studio Workflow - {stage.upper()}] {status}: {message}")

    # --- MODE / SOURCE STORY HELPERS ---

    def _normalize_mode(self, mode):
        """Map a variety of user-facing mode names onto the three canonical modes."""
        m = (mode or MODE_SEED).lower().strip()
        if m in ("adapt", "start", "start_from", "startfrom", "existing", "import"):
            return MODE_ADAPT
        if m in ("continue", "continue_from", "continuefrom", "sequel", "next"):
            return MODE_CONTINUE
        return MODE_SEED

    def _story_excerpt(self, text):
        """Trim a long source story to a prompt-friendly excerpt that keeps the opening and the ending.

        The ending matters most for "continue" mode, the opening for "adapt"; keeping both
        gives the model the arc without blowing the context window. Full text stays in memory.
        """
        if not text:
            return ""
        text = text.strip()
        if len(text) <= STORY_CONTEXT_CHARS:
            return text
        head_len = STORY_CONTEXT_CHARS * 2 // 3
        tail_len = STORY_CONTEXT_CHARS - head_len
        head = text[:head_len].rstrip()
        tail = text[-tail_len:].lstrip()
        return f"{head}\n\n[... middle of the story omitted for length ...]\n\n{tail}"

    def _resolve_source(self, seed_text, mode, source_story):
        """Determine the canonical mode and source story for a run.

        For adapt/continue the dropped story may arrive either as an explicit ``source_story``
        or simply as the ``seed_text`` field, so we normalize both into ``self.source_story``.
        """
        mode = self._normalize_mode(mode)
        if mode in (MODE_ADAPT, MODE_CONTINUE) and not source_story:
            source_story = seed_text
        self.mode = mode
        self.source_story = source_story
        return mode, source_story

    def _persist_source(self, mode, source_story):
        """Store the dropped story (and chosen mode) so later stages and continuity checks can ground on canon."""
        try:
            memory.set_user_preference(self.project_name, self.project_id, "story_mode", mode)
            if source_story:
                memory.set_user_preference(self.project_name, self.project_id, "source_story", source_story)
        except Exception as e:
            logger.warning(f"Could not persist source story / mode: {e}")

    def _load_source(self):
        """Recover mode + source story from memory (used when stages are run independently)."""
        try:
            prefs = memory.get_user_preferences(self.project_name, self.project_id)
        except Exception:
            prefs = {}
        self.mode = self._normalize_mode(prefs.get("story_mode", self.mode))
        if not self.source_story:
            self.source_story = prefs.get("source_story")
        return self.mode, self.source_story

    def _context_state(self):
        """Refresh the current memory bank before agents that must stay consistent."""
        bible = memory.get_bible(self.project_name, self.project_id)
        return {
            "bible": bible,
            "premise": bible.get("premise") or {},
            "world": bible.get("world") or {},
            "characters": memory.get_characters(self.project_name, self.project_id),
            "locations": memory.get_locations(self.project_name, self.project_id),
            "visual_guide": memory.get_user_preferences(self.project_name, self.project_id).get("visual_consistency_guide") or {},
            "storyboard": bible.get("storyboard") or {},
        }

    def _save_storyboard(self, story_data, ep_id=None, status="needs_user_review", note=""):
        story_data = _normalize_story_plan_shape(story_data)
        current_bible = memory.get_bible(self.project_name, self.project_id)
        current_bible["storyboard"] = story_data
        memory.save_bible(self.project_name, self.project_id, current_bible)
        memory.set_user_preference(
            self.project_name,
            self.project_id,
            "storyboard_review",
            {"status": status, "episode_id": ep_id, "note": note, "updated_at": datetime.now(timezone.utc).isoformat()},
        )
        try:
            studio_blackboard.put_artifact(
                self.project_name,
                self.project_id,
                "storyboard",
                story_data,
                produced_by="planner",
                status=status,
            )
        except Exception:
            pass
        return story_data

    def apply_storyboard_edits(self, story_plan, note=""):
        """User editing checkpoint for the Director/Storyboarder output."""
        story_plan = _normalize_story_plan_shape(story_plan)
        if not self._is_valid_story_plan(story_plan):
            raise ValueError("Storyboard edits must include a summary and at least one beat.")

        self._log_step("storyboard_edit", "start", "Applying user-edited storyboard beats.")
        episodes = memory.get_episodes(self.project_name, self.project_id)
        ep_id = episodes[0]["id"] if episodes else memory.add_episode(
            self.project_name,
            self.project_id,
            (memory.get_bible(self.project_name, self.project_id).get("premise") or {}).get("title", "Episode 1"),
            story_plan["summary"],
            metadata={"source": "storyboard_edit"},
        )
        if episodes:
            memory.update_episode(self.project_name, self.project_id, ep_id, summary=story_plan["summary"])

        minutes = [m for m in memory.get_minutes(self.project_name, self.project_id) if m.get("episode_id") == ep_id]
        for idx, beat in enumerate(story_plan["episodes"]):
            summary = f"{beat['name']}: {beat['summary']}"
            if idx < len(minutes):
                memory.update_minute(self.project_name, self.project_id, minutes[idx]["id"], summary=summary)
            else:
                memory.add_minute(self.project_name, self.project_id, ep_id, idx + 1, summary)
        if len(story_plan["episodes"]) < len(minutes):
            for m in minutes[len(story_plan["episodes"]):]:
                memory.delete_minute(self.project_name, self.project_id, m["id"])

        saved = self._save_storyboard(story_plan, ep_id=ep_id, status="approved", note=note)
        self._log_step("storyboard_edit", "complete", "Saved user-edited storyboard beats.", saved)
        return {"ok": True, "storyboard": saved, "episode_id": ep_id}

    def _canon_block(self, source_story, label="EXISTING STORY"):
        """Build a fenced canon block to append to a stage prompt, or empty string if no source."""
        excerpt = self._story_excerpt(source_story)
        if not excerpt:
            return ""
        return f'\n\n{label} (canon — treat as authoritative source material):\n"""\n{excerpt}\n"""'

    def _analysis(self, source_story=None):
        """Lazily run (and cache) the procedural story analysis for grounding fallbacks.

        Returns ``None`` when there is no source story (seed mode), so callers can fall
        back to their generic invention mocks. For adapt/continue this gives every stage
        access to the manuscript's real characters, places, dialogue, beats, and tone —
        so the no-LLM path produces a *faithful* adaptation instead of generic filler.
        """
        story = source_story if source_story is not None else self.source_story
        if not story:
            return None
        cached = getattr(self, "_analysis_cache", None)
        if cached is not None and cached.get("_story") == story:
            return cached
        result = studio_analyzer.analyze(story)
        result["_story"] = story
        self._analysis_cache = result
        return result

    def _understanding(self, source_story=None):
        """Lazily run (and cache) the Loremaster's WHOLE-story understanding.

        This is the Phase 0 keystone: instead of every stage reading a 6k head+tail
        excerpt (which dropped ~73% of a long manuscript, including its inciting
        incident and climax), the Loremaster map-reduces the full text once into a
        structured ``story_understanding`` (premise, themes, motifs, a real ordered
        timeline, and deep per-character dossiers) that downstream stages ground on.

        In seed mode (no manuscript) this does NOT return None — it falls through to Genesis,
        which *invents* a story_understanding with the same contract, so the "make a story from
        nothing" button gives every downstream stage the same rich input. Cached; persisted.
        """
        story = source_story if source_story is not None else self.source_story
        if story:
            cached = getattr(self, "_understanding_cache", None)
            if cached is not None and cached.get("_story") == story:
                return cached
            return self.run_loremaster(story)
        # Seed mode: reuse a stored understanding if present, else invent one (Genesis).
        stored = memory.get_bible(self.project_name, self.project_id).get("story_understanding")
        if stored:
            return stored
        premise = memory.get_bible(self.project_name, self.project_id).get("premise")
        if premise:
            return self.run_genesis(premise)
        return None

    def run_genesis(self, premise=None, seed_text=""):
        """Stage 0 (seed mode): invent a full ``story_understanding`` from a premise/seed.

        The counterpart to the Loremaster for the "from nothing" path. Persists to the same
        bible/blackboard keys so the Showrunner/Scriptwriter are agnostic to how the story
        came to exist (read vs invented)."""
        if premise is None:
            premise = memory.get_bible(self.project_name, self.project_id).get("premise") or {}
        self.state = "genesis"
        self._log_step("genesis", "start", "Inventing a story from the seed...")
        understanding = studio_genesis.invent_understanding(
            premise, seed_text=seed_text or "",
            llm_call=self._call_llm_with_fallback, profile=self.profile,
            progress=lambda m: self._progress("genesis", m),
            taste=studio_taste.digest_clause(self.project_name, self.project_id),
        )
        try:
            current_bible = memory.get_bible(self.project_name, self.project_id)
            current_bible["story_understanding"] = understanding
            memory.save_bible(self.project_name, self.project_id, current_bible)
            studio_blackboard.put_artifact(
                self.project_name, self.project_id, "understanding", understanding,
                produced_by="genesis")
        except Exception as e:
            logger.warning(f"Could not persist invented understanding: {e}")
        self._log_step("genesis", "complete",
                       f"Invented {len(understanding.get('timeline', []))} beats and "
                       f"{len(understanding.get('character_dossiers', []))} characters.",
                       understanding)
        return understanding

    def run_loremaster(self, source_story=None):
        """Stage 0: Loremaster — distill the full source story into ``story_understanding``.

        Reads the ENTIRE manuscript (not a truncated excerpt) via map-reduce and persists
        the result so every later stage — world, characters, storyboard, scriptwriting —
        works from one faithful, complete distillation. Safe to call repeatedly (cached).
        """
        story = source_story if source_story is not None else self.source_story
        if not story:
            return None
        self.state = "loremaster"
        self._log_step("loremaster", "start",
                       f"Reading the full story ({len(story)} chars) to build a complete understanding...")
        understanding = studio_loremaster.analyze_full(
            story,
            llm_call=self._call_llm_with_fallback,
            profile=self.profile,
            progress=lambda m: self._progress("loremaster", m),
        )
        understanding["_story"] = story
        self._understanding_cache = understanding

        # Persist: into the bible (for stages/export) and as a blackboard artifact (for the Producer).
        try:
            current_bible = memory.get_bible(self.project_name, self.project_id)
            # Don't carry the raw-story echo into stored memory.
            current_bible["story_understanding"] = {k: v for k, v in understanding.items() if k != "_story"}
            memory.save_bible(self.project_name, self.project_id, current_bible)
        except Exception as e:
            logger.warning(f"Could not persist story understanding to bible: {e}")
        try:
            studio_blackboard.put_artifact(
                self.project_name, self.project_id, "understanding",
                {k: v for k, v in understanding.items() if k != "_story"},
                produced_by="loremaster",
            )
        except Exception:
            pass

        self._log_step(
            "loremaster", "complete",
            f"Distilled {len(understanding.get('timeline', []))} timeline events and "
            f"{len(understanding.get('character_dossiers', []))} character dossiers "
            f"({understanding.get('_grounding')}).",
            {k: v for k, v in understanding.items() if k != "_story"},
        )
        return understanding

    def _call_llm_with_fallback(self, prompt, system_prompt, fallback_data_func, max_output_tokens=None):
        """Thin adapter that calls LLMEngine and falls back gracefully to mocks if needed."""
        if "AGENTIC CONSTRAINTS" not in system_prompt:
            system_prompt += AGENTIC_CONSTRAINTS

        engine = None
        self.model_status["llm_attempted"] = True
        try:
            # Check if LLMEngine is initialized/active
            engine = get_engine_if_initialized() or get_engine()
            self.model_status["model_id"] = getattr(engine, "model_id", None)
        except Exception as e:
            logger.warning(f"Could not initialize LLMEngine: {e}")
            self.model_status["messages"].append(f"LLM init failed: {e}")

        # If engine is initialized, try to ensure it is ready
        engine_ready = False
        if engine:
            try:
                engine_ready = engine.ensure_ready()
                self.model_status["llm_ready"] = bool(engine_ready)
                self.model_status["model_id"] = getattr(engine, "model_id", None)
            except Exception as e:
                logger.warning(f"LLMEngine ensure_ready failed: {e}")
                self.model_status["messages"].append(f"LLM readiness failed: {e}")

        if not engine_ready:
            self.model_status["used_fallback"] = True
            self._log_step("llm_adapter", "warning", "LLM engine sidecar not ready. Using high-quality procedural mock fallback.")
            return fallback_data_func()

        # Try up to 2 times to run and parse JSON
        active_system_prompt = system_prompt
        for attempt in range(2):
            try:
                if attempt > 0:
                    active_system_prompt += (
                        "\n\nCRITICAL SYSTEM WARNING: Your previous response was rejected because it failed JSON parsing or exceeded length limits. "
                        "You MUST output ONLY strictly valid JSON. Double-check your brackets, braces, and trailing commas. Do not include any markdown or conversational filler."
                    )

                raw_response = engine.process_custom_prompt(
                    user_text=prompt,
                    system_prompt=active_system_prompt,
                    max_output_tokens=int(max_output_tokens or 1500)
                )

                if len(raw_response or "") > 32_000:
                    logger.warning(f"LLM response oversized ({len(raw_response)} bytes), using fallback.")
                    self.model_status["used_fallback"] = True
                    self.model_status["messages"].append("LLM response was oversized; fallback used.")
                    return fallback_data_func()

                parsed = self._extract_and_parse_json(raw_response)
                if parsed:
                    return parsed

                logger.warning(f"LLM response failed JSON parsing. Attempt {attempt + 1}. Raw output: {raw_response[:200]}")
                self.model_status["messages"].append(f"LLM JSON parse failed on attempt {attempt + 1}.")
            except Exception as e:
                logger.error(f"LLM call failed on attempt {attempt + 1}: {e}")
                self.model_status["messages"].append(f"LLM call failed on attempt {attempt + 1}: {e}")

        self.model_status["used_fallback"] = True
        self._log_step("llm_adapter", "error", "Failed to get valid JSON from LLM after retries. Using mock fallback.")
        return fallback_data_func()

    def _generate_structured(self, prompt, system_prompt, fallback_data_func,
                             required_keys=None, shape="medium", item_keys=None):
        """Model-aware, schema-checked generation for one small piece of the pipeline.

        Asks the LLM for a small structured object/list using the token budget for the
        current model tier, then validates the shape:
          - `required_keys`: keys a dict result must contain (non-empty).
          - `item_keys`: when the result is a list, keys each item must contain.
        If the first result is the wrong shape, retry once with a targeted nudge naming the
        missing fields before giving up to the deterministic fallback. Keeping each ask
        small + schema-checked is what stops a small local model collapsing to mock data.
        """
        max_tokens = studio_generation.max_tokens_for(self.profile, shape)

        def _shape_ok(result):
            if required_keys is not None:
                return studio_generation.ensure_keys(result, required_keys)
            if item_keys is not None:
                return isinstance(result, list) and all(
                    studio_generation.ensure_keys(item, item_keys) for item in result
                ) and len(result) > 0
            return result is not None

        result = self._call_llm_with_fallback(prompt, system_prompt, fallback_data_func, max_tokens)
        if _shape_ok(result):
            return result

        # One targeted repair attempt: tell the model exactly which fields were wrong.
        if required_keys:
            missing = studio_generation.missing_keys(result, required_keys)
            nudge = f"\n\nYour previous answer was missing required fields: {missing}. Return ALL fields."
        else:
            nudge = "\n\nReturn a non-empty JSON list where every item has all required fields."
        retry = self._call_llm_with_fallback(prompt, system_prompt + nudge, fallback_data_func, max_tokens)
        if _shape_ok(retry):
            return retry

        self.model_status["used_fallback"] = True
        return fallback_data_func()

    def _batched(self, items, fn, batch_size):
        """Thin wrapper over studio_generation.run_batched (stitches batched LLM output)."""
        return studio_generation.run_batched(items, fn, batch_size)

    def propose_repairs(self, report, user_note=""):
        """
        Given a repair report and the user's explanation of intent, ask the LLM to
        diagnose the core issue and propose grounded, selectable fixes. Falls back to
        deterministic registry-grounded proposals when the LLM is unavailable.
        """
        report = report or {}
        prompt, system_prompt = studio_repair.build_proposal_prompt(report, user_note)

        def fallback():
            return {
                "diagnosis": report.get("problem", "This step was rejected."),
                "proposals": studio_repair.deterministic_proposals(report),
            }

        parsed = self._call_llm_with_fallback(prompt, system_prompt, fallback)
        proposals = parsed.get("proposals") if isinstance(parsed, dict) else None
        if not proposals:
            return fallback()

        # Always keep a freeform escape hatch so the user can override the AI picks.
        if not any((p or {}).get("resolution", {}).get("type") == "freeform" for p in proposals):
            proposals.append({
                "label": "Describe the fix myself",
                "description": "Write what this beat should be; the AI will rebuild it from your description.",
                "resolution": {"type": "freeform"},
            })
        return {
            "diagnosis": parsed.get("diagnosis", report.get("problem", "")),
            "proposals": proposals,
        }

    def _extract_and_parse_json(self, text):
        if not text:
            return None
        text_strip = text.strip()

        # 1. Direct try
        try:
            return json.loads(text_strip)
        except json.JSONDecodeError:
            pass

        # Find first brace and bracket
        first_bracket = text_strip.find('[')
        first_brace = text_strip.find('{')

        # Determine check order
        stages = []
        if first_bracket != -1 and (first_brace == -1 or first_bracket < first_brace):
            stages = [r"(\[.*\])", r"(\{.*\})"]
        else:
            stages = [r"(\{.*\})", r"(\[.*\])"]

        for pattern in stages:
            try:
                match = re.search(pattern, text_strip, re.DOTALL)
                if match:
                    return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass

        return None

    def run_director_exploration(self, page_size=20):
        """Phase 1: read-only exploration of regions, skins, POIs, and action chains."""
        self._log_step("director_exploration", "start", "Reading Studio capability registry for Director phase 1.")
        snapshot = studio_capabilities.exploration_snapshot(page_size=page_size)
        memory.set_user_preference(
            self.project_name,
            self.project_id,
            "director_exploration_registry",
            snapshot["registry_version"],
        )
        self._log_step(
            "director_exploration",
            "complete",
            "Director exploration registry loaded.",
            {
                "registry_version": snapshot["registry_version"],
                "categories": snapshot["categories"],
            },
        )
        return {"ok": True, "phase": "exploration", "data": snapshot}

    def run_director_casting(self, premise_data=None, cast_size=2):
        """Director Phase 2: Casting.

        Anchors the narrative in the simulation by selecting ONE region and casting
        2-4 registry skins onto named characters. Per the Absolute Grounding rule the
        model may only choose ids that exist in the capability registry; the selection
        is then validated programmatically (`studio_capabilities.validate_casting`) and
        repaired to a deterministic grounded default if the model returns anything invalid.
        """
        self.state = "director_casting"
        # Ensure the exploration registry has been recorded before casting from it.
        if not memory.get_user_preferences(self.project_name, self.project_id).get("director_exploration_registry"):
            self.run_director_exploration()

        if premise_data is None:
            premise_data = memory.get_bible(self.project_name, self.project_id).get("premise") or {}

        self._log_step("director_casting", "start", "Casting regions and skins from the capability registry...")

        regions = studio_capabilities.list_capabilities("regions", page_size=100)["items"]
        skins = studio_capabilities.list_capabilities("skins", page_size=100)["items"]
        region_menu = [{"id": r["id"], "name": r["name"], "mood_tags": r.get("mood_tags", [])} for r in regions]
        skin_menu = [{"id": s["id"], "name": s["name"], "roles": s.get("roles", [])} for s in skins]

        system_prompt = (
            "You are the Director casting a short scene. You MUST only use the region ids and skin ids "
            "provided in the registry below — never invent ids. Choose exactly one region and cast 2 to 4 "
            "characters, each anchored to a distinct skin id. Output MUST be a single valid JSON object: "
            '{"region_id": "<one region id>", "cast": [{"skin_id": "<skin id>", "character_name": "Name", "role": "role"}]}'
        )
        prompt = (
            f"Premise: {json.dumps(premise_data)}\n"
            f"Available regions (choose one): {json.dumps(region_menu)}\n"
            f"Available skins (anchor each character to one): {json.dumps(skin_menu)}"
        )

        def fallback():
            return studio_capabilities.default_casting(cast_size=cast_size)

        raw = self._call_llm_with_fallback(prompt, system_prompt, fallback)
        try:
            casting = studio_capabilities.validate_casting(raw)
        except ValueError as e:
            # Structured rejection of an ungrounded/invalid pick: repair deterministically.
            self.model_status["used_fallback"] = True
            self.model_status["messages"].append(f"Casting validation rejected model output: {e}")
            self._log_step("director_casting", "warning", f"Casting rejected ({e}); using grounded default.")
            casting = studio_capabilities.default_casting(cast_size=cast_size)

        # Persist: anchor the region as a project location and record the casting selection.
        existing_locations = {loc["name"] for loc in memory.get_locations(self.project_name, self.project_id)}
        if casting["region_name"] not in existing_locations:
            memory.add_location(
                self.project_name,
                self.project_id,
                casting["region_name"],
                casting["region_description"],
                metadata={"region_id": casting["region_id"], "source": "director_casting"},
            )
        memory.set_user_preference(self.project_name, self.project_id, "director_casting", casting)
        current_bible = memory.get_bible(self.project_name, self.project_id)
        current_bible["casting"] = casting
        memory.save_bible(self.project_name, self.project_id, current_bible)

        self._log_step("director_casting", "complete", f"Cast {len(casting['cast'])} characters into {casting['region_name']}.", casting)
        return {"ok": True, "phase": "casting", "data": casting}

    def run_scene_round(self, scene_spec):
        """Director Phase 3: Scene Planning via the round-based Scene Builder state machine.

        Drives `studio_scene.SceneBuilder` from a deterministic, structured scene spec and
        commits each accepted action chain into the GEST graph. All physical validity
        (posture, POI support, object/receiver prerequisites, action-chain ordering,
        capacity) is enforced by the backend, so an invalid spec is rejected cleanly
        without writing partial state.

        scene_spec = {
            "region_id": "<optional; defaults to the cast region>",
            "actors": [{"id"/"name", "skin_id"?, "start_poi"?, "posture"?, "held"?}],
            "chains": [{"actor", "poi"?, "actions": [{"action", "object"?, "receiver"?, "poi"?}]}]
        }
        """
        from studio_scene import SceneBuilder, SceneError

        self.state = "scene_planning"
        episodes = memory.get_episodes(self.project_name, self.project_id)
        episode_id = episodes[0]["id"] if episodes else None

        region_id = (scene_spec or {}).get("region_id")
        if not region_id:
            casting = memory.get_user_preferences(self.project_name, self.project_id).get("director_casting") or {}
            region_id = casting.get("region_id")

        # Tag every node committed in this round with a scene id so Finalization can
        # group the GEST nodes by scene and link scenes into a global timeline.
        existing_scene_ids = {
            (node.get("metadata") or {}).get("scene_id")
            for node in memory.get_gest_nodes(self.project_name, self.project_id)
            if (node.get("metadata") or {}).get("scene_id")
        }
        scene_id = (scene_spec or {}).get("scene_id") or f"scene-{len(existing_scene_ids) + 1}"

        self._log_step("scene_planning", "start", f"Building scene round(s) in region '{region_id}' ({scene_id})...")
        builder = SceneBuilder(self.project_name, self.project_id, episode_id=episode_id, scene_id=scene_id)
        all_nodes, all_edges = [], []
        try:
            builder.start_round(region_id, (scene_spec or {}).get("actors", []))
            for chain in (scene_spec or {}).get("chains", []):
                builder.start_chain(chain.get("actor"), chain.get("poi"))
                for act in chain.get("actions", []):
                    builder.add_action(
                        act.get("action"),
                        target_object=act.get("object"),
                        receiver_id=act.get("receiver"),
                        poi_id=act.get("poi"),
                    )
                result = builder.end_round()
                all_nodes += result.get("nodes", [])
                all_edges += result.get("edges", [])
        except SceneError as e:
            self._log_step("scene_planning", "error", f"Scene round rejected: {e}")
            repair = studio_repair.build_repair_report(
                "scene_planning", e, {"region_id": region_id, "scene_id": scene_id},
            )
            return {"ok": False, "phase": "scene_planning", "error": str(e), "repair": repair}

        self._log_step(
            "scene_planning", "complete",
            f"Committed {len(all_nodes)} GEST nodes and {len(all_edges)} edges.",
            {"nodes": all_nodes, "edges": all_edges},
        )
        return {
            "ok": True,
            "phase": "scene_planning",
            "data": {
                "scene_id": scene_id,
                "nodes": all_nodes,
                "edges": all_edges,
                "state": builder.state_payload(),
                "graph": memory.get_gest_graph(self.project_name, self.project_id),
            },
        }

    def run_finalization(self, scene_order=None):
        """Director Phase 4: Finalization — cross-scene temporal linking + timeline validation.

        Scenes are built in isolation (each `run_scene_round` tags its nodes with a `scene_id`),
        so the per-scene chains are not yet connected to each other. Finalization links them into
        one narrative flow: it orders the scenes (by an explicit `scene_order`, else by creation
        order), connects the last event of each scene to the first event of the next with a
        cross-scene `before` edge, and then resolves the whole GEST graph into a validated
        execution timeline (topological order; rejects if a temporal cycle exists).
        """
        self.state = "finalization"
        self._log_step("finalization", "start", "Linking scenes into a unified timeline...")

        nodes = memory.get_gest_nodes(self.project_name, self.project_id)
        scenes = {}
        for node in nodes:
            if node["node_type"] not in ("action", "event"):
                continue
            scene_id = (node.get("metadata") or {}).get("scene_id") or "unscened"
            scenes.setdefault(scene_id, []).append(node["id"])

        if not scenes:
            timeline = memory.compute_gest_timeline(self.project_name, self.project_id)
            self._log_step("finalization", "complete", "No scene events to link.")
            return {"ok": True, "phase": "finalization", "data": {"scenes": [], "edges_added": [], "timeline": timeline}}

        # Order scenes: honor an explicit order, then append any scenes it omitted (by creation order).
        if scene_order:
            ordered = [sid for sid in scene_order if sid in scenes]
            ordered += [sid for sid in sorted(scenes, key=lambda s: min(scenes[s])) if sid not in ordered]
        else:
            ordered = sorted(scenes, key=lambda s: min(scenes[s]))

        # Existing 'before' edges, so re-running Finalization stays idempotent (no duplicate links).
        existing_before = {
            (edge["source_id"], edge["target_id"])
            for edge in memory.get_gest_edges(self.project_name, self.project_id)
            if edge["relation"] == "before"
        }

        edges_added = []
        prev_tail = None
        for sid in ordered:
            node_ids = sorted(scenes[sid])
            head, tail = node_ids[0], node_ids[-1]
            if prev_tail is not None and (prev_tail, head) not in existing_before:
                try:
                    edge_id = memory.add_gest_edge(
                        self.project_name, self.project_id, prev_tail, head, "before",
                        metadata={"cross_scene": True},
                    )
                    edges_added.append(edge_id)
                    existing_before.add((prev_tail, head))
                except ValueError as e:
                    # A link that would create a temporal cycle is skipped, not fatal.
                    logger.info(f"Skipped cross-scene link {prev_tail}->{head}: {e}")
            prev_tail = tail

        timeline = memory.compute_gest_timeline(self.project_name, self.project_id)
        memory.set_user_preference(
            self.project_name, self.project_id, "gest_timeline",
            {"scene_order": ordered, "timeline": timeline},
        )
        self._log_step(
            "finalization", "complete",
            f"Linked {len(ordered)} scene(s); added {len(edges_added)} cross-scene edge(s); timeline valid={timeline['valid']}.",
            {"scene_order": ordered, "edges_added": edges_added},
        )
        result = {
            "ok": timeline.get("valid", True),
            "phase": "finalization",
            "data": {"scenes": ordered, "edges_added": edges_added, "timeline": timeline},
        }
        if not timeline.get("valid", True):
            # A cyclic/unsatisfiable timeline is a continuity rejection: offer repair
            # instead of returning a quietly-invalid "complete" result.
            self._log_step("finalization", "error", "Timeline is invalid (continuity cycle); offering repair.")
            result["error"] = timeline.get("error") or "Scenes form a temporal cycle; the timeline can't be ordered."
            result["repair"] = studio_repair.build_repair_report(
                "finalization", result["error"], {"scene_order": ordered},
            )
        return result

    def _scene_actor_id(self, value):
        text = re.sub(r"[^a-z0-9_]+", "_", str(value or "").strip().lower())
        text = re.sub(r"_+", "_", text).strip("_")
        return text or "actor"

    def _default_scene_spec(self, casting=None, characters=None):
        """Create a tiny registry-valid scene spec for the current cast/region.

        This is the deterministic fallback for Phase 3. It is intentionally small:
        one actor, one valid POI, and a short valid chain. Bigger narrative scene specs
        can be produced by the Director LLM, but the fallback must always commit cleanly.
        """
        casting = casting or memory.get_bible(self.project_name, self.project_id).get("casting") or {}
        characters = characters or memory.get_characters(self.project_name, self.project_id)
        region_id = casting.get("region_id") or "archive_hall"
        region = studio_capabilities.get_capability("regions", region_id) or studio_capabilities.get_capability("regions", "archive_hall")
        region_id = region["id"]

        cast_members = casting.get("cast") or []
        character_by_skin = {
            (char.get("metadata") or {}).get("skin_id"): char
            for char in characters
            if (char.get("metadata") or {}).get("skin_id")
        }
        first_cast = cast_members[0] if cast_members else {}
        skin_id = first_cast.get("skin_id") or "young_archivist"
        character = character_by_skin.get(skin_id) or (characters[0] if characters else {})
        name = character.get("name") or first_cast.get("character_name") or first_cast.get("skin_name") or "Scene Lead"
        actor_id = self._scene_actor_id(name)

        # Pick a known valid POI/action chain for each starter region.
        if region_id == "rain_market":
            poi_id = "tram_stop"
            actions = [{"action": "stand_at"}, {"action": "talk"}]
        elif region_id == "rooftop_shrine":
            poi_id = "shrine_gate"
            actions = [{"action": "stand_at"}, {"action": "observe"}, {"action": "call_out"}]
        else:
            poi_id = "archive_table"
            actions = [{"action": "stand_at"}, {"action": "inspect_object"}, {"action": "write_note"}]

        return {
            "region_id": region_id,
            "actors": [
                {
                    "id": actor_id,
                    "name": name,
                    "skin_id": skin_id,
                    "start_poi": poi_id,
                    "posture": "standing",
                }
            ],
            "chains": [
                {
                    "actor": actor_id,
                    "actions": actions,
                }
            ],
        }

    def run_director_scene_planning(self, premise=None, world=None, characters=None, story_plan=None):
        """Director Phase 3: generate a structured scene spec and delegate it to Scene Builder."""
        self.state = "director_scene_planning"
        bible = memory.get_bible(self.project_name, self.project_id)
        premise = premise if premise is not None else bible.get("premise") or {}
        world = world if world is not None else bible.get("world") or {}
        casting = bible.get("casting") or memory.get_user_preferences(self.project_name, self.project_id).get("director_casting") or {}
        characters = characters if characters is not None else memory.get_characters(self.project_name, self.project_id)
        if story_plan is None:
            episodes = memory.get_episodes(self.project_name, self.project_id)
            minutes = memory.get_minutes(self.project_name, self.project_id)
            story_plan = {
                "episodes": [{"name": ep.get("name"), "summary": ep.get("summary")} for ep in episodes],
                "minutes": [{"minute_number": m.get("minute_number"), "summary": m.get("summary")} for m in minutes],
            }

        self._log_step("director_scene_planning", "start", "Generating an isolated Scene Builder spec...")

        region_id = casting.get("region_id") or "archive_hall"
        pois = [
            poi for poi in studio_capabilities.list_capabilities("pois", page_size=100)["items"]
            if poi.get("region_id") == region_id
        ]
        actions = studio_capabilities.list_capabilities("actions", page_size=100)["items"]
        actor_menu = [
            {
                "id": self._scene_actor_id(char.get("name")),
                "name": char.get("name"),
                "skin_id": (char.get("metadata") or {}).get("skin_id"),
            }
            for char in characters
        ]
        if not actor_menu:
            actor_menu = self._default_scene_spec(casting=casting, characters=characters)["actors"]

        system_prompt = (
            "You are the Director delegating ONE isolated scene to the deterministic Scene Builder. "
            "Output ONLY a valid JSON scene_spec object. Use only the provided actor ids, region id, POI ids, and action ids. "
            "Keep it short: one region, 1-2 actors, and 1-2 chains. "
            "The Scene Builder will reject unsupported POI/action combinations, invalid ordering, missing held objects, and impossible receivers. "
            'Required shape: {"region_id":"id","actors":[{"id":"actor_id","name":"Name","skin_id":"skin","start_poi":"poi","posture":"standing"}],'
            '"chains":[{"actor":"actor_id","actions":[{"action":"stand_at"},{"action":"inspect_object"}]}]}'
        )
        prompt = (
            f"Premise: {json.dumps(premise)}\n"
            f"World: {json.dumps(world)}\n"
            f"Story plan: {json.dumps(story_plan)}\n"
            f"Casting: {json.dumps(casting)}\n"
            f"Allowed actors: {json.dumps(actor_menu)}\n"
            f"Allowed region: {region_id}\n"
            f"Allowed POIs in region: {json.dumps(pois)}\n"
            f"Allowed actions: {json.dumps(actions)}"
        )

        def fallback():
            return self._default_scene_spec(casting=casting, characters=characters)

        raw_spec = self._call_llm_with_fallback(prompt, system_prompt, fallback)
        if not isinstance(raw_spec, dict):
            raw_spec = fallback()

        result = self.run_scene_round(raw_spec)
        if not result.get("ok"):
            self.model_status["used_fallback"] = True
            self.model_status["messages"].append(f"Scene spec rejected: {result.get('error')}; fallback used.")
            self._log_step("director_scene_planning", "warning", f"Scene spec rejected ({result.get('error')}); using deterministic fallback.")
            raw_spec = fallback()
            result = self.run_scene_round(raw_spec)

        if result.get("ok"):
            memory.set_user_preference(self.project_name, self.project_id, "director_scene_spec", raw_spec)
            current_bible = memory.get_bible(self.project_name, self.project_id)
            current_bible["scene_spec"] = raw_spec
            memory.save_bible(self.project_name, self.project_id, current_bible)
            self._log_step("director_scene_planning", "complete", "Scene spec committed to GEST.", {"scene_spec": raw_spec})
            return {"ok": True, "phase": "director_scene_planning", "scene_spec": raw_spec, "data": result["data"]}

        self._log_step("director_scene_planning", "error", f"Fallback scene spec failed: {result.get('error')}")
        return {
            "ok": False,
            "phase": "director_scene_planning",
            "scene_spec": raw_spec,
            "error": result.get("error"),
            "repair": result.get("repair"),
        }

    def run_brief_review(self, seed_text, mode=MODE_SEED, source_story=None, user_notes=""):
        """Ask the local model for an understanding check before full production."""
        mode, source_story = self._resolve_source(seed_text, mode, source_story)
        self._persist_source(mode, source_story)
        self._log_step("brief_review", "start", f"Reviewing story brief before production (mode={mode})...")

        mode_instruction = {
            MODE_SEED: "The user wants to invent a new story from this seed.",
            MODE_ADAPT: "The user wants to adapt the supplied story faithfully into a storyboard.",
            MODE_CONTINUE: "The user wants to continue from the supplied story without retelling prior events.",
        }.get(mode, "The user wants a storyboarding plan.")

        system_prompt = (
            "You are a patient creative producer. Before generating anything final, check your understanding. "
            "Output MUST be a single valid JSON object: "
            '{"guess": "short plain-language summary of what you think the user wants", '
            '"open_questions": ["open-ended question 1", "open-ended question 2"], '
            '"small_fix_suggestions": ["specific thing user could clarify or change"], '
            '"confidence": "low|medium|high"} '
            "Do not make a full outline yet. Keep it collaborative and concise."
        )
        prompt = (
            f"Production mode: {mode}\n{mode_instruction}\n\n"
            f"User seed/story:\n{seed_text}\n\n"
            f"User notes or corrections so far:\n{user_notes or '(none)'}"
        )

        def fallback():
            excerpt = self._story_excerpt(source_story or seed_text)
            return {
                "guess": f"You want a {mode} Studio project based on: {excerpt[:240]}",
                "open_questions": [
                    "What emotional ending should this reel leave the viewer with?",
                    "Which character or relationship matters most in this piece?",
                    "Are there any details I must preserve exactly?"
                ],
                "small_fix_suggestions": [
                    "Add names, tone, or must-keep moments if those are important.",
                    "Tell me what to avoid if there is a direction that would feel wrong."
                ],
                "confidence": "medium"
            }

        data = self._call_llm_with_fallback(prompt, system_prompt, fallback)
        if not isinstance(data, dict):
            data = fallback()
        data.setdefault("guess", "")
        data.setdefault("open_questions", [])
        data.setdefault("small_fix_suggestions", [])
        data.setdefault("confidence", "medium")
        data["mode"] = mode
        data["model_status"] = dict(self.model_status)
        try:
            memory.set_user_preference(self.project_name, self.project_id, "brief_review", data)
        except Exception as e:
            logger.warning(f"Could not persist brief review: {e}")
        self._log_step("brief_review", "complete", "Generated pre-production understanding check.", data)
        return data

    # --- PIPELINE STAGES ---

    def run_intake_interview_turn(self, chat_history):
        """Phase 3: Conversational Intake Agent turn.
        
        chat_history: List of dicts [{"role": "user"|"assistant", "content": "..."}]
        """
        self._log_step("intake_interview", "start", "Processing conversational intake turn.")
        
        system_prompt = (
            "You are the Source Arcanum Intake Agent, a seasoned creative producer. Your goal is to interview the user and flesh out a 60-second comic reel concept.\n"
            "Your objectives:\n"
            "1. Uncover the core story (protagonist, central conflict).\n"
            "2. Define the desired aesthetic/tone.\n"
            "3. Identify the main character concepts.\n\n"
            "AGENTIC CONSTRAINTS & HARDWARE LIMITS:\n"
            "- A 60-second reel is extremely short. Do NOT allow sprawling epics.\n"
            "- Keep the scope tight: STRICT MAXIMUM of 2-3 characters and 1-2 locations.\n"
            "- If the user suggests something too large, politely but firmly ask them to narrow it down.\n"
            "- Only set 'is_complete' to true when you have explicitly gathered the protagonist, setting, conflict, and tone, AND the scope fits the hardware limits.\n\n"
            "Output MUST be a single valid JSON block with NO markdown wrapping. Format:\n"
            "{\n"
            '  "internal_thought": "Analyze the chat history. What is missing? Is the scope too big? What should I ask next?",\n'
            '  "response_text": "Your conversational response to the user. Ask ONE clear question at a time.",\n'
            '  "is_complete": true or false,\n'
            '  "draft_premise": {"title": "Working Title", "theme": "Working Theme", "premise": "Current summary of the story"}\n'
            "}"
        )
        
        transcript = ""
        for msg in chat_history:
            role = msg.get("role", "user").upper()
            transcript += f"{role}: {msg.get('content', '')}\n\n"
            
        prompt = f"Here is the conversation so far:\n{transcript}\n\nWhat is your next response?"
        
        def fallback():
            user_messages = [m["content"] for m in chat_history if m.get("role", "user")]
            last_msg = user_messages[-1] if user_messages else "Let's make a story."
            
            if len(user_messages) < 2:
                return {
                    "internal_thought": "The user has only provided one message. I need to ask about the emotional tone.",
                    "response_text": "That sounds like a great start! To help me scope this for a 60-second reel, what is the main emotional tone you're going for?",
                    "is_complete": False,
                    "draft_premise": {"title": "Untitled", "theme": "Unknown", "premise": last_msg[:100]}
                }
            else:
                return {
                    "internal_thought": "I have the protagonist, location, and tone. The scope fits our limits. I am ready.",
                    "response_text": "Perfect, I think I have enough to build the premise now!",
                    "is_complete": True,
                    "draft_premise": {"title": "Project Alpha", "theme": "Action", "premise": "A 60-second reel based on our chat."}
                }
                
        data = self._call_llm_with_fallback(prompt, system_prompt, fallback)
        self._log_step("intake_interview", "complete", "Generated conversational response.", data)
        return data

    def run_intake(self, seed_text, mode=MODE_SEED, source_story=None):
        """Stage 1: Intake & Premise Generation.

        seed mode     -> invent a premise from a short prompt.
        adapt mode     -> extract the premise of the dropped story faithfully.
        continue mode  -> derive the premise of the NEXT installment from canon.
        """
        mode, source_story = self._resolve_source(seed_text, mode, source_story)
        self.state = "intake"
        self._persist_source(mode, source_story)

        if mode == MODE_ADAPT:
            self._log_step("intake", "start", f"Adapting existing story ({len(source_story or '')} chars)...")
            system_prompt = (
                "You are a story development editor. The user has supplied a COMPLETE, already-written story. "
                "Read it and extract its ACTUAL premise faithfully — do NOT invent a new plot or change events. "
                "Output MUST be a single valid JSON block like: "
                '{"title": "Story Title", "theme": "Core Theme", "premise": "2-sentence premise drawn from the text"}'
            )
            prompt = f"Extract the premise of this existing story so it can be storyboarded faithfully.{self._canon_block(source_story)}"

            def fallback():
                analysis = self._analysis(source_story or seed_text)
                if analysis:
                    leads = ", ".join(c["name"] for c in analysis["characters"][:3]) or "the protagonist"
                    place = analysis["locations"][0]["name"] if analysis["locations"] else "the story's world"
                    return {
                        "title": analysis["title"],
                        "theme": f"A {analysis['tone']} story of {leads}",
                        "premise": (
                            f"A faithful comic-reel adaptation following {leads} through {place}. "
                            f"{analysis['summary']}"
                        ),
                    }
                snippet = (source_story or seed_text or "").strip()
                first_line = (snippet.split("\n", 1)[0] or "Untitled Story").strip()[:60]
                return {
                    "title": first_line.title() if first_line else "Untitled Story",
                    "theme": "Adapted from the provided manuscript",
                    "premise": f"A faithful comic-reel adaptation of the supplied story. Opening: {snippet[:180]}"
                }

        elif mode == MODE_CONTINUE:
            self._log_step("intake", "start", f"Continuing existing story ({len(source_story or '')} chars)...")
            system_prompt = (
                "You are a story development editor. The user has supplied an existing story that is CANON. "
                "Do NOT retell it. Devise the premise for the NEXT installment that continues forward from where it ends, "
                "preserving the established characters, world, and tone. "
                "Output MUST be a single valid JSON block like: "
                '{"title": "Next Installment Title", "theme": "Core Theme", "premise": "2-sentence premise for what happens next"}'
            )
            prompt = f"Given this canon story, devise the premise for what happens NEXT (a continuation, not a recap).{self._canon_block(source_story)}"

            def fallback():
                analysis = self._analysis(source_story or seed_text)
                snippet = (source_story or seed_text or "").strip()
                if analysis:
                    leads = ", ".join(c["name"] for c in analysis["characters"][:3]) or "the surviving cast"
                    return {
                        "title": f"{analysis['title']} — The Next Chapter",
                        "theme": f"Continuation & consequence in a {analysis['tone']} key",
                        "premise": (
                            f"Picking up immediately after the established events, {leads} face the next challenge "
                            f"raised by where the story left off. Prior canon ended: ...{snippet[-180:]}"
                        ),
                    }
                return {
                    "title": "The Story Continues",
                    "theme": "Continuation & Consequence",
                    "premise": (
                        "Picking up immediately after the established events, the cast faces the next challenge raised "
                        f"by where the story left off. Prior canon ended: ...{snippet[-180:]}"
                    )
                }

        else:
            self._log_step("intake", "start", f"Processing story seed: '{(seed_text or '')[:40]}...'")
            system_prompt = (
                "You are a story development editor. Parse the story seed and generate a project premise. "
                "Output MUST be a single valid JSON block like: "
                '{"title": "Project Title", "theme": "Core Theme", "premise": "2-sentence premise statement"}'
            )
            prompt = f"Story seed: {seed_text}"

            def fallback():
                # Seed-specific naming
                words = (seed_text or "").split()
                title_part = " ".join(words[:3]).title() if words else "Untitled Adventure"
                return {
                    "title": f"Source Arcanum: {title_part}",
                    "theme": "Exploration & Consequence",
                    "premise": f"Based on seed: '{seed_text}'. A group of adventurers unravel a long-lost secret that threatens to reshape their world."
                }

        data = self._call_llm_with_fallback(prompt, system_prompt, fallback)

        # Store premise + mode in the bible so later stages and the export carry the production style.
        memory.save_bible(self.project_name, self.project_id, {"premise": data, "mode": mode})
        self._log_step("intake", "complete", "Generated and stored premise.", data)
        return data

    def run_world_building(self, premise_data, mode=None, source_story=None):
        """Stage 2: World Building (World Builder agent).

        Produces a *structured* world bible in two small, schema-checked calls instead of one
        vague blob: (1) the world core (setting, genre/tone rules, palette, lighting, danger,
        factions, materials) and (2) a short list of named locations with their own visual
        prompts. The named palette/lighting/locations are what later let image prompts be
        specific instead of "cinematic comic panel, high detail" boilerplate.
        """
        mode = self._normalize_mode(mode) if mode is not None else self.mode
        source_story = source_story if source_story is not None else self.source_story
        self.state = "world_building"
        self._log_step("world_building", "start", "Generating structured world bible...")

        grounding = ""
        if source_story and mode in (MODE_ADAPT, MODE_CONTINUE):
            grounding = self._canon_block(source_story)
            stance = ("Extract the world that is ACTUALLY present in the story; do not invent "
                      "elements it does not support." if mode == MODE_ADAPT else
                      "Preserve the established world and extend it forward consistently.")
        else:
            stance = "Invent a vivid, internally consistent world that fits the premise."

        # --- Call 1: world core ---
        core_system = (
            "You are the World Builder, a specialist who designs the rules and look of a world. "
            + stance + " Output ONLY a JSON object with these fields: "
            '{"setting": "2-3 sentence setting", "genre_rules": ["..."], "tone_rules": ["..."], '
            '"palette": "named colors that define the look", "materials": "key textures/materials", '
            '"lighting": "how scenes are lit", "factions": ["group: one-line role"], '
            '"danger_level": "low|medium|high with a why"}'
        )
        core_prompt = f"Premise: {json.dumps(premise_data)}{grounding}"

        def core_fallback():
            analysis = self._analysis(source_story) if source_story else None
            if analysis:
                places = ", ".join(p["name"] for p in analysis["locations"][:4])
                setting = studio_generation.sentence_safe_trim(
                    (f"The world of the supplied story, centered on {places}. " if places else "")
                    + (analysis["summary"] or ""), 260)
                return {
                    "setting": setting or "The world as established in the supplied story.",
                    "genre_rules": ["Honor the source story's established facts without contradiction."],
                    "tone_rules": [f"Maintain a {analysis['tone']} tone throughout."],
                    "palette": analysis["aesthetic"],
                    "materials": "Textures consistent with the source story's setting.",
                    "lighting": f"Lighting that reinforces the {analysis['tone']} mood.",
                    "factions": [],
                    "danger_level": "medium — driven by the story's central conflict.",
                }
            return {
                "setting": "A neon-soaked harbor city where old money and new crime share the same fog.",
                "genre_rules": ["Grounded noir: no magic; consequences are physical and social."],
                "tone_rules": ["Wry, tense, intimate. Let silence do work."],
                "palette": "Sodium amber, rain-slick black, bruised teal, cigarette red.",
                "materials": "Wet asphalt, brushed brass, worn leather, frosted glass.",
                "lighting": "Low-key, single-source practical lights and hard shadows.",
                "factions": ["Dockside crew: small-time operators", "The Office: the people who collect"],
                "danger_level": "high — debts come due in person.",
            }

        world = self._generate_structured(
            core_prompt, core_system, core_fallback,
            required_keys=WORLD_CORE_KEYS, shape="medium",
        )

        # --- Call 2: named locations (their own visual prompts) ---
        loc_system = (
            "You are the World Builder's location designer. Given the world, list 2-4 concrete "
            "locations where scenes happen. Output ONLY a JSON list: "
            '[{"name": "Place Name", "visual_prompt": "what an artist would draw: architecture, '
            'props, atmosphere", "mood": "one or two mood words"}]'
        )
        loc_prompt = f"World: {json.dumps(world)}\nPremise: {json.dumps(premise_data)}{grounding}"

        def loc_fallback():
            analysis = self._analysis(source_story) if source_story else None
            if analysis and analysis["locations"]:
                return [
                    {
                        "name": p["name"],
                        "visual_prompt": studio_generation.sentence_safe_trim(
                            p.get("description") or f"{p['name']}, a location from the story.", 180),
                        "mood": analysis["tone"],
                    }
                    for p in analysis["locations"][:4]
                ]
            return [
                {"name": "The Back Room", "visual_prompt": "A windowless basement club, low brass lamps, "
                 "cigarette haze, a battered piano in the corner.", "mood": "smoky, watchful"},
                {"name": "The Waterfront", "visual_prompt": "Fog over black water, shipping containers, "
                 "a single buzzing dock light, gulls.", "mood": "cold, exposed"},
            ]

        locations = self._generate_structured(
            loc_prompt, loc_system, loc_fallback, item_keys=WORLD_LOCATION_KEYS, shape="medium",
        )
        world["locations"] = locations
        # Keep a legacy `aesthetic` string so older readers/exports still work.
        world.setdefault("aesthetic", world.get("palette", ""))
        data = world

        # Merge with current bible memory
        current_bible = memory.get_bible(self.project_name, self.project_id)
        current_bible["world"] = data
        memory.save_bible(self.project_name, self.project_id, current_bible)

        # Persist the structured locations as reusable location assets (for seed mode too).
        try:
            existing = {loc["name"].lower() for loc in memory.get_locations(self.project_name, self.project_id)}
            for place in locations:
                nm = str(place.get("name") or "").strip()
                if not nm or nm.lower() in existing:
                    continue
                memory.add_location(
                    self.project_name, self.project_id, nm,
                    studio_generation.sentence_safe_trim(place.get("visual_prompt") or nm, 240),
                    metadata={"source": "world_builder", "mood": place.get("mood", "")},
                )
                existing.add(nm.lower())
        except Exception as e:
            logger.warning(f"Could not persist world locations: {e}")

        # For adapt/continue, persist the manuscript's real places as reusable location
        # assets so the locations table reflects the actual story, not just the cast region.
        if source_story and mode in (MODE_ADAPT, MODE_CONTINUE):
            analysis = self._analysis(source_story)
            if analysis:
                existing = {loc["name"].lower() for loc in memory.get_locations(self.project_name, self.project_id)}
                for place in analysis.get("locations", [])[:6]:
                    if place["name"].lower() in existing:
                        continue
                    try:
                        memory.add_location(
                            self.project_name, self.project_id,
                            place["name"],
                            (place.get("description") or f"{place['name']}, a location established in the source story.")[:240],
                            metadata={"source": "story_analysis", "mentions": place.get("mentions", 0)},
                        )
                    except Exception as e:
                        logger.warning(f"Could not add story location {place['name']}: {e}")

        self._log_step("world_building", "complete", "Generated and stored world bible.", data)
        return data

    def _character_roster(self, mode, source_story, casting):
        """Decide WHO is in the cast before fleshing anyone out.

        Returns a list of lightweight seeds: {name, role, skin_id, grounding}. The roster is
        derived deterministically (from the source story's real cast, or the Director casting
        anchor) so the expensive per-character expansion stays focused and grounded.
        """
        cast = casting.get("cast") or []
        seeds = []

        if source_story and mode in (MODE_ADAPT, MODE_CONTINUE):
            # Prefer the Loremaster's deep dossiers (built from the WHOLE story) over the
            # heuristic analyzer roster, so characters who only appear in the middle of a
            # long manuscript are cast — and each seed carries real, story-derived depth.
            understanding = self._understanding(source_story) or {}
            dossiers = understanding.get("character_dossiers") or []
            roles = ["lead", "rival", "supporting", "supporting"]
            for i, dossier in enumerate(dossiers[:4]):
                name = (dossier.get("name") or "").strip()
                if not name:
                    continue
                seeds.append({
                    "name": name,
                    "role": dossier.get("role") or (roles[i] if i < len(roles) else "supporting"),
                    "skin_id": cast[i]["skin_id"] if i < len(cast) else None,
                    # The full dossier grounds the expansion (traits/want/wound/secret/voice),
                    # not just one quoted line. Used to EXPAND, never stored verbatim.
                    "dossier": dossier,
                    "grounding": _dossier_grounding(dossier),
                })
            if seeds:
                return seeds

            # Fallback: heuristic analyzer roster if the Loremaster produced no dossiers.
            analysis = self._analysis(source_story)
            people = (analysis or {}).get("characters") or []
            for i, person in enumerate(people[:4]):
                seeds.append({
                    "name": person["name"],
                    "role": roles[i] if i < len(roles) else "supporting",
                    "skin_id": cast[i]["skin_id"] if i < len(cast) else None,
                    "grounding": (person.get("sample_line") or person.get("description") or "").strip(),
                })
            if seeds:
                return seeds

        # Director casting anchor (seed mode or no analyzable source).
        for member in cast:
            seeds.append({
                "name": member["character_name"],
                "role": member.get("role", "supporting"),
                "skin_id": member.get("skin_id"),
                "grounding": member.get("skin_name", ""),
            })
        if seeds:
            return seeds

        # Last resort: two unnamed leads the expansion step will name via premise context.
        return [
            {"name": "Lead", "role": "protagonist", "skin_id": None, "grounding": ""},
            {"name": "Foil", "role": "deuteragonist", "skin_id": None, "grounding": ""},
        ]

    def _expand_character(self, seed, premise_data, world_data, mode, source_story):
        """Expand one roster seed into a full structured character bible via a single small,
        schema-checked LLM call (with a structured deterministic fallback)."""
        stance = ("Stay faithful to how this character appears in the source story."
                  if source_story and mode in (MODE_ADAPT, MODE_CONTINUE)
                  else "Invent a distinctive, premise-appropriate character.")
        system_prompt = (
            "You are the Character Creator, a specialist who writes one character bible at a time. "
            + stance + " Expand the seed into a real, specific person — do NOT echo the seed text "
            "back verbatim. Output ONLY a JSON object: "
            '{"name": "...", "role": "...", "archetype": "...", "personality": "2-3 traits with edge", '
            '"goals": "what they want now", "fears": "what they avoid", "secrets": "what they hide", '
            '"relationships": "who matters to them and how", '
            '"speech_style": "how they talk: rhythm, vocabulary, verbal tics", '
            '"visual": {"face": "...", "hair": "...", "build": "...", "outfit": "...", "palette": "signature colors"}, '
            '"voice_profile": {"tone": "...", "pace": "...", "accent": "..."}}'
        )
        grounding = f"\nHow they appear in the source: {seed['grounding']}" if seed.get("grounding") else ""
        prompt = (
            f"Seed: name={seed['name']}, role={seed['role']}\n"
            f"Premise: {json.dumps(premise_data)}\nWorld palette/tone: "
            f"{json.dumps({k: world_data.get(k) for k in ('palette', 'tone_rules', 'setting')})}"
            f"{grounding}"
        )

        def fallback():
            tone = (self._analysis(source_story) or {}).get("tone", "grounded") if source_story else "grounded"
            # Ground the fallback in the Loremaster dossier when present, so an offline run
            # still yields a character shaped by the real story rather than generic noir.
            dossier = seed.get("dossier") if isinstance(seed.get("dossier"), dict) else {}
            traits = ", ".join(str(t) for t in (dossier.get("traits") or [])) or \
                "Guarded, quick-witted, carries more weight than they show."
            rels = dossier.get("relationships") or []
            rel_text = "; ".join(
                f"{r.get('who', '')} ({r.get('bond', '')})".strip() if isinstance(r, dict) else str(r)
                for r in rels if r
            ) or "Bound to the others by obligation more than trust."
            arc = (f"From wanting {dossier['want']} to needing {dossier['need']}."
                   if dossier.get("want") and dossier.get("need")
                   else "Learning to trust again despite past betrayals.")
            return {
                "name": seed["name"],
                "role": seed["role"],
                "archetype": "Lead" if "lead" in seed["role"].lower() or "protagon" in seed["role"].lower() else "Supporting",
                "personality": traits,
                "goals": dossier.get("want") or "Get through the next hour without losing what little they have left.",
                "fears": "Being seen as expendable.",
                "secrets": dossier.get("secret") or "Owes someone dangerous and can't pay.",
                "relationships": rel_text,
                "backstory": "Forged by the events of the story; their past surfaces in what they protect.",
                "core_wounds": dossier.get("wound") or "Abandoned when they needed help the most.",
                "character_arc": arc,
                "speech_style": studio_generation.sentence_safe_trim(
                    dossier.get("voice") or seed.get("grounding") or "Clipped, dry, says less than they mean.", 140),
                "visual": {
                    "face": "lived-in, alert eyes", "hair": "unfussed, practical",
                    "build": "average, tense", "outfit": "worn everyday clothes that fit the world",
                    "palette": world_data.get("palette", "muted, low-key"),
                },
                "voice_profile": {"tone": tone, "pace": "measured", "accent": "local"},
            }

        bible = self._generate_structured(
            prompt, system_prompt, fallback, required_keys=CHARACTER_BIBLE_KEYS, shape="medium",
        )
        bible.setdefault("name", seed["name"])
        bible.setdefault("role", seed["role"])
        bible["skin_id"] = seed.get("skin_id")
        return bible

    def run_character_building(self, premise_data, world_data, mode=None, source_story=None):
        """Stage 3: Character Building (Character Creator agent).

        Two steps: (1) deterministically decide the roster, then (2) expand each character into
        a full structured bible in its own small call (batched by the model tier). This replaces
        the old single blob that stored 1-sentence excerpts like 'Speaks like: "..."'.
        """
        mode = self._normalize_mode(mode) if mode is not None else self.mode
        source_story = source_story if source_story is not None else self.source_story
        self.state = "character_building"
        self._log_step("character_building", "start", "Building structured character bibles...")
        casting = memory.get_bible(self.project_name, self.project_id).get("casting") or {}

        seeds = self._character_roster(mode, source_story, casting)
        total = len(seeds)
        progress = {"n": 0}

        def expand_batch(batch):
            out = []
            for s in batch:
                progress["n"] += 1
                self._progress("characters", f"Writing character {progress['n']} of {total}: {s.get('name', '')}")
                out.append(self._expand_character(s, premise_data, world_data, mode, source_story))
            return out

        bibles = self._batched(seeds, expand_batch, self.profile["characters_per_call"])

        saved_chars = []
        for bible in bibles:
            # A short synthesized description for legacy list/card displays; the rich data lives
            # in metadata["bible"] and voice_profile.
            description = studio_generation.sentence_safe_trim(
                f"{bible.get('personality', '')} {bible.get('goals', '')}".strip()
                or f"{bible.get('name')} — {bible.get('role')}", 200)
            char_id = memory.add_character(
                self.project_name,
                self.project_id,
                bible["name"],
                description,
                bible.get("role", ""),
                bible.get("archetype", ""),
                voice_profile=bible.get("voice_profile"),
                metadata={
                    "skin_id": bible.get("skin_id"),
                    # A character anchored to a Director casting skin keeps that provenance;
                    # otherwise it was authored fresh by the Character Creator.
                    "source": "director_casting" if bible.get("skin_id") else "character_creator",
                    "bible": bible,
                    "visual": bible.get("visual"),
                    "speech_style": bible.get("speech_style"),
                },
            )
            record = dict(bible)
            record["id"] = char_id
            record["description"] = description
            saved_chars.append(record)

        self._log_step("character_building", "complete", f"Built {len(saved_chars)} character bibles.", {"characters": saved_chars})
        return saved_chars

    def run_treatment(self, premise_data, world_data, characters, mode=None, source_story=None):
        """Stage 3.5: Treatment (Story Editor agent).

        Expands the thin 2-sentence premise into a short treatment — logline, synopsis,
        central conflict, intended ending, theme, tone — that every downstream agent reads.
        This is the "interpret + expand" step that turns a seed into a story with a spine,
        instead of asking the planner to invent everything from two sentences.
        """
        mode = self._normalize_mode(mode) if mode is not None else self.mode
        source_story = source_story if source_story is not None else self.source_story
        self.state = "treatment"
        self._log_step("treatment", "start", "Expanding premise into a treatment...")

        if source_story and mode in (MODE_ADAPT, MODE_CONTINUE):
            stance = ("Summarize the supplied story's actual spine — do not invent a new plot."
                      if mode == MODE_ADAPT else
                      "Describe the spine of what happens NEXT, after the supplied story ends.")
            grounding = self._canon_block(source_story)
        else:
            stance = "Expand the premise into a focused 60-second spine with a clear ending."
            grounding = ""

        system_prompt = (
            "You are the Story Editor. " + stance + " Keep it tight: this is a 60-second reel. "
            "Output ONLY a JSON object: "
            '{"logline": "one vivid sentence", "synopsis": "3-4 sentence spine with a beginning, '
            'turn, and ending", "central_conflict": "the core tension", "ending": "how it lands", '
            '"theme": "what it is really about", "tone": "the felt mood"}'
        )
        cast = ", ".join(c.get("name", "") for c in characters if c.get("name"))
        prompt = (
            f"Premise: {json.dumps(premise_data)}\n"
            f"World: {json.dumps({k: world_data.get(k) for k in ('setting', 'tone_rules')})}\n"
            f"Cast: {cast}{grounding}"
        )

        def fallback():
            analysis = self._analysis(source_story) if source_story else None
            lead = characters[0]["name"] if characters else "the lead"
            synopsis = (analysis or {}).get("summary") or premise_data.get("premise", "")
            return {
                "logline": premise_data.get("premise", f"{lead} faces a decisive hour."),
                "synopsis": studio_generation.sentence_safe_trim(synopsis, 320)
                            or f"{lead} is pulled into a conflict, forced to choose, and pays the cost.",
                "central_conflict": "What the lead wants collides with what the situation demands.",
                "ending": "A decisive, earned beat that lands the theme.",
                "theme": premise_data.get("theme", "consequence"),
                "tone": (analysis or {}).get("tone", "grounded"),
            }

        treatment = self._generate_structured(
            prompt, system_prompt, fallback,
            required_keys=["logline", "synopsis", "ending"], shape="medium",
        )
        current_bible = memory.get_bible(self.project_name, self.project_id)
        current_bible["treatment"] = treatment
        memory.save_bible(self.project_name, self.project_id, current_bible)
        self._log_step("treatment", "complete", "Stored story treatment.", treatment)
        return treatment

    def run_story_planning(self, premise_data, world_data, characters, mode=None, source_story=None):
        """Stage 4: Story Planning (60-Second Episode Plan).

        adapt mode    -> condense the existing story's real arc into three beats.
        continue mode -> plan the three beats that come AFTER the existing story ends.
        seed mode     -> plan an original arc.
        """
        mode = self._normalize_mode(mode) if mode is not None else self.mode
        source_story = source_story if source_story is not None else self.source_story
        self.state = "story_planning"
        self._log_step("story_planning", "start", "Creating 60-second episode plan...")

        # The treatment (if present) is the spine the beats must serve.
        treatment = memory.get_bible(self.project_name, self.project_id).get("treatment") or {}
        spine = f"\nTreatment spine (follow this): {json.dumps(treatment)}" if treatment else ""

        if source_story and mode == MODE_ADAPT:
            system_prompt = (
                "You are a storyboard director. Condense the ACTUAL arc of the supplied story into a 60-second reel: "
                "three major beats and three canon events, all drawn from real events in the text (in order). "
                "Output MUST be a single valid JSON block: "
                '{"summary": "Overall episode summary", "episodes": [{"name": "Beat Name", "summary": "Beat summary"}], '
                '"canon_events": [{"description": "Event detail", "time_index": "0:XX"}]}'
            )
            prompt = (
                f"Premise: {json.dumps(premise_data)}\nWorld: {json.dumps(world_data)}\n"
                f"Characters: {json.dumps(characters)}{self._canon_block(source_story)}"
            )
        elif source_story and mode == MODE_CONTINUE:
            system_prompt = (
                "You are a storyboard director. Plan the NEXT 60 seconds of story that occur AFTER the supplied canon ends. "
                "Do NOT retell prior events. Provide three forward-moving beats and three new canon events. "
                "Output MUST be a single valid JSON block: "
                '{"summary": "Overall episode summary", "episodes": [{"name": "Beat Name", "summary": "Beat summary"}], '
                '"canon_events": [{"description": "Event detail", "time_index": "0:XX"}]}'
            )
            prompt = (
                f"Premise (what happens next): {json.dumps(premise_data)}\nWorld: {json.dumps(world_data)}\n"
                f"Characters: {json.dumps(characters)}{self._canon_block(source_story, label='PRIOR STORY')}"
            )
        else:
            system_prompt = (
                "You are a storyboard director. Create a structured 60-second story arc divided into three major beats (episodes/scenes) "
                "and three canon events. Output MUST be a single valid JSON block: "
                '{"summary": "Overall episode summary", "episodes": [{"name": "Beat Name", "summary": "Beat summary"}], '
                '"canon_events": [{"description": "Event detail", "time_index": "0:XX"}]}'
            )
            prompt = f"Premise: {json.dumps(premise_data)}\nWorld: {json.dumps(world_data)}\nCharacters: {json.dumps(characters)}"

        prompt += spine

        def fallback():
            if source_story and mode in (MODE_ADAPT, MODE_CONTINUE):
                analysis = self._analysis(source_story)
                summary = premise_data.get("premise", "A continuation of the supplied story.")
                if analysis and analysis["beats"]:
                    beats = analysis["beats"]
                    time_slots = ["0:15", "0:35", "0:50", "0:58"]
                    return {
                        "summary": analysis["summary"] or summary,
                        "episodes": [
                            {"name": b["name"], "summary": b["summary"]}
                            for b in beats
                        ],
                        "canon_events": [
                            {"description": b["summary"][:160], "time_index": time_slots[min(i, len(time_slots) - 1)]}
                            for i, b in enumerate(beats)
                        ],
                    }
                lead = characters[0]["name"] if characters else "The protagonist"
                stage_word = "continues" if mode == MODE_CONTINUE else "unfolds"
                return {
                    "summary": summary,
                    "episodes": [
                        {"name": "Setup", "summary": f"{lead}'s situation {stage_word} as the scene opens."},
                        {"name": "Turn", "summary": "A complication forces a decisive choice."},
                        {"name": "Payoff", "summary": "The beat resolves and sets up what follows."}
                    ],
                    "canon_events": [
                        {"description": f"{lead} takes the opening action.", "time_index": "0:15"},
                        {"description": "The central complication lands.", "time_index": "0:35"},
                        {"description": "The beat reaches its turning point.", "time_index": "0:50"}
                    ]
                }
            return {
                "summary": "Silas and Vivienne infiltrate the Iron Guild vaults to acquire the Core Engine key.",
                "episodes": [
                    {"name": "The Infiltration", "summary": "Silas slips past the steam sentinel gears at 0:10."},
                    {"name": "The Discovery", "summary": "Vivienne deciphers the runic pressure locks at 0:35."},
                    {"name": "The Alarm", "summary": "An alarm triggers; they escape into the lower piping at 0:55."}
                ],
                "canon_events": [
                    {"description": "Silas unlocks the vault primary gear.", "time_index": "0:15"},
                    {"description": "Vivienne steals the arcane Core Engine key.", "time_index": "0:40"},
                    {"description": "A steam pipe ruptures, blocking the sentinels.", "time_index": "0:50"}
                ]
            }

        story_data = self._call_llm_with_fallback(prompt, system_prompt, fallback)
        if not self._is_valid_story_plan(story_data):
            self.model_status["used_fallback"] = True
            self.model_status["messages"].append("Story planning returned malformed JSON shape; fallback used.")
            self._log_step("story_planning", "warning", "Story planning returned malformed JSON shape; using deterministic fallback.")
            story_data = fallback()

        # Save Episode
        ep_id = memory.add_episode(self.project_name, self.project_id, premise_data.get("title", "Episode 1"), story_data["summary"])

        # Save minutes
        for idx, beat in enumerate(story_data["episodes"]):
            memory.add_minute(self.project_name, self.project_id, ep_id, idx + 1, f"{beat['name']}: {beat['summary']}")

        # Save canon events
        for event in story_data["canon_events"]:
            memory.add_canon_event(self.project_name, self.project_id, event["description"], event["time_index"])

        self._save_storyboard(story_data, ep_id=ep_id)
        self._log_step("story_planning", "complete", "Created and stored story plan.", story_data)
        return story_data, ep_id

    def run_showrunner(self, premise_data=None, world_data=None, characters=None,
                       mode=None, source_story=None):
        """Stage 4 (cinematic): Showrunner — dynamic scene blueprint + setup/payoff gate.

        Replaces the hardcoded 3-beat planner for the cinematic path. Decides how many
        scenes the story actually needs (from the Loremaster timeline, not a fixed count),
        emits a per-scene blueprint with explicit setup→payoff, persists it, and mirrors it
        onto the legacy storyboard so the existing approval gate/editor keep working.
        Returns (storyboard, episode_id, blueprint).
        """
        mode = self._normalize_mode(mode) if mode is not None else self.mode
        source_story = source_story if source_story is not None else self.source_story
        self.state = "showrunner"
        self._log_step("showrunner", "start", "Breaking the story into scenes...")

        state = self._context_state()
        world_data = world_data or state["world"]
        characters = characters or state["characters"]
        understanding = (
            self._understanding(source_story)
            or state["bible"].get("story_understanding")
            or {}
        )
        if premise_data is None:
            premise_data = state["premise"]

        blueprint = studio_showrunner.build_blueprint(
            understanding, world=world_data, characters=characters,
            llm_call=self._call_llm_with_fallback, profile=self.profile,
            progress=lambda m: self._progress("showrunner", m),
            taste=studio_taste.digest_clause(self.project_name, self.project_id),
        )

        # Persist the rich blueprint, and mirror onto the legacy storyboard shape so the
        # existing review gate / editor / minutes plumbing all keep functioning.
        try:
            current_bible = memory.get_bible(self.project_name, self.project_id)
            current_bible["scene_blueprint"] = blueprint
            memory.save_bible(self.project_name, self.project_id, current_bible)
            studio_blackboard.put_artifact(
                self.project_name, self.project_id, "scene_blueprint", blueprint,
                produced_by="showrunner", status="needs_user_review",
            )
        except Exception as e:
            logger.warning(f"Could not persist scene blueprint: {e}")

        storyboard = studio_showrunner.blueprint_to_storyboard(blueprint)
        # Idempotent: reuse this project's episode on a re-run instead of piling up duplicate
        # episodes/minutes. Update its summary; rewrite minutes in place to match the new beats.
        episodes = memory.get_episodes(self.project_name, self.project_id)
        if episodes:
            ep_id = episodes[0]["id"]
            memory.update_episode(self.project_name, self.project_id, ep_id, summary=storyboard.get("summary", ""))
        else:
            ep_id = memory.add_episode(
                self.project_name, self.project_id,
                (premise_data or {}).get("title", "Episode 1"),
                storyboard.get("summary", ""),
                metadata={"source": "showrunner", "scene_count": blueprint.get("scene_count")},
            )
        existing_minutes = [m for m in memory.get_minutes(self.project_name, self.project_id)
                            if m.get("episode_id") == ep_id]
        for idx, beat in enumerate(storyboard.get("episodes", [])):
            summary = f"{beat['name']}: {beat['summary']}"
            if idx < len(existing_minutes):
                memory.update_minute(self.project_name, self.project_id, existing_minutes[idx]["id"], summary=summary)
            else:
                memory.add_minute(self.project_name, self.project_id, ep_id, idx + 1, summary)
        if len(storyboard.get("episodes", [])) < len(existing_minutes):
            for m in existing_minutes[len(storyboard.get("episodes", [])):]:
                memory.delete_minute(self.project_name, self.project_id, m["id"])
        self._save_storyboard(storyboard, ep_id=ep_id, status="needs_user_review")

        self._log_step("showrunner", "complete",
                       f"Drafted a {blueprint.get('scene_count')}-scene blueprint "
                       f"with {len(blueprint.get('setups', []))} setup/payoff threads.",
                       blueprint)
        return storyboard, ep_id, blueprint

    def run_scenes(self, blueprint=None, ep_id=None, mode=None, source_story=None):
        """Stage 5 (cinematic): Scriptwriter + Cinematographer — write every scene.

        Replaces the 12-panel comic back half. For each blueprint scene it writes an
        authored ``narration_script`` (flowing narration + in-voice dialogue, paced to the
        scene's length — not balloons) and one evocative image prompt (via studio_visual).
        Persists a ``scenes`` artifact (the new spine) and mirrors each scene onto a
        panel + dialogue rows so the existing export/UI keep working. Because every
        script beat is non-empty, this path also avoids the legacy empty-dialogue crash.
        Returns the list of written scenes.
        """
        mode = self._normalize_mode(mode) if mode is not None else self.mode
        source_story = source_story if source_story is not None else self.source_story
        self.state = "scriptwriting"

        state = self._context_state()
        if blueprint is None:
            blueprint = state["bible"].get("scene_blueprint") or {}
        if not blueprint.get("scenes"):
            # No blueprint yet — produce one so this stage can run stand-alone.
            _, ep_id, blueprint = self.run_showrunner(mode=mode, source_story=source_story)

        understanding = self._understanding(source_story) or state["bible"].get("story_understanding") or {}
        characters = state["characters"]
        world_data = state["world"]

        self._log_step("scriptwriting", "start",
                       f"Writing {len(blueprint.get('scenes', []))} cinematic scenes...")
        scenes = studio_scriptwriter.build_scenes(
            blueprint, understanding=understanding, world=world_data, characters=characters,
            llm_call=self._call_llm_with_fallback, profile=self.profile,
            progress=lambda m: self._progress("scriptwriting", m),
            taste=studio_taste.digest_clause(self.project_name, self.project_id),
        )

        # Persist the new spine + the voice guide (so continuity can check drift and a single-scene
        # regenerate stays voice-consistent).
        try:
            current_bible = memory.get_bible(self.project_name, self.project_id)
            current_bible["scenes"] = scenes
            memory.save_bible(self.project_name, self.project_id, current_bible)
            studio_blackboard.put_artifact(
                self.project_name, self.project_id, "scenes", scenes, produced_by="scriptwriter",
            )
            memory.set_user_preference(
                self.project_name, self.project_id, "voice_guide",
                studio_scriptwriter.build_voice_guide(characters, understanding))
        except Exception as e:
            logger.warning(f"Could not persist scenes artifact: {e}")

        # Mirror onto panels + dialogue rows for export/back-compat.
        self._persist_scenes_as_panels(scenes, ep_id, blueprint)

        self._log_step("scriptwriting", "complete",
                       f"Wrote {len(scenes)} scenes "
                       f"({sum(len(s['narration_script']) for s in scenes)} script beats).",
                       {"scenes": scenes})
        return scenes

    def _persist_scenes_as_panels(self, scenes, ep_id, blueprint):
        """Write each cinematic scene to a panel + its narration beats as dialogue rows, so
        export and any panel-reading UI keep functioning while the spine becomes scene-based."""
        episodes = memory.get_episodes(self.project_name, self.project_id)
        if ep_id is None:
            ep_id = episodes[-1]["id"] if episodes else memory.add_episode(
                self.project_name, self.project_id, "Episode 1",
                (blueprint or {}).get("summary", ""), metadata={"source": "scenes"})
        minutes = [m for m in memory.get_minutes(self.project_name, self.project_id)
                   if m.get("episode_id") == ep_id]
        page_id = memory.ensure_page(
            self.project_name, self.project_id, ep_id, 1, title="Scenes",
            summary=(blueprint or {}).get("summary", ""),
            metadata={"source": "scenes", "scene_count": len(scenes)})

        existing = {(p.get("page_id"), p["panel_number"]): p
                    for p in memory.get_panels(self.project_name, self.project_id)}
        for i, scene in enumerate(scenes):
            min_id = minutes[min(i, len(minutes) - 1)]["id"] if minutes else memory.add_minute(
                self.project_name, self.project_id, ep_id, i + 1, scene.get("title", ""))
            panel_meta = {
                "scene_id": scene.get("id"),
                "image_prompt": scene.get("image_prompt"),
                "negative_prompt": scene.get("negative_prompt", ""),
                "location_ref": scene.get("location", ""),
                "visible_characters": scene.get("characters", []),
                "duration_seconds": scene.get("duration_seconds", 12),
                "emotional_shift": scene.get("emotional_shift", ""),
                "kind": "scene",
            }
            key = (page_id, i + 1)
            if key in existing:
                panel_id = existing[key]["id"]
                memory.update_panel(self.project_name, self.project_id, panel_id,
                                    scene.get("title", ""), panel_meta, page_id=page_id)
            else:
                panel_id = memory.add_panel(
                    self.project_name, self.project_id, min_id, i + 1,
                    scene.get("title", ""), scene.get("image_prompt", ""),
                    metadata=panel_meta, page_id=page_id)

            memory.clear_dialogue_lines(self.project_name, self.project_id, panel_id)
            for beat in scene.get("narration_script", []):
                memory.add_dialogue_line(
                    self.project_name, self.project_id, panel_id,
                    beat.get("speaker", "Narrator"), beat.get("line", ""),
                    metadata={"emotion": beat.get("emotion", "neutral"),
                              "delivery": beat.get("delivery", ""),
                              "duration_seconds": beat.get("duration_seconds", 3)})
            scene["panel_id"] = panel_id

    def run_scene_continuity(self):
        """Stage 7 (cinematic): audit the SCENE spine for continuity + payoff landing (§9.2b).

        Verifies every planted setup is actually echoed in its payoff scene, flags off-roster
        speakers, thin scenes, and an early climax. Persists warnings (with a repair target so the
        UI can route each into scene regeneration) and returns them."""
        self.state = "scene_continuity"
        bible = memory.get_bible(self.project_name, self.project_id)
        scenes = bible.get("scenes") or []
        blueprint = bible.get("scene_blueprint") or {}
        understanding = bible.get("story_understanding") or {}
        voice_guide = memory.get_user_preferences(self.project_name, self.project_id).get("voice_guide") or {}
        self._log_step("scene_continuity", "start", f"Auditing {len(scenes)} scenes for continuity...")

        warnings = studio_continuity.audit_scenes(scenes, blueprint, voice_guide, understanding)

        # Persist as continuity warnings (target_id maps to the scene's panel where available).
        panel_by_scene = {}
        for p in memory.get_panels(self.project_name, self.project_id):
            sid = (p.get("metadata") or {}).get("scene_id")
            if sid:
                panel_by_scene[sid] = p["id"]
        for w in warnings:
            try:
                memory.add_continuity_warning(
                    self.project_name, self.project_id, "panel",
                    panel_by_scene.get(w.get("scene_id"), 0) or 0,
                    w.get("severity", "low"), w.get("message", ""),
                    metadata={"scene_id": w.get("scene_id"), "suggestion": w.get("suggestion", ""),
                              "repair_target": w.get("repair_target", "all"), "kind": "scene_continuity"})
            except Exception:
                pass
        try:
            studio_blackboard.put_artifact(self.project_name, self.project_id, "scene_continuity",
                                           warnings, produced_by="continuity")
        except Exception:
            pass
        high = sum(1 for w in warnings if w.get("severity") == "high")
        self._log_step("scene_continuity", "complete",
                       f"{len(warnings)} continuity notes ({high} high — unpaid setups).",
                       {"warnings": warnings})
        return warnings

    def run_scene_audio(self, force=False):
        """Stage 8 (cinematic): render each narration beat to local audio (gpt §4).

        Uses the local Kokoro/TTS path when available; with none, every beat is marked
        ``unavailable`` and the player falls back to browser speech — nothing is faked. Stamps
        ``audio_path`` onto beats and persists the updated scenes. Voices each speaker via the
        per-character voice profile when one exists."""
        self.state = "voicing"
        bible = memory.get_bible(self.project_name, self.project_id)
        scenes = bible.get("scenes") or []
        if not scenes:
            return {"ok": False, "error": "No scenes to voice. Run scenes first."}

        # Map each speaker -> a voice id from their bible voice_profile when present.
        by_name = {}
        for ch in memory.get_characters(self.project_name, self.project_id):
            vid = ((ch.get("metadata") or {}).get("voice_profile") or {}).get("voice") \
                if isinstance(ch.get("metadata"), dict) else None
            if ch.get("name"):
                by_name[str(ch["name"]).lower()] = vid
        def voice_for(speaker):
            return by_name.get(str(speaker or "").lower())

        self._log_step("voicing", "start", f"Voicing {len(scenes)} scenes...")
        synth = studio_audio.kokoro_synth(self.project_name)  # None -> unavailable, graceful
        scenes, status = studio_audio.synthesize_scenes(
            self.project_name, self.project_id, scenes, synth=synth, voice_for=voice_for,
            force=force, progress=lambda m: self._progress("voicing", m))
        try:
            bible = memory.get_bible(self.project_name, self.project_id)
            bible["scenes"] = scenes
            memory.save_bible(self.project_name, self.project_id, bible)
            studio_blackboard.put_artifact(self.project_name, self.project_id, "scenes", scenes,
                                           produced_by="sound")
        except Exception as e:
            logger.warning(f"Could not persist voiced scenes: {e}")
        self._log_step("voicing", "complete",
                       f"Voiced {status['done']}/{status['total']} beats "
                       f"({'TTS available' if status['synth_available'] else 'no TTS — browser fallback'}).",
                       status)
        return {"ok": True, "scenes": scenes, **status}

    def run_render_images(self, force=False):
        """Stage 6 (cinematic): render an image for each scene from its prompt (gpt §3).

        Uses the configured image renderer (``studio_render.set_renderer``) if one exists; with
        none configured every scene is marked ``unavailable`` and the player keeps its gradient —
        nothing is faked. Updates the scenes artifact with ``image_path``/``image_status``.
        Returns the render status rollup.
        """
        self.state = "rendering"
        bible = memory.get_bible(self.project_name, self.project_id)
        scenes = bible.get("scenes") or []
        if not scenes:
            return {"ok": False, "error": "No scenes to render. Run scenes first."}
        # Visual Prompt Compiler: turn each scene + the world/character bibles into a reproducible
        # PromptPacket (positive/negative + model/steps/cfg/seed) attached as scene['prompt_packet'].
        world_data = bible.get("world") or {}
        characters = memory.get_characters(self.project_name, self.project_id)
        prefs = memory.get_user_preferences(self.project_name, self.project_id)
        model_profile = prefs.get("image_model_profile") or {}
        studio_prompt_compiler.compile_for_scenes(scenes, world_data, characters, model_profile)

        # Self-install the in-process image backend if one is configured + available (diffusers +
        # CUDA + a model). If not, this is a no-op and the gradient fallback stands — never faked.
        if not studio_render.has_renderer():
            try:
                fn = studio_image_backend.make_image_backend(prefs.get("image_settings") or {})
                if fn:
                    studio_render.set_renderer(fn)
            except Exception as e:
                logger.warning(f"Image backend install skipped: {e}")
        self._log_step("rendering", "start", f"Rendering {len(scenes)} scene images...")
        scenes, queue = studio_render.render_scenes(
            self.project_name, self.project_id, scenes, force=force,
            progress=lambda m: self._progress("rendering", m))
        try:
            bible = memory.get_bible(self.project_name, self.project_id)
            bible["scenes"] = scenes
            memory.save_bible(self.project_name, self.project_id, bible)
            studio_blackboard.put_artifact(self.project_name, self.project_id, "scenes", scenes,
                                           produced_by="renderer")
        except Exception as e:
            logger.warning(f"Could not persist rendered scenes: {e}")
        status = studio_render.render_status(self.project_name, self.project_id)
        done = status["counts"].get("done", 0)
        self._log_step("rendering", "complete",
                       f"Rendered {done}/{len(scenes)} scene images "
                       f"(renderer {'available' if status['renderer_available'] else 'not configured'}).",
                       status)
        return {"ok": True, "scenes": scenes, **status}

    def regenerate_scene(self, scene_id, target="all", feedback=""):
        """Per-scene reject/refine: rewrite one scene's script and/or image, leaving the
        rest of the reel intact. ``target`` is 'script', 'image', or 'all'."""
        state = self._context_state()
        scenes = state["bible"].get("scenes") or []
        blueprint = state["bible"].get("scene_blueprint") or {}
        bp_by_id = {s.get("id"): s for s in blueprint.get("scenes", [])}
        idx = next((i for i, s in enumerate(scenes) if s.get("id") == scene_id), None)
        if idx is None:
            return {"ok": False, "error": f"Unknown scene '{scene_id}'."}

        # Learn the user's taste from this steer (§9.4): a worded refine is the richest signal;
        # a bare regenerate reads as a reject of the current take.
        studio_taste.record_signal(
            self.project_name, self.project_id,
            kind="refine" if feedback else "reject", note=feedback, scene_id=scene_id)

        understanding = self._understanding() or state["bible"].get("story_understanding") or {}
        characters = state["characters"]
        world_data = state["world"]
        by_name = studio_visual.index_characters(characters)
        # Keep payoff-landing (§9.2b) and cross-scene voice (§9.2d) intact on a single-scene rewrite.
        setups = {s.get("id"): s for s in (blueprint.get("setups") or []) if s.get("id")}
        voice_guide = studio_scriptwriter.build_voice_guide(characters, understanding)
        bp_scene = dict(bp_by_id.get(scene_id) or {})
        if feedback:
            bp_scene["purpose"] = f"{bp_scene.get('purpose', '')}\nUser direction: {feedback}".strip()

        fresh = studio_scriptwriter.write_scene(
            bp_scene, idx, understanding, world_data, characters, by_name,
            llm_call=self._call_llm_with_fallback, profile=self.profile,
            setups=setups, voice_guide=voice_guide)

        old = scenes[idx]
        if target in ("script", "all"):
            old["narration_script"] = fresh["narration_script"]
            old["duration_seconds"] = fresh["duration_seconds"]
        if target in ("image", "all"):
            old["image_prompt"] = fresh["image_prompt"]
            old["negative_prompt"] = fresh["negative_prompt"]
        old["status"] = "draft"
        scenes[idx] = old

        current_bible = memory.get_bible(self.project_name, self.project_id)
        current_bible["scenes"] = scenes
        memory.save_bible(self.project_name, self.project_id, current_bible)
        try:
            studio_blackboard.put_artifact(self.project_name, self.project_id, "scenes", scenes,
                                           produced_by="scriptwriter")
        except Exception:
            pass
        self._persist_scenes_as_panels(scenes, None, blueprint)
        self._log_step("scriptwriting", "complete", f"Regenerated scene {scene_id} ({target}).", old)
        return {"ok": True, "scene": old}

    def _is_valid_story_plan(self, value):
        if not isinstance(value, dict):
            return False
        if not isinstance(value.get("summary"), str) or not value.get("summary").strip():
            return False
        episodes = value.get("episodes")
        canon_events = value.get("canon_events")
        if not isinstance(episodes, list) or not episodes:
            return False
        if not isinstance(canon_events, list) or not canon_events:
            return False
        for beat in episodes:
            if not isinstance(beat, dict) or not str(beat.get("name") or "").strip() or not str(beat.get("summary") or "").strip():
                return False
        for event in canon_events:
            if not isinstance(event, dict) or not str(event.get("description") or "").strip():
                return False
        return True

    # Camera language cycled across panels so a 12-panel reel reads cinematically
    # instead of 12 identical medium shots.
    _CAMERA_CYCLE = [
        ("establishing wide shot", "full scene, characters small in frame, environment dominant"),
        ("medium shot", "waist-up framing, balanced composition"),
        ("close-up", "face fills frame, shallow depth of field, emotional focus"),
        ("over-the-shoulder", "foreground shoulder, subject facing camera"),
        ("low angle", "camera tilted up, subject looms, dramatic power"),
        ("dutch angle", "tilted horizon, unease and tension"),
    ]

    def _distribute_dialogue(self, source_story, n):
        """Distribute up to n real quoted lines from the source across the reel, in order.

        Reserves roughly half the slots for the named cast (not just the narrator) and fills
        the rest with narration, then restores document order so the reel reads in sequence.
        Returns a list of {speaker, text} (possibly shorter than n).
        """
        analysis = self._analysis(source_story) or {}
        dialogue = [d for d in (analysis.get("dialogue") or []) if d.get("text")]
        if not dialogue:
            return []
        named_idx = [i for i, d in enumerate(dialogue) if (d.get("speaker") or "Narrator") != "Narrator"]
        narr_idx = [i for i, d in enumerate(dialogue) if (d.get("speaker") or "Narrator") == "Narrator"]

        def _even(indices, k):
            if not indices or k <= 0:
                return []
            step = max(1, len(indices) / k)
            return [indices[min(len(indices) - 1, int(j * step))] for j in range(k)]

        chosen = set(_even(named_idx, min(len(named_idx), n // 2)))
        chosen |= set(_even(narr_idx, n - len(chosen)))
        for i in range(len(dialogue)):
            if len(chosen) >= n:
                break
            chosen.add(i)
        return [{"speaker": dialogue[i].get("speaker") or "Narrator", "text": dialogue[i]["text"]}
                for i in sorted(chosen)][:n]

    def run_shot_list(self, premise_data, world_data, characters, story_plan, mode=None, source_story=None):
        """Stage 5a: Shot List (Shot Designer agent).

        For each story beat, ask the model for a few concrete SHOTS — what is on screen, who
        is in it, the camera, and the continuity state — batched one beat at a time so a small
        model never has to invent a whole reel in one breath. Returns a flat, ordered list of
        shot dicts tagged with their beat. The deterministic fallback grounds shots in the
        beat summary (and, for adaptations, the manuscript) without ever truncating mid-word.
        """
        mode = self._normalize_mode(mode) if mode is not None else self.mode
        source_story = source_story if source_story is not None else self.source_story
        beats = (story_plan or {}).get("episodes") or []
        if not beats:
            beats = [{"name": "Scene", "summary": premise_data.get("premise", "")}]
        cast_names = [c.get("name") for c in characters if c.get("name")]
        locations = [loc.get("name") for loc in world_data.get("locations", []) if loc.get("name")]
        # Enough shots to fill a 12-panel reel without padding-duplication: the tier's
        # shots_per_beat is a floor, but we raise it so beats * shots covers all 12 panels.
        shots_per_beat = max(self.profile["shots_per_beat"], -(-12 // max(1, len(beats))))

        system_prompt = (
            "You are the Shot Designer. Turn ONE story beat into concrete comic shots. "
            f"Use ONLY these characters when present: {cast_names or ['the lead']}. "
            f"Prefer these locations: {locations or ['the main location']}. "
            "Each shot is a single moment a reader could draw. Output ONLY a JSON list of "
            f"{shots_per_beat} shots: "
            '[{"subject": "what the shot is OF", "action": "what is happening", '
            '"location_ref": "place name", "characters_present": ["Name"], '
            '"camera": "shot type", "composition": "framing", '
            '"continuity_state": {"outfit": "", "props": "", "injury": "", "lighting": "", "mood": ""}}]'
        )

        def make_beat_shots(beat, beat_index):
            self._progress("panels", f"Designing shots for beat {beat_index + 1} of {len(beats)}: {beat.get('name', 'Scene')}")
            prompt = (
                f"Beat {beat_index + 1}: {beat.get('name', 'Scene')} — {beat.get('summary', '')}\n"
                f"World tone: {json.dumps({k: world_data.get(k) for k in ('palette', 'lighting', 'tone_rules')})}"
            )

            def fallback():
                summary = studio_generation.sentence_safe_trim(beat.get("summary", "") or premise_data.get("premise", ""), 200)
                loc = locations[beat_index % len(locations)] if locations else "the main location"
                # Vary the angle of approach per shot so the beat doesn't read as one frozen frame.
                angles = ["establishing the moment", "the key action", "the reaction"]
                out = []
                for s in range(shots_per_beat):
                    who = cast_names[s % len(cast_names)] if cast_names else "the lead"
                    out.append({
                        "subject": f"{who} — {angles[s % len(angles)]}",
                        "action": summary,
                        "location_ref": loc,
                        "characters_present": [who] if cast_names else [],
                        "camera": self._CAMERA_CYCLE[s % len(self._CAMERA_CYCLE)][0],
                        "composition": self._CAMERA_CYCLE[s % len(self._CAMERA_CYCLE)][1],
                        "continuity_state": {"outfit": "", "props": "", "injury": "",
                                             "lighting": world_data.get("lighting", ""),
                                             "mood": beat.get("name", "")},
                    })
                return out

            shots = self._generate_structured(
                prompt, system_prompt, fallback,
                item_keys=["subject", "action"], shape="medium",
            )
            for shot in shots:
                shot["beat"] = beat.get("name", "Scene")
                shot["beat_index"] = beat_index
            return shots

        # Batch the beats per the model tier; each beat still yields its own focused call.
        indexed = list(enumerate(beats))
        return self._batched(
            indexed,
            lambda batch: [s for (idx, beat) in batch for s in make_beat_shots(beat, idx)],
            self.profile["beats_per_call"],
        )

    def assemble_panels(self, shots, world_data, characters, premise_data, story_plan, source_story=None, mode=None):
        """Stage 5b: deterministic panel assembly (system, not LLM).

        Turns the shot list into exactly 12 ordered panels: evenly samples/pads shots to 12,
        cycles camera language only where a shot didn't specify it, carries continuity state
        forward, and distributes real source dialogue (for adaptations) or beat narration.
        Image/negative prompts are filled by the Visual Prompt agent in a later step; here we
        seed a basic prompt so the panel is never empty. No mid-word truncation anywhere.
        """
        mode = self._normalize_mode(mode) if mode is not None else self.mode
        source_story = source_story if source_story is not None else self.source_story
        target = 12
        shots = list(shots or [])
        cast_names = [c.get("name") for c in characters if c.get("name")]

        # Even selection to exactly `target` panels (sample down or pad up by cycling).
        if shots:
            if len(shots) >= target:
                step = len(shots) / target
                chosen = [shots[min(len(shots) - 1, int(i * step))] for i in range(target)]
            else:
                chosen = [shots[i % len(shots)] for i in range(target)]
        else:
            chosen = [{"subject": "Scene", "action": premise_data.get("premise", ""),
                       "beat": "Scene"} for _ in range(target)]

        dialogue = self._distribute_dialogue(source_story, target) if (
            source_story and mode in (MODE_ADAPT, MODE_CONTINUE)) else []
        palette = world_data.get("palette") or world_data.get("aesthetic", "comic style")

        panels = []
        for i, shot in enumerate(chosen):
            cam_name = shot.get("camera") or self._CAMERA_CYCLE[i % len(self._CAMERA_CYCLE)][0]
            cam_comp = shot.get("composition") or self._CAMERA_CYCLE[i % len(self._CAMERA_CYCLE)][1]
            subject = studio_generation.sentence_safe_trim(
                f"{shot.get('subject', '')}: {shot.get('action', '')}".strip(" :"), 220)
            present = shot.get("characters_present") or cast_names[:1]
            if dialogue:
                line = dialogue[i] if i < len(dialogue) else {"speaker": "Narrator", "text": ""}
                speaker, text = line["speaker"], line["text"]
            else:
                speaker, text = "Narrator", studio_generation.sentence_safe_trim(shot.get("action", ""), 160)
            # A panel must never carry empty narration: an empty distributed slot or an
            # actionless shot would otherwise crash add_dialogue_line ("text is required").
            if not str(text or "").strip():
                speaker = speaker or "Narrator"
                text = subject or studio_generation.sentence_safe_trim(
                    shot.get("subject", "") or premise_data.get("premise", "") or "The scene continues.", 160)
            style_prompt = f"{palette}, {cam_comp}, cinematic comic panel"
            panels.append({
                "panel_number": i + 1,
                "visual_description": subject or "Scene",
                "style_prompt": style_prompt,
                # Placeholder image/negative prompts; the Visual Prompt agent overwrites these.
                "image_prompt": f"{subject}. {style_prompt}".strip(". "),
                "negative_prompt": "",
                "speaker": speaker,
                "text": text,
                "camera": cam_name,
                "composition": cam_comp,
                "visible_characters": present,
                "duration_seconds": 5,
                "beat": shot.get("beat", "Scene"),
                "location_ref": shot.get("location_ref", ""),
                "continuity_state": shot.get("continuity_state", {}),
            })
        return panels

    def _apply_visual_prompts(self, panels, world_data, characters):
        """Visual Prompt agent: assemble each panel's image_prompt + negative_prompt from the
        structured world + character bibles (deterministic; see studio_visual)."""
        state = self._context_state()
        world_data = state["world"] or world_data
        characters = state["characters"] or characters
        visual_guide = state["visual_guide"] if isinstance(state.get("visual_guide"), dict) else {}
        by_name = studio_visual.index_characters(characters)
        for p in panels:
            if visual_guide:
                continuity = p.get("continuity_state") if isinstance(p.get("continuity_state"), dict) else {}
                persistent = visual_guide.get("persistent") if isinstance(visual_guide.get("persistent"), dict) else {}
                continuity.update({k: v for k, v in persistent.items() if v and not continuity.get(k)})
                p["continuity_state"] = continuity
            image_prompt, negative_prompt = studio_visual.build_image_prompt(p, world_data, by_name)
            p["image_prompt"] = image_prompt
            p["negative_prompt"] = negative_prompt
            panel_note = {
                "panel_number": p.get("panel_number"),
                "beat": p.get("beat"),
                "location_ref": p.get("location_ref"),
                "visible_characters": p.get("visible_characters", []),
                "continuity_state": p.get("continuity_state", {}),
            }
            visual_guide.setdefault("panels", []).append(panel_note)
            visual_guide["persistent"] = {
                "lighting": (p.get("continuity_state") or {}).get("lighting") or world_data.get("lighting", ""),
                "palette": world_data.get("palette") or world_data.get("aesthetic", ""),
            }
            visual_guide["last_panel"] = panel_note
        memory.set_user_preference(self.project_name, self.project_id, "visual_consistency_guide", visual_guide)
        return panels

    @staticmethod
    def _estimate_line_duration(text):
        """Rough spoken duration from word count (~2.5 words/sec), floored at 2s."""
        words = len((text or "").split())
        return max(2, min(8, round(words / 2.5)))

    def _apply_dialogue(self, panels, world_data, characters, story_plan, mode, source_story):
        """Dialogue agent: rewrite each panel's line in the speaker's voice and attach emotion,
        delivery, and duration. Batched per the model tier; on medium/large a second punch-up
        pass tightens the lines. Falls back to the assembly-assigned line when the LLM is off."""
        state = self._context_state()
        world_data = state["world"] or world_data
        characters = state["characters"] or characters
        storyboard = state["storyboard"] or story_plan
        by_name = {}
        for ch in characters:
            if isinstance(ch, dict) and ch.get("name"):
                by_name[str(ch["name"]).lower()] = ch

        def voice_batch(batch):
            briefs = []
            for p in batch:
                speaker = p.get("speaker", "Narrator")
                ch = by_name.get(str(speaker).lower())
                style = (ch or {}).get("speech_style") or (
                    "Spare, atmospheric narration." if speaker == "Narrator" else "Natural, in-character.")
                briefs.append({
                    "panel_number": p["panel_number"],
                    "speaker": speaker,
                    "on_screen": studio_generation.sentence_safe_trim(p.get("visual_description", ""), 120),
                    "beat": p.get("beat", ""),
                    "draft": studio_generation.sentence_safe_trim(p.get("text", ""), 160),
                    "voice": style,
                    "world_context": studio_generation.sentence_safe_trim(world_data.get("setting", ""), 140),
                })
            system_prompt = (
                "You are the Dialogue & Performance writer. Rewrite each panel's single line so it "
                "sounds like the named speaker, fits the current beat and what is on screen, and stays "
                "strictly consistent with the refreshed character/world/storyboard memory. Prioritize "
                "scene consistency over creative flair. Narrator lines are spare and atmospheric. Keep "
                "each line short (a comic balloon). Output ONLY a JSON list, one object per panel: "
                '[{"panel_number": N, "speaker": "...", "line": "...", "emotion": "one word", '
                '"delivery_note": "short performance note"}]'
            )
            prompt = (
                "Storyboard memory:\n" + json.dumps(storyboard) +
                "\n\nPanels to voice:\n" + json.dumps(briefs)
            )
            nums = [b["panel_number"] for b in briefs]
            self._progress("panels", f"Writing dialogue for panel(s) {min(nums)}–{max(nums)} of {len(panels)}")

            def fallback():
                return [{
                    "panel_number": b["panel_number"], "speaker": b["speaker"],
                    "line": b["draft"], "emotion": "neutral", "delivery_note": "",
                } for b in briefs]

            lines = self._generate_structured(
                prompt, system_prompt, fallback,
                item_keys=["panel_number", "line"], shape="medium",
            )
            return lines

        voiced = self._batched(panels, voice_batch, self.profile["panels_per_call"])
        by_num = {int(v["panel_number"]): v for v in voiced if isinstance(v, dict) and "panel_number" in v}

        for p in panels:
            v = by_num.get(int(p["panel_number"]))
            if v:
                if v.get("speaker"):
                    p["speaker"] = v["speaker"]
                p["text"] = v.get("line") or p.get("text", "")
                p["emotion"] = v.get("emotion", "neutral")
                p["delivery_note"] = v.get("delivery_note", "")
            p["duration_seconds"] = self._estimate_line_duration(p.get("text", ""))
        return panels

    def run_dialogue_and_panels(self, premise_data, world_data, characters, story_plan, ep_id, mode=None, source_story=None):
        """Stage 5 & 6: Shot list -> deterministic 12-panel assembly -> persist.

        The visuals come from per-beat shots (run_shot_list) assembled deterministically
        (assemble_panels); image prompts and dialogue are then enriched by the Visual Prompt
        and Dialogue agents. This replaces the old single 12-panel LLM blob that overloaded
        small models and collapsed to a hardcoded steampunk mock.
        """
        mode = self._normalize_mode(mode) if mode is not None else self.mode
        source_story = source_story if source_story is not None else self.source_story
        self.state = "panel_planning"
        self._log_step("panel_planning", "start", "Building shot list and assembling 12 panels...")
        state = self._context_state()
        world_data = state["world"] or world_data
        characters = state["characters"] or characters
        story_plan = state["storyboard"] or story_plan

        shots = self.run_shot_list(premise_data, world_data, characters, story_plan, mode, source_story)
        panels_list = self.assemble_panels(
            shots, world_data, characters, premise_data, story_plan, source_story=source_story, mode=mode,
        )
        # Enrich image prompts (Visual Prompt agent) and dialogue (Dialogue agent).
        panels_list = self._apply_visual_prompts(panels_list, world_data, characters)
        panels_list = self._apply_dialogue(panels_list, world_data, characters, story_plan, mode, source_story)

        # Use only the minutes created for this episode. Older project runs may already
        # have panel 1/2/3... on earlier minutes, so using all project minutes can
        # collide when a user reruns production on the same project.
        minutes = [
            minute for minute in memory.get_minutes(self.project_name, self.project_id)
            if minute.get("episode_id") == ep_id
        ]
        if not minutes:
            # Create a fallback minute
            min_id = memory.add_minute(self.project_name, self.project_id, ep_id, 1, "Vault Infiltration Scene")
            minutes = [minute for minute in memory.get_minutes(self.project_name, self.project_id) if minute.get("id") == min_id]
        else:
            # Map panels across minutes (4 panels per minute beat)
            min_id = minutes[0]["id"]

        page_id = memory.ensure_page(
            self.project_name,
            self.project_id,
            ep_id,
            1,
            title="Page 1",
            summary=story_plan.get("summary", "Opening storyboard page") if isinstance(story_plan, dict) else "Opening storyboard page",
            metadata={"source": "panel_planning", "panel_target": len(panels_list)},
        )
        saved_panels = []
        existing_panels = {
            (panel.get("page_id"), panel["panel_number"]): panel
            for panel in memory.get_panels(self.project_name, self.project_id)
        }
        for p in panels_list:
            p_num = p["panel_number"]
            # Map minutes: 1-4 -> min 0, 5-8 -> min 1, 9-12 -> min 2
            m_idx = min(len(minutes) - 1, (p_num - 1) // 4) if minutes else 0
            curr_min_id = minutes[m_idx]["id"] if minutes else min_id

            # Rich panel planning fields (camera, composition, prompts, timing) ride in
            # metadata so the storyboard is production-ready per the Comic Panel System spec.
            panel_meta = {
                "style_prompt": p.get("style_prompt"),
                "negative_prompt": p.get("negative_prompt", ""),
                "camera": p.get("camera"),
                "composition": p.get("composition"),
                "visible_characters": p.get("visible_characters", []),
                "duration_seconds": p.get("duration_seconds", 5),
                "beat": p.get("beat"),
                "location_ref": p.get("location_ref", ""),
                "continuity_state": p.get("continuity_state", {}),
                # The Visual Prompt agent's structured prompt (set by _apply_visual_prompts);
                # fall back to a simple concat only if it is somehow missing.
                "image_prompt": p.get("image_prompt") or f"{p.get('visual_description', '')}. {p.get('style_prompt', '')}".strip(),
            }

            existing = existing_panels.get((page_id, p_num))
            if existing:
                panel_id = existing["id"]
                memory.update_panel(self.project_name, self.project_id, panel_id, p["visual_description"], panel_meta, page_id=page_id)
            else:
                panel_id = memory.add_panel(
                    self.project_name,
                    self.project_id,
                    curr_min_id,
                    p_num,
                    p["visual_description"],
                    p["style_prompt"],
                    metadata=panel_meta,
                    page_id=page_id,
                )

            memory.clear_dialogue_lines(self.project_name, self.project_id, panel_id)
            memory.add_dialogue_line(
                self.project_name,
                self.project_id,
                panel_id,
                p["speaker"],
                p["text"],
                metadata={
                    "duration_seconds": p.get("duration_seconds", 5),
                    "emotion": p.get("emotion", "neutral"),
                    "delivery_note": p.get("delivery_note", ""),
                },
            )
            p["id"] = panel_id
            saved_panels.append(p)

        self._log_step("panel_planning", "complete", f"Generated and saved {len(saved_panels)} panels & scripts.", {"panels": saved_panels})
        return saved_panels

    def run_continuity_audit(self, premise, world, characters, panels, mode=None, source_story=None):
        """Stage 7: Approval Ready & Continuity Verification"""
        mode = self._normalize_mode(mode) if mode is not None else self.mode
        source_story = source_story if source_story is not None else self.source_story
        self.state = "approval_ready"
        self._log_step("approval_ready", "start", "Running continuity and safety audit on storyboards...")

        canon_clause = ""
        canon = ""
        if source_story and mode in (MODE_ADAPT, MODE_CONTINUE):
            canon_clause = (
                "Also flag any panel that contradicts the canon story (wrong names, events, or established facts). "
            )
            canon = self._canon_block(source_story, label="CANON STORY")
        system_prompt = (
            "You are a continuity editor. Review the characters, world setting, and storyboard panels. "
            "Identify any inconsistencies (e.g. hair colors, tool descriptions, locations, rule breaches). "
            + canon_clause +
            "Output MUST be a single valid JSON list of warning objects: "
            '[{"target_type": "character|panel", "target_id": 1, "severity": "low|medium|high", "message": "inconsistency detail"}]'
        )
        prompt = (
            f"Premise: {json.dumps(premise)}\nWorld: {json.dumps(world)}\n"
            f"Characters: {json.dumps(characters)}\nPanels: {json.dumps(panels)}{canon}"
        )

        def fallback():
            # Standard structural continuity warning example
            char_id = characters[0]["id"] if characters else 1
            panel_id = panels[1]["id"] if len(panels) > 1 else 1
            if source_story and mode in (MODE_ADAPT, MODE_CONTINUE):
                lead = characters[0]["name"] if characters else "the protagonist"
                return [
                    {
                        "target_type": "character",
                        "target_id": char_id,
                        "severity": "low",
                        "message": f"Verify {lead}'s depiction matches the details established in the source story."
                    }
                ]
            return [
                {
                    "target_type": "character",
                    "target_id": char_id,
                    "severity": "medium",
                    "message": "Silas Vance is described as holding a pocket watch key, but vault lockpick methods use a traditional wrench in Panel 11."
                },
                {
                    "target_type": "panel",
                    "target_id": panel_id,
                    "severity": "low",
                    "message": "Vivienne has her spectacles in character description, check if they are drawn in Panel 3."
                }
            ]

        warnings_list = self._call_llm_with_fallback(prompt, system_prompt, fallback)

        saved_warnings = []
        for warn in warnings_list:
            warn_id = memory.add_continuity_warning(
                self.project_name,
                self.project_id,
                warn["target_type"],
                warn["target_id"],
                warn["severity"],
                warn["message"]
            )
            warn["id"] = warn_id
            saved_warnings.append(warn)

        self._log_step("approval_ready", "complete", f"Continuity audit complete. Loged {len(saved_warnings)} warnings.", {"warnings": saved_warnings})
        return saved_warnings

    def run_correction_turn(self, item_type, item_id, feedback):
        """Phase 5: Agentic Correction Loop."""
        self._log_step("correction_loop", "start", f"Processing rejection for {item_type} {item_id}.")
        
        if item_type != "panel":
            self._log_step("correction_loop", "error", f"Correction for {item_type} not implemented yet.")
            return False
            
        panels = memory.get_panels(self.project_name, self.project_id)
        target_panel = next((p for p in panels if p["id"] == item_id), None)
        if not target_panel:
            self._log_step("correction_loop", "error", f"Panel {item_id} not found.")
            return False
            
        dialogue = memory.get_dialogue_lines(self.project_name, self.project_id, item_id)
        
        # Build prompt
        system_prompt = (
            "You are the Arcanum Quality Control Agent. The user has REJECTED a generated panel and provided feedback. "
            "Your job is to read the original panel, read the user's feedback, and rewrite the panel to fix the issue.\n"
            "Output MUST be a single valid JSON block: "
            '{"internal_thought": "Analyze the feedback and plan the fix", '
            '"visual_description": "New updated visual description", '
            '"dialogue_lines": [{"speaker": "Name or Narrator", "text": "Line of dialogue"}]}'
        )
        prompt = f"Original Panel JSON:\n{json.dumps(target_panel)}\nOriginal Dialogue:\n{json.dumps(dialogue)}\n\nUser Feedback:\n{feedback}\n\nRewrite the panel now."
        
        def fallback():
            return {
                "internal_thought": "Fallback used for correction.",
                "visual_description": target_panel.get("visual_description", "") + f" [Fixed: {feedback}]",
                "dialogue_lines": dialogue
            }
            
        data = self._call_llm_with_fallback(prompt, system_prompt, fallback)
        if not isinstance(data, dict):
            data = fallback()
            
        # Apply the fix
        new_visual = data.get("visual_description", target_panel.get("visual_description"))
        new_dialogue = data.get("dialogue_lines", dialogue)
        
        # Update memory
        metadata = target_panel.get("metadata") or {}
        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except:
                metadata = {}
        metadata["last_correction"] = feedback
        
        memory.update_panel(self.project_name, self.project_id, item_id, new_visual, metadata)
        memory.clear_dialogue_lines(self.project_name, self.project_id, item_id)
        
        for line in new_dialogue:
            memory.add_dialogue_line(self.project_name, self.project_id, item_id, line.get("speaker", "Narrator"), line.get("text", ""))
            
        self._log_step("correction_loop", "complete", f"Panel {item_id} corrected and saved.")
        return True

    def run_full_pipeline(self, seed_text, mode=MODE_SEED, source_story=None):
        """Orchestrate the entire pipeline end-to-end and return structured JSON output.

        mode:
            "seed"     -> invent a new story from a short prompt (default, original behavior).
            "adapt"    -> storyboard an existing finished story ("start from").
            "continue" -> generate what happens next from an existing story ("continue from").
        source_story: the full text of an existing story (optional; for adapt/continue it may also be
            passed via seed_text).
        """
        try:
            mode, source_story = self._resolve_source(seed_text, mode, source_story)
            self._log_step("pipeline", "start", f"Executing Source Arcanum Studio pipeline (mode={mode})...")

            # The Producer (Headmaster) drives the specialist agents through the shared
            # blackboard: each agent runs once its dependencies are published, and a rejected
            # stage routes to the repair flow. The agents wrap the structured stage methods
            # above, so this keeps the generation logic and adds explicit roles + scheduling.
            import studio_agents
            producer = studio_agents.Producer(self)
            return producer.run(seed_text, mode, source_story)
        except Exception as e:
            logger.exception("Source Arcanum pipeline crashed")
            self._log_step("pipeline", "failed", f"Pipeline aborted due to crash: {e}")
            self.state = "error"
            return {
                "ok": False,
                "error": str(e),
                "model_status": self.model_status,
            }
