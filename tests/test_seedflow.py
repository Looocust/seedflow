"""Tests del motor de seedflow (plugins/seedflow/scripts/seedflow.py).

Solo librería estándar. Desde la raíz del repo:

    python3 -m unittest discover -s tests -v

SEEDFLOW_SCRIPT permite apuntar a otra copia del script (lo usa
tests/mutantes.py para comprobar que los tests detectan fallas).
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
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


def load_seedflow():
    """Carga el script como módulo, fresco en cada test."""
    spec = importlib.util.spec_from_file_location("seedflow_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


FAKE_TOOL = """#!/bin/sh
echo "$(basename "$0") $* @$(basename "$PWD")" >> "$SEEDFLOW_TOOL_LOG"
if [ "$(basename "$0")" = "cdk" ] && [ -n "$SEEDFLOW_CDK_FAIL" ]; then
  echo "cdk roto" >&2
  exit 1
fi
if [ "$(basename "$0")" = "npm" ] && [ -n "$SEEDFLOW_NPM_FAIL" ]; then
  echo "npm roto" >&2
  exit 1
fi
if [ "$1" = "init" ]; then echo '{}' > package.json; fi
exit 0
"""


class SeedflowTestCase(unittest.TestCase):
    """Base: una carpeta raíz temporal y helpers para correr comandos."""

    def setUp(self):
        self.seedflow = load_seedflow()
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name).resolve()
        self.root = self.base / "repo"
        self.root.mkdir()
        # Un archivo fuera de projects/ que nunca debe tocarse.
        self.sentinel = self.root / "no_borrar.txt"
        self.sentinel.write_text("importante")

    def run_cli(self, *argv):
        """Corre el script y devuelve (código, stdout, stderr)."""
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = self.seedflow.main(["--root", str(self.root), *argv])
            except SystemExit as error:  # errores de argparse
                code = error.code
        return code, out.getvalue(), err.getvalue()

    def create_project(self, name="demo", service_type="internal-services"):
        code, out, err = self.run_cli(
            "create-project", name, "--service-type", service_type, "--skip-cdk"
        )
        self.assertEqual(code, 0, out + err)
        return self.root / "projects" / name

    def create_microservice(
        self, name="orders", project="demo", service_type="internal-services", *extra
    ):
        code, out, err = self.run_cli(
            "create-microservice",
            name,
            "--project",
            project,
            "--service-type",
            service_type,
            *extra,
        )
        self.assertEqual(code, 0, out + err)
        return self.root / "projects" / project / "python" / service_type / name

    def launch_configs(self, project="demo"):
        path = self.root / "projects" / project / "python" / ".vscode" / "launch.json"
        return json.loads(path.read_text(encoding="utf-8"))["configurations"]

    def fake_tools(self, cdk_fails=False, npm_fails=False, tools=("cdk", "npm")):
        """Pone cdk y npm falsos en el PATH y devuelve el log de llamadas."""
        bin_dir = self.base / "fakebin"
        bin_dir.mkdir()
        for tool in tools:
            path = bin_dir / tool
            path.write_text(FAKE_TOOL)
            path.chmod(path.stat().st_mode | stat.S_IEXEC)
        log = self.base / "tools.log"
        env = {
            "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
            "SEEDFLOW_TOOL_LOG": str(log),
            "SEEDFLOW_CDK_FAIL": "1" if cdk_fails else "",
            "SEEDFLOW_NPM_FAIL": "1" if npm_fails else "",
        }
        patcher = mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)
        return log

    def snapshot(self):
        """Todas las rutas bajo la raíz, para comparar antes y después."""
        return sorted(p.relative_to(self.root).as_posix() for p in self.root.rglob("*"))

    def symlink(self, link, target):
        try:
            link.symlink_to(target, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("este sistema no permite crear enlaces simbólicos")

    def no_tools_in_path(self):
        patcher = mock.patch.dict(os.environ, {"PATH": str(self.base / "vacio")})
        patcher.start()
        self.addCleanup(patcher.stop)


class ValidacionDeNombresTest(SeedflowTestCase):
    INVALIDOS = ["..", "../x", "a/b", "_x", "", "a b", "x" * 65, "á"]

    def test_nombre_que_empieza_con_guion_lo_rechaza_argparse(self):
        # argparse lo toma como una opción y corta antes de validar (código 2).
        code, _, _ = self.run_cli(
            "create-project", "-x", "--service-type", "internal-services",
            "--skip-cdk",
        )
        self.assertEqual(code, 2)
        self.assertFalse((self.root / "projects").exists())

    def test_nombres_invalidos_de_proyecto_se_rechazan_sin_crear_nada(self):
        for name in self.INVALIDOS:
            with self.subTest(name=name):
                code, _, err = self.run_cli(
                    "create-project", name, "--service-type", "internal-services",
                    "--skip-cdk",
                )
                self.assertEqual(code, 1)
                self.assertIn("no es válido", err)
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ["no_borrar.txt"])

    def test_nombres_invalidos_de_microservicio_se_rechazan(self):
        self.create_project()
        for name in self.INVALIDOS:
            with self.subTest(name=name):
                code, _, err = self.run_cli(
                    "create-microservice", name, "--project", "demo",
                    "--service-type", "internal-services",
                )
                self.assertEqual(code, 1)
                self.assertIn("no es válido", err)
        self.assertFalse((self.root / "projects" / "x").exists())

    def test_nombres_validos_se_aceptan(self):
        for name in ["warehouses-operation", "orders_sync", "A1", "x" * 64]:
            with self.subTest(name=name):
                self.assertTrue(self.create_project(name).is_dir())


class CrearProyectoTest(SeedflowTestCase):
    def test_crea_la_estructura_base(self):
        project = self.create_project()
        for relative in [
            "deployment-scripts/build.sh",
            "deployment-scripts/install.sh",
            "deployment-scripts/pre_build.sh",
            "deployment-scripts/post_build.sh",
            "python/.env.example",
            "python/pyproject.toml",
            "python/requirements.txt",
            "python/.vscode/settings.json",
            "python/.vscode/launch.json",
        ]:
            with self.subTest(archivo=relative):
                self.assertTrue((project / relative).is_file())
        self.assertTrue((project / "iac").is_dir())
        self.assertTrue((project / "python" / "internal-services").is_dir())
        self.assertFalse((project / "python" / "consumable-services").exists())

    def test_la_carpeta_de_servicios_vacia_queda_en_git(self):
        project = self.create_project()
        self.assertTrue((project / "python" / "internal-services" / ".gitkeep").is_file())
        code, out, _ = self.run_cli("status", "--json")
        services = json.loads(out)["projects"][0]["services"]
        self.assertEqual(services, {"internal-services": []})

    @unittest.skipIf(os.name == "nt", "Windows no tiene bit de ejecución")
    def test_los_scripts_de_despliegue_son_ejecutables(self):
        project = self.create_project()
        for script in (project / "deployment-scripts").glob("*.sh"):
            with self.subTest(script=script.name):
                self.assertTrue(os.access(script, os.X_OK))

    def test_launch_json_inicial_solo_tiene_la_configuracion_generica(self):
        self.create_project()
        configs = self.launch_configs()
        self.assertEqual([c["name"] for c in configs], ["Python: Current File"])

    def test_no_sobrescribe_un_proyecto_existente(self):
        project = self.create_project()
        marker = project / "python" / "requirements.txt"
        marker.write_text("mi versión")
        code, _, err = self.run_cli(
            "create-project", "demo", "--service-type", "consumable-services",
            "--skip-cdk",
        )
        self.assertEqual(code, 1)
        self.assertIn("ya existe", err)
        self.assertEqual(marker.read_text(), "mi versión")
        self.assertFalse((project / "python" / "consumable-services").exists())

    def test_tipo_de_servicio_invalido_lo_rechaza_argparse(self):
        code, _, _ = self.run_cli(
            "create-project", "demo", "--service-type", "otra", "--skip-cdk"
        )
        self.assertEqual(code, 2)
        self.assertFalse((self.root / "projects").exists())

    def test_sin_cdk_falla_antes_de_crear_cualquier_cosa(self):
        self.no_tools_in_path()
        code, out, err = self.run_cli(
            "create-project", "demo", "--service-type", "internal-services"
        )
        self.assertEqual(code, 1)
        self.assertIn("no están instalados", err)
        self.assertNotIn("Creando", out)
        self.assertFalse((self.root / "projects" / "demo").exists())

    @unittest.skipIf(os.name == "nt", "usa ejecutables falsos de shell POSIX")
    def test_inicializa_cdk_sin_repo_git_y_luego_instala(self):
        log = self.fake_tools()
        code, out, err = self.run_cli(
            "create-project", "demo", "--service-type", "internal-services"
        )
        self.assertEqual(code, 0, out + err)
        calls = log.read_text().splitlines()
        self.assertEqual(
            calls,
            [
                "cdk init app --language=typescript --generate-only @demo",
                "npm install --no-audit --no-fund @iac",
            ],
        )
        project = self.root / "projects" / "demo"
        self.assertTrue((project / "iac" / "package.json").is_file())
        # La carpeta temporal donde corrió cdk init no queda en el proyecto.
        self.assertEqual(
            sorted(p.name for p in project.iterdir()),
            ["deployment-scripts", "iac", "python"],
        )

    @unittest.skipIf(os.name == "nt", "usa ejecutables falsos de shell POSIX")
    def test_si_cdk_falla_se_deshace_el_proyecto(self):
        self.fake_tools(cdk_fails=True)
        code, out, err = self.run_cli(
            "create-project", "demo", "--service-type", "internal-services"
        )
        self.assertEqual(code, 1)
        self.assertIn("cdk roto", err)
        self.assertIn("Se deshizo", out)
        self.assertFalse((self.root / "projects" / "demo").exists())
        self.assertTrue(self.sentinel.exists())


class CrearMicroservicioTest(SeedflowTestCase):
    def setUp(self):
        super().setUp()
        self.create_project()

    def test_crea_la_estructura_del_microservicio(self):
        service = self.create_microservice()
        for relative in [
            "events/orders.json",
            "layers/requirements.txt",
            "src/handler.py",
            "src/service/__init__.py",
            "src/service/main.py",
        ]:
            with self.subTest(archivo=relative):
                self.assertTrue((service / relative).is_file())
        self.assertFalse((service / "src" / "database").exists())

    def test_database_es_opcional(self):
        service = self.create_microservice("orders", "demo", "internal-services", "--database")
        self.assertTrue((service / "src" / "database" / "__init__.py").is_file())

    def test_el_handler_generado_lee_su_evento_y_corre(self):
        service = self.create_microservice()
        (service / "events" / "orders.json").write_text('{"hola": 1}')
        result = subprocess.run(
            [sys.executable, "src/handler.py", "orders"],
            cwd=service,
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Processing event in dev environment", result.stdout)
        self.assertIn('"hola": 1', result.stdout)

    def test_agrega_la_configuracion_de_depuracion(self):
        self.create_microservice()
        configs = self.launch_configs()
        self.assertEqual(
            [c["name"] for c in configs], ["orders", "Python: Current File"]
        )
        orders = configs[0]
        self.assertEqual(
            orders["program"],
            "${workspaceFolder}/internal-services/orders/src/handler.py",
        )
        self.assertEqual(orders["args"], ["orders"])
        self.assertEqual(orders["envFile"], "${workspaceFolder}/.env")

    def test_no_sobrescribe_un_microservicio_existente(self):
        service = self.create_microservice()
        handler = service / "src" / "handler.py"
        handler.write_text("# mi código")
        code, _, err = self.run_cli(
            "create-microservice", "orders", "--project", "demo",
            "--service-type", "internal-services",
        )
        self.assertEqual(code, 1)
        self.assertIn("ya existe", err)
        self.assertEqual(handler.read_text(), "# mi código")

    def test_proyecto_inexistente_falla(self):
        code, _, err = self.run_cli(
            "create-microservice", "orders", "--project", "otro",
            "--service-type", "internal-services",
        )
        self.assertEqual(code, 1)
        self.assertIn("No existe el proyecto", err)
        self.assertFalse((self.root / "projects" / "otro").exists())

    def test_crea_la_carpeta_de_servicios_si_no_existe(self):
        service = self.create_microservice("api", "demo", "consumable-services")
        self.assertTrue(service.is_dir())

    def test_si_algo_falla_deshace_todo_lo_que_creo(self):
        launch = self.root / "projects/demo/python/.vscode/launch.json"
        before = launch.read_bytes()

        def escribe_y_falla(*args, **kwargs):
            launch.write_text("{a medias")
            raise RuntimeError("falla simulada")

        self.seedflow.update_launch = escribe_y_falla
        with self.assertRaises(RuntimeError), contextlib.redirect_stdout(io.StringIO()):
            self.seedflow.main([
                "--root", str(self.root), "create-microservice", "api",
                "--project", "demo", "--service-type", "consumable-services",
            ])
        python = self.root / "projects/demo/python"
        self.assertFalse((python / "consumable-services").exists())
        self.assertTrue((python / "internal-services").is_dir())
        self.assertEqual(launch.read_bytes(), before)

    def test_si_falla_y_no_habia_launch_json_no_deja_uno_a_medias(self):
        launch = self.root / "projects/demo/python/.vscode/launch.json"
        launch.unlink()

        def escribe_y_falla(*args, **kwargs):
            launch.write_text("{a medias")
            raise RuntimeError("falla simulada")

        self.seedflow.update_launch = escribe_y_falla
        with self.assertRaises(RuntimeError), contextlib.redirect_stdout(io.StringIO()):
            self.seedflow.main([
                "--root", str(self.root), "create-microservice", "api",
                "--project", "demo", "--service-type", "internal-services",
            ])
        self.assertFalse(launch.exists())

    def test_launch_json_con_comentarios_no_se_toca(self):
        launch = self.root / "projects/demo/python/.vscode/launch.json"
        launch.write_text('{\n  // mis configuraciones\n  "version": "0.2.0"\n}\n')
        before = launch.read_bytes()
        code, out, _ = self.run_cli(
            "create-microservice", "orders", "--project", "demo",
            "--service-type", "internal-services",
        )
        self.assertEqual(code, 0)
        self.assertIn("No lo toqué", out)
        self.assertEqual(launch.read_bytes(), before)


class PlantillasTest(SeedflowTestCase):
    def test_los_caches_en_plantillas_no_se_copian(self):
        source = self.base / "tpl"
        for junk in [".mypy_cache/x.db", "src/__pycache__/a.pyc", ".ruff_cache/y",
                     ".DS_Store", "src/.pytest_cache/z"]:
            path = source / junk
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("basura")
        (source / "src" / "ok.py").write_text("")
        (source / "__name__.json").write_text("{}")
        target = self.base / "out"
        created = self.seedflow.copy_template(source, target, "svc")
        self.assertEqual(
            sorted(p.relative_to(target).as_posix() for p in created),
            ["src/ok.py", "svc.json"],
        )
        self.assertFalse((target / ".mypy_cache").exists())

    def test_las_plantillas_del_plugin_no_traen_caches(self):
        templates = SCRIPT.resolve().parent.parent / "templates"
        junk = [
            p for p in templates.rglob("*")
            if p.name in self.seedflow.IGNORED_IN_TEMPLATES
        ]
        self.assertEqual(junk, [])


class EliminarTest(SeedflowTestCase):
    def setUp(self):
        super().setUp()
        self.project = self.create_project()
        self.service = self.create_microservice()

    def test_borrar_proyecto_sin_yes_no_borra(self):
        code, _, err = self.run_cli("delete-project", "demo")
        self.assertEqual(code, 1)
        self.assertIn("--yes", err)
        self.assertTrue(self.project.is_dir())

    def test_borrar_proyecto_con_yes_borra_solo_el_proyecto(self):
        other = self.create_project("otro")
        code, out, _ = self.run_cli("delete-project", "demo", "--yes")
        self.assertEqual(code, 0)
        self.assertIn("eliminado", out)
        self.assertFalse(self.project.exists())
        self.assertTrue(other.is_dir())
        self.assertTrue(self.sentinel.exists())

    def test_borrar_proyecto_con_puntos_no_borra_nada(self):
        for name in ["..", ".", "../repo"]:
            with self.subTest(name=name):
                code, _, _ = self.run_cli("delete-project", name, "--yes")
                self.assertEqual(code, 1)
        self.assertTrue(self.sentinel.exists())
        self.assertTrue(self.project.is_dir())

    def test_un_enlace_que_sale_de_projects_no_se_borra(self):
        outside = self.base / "afuera"
        outside.mkdir()
        (outside / "valioso.txt").write_text("x")
        self.symlink(self.root / "projects" / "enlace", outside)
        code, _, err = self.run_cli("delete-project", "enlace", "--yes")
        self.assertEqual(code, 1)
        self.assertIn("enlace simbólico", err)
        self.assertTrue((outside / "valioso.txt").exists())

    def test_borrar_microservicio_sin_yes_no_borra(self):
        code, _, _ = self.run_cli(
            "delete-microservice", "orders", "--project", "demo",
            "--service-type", "internal-services",
        )
        self.assertEqual(code, 1)
        self.assertTrue(self.service.is_dir())

    def test_borrar_microservicio_lo_quita_de_launch_json(self):
        code, _, _ = self.run_cli(
            "delete-microservice", "orders", "--project", "demo",
            "--service-type", "internal-services", "--yes",
        )
        self.assertEqual(code, 0)
        self.assertFalse(self.service.exists())
        self.assertEqual(
            [c["name"] for c in self.launch_configs()], ["Python: Current File"]
        )

    def test_borrar_microservicio_inexistente_falla(self):
        code, _, err = self.run_cli(
            "delete-microservice", "nada", "--project", "demo",
            "--service-type", "internal-services", "--yes",
        )
        self.assertEqual(code, 1)
        self.assertIn("No existe el microservicio", err)

    def test_borrar_microservicio_con_puntos_no_borra_nada(self):
        code, _, _ = self.run_cli(
            "delete-microservice", "..", "--project", "demo",
            "--service-type", "internal-services", "--yes",
        )
        self.assertEqual(code, 1)
        self.assertTrue(self.service.is_dir())


class StatusTest(SeedflowTestCase):
    def test_status_json_lista_proyectos_y_microservicios(self):
        self.create_project()
        self.create_microservice()
        self.create_microservice("api", "demo", "consumable-services")
        code, out, _ = self.run_cli("status", "--json")
        self.assertEqual(code, 0)
        status = json.loads(out)
        self.assertEqual(status["root"], str(self.root))
        self.assertTrue(status["has_projects_folder"])
        self.assertEqual(
            status["projects"],
            [{
                "name": "demo",
                "services": {
                    "internal-services": ["orders"],
                    "consumable-services": ["api"],
                },
            }],
        )
        self.assertEqual(set(status["tools"]), {"cdk", "node", "npm", "git"})

    def test_status_sin_projects(self):
        code, out, _ = self.run_cli("status", "--json")
        self.assertEqual(code, 0)
        status = json.loads(out)
        self.assertFalse(status["has_projects_folder"])
        self.assertEqual(status["projects"], [])


class NombresExtraTest(SeedflowTestCase):
    def test_nombre_con_salto_de_linea_se_rechaza(self):
        code, _, err = self.run_cli(
            "create-project", "demo\n", "--service-type", "internal-services",
            "--skip-cdk",
        )
        self.assertEqual(code, 1)
        self.assertIn("no es válido", err)
        self.assertFalse((self.root / "projects").exists())

    def test_nombres_reservados_de_windows_se_rechazan(self):
        for name in ["CON", "nul", "Com1", "LPT9", "aux", "PRN"]:
            with self.subTest(name=name):
                code, _, err = self.run_cli(
                    "create-project", name, "--service-type", "internal-services",
                    "--skip-cdk",
                )
                self.assertEqual(code, 1)
                self.assertIn("reservado", err)

    def test_la_salida_no_falla_con_una_consola_sin_emojis(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--root", str(self.root), "status"],
            capture_output=True,
            env={**os.environ, "PYTHONIOENCODING": "cp1252"},
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


class EnlacesSimbolicosTest(SeedflowTestCase):
    def setUp(self):
        super().setUp()
        self.project = self.create_project()
        self.outside = self.base / "afuera"
        self.outside.mkdir()
        (self.outside / "valioso.txt").write_text("x")

    def test_un_proyecto_que_apunta_a_projects_no_borra_todo(self):
        other = self.create_project("otro")
        self.symlink(self.root / "projects" / "enlace", self.root / "projects")
        code, _, err = self.run_cli("delete-project", "enlace", "--yes")
        self.assertEqual(code, 1)
        self.assertIn("enlace simbólico", err)
        self.assertTrue(self.project.is_dir())
        self.assertTrue(other.is_dir())

    def test_carpeta_de_servicios_enlazada_afuera_no_se_usa(self):
        services = self.project / "python" / "consumable-services"
        self.symlink(services, self.outside)
        code, _, err = self.run_cli(
            "create-microservice", "x", "--project", "demo",
            "--service-type", "consumable-services",
        )
        self.assertEqual(code, 1)
        self.assertIn("enlace simbólico", err)
        self.assertEqual(sorted(p.name for p in self.outside.iterdir()), ["valioso.txt"])

    def test_microservicio_enlazado_afuera_no_se_borra(self):
        services = self.project / "python" / "internal-services"
        self.symlink(services / "x", self.outside)
        code, _, err = self.run_cli(
            "delete-microservice", "x", "--project", "demo",
            "--service-type", "internal-services", "--yes",
        )
        self.assertEqual(code, 1)
        self.assertTrue((self.outside / "valioso.txt").exists())

    def test_projects_enlazada_afuera_no_se_usa(self):
        other_root = self.base / "otra-raiz"
        other_root.mkdir()
        self.symlink(other_root / "projects", self.outside)
        self.root = other_root
        code, _, err = self.run_cli(
            "create-project", "nuevo", "--service-type", "internal-services",
            "--skip-cdk",
        )
        self.assertEqual(code, 1)
        self.assertIn("enlace simbólico", err)
        self.assertEqual(sorted(p.name for p in self.outside.iterdir()), ["valioso.txt"])

    def test_vscode_enlazada_afuera_no_se_escribe(self):
        vscode = self.project / "python" / ".vscode"
        for item in vscode.iterdir():
            item.unlink()
        vscode.rmdir()
        self.symlink(vscode, self.outside)
        code, _, err = self.run_cli(
            "create-microservice", "x", "--project", "demo",
            "--service-type", "internal-services",
        )
        self.assertEqual(code, 1)
        self.assertIn("enlace simbólico", err)
        self.assertEqual(sorted(p.name for p in self.outside.iterdir()), ["valioso.txt"])
        self.assertFalse((self.project / "python" / "internal-services" / "x").exists())


    def test_vscode_enlazada_afuera_impide_borrar_el_microservicio(self):
        service = self.create_microservice("x")
        vscode = self.project / "python" / ".vscode"
        for item in vscode.iterdir():
            item.unlink()
        vscode.rmdir()
        self.symlink(vscode, self.outside)
        code, _, err = self.run_cli(
            "delete-microservice", "x", "--project", "demo",
            "--service-type", "internal-services", "--yes",
        )
        self.assertEqual(code, 1)
        self.assertIn("enlace simbólico", err)
        self.assertTrue(service.is_dir())

class RollbackCompletoTest(SeedflowTestCase):
    @unittest.skipIf(os.name == "nt", "usa ejecutables falsos de shell POSIX")
    def test_si_cdk_falla_la_raiz_queda_igual_que_antes(self):
        before = self.snapshot()
        self.fake_tools(cdk_fails=True)
        code, _, _ = self.run_cli(
            "create-project", "demo", "--service-type", "internal-services"
        )
        self.assertEqual(code, 1)
        self.assertEqual(self.snapshot(), before)

    @unittest.skipIf(os.name == "nt", "usa ejecutables falsos de shell POSIX")
    def test_si_npm_install_falla_se_deshace_el_proyecto(self):
        before = self.snapshot()
        self.fake_tools(npm_fails=True)
        code, _, err = self.run_cli(
            "create-project", "demo", "--service-type", "internal-services"
        )
        self.assertEqual(code, 1)
        self.assertIn("npm roto", err)
        self.assertEqual(self.snapshot(), before)

    @unittest.skipIf(os.name == "nt", "usa ejecutables falsos de shell POSIX")
    def test_con_cdk_pero_sin_npm_falla_antes_de_crear(self):
        self.fake_tools(tools=("cdk",))
        with mock.patch.dict(os.environ, {"PATH": str(self.base / "fakebin")}):
            code, out, err = self.run_cli(
                "create-project", "demo", "--service-type", "internal-services"
            )
        self.assertEqual(code, 1)
        self.assertNotIn("Creando", out)
        self.assertFalse((self.root / "projects" / "demo").exists())

    def test_microservicio_sin_vscode_previa_no_deja_carpetas_vacias(self):
        project = self.create_project()
        vscode = project / "python" / ".vscode"
        for item in vscode.iterdir():
            item.unlink()
        vscode.rmdir()
        before = self.snapshot()
        original = self.seedflow.update_launch

        def escribe_y_falla(*args, **kwargs):
            original(*args, **kwargs)
            raise RuntimeError("falla simulada")

        self.seedflow.update_launch = escribe_y_falla
        with self.assertRaises(RuntimeError), contextlib.redirect_stdout(io.StringIO()):
            self.seedflow.main([
                "--root", str(self.root), "create-microservice", "api",
                "--project", "demo", "--service-type", "consumable-services",
            ])
        self.assertEqual(self.snapshot(), before)

    def test_si_no_puede_limpiar_lo_dice(self):
        project = self.create_project()

        def falla(*args, **kwargs):
            raise RuntimeError("falla simulada")

        self.seedflow.update_launch = falla
        out = io.StringIO()
        with mock.patch.object(self.seedflow, "remove_tree", lambda path: None), \
                self.assertRaises(RuntimeError), contextlib.redirect_stdout(out):
            self.seedflow.main([
                "--root", str(self.root), "create-microservice", "api",
                "--project", "demo", "--service-type", "internal-services",
            ])
        self.assertIn("No pude deshacer", out.getvalue())
        self.assertNotIn("Se deshizo la creación", out.getvalue())
        self.assertIn("internal-services/api", out.getvalue())


class LaunchJsonTest(SeedflowTestCase):
    def setUp(self):
        super().setUp()
        self.project = self.create_project()
        self.launch = self.project / "python" / ".vscode" / "launch.json"

    def test_preserva_lo_que_no_es_de_seedflow(self):
        custom = {"name": "Mi config", "type": "debugpy", "request": "launch",
                  "program": "${file}", "args": ["--debug"]}
        self.launch.write_text(json.dumps({
            "version": "0.2.0",
            "configurations": [custom],
            "compounds": [{"name": "todo", "configurations": ["Mi config"]}],
        }))
        self.create_microservice()
        data = json.loads(self.launch.read_text())
        self.assertEqual(data["compounds"], [{"name": "todo", "configurations": ["Mi config"]}])
        self.assertIn(custom, data["configurations"])
        self.assertIn("orders", [c["name"] for c in data["configurations"]])

    def test_json_valido_con_otra_forma_no_rompe_ni_se_toca(self):
        for content in ["[]", "null", '{"configurations": [null]}', '{"configurations": {}}']:
            with self.subTest(content=content):
                self.launch.write_text(content)
                name = f"ms{len(content)}"
                code, out, err = self.run_cli(
                    "create-microservice", name, "--project", "demo",
                    "--service-type", "internal-services",
                )
                self.assertEqual(code, 0, err)
                self.assertIn("No lo toqué", out)
                self.assertEqual(self.launch.read_text(), content)
                code, out, err = self.run_cli(
                    "delete-microservice", name, "--project", "demo",
                    "--service-type", "internal-services", "--yes",
                )
                self.assertEqual(code, 0, err)
                self.assertEqual(self.launch.read_text(), content)


class DryRunTest(SeedflowTestCase):
    def setUp(self):
        super().setUp()
        self.project = self.create_project()
        self.service = self.create_microservice()

    def test_dry_run_de_proyecto_muestra_y_no_borra(self):
        code, out, _ = self.run_cli("delete-project", "demo", "--dry-run")
        self.assertEqual(code, 0)
        self.assertIn(str(self.project), out)
        self.assertIn("archivos", out)
        self.assertTrue(self.project.is_dir())

    def test_dry_run_de_microservicio_muestra_y_no_borra(self):
        code, out, _ = self.run_cli(
            "delete-microservice", "orders", "--project", "demo",
            "--service-type", "internal-services", "--dry-run",
        )
        self.assertEqual(code, 0)
        self.assertIn(str(self.service), out)
        self.assertIn("launch.json", out)
        self.assertTrue(self.service.is_dir())
        self.assertIn("orders", [c["name"] for c in self.launch_configs()])


class HandlerEnvTest(SeedflowTestCase):
    def test_el_handler_carga_el_env_del_proyecto(self):
        self.create_project()
        service = self.create_microservice()
        (self.root / "projects/demo/python/.env").write_text("x=1\n")
        fake = self.base / "fake_dotenv"
        fake.mkdir()
        (fake / "dotenv.py").write_text(
            "def load_dotenv(path):\n"
            "    print('ENV_CARGADO', path)\n"
        )
        result = subprocess.run(
            [sys.executable, "src/handler.py", "orders"],
            cwd=service, capture_output=True, text=True, check=False,
            env={**os.environ, "PYTHONPATH": str(fake), "PYTHONDONTWRITEBYTECODE": "1"},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        expected = (self.root / "projects/demo/python/.env").resolve()
        self.assertIn(f"ENV_CARGADO {expected}", result.stdout)


class Ronda2Test(SeedflowTestCase):
    """Casos de la segunda revisión."""

    def setUp(self):
        super().setUp()
        self.project = self.create_project()
        self.launch = self.project / "python" / ".vscode" / "launch.json"
        self.outside_file = self.base / "ajeno.txt"
        self.outside_file.write_text("no tocar")

    def test_temporal_de_launch_con_enlace_preexistente_no_escribe_afuera(self):
        tmp = self.launch.with_name("launch.json.seedflow-tmp")
        try:
            tmp.symlink_to(self.outside_file)
        except (OSError, NotImplementedError):
            self.skipTest("este sistema no permite crear enlaces simbólicos")
        self.create_microservice()
        self.assertEqual(self.outside_file.read_text(), "no tocar")
        self.assertIn("orders", [c["name"] for c in self.launch_configs()])

    def test_si_falla_el_reemplazo_no_queda_temporal_ni_cambia_launch(self):
        before = self.launch.read_bytes()
        vscode_before = sorted(p.name for p in self.launch.parent.iterdir())
        with mock.patch.object(self.seedflow.os, "replace", side_effect=OSError("disco lleno")):
            with self.assertRaises(OSError), contextlib.redirect_stdout(io.StringIO()):
                self.seedflow.main([
                    "--root", str(self.root), "create-microservice", "orders",
                    "--project", "demo", "--service-type", "internal-services",
                ])
        self.assertEqual(self.launch.read_bytes(), before)
        self.assertEqual(sorted(p.name for p in self.launch.parent.iterdir()), vscode_before)
        self.assertFalse((self.project / "python/internal-services/orders").exists())

    def test_un_enlace_que_is_symlink_no_detecta_igual_se_rechaza(self):
        # Simula una junction de Windows: un enlace que is_symlink() no ve.
        outside = self.base / "afuera"
        outside.mkdir()
        services = self.project / "python" / "consumable-services"
        try:
            services.symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("este sistema no permite crear enlaces simbólicos")
        with mock.patch.object(Path, "is_symlink", return_value=False):
            code, _, err = self.run_cli(
                "create-microservice", "x", "--project", "demo",
                "--service-type", "consumable-services",
            )
        self.assertEqual(code, 1)
        self.assertIn("enlace", err)
        self.assertEqual(list(outside.iterdir()), [])

    def test_si_no_se_puede_actualizar_launch_no_se_borra_el_microservicio(self):
        service = self.create_microservice()
        before = self.launch.read_bytes()
        with mock.patch.object(self.seedflow, "write_atomic", side_effect=OSError("sin permiso")):
            with self.assertRaises(OSError), contextlib.redirect_stdout(io.StringIO()):
                self.seedflow.main([
                    "--root", str(self.root), "delete-microservice", "orders",
                    "--project", "demo", "--service-type", "internal-services", "--yes",
                ])
        self.assertTrue(service.is_dir())
        self.assertEqual(self.launch.read_bytes(), before)

    def test_si_el_borrado_falla_se_restaura_launch(self):
        service = self.create_microservice()
        before = self.launch.read_bytes()
        with mock.patch.object(self.seedflow.shutil, "rmtree", side_effect=OSError("ocupado")):
            with self.assertRaises(OSError), contextlib.redirect_stdout(io.StringIO()):
                self.seedflow.main([
                    "--root", str(self.root), "delete-microservice", "orders",
                    "--project", "demo", "--service-type", "internal-services", "--yes",
                ])
        self.assertTrue(service.is_dir())
        self.assertEqual(self.launch.read_bytes(), before)

    def test_launch_que_es_una_carpeta_no_rompe_el_borrado(self):
        service = self.create_microservice()
        self.launch.unlink()
        self.launch.mkdir()
        code, out, err = self.run_cli(
            "delete-microservice", "orders", "--project", "demo",
            "--service-type", "internal-services", "--yes",
        )
        self.assertEqual(code, 0, err)
        self.assertIn("No lo toqué", out)
        self.assertFalse(service.exists())
        self.assertTrue(self.launch.is_dir())

    def test_rollback_no_borra_contenedores_con_trabajo_ajeno(self):
        python = self.project / "python"

        def otro_comando_y_falla(*args, **kwargs):
            # Mientras tanto, otro comando creó algo en la misma carpeta nueva.
            (python / "consumable-services" / "de-otro").mkdir()
            raise RuntimeError("falla simulada")

        self.seedflow.update_launch = otro_comando_y_falla
        with self.assertRaises(RuntimeError), contextlib.redirect_stdout(io.StringIO()):
            self.seedflow.main([
                "--root", str(self.root), "create-microservice", "api",
                "--project", "demo", "--service-type", "consumable-services",
            ])
        self.assertFalse((python / "consumable-services" / "api").exists())
        self.assertTrue((python / "consumable-services" / "de-otro").is_dir())

    def test_borrar_con_otra_capitalizacion_quita_la_configuracion(self):
        service = self.create_microservice("Orders")
        if not (service.parent / "orders").exists():
            self.skipTest("este sistema de archivos distingue mayúsculas")
        code, _, err = self.run_cli(
            "delete-microservice", "orders", "--project", "demo",
            "--service-type", "internal-services", "--yes",
        )
        self.assertEqual(code, 0, err)
        self.assertFalse(service.exists())
        self.assertEqual(
            [c["name"] for c in self.launch_configs()], ["Python: Current File"]
        )


class Ronda3Test(SeedflowTestCase):
    """Casos de la tercera revisión."""

    def setUp(self):
        super().setUp()
        self.project = self.create_project()
        self.launch = self.project / "python" / ".vscode" / "launch.json"

    def test_disco_lleno_persistente_no_vacia_launch_json(self):
        before = self.launch.read_bytes()
        disco_lleno = OSError(28, "No space left on device")

        def abre_vacia_y_falla(path, data):
            # Como el write_bytes real: abre truncando y luego no puede escribir.
            open(path, "wb").close()
            raise disco_lleno

        with mock.patch.object(self.seedflow, "write_atomic", side_effect=disco_lleno), \
                mock.patch.object(Path, "write_bytes", abre_vacia_y_falla), \
                self.assertRaises(OSError), contextlib.redirect_stdout(io.StringIO()):
            self.seedflow.main([
                "--root", str(self.root), "create-microservice", "orders",
                "--project", "demo", "--service-type", "internal-services",
            ])
        self.assertEqual(self.launch.read_bytes(), before)

    def test_launch_que_es_una_carpeta_no_impide_crear(self):
        self.launch.unlink()
        self.launch.mkdir()
        code, out, err = self.run_cli(
            "create-microservice", "orders", "--project", "demo",
            "--service-type", "internal-services",
        )
        self.assertEqual(code, 0, err)
        self.assertIn("No lo toqué", out)
        self.assertTrue(self.launch.is_dir())

    def test_borrar_sin_launch_json_no_lo_crea(self):
        self.create_microservice()
        self.launch.unlink()
        code, _, err = self.run_cli(
            "delete-microservice", "orders", "--project", "demo",
            "--service-type", "internal-services", "--yes",
        )
        self.assertEqual(code, 0, err)
        self.assertFalse(self.launch.exists())

    def test_borrado_a_medias_lo_dice(self):
        service = self.create_microservice()
        handler = service / "src" / "handler.py"

        def borra_algo_y_falla(path, *args, **kwargs):
            handler.unlink()
            raise OSError("ocupado")

        out = io.StringIO()
        with mock.patch.object(self.seedflow.shutil, "rmtree", side_effect=borra_algo_y_falla), \
                self.assertRaises(OSError), contextlib.redirect_stdout(out):
            self.seedflow.main([
                "--root", str(self.root), "delete-microservice", "orders",
                "--project", "demo", "--service-type", "internal-services", "--yes",
            ])
        self.assertIn("puede haber quedado incompleto", out.getvalue())
        self.assertNotIn("No se borró el microservicio", out.getvalue())
        self.assertIn("orders", [c["name"] for c in self.launch_configs()])


if __name__ == "__main__":
    unittest.main()
