"""Reglas de estructura: lo que tiene que existir y dónde.

| Regla | Qué revisa                                              | Arreglo |
|-------|---------------------------------------------------------|---------|
| E1    | El proyecto tiene deployment-scripts/, iac/ y python/   | No      |
| E2    | El microservicio tiene events/, layers/requirements.txt,| No      |
|       | src/handler.py y src/service/                           |         |
| E3    | Existe events/<microservicio>.json                      | Sí      |
| E4    | launch.json tiene una entrada por microservicio, y      | Sí      |
|       | ninguna de un microservicio que no existe               |         |
| E5    | El handler no busca el evento en ../../events           | Sí      |
| E6    | iac/ no tiene un repo git anidado (iac/.git)            | No      |
| E7    | El stack de CDK no se llama IacStack                    | No      |
| E8    | Los nombres cumplen las reglas de seedflow              | No      |

run() solo lee. Los arreglos (FIXES) escriben solo el archivo de su arreglo,
nunca a través de enlaces, y no hacen nada si ya está arreglado.
"""

from __future__ import annotations

import os
import re
import stat
from collections.abc import Callable
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import seedflow
from checks import SEVERITY
from checks import CheckResult
from checks import Context
from checks import Finding
from checks import Microservice
from checks import Project


CATEGORY = "estructura"
QUICK = True

PROJECT_FOLDERS = ("deployment-scripts", "iac", "python")
# (ruta dentro del microservicio, si tiene que ser carpeta)
MICROSERVICE_PARTS = (
    ("events", True),
    ("layers/requirements.txt", False),
    ("src/handler.py", False),
    ("src/service", True),
)
BROKEN_EVENTS = b"../../events"
FIXED_EVENTS = b"../events"
IAC_STACK = re.compile(rb"\bIacStack\b")
LAUNCH_PROGRAM = re.compile(
    r"\$\{workspaceFolder\}/("
    + "|".join(re.escape(t) for t in seedflow.SERVICE_TYPES)
    + r")/([^/]+)/src/handler\.py"
)
STANDARD = "references/estructura.md del plugin"

# regla -> (gravedad, por qué importa)
RULES = {
    "E1": (
        "importante",
        "Cada proyecto tiene las mismas tres carpetas: el pipeline de "
        "despliegue, la infraestructura y el código. Si falta una, el "
        "proyecto no se puede desplegar igual que los demás.",
    ),
    "E2": (
        "importante",
        "Todos los microservicios tienen la misma forma: así cualquiera sabe "
        "dónde está el punto de entrada, la lógica, las dependencias de la "
        "Lambda y el evento para probarlo.",
    ),
    "E3": (
        "menor",
        "Sin evento de prueba no se puede correr el handler en local ni "
        "desde VS Code.",
    ),
    "E4": (
        "menor",
        "launch.json es lo que usa VS Code para depurar cada microservicio: "
        "sin la entrada no se puede depurar, y una entrada huérfana falla al "
        "usarla.",
    ),
    "E5": (
        "importante",
        "Es la ruta rota del CLI anterior: busca el evento un nivel por "
        "encima de la carpeta del microservicio y el handler no corre en "
        "local.",
    ),
    "E6": (
        "importante",
        "Un repo git dentro del repo hace que git ignore iac/ (o lo trate "
        "como submódulo): los cambios de infraestructura no quedan en el "
        "historial del repo.",
    ),
    "E7": (
        "menor",
        "Todos los proyectos creados con el CLI anterior tienen el stack "
        "IacStack; dos de ellos chocan al desplegarse en la misma cuenta y "
        "región.",
    ),
    "E8": (
        "menor",
        "seedflow no opera sobre nombres que no cumplen sus reglas (no los "
        "puede crear, borrar ni arreglar), y pueden fallar en Windows o en "
        "AWS.",
    ),
}


# --------------------------------------------------------------------------
# Reglas
# --------------------------------------------------------------------------


def run(ctx: Context) -> CheckResult:
    """Hallazgos de estructura de cada proyecto. Solo lee."""
    findings: list[Finding] = []
    for project in ctx.projects:
        findings.extend(project_findings(ctx.root, project))
    return CheckResult(findings)


def project_findings(root: Path, project: Project) -> Iterator[Finding]:
    """Todas las reglas sobre un proyecto y sus microservicios."""
    yield from name_findings(root, project)
    yield from folder_findings(root, project)
    yield from iac_findings(root, project)
    for microservice in project.microservices:
        yield from microservice_findings(root, project, microservice)
    yield from launch_findings(root, project)


