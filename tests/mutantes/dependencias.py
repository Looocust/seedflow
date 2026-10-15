"""Fallas de las reglas de dependencias (checks/dependencias.py).

Las corre tests/mutantes.py: cada una se aplica sobre una copia de TARGET y
la suite tiene que ponerse en rojo.
"""

TARGET = "plugins/seedflow/scripts/checks/dependencias.py"

# (qué se rompe, [(texto original, texto roto), ...])
MUTANTES = [
    # D1: lib-python-* sin @<sha>
    ("D1: @main o un tag cuentan como SHA",
     [('SHA = re.compile(r"[0-9a-fA-F]{7,40}")',
       'SHA = re.compile(r"[0-9a-zA-Z.]+")')]),
    ("D1: una librería sin @ no cuenta",
     [("        if is_sha(ref):\n            continue\n        version",
       "        if is_sha(ref) or not ref:\n            continue\n        version")]),
    ("D1: no revisa python/requirements.txt",
     [("    yield from unpinned(root, project, python_reqs, python_lines)\n",
       "")]),
    ("D1: las líneas comentadas cuentan",
     [('LIBRARY.finditer(COMMENT.sub("", line))', "LIBRARY.finditer(line)")]),
    ("D1: con `nombre @ url` toma el nombre y no la URL",
     [("            last = matches[-1]", "            last = matches[0]")]),
    ("D1: descuenta como menor",
     [('            rule="D1",\n            points=SEVERITY["importante"],',
       '            rule="D1",\n            points=SEVERITY["menor"],')]),
    # D2: SHAs distintos entre layers/ y python/
    ("D2: no compara los SHAs",
     [("        if any(same_commit(sha, other) for other in others):",
       "        if True:")]),
    ("D2: un SHA abreviado del mismo commit cuenta como distinto",
     [("    return sha.startswith(other) or other.startswith(sha)",
       "    return sha == other")]),
    ("D2: compara también versiones que no son SHA (@main)",
     [("        if not is_sha(sha) or not others:",
       "        if not others:")]),
    ("D2: descuenta como importante",
     [('            rule="D2",\n            points=SEVERITY["menor"],',
       '            rule="D2",\n            points=SEVERITY["importante"],')]),
    # D3: import sin la librería en layers/
    ("D3: no marca los imports que faltan",
     [("            if repo not in present:", "            if False:")]),
    ("D3: busca la librería en python/requirements.txt y no en layers/",
     [("    present = {repo for _, _, repo, _ in lines}",
       "    present = {repo for _, _, repo, _ in read_requirements(\n"
       '        project.path, "python", "requirements.txt")}')]),
    ("D3: we_are_melonn.* se busca solo por el primer nombre",
     [('parts[:2] if parts[0] == "we_are_melonn" else parts[:1]',
       "parts[:1]")]),
    ("D3: solo mira los imports del nivel superior del archivo",
     [("    for node in ast.walk(tree):", "    for node in tree.body:")]),
    ("D3: cuenta los imports relativos",
     [("isinstance(node, ast.ImportFrom) and node.level == 0",
       "isinstance(node, ast.ImportFrom)")]),
    ("D3: `from we_are_melonn import x` no cuenta",
     [('            yield from (f"{base}.{alias.name}" for alias in node.names)\n',
       "")]),
    ("D3: un archivo que no parsea rompe la calificación",
     [("    except (OSError, SyntaxError, ValueError):",
       "    except (OSError, ValueError):")]),
    ("D3: descuenta como menor",
     [('            rule="D3",\n            points=SEVERITY["importante"],',
       '            rule="D3",\n            points=SEVERITY["menor"],')]),
    # Calificar no atraviesa enlaces
    ("lee requirements a través de enlaces",
     [("        if is_link(path):\n            return None",
       "        if False:\n            return None")]),
    ("lee una carpeta src/ enlazada",
     [("    if is_link(folder):\n        return []",
       "    if False:\n        return []")]),
    ("lee los .py de .venv y node_modules, y los enlazados",
     [('    return list(iter_files(folder, (".py",)))',
       '    return sorted(folder.rglob("*.py"))')]),
]
