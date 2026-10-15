"""Fallas del cálculo de la nota (checks/__init__.py).

Las corre tests/mutantes.py: cada una se aplica sobre una copia de TARGET y
la suite tiene que ponerse en rojo.
"""

TARGET = "plugins/seedflow/scripts/checks/__init__.py"
TESTS = ['test_check_puntaje']

# (qué se rompe, [(texto original, texto roto), ...])
MUTANTES = [
    ("la categoría baja de 0",
     [("    return max(0, 100 - sum(points))", "    return 100 - sum(points)")]),
    ("la categoría descuenta solo el hallazgo más grave",
     [("    return max(0, 100 - sum(points))",
       "    return max(0, 100 - max(points, default=0))")]),
    ("el redondeo usa round() (74.5 baja a 74)",
     [("    return (2 * sum(values) + len(values)) // (2 * len(values))",
       "    return round(sum(values) / len(values))")]),
    ("el redondeo trunca (92.5 queda en 92)",
     [("    return (2 * sum(values) + len(values)) // (2 * len(values))",
       "    return sum(values) // len(values)")]),
    ("75 no es verde", [("    if score >= 75:", "    if score > 75:")]),
    ("50 no es amarillo", [("    if score >= 50:", "    if score > 50:")]),
    ("verde y rojo intercambiados",
     [('        return "🟢"', '        return "🔴"'),
      ('        return "🟡"\n    return "🔴"', '        return "🟡"\n    return "🟢"')]),
    ("--quick corre los módulos no-quick",
     [("        if ctx.quick and not module.QUICK:", "        if False:")]),
    ("los módulos no-quick no corren nunca",
     [("        if ctx.quick and not module.QUICK:",
       "        if not module.QUICK:")]),
    ("una categoría no evaluada cuenta como 100",
     [("    evaluated = [s for s in categories.values() if s is not None]",
       "    evaluated = [100 if s is None else s for s in categories.values()]")]),
    ("una categoría sin módulo cuenta como evaluada",
     [("    skipped: dict[str, str] = {c: NO_RULES for c in CATEGORIES}",
       "    skipped: dict[str, str] = {}")]),
    ("ignora lo que el módulo no pudo evaluar en un proyecto",
     [("        reason = skipped.get(category) or per_project[category].get(name)",
       "        reason = skipped.get(category)")]),
    ("cuenta los hallazgos de otros proyectos",
     [("            if f.project == name and f.category == category",
       "            if f.category == category")]),
    ("el repo promedia también los proyectos sin nota como 0",
     [("    score = average([p.score for p in projects if p.score is not None])",
       "    score = average([p.score or 0 for p in projects])")]),
    ("acepta hallazgos de otra categoría",
     [("        if finding.category != module.CATEGORY:", "        if False:")]),
    ("los hallazgos salen en el orden en que llegan",
     [("        findings=sorted(findings, key=finding_order),",
       "        findings=findings,")]),
    ("el JSON no trae el semáforo",
     [('            "semaphore": self.semaphore,\n', "")]),
    ("iter_files entra a .venv y node_modules",
     [("if d not in IGNORED_DIRS)", "if True)")]),
    ("iter_files sigue enlaces a archivos",
     [("            if path.is_symlink():\n                continue\n", "")]),
    ("iter_files ignora el filtro de extensión",
     [("            if suffixes and not name.endswith(suffixes):\n                continue\n", "")]),
]
