"""Reglas de dependencias: las librerías Melonn (`lib-python-*`).

- D1 (importante): una `lib-python-*` sin `@<sha>` (sin `@`, con `@main` o
  con otra rama o tag), en `python/requirements.txt` o en el
  `layers/requirements.txt` de un microservicio.
- D2 (menor): la misma librería con SHAs distintos entre el
  `layers/requirements.txt` de un microservicio y `python/requirements.txt`.
- D3 (importante): el código de `src/` importa una librería Melonn cuyo repo
  no está en el `layers/requirements.txt` de su microservicio.

Ninguna tiene arreglo mecánico: fijar o cambiar una versión es una decisión.
Solo lee; no atraviesa enlaces.
"""

from __future__ import annotations

import ast
import os
import re
from collections.abc import Iterator
from pathlib import Path

from . import SEVERITY
from . import CheckResult
from . import Context
from . import Finding
from . import Microservice
from . import Project
from . import iter_files


CATEGORY = "dependencias"
QUICK = True

# Import -> repo, según el índice de references/librerias.md.
IMPORT_TO_REPO = {
    "melonnRedshiftConnector": "lib-python-redshift-connector",
    "melonnMySQLConnector": "lib-python-mysql-connector",
    "melonnAWSUtils": "lib-python-aws-utils",
    "melonnGoogleConnector": "lib-python-google-connector",
    "melonnCustomErrors": "lib-python-custom-errors",
    "melonnValidator": "lib-python-validator",
    "we_are_melonn.slack_notifier": "lib-python-slack-notifier",
    "we_are_melonn.google_notifier": "lib-python-google-chat-notifier",
    "we_are_melonn.melogger": "lib-python-melogger",
}

# Un comentario de requirements empieza con '#' al inicio o tras un espacio
# (así `...@sha#egg=...` no es un comentario).
COMMENT = re.compile(r"(^|\s)#.*$")
# El repo va al inicio de la línea, tras espacios o tras '/' (en la URL), con
# o sin especificador (`==1.0`, `[extra]`); la versión de git va tras '@'.
LIBRARY = re.compile(
    r"(?:^|[\s/])(?P<repo>lib-python-[A-Za-z0-9_-]+)(?:\.git)?"
    r"(?:@(?P<ref>[^\s#;]+))?"
)
SHA = re.compile(r"[0-9a-fA-F]{7,40}")

WHY_PIN = (
    "Sin un SHA fijo, cada despliegue instala lo último de la rama: un cambio "
    "en la librería puede romper la Lambda sin que nadie toque este repo."
)
HOW_PIN = (
    "Fija el commit: git+https://github.com/we-are-melonn/<repo>.git@<sha>, "
    "con el mismo SHA de python/requirements.txt (o el de "
    "`git ls-remote ... HEAD`)."
)
WHY_SAME_SHA = (
    "En local se prueba con una versión y la Lambda corre con otra: lo que "
    "funciona en tu máquina puede fallar desplegado."
)
HOW_SAME_SHA = (
    "Usa el mismo SHA en los dos archivos (el de python/requirements.txt, "
    "salvo que el microservicio necesite otro a propósito)."
)
WHY_IMPORT = (
    "La capa de la Lambda se arma con layers/requirements.txt: si la librería "
    "no está ahí, el import falla al desplegar aunque en local funcione."
)
HOW_IMPORT = (
    "Agrega la librería a layers/requirements.txt con su @<sha> (el mismo de "
    "python/requirements.txt)."
)


def run(ctx: Context) -> CheckResult:
    """Revisa las dependencias de cada proyecto y sus microservicios."""
    findings: list[Finding] = []
    for project in ctx.projects:
        findings.extend(check_project(ctx.root, project))
    return CheckResult(findings=findings)


def check_project(root: Path, project: Project) -> Iterator[Finding]:
    """D1 en python/requirements.txt y las tres reglas en cada microservicio."""
    python_reqs = project.path / "python" / "requirements.txt"
    python_lines = read_requirements(project.path, "python", "requirements.txt")
    yield from unpinned(root, project, python_reqs, python_lines)
    python_shas = pinned_shas(python_lines)
    for service in project.microservices:
        layers = service.path / "layers" / "requirements.txt"
        lines = read_requirements(service.path, "layers", "requirements.txt")
        yield from unpinned(root, project, layers, lines)
        yield from different_shas(root, project, layers, lines, python_shas)
        yield from missing_imports(root, project, service, layers, lines)


# --------------------------------------------------------------------------
# Lectura
# --------------------------------------------------------------------------


def is_link(path: Path) -> bool:
    """Cualquier tipo de enlace (symlink o junction de Windows)."""
    if path.is_symlink():
        return True
    literal = os.path.normcase(os.path.abspath(path))
    return literal != os.path.normcase(os.path.realpath(path))


def regular_file(base: Path, *parts: str) -> Path | None:
    """base/parts si es un archivo al que se llega sin pasar por enlaces."""
    path = base
    for part in parts:
        path = path / part
        if is_link(path):
            return None
    return path if path.is_file() else None


