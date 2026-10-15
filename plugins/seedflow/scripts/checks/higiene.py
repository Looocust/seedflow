"""Reglas de seguridad e higiene.

- H1: un `.env` commiteado dentro de projects/ (crítico). Sin git no se
  evalúa: fuera de un repo nada está commiteado.
- H2: el `.gitignore` de la raíz no ignora `.env` (importante, en cada
  proyecto). Es la única con arreglo mecánico (FIXES).
- H3: texto con forma de credencial en un `.py` (crítico).
- H4: `read`, `execute_query` o `write` con una query armada con una
  f-string o `.format()` (importante).

Solo leen: el único que escribe es el arreglo de H2, y solo el `.gitignore`.
Nunca muestran el valor de una credencial: solo el archivo y la línea.
"""

from __future__ import annotations

import ast
import os
import re
import shutil
import subprocess
from collections.abc import Callable
from collections.abc import Iterator
from pathlib import Path

from checks import SEVERITY
from checks import CheckResult
from checks import Context
from checks import Finding
from checks import Project
from checks import iter_files


CATEGORY = "higiene"
QUICK = True

GITIGNORE = ".gitignore"
GITIGNORE_FIX = "H2:.gitignore"
FALSE_POSITIVE = "puede ser un falso positivo"

AWS_KEY = re.compile(r"(?<![0-9A-Z])AKIA[0-9A-Z]{16}(?![0-9A-Z])")
SECRET_NAME = re.compile(r"(password|secret|token)$", re.IGNORECASE)
QUERY_METHODS = {"read", "execute_query", "write"}


def run(ctx: Context) -> CheckResult:
    """Corre las cuatro reglas sobre cada proyecto."""
    exposed = exposed_projects(ctx)
    env_files = committed_env_files(ctx.tracked)
    findings: list[Finding] = []
    for project in ctx.projects:
        findings.extend(committed_env(project, env_files))
        if project.name in exposed:
            findings.append(gitignore_finding(project))
        findings.extend(code_findings(ctx.root, project))
    return CheckResult(findings=findings)


def finding(
    rule: str,
    severity: str,
    project: Project,
    path: str,
    texts: tuple[str, str, str],
    fix_id: str | None = None,
) -> Finding:
    """Un hallazgo de esta categoría (texts: qué pasa, por qué, cómo)."""
    message, why, how = texts
    return Finding(
        category=CATEGORY,
        rule=rule,
        points=SEVERITY[severity],
        project=project.name,
        path=path,
        message=message,
        why=why,
        how=how,
        fix_id=fix_id,
    )


# --------------------------------------------------------------------------
# H1: .env commiteado
# --------------------------------------------------------------------------


def committed_env_files(tracked: set[str] | None) -> list[str]:
    """Los `.env` que git sigue, en orden (sin git no se evalúa: ninguno)."""
    if tracked is None:
        return []
    return sorted(p for p in tracked if p.rsplit("/", 1)[-1] == ".env")


def committed_env(project: Project, env_files: list[str]) -> list[Finding]:
    """Un hallazgo por cada `.env` commiteado dentro del proyecto."""
    prefix = f"projects/{project.name}/"
    return [
        finding(
            "H1",
            "critico",
            project,
            path,
            (
                "Hay un .env commiteado.",
                "Las credenciales que tiene quedan en el historial de git "
                "para cualquiera con acceso al repo, aunque luego se borre.",
                "Deja de seguirlo (git rm --cached), agrégalo al .gitignore "
                "y rota las credenciales que tenía. seedflow te ofrece "
                "hacerlo con confirmación; sacarlo del historial queda fuera.",
            ),
        )
        for path in env_files
        if path.startswith(prefix)
    ]


# --------------------------------------------------------------------------
# H2: el .gitignore no ignora .env
# --------------------------------------------------------------------------


def exposed_projects(ctx: Context) -> set[str]:
    """Los proyectos en los que un `python/.env` no quedaría ignorado.

    En un repo git se lo pregunta a git (entiende todos sus patrones), sin la
    configuración global de quien califica: la nota no puede depender de la
    máquina. Fuera de git, o si git falla, mira las líneas del `.gitignore`.
    """
    names = {project.name for project in ctx.projects}
    if ctx.tracked is not None:
        ignored = git_ignored_projects(ctx)
        if ignored is not None:
            return names - ignored
    if gitignore_lines_ignore_env(ctx.root / GITIGNORE):
        return set()
    return names


