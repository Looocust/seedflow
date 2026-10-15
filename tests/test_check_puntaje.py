"""Tests de `seedflow.py check`: la nota, el semáforo y la salida.

Las reglas reales llegan en otros módulos de scripts/checks/; aquí se inyectan
módulos de reglas falsos para probar el cálculo sin depender de ellas.

Solo librería estándar. Desde la raíz del repo:

    python3 -m unittest tests.test_check_puntaje -v

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
import time
import types
import unittest
from dataclasses import fields
from pathlib import Path
from unittest import mock


REPO = Path(__file__).resolve().parent.parent
SCRIPT = Path(
    os.environ.get(
        "SEEDFLOW_SCRIPT", REPO / "plugins" / "seedflow" / "scripts" / "seedflow.py"
    )
)
CATEGORIAS = ["estructura", "calidad", "dependencias", "higiene"]


def load_seedflow():
    """Carga el script como módulo, fresco en cada test."""
    spec = importlib.util.spec_from_file_location("seedflow_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CheckTestCase(unittest.TestCase):
    """Base: una raíz temporal fuera de git y módulos de reglas falsos."""

    def setUp(self):
        self.seedflow = load_seedflow()
        self.checks = self.seedflow.load_checks()
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name).resolve()
        self.root = self.base / "repo"
        self.root.mkdir()
        # Que git no encuentre un repo por encima de la carpeta temporal.
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

    def run_with_rules(self, rules, *argv):
        """Corre el script con estos módulos de reglas en lugar de los reales."""
        with mock.patch.object(self.seedflow, "discover_rules", return_value=rules):
            return self.run_cli(*argv)

    def check_json(self, rules, *extra):
        code, out, err = self.run_with_rules(rules, "check", "--json", *extra)
        self.assertEqual(code, 0, out + err)
        return json.loads(out)

    def make_projects(self, *names):
        """Proyectos mínimos (solo la carpeta python/)."""
        for name in names:
            (self.root / "projects" / name / "python").mkdir(parents=True)

    def finding(self, category, points, project="demo", rule="X1", path=None):
        return self.checks.Finding(
            category=category,
            rule=rule,
            points=points,
            project=project,
            path=path or f"projects/{project}",
            message=f"{rule} falla",
            why="porque sí",
            how="arréglalo",
            fix_id=None,
        )

    def rule(self, category, findings=(), not_evaluated=None, quick=True,
             calls=None):
        """Un módulo de reglas falso."""

        def run(ctx):
            if calls is not None:
                calls.append(ctx)
            return self.checks.CheckResult(
                findings=list(findings), not_evaluated=dict(not_evaluated or {})
            )

        return types.SimpleNamespace(
            __name__=f"checks.falso_{category}",
            CATEGORY=category,
            QUICK=quick,
            run=run,
        )

    def project(self, report, name="demo"):
        return next(p for p in report["projects"] if p["name"] == name)

    def git(self, *args):
        git = shutil.which("git")
        if not git:
            self.skipTest("git no está instalado")
        subprocess.run(
            [git, *args], cwd=self.root, check=True, capture_output=True
        )


class FormulaTest(CheckTestCase):
    def test_categoria_no_baja_de_cero(self):
        self.make_projects("demo")
        report = self.check_json([
            self.rule("estructura", [
                self.finding("estructura", 60, rule="E1"),
                self.finding("estructura", 50, rule="E2"),
            ]),
            self.rule("higiene"),
        ])
        demo = self.project(report)
        self.assertEqual(demo["categories"]["estructura"], 0)
        self.assertEqual(demo["categories"]["higiene"], 100)
        self.assertEqual(demo["score"], 50)

    def test_proyecto_promedia_solo_categorias_evaluadas(self):
        self.make_projects("demo", "otro")
        report = self.check_json([
            self.rule("estructura", [self.finding("estructura", 15)]),
            self.rule("dependencias"),
            self.rule(
                "higiene",
                [self.finding("higiene", 25, project="otro")],
                not_evaluated={"demo": "no es un repo git"},
            ),
        ])
        demo = self.project(report)
        # calidad no tiene módulo e higiene no se pudo evaluar en demo:
        # ninguna de las dos entra en el promedio.
        self.assertEqual(
            demo["categories"],
            {"estructura": 85, "calidad": None, "dependencias": 100,
             "higiene": None},
        )
        self.assertEqual(demo["not_evaluated"]["higiene"], "no es un repo git")
        self.assertIn("calidad", demo["not_evaluated"])
        self.assertNotIn("estructura", demo["not_evaluated"])
        # (85 + 100) / 2 = 92.5, que sube a 93.
        self.assertEqual(demo["score"], 93)
        otro = self.project(report, "otro")
        self.assertEqual(otro["categories"]["higiene"], 75)
        self.assertEqual(otro["score"], 92)  # (100 + 100 + 75) / 3 = 91.67

    def test_repo_promedia_proyectos_y_redondea_hacia_arriba(self):
        self.make_projects("a", "b")
        report = self.check_json([
            self.rule("estructura", [
                self.finding("estructura", 25, project="a"),
                self.finding("estructura", 10, project="b", rule="E1"),
                self.finding("estructura", 10, project="b", rule="E2"),
                self.finding("estructura", 3, project="b", rule="E3"),
                self.finding("estructura", 3, project="b", rule="E4"),
            ]),
        ])
        self.assertEqual(self.project(report, "a")["score"], 75)
        self.assertEqual(self.project(report, "b")["score"], 74)
        # (75 + 74) / 2 = 74.5: hacia arriba es 75 (round() de Python da 74).
        self.assertEqual(report["score"], 75)
        self.assertEqual(report["semaphore"], "🟢")

    def test_repo_no_promedia_proyectos_sin_nota(self):
        self.make_projects("a", "b")
        report = self.check_json([
            self.rule(
                "estructura",
                [self.finding("estructura", 40, project="a")],
                not_evaluated={"b": "launch.json con comentarios"},
            ),
        ])
        self.assertIsNone(self.project(report, "b")["score"])
        # Solo cuenta a (60); b no tiene nota y no baja el promedio a 30.
        self.assertEqual(report["score"], 60)

    def test_repo_promedia_las_notas_ya_redondeadas_de_los_proyectos(self):
        self.make_projects("a", "b")
        report = self.check_json([
            self.rule("estructura", [
                self.finding("estructura", 15, project="a"),
                self.finding("estructura", 16, project="b"),
            ]),
            self.rule("dependencias"),
        ])
        # a: (85 + 100) / 2 = 92.5 → 93; b: (84 + 100) / 2 = 92.
        self.assertEqual(self.project(report, "a")["score"], 93)
        self.assertEqual(self.project(report, "b")["score"], 92)
        # Con las notas que ve el usuario: (93 + 92) / 2 = 92.5 → 93.
        # (Con las notas sin redondear sería (92.5 + 92) / 2 = 92.25 → 92.)
        self.assertEqual(report["score"], 93)

    def test_redondeo_hacia_abajo_por_debajo_de_punto_cinco(self):
        self.make_projects("a", "b", "c")
        report = self.check_json([
            self.rule("estructura", [
                self.finding("estructura", 26, project="a"),
                self.finding("estructura", 25, project="b"),
                self.finding("estructura", 25, project="c"),
            ]),
        ])
        # (74 + 75 + 75) / 3 = 74.67 → 75; y con 2 en 74: 74.33 → 74.
        self.assertEqual(report["score"], 75)
        report = self.check_json([
            self.rule("estructura", [
                self.finding("estructura", 26, project="a"),
                self.finding("estructura", 26, project="b"),
                self.finding("estructura", 25, project="c"),
            ]),
        ])
        self.assertEqual(report["score"], 74)

    def test_semaforo_en_los_bordes_74_75_49_50(self):
        self.make_projects("demo")
        for points, score, light in [
            (0, 100, "🟢"),
            (25, 75, "🟢"),
            (26, 74, "🟡"),
            (50, 50, "🟡"),
            (51, 49, "🔴"),
            (200, 0, "🔴"),
        ]:
            with self.subTest(nota=score):
                rules = [self.rule(
                    "estructura",
                    [self.finding("estructura", points)] if points else [],
                )]
                report = self.check_json(rules)
                self.assertEqual(report["score"], score)
                self.assertEqual(report["semaphore"], light)
                code, out, _ = self.run_with_rules(rules, "check", "--quick")
                self.assertEqual(code, 0)
                self.assertIn(f"{score}/100 {light}", out)

    def test_hallazgos_salen_en_orden_estable(self):
        self.make_projects("a", "b")
        desordenados = [
            self.finding("higiene", 3, project="b", rule="H1"),
            self.finding("higiene", 3, project="a", rule="H2", path="projects/a/z"),
            self.finding("higiene", 3, project="a", rule="H1", path="projects/a/z"),
            self.finding("higiene", 3, project="a", rule="H9", path="projects/a/b"),
        ]
        estructura = [self.finding("estructura", 3, project="b", rule="E1")]
        report = self.check_json([
            self.rule("higiene", desordenados), self.rule("estructura", estructura)
        ])
        self.assertEqual(
            [(f["project"], f["rule"], f["path"]) for f in report["findings"]],
            [
                ("a", "H9", "projects/a/b"),
                ("a", "H1", "projects/a/z"),
                ("a", "H2", "projects/a/z"),
                ("b", "E1", "projects/b"),
                ("b", "H1", "projects/b"),
            ],
        )

    def test_hallazgo_de_otra_categoria_es_un_error_del_modulo(self):
        self.make_projects("demo")
        with self.assertRaises(ValueError) as error:
            self.check_json([
                self.rule("estructura", [self.finding("higiene", 10)]),
            ])
        self.assertIn("higiene", str(error.exception))


class QuickTest(CheckTestCase):
    def test_modulo_no_quick_no_corre_en_quick(self):
        self.make_projects("demo")
        calidad, estructura = [], []
        rules = [
            self.rule("calidad", [self.finding("calidad", 30)], quick=False,
                      calls=calidad),
            self.rule("estructura", calls=estructura),
        ]
        report = self.check_json(rules, "--quick")
        self.assertEqual(calidad, [])
        self.assertEqual(len(estructura), 1)
        self.assertTrue(estructura[0].quick)
        demo = self.project(report)
        self.assertIsNone(demo["categories"]["calidad"])
        self.assertIn("calidad", demo["not_evaluated"])
        self.assertEqual(demo["score"], 100)
        self.assertEqual(report["findings"], [])

        # Sin --quick sí corre, y su descuento cuenta.
        report = self.check_json(rules)
        self.assertEqual(len(calidad), 1)
        self.assertFalse(calidad[0].quick)
        self.assertEqual(self.project(report)["categories"]["calidad"], 70)
        self.assertEqual(self.project(report)["score"], 85)

    def test_quick_imprime_una_linea(self):
        self.make_projects("demo")
        rules = [self.rule("estructura", [
            self.finding("estructura", 10, rule="E1"),
            self.finding("estructura", 3, rule="E2"),
        ])]
        code, out, err = self.run_with_rules(rules, "check", "--quick")
        self.assertEqual(code, 0, err)
        self.assertEqual(
            out,
            "repo: 87/100 🟢 · 2 cosas por mejorar (sin calidad de código)"
            " · detalle: /seedflow:revisar\n",
        )
        rules = [self.rule("estructura", [self.finding("estructura", 3)])]
        _, out, _ = self.run_with_rules(rules, "check", "--quick")
        self.assertIn("· 1 cosa por mejorar (sin calidad de código) ·", out)

    def test_quick_rapido_con_20_proyectos_y_100_microservicios(self):
        # Un proyecto real con 5 microservicios, copiado 19 veces (crearlos
        # todos con el CLI hace lento el test sin cambiar lo que se mide).
        code, out, err = self.run_cli(
            "create-project", "p0", "--service-type", "internal-services",
            "--skip-cdk",
        )
        self.assertEqual(code, 0, out + err)
        for m in range(5):
            code, out, err = self.run_cli(
                "create-microservice", f"m{m}", "--project", "p0",
                "--service-type", "internal-services",
            )
            self.assertEqual(code, 0, out + err)
        projects = self.root / "projects"
        for p in range(1, 20):
            shutil.copytree(projects / "p0", projects / f"p{p}", symlinks=True)
        if shutil.which("git"):
            self.git("init", "-q")
            self.git("add", "-A")
        start = time.perf_counter()
        code, out, err = self.run_cli("check", "--quick")  # reglas reales
        elapsed = time.perf_counter() - start
        self.assertEqual(code, 0, out + err)
        self.assertEqual(len(out.splitlines()), 1, out)
        self.assertLess(elapsed, 2.0)


class SalidaTest(CheckTestCase):
    def test_json_tiene_la_forma_del_contrato(self):
        self.make_projects("demo")
        finding = self.checks.Finding(
            category="estructura",
            rule="E3",
            points=3,
            project="demo",
            path="projects/demo/python/internal-services/orders/events",
            message="Falta events/orders.json",
            why="Sin evento no se puede probar el handler",
            how="Crea el archivo con {}",
            fix_id="E3:demo/internal-services/orders",
        )
        report = self.check_json([self.rule("estructura", [finding])])
        self.assertEqual(
            set(report), {"root", "score", "semaphore", "projects", "findings"}
        )
        self.assertEqual(report["root"], str(self.root))
        self.assertEqual(report["score"], 97)
        self.assertEqual(report["semaphore"], "🟢")
        self.assertEqual(
            report["projects"],
            [{
                "name": "demo",
                "score": 97,
                "categories": {
                    "estructura": 97,
                    "calidad": None,
                    "dependencias": None,
                    "higiene": None,
                },
                "not_evaluated": report["projects"][0]["not_evaluated"],
            }],
        )
        not_evaluated = report["projects"][0]["not_evaluated"]
        self.assertEqual(
            set(not_evaluated), {"calidad", "dependencias", "higiene"}
        )
        self.assertTrue(all(isinstance(v, str) and v for v in not_evaluated.values()))
        self.assertEqual(
            report["findings"],
            [{
                "category": "estructura",
                "rule": "E3",
                "points": 3,
                "project": "demo",
                "path": "projects/demo/python/internal-services/orders/events",
                "message": "Falta events/orders.json",
                "why": "Sin evento no se puede probar el handler",
                "how": "Crea el archivo con {}",
                "fix_id": "E3:demo/internal-services/orders",
            }],
        )
        self.assertEqual(
            [f.name for f in fields(self.checks.Finding)],
            ["category", "rule", "points", "project", "path", "message",
             "why", "how", "fix_id"],
        )
        self.assertEqual(tuple(self.checks.CATEGORIES), tuple(CATEGORIAS))
        self.assertEqual(
            self.checks.SEVERITY, {"critico": 25, "importante": 10, "menor": 3}
        )

    def test_reporte_completo_muestra_cada_hallazgo(self):
        self.make_projects("demo")
        finding = self.finding("estructura", 10, rule="E1",
                               path="projects/demo/iac")
        code, out, err = self.run_with_rules(
            [self.rule("estructura", [finding])], "check"
        )
        self.assertEqual(code, 0, err)
        for text in ["90/100", "demo", "E1", "projects/demo/iac", "E1 falla",
                     "porque sí", "arréglalo", "10"]:
            with self.subTest(texto=text):
                self.assertIn(text, out)

    def test_sin_projects_dice_que_no_hay_proyectos(self):
        rules = [self.rule("estructura")]
        for preparar in [lambda: None,
                         lambda: (self.root / "projects").mkdir()]:
            preparar()
            with self.subTest(projects=(self.root / "projects").exists()):
                for extra in [(), ("--quick",)]:
                    code, out, err = self.run_with_rules(rules, "check", *extra)
                    self.assertEqual(code, 0, err)
                    self.assertIn("no encontré proyectos", out.lower())
                    self.assertIn(str(self.root / "projects"), out)
                    self.assertEqual(len(out.splitlines()), 1, out)
                report = self.check_json(rules)
                self.assertEqual(report["projects"], [])
                self.assertIsNone(report["score"])
                self.assertIsNone(report["semaphore"])
                self.assertEqual(report["findings"], [])

    def test_check_no_escribe_en_el_repo(self):
        code, out, err = self.run_cli(
            "create-project", "demo", "--service-type", "internal-services",
            "--skip-cdk",
        )
        self.assertEqual(code, 0, out + err)
        code, out, err = self.run_cli(
            "create-microservice", "orders", "--project", "demo",
            "--service-type", "internal-services",
        )
        self.assertEqual(code, 0, out + err)
        if shutil.which("git"):
            self.git("init", "-q")
            self.git("add", "-A")

        def snapshot():
            result = {}
            for path in sorted(self.root.rglob("*")):
                stat = path.lstat()
                content = (
                    hashlib.sha256(path.read_bytes()).hexdigest()
                    if path.is_file() else None
                )
                result[path.relative_to(self.root).as_posix()] = (
                    stat.st_mode, stat.st_mtime_ns, content
                )
            return result

        before = snapshot()
        rules = [self.rule("estructura", [self.finding("estructura", 10)])]
        for extra in [(), ("--quick",), ("--json",), ("--quick", "--json")]:
            with self.subTest(args=extra):
                code, out, err = self.run_cli("check", *extra)  # reglas reales
                self.assertEqual(code, 0, out + err)
                code, out, err = self.run_with_rules(rules, "check", *extra)
                self.assertEqual(code, 0, out + err)
                self.assertEqual(snapshot(), before)


    def test_check_no_escribe_bytecode_aunque_el_plugin_este_en_la_raiz(self):
        # Califica una raíz que contiene una copia del plugin (como cuando se
        # califica el propio repo seedflow), en un proceso nuevo y sin
        # PYTHONDONTWRITEBYTECODE: importar checks/ no puede dejar __pycache__.
        self.make_projects("demo")
        scripts = self.root / "plugin" / "scripts"
        shutil.copytree(
            SCRIPT.parent, scripts, ignore=shutil.ignore_patterns("__pycache__")
        )
        (scripts / "checks" / "zz_regla_falsa.py").write_text(
            "from checks import CheckResult\n"
            "CATEGORY = 'estructura'\n"
            "QUICK = True\n"
            "def run(ctx):\n"
            "    import checks._ayuda_falsa  # importada recién al correr\n"
            "    return CheckResult()\n"
        )
        (scripts / "checks" / "_ayuda_falsa.py").write_text("X = 1\n")
        env = {k: v for k, v in os.environ.items()
               if k not in ("PYTHONDONTWRITEBYTECODE", "PYTHONPYCACHEPREFIX")}
        before = sorted(p.relative_to(self.root).as_posix()
                        for p in self.root.rglob("*"))
        for extra in [(), ("--quick",), ("--json",)]:
            with self.subTest(args=extra):
                result = subprocess.run(
                    [sys.executable, str(scripts / "seedflow.py"),
                     "--root", str(self.root), "check", *extra],
                    env=env, capture_output=True, text=True, check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("100", result.stdout)  # la regla falsa corrió
                after = sorted(p.relative_to(self.root).as_posix()
                               for p in self.root.rglob("*"))
                self.assertEqual(after, before)


class ContextoTest(CheckTestCase):
    def capture_context(self, *extra):
        calls = []
        code, out, err = self.run_with_rules(
            [self.rule("estructura", calls=calls)], "check", *extra
        )
        self.assertEqual(code, 0, out + err)
        self.assertEqual(len(calls), 1)
        return calls[0]

    def test_fuera_de_git_tracked_es_none(self):
        self.make_projects("demo")
        ctx = self.capture_context()
        self.assertIsNone(ctx.tracked)
        self.assertEqual(ctx.root, self.root)

    def test_dentro_de_git_tracked_lista_lo_commiteado(self):
        self.make_projects("demo")
        (self.root / "projects" / "demo" / "python" / "a.py").write_text("")
        (self.root / "projects" / "demo" / "python" / "nuevo.py").write_text("")
        self.git("init", "-q")
        self.git("add", "projects/demo/python/a.py")
        ctx = self.capture_context()
        self.assertEqual(ctx.tracked, {"projects/demo/python/a.py"})

    def test_contexto_lista_proyectos_y_microservicios(self):
        for project, service_type, name in [
            ("demo", "internal-services", "orders"),
            ("demo", "consumable-services", "api"),
            ("demo", "internal-services", "billing"),
        ]:
            (self.root / "projects" / project / "python" / service_type
             / name).mkdir(parents=True)
        (self.root / "projects" / "vacio").mkdir()
        (self.root / "projects" / "suelto.txt").write_text("")
        ctx = self.capture_context("--quick")
        self.assertTrue(ctx.quick)
        self.assertEqual([p.name for p in ctx.projects], ["demo", "vacio"])
        demo, vacio = ctx.projects
        self.assertEqual(demo.path, self.root / "projects" / "demo")
        self.assertEqual(
            [(m.service_type, m.name, m.path) for m in demo.microservices],
            [
                ("internal-services", "billing",
                 self.root / "projects/demo/python/internal-services/billing"),
                ("internal-services", "orders",
                 self.root / "projects/demo/python/internal-services/orders"),
                ("consumable-services", "api",
                 self.root / "projects/demo/python/consumable-services/api"),
            ],
        )
        self.assertEqual(vacio.microservices, [])


    def test_no_atraviesa_enlaces(self):
        afuera = self.base / "afuera"
        (afuera / "python" / "internal-services" / "x").mkdir(parents=True)
        (self.root / "projects" / "demo" / "python" / "internal-services").mkdir(
            parents=True
        )
        servicios = self.root / "projects" / "demo" / "python" / "internal-services"
        try:
            (self.root / "projects" / "enlace").symlink_to(
                afuera, target_is_directory=True
            )
            (servicios / "enlazado").symlink_to(
                afuera / "python" / "internal-services" / "x",
                target_is_directory=True,
            )
        except (OSError, NotImplementedError):
            self.skipTest("este sistema no permite crear enlaces simbólicos")
        ctx = self.capture_context()
        self.assertEqual([p.name for p in ctx.projects], ["demo"])
        self.assertEqual(ctx.projects[0].microservices, [])


class DescubrimientoTest(CheckTestCase):
    def make_package(self, files):
        """Un paquete de reglas temporal con nombre único, importable."""
        self.packages = getattr(self, "packages", 0) + 1
        name = f"reglas_{self.id().rsplit('.', 1)[-1]}_{self.packages}"
        folder = self.base / "paquetes" / name
        folder.mkdir(parents=True)
        (folder / "__init__.py").write_text(
            "CATEGORIES = ('estructura', 'calidad', 'dependencias', 'higiene')\n"
        )
        for filename, content in files.items():
            (folder / filename).write_text(content)
        if str(folder.parent) not in sys.path:
            sys.path.insert(0, str(folder.parent))
            self.addCleanup(sys.path.remove, str(folder.parent))
        self.addCleanup(
            lambda: [sys.modules.pop(m) for m in list(sys.modules)
                     if m == name or m.startswith(name + ".")]
        )
        importlib.invalidate_caches()
        return importlib.import_module(name)

    def test_descubre_los_modulos_en_orden_y_omite_los_privados(self):
        rule = "CATEGORY = '{}'\nQUICK = {}\ndef run(ctx):\n    return None\n"
        package = self.make_package({
            "zeta.py": rule.format("higiene", True),
            "alfa.py": rule.format("calidad", False),
            "_ayuda.py": "X = 1\n",
        })
        modules = self.seedflow.discover_rules(package)
        self.assertEqual(
            [m.__name__.rsplit(".", 1)[-1] for m in modules], ["alfa", "zeta"]
        )

    def test_modulo_que_no_cumple_el_contrato_es_un_error(self):
        for content in [
            "QUICK = True\ndef run(ctx):\n    return None\n",
            "CATEGORY = 'otra'\nQUICK = True\ndef run(ctx):\n    return None\n",
            "CATEGORY = 'higiene'\nQUICK = 'si'\ndef run(ctx):\n    return None\n",
            "CATEGORY = 'higiene'\nQUICK = True\nrun = 3\n",
        ]:
            with self.subTest(modulo=content):
                package = self.make_package({"mala.py": content})
                with self.assertRaises(self.seedflow.SeedError) as error:
                    self.seedflow.discover_rules(package)
                self.assertIn("mala", str(error.exception))

    def test_las_reglas_reales_cumplen_el_contrato(self):
        for module in self.seedflow.discover_rules():
            with self.subTest(modulo=module.__name__):
                self.assertIn(module.CATEGORY, CATEGORIAS)
                self.assertIsInstance(module.QUICK, bool)
                self.assertEqual(module.QUICK, module.CATEGORY != "calidad")


if __name__ == "__main__":
    unittest.main()
