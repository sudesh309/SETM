"""Registry of the worked examples SETM ships.

One place both the CLI (``setm demo --example ...``) and the HTTP API
(``GET/POST /api/examples``) read from, so the two never drift.
"""

from __future__ import annotations

from typing import Any, Callable

from .demo import build_demo
from .model import GraphDocument
from .modification_demo import build_modification_demo
from .ontology.schema import Ontology

Builder = Callable[[Ontology], GraphDocument]

EXAMPLES: dict[str, dict[str, Any]] = {
    "payload": {
        "label": "Satellite payload (new development)",
        "description": "Phase B optical payload programme: objectives, milestones, work packages, "
                        "a seven-tool engineering chain, requirements, risks and processes, all linked.",
        "build": build_demo,
    },
    "modification": {
        "label": "Aircraft modification programme (in-service)",
        "description": "A complex in-service modification with two workstreams - obsolescence and "
                        "a performance retrofit - sharing an architecture baseline (OAD/OPD/OSD) and "
                        "a real system-element breakdown.",
        "build": build_modification_demo,
    },
}
