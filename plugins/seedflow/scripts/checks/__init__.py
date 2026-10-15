"""Reglas con las que seedflow califica qué tan organizado está un repo.

Contrato que comparten todos los módulos de reglas de esta carpeta.
"""

from __future__ import annotations

from collections.abc import Iterable
from collections.abc import Sequence
from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
from typing import Any


CATEGORIES = ("estructura", "calidad", "dependencias", "higiene")
SEVERITY = {"critico": 25, "importante": 10, "menor": 3}


@dataclass(frozen=True)
class Finding:
    """Una regla incumplida en un lugar concreto."""

    category: str
    rule: str
    points: int
    project: str
    path: str
    message: str
    why: str
    how: str
    fix_id: str | None = None


@dataclass
class CheckResult:
    """Lo que devuelve el run() de un módulo de reglas."""

    findings: list[Finding] = field(default_factory=list)
    not_evaluated: dict[str, str] = field(default_factory=dict)


@dataclass
class Microservice:
    """Un microservicio de un proyecto."""

    name: str
    service_type: str
    path: Path


@dataclass
class Project:
    """Un proyecto de projects/."""

    name: str
    path: Path
    microservices: list[Microservice]


@dataclass
class Context:
    """Lo que reciben las reglas."""

    root: Path
    projects: list[Project]
    tracked: set[str] | None
    quick: bool


# --------------------------------------------------------------------------
# Nota
# --------------------------------------------------------------------------

CATEGORY_LABELS = {
    "estructura": "estructura",
    "calidad": "calidad de código",
    "dependencias": "dependencias",
    "higiene": "seguridad e higiene",
}
SKIPPED_IN_QUICK = "no se revisa en la línea de resumen"
NO_RULES = "no hay reglas de esta categoría"


@dataclass
class ProjectScore:
    """La nota de un proyecto y la de cada categoría (None: no evaluada)."""

    name: str
    score: int | None
    categories: dict[str, int | None]
    not_evaluated: dict[str, str]


@dataclass
class Report:
    """El resultado de calificar el repo."""

    root: Path
    score: int | None
    semaphore: str | None
    projects: list[ProjectScore]
    findings: list[Finding]

    def as_dict(self) -> dict[str, Any]:
        """Forma de `seedflow.py check --json`."""
        return {
            "root": str(self.root),
            "score": self.score,
            "semaphore": self.semaphore,
            "projects": [asdict(project) for project in self.projects],
            "findings": [asdict(finding) for finding in self.findings],
        }


def category_score(points: Iterable[int]) -> int:
    """100 menos los descuentos, sin bajar de 0."""
    return max(0, 100 - sum(points))


def average(values: Sequence[int]) -> int | None:
    """Promedio redondeado al entero más cercano, con .5 hacia arriba.

    Con enteros, sin pasar por float: round() de Python lleva 74.5 a 74.
    """
    if not values:
        return None
    return (2 * sum(values) + len(values)) // (2 * len(values))


def semaphore(score: int | None) -> str | None:
    """🟢 75 o más, 🟡 de 50 a 74, 🔴 menos de 50."""
    if score is None:
        return None
    if score >= 75:
        return "🟢"
    if score >= 50:
        return "🟡"
    return "🔴"


def evaluate(ctx: Context, modules: Sequence[Any]) -> Report:
    """Corre los módulos de reglas que tocan y calcula la nota.

    Con ctx.quick no corren los módulos con QUICK = False. Una categoría sin
    módulo que la evalúe queda "no evaluada" y no entra en el promedio.
    """
    findings: list[Finding] = []
    per_project: dict[str, dict[str, str]] = {c: {} for c in CATEGORIES}
    skipped: dict[str, str] = {c: NO_RULES for c in CATEGORIES}
    ran: set[str] = set()
    for module in modules:
        if ctx.quick and not module.QUICK:
            skipped[module.CATEGORY] = SKIPPED_IN_QUICK
            continue
        result = module.run(ctx)
        check_findings(module, result.findings)
        ran.add(module.CATEGORY)
        findings.extend(result.findings)
        per_project[module.CATEGORY].update(result.not_evaluated)
    for category in ran:
        del skipped[category]
    projects = [
        score_project(project.name, findings, skipped, per_project)
        for project in ctx.projects
    ]
    score = average([p.score for p in projects if p.score is not None])
    return Report(
        root=ctx.root,
        score=score,
        semaphore=semaphore(score),
        projects=projects,
        findings=sorted(findings, key=finding_order),
    )


def check_findings(module: Any, findings: Iterable[Finding]) -> None:
    """Un módulo solo puede descontar en su propia categoría."""
    for finding in findings:
        if finding.category != module.CATEGORY:
            raise ValueError(
                f"{module.__name__} es de la categoría '{module.CATEGORY}' "
                f"pero devolvió un hallazgo de '{finding.category}' "
                f"({finding.rule} en {finding.path})."
            )


def score_project(
    name: str,
    findings: Sequence[Finding],
    skipped: dict[str, str],
    per_project: dict[str, dict[str, str]],
) -> ProjectScore:
    """Nota de cada categoría del proyecto y el promedio de las evaluadas."""
    categories: dict[str, int | None] = {}
    not_evaluated: dict[str, str] = {}
    for category in CATEGORIES:
        reason = skipped.get(category) or per_project[category].get(name)
        if reason is not None:
            categories[category] = None
            not_evaluated[category] = reason
            continue
        categories[category] = category_score(
            f.points
            for f in findings
            if f.project == name and f.category == category
        )
    evaluated = [s for s in categories.values() if s is not None]
    return ProjectScore(name, average(evaluated), categories, not_evaluated)


def finding_order(finding: Finding) -> tuple[str, int, str, str, str]:
    """Orden estable de los hallazgos, para que el reporte no cambie."""
    return (
        finding.project,
        CATEGORIES.index(finding.category),
        finding.path,
        finding.rule,
        finding.message,
    )
