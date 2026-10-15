"""Comprueba que los tests detectan fallas reales en el motor y en las reglas.

Copia plugins/seedflow/scripts/ completo a una carpeta temporal (sin tocar el
original), mete una falla por vez en la copia, corre la suite contra esa copia
y espera que falle. Si una falla pasa sin que ningún test se ponga en rojo, ese
comportamiento no está protegido.

Las fallas viven en tests/mutantes/*.py, un archivo por tema (motor, puntaje,
estructura...), para que cada tarea agregue las suyas sin tocar las de otra.
Cada archivo define:

    TARGET = "plugins/seedflow/scripts/checks/estructura.py"  # desde la raíz
    MUTANTES = [
        ("qué se rompe", [("texto original", "texto roto"), ...]),
        ...
    ]

Cada texto original se reemplaza una sola vez (la primera aparición) en
TARGET; si no aparece, la falla cuenta como sobreviviente.

Opcionalmente, un archivo define qué módulos de test cubren sus fallas:

    TESTS = ["test_check_estructura"]

Con TESTS, cada falla de ese archivo corre solo esos módulos (mucho más
rápido); sin TESTS, corre la suite completa. Si una falla sobrevive con los
módulos elegidos, el resultado lo muestra: lo peor que puede pasar es una falsa
alarma, nunca una falla tapada.

Desde la raíz del repo:

    python3 tests/mutantes.py

Las fallas corren en paralelo, cada una en su propia copia de scripts/. SEEDFLOW_MUTANTES_JOBS fija cuántas a la vez (por defecto,
la mitad de los núcleos).
"""

from __future__ import annotations

import concurrent.futures
import os
import runpy
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent
PLUGIN = REPO / "plugins" / "seedflow"
SCRIPTS = PLUGIN / "scripts"
LISTAS = Path(__file__).resolve().parent / "mutantes"


def cargar_listas() -> list[tuple[str, Path, list, list[str]]]:
    """(tema, TARGET relativo a scripts/, MUTANTES, TESTS) de cada archivo."""
    listas = []
    for archivo in sorted(LISTAS.glob("*.py")):
        datos = runpy.run_path(str(archivo))
        target = (REPO / datos["TARGET"]).resolve()
        if SCRIPTS not in target.parents or not target.is_file():
            raise SystemExit(
                f"{archivo.name}: TARGET debe ser un archivo dentro de "
                f"{SCRIPTS.relative_to(REPO)}/ (es {datos['TARGET']!r})."
            )
        tests = list(datos.get("TESTS", []))
        for modulo in tests:
            if not (Path(__file__).resolve().parent / f"{modulo}.py").is_file():
                raise SystemExit(f"{archivo.name}: no existe tests/{modulo}.py")
        listas.append(
            (
                archivo.stem,
                target.relative_to(SCRIPTS),
                datos["MUTANTES"],
                tests,
            )
        )
    return listas


def run_suite(script: Path, tests: list[str] | None = None) -> bool:
    """True si la suite (o solo esos módulos de tests/) pasa con ese script."""
    if tests:
        comando = [sys.executable, "-m", "unittest", *[f"tests.{t}" for t in tests]]
    else:
        comando = [sys.executable, "-m", "unittest", "discover", "-s", "tests"]
    result = subprocess.run(
        comando,
        cwd=REPO,
        env={
            **os.environ,
            "SEEDFLOW_SCRIPT": str(script),
            "PYTHONDONTWRITEBYTECODE": "1",
        },
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0


def mutar(texto: str, reemplazos: list) -> str | None:
    """El texto con la falla aplicada, o None si algún original no aparece."""
    if any(viejo not in texto for viejo, _ in reemplazos):
        return None
    for viejo, nuevo in reemplazos:
        texto = texto.replace(viejo, nuevo, 1)
    return texto


def probar(target: Path, mutado: str, tests: list[str]) -> bool:
    """True si la suite detecta la falla (en una copia propia de scripts/)."""
    with tempfile.TemporaryDirectory() as temp:
        copia = Path(temp) / "scripts"
        shutil.copytree(
            SCRIPTS, copia, ignore=shutil.ignore_patterns("__pycache__")
        )
        (Path(temp) / "templates").symlink_to(PLUGIN / "templates")
        (copia / target).write_text(mutado, encoding="utf-8")
        return not run_suite(copia / "seedflow.py", tests)


def trabajos() -> int:
    """Cuántas fallas corren a la vez."""
    pedido = os.environ.get("SEEDFLOW_MUTANTES_JOBS", "")
    if pedido.isdigit() and int(pedido) > 0:
        return int(pedido)
    return max(1, (os.cpu_count() or 2) // 2)


def main() -> int:
    """Corre cada mutante y reporta los que sobreviven."""
    listas = cargar_listas()
    if not run_suite(SCRIPTS / "seedflow.py"):
        print("La suite ya falla con el script original: arregla eso primero.")
        return 1
    casos = []
    for tema, target, mutantes, tests in listas:
        original = (SCRIPTS / target).read_text(encoding="utf-8")
        for descripcion, reemplazos in mutantes:
            casos.append(
                (
                    f"[{tema}] {descripcion}",
                    target,
                    mutar(original, reemplazos),
                    tests,
                )
            )
    sobrevivientes = []
    with concurrent.futures.ThreadPoolExecutor(trabajos()) as pool:
        futuros = [
            pool.submit(probar, target, mutado, tests)
            if mutado is not None
            else None
            for _, target, mutado, tests in casos
        ]
        for (nombre, _, _, _), futuro in zip(casos, futuros):
            if futuro is None:
                print(f"⚠️  no encontré el texto para «{nombre}»", flush=True)
                sobrevivientes.append(nombre)
            elif futuro.result():
                print(f"✅ detectado: {nombre}", flush=True)
            else:
                print(f"❌ sobrevive: {nombre}", flush=True)
                sobrevivientes.append(nombre)
    print(f"\n{len(casos) - len(sobrevivientes)}/{len(casos)} detectados")
    return 1 if sobrevivientes else 0


if __name__ == "__main__":
    sys.exit(main())
