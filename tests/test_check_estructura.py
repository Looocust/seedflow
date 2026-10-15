"""Tests de las reglas de estructura (scripts/checks/estructura.py).

Cada test arma un proyecto real con el CLI, lo rompe a propósito y revisa el
hallazgo que da `check --json`; los arreglos se prueban con FIXES.

Solo librería estándar. Desde la raíz del repo:

    python3 -m unittest tests.test_check_estructura -v

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
import shutil
import stat
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
LAUNCH = "projects/demo/python/.vscode/launch.json"
# El handler que generaba melonn-python-cli: busca el evento un nivel de más.
OLD_HANDLER = (
    '"""Module lambda handler."""\r\n'
    "\r\n"
    "import os\r\n"
    "import json\r\n"
    "import sys\r\n"
    "from pathlib import Path\r\n"
    "\r\n"
    "def run(event, stage):\r\n"
    "    print(json.dumps(event, indent=2))\r\n"
    "\r\n"
    'if __name__ == "__main__":\r\n'
    "    event_file_path = os.path.join(\r\n"
    '        os.path.dirname(__file__), f"../../events/{sys.argv[1]}.json"\r\n'
    "    )\r\n"
    "    # ../../events otra vez, en un comentario: también se cambia\r\n"
    "    run(json.loads(Path(event_file_path).read_text()), 'dev')\r\n"
)


def load_seedflow():
    """Carga el script como módulo, fresco en cada test."""
    spec = importlib.util.spec_from_file_location("seedflow_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class EstructuraTestCase(unittest.TestCase):
    """Base: un repo temporal con el proyecto demo y el microservicio orders."""

    def setUp(self):
        self.seedflow = load_seedflow()
        self.seedflow.load_checks()
        self.estructura = importlib.import_module("checks.estructura")
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name).resolve()
        self.root = self.base / "repo"
        self.root.mkdir()
        # Sin repo git por encima del temporal, y sin instalar herramientas
        # de calidad desde internet si check corre con todas las reglas.
        patcher = mock.patch.dict(
            os.environ,
            {
                "GIT_CEILING_DIRECTORIES": str(self.base),
                "SEEDFLOW_TOOLS_DIR": str(self.base / "tools"),
                "PIP_NO_INDEX": "1",
            },
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.create_project("demo")
        self.create_microservice("orders")

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

    def create_project(self, name):
        code, out, err = self.run_cli(
            "create-project", name, "--service-type", "internal-services",
            "--skip-cdk",
        )
        self.assertEqual(code, 0, out + err)

    def create_microservice(self, name, project="demo",
                            service_type="internal-services", *extra):
        code, out, err = self.run_cli(
            "create-microservice", name, "--project", project,
            "--service-type", service_type, *extra,
        )
        self.assertEqual(code, 0, out + err)

    def report(self, *extra):
        code, out, err = self.run_cli("check", "--json", *extra)
        self.assertEqual(code, 0, out + err)
        return json.loads(out)

    def findings(self, rule=None):
        """Hallazgos de estructura (de una regla, si se pide)."""
        return [
            f for f in self.report()["findings"]
            if f["category"] == "estructura" and rule in (None, f["rule"])
        ]

    def score(self, project="demo"):
        report = self.report()
        found = next(p for p in report["projects"] if p["name"] == project)
        return found["categories"]["estructura"]

    def path(self, relative):
        return self.root / relative

    def assert_finding(self, finding, rule, points, path, fix_id=None):
        self.assertEqual(finding["rule"], rule)
        self.assertEqual(finding["points"], points)
        self.assertEqual(finding["path"], path)
        self.assertEqual(finding["fix_id"], fix_id)
        for key in ("message", "why", "how"):
            self.assertIsInstance(finding[key], str)
            self.assertTrue(finding[key].strip(), key)

    def fix(self, fix_id):
        """Aplica un arreglo como lo hará `seedflow.py fix`."""
        prefix = fix_id.split(":", 1)[0]
        with contextlib.redirect_stdout(io.StringIO()):
            return self.estructura.FIXES[prefix](self.root, fix_id)

    def link(self, path, target):
        """Crea un enlace simbólico, o salta el test si no se puede."""
        try:
            path.symlink_to(target)
        except OSError:
            self.skipTest("no se pueden crear enlaces simbólicos")

    def seed_error(self):
        return self.estructura.seedflow.SeedError

    def read_launch(self, relative=LAUNCH):
        return json.loads(self.path(relative).read_text(encoding="utf-8"))

    def write_launch(self, data, relative=LAUNCH):
        self.path(relative).write_text(
            json.dumps(data, indent=4) + "\n", encoding="utf-8"
        )

    def snapshot(self):
        result = {}
        for path in sorted(self.root.rglob("*")):
            stat_result = path.lstat()
            content = (
                hashlib.sha256(path.read_bytes()).hexdigest()
                if path.is_file() else None
            )
            result[path.relative_to(self.root).as_posix()] = (
                stat_result.st_mode, stat_result.st_mtime_ns, content
            )
        return result


class ProyectoNuevoTest(EstructuraTestCase):
    def test_proyecto_nuevo_de_seedflow_no_tiene_hallazgos_de_estructura(self):
        self.create_project("vacio")  # sin microservicios
        self.create_microservice("api", "demo", "consumable-services")
        self.create_microservice("db", "demo", "internal-services",
                                 "--database")
        for extra in [(), ("--quick",)]:
            with self.subTest(args=extra):
                code, out, err = self.run_cli("check", "--json", *extra)
                self.assertEqual(code, 0, out + err)
                report = json.loads(out)
                self.assertEqual(
                    [f for f in report["findings"]
                     if f["category"] == "estructura"],
                    [],
                )
                for project in report["projects"]:
                    self.assertEqual(
                        project["categories"]["estructura"], 100,
                        project["name"],
                    )

    def test_modulo_cumple_el_contrato(self):
        self.assertEqual(self.estructura.CATEGORY, "estructura")
        self.assertIs(self.estructura.QUICK, True)
        self.assertEqual(set(self.estructura.FIXES), {"E3", "E4", "E5"})

    def test_calificar_no_escribe_aunque_todo_este_mal(self):
        shutil.rmtree(self.path("projects/demo/deployment-scripts"))
        self.path(f"{ORDERS}/events/orders.json").unlink()
        self.path(f"{ORDERS}/src/handler.py").write_text(OLD_HANDLER)
        self.write_launch({"version": "0.2.0", "configurations": []})
        self.path("projects/demo/iac/.git").mkdir()
        (self.path("projects/mal nombre")).mkdir()
        before = self.snapshot()
        self.assertGreaterEqual(len(self.findings()), 6)
        for extra in [(), ("--quick",)]:
            code, out, err = self.run_cli("check", *extra)
            self.assertEqual(code, 0, out + err)
        self.assertEqual(self.snapshot(), before)


class ProyectoTest(EstructuraTestCase):
    def test_falta_iac_o_python_o_deployment_scripts(self):
        for folder in ["deployment-scripts", "iac", "python"]:
            with self.subTest(carpeta=folder):
                name = f"sin-{folder}"
                self.create_project(name)
                shutil.rmtree(self.path(f"projects/{name}/{folder}"))
                found = [f for f in self.findings() if f["project"] == name]
                self.assertEqual(len(found), 1, found)
                self.assert_finding(
                    found[0], "E1", 10, f"projects/{name}/{folder}"
                )
                self.assertIn(folder, found[0]["message"])
                self.assertEqual(self.score(name), 90)

    def test_carpeta_de_proyecto_que_es_un_archivo_cuenta_como_faltante(self):
        shutil.rmtree(self.path("projects/demo/iac"))
        self.path("projects/demo/iac").write_text("")
        found = self.findings("E1")
        self.assertEqual([f["path"] for f in found], ["projects/demo/iac"])

    def test_iac_git_anidado_es_importante_sin_arreglo(self):
        self.path("projects/demo/iac/.git").mkdir()
        (found,) = self.findings()
        self.assert_finding(found, "E6", 10, "projects/demo/iac/.git")
        self.assertEqual(self.score(), 90)
        # .git también puede ser un archivo (worktree o submódulo).
        shutil.rmtree(self.path("projects/demo/iac/.git"))
        self.path("projects/demo/iac/.git").write_text("gitdir: ../x\n")
        self.assertEqual(
            [f["path"] for f in self.findings("E6")],
            ["projects/demo/iac/.git"],
        )

    def test_stack_iacstack_es_menor(self):
        iac = self.path("projects/demo/iac")
        (iac / "lib").mkdir()
        (iac / "bin").mkdir()
        # Lo que deja cdk init corriendo en iac/: IacStack en bin y lib.
        (iac / "lib" / "iac-stack.ts").write_text(
            "export class IacStack extends cdk.Stack {}\n"
        )
        (iac / "bin" / "iac.ts").write_text(
            "new IacStack(app, 'IacStack', {});\n"
        )
        (found,) = self.findings()
        self.assert_finding(found, "E7", 3, "projects/demo/iac/bin/iac.ts")
        self.assertIn("IacStack", found["message"])
        self.assertEqual(self.score(), 97)

        # Solo en lib/*-stack.ts también cuenta.
        (iac / "bin" / "iac.ts").write_text("new DemoStack(app, 'DemoStack');\n")
        self.assertEqual(
            [f["path"] for f in self.findings("E7")],
            ["projects/demo/iac/lib/iac-stack.ts"],
        )

        # Con el nombre del proyecto no hay hallazgo, ni por un nombre que
        # solo contiene IacStack, ni por archivos que no son el stack.
        (iac / "lib" / "iac-stack.ts").write_text(
            "export class DemoStack extends cdk.Stack {}\n"
            "export interface DemoIacStackProps {}\n"
        )
        (iac / "lib" / "notas.ts").write_text("// antes era IacStack\n")
        (iac / "bin" / "iac.js").write_text("new IacStack();\n")
        (iac / "notas.ts").write_text("// antes era IacStack\n")
        self.assertEqual(self.findings("E7"), [])

    def test_nombre_invalido_es_menor(self):
        self.path("projects/mal nombre/python").mkdir(parents=True)
        self.path("projects/con/python").mkdir(parents=True)
        services = self.path("projects/demo/python/internal-services")
        shutil.copytree(services / "orders", services / "con.punto")
        found = self.findings("E8")
        self.assertEqual(
            [(f["project"], f["path"]) for f in found],
            [
                ("con", "projects/con"),
                ("demo",
                 "projects/demo/python/internal-services/con.punto"),
                ("mal nombre", "projects/mal nombre"),
            ],
        )
        for finding in found:
            self.assert_finding(finding, "E8", 3, finding["path"])
        # Con un nombre inválido seedflow no puede arreglar nada ahí: el
        # hallazgo de launch.json queda sin arreglo automático.
        (launch,) = self.findings("E4")
        self.assertIn("con.punto", launch["message"])
        self.assertIsNone(launch["fix_id"])


class MicroservicioTest(EstructuraTestCase):
    def test_microservicio_sin_events_layers_handler_o_service(self):
        services = "projects/demo/python/internal-services"
        for name, missing in [
            ("m-events", "events"),
            ("m-layers", "layers/requirements.txt"),
            ("m-handler", "src/handler.py"),
            ("m-service", "src/service"),
        ]:
            with self.subTest(falta=missing):
                self.create_microservice(name)
                path = self.path(f"{services}/{name}/{missing}")
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink()
                found = [
                    f for f in self.findings()
                    if f["path"].startswith(f"{services}/{name}/")
                ]
                # Sin events/ tampoco se pide el evento: un solo hallazgo.
                self.assertEqual(len(found), 1, found)
                self.assert_finding(
                    found[0], "E2", 10, f"{services}/{name}/{missing}"
                )
                self.assertIn(missing, found[0]["message"])
                # Lo que tiene que ser carpeta no vale como archivo, y al revés.
                if missing in ("events", "src/service"):
                    path.write_text("")
                else:
                    path.mkdir()
                self.assertEqual(
                    [f["path"] for f in self.findings("E2")
                     if f["path"].startswith(f"{services}/{name}/")],
                    [f"{services}/{name}/{missing}"],
                )
                if path.is_dir():
                    path.rmdir()
                else:
                    path.unlink()

    def test_evento_faltante_es_menor_y_tiene_arreglo(self):
        event = self.path(f"{ORDERS}/events/orders.json")
        event.unlink()
        (self.path(f"{ORDERS}/events/otro.json")).write_text("{}")
        (found,) = self.findings()
        fix_id = "E3:demo/internal-services/orders"
        self.assert_finding(
            found, "E3", 3, f"{ORDERS}/events/orders.json", fix_id
        )
        self.assertEqual(self.score(), 97)

        self.assertEqual(self.fix(fix_id), [event])
        self.assertEqual(json.loads(event.read_text(encoding="utf-8")), {})
        self.assertEqual(self.findings(), [])
        self.assertEqual(self.score(), 100)
        # Ya está: no toca nada.
        event.write_text('{"mio": 1}')
        self.assertEqual(self.fix(fix_id), [])
        self.assertEqual(event.read_text(), '{"mio": 1}')

    def test_arreglo_de_evento_no_crea_events(self):
        shutil.rmtree(self.path(f"{ORDERS}/events"))
        with self.assertRaises(self.seed_error()):
            self.fix("E3:demo/internal-services/orders")
        self.assertFalse(self.path(f"{ORDERS}/events").exists())

    def test_handler_con_ruta_rota_es_importante_y_se_arregla(self):
        handler = self.path(f"{ORDERS}/src/handler.py")
        handler.write_bytes(OLD_HANDLER.encode("utf-8"))
        handler.chmod(0o640)
        (found,) = self.findings()
        fix_id = "E5:demo/internal-services/orders"
        self.assert_finding(
            found, "E5", 10, f"{ORDERS}/src/handler.py", fix_id
        )
        self.assertIn("../../events", found["message"])
        self.assertEqual(self.score(), 90)

        self.assertEqual(self.fix(fix_id), [handler])
        # Solo cambia ese texto: el resto (incluidos los \r\n) queda igual.
        self.assertEqual(
            handler.read_bytes(),
            OLD_HANDLER.replace("../../events", "../events").encode("utf-8"),
        )
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE(handler.stat().st_mode), 0o640)
        self.assertEqual(self.findings(), [])
        self.assertEqual(self.score(), 100)
        self.assertEqual(self.fix(fix_id), [])

    def test_handler_nuevo_no_tiene_la_ruta_rota(self):
        handler = self.path(f"{ORDERS}/src/handler.py")
        before = handler.read_bytes()
        self.assertEqual(
            self.fix("E5:demo/internal-services/orders"), []
        )
        self.assertEqual(handler.read_bytes(), before)
        handler.unlink()
        with self.assertRaises(self.seed_error()):
            self.fix("E5:demo/internal-services/orders")
        self.assertFalse(handler.exists())


class EnlacesYCarpetasTest(EstructuraTestCase):
    def test_evento_que_es_carpeta_no_cuenta_y_no_se_arregla(self):
        event = self.path(f"{ORDERS}/events/orders.json")
        event.unlink()
        event.mkdir()
        (event / "algo.txt").write_text("mío")
        (found,) = self.findings()
        self.assert_finding(found, "E3", 3, f"{ORDERS}/events/orders.json")
        self.assertIn("carpeta", found["message"])
        with self.assertRaises(self.seed_error()):
            self.fix("E3:demo/internal-services/orders")
        self.assertEqual((event / "algo.txt").read_text(), "mío")

@unittest.skipIf(os.name == "nt", "enlaces simbólicos en Windows")
class EnlacesTest(EstructuraTestCase):
    """Lo que está detrás de un enlace no se revisa ni descuenta: se avisa."""

    def setUp(self):
        super().setUp()
        self.afuera = self.base / "afuera"
        self.afuera.mkdir()

    def assert_only_notices(self, *expected):
        """Los hallazgos son exactamente estos avisos de 0 puntos."""
        found = self.findings()
        self.assertEqual(
            sorted((f["rule"], f["path"]) for f in found), sorted(expected)
        )
        for finding in found:
            self.assert_finding(finding, finding["rule"], 0, finding["path"])
            self.assertIn("enlace", finding["message"])
            self.assertIn("no se revis", finding["message"])
        self.assertEqual(self.score(), 100)

    def replace_with_link(self, relative, target):
        path = self.path(relative)
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
        self.link(path, target)

    def test_events_enlazada_no_se_revisa(self):
        # Afuera no está orders.json: si se mirara, E3 descontaría 3.
        self.replace_with_link(f"{ORDERS}/events", self.afuera)
        self.assert_only_notices(("E2", f"{ORDERS}/events"))
        with self.assertRaises(self.seed_error()):
            self.fix("E3:demo/internal-services/orders")
        self.assertEqual(list(self.afuera.iterdir()), [])

    def test_evento_enlazado_no_se_revisa(self):
        (self.afuera / "evento.json").write_text("{}")
        for target in [self.afuera / "evento.json", self.afuera / "no-existe"]:
            with self.subTest(destino=target.name):
                self.replace_with_link(f"{ORDERS}/events/orders.json", target)
                self.assert_only_notices(
                    ("E3", f"{ORDERS}/events/orders.json")
                )

    def test_layers_enlazado_no_se_revisa(self):
        (self.afuera / "layers").mkdir()  # sin requirements.txt
        self.replace_with_link(f"{ORDERS}/layers/requirements.txt",
                               self.afuera / "no-existe.txt")
        self.assert_only_notices(("E2", f"{ORDERS}/layers/requirements.txt"))
        self.replace_with_link(f"{ORDERS}/layers", self.afuera / "layers")
        self.assert_only_notices(("E2", f"{ORDERS}/layers"))

    def test_handler_enlazado_no_se_lee(self):
        (self.afuera / "src").mkdir()  # sin service/
        for folder in (self.afuera, self.afuera / "src"):
            (folder / "handler.py").write_text(OLD_HANDLER)
        self.replace_with_link(f"{ORDERS}/src/handler.py",
                               self.afuera / "handler.py")
        with self.subTest(enlace="src/handler.py"):
            self.assert_only_notices(("E2", f"{ORDERS}/src/handler.py"))
        self.replace_with_link(f"{ORDERS}/src", self.afuera / "src")
        with self.subTest(enlace="src/"):
            # Un solo aviso por la carpeta, aunque falte service/ afuera.
            self.assert_only_notices(("E2", f"{ORDERS}/src"))

    def test_iac_enlazada_a_un_repo_con_git_no_se_revisa(self):
        (self.afuera / ".git").mkdir()
        (self.afuera / "lib").mkdir()
        (self.afuera / "lib" / "iac-stack.ts").write_text(
            "export class IacStack extends cdk.Stack {}\n"
        )
        self.replace_with_link("projects/demo/iac", self.afuera)
        self.assert_only_notices(("E1", "projects/demo/iac"))

    def test_iacstack_enlazado_no_se_lee(self):
        (self.afuera / "lib").mkdir()
        for path in (self.afuera / "iac.ts",
                     self.afuera / "lib" / "iac-stack.ts"):
            path.write_text("export class IacStack extends cdk.Stack {}\n")
        iac = self.path("projects/demo/iac")
        (iac / "bin").mkdir()
        (iac / "lib").mkdir()
        self.link(iac / "bin" / "iac.ts", self.afuera / "iac.ts")
        self.link(iac / "lib" / "iac-stack.ts",
                  self.afuera / "lib" / "iac-stack.ts")
        # Un enlace que no es un archivo del stack no se menciona.
        self.link(iac / "lib" / "otro.ts", self.afuera / "iac.ts")
        # Más abajo de bin/ tampoco se mira.
        (iac / "bin" / "sub").mkdir()
        (iac / "bin" / "sub" / "iac.ts").write_text("new IacStack();\n")
        self.assert_only_notices(
            ("E7", "projects/demo/iac/bin/iac.ts"),
            ("E7", "projects/demo/iac/lib/iac-stack.ts"),
        )
        shutil.rmtree(iac / "lib")
        self.link(iac / "lib", self.afuera / "lib")
        self.assert_only_notices(
            ("E7", "projects/demo/iac/bin/iac.ts"),
            ("E7", "projects/demo/iac/lib"),
        )

    def test_carpetas_del_proyecto_enlazadas_no_se_revisan(self):
        (self.afuera / "scripts").mkdir()
        self.replace_with_link("projects/demo/deployment-scripts",
                               self.afuera / "scripts")
        self.assert_only_notices(("E1", "projects/demo/deployment-scripts"))
        # python/ afuera, con un launch.json que tiene una entrada huérfana:
        # un solo aviso, sin el de launch.json ni la huérfana.
        python = self.afuera / "python"
        shutil.copytree(self.path("projects/demo/python"), python,
                        symlinks=True)
        data = json.loads((python / ".vscode" / "launch.json").read_text())
        data["configurations"].append(
            self.seedflow.microservice_launch_config("viejo", "internal-services")
        )
        (python / ".vscode" / "launch.json").write_text(json.dumps(data))
        self.replace_with_link("projects/demo/python", python)
        self.assert_only_notices(
            ("E1", "projects/demo/deployment-scripts"),
            ("E1", "projects/demo/python"),
        )

    def test_carpeta_de_servicios_enlazada_no_se_revisa(self):
        services = "projects/demo/python/internal-services"
        shutil.copytree(self.path(services), self.afuera / "services")
        shutil.rmtree(self.afuera / "services" / "orders" / "events")
        self.replace_with_link(services, self.afuera / "services")
        # La entrada de orders en launch.json no cuenta como huérfana.
        self.assert_only_notices(("E2", services))

    def test_microservicio_enlazado_no_se_revisa(self):
        self.create_microservice("viejo")
        services = "projects/demo/python/internal-services"
        self.replace_with_link(f"{services}/viejo", self.afuera)
        self.assert_only_notices(("E2", f"{services}/viejo"))


class LaunchTest(EstructuraTestCase):
    def test_launch_sin_entrada_o_con_entrada_huerfana(self):
        self.create_microservice("billing")
        data = self.read_launch()
        custom = {"name": "mio", "type": "debugpy", "request": "launch",
                  "program": "${workspaceFolder}/scripts/x.py"}
        orphan = self.seedflow.microservice_launch_config(
            "viejo", "consumable-services"
        )
        data["configurations"] = [
            c for c in data["configurations"] if c["name"] != "orders"
        ] + [custom, orphan, dict(orphan), {"name": "raro", "program": 3}]
        self.write_launch(data)

        found = self.findings()
        self.assertEqual(len(found), 2, found)
        orphan_found, missing_found = sorted(found, key=lambda f: f["fix_id"])
        self.assert_finding(
            missing_found, "E4", 3, LAUNCH, "E4:demo/internal-services/orders"
        )
        self.assert_finding(
            orphan_found, "E4", 3, LAUNCH, "E4:demo/consumable-services/viejo"
        )
        self.assertIn("orders", missing_found["message"])
        self.assertIn("viejo", orphan_found["message"])
        self.assertEqual(self.score(), 94)

        launch = self.path(LAUNCH)
        for finding in found:
            self.assertEqual(self.fix(finding["fix_id"]), [launch])
        self.assertEqual(self.findings(), [])
        configurations = self.read_launch()["configurations"]
        names = [c["name"] for c in configurations]
        self.assertEqual(sorted(names),
                         sorted(["orders", "billing", "mio", "raro",
                                 "Python: Current File"]))
        self.assertIn(custom, configurations)
        # Ya está en orden: no toca nada.
        before = launch.read_bytes()
        for finding in found:
            self.assertEqual(self.fix(finding["fix_id"]), [])
        self.assertEqual(launch.read_bytes(), before)

    def test_sin_launch_json_falta_la_entrada(self):
        launch = self.path(LAUNCH)
        launch.unlink()
        (found,) = self.findings()
        self.assert_finding(
            found, "E4", 3, LAUNCH, "E4:demo/internal-services/orders"
        )
        self.assertEqual(self.fix(found["fix_id"]), [launch])
        self.assertEqual(self.findings(), [])

    def assert_launch_not_evaluated(self, report, reason):
        """E4 avisa que no se evaluó (0 puntos, sin arreglo) y nada más."""
        found = [f for f in report["findings"]
                 if f["category"] == "estructura"]
        # La regla de launch.json no descuenta; las demás sí.
        self.assertEqual(sorted(f["rule"] for f in found), ["E3", "E4"])
        (notice,) = [f for f in found if f["rule"] == "E4"]
        self.assert_finding(notice, "E4", 0, LAUNCH)
        self.assertIn("no se pudo evaluar", notice["message"])
        self.assertIn(reason, notice["message"])
        self.assertIn("a mano", notice["how"])
        demo = report["projects"][0]
        self.assertEqual(demo["categories"]["estructura"], 97)
        self.assertNotIn("estructura", demo["not_evaluated"])

    def test_launch_con_comentarios_no_se_evalua(self):
        self.path(f"{ORDERS}/events/orders.json").unlink()  # otra regla
        self.create_microservice("billing")
        launch = self.path(LAUNCH)
        for content in [
            "// generado a mano\n" + launch.read_text(),
            '{"version": "0.2.0", "configurations": {}}',
            '["no es un objeto"]',
        ]:
            with self.subTest(contenido=content[:20]):
                launch.write_text(content)
                self.assert_launch_not_evaluated(self.report(), "formato")
                with self.assertRaises(self.seed_error()):
                    self.fix("E4:demo/internal-services/billing")
                self.assertEqual(launch.read_text(), content)

    @unittest.skipIf(os.name == "nt", "enlaces simbólicos en Windows")
    def test_launch_enlazado_no_se_lee(self):
        self.path(f"{ORDERS}/events/orders.json").unlink()  # otra regla
        afuera = self.base / "afuera"
        afuera.mkdir()
        # Afuera, un launch.json válido con una entrada huérfana: si se
        # leyera, daría un hallazgo de 3 puntos.
        data = self.read_launch()
        data["configurations"].append(
            self.seedflow.microservice_launch_config("viejo", "internal-services")
        )
        (afuera / "launch.json").write_text(json.dumps(data))
        before = (afuera / "launch.json").read_text()
        launch = self.path(LAUNCH)
        vscode = launch.parent
        launch.unlink()
        self.link(launch, afuera / "launch.json")
        with self.subTest(enlace="launch.json"):
            self.assert_launch_not_evaluated(self.report(), "enlace")
        shutil.rmtree(vscode)
        self.link(vscode, afuera)
        with self.subTest(enlace=".vscode"):
            self.assert_launch_not_evaluated(self.report(), "enlace")
            with self.assertRaises(self.seed_error()):
                self.fix("E4:demo/internal-services/viejo")
        self.assertEqual((afuera / "launch.json").read_text(), before)
        (afuera / "launch.json").unlink()
        with self.subTest(enlace=".vscode sin launch.json"):
            # Tampoco cuenta como "falta launch.json": no se sabe qué hay.
            self.assert_launch_not_evaluated(self.report(), "enlace")


class ArreglosTest(EstructuraTestCase):
    def test_fix_id_invalido_es_un_error(self):
        for fix_id in [
            "E3:demo/internal-services",
            "E3:demo/internal-services/orders/x",
            "E3:demo/otra-cosa/orders",
            "E3:../internal-services/orders",
            "E5:demo/internal-services/..",
            "E4",
        ]:
            with self.subTest(fix_id=fix_id):
                prefix = fix_id.split(":", 1)[0]
                with self.assertRaises(self.seed_error()):
                    with contextlib.redirect_stdout(io.StringIO()):
                        self.estructura.FIXES[prefix](self.root, fix_id)

    @unittest.skipIf(os.name == "nt", "enlaces simbólicos en Windows")
    def test_arreglos_no_atraviesan_enlaces(self):
        afuera = self.base / "afuera"
        afuera.mkdir()
        (afuera / "handler.py").write_bytes(OLD_HANDLER.encode("utf-8"))
        handler = self.path(f"{ORDERS}/src/handler.py")
        handler.unlink()
        try:
            handler.symlink_to(afuera / "handler.py")
        except OSError:
            self.skipTest("no se pueden crear enlaces simbólicos")
        with self.assertRaises(self.seed_error()):
            self.fix("E5:demo/internal-services/orders")
        self.assertEqual((afuera / "handler.py").read_bytes(),
                         OLD_HANDLER.encode("utf-8"))

        shutil.rmtree(self.path(f"{ORDERS}/events"))
        self.path(f"{ORDERS}/events").symlink_to(afuera)
        with self.assertRaises(self.seed_error()):
            self.fix("E3:demo/internal-services/orders")
        self.assertEqual(sorted(p.name for p in afuera.iterdir()),
                         ["handler.py"])

    @unittest.skipIf(os.name == "nt", "enlaces simbólicos en Windows")
    def test_arreglos_aceptan_una_raiz_con_enlaces_en_el_camino(self):
        # Como /tmp -> /private/tmp en macOS: la raíz se resuelve primero.
        atajo = self.base / "atajo"
        try:
            atajo.symlink_to(self.root)
        except OSError:
            self.skipTest("no se pueden crear enlaces simbólicos")
        self.path(f"{ORDERS}/events/orders.json").unlink()
        self.path(f"{ORDERS}/src/handler.py").write_text(OLD_HANDLER)
        launch = self.path(LAUNCH)
        launch.unlink()
        with contextlib.redirect_stdout(io.StringIO()):
            for prefix in ["E3", "E4", "E5"]:
                changed = self.estructura.FIXES[prefix](
                    atajo, f"{prefix}:demo/internal-services/orders"
                )
                self.assertEqual(len(changed), 1, prefix)
        self.assertEqual(self.findings(), [])

    def test_arreglos_funcionan_desde_la_terminal(self):
        # El arreglo se importa como lo hará `seedflow.py fix`: en un proceso
        # nuevo, con el script como __main__.
        self.path(f"{ORDERS}/events/orders.json").unlink()
        code = (
            "import sys\n"
            f"sys.path.insert(0, {str(SCRIPT.parent)!r})\n"
            "from pathlib import Path\n"
            "from checks import estructura\n"
            "print(estructura.FIXES['E3'](Path(sys.argv[1]), sys.argv[2]))\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", code, str(self.root),
             "E3:demo/internal-services/orders"],
            capture_output=True, text=True, check=False,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("orders.json", result.stdout)
        self.assertEqual(self.findings(), [])


if __name__ == "__main__":
    unittest.main()
