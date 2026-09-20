"""SETM - Systems Engineering Traceability Manager.

A standalone tool for chief engineers, work package leaders and systems
engineers to plan, link and visualise systems engineering work on a programme:
who does what, against which milestone, why, and under which process and method.
"""

__version__ = "0.1.0"

from .config import Settings
from .errors import SetmError, ValidationError
from .model import Edge, GraphDocument, Node
from .workspace import Workspace

__all__ = ["Settings", "Workspace", "GraphDocument", "Node", "Edge", "SetmError", "ValidationError", "__version__"]
