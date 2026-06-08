"""
Specialist agent registry + Producer orchestrator.

This is the "clear roles" layer from docs/visionchecklist.md §6. Each production stage is
declared as a StudioAgent with an explicit contract — what it reads, what artifact it writes,
and which model tier it prefers — instead of being an anonymous method buried in a hardcoded
chain. The Producer (the Headmaster) schedules each agent once its dependencies are present on
the StudioBlackboard, publishes results, logs status posts, and routes a rejected stage to the
repair flow instead of dead-ending.

The agents wrap the now-structured stage methods on StudioWorkflowRunner, so this layer adds the
orchestration/role clarity without re-implementing the (already improved) generation logic.
"""

from dataclasses import dataclass
from typing import Callable, List

import studio_blackboard as bb
import studio_showrunner
import studio_repair


@dataclass
class StudioAgent:
    id: str
    role: str
    reads: List[str]
    writes: str
    run: Callable          # run(runner, ctx) -> (artifact_content, control) ; control is a dict
    model_tier: str = "any"
    description: str = ""


# --- Agent run functions. Each pulls inputs from ctx (in-memory results passed between agents)
# and returns (artifact_to_publish, control). `control` may carry {"reject": <repair payload>}. ---

def _run_intake(runner, ctx):
    premise = runner.run_intake(ctx["seed_text"], mode=ctx["mode"], source_story=ctx["source_story"])
    ctx["premise"] = premise
    return premise, {}


def _run_understanding(runner, ctx):
    """Stage 0 (cinematic): build the whole-story ``story_understanding`` every later stage grounds on.

    Loremaster *reads* a supplied manuscript (adapt/continue); Genesis *invents* one from the
    premise/seed (the "make a story from nothing" path). Both emit the same rich contract, so the
    Showrunner/Scriptwriter stay agnostic to whether the story was read or invented.
    """
    if ctx.get("source_story"):
        understanding = runner.run_loremaster(ctx["source_story"])
    else:
        understanding = runner.run_genesis(ctx["premise"], seed_text=ctx.get("seed_text", ""))
    ctx["understanding"] = understanding or {}
    return ctx["understanding"], {}


def _run_world(runner, ctx):
    world = runner.run_world_building(ctx["premise"], mode=ctx["mode"], source_story=ctx["source_story"])
    ctx["world"] = world
    return world, {}


def _run_characters(runner, ctx):
    chars = runner.run_character_building(ctx["premise"], ctx["world"], mode=ctx["mode"], source_story=ctx["source_story"])
    ctx["characters"] = chars
    return chars, {}


def _run_showrunner(runner, ctx):
    """Stage 4 (cinematic): dynamic scene blueprint with explicit setup→payoff (replaces the
    legacy hardcoded 3-beat planner)."""
    storyboard, ep_id, blueprint = runner.run_showrunner(
        premise_data=ctx["premise"], world_data=ctx["world"], characters=ctx["characters"],
        mode=ctx["mode"], source_story=ctx["source_story"])
    ctx["storyboard"] = storyboard
    ctx["ep_id"] = ep_id
    ctx["blueprint"] = blueprint
    return blueprint, {}


def _run_gate(runner, ctx):
    """Stage 4b (cinematic): the setup/payoff gate. Verify the blueprint is structurally sound
    BEFORE spending scriptwriting tokens. A broken spine (no usable scenes, or a setup that pays
    off in a scene that doesn't exist) routes to the repair flow instead of writing scripts onto
    a broken story."""
    blueprint = ctx["blueprint"]
    problems = studio_showrunner.gate_blueprint(blueprint)
    if problems:
        error = "; ".join(problems)
        report = studio_repair.build_repair_report(
            "showrunner", error,
            context={"scene_count": (blueprint or {}).get("scene_count"),
                     "summary": (blueprint or {}).get("summary", "")})
        return ({"problems": problems, "blueprint": blueprint},
                {"reject": {"phase": "showrunner", "error": error, "repair": report}})
    return {"passed": True, "scene_count": (blueprint or {}).get("scene_count")}, {}


def _run_scenes(runner, ctx):
    """Stage 5 (cinematic): Scriptwriter + Cinematographer — write each scene's narration script
    + evocative image prompt from the approved blueprint (replaces the 12-panel comic back half)."""
    scenes = runner.run_scenes(blueprint=ctx["blueprint"], ep_id=ctx.get("ep_id"),
                               mode=ctx["mode"], source_story=ctx["source_story"])
    ctx["scenes"] = scenes
    return scenes, {}


