"""ww-auto-core: Shared deterministic extraction, Blender showcase & handoff core engine."""

from .pipeline import PipelineOrchestrator
from .version import CORE_VERSION, HANDOFF_SCHEMA_VERSION, PIPELINE_SCHEMA_VERSION

__all__ = [
    "CORE_VERSION",
    "HANDOFF_SCHEMA_VERSION",
    "PIPELINE_SCHEMA_VERSION",
    "PipelineOrchestrator",
]
