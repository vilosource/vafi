"""WorkSource protocol and implementations.

This package defines the WorkSource protocol that the controller uses to
interact with work systems. It includes the abstract protocol definition
and concrete implementations for different work sources.
"""

from .protocol import WorkSource
from .vtf import VtfWorkSource

__all__ = ["WorkSource", "VtfWorkSource"]