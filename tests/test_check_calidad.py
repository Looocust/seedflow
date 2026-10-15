"""Tests de la calidad de código (scripts/checks/calidad.py).

Nada sale a internet: el entorno de herramientas vive en un
SEEDFLOW_TOOLS_DIR temporal, la instalación (venv + pip) es falsa y `ruff` y
`mypy` son un script falso que reacciona a marcas en el código:

- `ERR_RUFF` es un error de ruff sin arreglo; `ERR_RUFF_FIX`, uno que
  `ruff check --fix` arregla (borra la marca).
- `UNFORMATTED` hace que `ruff format --check` pida formatear el archivo;
  `ruff format` borra la marca.
- `ERR_MYPY` es un error de mypy (y una nota, que no cuenta).

Solo librería estándar. Desde la raíz del repo:

    python3 -m unittest tests.test_check_calidad -v

SEEDFLOW_SCRIPT permite apuntar a otra copia del script (lo usa
tests/mutantes.py para comprobar que los tests detectan fallas).
"""

from __future__ import annotations

import contextlib
import hashlib
import importlib
import importlib.util
import io
import json
import os
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


REPO = Path(__file__).resolve().parent.parent
SCRIPT = Path(
    os.environ.get(
        "SEEDFLOW_SCRIPT", REPO / "plugins" / "seedflow" / "scripts" / "seedflow.py"
    )
)
ORDERS = "projects/demo/python/internal-services/orders"

# ruff y mypy falsos: el "python" del entorno de herramientas los corre con
# `python -m ruff ...` y `python -m mypy ...`, igual que a los de verdad.
FAKE_TOOLS = r'''
import json
import os
import re
import sys
from pathlib import Path

env = Path(__file__).resolve().parent
args = sys.argv[1:]
tool = args[1]
with (env / "calls.jsonl").open("a", encoding="utf-8") as log:
    log.write(json.dumps({"argv": args, "cwd": os.getcwd()}) + "\n")
fail = env / f"fail-{tool}"
if fail.exists():
    print(fail.read_text(), file=sys.stderr)
    sys.exit(2)
# Revisan los archivos que reciben, o todo lo que haya en una carpeta (sin
# excluir nada: si seedflow les pasa la carpeta, .venv cuenta).
targets = [Path(arg) for arg in args[2:] if not arg.startswith("-")
           and (arg.endswith(".py") or Path(arg).is_dir())]
files = []
for target in targets:
    if target.is_file():
        files.append(target)
        continue
    files.extend(target.rglob("*.py"))
files.sort()


def rewrite(marker):
    changed = []
    for path in files:
        text = path.read_text(encoding="utf-8")
        if marker in text:
            path.write_text(text.replace(marker, ""), encoding="utf-8")
            changed.append(path)
    return changed


if tool == "ruff" and args[2] == "check":
    if "--fix" in args:
        rewrite("ERR_RUFF_FIX")
    found = []
    for path in files:
        lines = path.read_text(encoding="utf-8").splitlines()
        for row, line in enumerate(lines, 1):
            for match in re.finditer(r"ERR_RUFF(_FIX)?", line):
                fix = {"applicability": "safe"} if match.group(1) else None
                found.append({
                    "code": "F841" if fix else "E999",
                    "message": "error falso",
                    "filename": str(path),
                    "location": {"row": row, "column": match.start() + 1},
                    "fix": fix,
                })
    if "json" in args:
        print(json.dumps(found))
    sys.exit(1 if found else 0)
if tool == "ruff" and args[2] == "format":
    if "--check" in args:
        pending = [p for p in files if "UNFORMATTED" in p.read_text("utf-8")]
        for path in pending:
            print(f"Would reformat: {path}")
        sys.exit(1 if pending else 0)
    print(f"{len(rewrite('UNFORMATTED'))} files reformatted")
    sys.exit(0)
if tool == "mypy":
    errors = 0
    for path in files:
        lines = path.read_text(encoding="utf-8").splitlines()
        for row, line in enumerate(lines, 1):
            if "ERR_MYPY" in line:
                errors += 1
                print(f"{path}:{row}: error: error falso  [misc]")
                print(f"{path}:{row}: note: una nota no cuenta")
    sys.exit(1 if errors else 0)
print(f"herramienta desconocida: {args}", file=sys.stderr)
sys.exit(2)
'''


