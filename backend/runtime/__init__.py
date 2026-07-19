"""Dependency-injection containers for backend service runtimes.

No FastAPI, model, or audio imports here — only plain data holders that
services (like ``backend.services.dictation_pipeline``) accept as explicit
collaborators instead of reaching for module-level globals.
"""

from .dependencies import JobManagerCancellationBridge, PipelineDependencies

__all__ = ["PipelineDependencies", "JobManagerCancellationBridge"]
