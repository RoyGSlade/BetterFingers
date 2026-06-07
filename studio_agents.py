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


def _run_casting(runner, ctx):
    casting = runner.run_director_casting(premise_data=ctx["premise"])
    ctx["casting"] = casting
    return casting.get("data", casting), {}


def _run_world(runner, ctx):
    world = runner.run_world_building(ctx["premise"], mode=ctx["mode"], source_story=ctx["source_story"])
    ctx["world"] = world
    return world, {}


def _run_characters(runner, ctx):
    chars = runner.run_character_building(ctx["premise"], ctx["world"], mode=ctx["mode"], source_story=ctx["source_story"])
    ctx["characters"] = chars
    return chars, {}


def _run_treatment(runner, ctx):
    treatment = runner.run_treatment(ctx["premise"], ctx["world"], ctx["characters"],
                                     mode=ctx["mode"], source_story=ctx["source_story"])
    ctx["treatment"] = treatment
    return treatment, {}


def _run_planner(runner, ctx):
    story_plan, ep_id = runner.run_story_planning(ctx["premise"], ctx["world"], ctx["characters"],
                                                  mode=ctx["mode"], source_story=ctx["source_story"])
    ctx["story_plan"] = story_plan
    ctx["ep_id"] = ep_id
    return story_plan, {}


def _run_scene(runner, ctx):
    scene = runner.run_director_scene_planning(ctx["premise"], ctx["world"], ctx["characters"], ctx["story_plan"])
    ctx["scene"] = scene
    # A rejected scene that even the grounded fallback couldn't commit -> route to repair.
    if not scene.get("ok") and scene.get("repair"):
        return scene, {"reject": {"phase": scene.get("phase", "director_scene_planning"),
                                  "error": scene.get("error"), "repair": scene.get("repair")}}
    return scene, {}


def _run_panels(runner, ctx):
    panels = runner.run_dialogue_and_panels(ctx["premise"], ctx["world"], ctx["characters"],
                                            ctx["story_plan"], ctx["ep_id"],
                                            mode=ctx["mode"], source_story=ctx["source_story"])
    ctx["panels"] = panels
    return panels, {}


def _run_continuity(runner, ctx):
    warnings = runner.run_continuity_audit(ctx["premise"], ctx["world"], ctx["characters"], ctx["panels"],
                                           mode=ctx["mode"], source_story=ctx["source_story"])
    ctx["warnings"] = warnings
    return warnings, {}


def build_registry() -> List[StudioAgent]:
    """The ordered roster. `reads` are the artifact keys each agent depends on."""
    return [
        StudioAgent("intake", "User Intake", [], "premise", _run_intake,
                    description="Turns the seed/story into a working premise."),
        StudioAgent("casting", "Director (Casting)", ["premise"], "casting", _run_casting,
                    description="Picks a grounded region + character skins."),
        StudioAgent("world", "World Builder", ["premise"], "world", _run_world, model_tier="medium",
                    description="Structured world bible: palette, lighting, locations."),
        StudioAgent("characters", "Character Creator", ["premise", "world"], "characters", _run_characters,
                    model_tier="medium", description="One structured bible per character."),
        StudioAgent("treatment", "Story Editor", ["premise", "world", "characters"], "treatment", _run_treatment,
                    model_tier="medium", description="Expands the premise into a story spine."),
        StudioAgent("planner", "Story Planner", ["treatment"], "beats", _run_planner, model_tier="medium",
                    description="60-second beat sheet."),
        StudioAgent("scene", "Director (Scene)", ["beats", "characters"], "scene", _run_scene,
                    description="Simulator-valid GEST scene; repairable on rejection."),
        StudioAgent("panels", "Shot/Panel + Visual + Dialogue", ["beats", "world", "characters"], "panels",
                    _run_panels, model_tier="medium",
                    description="Shot list -> 12 panels -> image prompts -> voiced dialogue."),
        StudioAgent("continuity", "Continuity Critic", ["panels"], "continuity", _run_continuity,
                    description="Flags inconsistencies for repair."),
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
            "casting": ctx.get("casting", {}).get("data") if isinstance(ctx.get("casting"), dict) else ctx.get("casting"),
            "scene": ctx.get("scene"),
            "data": final_data,
            "model_status": runner.model_status,
        }
