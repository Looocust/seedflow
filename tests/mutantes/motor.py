"""Fallas del motor: crear, eliminar, enlaces, rollback y launch.json.

Las corre tests/mutantes.py: cada una se aplica sobre una copia de TARGET y
la suite tiene que ponerse en rojo.
"""

TARGET = "plugins/seedflow/scripts/seedflow.py"

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
    # check: contexto, descubrimiento y salida
    ("check no ve lo que sigue git",
     [('    return {os.fsdecode(p) for p in result.stdout.split(b"\\0") if p}',
       "    return set()")]),
    ("check cree que hay git aunque no lo haya",
     [("    except (subprocess.SubprocessError, OSError):\n        return None\n"
       '    return {os.fsdecode(p)',
       "    except (subprocess.SubprocessError, OSError):\n        return set()\n"
       '    return {os.fsdecode(p)')]),
    ("check corre las ayudas privadas de checks/",
     [('        if info.name.startswith("_"):\n            continue\n', "")]),
    ("check acepta módulos de reglas que no cumplen el contrato",
     [("        validate_rule_module(module, package.CATEGORIES)\n", "")]),
    ("check atraviesa enlaces",
     [("        item for item in folder.iterdir() if item.is_dir() and not is_link(item)",
       "        item for item in folder.iterdir() if item.is_dir()")]),
    ("check pierde los microservicios de consumable-services",
     [("            for service_type in SERVICE_TYPES\n            if not is_link(python)",
       "            for service_type in SERVICE_TYPES[:1]\n            if not is_link(python)")]),
    ("check --quick no avisa que no incluye calidad de código",
     [('        f"{things_to_improve(report)} (sin calidad de código) "',
       '        f"{things_to_improve(report)} "')]),
    ("check sin proyectos no dice dónde buscó",
     [("            f\"{root.name}: no encontré proyectos en {root / 'projects'}, \"",
       "            f\"{root.name}: no encontré proyectos, \"")]),
    ("check --quick imprime el reporte completo",
     [("    elif args.quick:\n        say(quick_line(report))",
       "    elif False:\n        say(quick_line(report))")]),
    ("check deja __pycache__ en el repo si el plugin está dentro",
     [("    sys.dont_write_bytecode = True\n", "")]),
    ("check protege la carga de checks/ pero no lo que importan las reglas",
     [("    with without_bytecode():\n        check_repo(args)",
       "    with without_bytecode():\n        discover_rules()\n    check_repo(args)")]),
]
