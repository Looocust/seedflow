---
plan: calificacion-del-repo
titulo: Calificación de qué tan organizado está el repo
estado: aprobado         # borrador | aprobado
tracker: archivos        # archivos | linear
agentes_recomendados: 4
# comandos reales del proyecto (desde la raíz del repo seedflow)
cmd_test: PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests
cmd_mutantes: PYTHONDONTWRITEBYTECODE=1 python3 tests/mutantes.py
cmd_build: claude plugin validate .
cmd_lint: uvx ruff@0.9.6 check --config plugins/seedflow/templates/project/python/pyproject.toml plugins/seedflow/scripts && uvx ruff@0.9.6 format --check --config plugins/seedflow/templates/project/python/pyproject.toml plugins/seedflow/scripts && uvx --from mypy==1.15.0 mypy --config-file plugins/seedflow/templates/project/python/pyproject.toml plugins/seedflow/scripts
reviewer: codex exec --skip-git-repo-check --sandbox read-only -
webhook:
---

# Plan: Calificación de qué tan organizado está el repo

## Resumen

Se agrega a seedflow un comando `check` que califica el repo con reglas
deterministas, un comando `fix` que aplica los arreglos mecánicos, una skill
`revisar` que muestra el reporte con observaciones de Claude y ofrece arreglos,
y una línea de resumen al final de las otras tres skills. Para que varios
agentes trabajen en paralelo sin tocar los mismos archivos, las reglas no van
en `seedflow.py`: van en un paquete `scripts/checks/`, un módulo por categoría,
que el motor descubre solo.

## Decisiones de arquitectura

| Decisión | Alternativa descartada | Por qué |
|---|---|---|
| Paquete `scripts/checks/` con un módulo por categoría, descubierto con `pkgutil` | Todas las reglas en `seedflow.py` | Cuatro categorías en un archivo serializan el plan; además `seedflow.py` ya tiene 700 líneas |
| Cada módulo expone `CATEGORY`, `QUICK` y `run(ctx) -> CheckResult` | Registrar las reglas en una lista central | Una lista central es un archivo compartido por todas las tareas |
| La nota se calcula solo con hallazgos de reglas; las observaciones las agrega la skill y no se puntúan | Que Claude puntúe | El spec exige que la nota sea reproducible |
| `ruff` y `mypy` en un entorno propio (`~/.cache/seedflow/tools/…`, en Windows `%LOCALAPPDATA%\seedflow\tools\…`), con las versiones del `python/requirements.txt` del proyecto o, si no están, `ruff==0.9.6` y `mypy==1.15.0` | Usar los que tenga instalados el usuario | Versiones distintas dan notas distintas, y no se tocan los entornos del usuario |
| La variable `SEEDFLOW_TOOLS_DIR` reemplaza la carpeta del entorno de herramientas | Que los tests instalen desde PyPI | Los tests no pueden depender de internet |
| `mutantes.py` pasa a leer listas de fallas desde `tests/mutantes/*.py`, cada una con su archivo objetivo | Agregar todas las fallas a `mutantes.py` | `mutantes.py` sería un archivo compartido por cinco tareas |
| Los problemas no mecánicos (`.env` commiteado, `iac/.git`) se resuelven desde la skill con opciones y confirmación; el script no los arregla | Agregarlos a `fix` | El spec los deja como decisión del usuario, no como arreglo mecánico |

## Contratos compartidos

Los define **T-001** y los consumen todas las demás:

```python
# plugins/seedflow/scripts/checks/__init__.py
CATEGORIES = ("estructura", "calidad", "dependencias", "higiene")
SEVERITY = {"critico": 25, "importante": 10, "menor": 3}

@dataclass(frozen=True)
class Finding:
    category: str          # una de CATEGORIES
    rule: str              # id estable, p. ej. "E3"
    points: int            # lo que descuenta (positivo)
    project: str           # nombre del proyecto
    path: str              # relativo a la raíz del repo
    message: str           # qué pasa
    why: str               # por qué importa
    how: str               # cómo arreglarlo
    fix_id: str | None     # id para `seedflow.py fix`, si es mecánico

@dataclass
class CheckResult:
    findings: list[Finding]
    not_evaluated: dict[str, str]   # proyecto -> motivo (categoría no evaluada)

@dataclass
class Microservice:
    name: str
    service_type: str
    path: Path

@dataclass
class Project:
    name: str
    path: Path
    microservices: list[Microservice]

@dataclass
class Context:
    root: Path
    projects: list[Project]
    tracked: set[str] | None   # `git ls-files` relativo a la raíz; None si no es repo git
    quick: bool

# recorrido común (ajuste del orquestador durante la ola 2): toda regla que
# recorra archivos usa esto, que no entra a .venv, venv, node_modules, cdk.out,
# .git ni cachés, y no sigue enlaces
IGNORED_DIRS: frozenset[str]
def iter_files(folder: Path, suffixes: tuple[str, ...] = ()) -> Iterator[Path]: ...

# cada módulo de reglas, p. ej. checks/estructura.py:
CATEGORY = "estructura"
QUICK = True               # False solo en calidad
def run(ctx: Context) -> CheckResult: ...

# arreglos: cada módulo que ofrece arreglos expone
FIXES: dict[str, Callable[[Path, str], list[Path]]]   # prefijo de fix_id -> función(root, fix_id) que devuelve los archivos tocados
```

CLI (también lo define T-001; `fix` lo completa T-006):

```
seedflow.py check [--quick] [--json]
seedflow.py fix --list
seedflow.py fix FIX_ID [FIX_ID ...]
```

- `check --quick` imprime una línea:
  `data-hub: 78/100 🟡 · 5 cosas por mejorar (sin calidad de código) · detalle: /seedflow:revisar`
- `check --json` devuelve: `root`, `score`, `semaphore`, `projects`
  (cada uno con `name`, `score`, `categories`: `{categoria: puntaje o null}` y
  `not_evaluated`), y `findings` (lista de `Finding` como dict).
- La nota: categoría = `max(0, 100 - suma de points)`; proyecto = promedio
  de las categorías evaluadas; repo = promedio de los proyectos. Redondeo al
  entero más cercano, con `.5` hacia arriba. Semáforo: 🟢 ≥ 75, 🟡 50–74,
  🔴 < 50.
- `check` nunca escribe en el repo.

## Inventario de afirmaciones

| Afirmación que cambia | Dónde se afirma hoy | Tarea |
|---|---|---|
| El plugin tiene 3 skills / `Skills (3)` | `README.md` §3 Verificar y §9 Errores; `install.sh` (mensaje final) | T-008 |
| El script solo crea y borra (sin calificar) | `README.md` §1 y §6; docstring de `seedflow.py`; `plugin.json` y `marketplace.json` (descripción) | T-001 (docstring), T-008 (resto) |
| La lista de comandos del script es `status`, `create-*`, `delete-*` | `README.md` §6; `USO.md` | T-008 |
| La estructura del repo no tiene `checks/`, `skills/revisar/` ni `tests/mutantes/` | `README.md` §11 | T-008 |
| `mutantes.py` tiene una sola lista `MUTANTES` sobre `seedflow.py` | `README.md` §11 (Tests); `tests/mutantes.py` (docstring) | T-001 (mutantes.py), T-008 (README) |
| El cierre de `crear-proyecto`, `crear-microservicio` y `eliminar` no muestra nota | Las tres `SKILL.md` | T-007 |
| La calificación no existe / lo que queda fuera de alcance | `README.md` (no lo menciona) | T-008 |
| Requisitos: solo Python, Node/CDK, git | `README.md` §2 (falta: internet la primera vez para instalar `ruff`/`mypy`) | T-008 |

## Matriz de archivos

Rutas relativas a `plugins/seedflow/` cuando empiezan por `scripts/`,
`skills/`, `references/` o `USO.md`.