def read_requirements(
    base: Path, *parts: str
) -> list[tuple[int, str, str, str]]:
    """(número, línea tal cual, repo, versión) de cada lib-python-*.

    La línea va tal cual (sin el salto de línea). La versión es '' si no
    tiene '@' (también con un especificador como `==1.0`). Las comentadas no
    cuentan, y un archivo que no existe o es un enlace no tiene líneas.
    """
    path = regular_file(base, *parts)
    if path is None:
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    found = []
    for number, line in enumerate(text.splitlines(), start=1):
        matches = list(LIBRARY.finditer(COMMENT.sub("", line)))
        if matches:
            # Con `nombre @ url`, la que manda es la de la URL (la última).
            last = matches[-1]
            found.append((number, line, last["repo"], last["ref"] or ""))
    return found


def pinned_shas(lines: list[tuple[int, str, str, str]]) -> dict[str, set[str]]:
    """Repo -> SHAs con los que está fijado."""
    shas: dict[str, set[str]] = {}
    for _, _, repo, ref in lines:
        if is_sha(ref):
            shas.setdefault(repo, set()).add(ref.lower())
    return shas


def is_sha(ref: str) -> bool:
    """Un SHA de git, completo o abreviado (7 caracteres o más)."""
    return SHA.fullmatch(ref) is not None


def same_commit(sha: str, other: str) -> bool:
    """Dos SHAs del mismo commit, aunque uno esté abreviado."""
    return sha.startswith(other) or other.startswith(sha)


def relative(root: Path, path: Path) -> str:
    """Ruta relativa a la raíz del repo, con '/'."""
    return path.relative_to(root).as_posix()


# --------------------------------------------------------------------------
# Reglas
# --------------------------------------------------------------------------


def unpinned(
    root: Path,
    project: Project,
    path: Path,
    lines: list[tuple[int, str, str, str]],
) -> Iterator[Finding]:
    """D1: una lib-python-* sin @<sha>."""
    for number, line, repo, ref in lines:
        if is_sha(ref):
            continue
        version = f"con @{ref}" if ref else "sin @<sha>"
        yield Finding(
            category=CATEGORY,
            rule="D1",
            points=SEVERITY["importante"],
            project=project.name,
            path=relative(root, path),
            message=f"{repo} está {version} (línea {number}: {line})",
            why=WHY_PIN,
            how=HOW_PIN,
        )


def different_shas(
    root: Path,
    project: Project,
    layers: Path,
    lines: list[tuple[int, str, str, str]],
    python_shas: dict[str, set[str]],
) -> Iterator[Finding]:
    """D2: la librería tiene otro SHA en python/requirements.txt."""
    python_reqs = project.path / "python" / "requirements.txt"
    for number, _, repo, ref in lines:
        sha = ref.lower()
        others = python_shas.get(repo)
        if not is_sha(sha) or not others:
            continue
        if any(same_commit(sha, other) for other in others):
            continue
        yield Finding(
            category=CATEGORY,
            rule="D2",
            points=SEVERITY["menor"],
            project=project.name,
            path=relative(root, layers),
            message=(
                f"{repo} está en @{ref} (línea {number}) y en "
                f"{relative(root, python_reqs)} en "
                + ", ".join(f"@{other}" for other in sorted(others))
            ),
            why=WHY_SAME_SHA,
            how=HOW_SAME_SHA,
        )


def missing_imports(
    root: Path,
    project: Project,
    service: Microservice,
    layers: Path,
    lines: list[tuple[int, str, str, str]],
) -> Iterator[Finding]:
    """D3: el código importa una librería que no está en layers/."""
    present = {repo for _, _, repo, _ in lines}
    importers: dict[str, list[str]] = {}
    for source in python_files(service.path / "src"):
        for repo in sorted(imported_repos(source)):
            if repo not in present:
                where = relative(service.path, source)
                importers.setdefault(repo, []).append(where)
    for repo in sorted(importers):
        yield Finding(
            category=CATEGORY,
            rule="D3",
            points=SEVERITY["importante"],
            project=project.name,
            path=relative(root, layers),
            message=(
                f"{', '.join(importers[repo])} importa {repo}, pero no está "
                f"en layers/requirements.txt de {service.name}"
            ),
            why=WHY_IMPORT,
            how=HOW_IMPORT,
        )


def python_files(folder: Path) -> list[Path]:
    """Los .py de la carpeta, sin .venv ni cachés y sin atravesar enlaces."""
    if is_link(folder):
        return []
    return list(iter_files(folder, (".py",)))


def imported_repos(source: Path) -> set[str]:
    """Repos de las librerías Melonn que importa un archivo.

    Un archivo que no se puede leer o no parsea no cuenta (lo marca calidad
    de código).
    """
    try:
        tree = ast.parse(source.read_bytes(), filename=str(source))
    except (OSError, SyntaxError, ValueError):
        return set()
    repos = set()
    for module in imported_modules(tree):
        repo = repo_for(module)
        if repo is not None:
            repos.add(repo)
    return repos


def imported_modules(tree: ast.AST) -> Iterator[str]:
    """Cada módulo importado, absoluto (con `from x import y` da x y x.y)."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            base = node.module or ""
            yield base
            yield from (f"{base}.{alias.name}" for alias in node.names)


def repo_for(module: str) -> str | None:
    """El repo de una librería Melonn, o None si no es una de ellas."""
    parts = module.split(".")
    key = ".".join(parts[:2] if parts[0] == "we_are_melonn" else parts[:1])
    return IMPORT_TO_REPO.get(key)
