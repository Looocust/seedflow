#!/usr/bin/env python3
"""seedflow: crea, elimina y califica proyectos y microservicios Melonn.

Es el motor determinista del plugin. No hace preguntas: recibe todo por
argumentos. Las preguntas las hacen las skills antes de llamarlo, y una persona
también puede usarlo directo desde la terminal.

Uso (siempre desde la carpeta raíz del repo, por ejemplo data-hub):

    seedflow.py status [--json]
    seedflow.py create-project NOMBRE --service-type TIPO [--skip-cdk]
    seedflow.py create-microservice NOMBRE --project P --service-type TIPO
                                    [--database]
    seedflow.py delete-project NOMBRE (--dry-run | --yes)
    seedflow.py delete-microservice NOMBRE --project P --service-type TIPO
                                    (--dry-run | --yes)
    seedflow.py check [--quick] [--json]
    seedflow.py fix --list
    seedflow.py fix FIX_ID [FIX_ID ...]

check califica de 0 a 100 qué tan organizado está el repo. Las reglas viven
en el paquete checks/ (un módulo por categoría, que check descubre solo);
este script arma el contexto, las corre y muestra la nota. --quick deja fuera
las reglas lentas (calidad de código) e imprime una sola línea.

Garantías:

- Nunca opera fuera de <raíz>/projects/ ni a través de enlaces simbólicos.
- Nunca sobrescribe: si lo que va a crear ya existe, se detiene.
- Si una creación falla a mitad de camino, deja la raíz como estaba; si no
  puede, lo dice y lista lo que quedó.
- check solo lee: nunca escribe en el repo.

No cubre dos comandos de seedflow corriendo a la vez sobre el mismo proyecto,
ni otro proceso que cambie carpetas por enlaces mientras el comando corre
(las rutas se verifican antes de cada operación, no durante).

Solo usa la librería estándar de Python (3.8+).
"""

from __future__ import annotations

import argparse
import contextlib
import importlib
import json
import os
import pkgutil
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING
from typing import Any


if TYPE_CHECKING:
    import checks


SCRIPTS = Path(__file__).resolve().parent
TEMPLATES = SCRIPTS.parent / "templates"
SERVICE_TYPES = ("internal-services", "consumable-services")
NAME_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")
WINDOWS_RESERVED = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}
NAME_PLACEHOLDER = "__name__"
# Basura que puede aparecer en templates/ si alguien corre herramientas ahí.
IGNORED_IN_TEMPLATES = {
    ".DS_Store",
    "__pycache__",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
}
REVIEW_SKILL = "/seedflow:revisar"
GENERIC_LAUNCH_CONFIG = {
    "name": "Python: Current File",
    "type": "debugpy",
    "request": "launch",
    "program": "${file}",
    "console": "integratedTerminal",
    "justMyCode": True,
}


class SeedError(Exception):
    """Error esperado: se muestra al usuario sin traceback."""


# --------------------------------------------------------------------------
# Utilidades
# --------------------------------------------------------------------------


def say(message: str) -> None:
    """Imprime una línea de progreso."""
    print(message, flush=True)


def validate_name(value: str, what: str) -> str:
    """Valida un nombre de proyecto o microservicio.

    Solo letras, números, guion y guion bajo, sin empezar por guion. Así un
    nombre nunca puede salirse de la carpeta projects/ (nada de '..' ni '/').
    """
    if not NAME_PATTERN.fullmatch(value):
        raise SeedError(
            f"El nombre de {what} '{value}' no es válido. Usa solo letras, "
            "números, '-' y '_', sin empezar por '-' ni '_' (máx. 64)."
        )
    if value.lower() in WINDOWS_RESERVED:
        raise SeedError(
            f"'{value}' es un nombre reservado de Windows. Usa otro nombre."
        )
    return value


def validate_service_type(service_type: str) -> str:
    """Valida el tipo de carpeta de servicios."""
    if service_type not in SERVICE_TYPES:
        raise SeedError(
            f"Tipo de servicio '{service_type}' no válido. Opciones: "
            + ", ".join(SERVICE_TYPES)
        )
    return service_type


