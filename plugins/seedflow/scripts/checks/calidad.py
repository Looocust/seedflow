"""Calidad de código: ruff, mypy y TODO pendientes, por microservicio.

Solo en el reporte completo (QUICK = False): necesita herramientas externas.
`ruff` y `mypy` se instalan en un entorno propio de seedflow, fuera del repo
y de los entornos del usuario, en las versiones que fija el proyecto en
python/requirements.txt (o las del equipo). Así dos personas con la misma
copia del repo obtienen la misma nota.

Calificar no escribe en el repo: ruff corre con --no-cache y mypy guarda su
caché dentro del entorno de herramientas. Los arreglos (FIXES) sí escriben,
pero solo cuando se piden.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

import seedflow
from checks import SEVERITY
from checks import CheckResult
from checks import Context
from checks import Finding
from checks import iter_files
from checks import Microservice
from checks import Project


CATEGORY = "calidad"
QUICK = False

DEFAULT_VERSIONS = {"ruff": "0.9.6", "mypy": "1.15.0"}
WINDOWS = os.name == "nt"
PER_ERROR = 2
MAX_PER_TOOL = 30
SHOWN = 3  # ubicaciones que se muestran en cada hallazgo
NO_MICROSERVICES = "el proyecto no tiene microservicios"
PIN = re.compile(
    r"^\s*(ruff|mypy)\s*==\s*([0-9][0-9A-Za-z.+!-]*)\s*(#.*)?$",
    re.IGNORECASE,
)
RUFF_SUFFIXES = (".py", ".pyi", ".ipynb")  # lo que ruff revisa por defecto
TODO = re.compile(r"\bTODO\b")
MYPY_LOCATION = re.compile(r"^(.+?):(\d+)(?::\d+)?: error:")
READ_MYPY_SETTINGS = """
import json, sys
try:
    import tomllib
except ImportError:
    import tomli as tomllib
with open(sys.argv[1], "rb") as file:
    mypy = tomllib.load(file).get("tool", {}).get("mypy", {})
def as_list(value):
    value = [value] if isinstance(value, str) else value
    return [str(item).strip() for item in value if str(item).strip()]
