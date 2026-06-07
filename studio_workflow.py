import os
import json
import logging
import re
from datetime import datetime, timezone
import studio_capabilities
import studio_memory as memory
import studio_analyzer
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

    def _call_llm_with_fallback(self, prompt, system_prompt, fallback_data_func):
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
                    max_output_tokens=1500
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
            return {"ok": False, "phase": "scene_planning", "error": str(e)}

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
        return {
            "ok": True,
            "phase": "finalization",
            "data": {"scenes": ordered, "edges_added": edges_added, "timeline": timeline},
        }

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
        return {"ok": False, "phase": "director_scene_planning", "scene_spec": raw_spec, "error": result.get("error")}

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
        """Stage 2: World Building. Extracts an existing story's world, or invents one for seeds."""
        mode = self._normalize_mode(mode) if mode is not None else self.mode
        source_story = source_story if source_story is not None else self.source_story
        self.state = "world_building"
        self._log_step("world_building", "start", "Generating world bible...")

        if source_story and mode in (MODE_ADAPT, MODE_CONTINUE):
            verb = "Extract" if mode == MODE_ADAPT else "Extract and preserve"
            system_prompt = (
                f"You are a world-builder architect. {verb} the setting, aesthetic tone, and key world rules that are "
                "actually present in the supplied story. Do NOT contradict or invent elements the story does not support. "
                "Output MUST be a single valid JSON block: "
                '{"setting": "Setting description", "aesthetic": "Visual tone / style description", "rules": ["rule 1", "rule 2"]}'
            )
            prompt = f"Premise: {json.dumps(premise_data)}{self._canon_block(source_story)}"

            def fallback():
                analysis = self._analysis(source_story)
                if analysis:
                    places = analysis["locations"]
                    place_names = ", ".join(p["name"] for p in places[:4])
                    setting = (
                        f"The world established in the supplied story"
                        + (f", centered on {place_names}. " if place_names else ". ")
                        + (places[0]["description"] if places else analysis["summary"])
                    )
                    rules = ["Established canon from the source story is preserved without contradiction."]
                    for p in places[:3]:
                        rules.append(f"{p['name']} is a fixed location from the source and must stay consistent.")
                    return {
                        "setting": setting,
                        "aesthetic": analysis["aesthetic"],
                        "rules": rules,
                    }
                snippet = (source_story or "").strip()
                return {
                    "setting": f"The world as established in the supplied story. {snippet[:160]}",
                    "aesthetic": "Visual tone matched faithfully to the source story's mood.",
                    "rules": ["Established canon from the source story is preserved without contradiction."]
                }
        else:
            system_prompt = (
                "You are a world-builder architect. Generate setting rules, aesthetic tone, and world key facts based on the premise. "
                "Output MUST be a single valid JSON block: "
                '{"setting": "Setting description", "aesthetic": "Visual tone / style description", "rules": ["rule 1", "rule 2"]}'
            )
            prompt = f"Premise: {json.dumps(premise_data)}"

            def fallback():
                return {
                    "setting": "A mysterious steampunk metropolis built atop ancient subterranean arcane ruins.",
                    "aesthetic": "Neo-Gothic Steampunk Noir. Moody lightning, copper piping, and glowing blue magic vapors.",
                    "rules": [
                        "Magic vapor is highly volatile and tightly controlled by the Iron Guild.",
                        "The lower ruins are strictly forbidden to citizens."
                    ]
                }

        data = self._call_llm_with_fallback(prompt, system_prompt, fallback)

        # Merge with current bible memory
        current_bible = memory.get_bible(self.project_name, self.project_id)
        current_bible["world"] = data
        memory.save_bible(self.project_name, self.project_id, current_bible)

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

    def run_character_building(self, premise_data, world_data, mode=None, source_story=None):
        """Stage 3: Character Building. Extracts the cast of an existing story, or invents one for seeds."""
        mode = self._normalize_mode(mode) if mode is not None else self.mode
        source_story = source_story if source_story is not None else self.source_story
        self.state = "character_building"
        self._log_step("character_building", "start", "Generating main characters...")
        casting = memory.get_bible(self.project_name, self.project_id).get("casting") or {}
        casting_prompt = f"\nDirector casting anchor: {json.dumps(casting)}" if casting else ""

        if source_story and mode in (MODE_ADAPT, MODE_CONTINUE):
            system_prompt = (
                "You are a character designer. Identify the principal characters that ACTUALLY appear in the supplied story "
                "(2 to 4 of them). Use their real names and traits from the text — do NOT invent new leads. "
                "If a Director casting anchor is present, preserve the cast member names and roles unless they contradict the source story. "
                "Output MUST be a single valid JSON list of character objects: "
                '[{"name": "Name", "description": "1-sentence desc", "role": "Role in story", "archetype": "Archetype"}]'
            )
            prompt = (
                f"Premise: {json.dumps(premise_data)}\nWorld: {json.dumps(world_data)}"
                f"{casting_prompt}{self._canon_block(source_story)}"
            )

            def fallback():
                analysis = self._analysis(source_story)
                if analysis and analysis["characters"]:
                    cast_skins = casting.get("cast") or []
                    roles = ["lead", "rival", "supporting", "supporting"]
                    archetypes = ["Protagonist", "Antagonist", "Ally", "Ally"]
                    out = []
                    for i, person in enumerate(analysis["characters"][:4]):
                        # Anchor each real character onto an available registry skin so the
                        # Scene/GEST system still has a valid visual id to render against.
                        skin_id = cast_skins[i]["skin_id"] if i < len(cast_skins) else None
                        desc = person.get("description") or person.get("first_sentence") or ""
                        if person.get("sample_line"):
                            desc = f'{desc} Speaks like: "{person["sample_line"][:80]}"'
                        out.append({
                            "name": person["name"],
                            "description": (desc or f"{person['name']}, a key figure in the source story.")[:240],
                            "role": roles[i] if i < len(roles) else "supporting",
                            "archetype": archetypes[i] if i < len(archetypes) else "Supporting",
                            "skin_id": skin_id,
                        })
                    return out
                if casting.get("cast"):
                    return [
                        {
                            "name": member["character_name"],
                            "description": f"{member['skin_name']} anchored from the Director casting pass.",
                            "role": member["role"],
                            "archetype": "Cast Anchor",
                            "skin_id": member["skin_id"],
                        }
                        for member in casting["cast"]
                    ]
                return [
                    {
                        "name": "Protagonist",
                        "description": "The central figure carried over from the supplied story.",
                        "role": "Protagonist",
                        "archetype": "The Hero"
                    },
                    {
                        "name": "Supporting Lead",
                        "description": "A key ally or rival established in the supplied story.",
                        "role": "Deuteragonist",
                        "archetype": "The Companion"
                    }
                ]
        else:
            system_prompt = (
                "You are a character designer. Generate exactly two main characters based on the premise and world setting. "
                "If a Director casting anchor is present, use its character names, roles, and skin anchors. "
                "Output MUST be a single valid JSON list of character objects: "
                '[{"name": "Name", "description": "1-sentence desc", "role": "Role in story", "archetype": "Archetype"}]'
            )
            prompt = f"Premise: {json.dumps(premise_data)}\nWorld: {json.dumps(world_data)}{casting_prompt}"

            def fallback():
                if casting.get("cast"):
                    return [
                        {
                            "name": member["character_name"],
                            "description": f"{member['skin_name']} anchored from the Director casting pass.",
                            "role": member["role"],
                            "archetype": "Cast Anchor",
                            "skin_id": member["skin_id"],
                        }
                        for member in casting["cast"]
                    ]
                return [
                    {
                        "name": "Silas Vance",
                        "description": "A clever, cynical grease-monkey rogue carrying a mechanical mechanical pocket watch key.",
                        "role": "Protagonist / Thief",
                        "archetype": "The Scoundrel"
                    },
                    {
                        "name": "Lady Vivienne",
                        "description": "An aristocratic scholar who secretly studies outlawed technomancy.",
                        "role": "Deuteragonist / Scholar",
                        "archetype": "The Maverick Sage"
                    }
                ]

        char_list = self._call_llm_with_fallback(prompt, system_prompt, fallback)

        # Save each character to database
        saved_chars = []
        for char in char_list:
            char_id = memory.add_character(
                self.project_name,
                self.project_id,
                char["name"],
                char["description"],
                char["role"],
                char["archetype"],
                metadata={
                    "skin_id": char.get("skin_id"),
                    "source": "director_casting" if char.get("skin_id") else "character_building",
                }
            )
            char["id"] = char_id
            saved_chars.append(char)

        self._log_step("character_building", "complete", f"Generated and stored {len(saved_chars)} characters.", {"characters": saved_chars})
        return saved_chars

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

        # Save Episode
        ep_id = memory.add_episode(self.project_name, self.project_id, premise_data.get("title", "Episode 1"), story_data["summary"])

        # Save minutes
        for idx, beat in enumerate(story_data["episodes"]):
            memory.add_minute(self.project_name, self.project_id, ep_id, idx + 1, f"{beat['name']}: {beat['summary']}")

        # Save canon events
        for event in story_data["canon_events"]:
            memory.add_canon_event(self.project_name, self.project_id, event["description"], event["time_index"])

        self._log_step("story_planning", "complete", "Created and stored story plan.", story_data)
        return story_data, ep_id

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

    def _faithful_panels(self, premise_data, world_data, characters, story_plan, source_story):
        """Build a faithful 12-panel reel from the manuscript itself.

        Beats drive the visuals (panels 1-4 -> beat 1, 5-8 -> beat 2, 9-12 -> beat 3),
        and the story's *real quoted dialogue* is distributed in order across the panels,
        attributed to the speakers the analyzer detected. Each panel carries rich planning
        metadata (camera, composition, visible characters, duration, negative prompt) per
        the Comic Panel System spec, so the reel is production-ready, not placeholder text.
        """
        analysis = self._analysis(source_story) or {}
        beats = analysis.get("beats") or story_plan.get("episodes", []) or []
        dialogue = [d for d in (analysis.get("dialogue") or []) if d.get("text")]
        aesthetic = world_data.get("aesthetic", "Comic style")
        char_names = [c.get("name") for c in characters if c.get("name")]
        known_speakers = {n.lower(): n for n in char_names}

        # Select up to 12 real lines that (a) span the whole story chronologically and
        # (b) let the named cast actually speak, not just the first-person narrator.
        # We reserve roughly half the panels for attributed (named) lines and fill the
        # rest with narration, then restore document order so the reel reads in sequence.
        picked = []
        if dialogue:
            named_idx = [i for i, d in enumerate(dialogue) if (d.get("speaker") or "Narrator") != "Narrator"]
            narr_idx = [i for i, d in enumerate(dialogue) if (d.get("speaker") or "Narrator") == "Narrator"]

            def _even(indices, k):
                if not indices or k <= 0:
                    return []
                step = max(1, len(indices) / k)
                return [indices[min(len(indices) - 1, int(j * step))] for j in range(k)]

            want_named = min(len(named_idx), 6)
            chosen = set(_even(named_idx, want_named))
            chosen |= set(_even(narr_idx, 12 - len(chosen)))
            # Top up if rounding left us short.
            for i in range(len(dialogue)):
                if len(chosen) >= 12:
                    break
                chosen.add(i)
            picked = [dialogue[i] for i in sorted(chosen)][:12]

        panels = []
        for i in range(12):
            beat = beats[min(i // 4, len(beats) - 1)] if beats else {"name": "Scene", "summary": premise_data.get("premise", "")}
            cam_name, cam_comp = self._CAMERA_CYCLE[i % len(self._CAMERA_CYCLE)]
            line = picked[i] if i < len(picked) else None
            if line:
                raw_speaker = (line.get("speaker") or "Narrator").strip()
                speaker = known_speakers.get(raw_speaker.lower(), raw_speaker if raw_speaker != "Narrator" else "Narrator")
                text = line["text"]
            else:
                speaker = "Narrator"
                text = beat.get("summary", "")[:160]
            visible = [s for s in [speaker] if s != "Narrator"] or char_names[:1]
            visual = f"{beat.get('name', 'Scene')} — {cam_name}: {beat.get('summary', '')[:120]}"
            panels.append({
                "panel_number": i + 1,
                "visual_description": visual,
                "style_prompt": f"{aesthetic}, {cam_comp}, cinematic comic panel, high detail, cell shaded",
                "negative_prompt": "blurry, deformed hands, extra limbs, watermark, text artifacts, melted faces",
                "speaker": speaker,
                "text": text,
                "camera": cam_name,
                "composition": cam_comp,
                "visible_characters": visible,
                "duration_seconds": 5,
                "beat": beat.get("name", "Scene"),
            })
        return panels

    def run_dialogue_and_panels(self, premise_data, world_data, characters, story_plan, ep_id, mode=None, source_story=None):
        """Stage 5 & 6: Dialogue & Panel Planning (12 Panels & Lines)"""
        mode = self._normalize_mode(mode) if mode is not None else self.mode
        source_story = source_story if source_story is not None else self.source_story
        self.state = "panel_planning"
        self._log_step("panel_planning", "start", "Generating 12 visual panels and dialogue scripts...")

        grounding = ""
        if source_story and mode in (MODE_ADAPT, MODE_CONTINUE):
            voice_note = (
                "Keep every character voice and visual detail consistent with the canon story below. "
                if mode == MODE_CONTINUE else
                "Render the panels and dialogue faithfully from the canon story below. "
            )
            grounding = " " + voice_note
        system_prompt = (
            "You are a comic storyboard artist. Generate exactly 12 panels for a 60-second comic reel. "
            "Each panel must specify a number (1-12), visual description, style prompt, and single dialogue/narration line."
            + grounding +
            "Output MUST be a single valid JSON list of panels: "
            '[{"panel_number": 1, "visual_description": "visual desc", "style_prompt": "prompt style details", '
            '"speaker": "Character Name or Narrator", "text": "spoken dialogue text"}]'
        )
        canon = self._canon_block(source_story, label="CANON STORY") if mode in (MODE_ADAPT, MODE_CONTINUE) else ""
        prompt = (
            f"Premise: {json.dumps(premise_data)}\nWorld: {json.dumps(world_data)}\n"
            f"Characters: {json.dumps(characters)}\nPlan: {json.dumps(story_plan)}{canon}"
        )

        def fallback():
            panels_mock = []
            scenes = [
                ("Silas dodging steam vents in a dark hallway.", "Steam pipes, copper valves, silhouette.", "Narrator", "Midnight in the Iron Guild vaults. Silas Vance steps into the forbidden steam shafts."),
                ("Silas using a pick-tool on a large gear-lock.", "Close-up on gloved fingers, clockwork gears.", "Silas Vance", "Just one more gear, and this lock is history."),
                ("Vivienne holding a glowing lantern, whispering warnings.", "Warm lantern light, brass spectacles.", "Lady Vivienne", "Hurry, Silas! The steam patrols cycle every three minutes."),
                ("The large vault door grinding open.", "Heavy steel hatch opening, steam blasting.", "Narrator", "With a heavy metal groan, the iron seals break."),
                ("Entering a massive chamber filled with ticking machinery.", "Grand vault, colossal pendulum swinging.", "Narrator", "Inside lies the legendary Core Vault, ticking in perfect sync."),
                ("A glowing blue sphere floating on a brass pedestal.", "Vibrant blue light, floating artifact.", "Lady Vivienne", "The Core Engine Key... it is more beautiful than the bibles described."),
                ("Silas reaching out to grab the key.", "Tense reaching hand, electrical sparks.", "Silas Vance", "Let's grab it and get out. I don't like these sparks."),
                ("The pedestal glowing red, red lights flashing.", "Alarms sounding, red emergency lighting.", "Narrator", "But the pedestal detects the weight change. The trap springs."),
                ("Steam sentinels emerging from wall docks.", "Automaton soldiers, glowing brass optics.", "Narrator", "Steam sentinels deploy from the vault walls."),
                ("Vivienne casting a blue energy barrier.", "Technomancy barrier, blue sparks.", "Lady Vivienne", "Silas, get behind me! I'll hold the bulkhead!"),
                ("Silas smashing a copper steam pipe with a wrench.", "Pipe bursting, heavy steam cloud.", "Silas Vance", "Let's see how these iron buckets handle hot pressure!"),
                ("Silas and Vivienne running down a pipe corridor.", "Running away, steam engulfing path.", "Narrator", "They plunge into the exhaust tubes, escaping with the key as the vault seals.")
            ]
            # For adapt/continue, derive faithful panels from the actual manuscript:
            # real beats drive the visuals and real quoted dialogue drives the lines.
            if source_story and mode in (MODE_ADAPT, MODE_CONTINUE):
                return self._faithful_panels(premise_data, world_data, characters, story_plan, source_story)
            for i, scene in enumerate(scenes):
                panels_mock.append({
                    "panel_number": i + 1,
                    "visual_description": scene[0],
                    "style_prompt": f"Steampunk comic, {scene[1]}, high detail, comic style, cell shaded",
                    "speaker": scene[2],
                    "text": scene[3]
                })
            return panels_mock

        panels_list = self._call_llm_with_fallback(prompt, system_prompt, fallback)

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
                "image_prompt": f"{p.get('visual_description', '')}. {p.get('style_prompt', '')}".strip(),
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

            memory.add_dialogue_line(
                self.project_name,
                self.project_id,
                panel_id,
                p["speaker"],
                p["text"],
                metadata={"duration_seconds": p.get("duration_seconds", 5)},
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

            premise = self.run_intake(seed_text, mode=mode, source_story=source_story)
            casting = self.run_director_casting(premise_data=premise)
            world = self.run_world_building(premise, mode=mode, source_story=source_story)
            characters = self.run_character_building(premise, world, mode=mode, source_story=source_story)
            story_plan, ep_id = self.run_story_planning(premise, world, characters, mode=mode, source_story=source_story)
            scene = self.run_director_scene_planning(premise, world, characters, story_plan)
            panels = self.run_dialogue_and_panels(premise, world, characters, story_plan, ep_id, mode=mode, source_story=source_story)
            warnings = self.run_continuity_audit(premise, world, characters, panels, mode=mode, source_story=source_story)

            # Export final result
            final_data = memory.export_project_json(self.project_name, self.project_id)

            self._log_step("pipeline", "complete", "Successfully generated and stored comic reel plan.", {"project_id": self.project_id})
            self.state = "complete"

            return {
                "ok": True,
                "project_id": self.project_id,
                "project_name": self.project_name,
                "mode": mode,
                "casting": casting["data"],
                "scene": scene,
                "data": final_data,
                "model_status": self.model_status,
            }
        except Exception as e:
            logger.exception("Source Arcanum pipeline crashed")
            self._log_step("pipeline", "failed", f"Pipeline aborted due to crash: {e}")
            self.state = "error"
            return {
                "ok": False,
                "error": str(e),
                "model_status": self.model_status,
            }
