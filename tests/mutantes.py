"""Comprueba que los tests detectan fallas reales en el motor.

Mete una falla por vez en una copia de seedflow.py (sin tocar el original),
corre la suite contra esa copia y espera que falle. Si una falla pasa sin que
ningún test se ponga en rojo, ese comportamiento no está protegido.

Desde la raíz del repo:

    python3 tests/mutantes.py
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent
PLUGIN = REPO / "plugins" / "seedflow"

# (qué se rompe, [(texto original, texto roto), ...])
MUTANTES = [
    ("acepta nombres con basura al final (match en vez de fullmatch)",
     [("NAME_PATTERN.fullmatch(value)", "NAME_PATTERN.match(value)")]),
    ("acepta nombres reservados de Windows",
     [("    if value.lower() in WINDOWS_RESERVED:", "    if False:")]),
    ("atraviesa enlaces simbólicos",
     [("        if is_link(path):", "        if False:")]),
    ("no detecta enlaces que is_symlink() no ve (junctions)",
     [("    return literal != resolved", "    return False")]),
    ("el temporal de launch.json usa un nombre fijo",
     [('    descriptor, temporary = tempfile.mkstemp(\n'
       '        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"\n'
       '    )',
       '    temporary = str(path.with_name(path.name + ".seedflow-tmp"))\n'
       '    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC)')]),
    ("deja el temporal si falla el reemplazo",
     [("            os.unlink(temporary)", "            pass")]),
    ("el rollback borra contenedores con trabajo ajeno",
     [("    rollback.created(path, recursive=not container)",
       "    rollback.created(path, recursive=True)")]),
    ("revienta si launch.json no se puede leer",
     [("(json.JSONDecodeError, UnicodeDecodeError, OSError)",
       "(json.JSONDecodeError, UnicodeDecodeError)")]),
    ("borra antes de actualizar launch.json",
     [("    update_launch(root, args.project, name, args.service_type, add=False)\n"
       "    try:\n        shutil.rmtree(target)\n",
       "    try:\n        shutil.rmtree(target)\n"
       "        update_launch(root, args.project, name, args.service_type, add=False)\n")]),
    ("no restaura launch.json si el borrado falla",
     [("        leftovers = rollback.undo()\n", "        leftovers = []\n")]),
    ("borrar con otra capitalización deja la configuración",
     [('    name = existing_name(services, validate_name(args.name, "microservicio"))',
       '    name = validate_name(args.name, "microservicio")')]),
    ("sobrescribe un proyecto existente",
     [('    if target.exists():\n        raise SeedError(f"El proyecto',
       '    if False:\n        raise SeedError(f"El proyecto'),
      ("        path.mkdir()\n", "        path.mkdir(exist_ok=True)\n")]),
    ("sobrescribe un microservicio existente",
     [("    if target.exists():\n        raise SeedError(\n"
       "            f\"El microservicio",
       "    if False:\n        raise SeedError(\n"
       "            f\"El microservicio"),
      ("        path.mkdir()\n", "        path.mkdir(exist_ok=True)\n")]),
    ("borra sin --yes", [("    if not args.yes:", "    if False:")]),
    ("--dry-run borra o falla", [("    if args.dry_run:", "    if False:")]),
    ("no revisa cdk antes de crear",
     [('    if not args.skip_cdk and not (find_tool("cdk") and find_tool("npm")):',
       "    if False:")]),
    ("cdk init vuelve a crear un repo git anidado",
     [('"--language=typescript", "--generate-only"]', '"--language=typescript"]')]),
    ("no deshace el proyecto si algo falla",
     [('        rollback.report("del proyecto")', "        pass")]),
    ("deja projects/ vacía después del rollback",
     [("            reserve_folder(\n"
       '                projects, rollback, "La carpeta projects/", container=True\n'
       "            )",
       "            projects.mkdir()")]),
    ("deja .vscode/ vacía después del rollback",
     [("        rollback.new_dir(launch.parent)\n", "")]),
    ("no restaura launch.json", [("        rollback.file(launch)\n", "")]),
    ("dice «Se deshizo» aunque quedaron restos",
     [("                remove_tree(path)\n"
       "                if path.exists():\n"
       "                    leftovers.append(path)\n",
       "                remove_tree(path)\n")]),
    ("copia los cachés de las plantillas",
     [("        if IGNORED_IN_TEMPLATES.intersection(relative.parts):\n"
       "            continue\n", "")]),
    ("launch.json sin envFile", [('        "envFile": "${workspaceFolder}/.env",\n', "")]),
    ("pisa lo que no es de seedflow en launch.json",
     [('    data["configurations"] = configurations',
       '    data = {"version": "0.2.0", "configurations": configurations}')]),
    ("revienta con launch.json de otra forma",
     [("    if not all(isinstance(c, dict) for c in configurations):\n"
       "        return None\n", "")]),
    ("borrar un microservicio no lo quita de launch.json",
     [("    update_launch(root, args.project, name, args.service_type, add=False)",
       "    pass")]),
    ("la carpeta de servicios vacía no queda en git",
     [('        (services / ".gitkeep").touch()\n', "")]),
    ("restaura launch.json sin revisar si cambió y sin escritura atómica",
     [("            if current == content:\n"
       "                continue  # no cambió: reescribirlo solo agrega riesgo\n", ""),
      ("                    write_atomic(path, content)", "                    path.write_bytes(content)")]),
    ("una carpeta en lugar de launch.json rompe la creación",
     [("        if path.is_dir():\n            return\n        self._files", "        self._files")]),
    ("borrar sin launch.json lo crea",
     [("    if not add and not path.exists():\n        return  # no hay nada que quitar\n", "")]),
    ("dice que no borró aunque el borrado quedó a medias",
     [('f"⚠️  El borrado falló: {target} puede haber quedado incompleto."',
       '"↩️  No se borró el microservicio."')]),
    ("cdk init corre en iac/ (todos los stacks se llaman IacStack)",
     [("            staging,\n        )", "            iac,\n        )")]),
    ("deja la carpeta temporal de cdk init en el proyecto",
     [("        remove_tree(staging_parent)", "        pass")]),
    ("un emoji rompe la salida en consolas sin UTF-8",
     [('            reconfigure(errors="replace")', "            pass")]),
]


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


def main() -> int:
    """Corre cada mutante y reporta los que sobreviven."""
    original = (PLUGIN / "scripts" / "seedflow.py").read_text(encoding="utf-8")
    if not run_suite(PLUGIN / "scripts" / "seedflow.py"):
        print("La suite ya falla con el script original: arregla eso primero.")
        return 1

    sobrevivientes = []
    with tempfile.TemporaryDirectory() as temp:
        copy = Path(temp) / "scripts" / "seedflow.py"
        copy.parent.mkdir()
        (Path(temp) / "templates").symlink_to(PLUGIN / "templates")
        for description, replacements in MUTANTES:
            mutated = original
            missing = [old for old, _ in replacements if old not in mutated]
            if missing:
                print(f"⚠️  no encontré el texto para «{description}»")
                sobrevivientes.append(description)
                continue
            for old, new in replacements:
                mutated = mutated.replace(old, new, 1)
            copy.write_text(mutated, encoding="utf-8")
            if run_suite(copy):
                print(f"❌ sobrevive: {description}")
                sobrevivientes.append(description)
            else:
                print(f"✅ detectado: {description}")

    print(f"\n{len(MUTANTES) - len(sobrevivientes)}/{len(MUTANTES)} detectados")
    return 1 if sobrevivientes else 0


if __name__ == "__main__":
    sys.exit(main())
