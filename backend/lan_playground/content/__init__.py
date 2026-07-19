"""Content pipeline for The Lost Meaning: Infinite Stacks (board task #2).

`schemas.py` defines the versioned data model, `loader.py` loads YAML packs
into it strictly, `validators.py` runs CI-style cross-file checks (§23.2).
Content is data; the LLM never owns solutions or mechanics (§20.2).
"""

from .loader import LoaderError, load_core_pack, load_pack
from .schemas import ContentError, ContentPack
from .validators import Finding, ValidationError, validate_pack, validate_pack_dir

__all__ = [
    "ContentError",
    "ContentPack",
    "LoaderError",
    "ValidationError",
    "Finding",
    "load_core_pack",
    "load_pack",
    "validate_pack",
    "validate_pack_dir",
]
