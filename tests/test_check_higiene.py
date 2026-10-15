"""Tests de las reglas de seguridad e higiene (scripts/checks/higiene.py).

Califican repos temporales con `seedflow.py check --json` y miran solo los
hallazgos de la categoría "higiene". Los que dependen de git crean su propio
repo git en una carpeta temporal.

Las credenciales de estos tests son ficticias a propósito.

Solo librería estándar. Desde la raíz del repo:

    python3 -m unittest tests.test_check_higiene -v

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
import shutil
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
# Clave de acceso con la forma de AWS (la de ejemplo de su documentación),
# partida en dos para que ningún escáner la tome por real en este archivo.
AWS_KEY = "AKIA" + "IOSFODNN7EXAMPLE"
FAKE_PASSWORD = "contrasena-ficticia-123"


def load_seedflow():
    """Carga el script como módulo, fresco en cada test."""
    spec = importlib.util.spec_from_file_location("seedflow_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class HigieneTestCase(unittest.TestCase):
    """Base: una raíz temporal, con o sin git, aislada de la config global."""

    def setUp(self):
        self.seedflow = load_seedflow()
        self.seedflow.load_checks()
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name).resolve()
        self.root = self.base / "repo"
        self.root.mkdir()
        # Que git no encuentre un repo por encima de la carpeta temporal ni use
        # la configuración global de quien corre los tests.
        empty_config = self.base / "gitconfig"
        empty_config.write_text("")
        patcher = mock.patch.dict(os.environ, {
            "GIT_CEILING_DIRECTORIES": str(self.base),
            "GIT_CONFIG_GLOBAL": str(empty_config),
            "XDG_CONFIG_HOME": str(self.base / "xdg"),
        })
        patcher.start()
        self.addCleanup(patcher.stop)

    # -- ayudas ------------------------------------------------------------

    def higiene(self):
        """El módulo de reglas de higiene de la copia del script que se prueba."""
        return importlib.import_module("checks.higiene")

    def run_cli(self, *argv):
        """Corre el script y devuelve (código, stdout, stderr)."""
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = self.seedflow.main(["--root", str(self.root), *argv])
            except SystemExit as error:  # errores de argparse
                code = error.code
        return code, out.getvalue(), err.getvalue()

    def check(self):
        """(reporte JSON, hallazgos de higiene) de check con las reglas reales.

        Los avisos de H1 sin evaluar (0 puntos) quedan aparte, en self.avisos.
        """
        code, out, err = self.run_cli("check", "--json")
        self.assertEqual(code, 0, out + err)
        report = json.loads(out)
        higiene = [f for f in report["findings"] if f["category"] == "higiene"]
        self.avisos = [f for f in higiene if f["points"] == 0]
        return report, [f for f in higiene if f["points"] != 0]

    def score(self, report, project="demo"):
        """Nota de higiene de un proyecto (None si no se evaluó)."""
        found = next(p for p in report["projects"] if p["name"] == project)
        return found["categories"]["higiene"]

    def write(self, relative, content=""):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def make_projects(self, *names):
        """Proyectos mínimos (solo la carpeta python/)."""
        for name in names:
            (self.root / "projects" / name / "python").mkdir(parents=True)

    def git(self, *args):
        git = shutil.which("git")
        if not git:
            self.skipTest("git no está instalado")
        subprocess.run(
            [git, *args], cwd=self.root, check=True, capture_output=True
        )

    def git_repo(self, gitignore=".env\n"):
        """La raíz como repo git, con este .gitignore (None: sin .gitignore)."""
        if gitignore is not None:
            self.write(".gitignore", gitignore)
        self.git("init", "-q")

    def rules(self, findings, rule):
        return [f for f in findings if f["rule"] == rule]

    def without_git(self):
        """Como si git no estuviera instalado (solo para estas reglas)."""
        patcher = mock.patch.object(
            self.higiene(), "git_executable", return_value=None
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def prepare(self, modo, gitignore):
        """La raíz en uno de MODOS, con este .gitignore (None: sin él)."""
        if modo == "repo git":
            self.git_repo(gitignore)
            return
        if gitignore is not None:
            self.write(".gitignore", gitignore)
        if modo == "git no instalado":
            self.without_git()


# Cómo puede estar la raíz: H2 no depende de que sea un repo git (lee solo el
# .gitignore de la raíz); sin git instalado usa las líneas exactas.
MODOS = ("repo git", "carpeta sin git", "git no instalado")
MODOS_CON_GIT = ("repo git", "carpeta sin git")


class ProyectoNuevoTest(HigieneTestCase):
    def test_proyecto_nuevo_con_gitignore_correcto_no_tiene_hallazgos(self):
        for argv in [
            ("create-project", "demo", "--service-type", "internal-services",
             "--skip-cdk"),
            ("create-microservice", "orders", "--project", "demo",
             "--service-type", "internal-services", "--database"),
            ("create-project", "solo", "--service-type", "consumable-services",
             "--skip-cdk"),
        ]:
            code, out, err = self.run_cli(*argv)
            self.assertEqual(code, 0, out + err)
        # El .env local existe (ignorado) y el .env.example está commiteado.
        self.write("projects/demo/python/.env",
                   f"DATABASE_PASSWORD={FAKE_PASSWORD}\n")
        self.git_repo(".env\n")
        self.git("add", "-A")
        report, findings = self.check()
        self.assertEqual(findings, [])
        self.assertEqual(self.avisos, [])
        self.assertEqual(self.score(report, "demo"), 100)
        self.assertEqual(self.score(report, "solo"), 100)


class EnvCommiteadoTest(HigieneTestCase):
    def test_env_commiteado_es_critico(self):
        self.make_projects("demo", "otro")
        self.write("projects/demo/python/.env", f"PASSWORD={FAKE_PASSWORD}\n")
        self.write("projects/demo/python/app/.env", "X=1\n")
        self.write("projects/otro/python/.env", "X=1\n")  # no commiteado
        self.git_repo(".env\n")
        self.git("add", "-f", "projects/demo/python/.env",
                 "projects/demo/python/app/.env")
        report, findings = self.check()
        h1 = self.rules(findings, "H1")
        self.assertEqual(
            [(f["project"], f["path"], f["points"]) for f in h1],
            [("demo", "projects/demo/python/.env", 25),
             ("demo", "projects/demo/python/app/.env", 25)],
        )
        self.assertEqual(len(findings), 2)
        for finding in h1:
            self.assertIsNone(finding["fix_id"])
            self.assertTrue(finding["why"] and finding["how"])
        self.assertEqual(self.score(report, "demo"), 50)
        self.assertEqual(self.score(report, "otro"), 100)
        # Nunca muestra lo que tiene el .env.
        self.assertNotIn(FAKE_PASSWORD, json.dumps(report))

    def test_env_example_no_cuenta(self):
        self.make_projects("demo")
        for name in [".env.example", "settings.env.example", "env", ".envrc"]:
            self.write(f"projects/demo/python/{name}", "X=\n")
        self.git_repo(".env\n")
        self.git("add", "-A")
        report, findings = self.check()
        self.assertEqual(findings, [])
        self.assertEqual(self.score(report), 100)

    def test_fuera_de_git_no_se_evalua_env_commiteado(self):
        # Sin git la regla no se puede evaluar: lo avisa con un hallazgo de 0
        # puntos por proyecto, y el resto de la categoría sí se evalúa.
        self.make_projects("demo", "otro")
        self.write("projects/demo/python/.env", "X=1\n")
        self.write(".gitignore", ".env\n")
        report, findings = self.check()
        self.assertEqual(findings, [])
        self.assertEqual(
            [(f["rule"], f["project"], f["path"], f["points"], f["fix_id"])
             for f in self.avisos],
            [("H1", "demo", "projects/demo", 0, None),
             ("H1", "otro", "projects/otro", 0, None)],
        )
        for aviso in self.avisos:
            self.assertIn("no se pudo evaluar", aviso["message"])
            self.assertIn("no es un repo git", aviso["message"])
            self.assertIn("git ls-files", aviso["how"])
            self.assertTrue(aviso["why"])
        self.assertEqual(self.score(report), 100)
        self.assertEqual(self.score(report, "otro"), 100)
        for project in report["projects"]:
            self.assertNotIn("higiene", project["not_evaluated"])


class GitignoreTest(HigieneTestCase):
    def assert_h2_en_cada_proyecto(self, findings):
        h2 = self.rules(findings, "H2")
        self.assertEqual(
            [(f["project"], f["path"], f["points"]) for f in h2],
            [("demo", ".gitignore", 10), ("otro", ".gitignore", 10)],
        )
        for finding in h2:
            self.assertEqual(finding["fix_id"], "H2:.gitignore")
            self.assertTrue(finding["why"] and finding["how"])
            self.assertIn(".env", finding["message"])

    def test_gitignore_sin_env_descuenta_en_cada_proyecto(self):
        casos = {
            "sin .gitignore": None,
            "sin la línea": "node_modules/\n*.pyc\n.env.example\n",
            "solo el .env de la raíz": "/.env\n",
            "con espacios delante": "  .env\n",
            "ignorado y después des-ignorado": ".env\n!.env\n",
        }
        for caso, gitignore in casos.items():
            for modo in MODOS:
                with self.subTest(caso=caso, modo=modo):
                    self.setUp()
                    self.make_projects("demo", "otro")
                    self.prepare(modo, gitignore)
                    report, findings = self.check()
                    self.assert_h2_en_cada_proyecto(findings)
                    self.assertEqual(len(findings), 2)
                    self.assertEqual(self.score(report, "demo"), 90)
                    self.assertEqual(self.score(report, "otro"), 90)

    def test_gitignore_que_ignora_env_no_descuenta(self):
        for gitignore in [".env\n", "*.env\n", ".env  \n", "# x\r\n.env\r\n"]:
            for modo in MODOS:
                with self.subTest(gitignore=gitignore, modo=modo):
                    self.setUp()
                    self.make_projects("demo")
                    self.prepare(modo, gitignore)
                    report, findings = self.check()
                    self.assertEqual(findings, [])
                    self.assertEqual(self.score(report), 100)

    def test_con_git_entiende_los_patrones_de_git(self):
        # Patrones del .gitignore de la raíz que solo git sabe leer.
        for gitignore in ["**/.env\n", ".env*\n!.env.example\n",
                          "projects/*/python/.env\n"]:
            for modo in MODOS_CON_GIT:
                with self.subTest(gitignore=gitignore, modo=modo):
                    self.setUp()
                    self.make_projects("demo")
                    self.prepare(modo, gitignore)
                    report, findings = self.check()
                    self.assertEqual(findings, [])
                    self.assertEqual(self.score(report), 100)

    def test_con_git_una_proteccion_limitada_a_una_ruta(self):
        # Lo que protege a un proyecto no protege a los demás, y lo que
        # des-ignora un proyecto lo deja expuesto solo a él.
        for gitignore, expuesto in [
            ("projects/demo/python/.env\n", "otro"),
            (".env\n!projects/demo/python/.env\n", "demo"),
        ]:
            for modo in MODOS_CON_GIT:
                with self.subTest(gitignore=gitignore, modo=modo):
                    self.setUp()
                    self.make_projects("demo", "otro")
                    self.prepare(modo, gitignore)
                    report, findings = self.check()
                    self.assertEqual(
                        [(f["rule"], f["project"]) for f in findings],
                        [("H2", expuesto)],
                    )
                    self.assertEqual(self.score(report, expuesto), 90)

    def test_solo_cuenta_el_gitignore_de_la_raiz(self):
        # Un .gitignore del proyecto o .git/info/exclude (que no se commitea)
        # no protegen: H2 mira solo el .gitignore de la raíz, así dos copias
        # iguales del repo sacan la misma nota.
        self.make_projects("demo", "otro")
        self.write("projects/demo/.gitignore", ".env\n")
        self.write("projects/otro/python/.gitignore", ".env\n")
        self.git_repo("node_modules/\n")
        exclude = self.root / ".git" / "info" / "exclude"
        exclude.parent.mkdir(parents=True, exist_ok=True)
        exclude.write_text(".env\n")
        _, findings = self.check()
        self.assert_h2_en_cada_proyecto(findings)

    def test_variables_de_git_del_entorno_no_cambian_el_resultado(self):
        # Si seedflow corre dentro de un hook de git (GIT_DIR y GIT_WORK_TREE
        # apuntan al repo), H2 igual mira solo el .gitignore de la raíz.
        self.make_projects("demo", "otro")
        self.write("projects/demo/.gitignore", ".env\n")
        self.git_repo("node_modules/\n")
        git_dir = self.root / ".git"
        before = sorted(p.relative_to(git_dir).as_posix()
                        for p in git_dir.rglob("*"))
        with mock.patch.dict(os.environ, {
            "GIT_DIR": str(git_dir), "GIT_WORK_TREE": str(self.root),
        }):
            _, findings = self.check()
        self.assert_h2_en_cada_proyecto(findings)
        after = sorted(p.relative_to(git_dir).as_posix()
                       for p in git_dir.rglob("*"))
        self.assertEqual(after, before)

    def test_la_plantilla_de_git_init_no_se_usa_ni_se_escribe(self):
        # Una plantilla de git init (por variable y por configuración) cuyo
        # info/exclude es un enlace a un archivo de afuera: calificar no lo
        # toca, y lo que excluye no protege.
        for modo in MODOS_CON_GIT:
            with self.subTest(modo=modo):
                self.setUp()
                afuera = self.base / "afuera-exclude"
                afuera.write_bytes(b".env\n# no me borres\n")
                template = self.base / "plantilla-enlazada"
                (template / "info").mkdir(parents=True)
                try:
                    (template / "info" / "exclude").symlink_to(afuera)
                except (OSError, NotImplementedError):
                    self.skipTest("este sistema no permite crear enlaces")
                self.make_projects("demo", "otro")
                self.prepare(modo, "node_modules/\n")
                Path(os.environ["GIT_CONFIG_GLOBAL"]).write_text(
                    f"[init]\n\ttemplateDir = {template.as_posix()}\n"
                )
                with mock.patch.dict(
                    os.environ, {"GIT_TEMPLATE_DIR": str(template)}
                ):
                    _, findings = self.check()
                self.assert_h2_en_cada_proyecto(findings)
                self.assertEqual(
                    afuera.read_bytes(), b".env\n# no me borres\n"
                )

    def test_mayusculas_no_dependen_de_la_configuracion_de_git(self):
        # Git compara con mayúsculas (como en Linux y en CI) aunque el sistema
        # de archivos o la configuración de quien califica digan lo contrario:
        # mismos hallazgos y mismo arreglo en cualquier máquina.
        config_global = self.base / "gitconfig-ignorecase"
        config_global.write_text("[core]\n\tignoreCase = true\n")
        entornos = {
            "sin configuración": {},
            "global": {"GIT_CONFIG_GLOBAL": str(config_global)},
            "variables": {"GIT_CONFIG_COUNT": "1",
                          "GIT_CONFIG_KEY_0": "core.ignoreCase",
                          "GIT_CONFIG_VALUE_0": "true"},
            "parámetros": {"GIT_CONFIG_PARAMETERS": "'core.ignorecase'='true'"},
        }
        for nombre, variables in entornos.items():
            for modo in MODOS_CON_GIT:
                with self.subTest(entorno=nombre, modo=modo):
                    self.setUp()
                    self.make_projects("demo", "otro")
                    self.prepare(modo, ".ENV\n")
                    gitignore = self.root / ".gitignore"
                    with mock.patch.dict(os.environ, variables):
                        _, findings = self.check()
                        self.assert_h2_en_cada_proyecto(findings)
                        module = self.higiene()
                        touched = module.FIXES["H2"](self.root, "H2:.gitignore")
                        self.assertEqual(touched, [gitignore])
                        self.assertEqual(gitignore.read_bytes(), b".ENV\n.env\n")
                        _, findings = self.check()
                        self.assertEqual(findings, [])

    def test_el_gitignore_global_del_usuario_no_cuenta(self):
        # Dos personas con la misma copia del repo tienen que ver la misma
        # nota: lo que ignore la configuración global de una no cuenta.
        # Ni sus exclusiones globales ni la plantilla de git init.
        global_ignore = self.base / "ignore-global"
        global_ignore.write_text(".env\n")
        template = self.base / "plantilla"
        (template / "info").mkdir(parents=True)
        (template / "info" / "exclude").write_text(".env\n")
        Path(os.environ["GIT_CONFIG_GLOBAL"]).write_text(
            f"[core]\n\texcludesFile = {global_ignore.as_posix()}\n"
            f"[init]\n\ttemplateDir = {template.as_posix()}\n"
        )
        xdg = self.base / "xdg" / "git"
        xdg.mkdir(parents=True)
        (xdg / "ignore").write_text(".env\n")
        self.make_projects("demo", "otro")
        self.git_repo("node_modules/\n")
        _, findings = self.check()
        self.assert_h2_en_cada_proyecto(findings)


class CredencialesTest(HigieneTestCase):
    def test_credencial_aws_y_password_literal(self):
        self.make_projects("demo")
        self.git_repo()
        self.write(
            "projects/demo/python/internal-services/orders/src/service/main.py",
            "import os\n"                                         # 1
            f'KEY = "{AWS_KEY}"\n'                                # 2
            f'password = "{FAKE_PASSWORD}"\n'                     # 3
            f'DB_PASSWORD: str = "{FAKE_PASSWORD}"\n'             # 4
            f'conn = connect(api_token="{FAKE_PASSWORD}")\n'      # 5
            f'params = {{"password": "{FAKE_PASSWORD}"}}\n'       # 6
            f'self.client_secret = "{FAKE_PASSWORD}"\n'           # 7
            f'config["Secret"] = "{FAKE_PASSWORD}"\n'             # 8
            f"# clave vieja: {AWS_KEY}\n"                          # 9
            'API_TOKEN = " "\n',                                  # 10
        )
        self.write("projects/demo/python/scripts/uno.py",
                   f'\n\ntoken = "{FAKE_PASSWORD}"\n')
        self.write("projects/demo/python/scripts/roto.py",
                   f'def (:\n    "{AWS_KEY}"\n')
        report, findings = self.check()
        h3 = self.rules(findings, "H3")
        base = "projects/demo/python"
        self.assertEqual(
            [(f["path"], f["points"]) for f in h3],
            [(f"{base}/internal-services/orders/src/service/main.py", 25),
             (f"{base}/scripts/roto.py", 25),
             (f"{base}/scripts/uno.py", 25)],
        )
        self.assertIn("líneas 2, 3, 4, 5, 6, 7, 8, 9, 10", h3[0]["message"])
        self.assertIn("línea 2", h3[1]["message"])
        self.assertIn("línea 3", h3[2]["message"])
        self.assertNotIn("líneas", h3[2]["message"])
        for finding in h3:
            self.assertEqual(finding["project"], "demo")
            self.assertIsNone(finding["fix_id"])
            self.assertIn("falso positivo", finding["message"])
            self.assertTrue(finding["why"] and finding["how"])
        self.assertEqual(len(findings), 3)
        self.assertEqual(self.score(report), 25)
        # El valor de la credencial no aparece en ninguna salida.
        for argv in [("check", "--json"), ("check",), ("check", "--quick")]:
            with self.subTest(argv=argv):
                code, out, err = self.run_cli(*argv)
                self.assertEqual(code, 0, err)
                self.assertNotIn(FAKE_PASSWORD, out + err)
                self.assertNotIn("IOSFODNN7", out + err)

    def test_password_desde_os_environ_no_cuenta(self):
        self.make_projects("demo")
        self.git_repo()
        self.write(
            "projects/demo/python/internal-services/orders/src/service/main.py",
            "import os\n"
            'password = os.environ["DATABASE_PASSWORD"]\n'
            'token = os.getenv("API_TOKEN", "")\n'
            'secret = ""\n'
            'conn = connect(password=os.environ["X"], user="admin")\n'
            'params = {"password": os.environ["X"], "host": "db.local"}\n'
            'secret_name = "prod/db"\n'
            'token_type = "Bearer"\n'
            'password_field = "password"\n'
            'config[0] = "password"\n'
            'PASSWORD = 1234\n'
            'logger.info("password incorrecto")\n'
            '"AKIA123"\n'
            f'"X{AWS_KEY}"\n',
        )
        report, findings = self.check()
        self.assertEqual(findings, [])
        self.assertEqual(self.score(report), 100)

    def test_credencial_dentro_de_venv_no_cuenta(self):
        self.make_projects("demo")
        self.git_repo()
        credencial = f'password = "{FAKE_PASSWORD}"\n'
        self.write("projects/demo/python/.venv/lib/python3.12/site-packages/"
                   "paquete/x.py", credencial)
        self.write("projects/demo/python/internal-services/orders/.venv/lib/"
                   "x.py", credencial)
        self.write("projects/demo/python/venv/lib/x.py", credencial)
        report, findings = self.check()
        self.assertEqual(findings, [])
        self.assertEqual(self.score(report), 100)

    def test_no_revisa_a_traves_de_enlaces(self):
        afuera = self.base / "afuera"
        afuera.mkdir()
        (afuera / "x.py").write_text(f'password = "{FAKE_PASSWORD}"\n')
        (self.root / "projects" / "demo").mkdir(parents=True)
        try:
            (self.root / "projects" / "demo" / "python").symlink_to(
                afuera, target_is_directory=True
            )
        except (OSError, NotImplementedError):
            self.skipTest("este sistema no permite crear enlaces simbólicos")
        self.git_repo()
        report, findings = self.check()
        self.assertEqual(findings, [])
        self.assertEqual(self.score(report), 100)

    def test_no_se_queda_leyendo_algo_que_no_es_un_archivo(self):
        # Un "x.py" que es una tubería (FIFO) bloquearía la lectura para
        # siempre; check lo salta. Corre en otro proceso, con tiempo límite.
        if not hasattr(os, "mkfifo"):
            self.skipTest("este sistema no tiene tuberías con nombre")
        self.make_projects("demo")
        self.write("projects/demo/python/a.py", f'password = "{FAKE_PASSWORD}"\n')
        os.mkfifo(self.root / "projects" / "demo" / "python" / "b.py")
        self.git_repo()
        try:
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--root", str(self.root),
                 "check", "--json"],
                capture_output=True, text=True, check=False, timeout=15,
            )
        except subprocess.TimeoutExpired:
            self.fail("check se quedó leyendo la tubería")
        self.assertEqual(result.returncode, 0, result.stderr)
        findings = [f for f in json.loads(result.stdout)["findings"]
                    if f["category"] == "higiene"]
        self.assertEqual([(f["rule"], f["path"]) for f in findings],
                         [("H3", "projects/demo/python/a.py")])

    def test_solo_revisa_los_py_de_python_sin_caches(self):
        self.make_projects("demo")
        self.git_repo()
        credencial = f'password = "{FAKE_PASSWORD}"\n'
        self.write("projects/demo/python/__pycache__/x.py", credencial)
        self.write("projects/demo/python/.mypy_cache/x.py", credencial)
        self.write("projects/demo/iac/node_modules/x.py", credencial)
        self.write("projects/demo/deployment-scripts/x.py", credencial)
        self.write("projects/demo/python/notas.txt", credencial)
        report, findings = self.check()
        self.assertEqual(findings, [])
        self.assertEqual(self.score(report), 100)


class QueriesTest(HigieneTestCase):
    def test_query_con_fstring_o_format(self):
        self.make_projects("demo")
        self.git_repo()
        self.write(
            "projects/demo/python/internal-services/orders/src/service/main.py",
            "def main(event, redshift, aurora):\n"                       # 1
            '    redshift.read(f"SELECT * FROM t WHERE id = {event}")\n'  # 2
            '    aurora.execute_query("DELETE FROM t WHERE id = {}"\n'    # 3
            "                         .format(event))\n"                  # 4
            '    redshift.write(QUERY.format(id=event["id"]))\n'         # 5
            '    redshift.read(query=f"SELECT {event}")\n'               # 6
            '    read(f"SELECT {event}")\n'                              # 7
            '    redshift.read("SELECT 1")\n',                           # 8
        )
        report, findings = self.check()
        h4 = self.rules(findings, "H4")
        self.assertEqual(
            [(f["project"], f["path"], f["points"]) for f in h4],
            [("demo", "projects/demo/python/internal-services/orders/src/"
              "service/main.py", 10)],
        )
        self.assertIn("líneas 2, 3, 5, 6, 7", h4[0]["message"])
        self.assertIn("falso positivo", h4[0]["message"])
        self.assertIsNone(h4[0]["fix_id"])
        self.assertTrue(h4[0]["why"] and h4[0]["how"])
        self.assertEqual(len(findings), 1)
        self.assertEqual(self.score(report), 90)

    def test_query_con_constante_no_cuenta(self):
        self.make_projects("demo")
        self.git_repo()
        self.write(
            "projects/demo/python/internal-services/orders/src/service/main.py",
            "def main(event, redshift, logger):\n"
            '    redshift.read("SELECT * FROM t WHERE id = {id}", event)\n'
            "    redshift.read(QUERY, {\"id\": event['id']})\n"
            '    redshift.execute_query(QUERY)\n'
            '    redshift.write("DELETE FROM t")\n'
            '    redshift.read(QUERY, f"{event}")\n'
            '    redshift.read()\n'
            '    logger.info(f"SELECT {event}")\n'
            '    redshift.read_json(f"s3://{event}")\n'
            '    redshift.read(build(f"{event}"))\n'
            '    print("SELECT {}".format(event))\n',
        )
        report, findings = self.check()
        self.assertEqual(findings, [])
        self.assertEqual(self.score(report), 100)


class ArregloTest(HigieneTestCase):
    def fix(self):
        """La función de FIXES que corresponde al fix_id de la regla H2."""
        module = self.higiene()
        fix_id = "H2:.gitignore"
        prefix = next(p for p in module.FIXES if fix_id.startswith(p))
        return lambda: module.FIXES[prefix](self.root, fix_id)

    def test_arreglo_gitignore_agrega_env_y_conserva_lo_demas(self):
        casos = {
            "sin salto al final": (b"node_modules/\n# x\n*.pyc",
                                   b"node_modules/\n# x\n*.pyc\n.env\n"),
            "con salto al final": (b"node_modules/\n", b"node_modules/\n.env\n"),
            "con saltos de Windows": (b"node_modules/\r\n*.pyc",
                                      b"node_modules/\r\n*.pyc\r\n.env\r\n"),
            "vacío": (b"", b".env\n"),
            "des-ignorado": (b".env\n!.env\n", b".env\n!.env\n.env\n"),
            "sin .gitignore": (None, b".env\n"),
        }
        for caso, (antes, despues) in casos.items():
            for modo in MODOS:
                with self.subTest(caso=caso, modo=modo):
                    self.setUp()
                    self.make_projects("demo", "otro")
                    gitignore = self.root / ".gitignore"
                    if antes is not None:
                        gitignore.write_bytes(antes)
                    self.prepare(modo, None)
                    report, findings = self.check()
                    self.assertEqual(len(self.rules(findings, "H2")), 2)
                    self.assertEqual(self.score(report), 90)
                    touched = self.fix()()
                    self.assertEqual(touched, [gitignore])
                    self.assertEqual(gitignore.read_bytes(), despues)
                    report, findings = self.check()
                    self.assertEqual(findings, [])
                    self.assertEqual(self.score(report, "demo"), 100)
                    self.assertEqual(self.score(report, "otro"), 100)

    def test_arreglo_gitignore_no_hace_nada_si_ya_ignora_env(self):
        for modo in MODOS:
            with self.subTest(modo=modo):
                self.setUp()
                self.make_projects("demo")
                gitignore = self.root / ".gitignore"
                gitignore.write_bytes(b"*.pyc\n**/.env\n.env\n")
                self.prepare(modo, None)
                self.assertEqual(self.fix()(), [])
                self.assertEqual(gitignore.read_bytes(), b"*.pyc\n**/.env\n.env\n")

    def test_arreglo_decide_con_el_mismo_detector_que_h2(self):
        # .env está en el .gitignore, pero una línea después des-ignora el de
        # demo: H2 lo ve expuesto, y el arreglo tiene que corregirlo.
        antes = b".env\n!projects/demo/python/.env\n"
        for modo in MODOS_CON_GIT:
            with self.subTest(modo=modo):
                self.setUp()
                self.make_projects("demo", "otro")
                gitignore = self.root / ".gitignore"
                gitignore.write_bytes(antes)
                self.prepare(modo, None)
                _, findings = self.check()
                self.assertEqual(
                    [(f["rule"], f["project"]) for f in findings],
                    [("H2", "demo")],
                )
                self.assertEqual(self.fix()(), [gitignore])
                self.assertEqual(gitignore.read_bytes(), antes + b".env\n")
                report, findings = self.check()
                self.assertEqual(findings, [])
                self.assertEqual(self.score(report), 100)

    def test_arreglo_gitignore_no_escribe_a_traves_de_un_enlace(self):
        self.make_projects("demo")
        afuera = self.base / "afuera.txt"
        afuera.write_text(".env\n")
        try:
            (self.root / ".gitignore").symlink_to(afuera)
        except (OSError, NotImplementedError):
            self.skipTest("este sistema no permite crear enlaces simbólicos")
        # git no lee un .gitignore que es un enlace: el .env queda expuesto.
        _, findings = self.check()
        self.assertEqual([f["rule"] for f in findings], ["H2"])
        with self.assertRaises(ValueError) as error:
            self.fix()()
        self.assertIn(".gitignore", str(error.exception))
        self.assertEqual(afuera.read_text(), ".env\n")

    def test_arreglo_gitignore_no_toca_algo_que_no_es_un_archivo(self):
        # Una carpeta (o una tubería) llamada .gitignore: el arreglo no la
        # lee ni la reemplaza, y lo dice.
        self.make_projects("demo")
        (self.root / ".gitignore").mkdir()
        (self.root / ".gitignore" / "dentro").write_text("x")
        with self.assertRaises(ValueError) as error:
            self.fix()()
        self.assertIn(".gitignore", str(error.exception))
        self.assertEqual((self.root / ".gitignore" / "dentro").read_text(), "x")

    def test_las_reglas_no_escriben_en_el_repo(self):
        self.make_projects("demo")
        self.write("projects/demo/python/a.py", f'password = "{FAKE_PASSWORD}"\n')
        self.git_repo("node_modules/\n")

        def snapshot():
            return {
                p.relative_to(self.root).as_posix(): p.read_bytes()
                for p in sorted(self.root.rglob("*"))
                if p.is_file() and ".git" not in p.relative_to(self.root).parts
            }

        before = snapshot()
        _, findings = self.check()
        self.assertEqual({f["rule"] for f in findings}, {"H2", "H3"})
        self.assertEqual(snapshot(), before)


if __name__ == "__main__":
    unittest.main()
