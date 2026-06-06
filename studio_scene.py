"""Scene Builder — the programmatic, round-based state backend (Phase 2).

This is the deterministic half of the doc's Director/Scene-Builder split: the LLM
decides *what* should happen narratively, but this backend decides whether each
action is *physically valid* and records the result. It enforces simulator-valid
state against the capability registry (`studio_capabilities`) and commits accepted
action chains into the GEST graph (`studio_memory`) as nodes + temporal edges.

Round-based state machine (mirrors the spec):
    start_round  -> initialize actors at a region, return a state payload
    start_chain  -> open a transactional action sequence for one actor at a POI
    add_action   -> validate + buffer the next action (posture/POI/object/order rules)
    do_interaction -> synchronized two-actor action (e.g. give_object)
    end_round    -> commit the buffered chain to GEST; merge state
    abort_chain  -> discard the buffered chain without touching committed state

Validation is programmatic and constraint-first: an invalid action raises
``SceneError`` *before* anything is written, so the committed GEST stays
executable by construction.
"""

import copy
import logging

import studio_capabilities as caps
import studio_memory as memory

logger = logging.getLogger("studio_scene")


class SceneError(ValueError):
    """Raised when an action would violate simulator state or registry constraints."""


class SceneBuilder:
    def __init__(self, project_name, project_id, episode_id=None, scene_id=None):
        self.project_name = project_name
        self.project_id = project_id
        self.episode_id = episode_id
        # Tags every committed node so Finalization can group nodes by scene and link scenes.
        self.scene_id = scene_id
        self.region = None
        self.actors = {}          # committed actor state: id -> {name, skin_id, posture, poi_id, held[]}
        self.poi_occupancy = {}   # committed POI occupancy: poi_id -> set(actor_id)
        self._round_open = False
        self._chain = None        # open transactional chain (working copy of state + buffered actions)
        self._actor_nodes = {}    # actor_id -> committed "exists" GEST node id
        self.committed = {"nodes": [], "edges": []}

    # --- round / state ----------------------------------------------------

    def start_round(self, region_id, actors=None):
        region = caps.get_capability("regions", region_id)
        if not region:
            raise SceneError(f"Unknown region '{region_id}'.")
        self.region = region
        self.actors = {}
        self.poi_occupancy = {}
        for spec in (actors or []):
            self._add_actor(spec)
        self._round_open = True
        return self.state_payload()

    def _add_actor(self, spec):
        actor_id = str(spec.get("id") or spec.get("name") or "").strip()
        if not actor_id:
            raise SceneError("Each actor needs an 'id' or 'name'.")
        if actor_id in self.actors:
            raise SceneError(f"Duplicate actor '{actor_id}'.")
        skin_id = spec.get("skin_id")
        if skin_id and not caps.get_capability("skins", skin_id):
            raise SceneError(f"Unknown skin '{skin_id}' for actor '{actor_id}'.")
        self.actors[actor_id] = {
            "id": actor_id,
            "name": spec.get("name", actor_id),
            "skin_id": skin_id,
            "posture": spec.get("posture", "standing"),
            "poi_id": None,
            "held": list(spec.get("held", [])),
        }
        start_poi = spec.get("start_poi") or spec.get("poi_id")
        if start_poi:
            self._place(self.actors, self.poi_occupancy, actor_id, start_poi)

    def _place(self, actors, occ, actor_id, poi_id):
        poi = caps.get_capability("pois", poi_id)
        if not poi:
            raise SceneError(f"Unknown POI '{poi_id}'.")
        if poi.get("region_id") != self.region["id"]:
            raise SceneError(f"POI '{poi_id}' is not in region '{self.region['id']}'.")
        prev = actors[actor_id]["poi_id"]
        if prev and prev != poi_id and prev in occ:
            occ[prev].discard(actor_id)
        current = occ.setdefault(poi_id, set())
        if actor_id not in current and len(current) >= int(poi.get("capacity", 1)):
            raise SceneError(f"POI '{poi_id}' is at capacity ({poi.get('capacity')}).")
        current.add(actor_id)
        actors[actor_id]["poi_id"] = poi_id

    def state_payload(self):
        return {
            "region_id": self.region["id"] if self.region else None,
            "region_name": self.region["name"] if self.region else None,
            "actors": [copy.deepcopy(actor) for actor in self.actors.values()],
        }

    # --- chain ------------------------------------------------------------

    def start_chain(self, actor_id, poi_id=None):
        if not self._round_open:
            raise SceneError("start_round must be called before start_chain.")
        if self._chain is not None:
            raise SceneError("A chain is already open; call end_round or abort_chain first.")
        if actor_id not in self.actors:
            raise SceneError(f"Unknown actor '{actor_id}'.")
        working_actors = copy.deepcopy(self.actors)
        working_occ = copy.deepcopy(self.poi_occupancy)
        if poi_id:
            self._place(working_actors, working_occ, actor_id, poi_id)
        self._chain = {"actor_id": actor_id, "actors": working_actors, "occ": working_occ, "actions": []}
        return copy.deepcopy(working_actors[actor_id])

    def add_action(self, action_id, target_object=None, receiver_id=None, poi_id=None):
        if self._chain is None:
            raise SceneError("start_chain must be called before adding actions.")
        action = caps.get_capability("actions", action_id)
        if not action:
            raise SceneError(f"Unknown action '{action_id}'.")

        actors = self._chain["actors"]
        occ = self._chain["occ"]
        actor_id = self._chain["actor_id"]
        actor = actors[actor_id]

        if poi_id:
            self._place(actors, occ, actor_id, poi_id)

        # Action-chain ordering: each step must be a permitted successor of the last.
        if self._chain["actions"]:
            prev_id = self._chain["actions"][-1]["action_id"]
            allowed = caps.get_capability("actions", prev_id).get("next_actions", [])
            if action_id not in allowed:
                raise SceneError(f"Action '{action_id}' cannot follow '{prev_id}'. Allowed: {allowed}.")

        # Posture prerequisite.
        req_posture = action.get("requires_posture") or []
        if req_posture and actor["posture"] not in req_posture:
            raise SceneError(
                f"Action '{action_id}' requires posture {req_posture}, but '{actor_id}' is '{actor['posture']}'."
            )

        # The actor must be at a POI that supports this action.
        poi_id_cur = actor["poi_id"]
        if not poi_id_cur:
            raise SceneError(f"Actor '{actor_id}' must be placed at a POI before '{action_id}'.")
        poi = caps.get_capability("pois", poi_id_cur)
        if action_id not in poi.get("supports", []):
            raise SceneError(f"POI '{poi_id_cur}' does not support action '{action_id}'.")

        # Object prerequisite.
        if action.get("requires_object"):
            if target_object and target_object not in actor["held"]:
                raise SceneError(f"Action '{action_id}' requires '{actor_id}' to hold '{target_object}'.")
            if not target_object and not actor["held"]:
                raise SceneError(f"Action '{action_id}' requires a held object.")

        # Receiver prerequisite (synchronized interactions).
        if action.get("requires_receiver"):
            if not receiver_id or receiver_id not in actors:
                raise SceneError(f"Action '{action_id}' requires a valid receiver present in the scene.")

        # Apply deterministic effects to the working copy.
        if action_id == "take_object" and target_object and target_object not in actor["held"]:
            actor["held"].append(target_object)
        if action_id == "give_object":
            obj = target_object or (actor["held"][0] if actor["held"] else None)
            if not obj:
                raise SceneError("give_object requires a held object to give.")
            if obj in actor["held"]:
                actor["held"].remove(obj)
            actors[receiver_id]["held"].append(obj)
            target_object = obj
        if action.get("result_posture"):
            actor["posture"] = action["result_posture"]

        step = {
            "action_id": action_id,
            "actor_id": actor_id,
            "poi_id": poi_id_cur,
            "object": target_object,
            "receiver_id": receiver_id if action.get("requires_receiver") else None,
            "label": f"{actor['name']}: {action['name']} at {poi['name']}",
        }
        self._chain["actions"].append(step)
        return copy.deepcopy(step)

    # continue_chain is just the next action in an open chain.
    continue_chain = add_action

    def do_interaction(self, action_id, receiver_id, target_object=None):
        """Convenience for a synchronized two-actor action (e.g. give_object)."""
        return self.add_action(action_id, target_object=target_object, receiver_id=receiver_id)

    def abort_chain(self):
        """Discard the open chain; committed state is untouched."""
        self._chain = None

    def end_round(self):
        if self._chain is None:
            raise SceneError("No open chain to commit.")
        chain = self._chain
        actions = chain["actions"]
        if not actions:
            self._chain = None
            return {"committed": False, "reason": "empty chain", "nodes": [], "edges": []}

        node_ids = []
        edge_ids = []
        # Anchor the acting actor as an "exists" node once.
        self._ensure_actor_node(chain["actor_id"], chain["actors"][chain["actor_id"]])

        prev_node = None
        for step in actions:
            node_id = memory.add_gest_node(
                self.project_name, self.project_id, "action", step["label"],
                ref_type="poi", episode_id=self.episode_id,
                metadata=self._meta({
                    "action_id": step["action_id"], "actor_id": step["actor_id"],
                    "poi_id": step["poi_id"], "object": step["object"], "receiver_id": step["receiver_id"],
                }),
            )
            node_ids.append(node_id)
            if prev_node is not None:
                edge_ids.append(memory.add_gest_edge(self.project_name, self.project_id, prev_node, node_id, "before"))
            prev_node = node_id

            # Give/INV-Give synchronization: a receiver event occurs at the same time.
            if step["action_id"] == "give_object" and step["receiver_id"]:
                receiver = chain["actors"][step["receiver_id"]]
                self._ensure_actor_node(step["receiver_id"], receiver)
                inv_node = memory.add_gest_node(
                    self.project_name, self.project_id, "event",
                    f"{receiver['name']}: receives {step['object'] or 'object'}",
                    episode_id=self.episode_id,
                    metadata=self._meta({"action_id": "inv_give", "actor_id": step["receiver_id"], "object": step["object"]}),
                )
                node_ids.append(inv_node)
                edge_ids.append(memory.add_gest_edge(self.project_name, self.project_id, node_id, inv_node, "same_time"))

        # Commit: working state becomes the new committed state.
        self.actors = chain["actors"]
        self.poi_occupancy = chain["occ"]
        self._chain = None
        self.committed["nodes"].extend(node_ids)
        self.committed["edges"].extend(edge_ids)
        return {"committed": True, "nodes": node_ids, "edges": edge_ids, "state": self.state_payload()}

    def _ensure_actor_node(self, actor_id, actor):
        if actor_id in self._actor_nodes:
            return self._actor_nodes[actor_id]
        node_id = memory.add_gest_node(
            self.project_name, self.project_id, "exists", actor["name"],
            ref_type="character", episode_id=self.episode_id,
            metadata=self._meta({"actor_id": actor_id, "skin_id": actor.get("skin_id")}),
        )
        self._actor_nodes[actor_id] = node_id
        return node_id

    def _meta(self, data):
        """Tag node metadata with this scene's id so Finalization can group/link by scene."""
        if self.scene_id:
            return {**data, "scene_id": self.scene_id}
        return data
