"""Fallas de `seedflow.py fix` y de los avisos de 0 puntos en el reporte.

Las corre tests/mutantes.py: cada una se aplica sobre una copia de TARGET y
la suite tiene que ponerse en rojo.

Sin falla propia: `sys.modules.setdefault("seedflow", ...)` al correr como
script. Es una capa redundante con fix_errors (que atrapa el SeedError de la
copia que importó cada módulo), así que su falla sobreviviría.
"""

TARGET = "plugins/seedflow/scripts/seedflow.py"
TESTS = ['test_fix', 'test_check_puntaje', 'test_seedflow']

# (qué se rompe, [(texto original, texto roto), ...])
MUTANTES = [
    ("fix sin ids no dice que no hizo nada",
     [("    if not args.fix_ids and not args.list:", "    if False:")]),
    ("fix --list con ids no es un error",
     [("    if args.list and args.fix_ids:", "    if False:")]),
    ("aplica los ids repetidos más de una vez y en el orden pedido",
     [("    fix_ids = sorted(set(args.fix_ids))",
       "    fix_ids = list(args.fix_ids)")]),
    ("aplica en el orden pedido (C2 antes que C1)",
     [("    fix_ids = sorted(set(args.fix_ids))",
       "    fix_ids = list(dict.fromkeys(args.fix_ids))")]),
    ("aplica ids que check no ofrece",
     [("    if unknown:\n        raise SeedError(\n            f\"check no ofrece",
       "    if False:\n        raise SeedError(\n            f\"check no ofrece")]),
    ("valida solo el primer id antes de aplicar",
     [("    unknown = [fix_id for fix_id in fix_ids if fix_id not in offered]",
       "    unknown = [fix_id for fix_id in fix_ids[:1] if fix_id not in offered]")]),
    ("califica con todos los módulos aunque no ofrezcan esos arreglos",
     [("        if any(fix_prefix(i) in fixes_of(module) for i in fix_ids)",
       "        if True")]),
    ("ofrece fix_id sin arreglo en FIXES",
     [("        if finding.fix_id and fix_prefix(finding.fix_id) in fixes:",
       "        if finding.fix_id:")]),
    ("lista los arreglos sin calidad de código (modo rápido)",
     [("build_context(root, False), modules)",
       "build_context(root, True), modules)")]),
    ("lista los arreglos en el orden del reporte, no en el de aplicación",
     [("    return {fix_id: offered[fix_id] for fix_id in sorted(offered)}",
       "    return dict(offered)")]),
    ("sin arreglos no lo dice",
     [("    if not offered:\n        say(", "    if False:\n        say(")]),
    ("repite la descripción de un arreglo deduplicado",
     [("        for how in dict.fromkeys(finding.how for finding in findings):",
       "        for how in [finding.how for finding in findings]:")]),
    ("no muestra qué hace cada arreglo",
     [('            say(f"      {how}")', "            pass")]),
    ("no muestra los archivos que tocaría",
     [('        say(f"      Toca: {\', \'.join(shown)}")', "        pass")]),
    ("no distingue una carpeta en los archivos que tocaría",
     [('        shown = [f"{p}/" if (root / p).is_dir() else p for p in paths]',
       "        shown = paths")]),
    ("no imprime los archivos tocados",
     [('            say(f"   ✏️  {shown_path(root, path)}")', "            pass")]),
    ("imprime los archivos tocados con la ruta absoluta",
     [("        return Path(path).relative_to(root).as_posix()",
       "        return str(path)")]),
    ("no dice qué arreglos quedaron aplicados antes del error",
     [("                f\" Ya quedaron aplicados: {', '.join(fix_ids[:done])}.\"",
       '                ""')]),
    ("un ValueError de un arreglo sale con traceback",
     [("[SeedError, ValueError, OSError]", "[SeedError, OSError]")]),
    ("un OSError de un arreglo sale con traceback",
     [("[SeedError, ValueError, OSError]", "[SeedError, ValueError]")]),
    ("el SeedError de la otra copia de seedflow sale con traceback",
     [("            errors.append(other)", "            pass")]),
    ("fix escribe __pycache__ en el repo",
     [("    with without_bytecode():\n        fix_repo(args)",
       "    if True:\n        fix_repo(args)")]),
    ("muestra los avisos de 0 puntos como -0",
     [("    if not finding.points:\n        head =",
       "    if False:\n        head =")]),
]
