"""A small, dependency-free Turtle reader/writer.

SETM stores graphs as RDF when the user picks the ``rdf://`` backend. Pulling in
rdflib for that is optional: this module handles the Turtle subset SETM emits
(prefixes, IRIs, literals with datatype or language tags, ``;`` and ``,``
predicate/object lists, ``a`` for rdf:type). When rdflib *is* installed the
backend uses it instead, so arbitrary third-party Turtle still parses.

Terms are plain tuples so nothing outside this module needs a vocabulary:

* ``("iri", "https://example.org/x")``
* ``("lit", "text", datatype_iri | None, language | None)``
"""

from __future__ import annotations

import re
from typing import Iterable, Iterator, Sequence

Term = tuple
Triple = tuple[Term, Term, Term]

XSD = "http://www.w3.org/2001/XMLSchema#"
RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
RDFS = "http://www.w3.org/2000/01/rdf-schema#"
OWL = "http://www.w3.org/2002/07/owl#"
DCTERMS = "http://purl.org/dc/terms/"

BASE_PREFIXES = {
    "rdf": RDF,
    "rdfs": RDFS,
    "owl": OWL,
    "xsd": XSD,
    "dcterms": DCTERMS,
}

_PNAME_LOCAL_SAFE = re.compile(r"^[A-Za-z_][A-Za-z0-9_\-.]*$")


def iri(value: str) -> Term:
    return ("iri", value)


def lit(value: object, datatype: str | None = None, language: str | None = None) -> Term:
    if isinstance(value, bool):
        return ("lit", "true" if value else "false", XSD + "boolean", None)
    if isinstance(value, int) and datatype is None:
        return ("lit", str(value), XSD + "integer", None)
    if isinstance(value, float) and datatype is None:
        return ("lit", repr(value), XSD + "double", None)
    return ("lit", str(value), datatype, language)


# --------------------------------------------------------------------------- #
# Writing
# --------------------------------------------------------------------------- #

_ESCAPES = {"\\": "\\\\", '"': '\\"', "\n": "\\n", "\r": "\\r", "\t": "\\t"}


def _escape(text: str) -> str:
    return "".join(_ESCAPES.get(ch, ch) for ch in text)


def _compress(value: str, prefixes: dict[str, str]) -> str:
    for prefix, namespace in prefixes.items():
        if value.startswith(namespace):
            local = value[len(namespace) :]
            if _PNAME_LOCAL_SAFE.match(local):
                return f"{prefix}:{local}"
    return f"<{value}>"


def format_term(term: Term, prefixes: dict[str, str]) -> str:
    kind = term[0]
    if kind == "iri":
        return _compress(term[1], prefixes)
    value, datatype, language = term[1], term[2], term[3]
    if datatype in (XSD + "integer", XSD + "double", XSD + "decimal", XSD + "boolean"):
        return value
    body = f'"{_escape(value)}"'
    if language:
        return f"{body}@{language}"
    if datatype and datatype != XSD + "string":
        return f"{body}^^{_compress(datatype, prefixes)}"
    return body


def serialize_triples(
    triples: Iterable[Triple],
    prefixes: dict[str, str] | None = None,
    *,
    header: str = "",
) -> str:
    """Group triples by subject and emit compact Turtle."""
    all_prefixes = dict(BASE_PREFIXES)
    all_prefixes.update(prefixes or {})

    grouped: dict[str, list[tuple[Term, Term]]] = {}
    subjects: dict[str, Term] = {}
    for subject, predicate, obj in triples:
        key = repr(subject)
        subjects.setdefault(key, subject)
        grouped.setdefault(key, []).append((predicate, obj))

    lines: list[str] = []
    if header:
        lines.extend(f"# {line}" for line in header.splitlines())
        lines.append("")
    for prefix, namespace in all_prefixes.items():
        lines.append(f"@prefix {prefix}: <{namespace}> .")
    lines.append("")

    for key, pairs in grouped.items():
        subject_text = format_term(subjects[key], all_prefixes)
        lines.append(f"{subject_text}")
        rendered = []
        for predicate, obj in pairs:
            pred_text = "a" if predicate == ("iri", RDF + "type") else format_term(predicate, all_prefixes)
            rendered.append(f"    {pred_text} {format_term(obj, all_prefixes)}")
        lines.append(" ;\n".join(rendered) + " .")
        lines.append("")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Reading
# --------------------------------------------------------------------------- #

_TOKEN_RE = re.compile(
    r"""
      (?P<ws>\s+)
    | (?P<comment>\#[^\n]*)
    | (?P<longstring>"{3}(?:\\.|[^\\]|\n)*?"{3})
    | (?P<string>"(?:\\.|[^"\\])*")
    | (?P<iri><[^>\s]*>)
    | (?P<prefix_decl>@prefix|@base|(?i:PREFIX|BASE))
    | (?P<lang>@[A-Za-z][A-Za-z0-9\-]*)
    | (?P<datatype>\^\^)
    | (?P<number>[+-]?(?:\d+\.\d*(?:[eE][+-]?\d+)?|\.\d+(?:[eE][+-]?\d+)?|\d+(?:[eE][+-]?\d+)?))
    | (?P<pname>[A-Za-z_][A-Za-z0-9_\-.]*:[A-Za-z0-9_\-.%]*|:[A-Za-z0-9_\-.%]*)
    | (?P<keyword>true|false|a)
    | (?P<punct>[;,.\[\]()])
    """,
    re.VERBOSE,
)