def env_path(project: Project) -> str:
    """Dónde va el .env de un proyecto, relativo a la raíz."""
    return f"projects/{project.name}/python/.env"


def git_ignored_projects(ctx: Context) -> set[str] | None:
    """Proyectos cuyo .env ignora git (None si no se le pudo preguntar)."""
    git = shutil.which("git")
    if not git:
        return None
    paths = [env_path(project) for project in ctx.projects]
    try:
        result = subprocess.run(
            [
                git,
                "-c",
                "core.excludesFile=",
                "check-ignore",
                "--no-index",
                "--stdin",
                "-z",
            ],
            cwd=ctx.root,
            input="\0".join(paths).encode("utf-8"),
            capture_output=True,
            check=False,
            timeout=30,
        )
    except (subprocess.SubprocessError, OSError):
        return None
    if result.returncode not in (0, 1):
        return None
    ignored = {os.fsdecode(p) for p in result.stdout.split(b"\0") if p}
    return {p.name for p in ctx.projects if env_path(p) in ignored}


def gitignore_lines_ignore_env(gitignore: Path) -> bool:
    """Sin git: una línea exacta `.env` o `*.env` (la última decide)."""
    if not gitignore.is_file():
        return False
    ignored = False
    lines = gitignore.read_text(encoding="utf-8", errors="replace")
    for line in lines.splitlines():
        pattern = line.rstrip()
        if pattern in (".env", "*.env"):
            ignored = True
        elif pattern in ("!.env", "!*.env"):
            ignored = False
    return ignored


def gitignore_finding(project: Project) -> Finding:
    """El hallazgo de H2, uno por cada proyecto expuesto."""
    return finding(
        "H2",
        "importante",
        project,
        GITIGNORE,
        (
            "El .gitignore de la raíz no ignora .env.",
            "Un .env con credenciales se puede commitear sin que nadie lo "
            "note, en este proyecto y en todos los del repo.",
            "Agrega la línea .env al .gitignore de la raíz.",
        ),
        fix_id=GITIGNORE_FIX,
    )


def add_env_to_gitignore(root: Path, fix_id: str) -> list[Path]:
    """Agrega `.env` al final del `.gitignore` de la raíz (lo crea si falta).

    No toca las demás líneas. Devuelve los archivos que cambió: ninguno si
    ya ignoraba `.env`. No escribe a través de un enlace simbólico.
    """
    gitignore = root / GITIGNORE
    if gitignore.is_symlink():
        raise ValueError(
            f"{gitignore} es un enlace simbólico; seedflow no escribe a "
            "través de enlaces. Agrega la línea .env a mano."
        )
    if gitignore_lines_ignore_env(gitignore):
        return []
    data = gitignore.read_bytes() if gitignore.exists() else b""
    newline = b"\r\n" if b"\r\n" in data else b"\n"
    if data and not data.endswith(b"\n"):
        data += newline
    gitignore.write_bytes(data + b".env" + newline)
    return [gitignore]


FIXES: dict[str, Callable[[Path, str], list[Path]]] = {
    "H2": add_env_to_gitignore,
}


# --------------------------------------------------------------------------
# H3 y H4: credenciales y queries en el código
# --------------------------------------------------------------------------


def code_findings(root: Path, project: Project) -> list[Finding]:
    """Credenciales y queries armadas en los `.py` de python/."""
    findings = []
    for path in python_files(project.path / "python"):
        source = path.read_bytes()
        relative = path.relative_to(root).as_posix()
        tree = parse(source)
        secrets = sorted(set(aws_key_lines(source)) | set(secret_lines(tree)))
        if secrets:
            findings.append(credential_finding(project, relative, secrets))
        queries = sorted(set(query_lines(tree)))
        if queries:
            findings.append(query_finding(project, relative, queries))
    return findings


def python_files(folder: Path) -> Iterator[Path]:
    """Los `.py` de la carpeta, con el recorrido común de checks.

    iter_files no entra a entornos (.venv, venv), node_modules ni cachés, ni
    sigue enlaces; tampoco se recorre python/ si es un enlace.
    """
    if folder.is_symlink():
        return iter(())
    return iter_files(folder, (".py",))


def parse(source: bytes) -> ast.AST | None:
    """El árbol del archivo, o None si no se puede leer como Python."""
    try:
        return ast.parse(source)
    except (SyntaxError, ValueError):
        return None


