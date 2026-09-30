"""The master ontology: the organisation's vocabulary every project starts from.

It lives in a file SETM manages (the ``master_ontology`` setting, by default
``./data/ontologies/master.json``). Until anything has been merged into it that
file does not exist and the master is the shipped template (the ``ontology``
setting), which is never written. The first merge seeds the file.

Projects keep their own copy (see :mod:`setm.ontology.project`), so a change to
the master reaches a project only when someone compares and merges it.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from .loader import build_ontology, load_ontology, ontology_to_source
from .schema import Ontology


def master_path(settings: Any) -> Path:
    return Path(getattr(settings, "master_ontology", "") or "./data/ontologies/master.json")


def master_saved(settings: Any) -> bool:
    return master_path(settings).is_file()


def load_master(settings: Any) -> Ontology:
    """The master: the managed file once it exists, the shipped template before."""
    path = master_path(settings)
    source = str(path) if path.is_file() else settings.ontology
    return load_ontology(source, overlays=settings.overlays)


def bump_version(version: str) -> str:
    """1.1.0 -> 1.1.1; anything that is not dotted numbers gets ".1" appended."""
    parts = str(version or "").split(".")
    if parts and all(re.fullmatch(r"\d+", p) for p in parts):
        parts[-1] = str(int(parts[-1]) + 1)
        return ".".join(parts)
    return f"{version or '1.0.0'}.1"


def save_master(settings: Any, source: dict[str, Any]) -> Ontology:
    """Write a new master, atomically, with its version bumped.

    Returns the ontology as it will be loaded from now on. The source is
    checked by building it first, so a broken master is never written.
    """
    source = json.loads(json.dumps(source))  # a private copy
    meta = source.setdefault("ontology", {})
    meta["version"] = bump_version(meta.get("version", "1.0.0"))
    ontology = build_ontology(source)

    path = master_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp = tempfile.mkstemp(prefix=".master-", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(source, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
        os.replace(temp, path)
    except BaseException:
        Path(temp).unlink(missing_ok=True)
        raise
    ontology.source_path = str(path)
    return ontology


def master_source(master: Ontology) -> dict[str, Any]:
    return ontology_to_source(master)
