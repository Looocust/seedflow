"""Tests de las reglas de dependencias (scripts/checks/dependencias.py).

Cada test arma un proyecto real con el script (create-project y
create-microservice), cambia sus requirements o su código y califica con
`check --json`, corriendo solo el módulo de dependencias.

Solo librería estándar. Desde la raíz del repo:

    python3 -m unittest tests.test_check_dependencias -v

SEEDFLOW_SCRIPT permite apuntar a otra copia del script (lo usa
tests/mutantes.py para comprobar que los tests detectan fallas).
"""

from __future__ import annotations

import contextlib
import importlib
import importlib.util
import io
import json
import os
import re
import shutil
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
LIBRERIAS = REPO / "plugins" / "seedflow" / "references" / "librerias.md"

# SHAs que trae python/requirements.txt en la plantilla del proyecto.
AWS_SHA = "e82ce8716b324187407f4484f7c61d603a9730b8"
REDSHIFT_SHA = "e1af265513a1df6a72f8079f055251fdeacb866b"
SLACK_SHA = "fb47159d82d3b998be89a0f4890a2f0f999b61db"
OTRO_SHA = "0123456789abcdef0123456789abcdef01234567"
INTERNAL = "internal-services"


def load_seedflow():
    """Carga el script como módulo, fresco en cada test."""
    spec = importlib.util.spec_from_file_location("seedflow_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def lib(repo, ref=None):
    """La línea de requirements de una librería Melonn."""
    url = f"git+https://github.com/we-are-melonn/{repo}.git"
    return url if ref is None else f"{url}@{ref}"


class DependenciasTestCase(unittest.TestCase):
    """Base: una raíz temporal fuera de git con proyectos de verdad."""

    def setUp(self):
        self.seedflow = load_seedflow()
        self.seedflow.load_checks()
        self.rules = importlib.import_module("checks.dependencias")
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name).resolve()
        self.root = self.base / "repo"
        self.root.mkdir()
        patcher = mock.patch.dict(
            os.environ, {"GIT_CEILING_DIRECTORIES": str(self.base)}
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    # -- ayudas ------------------------------------------------------------

    def run_cli(self, *argv):
        """Corre el script y devuelve (código, stdout, stderr)."""
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = self.seedflow.main(["--root", str(self.root), *argv])
            except SystemExit as error:  # errores de argparse
                code = error.code
        return code, out.getvalue(), err.getvalue()

    def create_project(self, name="demo"):
        code, out, err = self.run_cli(
            "create-project", name, "--service-type", INTERNAL, "--skip-cdk"
        )
        self.assertEqual(code, 0, out + err)

    def create_microservice(self, name, project="demo",
                            service_type=INTERNAL, *extra):
        code, out, err = self.run_cli(
            "create-microservice", name, "--project", project,
            "--service-type", service_type, *extra,
        )
        self.assertEqual(code, 0, out + err)

    def check(self):
        """`check --json` corriendo solo las reglas de dependencias."""
        with mock.patch.object(
            self.seedflow, "discover_rules", return_value=[self.rules]
        ):
            code, out, err = self.run_cli("check", "--json")
        self.assertEqual(code, 0, out + err)
        return json.loads(out)

    def findings(self, report):
        return [f for f in report["findings"] if f["category"] == "dependencias"]

    def project(self, report, name="demo"):
        return next(p for p in report["projects"] if p["name"] == name)

    def python_reqs(self, project="demo"):
        return f"projects/{project}/python/requirements.txt"

    def layers(self, name, project="demo", service_type=INTERNAL):
        return (
            f"projects/{project}/python/{service_type}/{name}/layers/"
            "requirements.txt"
        )

    def src(self, name, *parts, project="demo", service_type=INTERNAL):
        return "/".join(
            [f"projects/{project}/python/{service_type}/{name}/src", *parts]
        )

    def write(self, relative, text):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def line_count(self, relative):
        return len((self.root / relative).read_text(encoding="utf-8")
                   .splitlines())

    def append(self, relative, *lines):
        path = self.root / relative
        text = path.read_text(encoding="utf-8")
        if text and not text.endswith("\n"):
            text += "\n"
        path.write_text(text + "".join(f"{line}\n" for line in lines),
                        encoding="utf-8")


class ProyectoNuevoTest(DependenciasTestCase):
    def test_proyecto_nuevo_no_tiene_hallazgos_de_dependencias(self):
        self.create_project("solo")
        self.create_project("demo")
        self.create_microservice("orders")
        self.create_microservice(
            "api", "demo", "consumable-services", "--database"
        )
        report = self.check()
        self.assertEqual(self.findings(report), [])
        for project in report["projects"]:
            with self.subTest(proyecto=project["name"]):
                self.assertEqual(project["categories"]["dependencias"], 100)
                self.assertNotIn("dependencias", project["not_evaluated"])

    def test_cumple_el_contrato_y_no_tiene_arreglos(self):
        self.assertEqual(self.rules.CATEGORY, "dependencias")
        self.assertIs(self.rules.QUICK, True)
        self.assertEqual(getattr(self.rules, "FIXES", {}), {})
        self.assertIn(
            "dependencias",
            [m.CATEGORY for m in self.seedflow.discover_rules()],
        )


class ShaTest(DependenciasTestCase):
    def test_libreria_sin_sha_o_con_main(self):
        self.create_project()
        self.create_microservice("orders")
        # Los números de línea dependen de lo que ya trae cada plantilla.
        en_python = self.line_count(self.python_reqs())
        en_layers = self.line_count(self.layers("orders"))
        sin_arroba = lib("lib-python-melogger")
        con_main = lib("lib-python-validator", "main") + "  # TODO: fijar SHA"
        self.append(
            self.python_reqs(),
            sin_arroba,
            con_main,
            "# " + lib("lib-python-google-connector"),  # comentada: no cuenta
        )
        main_en_layers = lib("lib-python-aws-utils", "main")
        con_tag = lib("lib-python-custom-errors", "v1.2.0")
        self.append(
            self.layers("orders"),
            main_en_layers,
            con_tag,
            "lib-python-redshift-connector @ "
            + lib("lib-python-redshift-connector", REDSHIFT_SHA[:7]),
            lib("lib-python-slack-notifier", SLACK_SHA)
            + "#egg=lib-python-slack-notifier",
            "pandas==2.2.3",
        )
        report = self.check()
        found = self.findings(report)
        self.assertEqual(
            sorted((f["rule"], f["points"], f["path"]) for f in found),
            sorted([
                ("D1", 10, self.python_reqs()),
                ("D1", 10, self.python_reqs()),
                ("D1", 10, self.layers("orders")),
                ("D1", 10, self.layers("orders")),
            ]),
        )
        messages = {f["path"]: [] for f in found}
        for finding in found:
            messages[finding["path"]].append(finding["message"])
            self.assertEqual(finding["project"], "demo")
            self.assertIsNone(finding["fix_id"])
            self.assertTrue(finding["why"])
            self.assertTrue(finding["how"])
        # Cada hallazgo trae la línea exacta (y su número).
        for path, lines in [
            (self.python_reqs(),
             [(sin_arroba, en_python + 1), (con_main, en_python + 2)]),
            (self.layers("orders"),
             [(main_en_layers, en_layers + 1), (con_tag, en_layers + 2)]),
        ]:
            for line, number in lines:
                with self.subTest(linea=line):
                    self.assertTrue(
                        any(line in m and f"línea {number}" in m
                            for m in messages[path]),
                        messages[path],
                    )
        self.assertEqual(self.project(report)["categories"]["dependencias"], 60)

    def test_libreria_sin_url_o_con_version_estilo_pypi_es_d1(self):
        self.create_project()
        self.create_microservice("orders")
        en_python = self.line_count(self.python_reqs())
        en_layers = self.line_count(self.layers("orders"))
        lineas_python = [
            "lib-python-aws-utils==1.0.0",
            "  lib-python-melogger",
            "lib-python-validator>=2 ; python_version >= '3.8'",
        ]
        lineas_layers = [
            "lib-python-redshift-connector",
            "\tlib-python-custom-errors~=1.0",
            "lib-python-slack-notifier[extra]",
        ]
        self.append(self.python_reqs(), *lineas_python)
        self.append(self.layers("orders"), *lineas_layers)
        report = self.check()
        found = self.findings(report)
        esperados = [
            (self.python_reqs(), en_python + i + 1, linea)
            for i, linea in enumerate(lineas_python)
        ] + [
            (self.layers("orders"), en_layers + i + 1, linea)
            for i, linea in enumerate(lineas_layers)
        ]
        self.assertEqual(len(found), len(esperados), found)
        for path, number, linea in esperados:
            with self.subTest(linea=linea):
                matches = [
                    f for f in found
                    if f["path"] == path
                    and f"(línea {number}: {linea})" in f["message"]
                ]
                self.assertEqual(len(matches), 1, found)
                self.assertEqual(matches[0]["rule"], "D1")
                self.assertEqual(matches[0]["points"], 10)
        self.assertEqual(self.project(report)["categories"]["dependencias"], 40)

    def test_hallazgo_trae_la_linea_tal_cual(self):
        self.create_project()
        self.create_microservice("orders")
        numero = self.line_count(self.layers("orders")) + 1
        linea = "   " + lib("lib-python-aws-utils", "main") + "   "
        self.append(self.layers("orders"), linea)
        found = self.findings(self.check())
        self.assertEqual(len(found), 1, found)
        self.assertTrue(
            found[0]["message"].endswith(f"(línea {numero}: {linea})"),
            found[0]["message"],
        )

    def test_sha_distinto_entre_layers_y_python(self):
        self.create_project()
        self.create_microservice("orders")
        self.create_microservice("billing")
        self.append(
            self.layers("orders"),
            lib("lib-python-aws-utils", OTRO_SHA),  # distinto: cuenta
            # El mismo commit escrito corto: no cuenta.
            lib("lib-python-redshift-connector", REDSHIFT_SHA[:7]),
            # No está en python/requirements.txt: no hay con qué comparar.
            lib("lib-python-google-connector", OTRO_SHA),
            # @main ya descuenta como D1; aquí no se compara.
            lib("lib-python-slack-notifier", "main"),
        )
        self.append(self.layers("billing"), lib("lib-python-aws-utils", AWS_SHA))
        report = self.check()
        d2 = [f for f in self.findings(report) if f["rule"] == "D2"]
        self.assertEqual(len(d2), 1, d2)
        finding = d2[0]
        self.assertEqual(finding["points"], 3)
        self.assertEqual(finding["project"], "demo")
        self.assertEqual(finding["path"], self.layers("orders"))
        for text in ["lib-python-aws-utils", OTRO_SHA, AWS_SHA,
                     self.python_reqs()]:
            with self.subTest(texto=text):
                self.assertIn(text, finding["message"])
        self.assertEqual(
            [f["rule"] for f in self.findings(report)], ["D1", "D2"]
        )
        self.assertEqual(self.project(report)["categories"]["dependencias"], 87)

    def test_no_lee_a_traves_de_enlaces(self):
        self.create_project()
        self.create_microservice("orders")
        afuera = self.base / "afuera.txt"
        afuera.write_text(lib("lib-python-aws-utils", "main") + "\n")
        codigo = self.base / "codigo.py"
        codigo.write_text("from we_are_melonn.melogger import Melogger\n")
        layers = self.root / self.layers("orders")
        layers.unlink()
        try:
            layers.symlink_to(afuera)
            (self.root / self.src("orders", "enlazado.py")).symlink_to(codigo)
        except (OSError, NotImplementedError):
            self.skipTest("este sistema no permite crear enlaces simbólicos")
        report = self.check()
        self.assertEqual(self.findings(report), [])


class ImportsTest(DependenciasTestCase):
    def test_import_sin_libreria_en_layers(self):
        self.create_project()
        self.create_microservice("orders")
        self.create_microservice("billing")
        self.append(
            self.layers("orders"),
            lib("lib-python-aws-utils", AWS_SHA),
            "# " + lib("lib-python-validator", OTRO_SHA),  # comentada
        )
        # billing sí la tiene, pero no cuenta para orders.
        self.append(
            self.layers("billing"), lib("lib-python-melogger", OTRO_SHA)
        )
        handler = self.root / self.src("orders", "handler.py")
        handler.write_text(
            "from melonnAWSUtils.s3 import S3\n"
            "from we_are_melonn.melogger import Melogger\n"
            "from we_are_melonn.melogger import System\n"
            + handler.read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        self.write(
            self.src("orders", "service", "main.py"),
            "import melonnValidator.event_validator\n"
            "from we_are_melonn import slack_notifier\n\n\n"
            "def main(event):\n"
            "    from melonnCustomErrors.custom_errors import "
            "LambdaExecutionError\n"
            "    return {}\n",
        )
        # No parsea: no se cuenta acá (lo marca calidad de código).
        self.write(
            self.src("orders", "service", "roto.py"),
            "from we_are_melonn.google_notifier import GoogleChatNotifier\n"
            "def (:\n",
        )
        report = self.check()
        found = self.findings(report)
        self.assertEqual(
            sorted((f["rule"], f["points"], f["path"]) for f in found),
            [("D3", 10, self.layers("orders"))] * 4,
        )
        repos = {
            "lib-python-melogger": "src/handler.py",
            "lib-python-validator": "src/service/main.py",
            "lib-python-slack-notifier": "src/service/main.py",
            "lib-python-custom-errors": "src/service/main.py",
        }
        for repo, archivo in repos.items():
            with self.subTest(repo=repo):
                matches = [f for f in found if repo in f["message"]]
                self.assertEqual(len(matches), 1, found)
                self.assertIn(archivo, matches[0]["message"])
                self.assertEqual(matches[0]["project"], "demo")
                self.assertIsNone(matches[0]["fix_id"])
        self.assertEqual(self.project(report)["categories"]["dependencias"], 60)

    def test_import_de_terceros_no_cuenta(self):
        self.create_project()
        self.create_microservice("orders")
        self.write(
            self.src("orders", "service", "main.py"),
            "import boto3\n"
            "import pandas as pd\n"
            "from dotenv import load_dotenv\n"
            "from service.helpers import ayuda\n"
            "from .database import conexion\n"
            "import we_are_melonn\n"
            "import melonnLocal\n"
            "from melonnRouterUtils.routerUtils import Router\n"
            "from we_are_melonnish.melogger import Melogger\n"
            # Relativo: es código del propio microservicio, no la librería.
            "from .we_are_melonn.melogger import Melogger as Local\n",
        )
        report = self.check()
        self.assertEqual(self.findings(report), [])
        self.assertEqual(
            self.project(report)["categories"]["dependencias"], 100
        )

    def test_import_dentro_de_venv_no_cuenta(self):
        self.create_project()
        self.create_microservice("orders")
        melogger = "from we_are_melonn.melogger import Melogger\n"
        for venv in [
            "projects/demo/.venv/lib/python3.12/site-packages/x.py",
            "projects/demo/python/.venv/lib/python3.12/site-packages/x.py",
            self.src("orders", ".venv", "lib", "x.py"),
            self.src("orders", "venv", "x.py"),
            self.src("orders", "node_modules", "x.py"),
        ]:
            self.write(venv, melogger)
        report = self.check()
        self.assertEqual(self.findings(report), [])
        # El mismo import en el código del microservicio sí cuenta.
        self.write(self.src("orders", "service", "logs.py"), melogger)
        found = self.findings(self.check())
        self.assertEqual([f["rule"] for f in found], ["D3"])
        self.assertIn("src/service/logs.py", found[0]["message"])
        self.assertNotIn(".venv", found[0]["message"])

    def test_carpeta_src_enlazada_no_se_lee(self):
        self.create_project()
        self.create_microservice("orders")
        afuera = self.base / "afuera_src"
        afuera.mkdir()
        (afuera / "handler.py").write_text(
            "from we_are_melonn.melogger import Melogger\n"
        )
        src = self.root / self.src("orders")
        shutil.rmtree(src)
        try:
            src.symlink_to(afuera, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("este sistema no permite crear enlaces simbólicos")
        self.assertEqual(self.findings(self.check()), [])

    def test_tabla_de_imports_es_la_de_librerias_md(self):
        tabla = {}
        fila = re.compile(
            r"^\|[^|]*\|\s*`(lib-python-[\w-]+)`\s*\|\s*`from ([\w.]+) import"
        )
        for line in LIBRERIAS.read_text(encoding="utf-8").splitlines():
            match = fila.match(line)
            if match:
                repo, module = match.groups()
                parts = module.split(".")
                key = ".".join(parts[:2] if parts[0] == "we_are_melonn"
                               else parts[:1])
                tabla[key] = repo
        self.assertEqual(len(tabla), 9, tabla)
        self.assertEqual(dict(self.rules.IMPORT_TO_REPO), tabla)


if __name__ == "__main__":
    unittest.main()