| Archivo | Tareas que lo tocan |
|---|---|
| `scripts/checks/__init__.py` | T-001 |
| `scripts/seedflow.py` | T-001, T-006 |
| `tests/test_check_puntaje.py` | T-001 |
| `tests/mutantes.py` | T-001 |
| `tests/mutantes/puntaje.py` | T-001 |
| `tests/mutantes/motor.py` | T-001 |
| `scripts/checks/estructura.py` | T-002 |
| `tests/test_check_estructura.py` | T-002 |
| `tests/mutantes/estructura.py` | T-002 |
| `scripts/checks/dependencias.py` | T-003 |
| `tests/test_check_dependencias.py` | T-003 |
| `tests/mutantes/dependencias.py` | T-003 |
| `scripts/checks/higiene.py` | T-004 |
| `tests/test_check_higiene.py` | T-004 |
| `tests/mutantes/higiene.py` | T-004 |
| `scripts/checks/calidad.py` | T-005 |
| `tests/test_check_calidad.py` | T-005 |
| `tests/mutantes/calidad.py` | T-005 |
| `tests/test_fix.py` | T-006 |
| `tests/mutantes/fix.py` | T-006 |
| `skills/revisar/SKILL.md` | T-007 |
| `skills/crear-proyecto/SKILL.md` | T-007 |
| `skills/crear-microservicio/SKILL.md` | T-007 |
| `skills/eliminar/SKILL.md` | T-007 |
| `README.md` (raíz) | T-008 |
| `USO.md` | T-008 |
| `.claude-plugin/plugin.json` | T-008 |
| `.claude-plugin/marketplace.json` (raíz) | T-008 |
| `install.sh` (raíz) | T-008 |

`seedflow.py` lo tocan T-001 (ola 1) y T-006 (ola 3): olas distintas, sin
conflicto. Los arreglos de cada categoría viven en su propio módulo (`FIXES`),
así que T-006 no toca los módulos de reglas.

## Mapa de olas

| Ola | Tareas | Agentes útiles |
|---|---|---|
| 1 | T-001 | 1 |
| 2 | T-002, T-003, T-004, T-005 | 4 |
| 3 | T-006 | 1 |
| 4 | T-007, T-008 | 2 |

**Agentes recomendados: 4** (ola 2).

Verificación a mano:

- [x] Todo `depende_de` apunta a una tarea que existe
- [x] Sin ciclos: T-001 → {T-002..T-005} → T-006 → {T-007, T-008}
- [x] Cada tarea está en una sola ola
- [x] Ninguna fila de la matriz tiene dos tareas de la misma ola

## Índice de tareas

| ID | Título | Tamaño | Depende de | Estado |
|---|---|---|---|---|
| T-001 | `check` calcula y muestra la nota (contrato, puntaje, CLI, mutantes por módulo) | M | — | pending |
| T-002 | Reglas de estructura, con sus arreglos | M | T-001 | pending |
| T-003 | Reglas de dependencias | S | T-001 | pending |
| T-004 | Reglas de seguridad e higiene, con su arreglo | M | T-001 | pending |
| T-005 | Calidad de código: entorno de herramientas, ruff, mypy y TODOs | M | T-001 | pending |
| T-006 | `fix` aplica los arreglos mecánicos | S | T-002, T-004, T-005 | pending |
| T-007 | Skill `revisar` y línea de resumen en las otras skills | M | T-006 | pending |
| T-008 | Documentación: README, USO, manifiestos, install.sh, versión 0.2.0 | M | T-002, T-003, T-004, T-005, T-006 | pending |

## Riesgos

| Riesgo | Impacto | Mitigación |
|---|---|---|
| La línea de resumen tarda más de 2 s en un repo grande | Medio | T-001 incluye un test de tiempo con 20 proyectos y 100 microservicios |
| Instalar `ruff`/`mypy` falla (sin internet, sin pip) | Medio | Calidad queda "no evaluada" con el motivo; test con instalación fallida |
| La regla de credenciales da falsos positivos | Medio | Patrones acotados, solo en `.py`; el reporte dice que puede ser un falso positivo |
| Regla de queries con `format()` sobre código arbitrario | Medio | Solo marca llamadas a `read`, `execute_query` o `write` cuyo primer argumento es una f-string o `.format(`; el resto lo observa Claude sin puntuar |
| Contrato de T-001 mal pensado obliga a rehacer la ola 2 | Alto | T-001 se revisa con codex antes de abrir la ola 2 |

## Puntos de parada obligatoria

- Cualquier arreglo que borre archivos o cambie el historial de git: no va en
  `fix`; se resuelve desde la skill con confirmación.
- Cambiar las reglas de `ruff`/`mypy` del equipo en las plantillas.
- Publicar en GitHub (push): lo decide el usuario.

## Preguntas abiertas

- Ninguna.