def safe_path(root: Path, *parts: str) -> Path:
    """Arma root/parts verificando que ningún componente sea un enlace.

    Los nombres ya validados no pueden contener '..' ni separadores, así que
    sin enlaces simbólicos la ruta queda literalmente dentro de root.
    """
    path = root
    for part in parts:
        path = path / part
        if is_link(path):
            raise SeedError(
                f"{path} es un enlace simbólico o una junction; seedflow no "
                "crea ni borra nada a través de enlaces."
            )
    return path


def is_link(path: Path) -> bool:
    """Indica si path es cualquier tipo de enlace (symlink, junction…).

    root ya está resuelta, así que una ruta sin enlaces se resuelve a sí
    misma. Comparar con realpath detecta también las junctions de Windows,
    que is_symlink() no ve en Python < 3.12.
    """
    if path.is_symlink():
        return True
    if not os.path.lexists(path):
        return False
    literal = os.path.normcase(os.path.abspath(path))
    resolved = os.path.normcase(os.path.realpath(path))
    return literal != resolved


def find_tool(name: str) -> str | None:
    """Ruta completa de un ejecutable (en Windows encuentra cdk.cmd)."""
    return shutil.which(name)


def tool_version(name: str) -> str | None:
    """Versión de una herramienta, o None si no está instalada."""
    path = find_tool(name)
    if not path:
        return None
    try:
        result = subprocess.run(
            [path, "--version"],
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        )
    except (subprocess.SubprocessError, OSError):
        return "instalado (no respondió a --version)"
    lines = (result.stdout or result.stderr).strip().splitlines()
    return lines[0] if lines else "instalado"


def copy_template(source: Path, target: Path, name: str) -> list[Path]:
    """Copia una carpeta de plantillas reemplazando __name__ en los nombres."""
    created = []
    for item in sorted(source.rglob("*")):
        relative = item.relative_to(source)
        if IGNORED_IN_TEMPLATES.intersection(relative.parts):
            continue
        destination = target / Path(
            *[part.replace(NAME_PLACEHOLDER, name) for part in relative.parts]
        )
        if item.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(item, destination)
        if destination.suffix == ".sh":
            destination.chmod(0o755)
        created.append(destination)
    return created


def remove_tree(path: Path) -> None:
    """Borra una carpeta completa (punto único, para poder simular fallas)."""
    shutil.rmtree(path, ignore_errors=True)


