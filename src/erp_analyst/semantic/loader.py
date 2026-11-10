"""Loads and renders the semantic layer (src/erp_analyst/semantic/layer.yaml):
metric definitions, dimension synonyms, and business rules — the thing
that closes the gap between "a schema" and "what the business actually
means by yield / revenue / a quarter." Kept separate from schema_context.py
(the raw table/column listing) so each can change independently.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

DEFAULT_PATH = Path(__file__).resolve().parent / "layer.yaml"


@dataclass
class Metric:
    name: str
    label: str
    definition: str
    source: str
    description: str
    filter: str | None = None


@dataclass
class Dimension:
    name: str
    table: str
    synonyms: list[str]


@dataclass
class BusinessRule:
    id: str
    rule: str


@dataclass
class SemanticLayer:
    version: str
    metrics: dict[str, Metric]
    dimensions: dict[str, Dimension]
    business_rules: list[BusinessRule]

    @classmethod
    def load(cls, path: Path = DEFAULT_PATH) -> SemanticLayer:
        raw = yaml.safe_load(path.read_text())
        metrics = {
            name: Metric(
                name=name,
                label=m["label"],
                definition=m["definition"],
                source=m["source"],
                description=m["description"].strip(),
                filter=m.get("filter"),
            )
            for name, m in raw.get("metrics", {}).items()
        }
        dimensions = {
            name: Dimension(name=name, table=d["table"], synonyms=d.get("synonyms", []))
            for name, d in raw.get("dimensions", {}).items()
        }
        business_rules = [BusinessRule(id=r["id"], rule=r["rule"].strip()) for r in raw.get("business_rules", [])]
        return cls(version=raw["version"], metrics=metrics, dimensions=dimensions, business_rules=business_rules)

    def find_metric_by_term(self, term: str) -> Metric | None:
        """Loose lookup: an exact metric name, or a word appearing in its label."""
        term_lower = term.lower().strip()
        if term_lower in self.metrics:
            return self.metrics[term_lower]
        for metric in self.metrics.values():
            if term_lower in metric.label.lower():
                return metric
        return None

    def find_dimension_by_synonym(self, term: str) -> Dimension | None:
        term_lower = term.lower().strip()
        for dim in self.dimensions.values():
            if term_lower == dim.name or term_lower in (s.lower() for s in dim.synonyms):
                return dim
        return None

    def render(self) -> str:
        """Plain-text block appended to the agent's prompt."""
        lines = ["Business definitions (semantic layer v" + self.version + "):", ""]

        lines.append("Metrics — use these exact definitions, don't improvise a different formula:")
        for m in self.metrics.values():
            filter_note = f" WHERE {m.filter}" if m.filter else ""
            lines.append(f"- {m.name} ({m.label}): {m.definition}{filter_note}, from {m.source}.")
            lines.append(f"  {m.description}")
        lines.append("")

        lines.append("Dimension synonyms — these all mean the same underlying table:")
        for d in self.dimensions.values():
            syn = ", ".join(d.synonyms)
            lines.append(f"- {d.name} ({d.table}): also called {syn}")
        lines.append("")

        lines.append("Business rules:")
        for r in self.business_rules:
            lines.append(f"- [{r.id}] {r.rule}")

        return "\n".join(lines)