def found(
    root: Path,
    project: Project,
    rule: str,
    path: Path,
    message: str,
    how: str,
    fix_id: str | None = None,
) -> Finding:
    """Un hallazgo de la regla, con su gravedad y su porqué."""
    severity, why = RULES[rule]
    return Finding(
        category=CATEGORY,
        rule=rule,
        points=SEVERITY[severity],
        project=project.name,
        path=path.relative_to(root).as_posix(),
        message=message,
        why=why,
        how=how,
        fix_id=fix_id,
    )


def name_problem(value: str, what: str) -> str | None:
    """Por qué el nombre no cumple las reglas de seedflow, o None."""
    try:
        seedflow.validate_name(value, what)
    except seedflow.SeedError as error:
        return str(error)
    return None


def fix_id_for(
    rule: str, project: str, service_type: str, name: str
) -> str | None:
    """Id del arreglo; None si un nombre no deja que seedflow lo arregle."""
    if name_problem(project, "proyecto") or name_problem(name, "microservicio"):
        return None
    return f"{rule}:{project}/{service_type}/{name}"


def name_findings(root: Path, project: Project) -> Iterator[Finding]:
    """E8: nombres de proyecto y de microservicios."""
    how = "Renombra la carpeta (y lo que la nombre en iac/ y launch.json)."
    problem = name_problem(project.name, "proyecto")
    if problem:
        yield found(root, project, "E8", project.path, problem, how)
    for microservice in project.microservices:
        problem = name_problem(microservice.name, "microservicio")
        if problem:
            yield found(root, project, "E8", microservice.path, problem, how)


def folder_findings(root: Path, project: Project) -> Iterator[Finding]:
    """E1: las tres carpetas del proyecto."""
    for folder in PROJECT_FOLDERS:
        path = project.path / folder
        if not path.is_dir():
            yield found(
                root,
                project,
                "E1",
                path,
                f"Al proyecto le falta la carpeta {folder}/.",
                f"Crea {folder}/ como en un proyecto nuevo de seedflow "
                f"(ver {STANDARD}).",
            )


def iac_findings(root: Path, project: Project) -> Iterator[Finding]:
    """E6 y E7: repo git anidado y stack IacStack."""
    iac = project.path / "iac"
    nested = iac / ".git"
    if os.path.lexists(nested):
        yield found(
            root,
            project,
            "E6",
            nested,
            "iac/ tiene su propio repo git (iac/.git).",
            "Muévelo a un respaldo fuera del repo, o bórralo si no necesitas "
            "ese historial; seedflow no lo borra solo porque se perdería.",
        )
    stack = iac_stack_file(iac)
    if stack is not None:
        yield found(
            root,
            project,
            "E7",
            stack,
            "El stack de CDK se llama IacStack (el nombre genérico de cdk "
            "init).",
            f"Renómbralo con el nombre del proyecto, p. ej. "
            f"{camel(project.name)}Stack, en iac/bin y iac/lib (ojo: "
            "cambiar el id del stack crea uno nuevo al desplegar).",
        )


def camel(name: str) -> str:
    """stock-forecast -> StockForecast."""
    return "".join(p[:1].upper() + p[1:] for p in re.split(r"[-_]", name))


def iac_stack_file(iac: Path) -> Path | None:
    """El primer archivo del stack (bin/*.ts, lib/*-stack.ts) con IacStack."""
    candidates = sorted([*iac.glob("bin/*.ts"), *iac.glob("lib/*-stack.ts")])
    for path in candidates:
        if IAC_STACK.search(read(path)):
            return path
    return None


def read(path: Path) -> bytes:
    """Contenido de un archivo; vacío si no es un archivo o no se puede leer."""
    try:
        return path.read_bytes() if path.is_file() else b""
    except OSError:
        return b""


def microservice_findings(
    root: Path, project: Project, microservice: Microservice
) -> Iterator[Finding]:
    """E2, E3 y E5: lo que tiene que tener cada microservicio."""
    for part, is_folder in MICROSERVICE_PARTS:
        path = microservice.path / part
        if not (path.is_dir() if is_folder else path.is_file()):
            kind = "la carpeta" if is_folder else "el archivo"
            yield found(
                root,
                project,
                "E2",
                path,
                f"Al microservicio {microservice.name} le falta {kind} {part}.",
                f"Créalo como en un microservicio nuevo de seedflow (ver "
                f"{STANDARD}).",
            )
    events = microservice.path / "events"
    event = events / f"{microservice.name}.json"
    if events.is_dir() and not event.exists():
        yield found(
            root,
            project,
            "E3",
            event,
            f"Falta el evento de prueba events/{microservice.name}.json.",
            "Crea el archivo con {} y completa el evento que recibe la Lambda.",
            fix_id_for(
                "E3", project.name, microservice.service_type, microservice.name
            ),
        )
    handler = microservice.path / "src" / "handler.py"
    if BROKEN_EVENTS in read(handler):
        yield found(
            root,
            project,
            "E5",
            handler,
            "El handler busca el evento en ../../events.",
            "Cambia ../../events por ../events en src/handler.py.",
            fix_id_for(
                "E5", project.name, microservice.service_type, microservice.name
            ),
        )