print(json.dumps({
    "keys": sorted(mypy),
    "exclude": as_list(mypy.get("exclude", [])),
    "plugins": as_list(mypy.get("plugins", [])),
}))
"""
# Opciones de [tool.mypy] (mypy 1.15) que escriben archivos de reporte: las
# *_report de mypy.defaults.REPORTER_NAMES, más junit_xml.
MYPY_REPORT_OPTIONS = frozenset(
    {
        "any_exprs_report",
        "cobertura_xml_report",
        "html_report",
        "linecount_report",
        "linecoverage_report",
        "lineprecision_report",
        "memory_xml_report",
        "txt_report",
        "xml_report",
        "xslt_html_report",
        "xslt_txt_report",
        "junit_xml",
    }
)
INSTALL_TIMEOUT = 900
TOOL_TIMEOUT = 600


class ToolError(Exception):
    """ruff o mypy no pudieron revisar un microservicio."""


class Versions(NamedTuple):
    """Versiones de ruff y mypy con las que se califica un proyecto."""

    ruff: str
    mypy: str

    def label(self) -> str:
        """'ruff 0.9.6 y mypy 1.15.0'."""
        return f"ruff {self.ruff} y mypy {self.mypy}"


# --------------------------------------------------------------------------
# Entorno de herramientas
# --------------------------------------------------------------------------


def tools_home() -> Path:
    r"""Carpeta de los entornos de herramientas de seedflow.

    SEEDFLOW_TOOLS_DIR la reemplaza (la usan los tests). Por defecto,
    ~/.cache/seedflow/tools, o %LOCALAPPDATA%\seedflow\tools en Windows.
    """
    custom = os.environ.get("SEEDFLOW_TOOLS_DIR")
    if custom:
        # Absoluta: las herramientas corren con otra carpeta actual.
        return Path(custom).absolute()
    if WINDOWS:
        local = os.environ.get("LOCALAPPDATA")
        base = Path(local) if local else Path.home() / "AppData" / "Local"
        return base / "seedflow" / "tools"
    return Path.home() / ".cache" / "seedflow" / "tools"


def project_versions(project: Path) -> Versions:
    """Las versiones fijadas (==) en python/requirements.txt del proyecto."""
    versions = dict(DEFAULT_VERSIONS)
    requirements = project / "python" / "requirements.txt"
    if requirements.is_file() and not seedflow.is_link(requirements):
        text = requirements.read_text(encoding="utf-8", errors="replace")
        for line in text.splitlines():
            match = PIN.match(line)
            if match:
                versions[match.group(1).lower()] = match.group(2)
    return Versions(versions["ruff"], versions["mypy"])


def python_of(env: Path) -> Path:
    """El intérprete de un entorno virtual."""
    if WINDOWS:
        return env / "Scripts" / "python.exe"
    return env / "bin" / "python"


def ruff_of(env: Path) -> Path:
    """El binario nativo de ruff del entorno: no importa nada de cwd."""
    if WINDOWS:
        return env / "Scripts" / "ruff.exe"
    return env / "bin" / "ruff"


def tools_ready(env: Path) -> bool:
    """Si el entorno ya tiene python y el binario de ruff."""
    return python_of(env).exists() and ruff_of(env).exists()


def install_step(command: list[str], cwd: Path) -> None:
    """Corre un paso de la instalación; si falla, lanza el error."""
    subprocess.run(
        command,
        cwd=cwd,
        env=tool_env(),
        capture_output=True,
        text=True,
        check=True,
        timeout=INSTALL_TIMEOUT,
    )


def ensure_tools(versions: Versions) -> Path:
    """El entorno con ruff y mypy; lo crea (venv + pip) solo la primera vez.

    Se instala en una carpeta temporal y se renombra al final: un entorno a
    medias nunca queda con el nombre definitivo. Lanza ToolError si no puede.
    """
    env = tools_home() / f"ruff-{versions.ruff}_mypy-{versions.mypy}"
    if tools_ready(env):
        return env
    try:
        env.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=f".{env.name}.", dir=env.parent))
    except OSError as error:
        raise ToolError(install_failure(versions, env, error)) from error
    try:
        # -I y cwd en la carpeta de herramientas: ni la carpeta actual (el
        # repo) ni PYTHONPATH pueden cambiar qué venv o qué pip corre.
        install_step(
            [sys.executable, "-I", "-m", "venv", str(staging)], env.parent
        )
        install_step(
            [
                str(python_of(staging)),
                "-I",
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "--no-input",
                "--quiet",
                f"ruff=={versions.ruff}",
                f"mypy=={versions.mypy}",
            ],
            env.parent,
        )
        if env.exists():  # un entorno roto de seedflow: sin python o sin ruff
            shutil.rmtree(env)
        staging.rename(env)
    except (OSError, subprocess.SubprocessError) as error:
        if not tools_ready(env):  # otro proceso pudo ganar la carrera
            raise ToolError(install_failure(versions, env, error)) from error
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return env


def install_failure(versions: Versions, env: Path, error: Exception) -> str:
    """Motivo de 'no evaluada' cuando no se pudieron instalar."""
    return (
        f"no se pudieron instalar {versions.label()} en {env} "
        f"({error_detail(error)}); se necesita internet la primera vez"
    )


def error_detail(error: Exception) -> str:
    """La última línea útil de un error de un comando."""
    output = getattr(error, "stderr", None) or getattr(error, "output", None)
    lines = [line.strip() for line in (output or "").splitlines()]
    lines = [line for line in lines if line]
    return lines[-1] if lines else str(error)


# --------------------------------------------------------------------------
# Correr ruff y mypy
# --------------------------------------------------------------------------


def tool_env() -> dict[str, str]:
    """Variables de entorno sin las que cambian lo que revisan ruff o mypy.

    Tampoco pasan las PYTHON* (PYTHONPATH, PYTHONHOME...): ningún python que
    lancen las herramientas puede importar código del proyecto.
    """
    return {
        key: value
        for key, value in os.environ.items()
        if not key.upper().startswith(("RUFF_", "MYPY", "PYTHON"))
    }


def run_ruff(
    env: Path, args: list[str], ok: tuple[int, ...], cwd: Path
) -> subprocess.CompletedProcess[str]:
    """Corre el binario de ruff del entorno en cwd.

    Es nativo: no importa módulos de Python, así que puede correr junto al
    pyproject sin que un ruff.py del proyecto lo reemplace.
    """
    return run_command([str(ruff_of(env)), *args], ok, "ruff", cwd)


def run_python(
    env: Path, args: list[str], ok: tuple[int, ...], what: str
) -> subprocess.CompletedProcess[str]:
    """Corre el python del entorno, aislado (-I) y en el entorno.

    Sin -I, la carpeta actual y PYTHONPATH van antes que lo instalado: un
    mypy.py o tomllib.py del proyecto se importaría en su lugar.
    """
    return run_command([str(python_of(env)), "-I", *args], ok, what, env)


def run_command(
    command: list[str], ok: tuple[int, ...], what: str, cwd: Path
) -> subprocess.CompletedProcess[str]:
    """Corre una herramienta; lanza ToolError si no responde o falla.

    Fallar es salir con un código que no está en ok.
    """
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            env=tool_env(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=TOOL_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise ToolError(f"{what} no respondió: {error}") from error
    if result.returncode not in ok:
        detail = error_detail(
            subprocess.CalledProcessError(
                result.returncode, command, result.stdout, result.stderr
            )
        )
        raise ToolError(f"{what} falló (código {result.returncode}): {detail}")
    return result


def pyproject(project: Path) -> Path | None:
    """El pyproject.toml del proyecto, con las reglas de ruff y mypy."""
    path = project / "python" / "pyproject.toml"
    if path.is_file() and not seedflow.is_link(path):
        return path
    return None


def ruff_config(config: Path | None) -> list[str]:
    """Las reglas del proyecto, o ninguna configuración ajena si no hay.

    --force-exclude: las exclusiones del proyecto valen también para los
    archivos que se le pasan uno por uno.
    """
    args = ["--config", str(config)] if config else ["--isolated"]
    return [*args, "--force-exclude"]


def ruff_cwd(env: Path, config: Path | None) -> Path:
    """Dónde corre ruff: junto al pyproject, como en el proyecto.

    Con --config, ruff resuelve las rutas relativas de la configuración
    (exclude, per-file-ignores...) desde la carpeta en la que corre. Sin
    pyproject, en el entorno de herramientas. Con --no-cache no deja nada.
    """
    return config.parent if config else env


def ruff_files(folder: Path) -> list[str]:
    """Lo que revisa ruff, sin entornos ni cachés (como las demás reglas).

    Se le pasan los archivos y no la carpeta: `ruff format` no acepta
    --extend-exclude, y así ruff, mypy y los TODO revisan lo mismo.
    """
    return [str(path) for path in iter_files(folder, RUFF_SUFFIXES)]


def ruff_check(env: Path, files: list[str], config: Path | None) -> list[dict]:
    """Los errores de `ruff check` en esos archivos."""
    if not files:
        return []
    result = run_ruff(
        env,
        [
            "check",
            "--no-cache",
            # Calificar nunca escribe, aunque el pyproject pida fix o fix-only.
            "--no-fix",
            "--no-fix-only",
            "--no-unsafe-fixes",
            "--output-format",
            "json",
            *ruff_config(config),
            *files,
        ],
        ok=(0, 1),
        cwd=ruff_cwd(env, config),
    )
    try:
        errors = json.loads(result.stdout)
    except ValueError as error:
        raise ToolError(
            f"ruff devolvió algo que no es JSON: {error}"
        ) from error
    if not isinstance(errors, list):
        raise ToolError("ruff devolvió algo que no es una lista de errores")
    return errors


def ruff_unformatted(
    env: Path, files: list[str], config: Path | None
) -> list[str]:
    """Los archivos que `ruff format` cambiaría."""
    if not files:
        return []
    result = run_ruff(
        env,
        [
            "format",
            "--check",
            "--no-cache",
            *ruff_config(config),
            *files,
        ],
        ok=(0, 1),
        cwd=ruff_cwd(env, config),
    )
    prefix = "Would reformat: "
    return [
        line[len(prefix) :].strip()
        for line in result.stdout.splitlines()
        if line.startswith(prefix)
    ]


def mypy_errors(env: Path, files: list[Path], config: Path | None) -> list[str]:
    """Las líneas de error de `mypy` en esos archivos (las notas no cuentan).

    Recibe los archivos de iter_files, no la carpeta: así mypy tampoco entra
    a entornos ni cachés.
    """
    result = run_python(
        env,
        [
            "-m",
            "mypy",
            f"--config-file={config}" if config else "--config-file=",
            "--cache-dir",
            str(env / "mypy-cache"),
            # Busca paquetes con el python del entorno: ni el
            # python_executable del pyproject (lo ejecutaría) ni un python
            # del PATH (la nota dependería de lo que cada uno tenga).
            "--python-executable",
            str(python_of(env)),
            "--no-error-summary",
            "--show-absolute-path",
            *(str(path) for path in files),
        ],
        ok=(0, 1),
        what="mypy",
    )
    return [line for line in result.stdout.splitlines() if ": error:" in line]


def mypy_exclude(env: Path, config: Path | None) -> list[re.Pattern[str]]:
    """Los patrones `exclude` de [tool.mypy] del pyproject.

    Antes de correr mypy revisa que el pyproject no pida algo que escriba
    archivos (reportes) o ejecute código del proyecto (plugins): en ese caso
    lanza ToolError y la calidad del proyecto queda "no evaluada".

    El TOML se lee con el python del entorno de herramientas (tomllib, o
    tomli, que mypy trae en Python < 3.11): seedflow solo usa la librería
    estándar de 3.8, que no lee TOML.
    """
    if config is None:
        return []
    result = run_python(
        env,
        ["-c", READ_MYPY_SETTINGS, str(config)],
        ok=(0,),
        what="leer [tool.mypy] del pyproject",
    )
    try:
        settings = json.loads(result.stdout)
        keys = {key.lower().replace("-", "_") for key in settings["keys"]}
        plugins = [str(plugin) for plugin in settings["plugins"]]
        patterns = [str(pattern) for pattern in settings["exclude"]]
    except (ValueError, TypeError, KeyError, AttributeError) as error:
        raise ToolError(f"no se pudo leer [tool.mypy] de {config}") from error
    reports = sorted(keys & MYPY_REPORT_OPTIONS)
    if reports:
        raise ToolError(
            f"el pyproject pide reportes de mypy ({', '.join(reports)}); "
            "seedflow no escribe archivos al calificar"
        )
    if plugins:
        raise ToolError(
            f"el pyproject pide plugins de mypy ({', '.join(plugins)}); "
            "seedflow no ejecuta código del proyecto al calificar"
        )
    try:
        return [re.compile(pattern) for pattern in patterns]
    except re.error as error:
        raise ToolError(
            f"exclude de mypy inválido en {config}: {error}"
        ) from error


def mypy_excluded(
    path: Path, folder: Path, config: Path, exclude: list[re.Pattern[str]]
) -> bool:
    """Si mypy dejaría fuera este archivo al recorrer la carpeta.

    Como mypy: cada carpeta bajo la del microservicio (con '/' al final) y el
    archivo, relativos a donde está el pyproject, contra cada patrón con
    re.search. mypy no aplica exclude a los archivos que recibe uno por uno,
    así que se filtran antes de pasárselos.
    """
    candidates = [path]
    candidates.extend(
        parent for parent in path.parents if folder in parent.parents
    )
    for candidate in candidates:
        relative = os.path.relpath(candidate, config.parent)
        relative = relative.replace(os.sep, "/")
        if candidate != path:
            relative += "/"
        if any(pattern.search(relative) for pattern in exclude):
            return True
    return False


# --------------------------------------------------------------------------
# Reglas
# --------------------------------------------------------------------------


def run(ctx: Context) -> CheckResult:
    """ruff, mypy y TODO de cada microservicio de cada proyecto."""
    result = CheckResult()
    envs: dict[Versions, Path | str] = {}
    for project in ctx.projects:
        if not project.microservices:
            result.not_evaluated[project.name] = NO_MICROSERVICES
            continue
        versions = project_versions(project.path)
        if versions not in envs:
            try:
                envs[versions] = ensure_tools(versions)
            except ToolError as error:
                envs[versions] = str(error)
        env = envs[versions]
        if isinstance(env, str):
            result.not_evaluated[project.name] = env
            continue
        try:
            findings = check_project(ctx.root, project, env)
        except ToolError as error:
            result.not_evaluated[project.name] = str(error)
            continue
        result.findings.extend(findings)
    return result


def check_project(root: Path, project: Project, env: Path) -> list[Finding]:
    """Los hallazgos de todos los microservicios de un proyecto."""
    config = pyproject(project.path)
    exclude = mypy_exclude(env, config)
    findings: list[Finding] = []
    for microservice in project.microservices:
        place = Place(root, project, microservice)
        files = ruff_files(place.folder)
        findings.extend(
            finding
            for finding in [
                ruff_finding(place, ruff_check(env, files, config)),
                format_finding(place, ruff_unformatted(env, files, config)),
                mypy_finding(place, env, config, exclude),
                todo_finding(place),
            ]
            if finding is not None
        )
    return findings


class Place:
    """Dónde está un microservicio: para rutas, mensajes y fix_id."""

    def __init__(
        self, root: Path, project: Project, microservice: Microservice
    ) -> None:
        self.project = project.name
        self.folder = microservice.path
        self.path = microservice.path.relative_to(root).as_posix()
        self.fix_target = (
            f"{project.name}/{microservice.service_type}/{microservice.name}"
        )

    def relative(self, filename: str) -> str:
        """Ruta de un archivo relativa al microservicio."""
        try:
            return Path(filename).relative_to(self.folder).as_posix()
        except ValueError:
            return filename

    def finding(
        self,
        rule: str,
        points: int,
        message: str,
        why: str,
        how: str,
        fix: str | None = None,
    ) -> Finding:
        """Un hallazgo de calidad en este microservicio."""
        return Finding(
            category=CATEGORY,
            rule=rule,
            points=points,
            project=self.project,
            path=self.path,
            message=message,
            why=why,
            how=how,
            fix_id=f"{fix}:{self.fix_target}" if fix else None,
        )


def per_error(count: int) -> int:
    """-2 por error, con tope de -30 por herramienta y microservicio."""
    return min(MAX_PER_TOOL, PER_ERROR * count)


def errors_word(count: int) -> str:
    """'1 error' o 'N errores'."""
    return "1 error" if count == 1 else f"{count} errores"


def some(items: list[str]) -> str:
    """Las primeras ubicaciones, y cuántas más hay."""
    shown = ", ".join(items[:SHOWN])
    rest = len(items) - SHOWN
    return f"{shown} y {rest} más" if rest > 0 else shown


def ruff_finding(place: Place, errors: list[dict]) -> Finding | None:
    """C1: `ruff check` con errores."""
    if not errors:
        return None
    locations = sorted(
        (
            place.relative(str(error.get("filename", ""))),
            int((error.get("location") or {}).get("row") or 0),
            str(error.get("code") or ""),
        )
        for error in errors
    )
    fixable = sum(
        1
        for error in errors
        if (error.get("fix") or {}).get("applicability") == "safe"
    )
    how = "Corrige lo que muestra `ruff check` en el microservicio."
    if fixable:
        how += (
            f" `ruff check --fix` arregla {fixable} de ellos solo; el resto "
            "es a mano."
        )
    return place.finding(
        "C1",
        per_error(len(errors)),
        f"ruff check encontró {errors_word(len(errors))}: "
        + some([f"{name}:{row} {code}" for name, row, code in locations]),
        "Con las reglas del proyecto, ruff encuentra bugs (variables sin "
        "usar, imports rotos) y código que el equipo lee distinto.",
        how,
        fix="C1" if fixable else None,
    )


def format_finding(place: Place, files: list[str]) -> Finding | None:
    """C2: `ruff format` cambiaría archivos."""
    if not files:
        return None
    names = sorted(place.relative(name) for name in files)
    count = "1 archivo" if len(names) == 1 else f"{len(names)} archivos"
    return place.finding(
        "C2",
        SEVERITY["menor"],
        f"ruff format cambiaría {count}: {some(names)}",
        "Con el formato del equipo, los diffs muestran solo cambios reales "
        "y no espacios o comillas.",
        "Aplica `ruff format` al microservicio; no cambia la lógica.",
        fix="C2",
    )


def mypy_finding(
    place: Place,
    env: Path,
    config: Path | None,
    exclude: list[re.Pattern[str]],
) -> Finding | None:
    """C3: `mypy` con errores."""
    files = [
        path
        for path in iter_files(place.folder, (".py",))
        if not (config and mypy_excluded(path, place.folder, config, exclude))
    ]
    if not files:
        return None  # sin código, mypy se queja de que no hay archivos
    errors = mypy_errors(env, files, config)
    if not errors:
        return None
    locations = []
    for line in errors:
        match = MYPY_LOCATION.match(line)
        filename, row = match.groups() if match else (line, "?")
        locations.append(f"{place.relative(filename)}:{row}")
    return place.finding(
        "C3",
        per_error(len(errors)),
        f"mypy encontró {errors_word(len(errors))}: " + some(sorted(locations)),
        "mypy encuentra errores de tipos antes de desplegar: argumentos "
        "equivocados, None donde no se espera.",
        "Corrige lo que muestra `mypy` en el microservicio.",
    )


def todo_finding(place: Place) -> Finding | None:
    """C4: TODO pendientes (uno por microservicio)."""
    locations = []
    for path in iter_files(place.folder, (".py",)):
        text = path.read_text(encoding="utf-8", errors="replace")
        for row, line in enumerate(text.splitlines(), 1):
            if TODO.search(line):
                locations.append(f"{place.relative(str(path))}:{row}")
    if not locations:
        return None
    count = (
        "1 TODO pendiente"
        if len(locations) == 1
        else f"{len(locations)} TODO pendientes"
    )
    return place.finding(
        "C4",
        SEVERITY["menor"],
        f"{count}: {some(sorted(locations))}",
        "Un TODO es trabajo pendiente que nadie sigue.",
        "Resuélvelo, o pásalo a una tarea y bórralo del código.",
    )


# --------------------------------------------------------------------------
# Arreglos
# --------------------------------------------------------------------------


def target_folder(root: Path, fix_id: str, prefix: str) -> tuple[Path, Path]:
    """(proyecto, microservicio) de un fix_id 'C2:proyecto/tipo/nombre'."""
    head, _, target = fix_id.partition(":")
    parts = target.split("/")
    if head != prefix or len(parts) != 3:
        raise seedflow.SeedError(
            f"'{fix_id}' no es un arreglo válido; se espera "
            f"'{prefix}:proyecto/tipo/microservicio'."
        )
    project, service_type, name = parts
    folder = seedflow.microservice_folder(root, project, service_type, name)
    if not folder.is_dir():
        raise seedflow.SeedError(f"No existe el microservicio {folder}.")
    return seedflow.project_folder(root, project), folder


def fingerprint(folder: Path) -> dict[Path, str]:
    """Contenido de cada archivo de la carpeta, para ver cuáles cambian."""
    return {
        path: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in iter_files(folder)
    }


def apply_ruff(
    root: Path, fix_id: str, prefix: str, args: list[str]
) -> list[Path]:
    """Corre ruff sobre el microservicio y devuelve los archivos que cambió."""
    project, folder = target_folder(root, fix_id, prefix)
    try:
        env = ensure_tools(project_versions(project))
        before = fingerprint(folder)
        config = pyproject(project)
        files = ruff_files(folder)
        if files:
            run_ruff(
                env,
                [*args, "--no-cache", *ruff_config(config), *files],
                ok=(0, 1),
                cwd=ruff_cwd(env, config),
            )
    except ToolError as error:
        raise seedflow.SeedError(str(error)) from error
    after = fingerprint(folder)
    return sorted(path for path in after if before.get(path) != after[path])


def fix_ruff_check(root: Path, fix_id: str) -> list[Path]:
    """C1: `ruff check --fix` (solo los arreglos seguros de ruff)."""
    return apply_ruff(
        root, fix_id, "C1", ["check", "--fix", "--no-unsafe-fixes"]
    )


def fix_ruff_format(root: Path, fix_id: str) -> list[Path]:
    """C2: `ruff format`."""
    return apply_ruff(root, fix_id, "C2", ["format"])


FIXES: dict[str, Callable[[Path, str], list[Path]]] = {
    "C1": fix_ruff_check,
    "C2": fix_ruff_format,
}