def load_seedflow():
    """Carga el script como módulo, fresco en cada test."""
    spec = importlib.util.spec_from_file_location("seedflow_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeInstaller:
    """Hace de `python -m venv` y de `pip install`, sin salir a internet."""

    def __init__(self, fail=None):
        self.fail = fail  # None, "venv" o "pip"
        self.pips = []    # (carpeta del entorno, paquetes pedidos)
        self.venvs = []

    def __call__(self, command):
        command = [str(part) for part in command]
        if command[1:3] == ["-m", "venv"]:
            env = Path(command[-1])
            self.venvs.append(env)
            if self.fail == "venv":
                raise subprocess.CalledProcessError(
                    1, command, output="", stderr="Error: venv roto"
                )
            (env / "bin").mkdir(parents=True)
            (env / "fake_tools.py").write_text(FAKE_TOOLS, encoding="utf-8")
            python = env / "bin" / "python"
            python.write_text(
                "#!/bin/sh\n"
                f"exec {shlex.quote(sys.executable)} "
                f'"$(dirname "$0")/../fake_tools.py" "$@"\n'
            )
            python.chmod(0o755)
            return
        if command[1:4] == ["-m", "pip", "install"]:
            env = Path(command[0]).parent.parent
            self.pips.append(
                (env, [c for c in command[4:] if not c.startswith("-")])
            )
            if self.fail == "pip":
                raise subprocess.CalledProcessError(
                    1, command, output="",
                    stderr="ERROR: Could not find a version that satisfies "
                    "the requirement ruff==0.9.6 (sin internet)",
                )
            return
        raise AssertionError(f"comando de instalación inesperado: {command}")


@unittest.skipUnless(os.name == "posix", "ruff y mypy falsos usan /bin/sh")
class CalidadTestCase(unittest.TestCase):
    """Base: un repo temporal con un proyecto y un microservicio reales."""

    def setUp(self):
        self.seedflow = load_seedflow()
        self.checks = self.seedflow.load_checks()
        self.calidad = importlib.import_module("checks.calidad")
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name).resolve()
        self.root = self.base / "repo"
        self.root.mkdir()
        self.tools = self.base / "tools"
        patcher = mock.patch.dict(
            os.environ,
            {
                "GIT_CEILING_DIRECTORIES": str(self.base),
                "SEEDFLOW_TOOLS_DIR": str(self.tools),
            },
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.installer = self.use_installer(FakeInstaller())

    # -- ayudas ------------------------------------------------------------

    def use_installer(self, installer):
        patcher = mock.patch.object(self.calidad, "install_step", installer)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.installer = installer
        return installer

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = self.seedflow.main(["--root", str(self.root), *argv])
            except SystemExit as error:
                code = error.code
        return code, out.getvalue(), err.getvalue()

    def create(self, project="demo", microservices=("orders",)):
        code, out, err = self.run_cli(
            "create-project", project, "--service-type", "internal-services",
            "--skip-cdk",
        )
        self.assertEqual(code, 0, out + err)
        for name in microservices:
            code, out, err = self.run_cli(
                "create-microservice", name, "--project", project,
                "--service-type", "internal-services",
            )
            self.assertEqual(code, 0, out + err)

    def microservice(self, name="orders", project="demo"):
        return (self.root / "projects" / project / "python"
                / "internal-services" / name)

    def add_code(self, text, name="orders", project="demo",
                 filename="src/service/extra.py"):
        path = self.microservice(name, project) / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as file:
            file.write(text)
        return path

    def errors(self, marker, count):
        return "".join(f"x{i} = 1  # {marker}\n" for i in range(count))

    def report(self, *extra):
        code, out, err = self.run_cli("check", "--json", *extra)
        self.assertEqual(code, 0, out + err)
        return json.loads(out)

    def calidad_of(self, report, project="demo"):
        project = next(p for p in report["projects"] if p["name"] == project)
        return (project["categories"]["calidad"],
                project["not_evaluated"].get("calidad"))

    def findings(self, report, rule=None):
        return [
            f for f in report["findings"]
            if f["category"] == "calidad" and rule in (None, f["rule"])
        ]

    def tool_calls(self, env=None):
        env = env or self.default_env()
        log = env / "calls.jsonl"
        if not log.exists():
            return []
        return [json.loads(line) for line in log.read_text().splitlines()]

    def default_env(self):
        return self.tools / "ruff-0.9.6_mypy-1.15.0"


class InstalacionTest(CalidadTestCase):
    def test_instala_herramientas_una_sola_vez(self):
        self.create("demo")
        self.create("otro", microservices=("billing",))
        for _ in range(2):
            report = self.report()
            self.assertEqual(self.calidad_of(report), (100, None))
            self.assertEqual(self.calidad_of(report, "otro"), (100, None))
        # Un solo pip para los dos proyectos y las dos corridas, con las
        # versiones del equipo, en el entorno propio de seedflow.
        self.assertEqual(len(self.installer.pips), 1)
        env, packages = self.installer.pips[0]
        self.assertEqual(packages, ["ruff==0.9.6", "mypy==1.15.0"])
        self.assertEqual(env.parent, self.tools)
        self.assertEqual(sorted(p.name for p in self.tools.iterdir()),
                         ["ruff-0.9.6_mypy-1.15.0"])
        self.assertTrue(self.tool_calls())  # y las herramientas sí corrieron

    def test_sin_seedflow_tools_dir_usa_la_cache_de_seedflow(self):
        self.create("demo")
        home = self.base / "home"
        home.mkdir()
        env = {k: v for k, v in os.environ.items() if k != "SEEDFLOW_TOOLS_DIR"}
        env["HOME"] = str(home)
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(self.calidad_of(self.report()), (100, None))
        expected = home / ".cache" / "seedflow" / "tools"
        self.assertEqual(self.installer.pips[0][0].parent, expected)
        self.assertTrue((expected / "ruff-0.9.6_mypy-1.15.0").is_dir())
        self.assertFalse(self.tools.exists())

    def test_en_windows_usa_localappdata(self):
        local = self.base / "local"
        env = {k: v for k, v in os.environ.items() if k != "SEEDFLOW_TOOLS_DIR"}
        env["LOCALAPPDATA"] = str(local)
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(self.calidad, "WINDOWS", True):
            self.assertEqual(
                self.calidad.tools_home(), local / "seedflow" / "tools"
            )
            self.assertEqual(
                self.calidad.python_of(local),
                local / "Scripts" / "python.exe",
            )
            del os.environ["LOCALAPPDATA"]
            self.assertEqual(
                self.calidad.tools_home(),
                Path.home() / "AppData" / "Local" / "seedflow" / "tools",
            )

    def test_si_la_instalacion_falla_calidad_no_se_evalua(self):
        self.create("demo")
        self.add_code(self.errors("ERR_RUFF", 3))
        for fail in ["pip", "venv"]:
            with self.subTest(falla=fail):
                self.use_installer(FakeInstaller(fail=fail))
                report = self.report()
                score, reason = self.calidad_of(report)
                self.assertIsNone(score)
                self.assertIn("ruff 0.9.6", reason)
                self.assertIn("mypy 1.15.0", reason)
                self.assertIn("roto" if fail == "venv" else "sin internet",
                              reason)
                self.assertEqual(self.findings(report), [])
                # No queda un entorno a medias que la próxima vez se use.
                self.assertEqual(list(self.tools.iterdir()), [])
        # Cuando vuelve a haber internet, se instala y se evalúa.
        self.use_installer(FakeInstaller())
        self.assertEqual(self.calidad_of(self.report())[0], 94)

    def test_versiones_salen_del_requirements_del_proyecto(self):
        self.create("demo")
        self.create("otro", microservices=("billing",))
        self.create("viejo", microservices=("legacy",))
        requirements = self.root / "projects/demo/python/requirements.txt"
        text = requirements.read_text()
        self.assertIn("ruff==0.9.6", text)
        requirements.write_text(
            text.replace("ruff==0.9.6", "Ruff == 0.11.2  # linter")
            .replace("mypy==1.15.0", "mypy==1.16.1")
        )
        # Sin versión fija (o sin requirements) se usan las del equipo.
        (self.root / "projects/viejo/python/requirements.txt").write_text(
            "ruff>=0.5\nmypyx==9.9\n"
        )
        (self.root / "projects/otro/python/requirements.txt").unlink()
        report = self.report()
        for name in ["demo", "otro", "viejo"]:
            self.assertEqual(self.calidad_of(report, name), (100, None))
        self.assertEqual(
            sorted(packages for _, packages in self.installer.pips),
            [["ruff==0.11.2", "mypy==1.16.1"], ["ruff==0.9.6", "mypy==1.15.0"]],
        )
        self.assertEqual(
            sorted(p.name for p in self.tools.iterdir()),
            ["ruff-0.11.2_mypy-1.16.1", "ruff-0.9.6_mypy-1.15.0"],
        )
        self.assertTrue(self.tool_calls(self.tools / "ruff-0.11.2_mypy-1.16.1"))

    def test_proyecto_sin_microservicios_no_instala_nada(self):
        self.create("demo", microservices=())
        score, reason = self.calidad_of(self.report())
        self.assertIsNone(score)
        self.assertIn("microservicios", reason)
        self.assertEqual(self.installer.pips, [])
        self.assertFalse(self.tools.exists())

    def test_quick_no_corre_calidad(self):
        self.create("demo")
        self.add_code(self.errors("ERR_RUFF", 3))
        report = self.report("--quick")
        score, reason = self.calidad_of(report)
        self.assertIsNone(score)
        self.assertTrue(reason)
        self.assertEqual(self.findings(report), [])
        self.assertEqual(self.installer.venvs, [])
        self.assertFalse(self.tools.exists())
        code, out, err = self.run_cli("check", "--quick")
        self.assertEqual(code, 0, err)
        self.assertEqual(len(out.splitlines()), 1)
        self.assertEqual(self.installer.venvs, [])


class ReglasTest(CalidadTestCase):
    def test_microservicio_recien_creado_no_tiene_hallazgos(self):
        self.create("demo", microservices=("orders", "billing"))
        report = self.report()
        self.assertEqual(self.findings(report), [])
        self.assertEqual(self.calidad_of(report), (100, None))

    def test_errores_de_ruff_descuentan_dos_cada_uno_con_tope(self):
        self.create("demo", microservices=("orders", "billing", "uno"))
        self.add_code(self.errors("ERR_RUFF", 3), name="orders")
        self.add_code(self.errors("ERR_RUFF", 40), name="billing")
        self.add_code(self.errors("ERR_RUFF", 1), name="uno")
        report = self.report()
        found = {f["path"].rsplit("/", 1)[-1]: f
                 for f in self.findings(report, "C1")}
        self.assertEqual(
            {name: f["points"] for name, f in found.items()},
            {"orders": 6, "billing": 30, "uno": 2},
        )
        orders = found["orders"]
        self.assertEqual(orders["path"], ORDERS)
        self.assertEqual(orders["project"], "demo")
        self.assertIn("3", orders["message"])
        # Rutas relativas al microservicio, no absolutas.
        self.assertIn(": src/service/extra.py:1 ", orders["message"])
        self.assertTrue(orders["why"] and orders["how"])
        # De 40 errores muestra los primeros y cuántos más hay.
        self.assertIn("y 37 más", found["billing"]["message"])
        self.assertIsNone(orders["fix_id"])  # ninguno se arregla solo
        self.assertEqual(self.findings(report, "C3"), [])
        self.assertEqual(self.calidad_of(report)[0], 100 - 6 - 30 - 2)

    def test_ruff_corre_con_las_reglas_del_proyecto_y_sin_escribir_cache(self):
        self.create("demo")
        self.report()
        ruff = [c for c in self.tool_calls() if c["argv"][1] == "ruff"]
        self.assertEqual(len(ruff), 2)  # check y format --check
        pyproject = str(self.root / "projects/demo/python/pyproject.toml")
        for call in ruff:
            argv = call["argv"]
            self.assertIn("--no-cache", argv)
            self.assertEqual(argv[argv.index("--config") + 1], pyproject)
            self.assertIn("--force-exclude", argv)
            # Recibe los archivos del microservicio, no la carpeta.
            self.assertEqual(
                [a for a in argv if a.endswith(".py")],
                [str(p) for p in sorted(self.microservice().rglob("*.py"))],
            )
            self.assertNotIn(str(self.microservice()), argv)
            self.assertNotIn(str(self.root), call["cwd"])
        self.assertIn("--check", ruff[1]["argv"])

    def test_sin_pyproject_ruff_y_mypy_no_leen_configuracion_ajena(self):
        self.create("demo")
        (self.root / "projects/demo/python/pyproject.toml").unlink()
        self.assertEqual(self.calidad_of(self.report()), (100, None))
        for call in self.tool_calls():
            argv = call["argv"]
            if argv[1] == "ruff":
                self.assertIn("--isolated", argv)
                self.assertNotIn("--config", argv)
            else:
                self.assertIn("--config-file=", argv)

    def test_errores_de_mypy_descuentan_dos_cada_uno_con_tope(self):
        self.create("demo", microservices=("orders", "billing"))
        self.add_code(self.errors("ERR_MYPY", 4), name="orders")
        self.add_code(self.errors("ERR_MYPY", 16), name="billing")
        report = self.report()
        found = {f["path"].rsplit("/", 1)[-1]: f
                 for f in self.findings(report, "C3")}
        # Las notas de mypy no cuentan como errores.
        self.assertEqual(
            {name: f["points"] for name, f in found.items()},
            {"orders": 8, "billing": 30},
        )
        self.assertEqual(found["orders"]["path"], ORDERS)
        self.assertIn("4", found["orders"]["message"])
        self.assertIn(": src/service/extra.py:1", found["orders"]["message"])
        self.assertIsNone(found["orders"]["fix_id"])
        self.assertEqual(self.findings(report, "C1"), [])
        self.assertEqual(self.calidad_of(report)[0], 62)

    def test_mypy_usa_su_cache_en_el_entorno_de_herramientas(self):
        self.create("demo")
        self.report()
        mypy = [c for c in self.tool_calls() if c["argv"][1] == "mypy"]
        self.assertEqual(len(mypy), 1)
        argv = mypy[0]["argv"]
        cache = Path(argv[argv.index("--cache-dir") + 1])
        self.assertIn(self.default_env(), cache.parents)
        pyproject = self.root / "projects/demo/python/pyproject.toml"
        self.assertIn(f"--config-file={pyproject}", argv)
        self.assertIn("--no-error-summary", argv)
        # Recibe los .py del microservicio, no la carpeta.
        self.assertEqual(
            [a for a in argv if a.endswith(".py")],
            [str(p) for p in sorted(self.microservice().rglob("*.py"))],
        )
        self.assertNotIn(str(self.microservice()), argv)
        self.assertNotIn(str(self.root), mypy[0]["cwd"])

    def test_microservicio_sin_codigo_no_corre_ruff_ni_mypy(self):
        # Sin archivos, ruff revisaría la carpeta donde corre y mypy se queja.
        self.create("demo")
        for path in self.microservice().rglob("*.py"):
            path.unlink()
        self.assertEqual(self.calidad_of(self.report()), (100, None))
        self.assertEqual(self.tool_calls(), [])
        for prefix in ["C1", "C2"]:
            self.assertEqual(
                self.calidad.FIXES[prefix](
                    self.root, f"{prefix}:demo/internal-services/orders"
                ),
                [],
            )
        self.assertEqual(self.tool_calls(), [])

    def test_format_pendiente_es_menor_con_arreglo(self):
        self.create("demo", microservices=("orders", "billing"))
        self.add_code("y = 1  # UNFORMATTED\n", name="orders")
        self.add_code("z = 2  # UNFORMATTED\n", name="orders",
                      filename="src/handler.py")
        report = self.report()
        found = self.findings(report, "C2")
        self.assertEqual(len(found), 1)  # uno por microservicio
        [finding] = found
        self.assertEqual(finding["points"], 3)
        self.assertEqual(finding["path"], ORDERS)
        self.assertIn("2", finding["message"])
        self.assertEqual(finding["fix_id"], "C2:demo/internal-services/orders")
        self.assertEqual(self.calidad_of(report)[0], 97)

        touched = self.calidad.FIXES["C2"](self.root, finding["fix_id"])
        self.assertEqual(
            sorted(Path(p) for p in touched),
            [self.microservice() / "src/handler.py",
             self.microservice() / "src/service/extra.py"],
        )
        report = self.report()
        self.assertEqual(self.findings(report, "C2"), [])
        self.assertEqual(self.calidad_of(report)[0], 100)

    def test_ruff_check_fix_es_un_arreglo_aparte(self):
        self.create("demo", microservices=("orders", "billing"))
        self.add_code(self.errors("ERR_RUFF_FIX", 2) + self.errors("ERR_RUFF", 1))
        self.add_code(self.errors("ERR_RUFF_FIX", 1), name="billing")
        self.add_code("w = 1  # UNFORMATTED\n", name="billing")
        report = self.report()
        [finding] = [f for f in self.findings(report, "C1")
                     if f["path"] == ORDERS]
        self.assertEqual(finding["points"], 6)
        self.assertEqual(finding["fix_id"], "C1:demo/internal-services/orders")
        self.assertIn("ruff check --fix", finding["how"])
        self.assertIn("2", finding["how"])  # arregla 2 de los 3

        touched = self.calidad.FIXES["C1"](self.root, finding["fix_id"])
        self.assertEqual(touched, [self.microservice() / "src/service/extra.py"])
        report = self.report()
        [finding] = [f for f in self.findings(report, "C1")
                     if f["path"] == ORDERS]
        self.assertEqual(finding["points"], 2)  # queda el que no tiene arreglo
        self.assertIsNone(finding["fix_id"])
        # Solo tocó ese microservicio, y no formateó nada.
        billing = [f["path"] for f in self.findings(report)
                   if f["path"] != ORDERS]
        self.assertEqual(len(billing), 2)  # C1 y C2 de billing siguen

    def test_un_arreglo_sin_cambios_no_devuelve_archivos(self):
        self.create("demo")
        for prefix in ["C1", "C2"]:
            with self.subTest(arreglo=prefix):
                self.assertEqual(
                    self.calidad.FIXES[prefix](
                        self.root, f"{prefix}:demo/internal-services/orders"
                    ),
                    [],
                )

    def test_arreglo_con_id_invalido_falla_sin_tocar_nada(self):
        self.create("demo")
        self.add_code("y = 1  # UNFORMATTED\n")
        for fix_id in [
            "C2:demo/internal-services",
            "C2:../demo/internal-services/orders",
            "C2:demo/otra-cosa/orders",
            "C2:demo/internal-services/no-existe",
            "C1:demo/internal-services/orders/src",
        ]:
            with self.subTest(fix_id=fix_id):
                prefix = fix_id.split(":")[0]
                with self.assertRaises(Exception) as error:
                    self.calidad.FIXES[prefix](self.root, fix_id)
                self.assertEqual(type(error.exception).__name__, "SeedError")
        self.assertEqual(len(self.findings(self.report(), "C2")), 1)

    def test_arreglo_sin_herramientas_falla_con_el_motivo(self):
        self.create("demo")
        self.use_installer(FakeInstaller(fail="pip"))
        with self.assertRaises(Exception) as error:
            self.calidad.FIXES["C2"](
                self.root, "C2:demo/internal-services/orders"
            )
        self.assertEqual(type(error.exception).__name__, "SeedError")
        self.assertIn("sin internet", str(error.exception))

    def test_todos_pendientes_es_un_solo_hallazgo_por_microservicio(self):
        self.create("demo", microservices=("orders", "billing"))
        self.add_code("# TODO: validar el evento\nx = 1  # TODO otro\n")
        handler = self.add_code("# TODO: y este\n", filename="src/handler.py")
        row = len(handler.read_text().splitlines())
        # "todo" en minúscula es una palabra, no un pendiente; TODOS tampoco.
        self.add_code('"""Procesa todo el evento."""\n# TODOS los casos\n',
                      name="billing")
        report = self.report()
        found = self.findings(report, "C4")
        self.assertEqual(len(found), 1)
        [finding] = found
        self.assertEqual(finding["points"], 3)
        self.assertEqual(finding["path"], ORDERS)
        self.assertEqual(
            finding["message"],
            f"3 TODO pendientes: src/handler.py:{row}, "
            "src/service/extra.py:1, src/service/extra.py:2",
        )
        self.assertIsNone(finding["fix_id"])
        self.assertEqual(self.calidad_of(report)[0], 97)

    def test_todos_fuera_de_python_no_cuentan(self):
        self.create("demo")
        self.add_code("TODO\n", filename="layers/requirements.txt")
        self.add_code("# TODO\n", filename="events/notas.md")
        self.assertEqual(self.findings(self.report(), "C4"), [])

    def test_entornos_y_caches_del_microservicio_no_descuentan(self):
        self.create("demo")
        code = (self.errors("ERR_RUFF", 3) + self.errors("ERR_MYPY", 3)
                + "y = 1  # UNFORMATTED\n# TODO\n")
        ignored = self.checks.IGNORED_DIRS
        self.assertTrue({".venv", "venv", "node_modules"} <= ignored)
        for folder in sorted(ignored):
            self.add_code(code, filename=f"{folder}/lib/x.py")
        report = self.report()
        self.assertEqual(self.findings(report), [])
        self.assertEqual(self.calidad_of(report), (100, None))
        for call in self.tool_calls():
            self.assertFalse(
                [a for a in call["argv"] if "/lib/x.py" in a], call["argv"]
            )
        # Los arreglos tampoco las tocan ni las cuentan.
        touched = self.calidad.FIXES["C2"](
            self.root, "C2:demo/internal-services/orders"
        )
        self.assertEqual(touched, [])
        venv = self.microservice() / ".venv/lib/x.py"
        self.assertIn("UNFORMATTED", venv.read_text())

    def test_herramienta_que_falla_deja_el_proyecto_sin_evaluar(self):
        self.create("demo")
        self.create("otro", microservices=("billing",))
        self.report()  # instala
        for tool in ["ruff", "mypy"]:
            with self.subTest(herramienta=tool):
                fail = self.default_env() / f"fail-{tool}"
                fail.write_text(f"{tool} explotó")
                try:
                    report = self.report()
                finally:
                    fail.unlink()
                score, reason = self.calidad_of(report)
                self.assertIsNone(score)
                self.assertIn(f"{tool} explotó", reason)
                self.assertEqual(self.findings(report), [])

    def test_salida_de_ruff_que_no_es_json_deja_el_proyecto_sin_evaluar(self):
        self.create("demo")
        self.report()  # instala
        fake = self.default_env() / "fake_tools.py"
        fake.write_text(
            fake.read_text().replace(
                "print(json.dumps(found))", "print('no soy json')"
            )
        )
        score, reason = self.calidad_of(self.report())
        self.assertIsNone(score)
        self.assertIn("ruff", reason)

    def test_check_con_calidad_no_escribe_en_el_repo(self):
        self.create("demo")
        self.add_code(self.errors("ERR_RUFF_FIX", 2) + "y = 1  # UNFORMATTED\n"
                      + self.errors("ERR_MYPY", 1) + "# TODO\n")

        def snapshot():
            result = {}
            for path in sorted(self.root.rglob("*")):
                content = (hashlib.sha256(path.read_bytes()).hexdigest()
                           if path.is_file() else None)
                result[path.relative_to(self.root).as_posix()] = (
                    path.lstat().st_mtime_ns, content
                )
            return result

        before = snapshot()
        report = self.report()
        self.assertEqual(
            sorted(f["rule"] for f in self.findings(report)),
            ["C1", "C2", "C3", "C4"],
        )
        code, out, err = self.run_cli("check")
        self.assertEqual(code, 0, err)
        self.assertIn("C2:demo/internal-services/orders", out)
        self.assertEqual(snapshot(), before)


class ContratoTest(CalidadTestCase):
    def test_modulo_cumple_el_contrato(self):
        self.assertEqual(self.calidad.CATEGORY, "calidad")
        self.assertIs(self.calidad.QUICK, False)
        self.assertEqual(sorted(self.calidad.FIXES), ["C1", "C2"])
        self.assertIn(
            self.calidad, self.seedflow.discover_rules()
        )


if __name__ == "__main__":
    unittest.main()