def launch_entries(data: dict) -> set[tuple[str, str]]:
    """(tipo, microservicio) de cada entrada de launch.json de seedflow."""
    entries = set()
    for configuration in data.get("configurations", []):
        program = configuration.get("program")
        if not isinstance(program, str):
            continue
        match = LAUNCH_PROGRAM.fullmatch(program)
        if match:
            entries.add((match.group(1), match.group(2)))
    return entries


def launch_findings(root: Path, project: Project) -> Iterator[Finding]:
    """E4: launch.json en sincronía con los microservicios.

    Si launch.json tiene comentarios u otra forma, la regla no se evalúa en
    ese proyecto: no descuenta (las demás reglas sí).
    """
    path = project.path / "python" / ".vscode" / "launch.json"
    data = seedflow.load_launch(path)
    if data is None:
        return
    entries = launch_entries(data)
    existing = {(m.service_type, m.name) for m in project.microservices}
    for service_type, name in sorted(existing - entries):
        yield found(
            root,
            project,
            "E4",
            path,
            f"launch.json no tiene la entrada de {service_type}/{name}.",
            "Agrega su configuración (la misma que crea seedflow).",
            fix_id_for("E4", project.name, service_type, name),
        )
    for service_type, name in sorted(entries - existing):
        yield found(
            root,
            project,
            "E4",
            path,
            f"launch.json tiene una entrada de {service_type}/{name}, que "
            "no existe.",
            "Quita esa configuración de launch.json.",
            fix_id_for("E4", project.name, service_type, name),
        )


# --------------------------------------------------------------------------
# Arreglos
# --------------------------------------------------------------------------


@dataclass
class Target:
    """El microservicio sobre el que actúa un arreglo."""

    root: Path
    project: str
    service_type: str
    name: str
    folder: Path


def parse_fix_id(root: Path, fix_id: str) -> Target:
    """El microservicio de 'E3:proyecto/tipo/nombre'.

    Valida los nombres y que ningún tramo de la ruta sea un enlace.
    """
    parts = fix_id.partition(":")[2].split("/")
    if len(parts) != 3:
        raise seedflow.SeedError(
            f"Arreglo '{fix_id}' no válido: se espera "
            "REGLA:proyecto/tipo/microservicio."
        )
    project, service_type, name = parts
    root = Path(root).resolve()
    folder = seedflow.microservice_folder(root, project, service_type, name)
    return Target(root, project, service_type, name, folder)


def fix_event(root: Path, fix_id: str) -> list[Path]:
    """E3: crea events/<microservicio>.json con {}."""
    target = parse_fix_id(root, fix_id)
    events = seedflow.safe_path(target.folder, "events")
    if not events.is_dir():
        raise seedflow.SeedError(
            f"No existe {events}: créala a mano antes de agregar el evento."
        )
    event = seedflow.safe_path(events, f"{target.name}.json")
    if event.exists():
        return []
    with event.open("x", encoding="utf-8") as file:
        file.write("{}\n")
    return [event]


def fix_launch(root: Path, fix_id: str) -> list[Path]:
    """E4: agrega la entrada que falta o quita la huérfana."""
    target = parse_fix_id(root, fix_id)
    path = seedflow.launch_path(target.root, target.project)
    data = seedflow.load_launch(path)
    if data is None:
        raise seedflow.SeedError(
            f"{path} no tiene el formato esperado (¿tiene comentarios?); "
            "actualízalo a mano."
        )
    wanted = target.folder.is_dir()
    present = (target.service_type, target.name) in launch_entries(data)
    if present == wanted:
        return []
    seedflow.update_launch(
        target.root, target.project, target.name, target.service_type, wanted
    )
    return [path]


def fix_handler(root: Path, fix_id: str) -> list[Path]:
    """E5: cambia ../../events por ../events; el resto queda igual."""
    target = parse_fix_id(root, fix_id)
    handler = seedflow.safe_path(target.folder, "src", "handler.py")
    if not handler.is_file():
        raise seedflow.SeedError(f"No existe {handler}.")
    content = handler.read_bytes()
    if BROKEN_EVENTS not in content:
        return []
    mode = stat.S_IMODE(handler.stat().st_mode)
    seedflow.write_atomic(handler, content.replace(BROKEN_EVENTS, FIXED_EVENTS))
    os.chmod(handler, mode)
    return [handler]


FIXES: dict[str, Callable[[Path, str], list[Path]]] = {
    "E3": fix_event,
    "E4": fix_launch,
    "E5": fix_handler,
}
