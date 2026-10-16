"""Tests de `seedflow.py fix`: lista y aplica los arreglos mecánicos.

Usan las reglas reales sobre un proyecto "del CLI anterior": sin el evento de
prueba, con la ruta ../../events en el handler, sin su entrada en
launch.json, con un error de ruff que `ruff check --fix` arregla, con formato
pendiente y con un .gitignore que no ignora .env.

Nada sale a internet: el entorno de herramientas vive en un
SEEDFLOW_TOOLS_DIR temporal, ya armado con los `ruff` y `mypy` falsos de
tests/test_check_calidad.py (reaccionan a marcas en el código), y pip no
tiene índice (PIP_NO_INDEX=1).

Solo librería estándar. Desde la raíz del repo:

    python3 -m unittest tests.test_fix -v

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
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock


REPO = Path(__file__).resolve().parent.parent
SCRIPT = Path(
    os.environ.get(
        "SEEDFLOW_SCRIPT", REPO / "plugins" / "seedflow" / "scripts" / "seedflow.py"
    )
)
DEMO = "demo/internal-services/orders"
ORDERS = "projects/demo/python/internal-services/orders"
IDS = [
    f"C1:{DEMO}",
    f"C2:{DEMO}",
    f"E3:{DEMO}",
    f"E4:{DEMO}",
    f"E5:{DEMO}",
    "H2:.gitignore",
]


def load_module(name, path):
    """Carga un archivo de Python como módulo, fresco."""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_seedflow():
    """El script como módulo, fresco en cada test."""
    return load_module("seedflow_under_test", SCRIPT)


# Los ruff y mypy falsos de los tests de calidad (sin editar ese archivo).
CALIDAD = load_module(
    "fakes_de_test_check_calidad",
    Path(__file__).resolve().parent / "test_check_calidad.py",
)


@unittest.skipUnless(os.name == "posix", "ruff y mypy falsos usan /bin/sh")
class FixTestCase(unittest.TestCase):
    """Base: un repo temporal con dos proyectos y el demo desordenado."""

    def setUp(self):
        self.seedflow = load_seedflow()
        self.checks = self.seedflow.load_checks()
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name).resolve()
        self.root = self.base / "repo"
        self.root.mkdir()
        tools = self.base / "tools"
        tools.mkdir()
        # El entorno ya instalado: seedflow no intenta instalar nada.
        self.env = tools / "ruff-0.9.6_mypy-1.15.0"
        CALIDAD.FakeInstaller()(
            [sys.executable, "-I", "-m", "venv", str(self.env)], tools
        )
        patcher = mock.patch.dict(
            os.environ,
            {
                "GIT_CEILING_DIRECTORIES": str(self.base),
                "SEEDFLOW_TOOLS_DIR": str(tools),
                "PIP_NO_INDEX": "1",
            },
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    # -- ayudas ------------------------------------------------------------

    def run_cli(self, *argv):
        """Corre el script en este proceso y devuelve (código, stdout, stderr)."""
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = self.seedflow.main(["--root", str(self.root), *argv])
            except SystemExit as error:  # errores de argparse
                code = error.code
        return code, out.getvalue(), err.getvalue()

    def run_script(self, *argv, script=SCRIPT, env=None):
        """Corre el script en un proceso nuevo, como lo corre una skill."""
        result = subprocess.run(
            [sys.executable, str(script), "--root", str(self.root), *argv],
            env=env, capture_output=True, text=True, check=False,
        )
        return result.returncode, result.stdout, result.stderr

    def create(self, project):
        for argv in [
            ("create-project", project, "--service-type", "internal-services",
             "--skip-cdk"),
            ("create-microservice", "orders", "--project", project,
             "--service-type", "internal-services"),
        ]:
            code, out, err = self.run_cli(*argv)
            self.assertEqual(code, 0, out + err)

    def old_repo(self):
        """demo como lo dejaba el CLI anterior; otro, recién creado."""
        self.create("demo")
        self.create("otro")
        orders = self.root / ORDERS
        (orders / "events" / "orders.json").unlink()
        with (orders / "src" / "handler.py").open("a", encoding="utf-8") as f:
            f.write('EVENTS = "../../events"  # ruta del CLI anterior\n')
        (orders / "src" / "service" / "extra.py").write_text(
            "x = 1  # ERR_RUFF_FIX\ny = 2  # UNFORMATTED\n", encoding="utf-8"
        )
        launch = self.root / "projects/demo/python/.vscode/launch.json"
        data = json.loads(launch.read_text(encoding="utf-8"))
        data["configurations"] = [
            c for c in data["configurations"] if c.get("name") != "orders"
        ]
        launch.write_text(json.dumps(data, indent=4) + "\n", encoding="utf-8")
        (self.root / ".gitignore").write_text("node_modules\n", encoding="utf-8")

    def snapshot(self):
        """Ruta y contenido de todo lo que hay en el repo."""
        return {
            path.relative_to(self.root).as_posix(): (
                hashlib.sha256(path.read_bytes()).hexdigest()
                if path.is_file() else None
            )
            for path in sorted(self.root.rglob("*"))
        }

    def report(self, runner=None):
        code, out, err = (runner or self.run_cli)("check", "--json")
        self.assertEqual(code, 0, out + err)
        return json.loads(out)

    def fix_calls(self):
        """Las corridas de ruff que arreglan (no las que califican)."""
        log = self.env / "calls.jsonl"
        if not log.exists():
            return []
        calls = [json.loads(line) for line in log.read_text().splitlines()]
        result = []
        for call in calls:
            argv = call["argv"]
            if argv[1] != "ruff":
                continue
            if argv[2] == "check" and "--fix" in argv:
                result.append("check --fix")
            elif argv[2] == "format" and "--check" not in argv:
                result.append("format")
        return result


class ListaTest(FixTestCase):
    def test_fix_list_muestra_arreglos_y_archivos(self):
        self.old_repo()
        before = self.snapshot()
        code, out, err = self.run_cli("fix", "--list")
        self.assertEqual(code, 0, out + err)
        positions = []
        for fix_id in IDS:
            with self.subTest(fix_id=fix_id):
                # Una sola vez: H2:.gitignore sale en los dos proyectos.
                self.assertEqual(out.count(fix_id), 1, out)
                positions.append(out.index(fix_id))
        self.assertEqual(positions, sorted(positions), out)  # C1 antes que C2
        for text in [
            # qué hace cada uno (el "cómo" de su hallazgo)
            "Crea el archivo con {} y completa el evento",
            "Agrega su configuración (la misma que crea seedflow).",
            "Cambia ../../events por ../events en src/handler.py.",
            "`ruff check --fix` arregla 1 de ellos solo",
            "Aplica `ruff format` al microservicio",
            "Agrega la línea .env al .gitignore de la raíz.",
            # y qué archivos tocaría
            f"{ORDERS}/events/orders.json",
            "projects/demo/python/.vscode/launch.json",
            f"{ORDERS}/src/handler.py",
            f"{ORDERS}/",
            ".gitignore",
        ]:
            with self.subTest(texto=text):
                self.assertIn(text, out)
        self.assertEqual(
            out.count("Agrega la línea .env al .gitignore de la raíz."), 1, out
        )
        lines = [line.strip() for line in out.splitlines()]
        self.assertIn(f"Toca: {ORDERS}/", lines)  # C1 y C2: el microservicio
        self.assertIn("Toca: .gitignore", lines)
        self.assertNotIn("H1", out)  # los avisos no tienen arreglo
        self.assertEqual(self.snapshot(), before)  # listar no escribe

    def test_fix_list_sin_arreglos_lo_dice(self):
        self.create("demo")
        (self.root / ".gitignore").write_text(".env\n", encoding="utf-8")
        before = self.snapshot()
        code, out, err = self.run_cli("fix", "--list")
        self.assertEqual(code, 0, out + err)
        self.assertIn("no hay arreglos", out.lower())
        self.assertEqual([i for i in IDS if i in out], [])
        self.assertEqual(self.snapshot(), before)

    def test_fix_sin_ids_no_hace_nada_y_lo_dice(self):
        self.old_repo()
        before = self.snapshot()
        code, out, err = self.run_cli("fix")
        self.assertEqual(code, 0, out + err)
        self.assertIn("no cambié nada", out)
        self.assertIn("fix --list", out)
        self.assertEqual(self.snapshot(), before)
        self.assertFalse((self.env / "calls.jsonl").exists())  # ni calificó

    def test_fix_list_con_ids_no_aplica_nada(self):
        self.old_repo()
        before = self.snapshot()
        code, out, err = self.run_cli("fix", "--list", "H2:.gitignore")
        self.assertEqual(code, 1, out + err)
        self.assertIn("❌", err)
        self.assertEqual(self.snapshot(), before)


class AplicarTest(FixTestCase):
    def test_fix_aplica_solo_los_pedidos(self):
        self.old_repo()
        before = self.snapshot()
        code, out, err = self.run_cli("fix", "H2:.gitignore", f"E3:{DEMO}")
        self.assertEqual(code, 0, out + err)
        after = self.snapshot()
        changed = sorted(
            path for path in set(before) | set(after)
            if before.get(path) != after.get(path)
        )
        self.assertEqual(
            changed, [".gitignore", f"{ORDERS}/events/orders.json"]
        )
        self.assertEqual(
            (self.root / ORDERS / "events" / "orders.json").read_text(), "{}\n"
        )
        # Imprime los archivos tocados, relativos a la raíz.
        lines = [line.strip() for line in out.splitlines()]
        self.assertIn(f"✏️  {ORDERS}/events/orders.json", lines)
        self.assertIn("✏️  .gitignore", lines)
        # Sin arreglos de calidad no corre ruff ni mypy (ni los instala).
        self.assertFalse((self.env / "calls.jsonl").exists())

    def test_fix_imprime_cada_arreglo_antes_de_lo_que_hace(self):
        # E4 imprime una línea mientras corre (update_launch): queda debajo
        # del arreglo que la produjo, y los archivos tocados después.
        self.old_repo()
        code, out, err = self.run_cli("fix", f"E4:{DEMO}", f"E3:{DEMO}")
        self.assertEqual(code, 0, out + err)
        lines = out.splitlines()

        def index(text):
            return next(i for i, line in enumerate(lines) if text in line)

        launch = "projects/demo/python/.vscode/launch.json"
        self.assertLess(index(f"E3:{DEMO}"), index(f"{ORDERS}/events/orders.json"))
        self.assertLess(index(f"{ORDERS}/events/orders.json"), index(f"E4:{DEMO}"))
        self.assertLess(index(f"E4:{DEMO}"), index("Configuración 'orders'"))
        self.assertLess(index("Configuración 'orders'"), index(launch))

    def test_fix_id_inexistente_no_aplica_nada(self):
        self.old_repo()
        before = self.snapshot()
        for unknown in [
            "Z9:nada",                              # ninguna regla lo ofrece
            "E5:otro/internal-services/orders",     # otro no tiene ese hallazgo
            "E3:demo/internal-services/nope",       # no existe
            "E3",                                   # sin lugar
        ]:
            with self.subTest(fix_id=unknown):
                # El válido va primero: tampoco se aplica.
                code, out, err = self.run_cli("fix", f"E3:{DEMO}", unknown)
                self.assertEqual(code, 1, out + err)
                self.assertIn("❌", err)
                self.assertIn(unknown, err)
                self.assertNotIn("Traceback", err)
                self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.fix_calls(), [])

    def test_fix_ids_repetidos_se_aplican_una_vez(self):
        self.old_repo()
        code, out, err = self.run_cli(
            "fix", "H2:.gitignore", f"E3:{DEMO}", "H2:.gitignore"
        )
        self.assertEqual(code, 0, out + err)
        self.assertEqual(out.count("H2:.gitignore"), 1, out)
        self.assertEqual(
            (self.root / ".gitignore").read_text().splitlines(),
            ["node_modules", ".env"],
        )

    def test_fix_aplica_c1_antes_que_c2(self):
        self.old_repo()
        code, out, err = self.run_cli("fix", f"C2:{DEMO}", f"C1:{DEMO}")
        self.assertEqual(code, 0, out + err)
        self.assertEqual(self.fix_calls(), ["check --fix", "format"])
        self.assertLess(out.index(f"C1:{DEMO}"), out.index(f"C2:{DEMO}"))
        self.assertIn(f"{ORDERS}/src/service/extra.py", out)
        self.assertEqual(
            (self.root / ORDERS / "src/service/extra.py").read_text(),
            "x = 1  # \ny = 2  # \n",
        )

    def test_fix_no_borra_archivos(self):
        self.old_repo()
        before = self.snapshot()
        code, out, err = self.run_cli("fix", *IDS)
        self.assertEqual(code, 0, out + err)
        after = self.snapshot()
        self.assertEqual(sorted(set(before) - set(after)), [])
        self.assertEqual(
            sorted(set(after) - set(before)), [f"{ORDERS}/events/orders.json"]
        )

    def test_errores_de_un_arreglo_se_reportan_sin_traceback(self):
        # SeedError de la copia de seedflow que importan las reglas (no la
        # de este módulo), ValueError (como el de higiene con un .gitignore
        # enlazado) y OSError.
        self.old_repo()
        estructura = importlib.import_module("checks.estructura")
        errors = [
            estructura.seedflow.SeedError("el arreglo no pudo"),
            ValueError("el arreglo no pudo"),
            PermissionError("el arreglo no pudo"),
        ]
        for error in errors:
            with self.subTest(error=type(error).__name__):

                def broken(root, fix_id, error=error):
                    raise error

                with mock.patch.dict(estructura.FIXES, {"E5": broken}):
                    code, out, err = self.run_cli(
                        "fix", f"E5:{DEMO}", f"E3:{DEMO}"
                    )
                self.assertEqual(code, 1, out + err)
                self.assertIn("❌", err)
                self.assertIn(f"E5:{DEMO}", err)
                self.assertIn("el arreglo no pudo", err)
                # Lo anterior quedó aplicado (E3 va antes que E5) y lo dice.
                self.assertTrue(
                    (self.root / ORDERS / "events" / "orders.json").is_file()
                )
                self.assertIn("E3", err)
                (self.root / ORDERS / "events" / "orders.json").unlink()

    def test_gitignore_enlazado_falla_controlado(self):
        self.old_repo()
        outside = self.base / "gitignore-de-afuera"
        outside.write_text("node_modules\n", encoding="utf-8")
        (self.root / ".gitignore").unlink()
        (self.root / ".gitignore").symlink_to(outside)
        code, out, err = self.run_cli("fix", "H2:.gitignore")
        self.assertEqual(code, 1, out + err)
        self.assertIn("❌", err)
        self.assertIn("enlace", err)
        self.assertEqual(outside.read_text(), "node_modules\n")


    def test_hallazgo_con_fix_id_sin_arreglo_no_se_ofrece(self):
        # Un fix_id cuyo prefijo no está en FIXES no se lista ni se aplica.
        self.create("demo")
        finding = self.checks.Finding(
            "dependencias", "Z2", 3, "demo", "projects/demo", "falla",
            "porque", "así", "Z2:demo",
        )
        rule = types.SimpleNamespace(
            __name__="checks.falso", CATEGORY="dependencias", QUICK=True,
            run=lambda ctx: self.checks.CheckResult([finding]), FIXES={},
        )
        with mock.patch.object(
            self.seedflow, "discover_rules", return_value=[rule]
        ):
            code, out, err = self.run_cli("fix", "--list")
            self.assertEqual(code, 0, out + err)
            self.assertNotIn("Z2:demo", out)
            self.assertIn("no hay arreglos", out.lower())
            code, out, err = self.run_cli("fix", "Z2:demo")
            self.assertEqual(code, 1, out + err)
            self.assertIn("❌", err)


class AvisoTest(FixTestCase):
    def test_avisos_de_cero_puntos_salen_como_aviso(self):
        # Fuera de git, H1 es un aviso de 0 puntos: no descuenta.
        self.create("demo")
        (self.root / ".gitignore").write_text(".env\n", encoding="utf-8")
        code, out, err = self.run_cli("check")
        self.assertEqual(code, 0, out + err)
        line = next(line for line in out.splitlines() if "[H1]" in line)
        self.assertIn("aviso", line)
        self.assertNotIn("-0", out)
        self.assertNotIn("−0", out)


class CliTest(FixTestCase):
    """En un proceso nuevo, como lo corren las skills."""

    def plugin_copy(self, rule=None):
        """Una copia de scripts/ dentro de la raíz, con una regla extra."""
        scripts = self.root / "plugin" / "scripts"
        shutil.copytree(
            SCRIPT.parent, scripts, ignore=shutil.ignore_patterns("__pycache__")
        )
        if rule is not None:
            (scripts / "checks" / "zz_regla_falsa.py").write_text(
                rule, encoding="utf-8"
            )
        return scripts / "seedflow.py"

    def test_despues_de_fix_la_nota_sube_lo_que_descontaba(self):
        self.old_repo()
        before = self.report(self.run_script)
        code, out, err = self.run_script("fix", "--list")
        self.assertEqual(code, 0, out + err)
        offered = [fix_id for fix_id in IDS if fix_id in out]
        self.assertEqual(offered, IDS)
        code, out, err = self.run_script("fix", *offered)
        self.assertEqual(code, 0, out + err)
        after = self.report(self.run_script)
        fixed = [f for f in before["findings"] if f["fix_id"] in offered]
        self.assertEqual(
            after["findings"],
            [f for f in before["findings"] if f["fix_id"] not in offered],
        )
        for old, new in zip(before["projects"], after["projects"]):
            for category, score in old["categories"].items():
                with self.subTest(project=old["name"], category=category):
                    recovered = sum(
                        f["points"] for f in fixed
                        if f["project"] == old["name"]
                        and f["category"] == category
                    )
                    self.assertEqual(
                        new["categories"][category], score + recovered
                    )
        self.assertGreater(after["score"], before["score"])
        code, out, err = self.run_script("check")
        self.assertEqual(code, 0, out + err)
        for fix_id in offered:
            self.assertNotIn(fix_id, out)
        code, out, err = self.run_script("fix", "--list")
        self.assertIn("no hay arreglos", out.lower())

    def test_id_invalido_por_cli_falla_sin_traceback(self):
        self.old_repo()
        before = self.snapshot()
        code, out, err = self.run_script("fix", f"E3:{DEMO}", "Z9:nada")
        self.assertEqual(code, 1, out + err)
        self.assertIn("❌", err)
        self.assertNotIn("Traceback", err)
        self.assertEqual(self.snapshot(), before)

    def test_seed_error_de_una_regla_por_cli_falla_sin_traceback(self):
        # Corriendo como script, seedflow.py es __main__ y las reglas hacen
        # `import seedflow`: su SeedError también es un error controlado.
        self.create("demo")
        script = self.plugin_copy(
            "import seedflow\n"
            "from checks import CheckResult, Finding\n"
            "CATEGORY = 'dependencias'\n"
            "QUICK = True\n"
            "def run(ctx):\n"
            "    return CheckResult([Finding('dependencias', 'Z1', 3, 'demo',\n"
            "        'projects/demo', 'falla', 'porque', 'así', 'Z1:demo')])\n"
            "def broken(root, fix_id):\n"
            "    raise seedflow.SeedError('la regla falsa no pudo')\n"
            "FIXES = {'Z1': broken}\n"
        )
        code, out, err = self.run_script("fix", "Z1:demo", script=script)
        self.assertEqual(code, 1, out + err)
        self.assertIn("❌", err)
        self.assertIn("la regla falsa no pudo", err)
        self.assertNotIn("Traceback", err)

    def test_fix_no_escribe_bytecode_aunque_el_plugin_este_en_la_raiz(self):
        self.old_repo()
        script = self.plugin_copy()
        env = {k: v for k, v in os.environ.items()
               if k not in ("PYTHONDONTWRITEBYTECODE", "PYTHONPYCACHEPREFIX")}
        for argv in [("fix", "--list"), ("fix", "H2:.gitignore")]:
            with self.subTest(argv=argv):
                code, out, err = self.run_script(*argv, script=script, env=env)
                self.assertEqual(code, 0, out + err)
                self.assertEqual(
                    sorted(p.as_posix() for p in self.root.rglob("__pycache__")),
                    [],
                )


if __name__ == "__main__":
    unittest.main()
