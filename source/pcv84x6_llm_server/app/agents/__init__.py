"""Installable open-source agents this service can run.

An agent here is a third-party assistant (opencode today, openclaw next) that
the service installs, configures against its own local models, and supervises.
Each one gets a directory tree of its own under ``<data>/agents/<id>/`` and is
reached through ``AgentManager`` rather than run by hand.
"""

from .manager import AgentBusy, AgentManager, AgentState, MemoryLow, PortBusy
from .spec import AgentError, AgentSpec, Artifact, InstallContext, ModelChoice

__all__ = [
    "AgentBusy",
    "AgentError",
    "AgentManager",
    "AgentSpec",
    "AgentState",
    "Artifact",
    "InstallContext",
    "MemoryLow",
    "ModelChoice",
    "PortBusy",
]