def build_registry() -> List[StudioAgent]:
    """The ordered cinematic roster. `reads` are the artifact keys each agent depends on.

    The chain — intake → understanding (loremaster/genesis) → world → characters → showrunner →
    gate → scenes — is the cinematic production path from docs/visionchecklist.md, replacing the
    legacy 12-panel comic chain (casting → treatment → planner → 12 panels → continuity).
    """
    return [
        StudioAgent("intake", "User Intake", [], "premise", _run_intake,
                    description="Turns the seed/story into a working premise."),
        StudioAgent("understanding", "Loremaster / Genesis", ["premise"], "understanding",
                    _run_understanding, model_tier="medium",
                    description="Distills (adapt/continue) or invents (seed) a complete story_understanding."),
        StudioAgent("world", "World Builder", ["premise"], "world", _run_world, model_tier="medium",
                    description="Structured world bible: palette, lighting, locations."),
        StudioAgent("characters", "Character Creator", ["premise", "world"], "characters", _run_characters,
                    model_tier="medium", description="One structured bible per character."),
        StudioAgent("showrunner", "Showrunner", ["understanding", "world", "characters"],
                    "scene_blueprint", _run_showrunner, model_tier="medium",
                    description="Dynamic scene blueprint with explicit setup→payoff."),
        StudioAgent("gate", "Setup/Payoff Gate", ["scene_blueprint"], "scene_gate", _run_gate,
                    description="Validates the blueprint before scriptwriting; routes a broken spine to repair."),
        StudioAgent("scenes", "Scriptwriter + Cinematographer", ["scene_blueprint", "scene_gate"],
                    "scenes", _run_scenes, model_tier="medium",
                    description="Writes each scene's narration script + evocative image prompt."),
    ]


class Producer:
    """Headmaster: schedules agents by dependency, publishes artifacts, routes rejections."""

    def __init__(self, runner, registry=None):
        self.runner = runner
        self.registry = registry or build_registry()
        self.project_name = runner.project_name
        self.project_id = runner.project_id

    def _post(self, agent_id, status, topic="", detail=""):
        bb.post(self.project_name, self.project_id, agent_id, status, topic, detail)

    def run(self, seed_text, mode, source_story):
        """Drive the full production through the blackboard. Returns the same shape as
        StudioWorkflowRunner.run_full_pipeline (ok / data / model_status, or a repair payload)."""
        runner = self.runner
        ctx = {"seed_text": seed_text, "mode": mode, "source_story": source_story}

        for agent in self.registry:
            if not bb.has_all(self.project_name, self.project_id, agent.reads):
                # Dependencies missing — should not happen given the ordered registry, but the
                # gate makes the contract explicit and the failure legible.
                self._post(agent.id, "blocked", agent.writes, f"missing deps: {agent.reads}")
                return {"ok": False, "error": f"Agent '{agent.id}' blocked on {agent.reads}",
                        "model_status": runner.model_status}

            self._post(agent.id, "running", agent.role, agent.description)
            try:
                artifact, control = agent.run(runner, ctx)
            except Exception as exc:
                self._post(agent.id, "error", agent.writes, str(exc))
                raise

            if control.get("reject"):
                rej = control["reject"]
                bb.put_artifact(self.project_name, self.project_id, agent.writes, artifact,
                                produced_by=agent.id, status="rejected")
                self._post(agent.id, "rejected", agent.writes, rej.get("error", ""))
                runner.state = "needs_repair"
                return {
                    "ok": False, "needs_repair": True, "phase": rej["phase"],
                    "project_id": self.project_id, "project_name": self.project_name,
                    "error": rej.get("error"), "repair": rej.get("repair"),
                    "model_status": runner.model_status,
                }

            bb.put_artifact(self.project_name, self.project_id, agent.writes, artifact, produced_by=agent.id)
            self._post(agent.id, "done", agent.writes)

        # Assemble the final result (mirrors run_full_pipeline's success payload).
        import studio_memory as memory
        final_data = memory.export_project_json(self.project_name, self.project_id)
        runner.state = "complete"
        self._post("producer", "complete", "pipeline", "All agents finished.")
        return {
            "ok": True,
            "project_id": self.project_id,
            "project_name": self.project_name,
            "mode": mode,
            "blueprint": ctx.get("blueprint"),
            "scenes": ctx.get("scenes"),
            "data": final_data,
            "model_status": runner.model_status,
        }