_STR_UNESCAPE = {"\\": "\\", '"': '"', "n": "\n", "r": "\r", "t": "\t", "'": "'"}


def _unescape(text: str) -> str:
    out: list[str] = []
    index = 0
    while index < len(text):
        char = text[index]
        if char == "\\" and index + 1 < len(text):
            nxt = text[index + 1]
            if nxt == "u":
                out.append(chr(int(text[index + 2 : index + 6], 16)))
                index += 6
                continue
            out.append(_STR_UNESCAPE.get(nxt, nxt))
            index += 2
            continue
        out.append(char)
        index += 1
    return "".join(out)


class TurtleSyntaxError(ValueError):
    pass


def _tokenize(text: str) -> Iterator[tuple[str, str]]:
    position = 0
    length = len(text)
    while position < length:
        match = _TOKEN_RE.match(text, position)
        if not match:
            snippet = text[position : position + 40].replace("\n", " ")
            raise TurtleSyntaxError(f"Cannot parse Turtle near: {snippet!r}")
        position = match.end()
        kind = match.lastgroup or ""
        if kind in ("ws", "comment"):
            continue
        yield kind, match.group()


def parse_turtle(text: str) -> tuple[list[Triple], dict[str, str]]:
    """Parse the Turtle subset SETM writes. Returns (triples, prefixes)."""
    tokens = list(_tokenize(text))
    prefixes: dict[str, str] = dict(BASE_PREFIXES)
    triples: list[Triple] = []
    index = 0
    subject: Term | None = None
    predicate: Term | None = None

    def resolve(kind: str, raw: str) -> Term:
        if kind == "iri":
            return ("iri", raw[1:-1])
        if kind == "pname":
            prefix, _, local = raw.partition(":")
            namespace = prefixes.get(prefix)
            if namespace is None:
                raise TurtleSyntaxError(f"Undefined prefix '{prefix}:'")
            return ("iri", namespace + local)
        raise TurtleSyntaxError(f"Expected an IRI, got {raw!r}")

    while index < len(tokens):
        kind, raw = tokens[index]

        if kind == "prefix_decl":
            if raw.lower() in ("@prefix", "prefix"):
                _, name = tokens[index + 1]
                _, target = tokens[index + 2]
                prefixes[name.rstrip(":").partition(":")[0]] = target[1:-1]
                index += 3
                if index < len(tokens) and tokens[index] == ("punct", "."):
                    index += 1
            else:  # @base / BASE - accepted and ignored
                index += 2
                if index < len(tokens) and tokens[index] == ("punct", "."):
                    index += 1
            continue

        if kind == "punct":
            if raw == ".":
                subject = predicate = None
            elif raw == ";":
                predicate = None
            elif raw == ",":
                pass
            else:
                raise TurtleSyntaxError(f"Unsupported Turtle construct '{raw}' (collections/blank nodes)")
            index += 1
            continue

        if subject is None:
            subject = resolve(kind, raw)
            index += 1
            continue

        if predicate is None:
            predicate = ("iri", RDF + "type") if (kind == "keyword" and raw == "a") else resolve(kind, raw)
            index += 1
            continue

        # object position
        if kind in ("string", "longstring"):
            value = _unescape(raw[3:-3] if kind == "longstring" else raw[1:-1])
            datatype: str | None = None
            language: str | None = None
            if index + 1 < len(tokens):
                next_kind, next_raw = tokens[index + 1]
                if next_kind == "lang":
                    language = next_raw[1:]
                    index += 1
                elif next_kind == "datatype":
                    dt_kind, dt_raw = tokens[index + 2]
                    datatype = resolve(dt_kind, dt_raw)[1]
                    index += 2
            obj: Term = ("lit", value, datatype, language)
        elif kind == "number":
            is_float = any(c in raw for c in ".eE")
            obj = ("lit", raw, XSD + ("double" if is_float else "integer"), None)
        elif kind == "keyword" and raw in ("true", "false"):
            obj = ("lit", raw, XSD + "boolean", None)
        else:
            obj = resolve(kind, raw)

        triples.append((subject, predicate, obj))
        index += 1

    return triples, prefixes


def literal_value(term: Term) -> object:
    """Convert a literal term back to a Python value."""
    if term[0] != "lit":
        return term[1]
    text, datatype = term[1], term[2]
    if datatype == XSD + "boolean":
        return text == "true"
    if datatype == XSD + "integer":
        return int(text)
    if datatype in (XSD + "double", XSD + "decimal", XSD + "float"):
        return float(text)
    return text


def group_by_subject(triples: Sequence[Triple]) -> dict[str, list[tuple[str, Term]]]:
    """Index triples as ``{subject_iri: [(predicate_iri, object_term), ...]}``."""
    out: dict[str, list[tuple[str, Term]]] = {}
    for subject, predicate, obj in triples:
        if subject[0] != "iri" or predicate[0] != "iri":
            continue
        out.setdefault(subject[1], []).append((predicate[1], obj))
    return out
