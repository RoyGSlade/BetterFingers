"""Aggregate strict-YAML loader for the wave-6B room/NPC/lattice slice.

The per-family loading logic lives in sibling modules to stay under the
repo's ~500-line module convention:
  - `room_loader.py` -- rooms, objects, lattice contributions/recipes.
  - `npc_loader.py` -- NPC templates.
  - `study_common.py` -- shared `prose`/`effects`/`viewer_scope` helpers and
    a `require_keys` re-export.

This module re-exports `LoaderError` and the individual `load_*` functions
so callers (tests, a future wiring wave) have one obvious entry point,
mirroring how `content/__init__.py` re-exports `loader.py`'s public names.
"""

from __future__ import annotations

from pathlib import Path
from typing import Mapping

from . import lattice as LT
from . import npcs as N
from . import rooms as R
from .loader import LoaderError
from .npc_loader import load_npc_templates
from .room_loader import load_lattice_recipes, load_room_templates

__all__ = [
    "LoaderError",
    "load_npc_templates",
    "load_lattice_recipes",
    "load_room_templates",
    "load_study_pack",
    "StudyContentPack",
    "STUDY_PACK_DIR",
]

STUDY_PACK_DIR = Path(__file__).resolve().parent / "packs" / "core"


class StudyContentPack:
    """Minimal loaded-pack container for this wave's room/npc/lattice
    content. Deliberately not merged into `schemas.ContentPack` this wave --
    see docs/INFINITE_STACKS_STUDY_SLICE.md's open questions for why (that
    dataclass is engine-lane-adjacent territory; this wave stays additive)."""

    def __init__(
        self,
        rooms: Mapping[str, R.RoomTemplate],
        npcs: Mapping[str, N.NPCTemplate],
        lattice_recipes: Mapping[str, LT.LatticeRecipe],
    ) -> None:
        self.rooms = dict(rooms)
        self.npcs = dict(npcs)
        self.lattice_recipes = dict(lattice_recipes)


def load_study_pack(pack_dir: Path = STUDY_PACK_DIR) -> StudyContentPack:
    rooms = load_room_templates(pack_dir / "study.yaml")
    npc_templates = load_npc_templates(pack_dir / "npcs.yaml")
    lattice_recipes = load_lattice_recipes(pack_dir / "lattice.yaml")
    return StudyContentPack(rooms=rooms, npcs=npc_templates, lattice_recipes=lattice_recipes)
