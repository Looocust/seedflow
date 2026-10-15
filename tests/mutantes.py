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

Desde la raíz del repo:

    python3 tests/mutantes.py
"""

from __future__ import annotations

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


def cargar_listas() -> list[tuple[str, Path, list]]:
    """(tema, TARGET relativo a scripts/, MUTANTES) de cada archivo de fallas."""
    listas = []
    for archivo in sorted(LISTAS.glob("*.py")):
        datos = runpy.run_path(str(archivo))
        target = (REPO / datos["TARGET"]).resolve()
        if SCRIPTS not in target.parents or not target.is_file():
            raise SystemExit(
                f"{archivo.name}: TARGET debe ser un archivo dentro de "
                f"{SCRIPTS.relative_to(REPO)}/ (es {datos['TARGET']!r})."
            )
        listas.append(
            (archivo.stem, target.relative_to(SCRIPTS), datos["MUTANTES"])
        )
    return listas


def run_suite(script: Path) -> bool:
    """True si la suite pasa contra ese script."""
    result = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests"],
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


def main() -> int:
    """Corre cada mutante y reporta los que sobreviven."""
    listas = cargar_listas()
    if not run_suite(SCRIPTS / "seedflow.py"):
        print("La suite ya falla con el script original: arregla eso primero.")
        return 1

    total = 0
    sobrevivientes = []
    with tempfile.TemporaryDirectory() as temp:
        copia = Path(temp) / "scripts"
        shutil.copytree(
            SCRIPTS, copia, ignore=shutil.ignore_patterns("__pycache__")
        )
        (Path(temp) / "templates").symlink_to(PLUGIN / "templates")
        for tema, target, mutantes in listas:
            archivo = copia / target
            original = archivo.read_text(encoding="utf-8")
            for descripcion, reemplazos in mutantes:
                total += 1
                nombre = f"[{tema}] {descripcion}"
                mutado = mutar(original, reemplazos)
                if mutado is None:
                    print(f"⚠️  no encontré el texto para «{nombre}»")
                    sobrevivientes.append(nombre)
                    continue
                archivo.write_text(mutado, encoding="utf-8")
                try:
                    detectado = not run_suite(copia / "seedflow.py")
                finally:
                    archivo.write_text(original, encoding="utf-8")
                if detectado:
                    print(f"✅ detectado: {nombre}")
                else:
                    print(f"❌ sobrevive: {nombre}")
                    sobrevivientes.append(nombre)

    print(f"\n{total - len(sobrevivientes)}/{total} detectados")
    return 1 if sobrevivientes else 0


if __name__ == "__main__":
    sys.exit(main())