def lines_text(lines: list[int]) -> str:
    """'la línea 3' o 'las líneas 3, 7'."""
    if len(lines) == 1:
        return f"la línea {lines[0]}"
    return "las líneas " + ", ".join(str(n) for n in lines)


def aws_key_lines(source: bytes) -> Iterator[int]:
    """Líneas con algo que tiene la forma de una clave de acceso de AWS."""
    text = source.decode("utf-8", errors="replace")
    for match in AWS_KEY.finditer(text):
        yield text.count("\n", 0, match.start()) + 1


def secret_lines(tree: ast.AST | None) -> Iterator[int]:
    """Líneas que asignan un texto literal a un password, secret o token."""
    for node in ast.walk(tree) if tree else ():
        for name, value in assignments(node):
            if (
                name is not None
                and SECRET_NAME.search(name)
                and isinstance(value, ast.Constant)
                and isinstance(value.value, str)
                and value.value.strip()
            ):
                yield value.lineno


def assignments(node: ast.AST) -> Iterator[tuple[str | None, ast.AST]]:
    """(nombre, valor) de lo que este nodo asigna.

    Cubre `x = …`, `x: str = …`, `obj.x = …`, `d["x"] = …`, `f(x=…)` y
    `{"x": …}`.
    """
    if isinstance(node, ast.Assign):
        for target in node.targets:
            yield target_name(target), node.value
    elif isinstance(node, ast.AnnAssign) and node.value is not None:
        yield target_name(node.target), node.value
    elif isinstance(node, ast.Call):
        for keyword in node.keywords:
            yield keyword.arg, keyword.value
    elif isinstance(node, ast.Dict):
        # Sin zip(): su strict= no existe en Python 3.8.
        for index, key in enumerate(node.keys):
            yield text_of(key), node.values[index]


def target_name(target: ast.AST) -> str | None:
    """El nombre al que se asigna: variable, atributo o clave de texto."""
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Attribute):
        return target.attr
    if isinstance(target, ast.Subscript):
        # En Python 3.8 la clave viene envuelta en un ast.Index.
        key = target.slice
        if not isinstance(key, ast.Constant):
            key = getattr(key, "value", key)
        return text_of(key)
    return None


def text_of(node: ast.AST | None) -> str | None:
    """El texto de un literal de texto, o None si no lo es."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def query_lines(tree: ast.AST | None) -> Iterator[int]:
    """Líneas que llaman a read/execute_query/write con una query armada."""
    for node in ast.walk(tree) if tree else ():
        if (
            isinstance(node, ast.Call)
            and call_name(node) in QUERY_METHODS
            and is_built_query(query_argument(node))
        ):
            yield node.lineno


def call_name(call: ast.Call) -> str | None:
    """`read` en `redshift.read(…)` o en `read(…)`."""
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    if isinstance(call.func, ast.Name):
        return call.func.id
    return None


def query_argument(call: ast.Call) -> ast.AST | None:
    """El primer argumento, o el que se pasa como `query=`."""
    if call.args:
        return call.args[0]
    for keyword in call.keywords:
        if keyword.arg == "query":
            return keyword.value
    return None


def is_built_query(node: ast.AST | None) -> bool:
    """Una f-string o un `.format(…)`."""
    if isinstance(node, ast.JoinedStr):
        return True
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "format"
    )


def credential_finding(
    project: Project, path: str, lines: list[int]
) -> Finding:
    """H3: nombra el archivo y las líneas, nunca el valor."""
    return finding(
        "H3",
        "critico",
        project,
        path,
        (
            f"Texto con forma de credencial en {lines_text(lines)} "
            f"({FALSE_POSITIVE}).",
            "Una credencial en el código queda en el historial de git y la "
            "ve cualquiera con acceso al repo.",
            "Léela de una variable de entorno (os.environ) y, si era real, "
            "rótala.",
        ),
    )


def query_finding(project: Project, path: str, lines: list[int]) -> Finding:
    """H4: una query armada pegando valores con f-string o format()."""
    return finding(
        "H4",
        "importante",
        project,
        path,
        (
            f"Query armada con f-string o format() en {lines_text(lines)} "
            f"({FALSE_POSITIVE}).",
            "Si algún valor viene del evento, alguien puede cambiar la query "
            "(inyección SQL).",
            "No pegues en la query valores sin validar: revisa su tipo "
            "(EventValidator) o compáralos con una lista cerrada de valores "
            "permitidos. Ojo: params también usa format(), no protege.",
        ),
    )
