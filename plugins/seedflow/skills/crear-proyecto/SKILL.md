---
name: crear-proyecto
argument-hint: "nombre del proyecto (opcional)"
description: Crea un proyecto nuevo con la estructura estándar de Melonn (deployment-scripts, iac con AWS CDK en TypeScript y python con internal-services o consumable-services), haciendo las mismas preguntas que el CLI melonn-python-cli. Úsala cuando el usuario diga "crea un proyecto", "nuevo proyecto", "arma la estructura del proyecto", "create-project", "arranquemos un proyecto en data-hub/ds-core", o pida la estructura base de un proyecto Melonn.
---

# Crear proyecto

Creas la estructura base de un proyecto Melonn. La estructura la crea **siempre**
el script del plugin, nunca a mano: así sale idéntica para todo el equipo. Tu
trabajo es hacer las preguntas, confirmar y, si el usuario quiere, seguir con el
primer microservicio.

Habla con el usuario en español.

## El script

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/seedflow.py" <comando> [opciones]
```

Si `python3` no existe (Windows), usa `py -3` o `python`. Córrelo **desde la
carpeta raíz del repo del usuario** (data-hub, ds-core…), que normalmente es la
carpeta de trabajo de la sesión. Lee
`${CLAUDE_PLUGIN_ROOT}/references/estructura.md` si necesitas explicar qué va en
cada carpeta.

## Paso 1 — Dónde estás parado

Corre `status --json` y revisa:

- **`root` y `git_repo`.** Dile al usuario en una línea dónde se va a crear
  (`<root>/projects/<nombre>`). Si `has_projects_folder` es `false`, o el repo
  no parece data-hub ni ds-core, pregúntale si de verdad es la carpeta raíz
  correcta antes de seguir (salvo que ya lo haya dicho en su mensaje). Es el
  error más común: crear el proyecto dentro de otro proyecto o en la carpeta de
  inicio. `git_repo` es solo el nombre de la carpeta del repo: un clon
  renombrado (`data-hub-2`) también vale.
- **`tools.cdk` y `tools.npm`.** Si falta alguno, explícale cómo instalarlo
  (Node.js y luego `npm install -g aws-cdk`) y ofrécele seguir con `--skip-cdk`,
  que deja `iac/` vacía para inicializarla después.
- **`projects`.** Si el nombre que trae `$ARGUMENTS` ya existe, díselo y pide
  otro.

## Paso 2 — Las preguntas

Son las mismas que hacía el CLI. Usa la herramienta `AskUserQuestion` cuando
esté disponible (una sola ronda con varias preguntas); si no, pregúntalas en
texto, todas juntas.

1. **Nombre del proyecto**, si no vino en `$ARGUMENTS`. Es texto libre, así que
   pídelo en el chat. Solo letras, números, `-` y `_`; el estilo de Melonn es
   kebab-case (`warehouses-operation`).
2. **Tipo de carpeta de servicios**: `internal-services` (por defecto) o
   `consumable-services`.
3. **¿Crear el primer microservicio ahora?** Sí / No.

No inventes preguntas extra en este paso. Si el usuario ya dio una respuesta en
su mensaje, no la vuelvas a preguntar.

## Paso 3 — Confirmar y crear

Muestra un resumen corto. Si el usuario ya confirmó en su mensaje, sigue sin
volver a preguntar; si no, pide confirmación:

```
Voy a crear: <root>/projects/<nombre>
  - python/<tipo>/
  - iac/ con AWS CDK (TypeScript)      ← o "vacía (--skip-cdk)"
  - deployment-scripts/
¿Sigo?
```

Con el sí, corre:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/seedflow.py" create-project <nombre> --service-type <tipo> [--skip-cdk]
```

`cdk init` y `npm install` tardan uno o dos minutos; avísale antes de correrlo.
Si el script falla, **él mismo deshace lo que creó**: no borres nada a mano.
Muestra el error tal cual y propón el arreglo. Si avisa que no pudo deshacer
todo, muéstrale la lista de rutas que quedaron. No reintentes creando carpetas
a mano.

## Paso 4 — Primer microservicio (si dijo que sí)

Sigue la skill `crear-microservicio` desde su paso 2 hasta su paso 5
(incluida la verificación), sabiendo ya el proyecto y el tipo de servicio. No
los vuelvas a preguntar. No uses su cierre: el cierre es uno solo, el del paso
5 de esta skill, e incluye lo del microservicio (TODOs, variables de entorno).

## Paso 5 — Cierre

Cuéntale qué quedó creado (sin listar archivo por archivo) y los siguientes pasos:

1. `cd projects/<nombre>/python`
2. Crear el entorno virtual e instalar dependencias. Las `lib-python-*` se
   instalan desde repos privados de `we-are-melonn`: hace falta acceso a la
   organización y git autenticado en GitHub (por ejemplo, con `gh auth login`).
   - Mac/Linux: `python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt`
   - Windows: `py -m venv .venv`, luego `.\.venv\Scripts\activate` y `pip install -r requirements.txt`
3. Copiar `.env.example` a `.env` y completar los valores.
4. Abrir la carpeta `python/` en VS Code, para que funcione el `launch.json`.

Cuéntale también que el stack de CDK lleva el nombre del proyecto: para
`stock-forecast` es `StockForecastStack`, en `iac/bin/stock-forecast.ts` e
`iac/lib/stock-forecast-stack.ts`.

No hagas commit: eso lo decide el usuario.
