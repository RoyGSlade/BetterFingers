import os
import json
import logging
import re
from datetime import datetime, timezone
import studio_memory as memory
from llm_engine import get_engine, get_engine_if_initialized

logger = logging.getLogger("studio_workflow")

class StudioWorkflowRunner:
    def __init__(self, project_name):
        self.project_name = project_name
        self.project_id = memory.init_project_db(project_name)
        self.state = "idle"
        self.steps_log = []

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

    def _call_llm_with_fallback(self, prompt, system_prompt, fallback_data_func):
        """Thin adapter that calls LLMEngine and falls back gracefully to mocks if needed."""
        engine = None
        try:
            # Check if LLMEngine is initialized/active
            engine = get_engine_if_initialized() or get_engine()
        except Exception as e:
            logger.warning(f"Could not initialize LLMEngine: {e}")

        # If engine is initialized, try to ensure it is ready
        engine_ready = False
        if engine:
            try:
                engine_ready = engine.ensure_ready()
            except Exception as e:
                logger.warning(f"LLMEngine ensure_ready failed: {e}")

        if not engine_ready:
            self._log_step("llm_adapter", "warning", "LLM engine sidecar not ready. Using high-quality procedural mock fallback.")
            return fallback_data_func()

        # Try up to 2 times to run and parse JSON
        for attempt in range(2):
            try:
                raw_response = engine.process_custom_prompt(
                    user_text=prompt,
                    system_prompt=system_prompt,
                    max_output_tokens=1500
                )

                if len(raw_response or "") > 32_000:
                    logger.warning(f"LLM response oversized ({len(raw_response)} bytes), using fallback.")
                    return fallback_data_func()

                parsed = self._extract_and_parse_json(raw_response)
                if parsed:
                    return parsed

                logger.warning(f"LLM response failed JSON parsing. Attempt {attempt + 1}. Raw output: {raw_response[:200]}")
            except Exception as e:
                logger.error(f"LLM call failed on attempt {attempt + 1}: {e}")
                
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

    # --- PIPELINE STAGES ---

    def run_intake(self, seed_text):
        """Stage 1: Intake & Premise Generation"""
        self.state = "intake"
        self._log_step("intake", "start", f"Processing story seed: '{seed_text[:40]}...'")

        system_prompt = (
            "You are a story development editor. Parse the story seed and generate a project premise. "
            "Output MUST be a single valid JSON block like: "
            '{"title": "Project Title", "theme": "Core Theme", "premise": "2-sentence premise statement"}'
        )
        prompt = f"Story seed: {seed_text}"

        def fallback():
            # Seed-specific naming
            words = seed_text.split()
            title_part = " ".join(words[:3]).title() if words else "Untitled Adventure"
            return {
                "title": f"Source Arcanum: {title_part}",
                "theme": "Exploration & Consequence",
                "premise": f"Based on seed: '{seed_text}'. A group of adventurers unravel a long-lost secret that threatens to reshape their world."
            }

        data = self._call_llm_with_fallback(prompt, system_prompt, fallback)
        
        # Store in preferences / memory
        memory.save_bible(self.project_name, self.project_id, {"premise": data})
        self._log_step("intake", "complete", "Generated and stored premise.", data)
        return data

    def run_world_building(self, premise_data):
        """Stage 2: World Building"""
        self.state = "world_building"
        self._log_step("world_building", "start", "Generating world bible...")

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

        self._log_step("world_building", "complete", "Generated and stored world bible.", data)
        return data

    def run_character_building(self, premise_data, world_data):
        """Stage 3: Character Building"""
        self.state = "character_building"
        self._log_step("character_building", "start", "Generating main characters...")

        system_prompt = (
            "You are a character designer. Generate exactly two main characters based on the premise and world setting. "
            "Output MUST be a single valid JSON list of character objects: "
            '[{"name": "Name", "description": "1-sentence desc", "role": "Role in story", "archetype": "Archetype"}]'
        )
        prompt = f"Premise: {json.dumps(premise_data)}\nWorld: {json.dumps(world_data)}"

        def fallback():
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
                char["archetype"]
            )
            char["id"] = char_id
            saved_chars.append(char)

        self._log_step("character_building", "complete", f"Generated and stored {len(saved_chars)} characters.", {"characters": saved_chars})
        return saved_chars

    def run_story_planning(self, premise_data, world_data, characters):
        """Stage 4: Story Planning (60-Second Episode Plan)"""
        self.state = "story_planning"
        self._log_step("story_planning", "start", "Creating 60-second episode plan...")

        system_prompt = (
            "You are a storyboard director. Create a structured 60-second story arc divided into three major beats (episodes/scenes) "
            "and three canon events. Output MUST be a single valid JSON block: "
            '{"summary": "Overall episode summary", "episodes": [{"name": "Beat Name", "summary": "Beat summary"}], '
            '"canon_events": [{"description": "Event detail", "time_index": "0:XX"}]}'
        )
        prompt = f"Premise: {json.dumps(premise_data)}\nWorld: {json.dumps(world_data)}\nCharacters: {json.dumps(characters)}"

        def fallback():
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

    def run_dialogue_and_panels(self, premise_data, world_data, characters, story_plan, ep_id):
        """Stage 5 & 6: Dialogue & Panel Planning (12 Panels & Lines)"""
        self.state = "panel_planning"
        self._log_step("panel_planning", "start", "Generating 12 visual panels and dialogue scripts...")

        system_prompt = (
            "You are a comic storyboard artist. Generate exactly 12 panels for a 60-second comic reel. "
            "Each panel must specify a number (1-12), visual description, style prompt, and single dialogue/narration line. "
            "Output MUST be a single valid JSON list of panels: "
            '[{"panel_number": 1, "visual_description": "visual desc", "style_prompt": "prompt style details", '
            '"speaker": "Character Name or Narrator", "text": "spoken dialogue text"}]'
        )
        prompt = (
            f"Premise: {json.dumps(premise_data)}\nWorld: {json.dumps(world_data)}\n"
            f"Characters: {json.dumps(characters)}\nPlan: {json.dumps(story_plan)}"
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
        
        # We need a minute reference to connect panels to
        minutes = memory.get_minutes(self.project_name, self.project_id)
        if not minutes:
            # Create a fallback minute
            min_id = memory.add_minute(self.project_name, self.project_id, ep_id, 1, "Vault Infiltration Scene")
        else:
            # Map panels across minutes (4 panels per minute beat)
            min_id = minutes[0]["id"]
            
        saved_panels = []
        for p in panels_list:
            p_num = p["panel_number"]
            # Map minutes: 1-4 -> min 0, 5-8 -> min 1, 9-12 -> min 2
            m_idx = min(len(minutes) - 1, (p_num - 1) // 4) if minutes else 0
            curr_min_id = minutes[m_idx]["id"] if minutes else min_id

            panel_id = memory.add_panel(
                self.project_name,
                self.project_id,
                curr_min_id,
                p_num,
                p["visual_description"],
                p["style_prompt"]
            )
            
            memory.add_dialogue_line(
                self.project_name,
                self.project_id,
                panel_id,
                p["speaker"],
                p["text"]
            )
            p["id"] = panel_id
            saved_panels.append(p)

        self._log_step("panel_planning", "complete", f"Generated and saved {len(saved_panels)} panels & scripts.", {"panels": saved_panels})
        return saved_panels

    def run_continuity_audit(self, premise, world, characters, panels):
        """Stage 7: Approval Ready & Continuity Verification"""
        self.state = "approval_ready"
        self._log_step("approval_ready", "start", "Running continuity and safety audit on storyboards...")

        system_prompt = (
            "You are a continuity editor. Review the characters, world setting, and storyboard panels. "
            "Identify any inconsistencies (e.g. hair colors, tool descriptions, locations, rule breaches). "
            "Output MUST be a single valid JSON list of warning objects: "
            '[{"target_type": "character|panel", "target_id": 1, "severity": "low|medium|high", "message": "inconsistency detail"}]'
        )
        prompt = (
            f"Premise: {json.dumps(premise)}\nWorld: {json.dumps(world)}\n"
            f"Characters: {json.dumps(characters)}\nPanels: {json.dumps(panels)}"
        )

        def fallback():
            # Standard structural continuity warning example
            char_id = characters[0]["id"] if characters else 1
            panel_id = panels[1]["id"] if len(panels) > 1 else 1
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

    def run_full_pipeline(self, seed_text):
        """Orchestrate the entire pipeline end-to-end and return structured JSON output."""
        try:
            self._log_step("pipeline", "start", "Executing Source Arcanum Studio pipeline...")
            
            premise = self.run_intake(seed_text)
            world = self.run_world_building(premise)
            characters = self.run_character_building(premise, world)
            story_plan, ep_id = self.run_story_planning(premise, world, characters)
            panels = self.run_dialogue_and_panels(premise, world, characters, story_plan, ep_id)
            warnings = self.run_continuity_audit(premise, world, characters, panels)
            
            # Export final result
            final_data = memory.export_project_json(self.project_name, self.project_id)
            
            self._log_step("pipeline", "complete", "Successfully generated and stored comic reel plan.", {"project_id": self.project_id})
            self.state = "complete"
            
            return {
                "ok": True,
                "project_id": self.project_id,
                "project_name": self.project_name,
                "data": final_data
            }
        except Exception as e:
            logger.exception("Source Arcanum pipeline crashed")
            self._log_step("pipeline", "failed", f"Pipeline aborted due to crash: {e}")
            self.state = "error"
            return {
                "ok": False,
                "error": str(e)
            }