def write_atomic(path: Path, content: str | bytes) -> None:
    """Escribe un archivo de una vez: o queda el nuevo o queda el anterior.

    El temporal se crea con nombre único y en exclusiva (nunca reutiliza ni
    atraviesa un archivo existente), y se borra si algo falla.
    """
    descriptor, temporary = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        data = content.encode("utf-8") if isinstance(content, str) else content
        with os.fdopen(descriptor, "wb") as file:
            file.write(data)
        os.replace(temporary, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(temporary)
        raise


def projects_folder(root: Path) -> Path:
    """Carpeta projects/ dentro de la raíz."""
    return safe_path(root, "projects")


def project_folder(root: Path, project: str) -> Path:
    """Carpeta de un proyecto, validando el nombre."""
    return safe_path(root, "projects", validate_name(project, "proyecto"))


def services_folder(root: Path, project: str, service_type: str) -> Path:
    """Carpeta internal-services o consumable-services de un proyecto."""
    return safe_path(
        root,
        "projects",
        validate_name(project, "proyecto"),
        "python",
        validate_service_type(service_type),
    )


def microservice_folder(
    root: Path, project: str, service_type: str, name: str
) -> Path:
    """Carpeta de un microservicio."""
    return safe_path(
        services_folder(root, project, service_type),
        validate_name(name, "microservicio"),
    )


def git_toplevel(root: Path) -> str | None:
    """Nombre de la carpeta raíz del repo git, si root está dentro de uno."""
    git = find_tool("git")
    if not git:
        return None
    try:
        result = subprocess.run(
            [git, "rev-parse", "--show-toplevel"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
    except (subprocess.SubprocessError, OSError):
        return None
    return Path(result.stdout.strip()).name


def count_files(folder: Path) -> int:
    """Cantidad de archivos dentro de una carpeta, sin contar node_modules."""
    return sum(
        1
        for item in folder.rglob("*")
        if item.is_file() and "node_modules" not in item.parts
    )


class Rollback:
    """Registra lo que crea un comando para deshacerlo si algo falla.

    Solo se registran carpetas que este comando creó (después de crearlas con
    éxito) y archivos cuyo contenido previo se guardó antes de tocarlos.
    """

    def __init__(self) -> None:
        # (carpeta, si se borra con todo su contenido)
        self._dirs: list[tuple[Path, bool]] = []
        self._files: list[tuple[Path, bytes | None]] = []

    def created(self, path: Path, recursive: bool = True) -> None:
        """Marca una carpeta creada por este comando.

        recursive=False es para contenedores (projects/, la carpeta de
        servicios, .vscode/): solo se borran si quedan vacíos, porque otro
        comando pudo haber dejado algo adentro.
        """
        self._dirs.append((path, recursive))

    def new_dir(self, path: Path) -> None:
        """Marca un contenedor que quizá se cree más adelante."""
        if not path.exists():
            self._dirs.append((path, False))

    def file(self, path: Path) -> None:
        """Guarda el contenido actual de un archivo antes de modificarlo.

        Si en esa ruta hay una carpeta, no se registra: nadie la va a
        modificar (update_launch avisa y no la toca).
        """
        if path.is_dir():
            return
        self._files.append((path, path.read_bytes() if path.exists() else None))

    def undo(self) -> list[Path]:
        """Deshace todo y devuelve lo que no se pudo dejar como estaba."""
        leftovers = []
        for path, content in reversed(self._files):
            current = path.read_bytes() if path.is_file() else None
            if current == content:
                continue  # no cambió: reescribirlo solo agrega riesgo
            try:
                if content is None:
                    path.unlink()
                else:
                    write_atomic(path, content)
            except OSError:
                leftovers.append(path)
        for path, recursive in reversed(self._dirs):
            if not path.exists():
                continue
            if recursive:
                remove_tree(path)
                if path.exists():
                    leftovers.append(path)
            elif not any(path.iterdir()):
                try:
                    path.rmdir()
                except OSError:
                    leftovers.append(path)
            # Un contenedor con contenido ajeno se deja como está.
        return leftovers

    def report(self, what: str) -> None:
        """Deshace y le dice al usuario si quedó algo."""
        leftovers = self.undo()
        if not leftovers:
            say(f"↩️  Se deshizo la creación {what}.")
            return
        say(f"⚠️  No pude deshacer todo lo que creé {what}. Revisa:")
        for path in leftovers:
            say(f"   - {path}")


# --------------------------------------------------------------------------
# launch.json de VS Code
# --------------------------------------------------------------------------


def launch_path(root: Path, project: str) -> Path:
    """Ruta del launch.json del proyecto."""
    return safe_path(
        root,
        "projects",
        validate_name(project, "proyecto"),
        "python",
        ".vscode",
        "launch.json",
    )


def microservice_launch_config(name: str, service_type: str) -> dict:
    """Configuración de depuración de un microservicio."""
    return {
        "name": name,
        "type": "debugpy",
        "request": "launch",
        "args": [name],
        "program": (
            f"${{workspaceFolder}}/{service_type}/{name}/src/handler.py"
        ),
        "envFile": "${workspaceFolder}/.env",
        "stopOnEntry": True,
        "justMyCode": False,
    }


def initial_launch() -> dict:
    """launch.json de un proyecto nuevo."""
    return {"version": "0.2.0", "configurations": [GENERIC_LAUNCH_CONFIG]}


def load_launch(path: Path) -> dict | None:
    """Contenido de launch.json, o None si no tiene la forma esperada."""
    if not path.exists():
        return initial_launch()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        return None
    if not isinstance(data, dict):
        return None
    configurations = data.get("configurations", [])
    if not isinstance(configurations, list):
        return None
    if not all(isinstance(c, dict) for c in configurations):
        return None
    return data


def update_launch(
    root: Path, project: str, name: str, service_type: str, add: bool
) -> None:
    """Agrega o quita la configuración de un microservicio en launch.json.

    Solo toca la configuración de ese microservicio; el resto del archivo
    (otras configuraciones, compounds, version) queda igual.
    """
    path = launch_path(root, project)
    if not add and not path.exists():
        return  # no hay nada que quitar
    data = load_launch(path)
    if data is None:
        say(
            "⚠️  python/.vscode/launch.json no tiene el formato esperado "
            "(¿tiene comentarios?). No lo toqué; actualízalo a mano."
        )
        return
    program = microservice_launch_config(name, service_type)["program"]
    configurations = [
        c for c in data.get("configurations", []) if c.get("program") != program
    ]
    if add:
        config = microservice_launch_config(name, service_type)
        if GENERIC_LAUNCH_CONFIG in configurations:
            index = configurations.index(GENERIC_LAUNCH_CONFIG)
            configurations.insert(index, config)
        else:
            configurations.append(config)
    data["configurations"] = configurations
    path.parent.mkdir(parents=True, exist_ok=True)
    write_atomic(path, json.dumps(data, indent=4) + "\n")
    action = "agregada a" if add else "quitada de"
    say(f"✅ Configuración '{name}' {action} python/.vscode/launch.json")


# --------------------------------------------------------------------------
# Comandos
# --------------------------------------------------------------------------


def collect_projects(root: Path) -> list[dict[str, Any]]:
    """Proyectos existentes con sus carpetas de servicios y microservicios."""
    folder = root / "projects"
    if not folder.is_dir():
        return []
    projects = []
    for project in sorted(p for p in folder.iterdir() if p.is_dir()):
        services = {}
        for service_type in SERVICE_TYPES:
            service_folder = project / "python" / service_type
            if service_folder.is_dir():
                services[service_type] = sorted(
                    m.name for m in service_folder.iterdir() if m.is_dir()
                )
        projects.append({"name": project.name, "services": services})
    return projects


def cmd_status(args: argparse.Namespace) -> None:
    """Muestra dónde estás parado, qué proyectos hay y qué herramientas."""
    root = Path(args.root).resolve()
    status: dict[str, Any] = {
        "root": str(root),
        "git_repo": git_toplevel(root),
        "has_projects_folder": (root / "projects").is_dir(),
        "projects": collect_projects(root),
        "tools": {
            name: tool_version(name) for name in ("cdk", "node", "npm", "git")
        },
    }
    if args.json:
        print(json.dumps(status, indent=2, ensure_ascii=False))
        return
    say(f"📍 Raíz: {status['root']}")
    say(f"   Repo git: {status['git_repo'] or '(no es un repo git)'}")
    if not status["has_projects_folder"]:
        say("   No hay carpeta projects/ aquí todavía.")
    for project in status["projects"]:
        say(f"📁 {project['name']}")
        for service_type, microservices in project["services"].items():
            listed = ", ".join(microservices) or "(vacío)"
            say(f"   - {service_type}: {listed}")
    for name, version in status["tools"].items():
        say(f"🔧 {name}: {version or 'NO instalado'}")


def run_tool(command: list[str], cwd: Path) -> None:
    """Corre una herramienta externa; si falla, error con su salida."""
    result = subprocess.run(
        command, cwd=cwd, capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()[-2000:]
        raise SeedError(f"Falló '{' '.join(command[1:])}':\n{detail}")


def init_cdk(iac: Path, name: str) -> None:
    """Inicializa AWS CDK en iac/ con el nombre del proyecto.

    cdk init toma los nombres de la carpeta donde corre: dentro de iac/ todos
    los proyectos quedarían con el stack 'IacStack' y chocarían al desplegar
    en la misma cuenta. Por eso corre en una carpeta temporal llamada como el
    proyecto (dentro del proyecto, así el rollback la cubre) y el resultado se
    mueve a iac/. --generate-only evita el repo git anidado; después,
    npm install.
    """
    cdk = find_tool("cdk")
    npm = find_tool("npm")
    if not cdk or not npm:
        raise SeedError("Falta cdk o npm.")
    say("🚀 Inicializando AWS CDK (TypeScript) en iac/ ...")
    staging_parent = Path(tempfile.mkdtemp(prefix=".cdk-init-", dir=iac.parent))
    try:
        staging = staging_parent / name
        staging.mkdir()
        run_tool(
            [cdk, "init", "app", "--language=typescript", "--generate-only"],
            staging,
        )
        for item in staging.iterdir():
            shutil.move(str(item), str(iac / item.name))
    finally:
        remove_tree(staging_parent)
    run_tool([npm, "install", "--no-audit", "--no-fund"], iac)
    say("✅ AWS CDK inicializado en iac/")


def reserve_folder(
    path: Path, rollback: Rollback, what: str, container: bool = False
) -> None:
    """Crea la carpeta solo si no existe, en una sola operación."""
    try:
        path.mkdir()
    except FileExistsError as error:
        raise SeedError(f"{what} ya existe en {path}.") from error
    rollback.created(path, recursive=not container)


def cmd_create_project(args: argparse.Namespace) -> None:
    """Crea la estructura base de un proyecto."""
    root = Path(args.root).resolve()
    name = validate_name(args.name, "proyecto")
    validate_service_type(args.service_type)
    projects = projects_folder(root)
    target = project_folder(root, name)
    if target.exists():
        raise SeedError(f"El proyecto '{name}' ya existe en {target}.")
    if not args.skip_cdk and not (find_tool("cdk") and find_tool("npm")):
        raise SeedError(
            "AWS CDK o npm no están instalados. Instala Node.js y luego "
            "'npm install -g aws-cdk', o usa --skip-cdk para crear iac/ vacía."
        )

    say(f"🚀 Creando el proyecto '{name}' en {target}")
    rollback = Rollback()
    try:
        if not projects.exists():
            reserve_folder(
                projects, rollback, "La carpeta projects/", container=True
            )
        reserve_folder(target, rollback, f"El proyecto '{name}'")
        copy_template(TEMPLATES / "project", target, name)
        services = target / "python" / args.service_type
        services.mkdir(parents=True)
        # Sin un archivo, git no guarda la carpeta mientras siga vacía.
        (services / ".gitkeep").touch()
        (target / "iac").mkdir(parents=True, exist_ok=True)
        write_atomic(
            target / "python" / ".vscode" / "launch.json",
            json.dumps(initial_launch(), indent=4) + "\n",
        )
        say("✅ deployment-scripts/ (build, install, pre_build, post_build)")
        say(
            "✅ python/ (.env.example, pyproject.toml, requirements.txt, "
            ".vscode)"
        )
        say(f"✅ python/{args.service_type}/")
        if args.skip_cdk:
            say("⏭️  iac/ creada vacía (--skip-cdk)")
        else:
            init_cdk(target / "iac", name)
    except BaseException:
        rollback.report("del proyecto")
        raise
    say(f"🎉 Proyecto '{name}' creado.")


def cmd_create_microservice(args: argparse.Namespace) -> None:
    """Crea un microservicio dentro de un proyecto existente."""
    root = Path(args.root).resolve()
    project = project_folder(root, args.project)
    services = services_folder(root, args.project, args.service_type)
    target = microservice_folder(
        root, args.project, args.service_type, args.name
    )
    launch = launch_path(root, args.project)
    if not (project / "python").is_dir():
        raise SeedError(
            f"No existe el proyecto '{args.project}' (o no tiene python/) en "
            f"{root / 'projects'}. Créalo primero."
        )
    if target.exists():
        raise SeedError(
            f"El microservicio '{args.name}' ya existe en {target}."
        )

    rollback = Rollback()
    try:
        if not services.exists():
            reserve_folder(
                services,
                rollback,
                f"python/{args.service_type}/",
                container=True,
            )
            say(f"✅ python/{args.service_type}/ no existía; la creé.")
        reserve_folder(target, rollback, f"El microservicio '{args.name}'")
        copy_template(TEMPLATES / "microservice", target, args.name)
        say(f"✅ {args.service_type}/{args.name}/ con events/, layers/ y src/")
        if args.database:
            copy_template(TEMPLATES / "database", target / "src", args.name)
            say("✅ src/database/")
        rollback.new_dir(launch.parent)
        rollback.file(launch)
        update_launch(
            root, args.project, args.name, args.service_type, add=True
        )
    except BaseException:
        rollback.report("del microservicio")
        raise
    say(f"🎉 Microservicio '{args.name}' creado en {target}")


def confirm_deletion(
    args: argparse.Namespace, target: Path, extra: str = ""
) -> bool:
    """Con --dry-run describe el borrado; sin --yes lo rechaza.

    Devuelve True si hay que borrar.
    """
    files = count_files(target)
    if args.dry_run:
        say(f"🔎 Se borraría: {target} ({files} archivos){extra}")
        say("   No borré nada (--dry-run).")
        return False
    if not args.yes:
        raise SeedError(
            f"Borrar {target} es irreversible. Revisa con --dry-run y repite "
            "el comando con --yes después de confirmar."
        )
    return True


def cmd_delete_project(args: argparse.Namespace) -> None:
    """Elimina un proyecto completo."""
    root = Path(args.root).resolve()
    target = project_folder(root, args.name)
    if not target.is_dir():
        raise SeedError(f"No existe el proyecto '{args.name}' en {target}.")
    if not confirm_deletion(args, target):
        return
    files = count_files(target)
    shutil.rmtree(target)
    say(f"🗑️  Proyecto '{args.name}' eliminado ({files} archivos).")


def existing_name(folder: Path, name: str) -> str:
    """Nombre real de la carpeta, si el sistema ignora mayúsculas.

    En macOS y Windows, 'orders' encuentra la carpeta 'Orders'; para quitar
    su configuración de launch.json hay que usar el nombre real.
    """
    if not (folder / name).exists():
        return name
    entries = [entry.name for entry in folder.iterdir()]
    if name in entries:
        return name
    matches = [e for e in entries if e.casefold() == name.casefold()]
    return matches[0] if len(matches) == 1 else name


def cmd_delete_microservice(args: argparse.Namespace) -> None:
    """Elimina un microservicio de un proyecto.

    Primero actualiza launch.json (reversible) y después borra la carpeta
    (irreversible); si el borrado falla, restaura launch.json.
    """
    root = Path(args.root).resolve()
    services = services_folder(root, args.project, args.service_type)
    name = existing_name(services, validate_name(args.name, "microservicio"))
    target = microservice_folder(root, args.project, args.service_type, name)
    launch = launch_path(root, args.project)
    if not target.is_dir():
        raise SeedError(
            f"No existe el microservicio '{args.name}' en "
            f"{args.service_type} del proyecto '{args.project}'."
        )
    extra = ", y su configuración en python/.vscode/launch.json"
    if not confirm_deletion(args, target, extra):
        return
    files = count_files(target)
    rollback = Rollback()
    rollback.file(launch)
    update_launch(root, args.project, name, args.service_type, add=False)
    try:
        shutil.rmtree(target)
    except BaseException:
        leftovers = rollback.undo()
        say(f"⚠️  El borrado falló: {target} puede haber quedado incompleto.")
        if leftovers:
            say("   Tampoco pude restaurar python/.vscode/launch.json.")
        else:
            say("   python/.vscode/launch.json quedó como estaba.")
        raise
    say(f"🗑️  Microservicio '{name}' eliminado ({files} archivos).")


# --------------------------------------------------------------------------
# Calificación (check)
# --------------------------------------------------------------------------


def load_checks() -> ModuleType:
    """El paquete checks/ que está junto a este script."""
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    return importlib.import_module("checks")


def discover_rules(package: ModuleType | None = None) -> list[ModuleType]:
    """Los módulos de reglas del paquete checks/, en orden alfabético.

    Cada módulo expone CATEGORY, QUICK y run(ctx). Los que empiezan por '_'
    son ayudas internas y no se corren.
    """
    if package is None:
        package = load_checks()
    modules = []
    found = pkgutil.iter_modules(package.__path__)
    for info in sorted(found, key=lambda info: info.name):
        if info.name.startswith("_"):
            continue
        module = importlib.import_module(f"{package.__name__}.{info.name}")
        validate_rule_module(module, package.CATEGORIES)
        modules.append(module)
    return modules


def validate_rule_module(
    module: ModuleType, categories: tuple[str, ...]
) -> None:
    """Un módulo de reglas que no cumple el contrato es un error, no un 100."""
    problems = []
    if getattr(module, "CATEGORY", None) not in categories:
        problems.append(f"CATEGORY debe ser una de {', '.join(categories)}")
    if not isinstance(getattr(module, "QUICK", None), bool):
        problems.append("QUICK debe ser True o False")
    if not callable(getattr(module, "run", None)):
        problems.append("falta la función run(ctx)")
    if problems:
        raise SeedError(
            f"El módulo de reglas {module.__name__} no cumple el contrato: "
            + "; ".join(problems)
            + "."
        )


def git_tracked(root: Path) -> set[str] | None:
    """Archivos que git sigue bajo root (relativos a root), o None sin git."""
    git = find_tool("git")
    if not git:
        return None
    try:
        result = subprocess.run(
            [git, "ls-files", "-z"],
            cwd=root,
            capture_output=True,
            check=True,
            timeout=30,
        )
    except (subprocess.SubprocessError, OSError):
        return None
    return {os.fsdecode(p) for p in result.stdout.split(b"\0") if p}


def plain_folders(folder: Path) -> list[Path]:
    """Subcarpetas ordenadas, sin enlaces: calificar no los atraviesa."""
    if not folder.is_dir() or is_link(folder):
        return []
    return sorted(
        item for item in folder.iterdir() if item.is_dir() and not is_link(item)
    )


def build_context(root: Path, quick: bool) -> checks.Context:
    """Proyectos, microservicios y archivos en git, para las reglas."""
    rules = load_checks()
    projects = []
    for folder in plain_folders(projects_folder(root)):
        python = folder / "python"
        microservices = [
            rules.Microservice(item.name, service_type, item)
            for service_type in SERVICE_TYPES
            if not is_link(python)
            for item in plain_folders(python / service_type)
        ]
        projects.append(rules.Project(folder.name, folder, microservices))
    return rules.Context(root, projects, git_tracked(root), quick)


def grade(score: int | None) -> str:
    """'78/100 🟡', o 'sin nota' si no se pudo evaluar ninguna categoría."""
    if score is None:
        return "sin nota"
    return f"{score}/100 {load_checks().semaphore(score)}"


def things_to_improve(report: checks.Report) -> str:
    """'1 cosa por mejorar' o 'N cosas por mejorar'."""
    count = len(report.findings)
    things = "1 cosa" if count == 1 else f"{count} cosas"
    return f"{things} por mejorar"


def quick_line(report: checks.Report) -> str:
    """La línea de resumen que muestran las skills al terminar."""
    return (
        f"{report.root.name}: {grade(report.score)} · "
        f"{things_to_improve(report)} (sin calidad de código) "
        f"· detalle: {REVIEW_SKILL}"
    )


def print_report(report: checks.Report) -> None:
    """El reporte completo, legible en la terminal."""
    rules = load_checks()
    say(
        f"📊 {report.root.name}: {grade(report.score)} · "
        f"{things_to_improve(report)}"
    )
    for project in report.projects:
        say(f"\n📁 {project.name}: {grade(project.score)}")
        for category, score in project.categories.items():
            label = rules.CATEGORY_LABELS[category]
            value = (
                f"{score}/100"
                if score is not None
                else f"no evaluada ({project.not_evaluated[category]})"
            )
            say(f"   - {label}: {value}")
        for finding in report.findings:
            if finding.project == project.name:
                print_finding(finding)


def print_finding(finding: checks.Finding) -> None:
    """Un hallazgo con su porqué, cómo arreglarlo y si seedflow puede."""
    fix = (
        f"seedflow puede hacerlo (fix {finding.fix_id})"
        if finding.fix_id
        else "a mano"
    )
    say(f"   ❗ [{finding.rule}] -{finding.points} · {finding.path}")
    say(f"      {finding.message}")
    say(f"      Por qué: {finding.why}")
    say(f"      Cómo: {finding.how} ({fix})")


def cmd_check(args: argparse.Namespace) -> None:
    """Califica el repo. Solo lee: nunca escribe en el repo."""
    root = Path(args.root).resolve()
    rules = load_checks()
    modules = discover_rules()
    ctx = build_context(root, args.quick)
    if not ctx.projects:
        if args.json:
            empty = rules.Report(root, None, None, [], [])
            print(json.dumps(empty.as_dict(), indent=2, ensure_ascii=False))
            return
        say(
            f"{root.name}: no encontré proyectos en {root / 'projects'}, "
            "así que no hay nota."
        )
        return
    report = rules.evaluate(ctx, modules)
    if args.json:
        print(json.dumps(report.as_dict(), indent=2, ensure_ascii=False))
    elif args.quick:
        say(quick_line(report))
    else:
        print_report(report)


def cmd_fix(args: argparse.Namespace) -> None:
    """Aplica arreglos mecánicos (lo completa la tarea T-006)."""
    raise SeedError("'fix' todavía no está disponible.")


# --------------------------------------------------------------------------
# Entrada
# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """Define los comandos y sus argumentos."""
    parser = argparse.ArgumentParser(
        prog="seedflow",
        description="Crea, elimina y califica proyectos Melonn.",
    )
    parser.add_argument(
        "--root",
        default=".",
        help="Carpeta raíz del repo (por defecto, la carpeta actual).",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    status = commands.add_parser("status", help="Dónde estás y qué hay.")
    status.add_argument("--json", action="store_true")
    status.set_defaults(func=cmd_status)

    project = commands.add_parser("create-project", help="Crea un proyecto.")
    project.add_argument("name")
    project.add_argument("--service-type", required=True, choices=SERVICE_TYPES)
    project.add_argument(
        "--skip-cdk", action="store_true", help="No correr cdk init."
    )
    project.set_defaults(func=cmd_create_project)

    microservice = commands.add_parser(
        "create-microservice", help="Crea un microservicio."
    )
    microservice.add_argument("name")
    microservice.add_argument("--project", required=True)
    microservice.add_argument(
        "--service-type", required=True, choices=SERVICE_TYPES
    )
    microservice.add_argument(
        "--database", action="store_true", help="Crear src/database/."
    )
    microservice.set_defaults(func=cmd_create_microservice)

    delete_project = commands.add_parser(
        "delete-project", help="Elimina un proyecto."
    )
    delete_project.add_argument("name")
    add_deletion_flags(delete_project)
    delete_project.set_defaults(func=cmd_delete_project)

    delete_microservice = commands.add_parser(
        "delete-microservice", help="Elimina un microservicio."
    )
    delete_microservice.add_argument("name")
    delete_microservice.add_argument("--project", required=True)
    delete_microservice.add_argument(
        "--service-type", required=True, choices=SERVICE_TYPES
    )
    add_deletion_flags(delete_microservice)
    delete_microservice.set_defaults(func=cmd_delete_microservice)

    check = commands.add_parser(
        "check", help="Califica qué tan organizado está el repo."
    )
    check.add_argument(
        "--quick",
        action="store_true",
        help="Solo las reglas rápidas, en una línea (sin calidad de código).",
    )
    check.add_argument("--json", action="store_true")
    check.set_defaults(func=cmd_check)

    fix = commands.add_parser("fix", help="Aplica arreglos mecánicos.")
    fix.add_argument(
        "--list", action="store_true", help="Lista los arreglos posibles."
    )
    fix.add_argument("fix_ids", nargs="*", metavar="FIX_ID")
    fix.set_defaults(func=cmd_fix)
    return parser


def add_deletion_flags(parser: argparse.ArgumentParser) -> None:
    """--dry-run y --yes, que no se pueden usar juntos."""
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--dry-run", action="store_true", help="Mostrar qué se borraría."
    )
    group.add_argument(
        "--yes", action="store_true", help="Confirmar el borrado."
    )


def safe_console() -> None:
    """Evita que un emoji rompa la salida en consolas sin UTF-8 (Windows)."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        with contextlib.suppress(ValueError, OSError):
            reconfigure(errors="replace")


def main(argv: list[str] | None = None) -> int:
    """Punto de entrada."""
    safe_console()
    args = build_parser().parse_args(argv)
    try:
        args.func(args)
    except SeedError as error:
        print(f"❌ {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
