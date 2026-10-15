# seedflow

Plugin de Claude Code para crear proyectos y microservicios con la estructura de
Melonn. Reemplaza a `melonn-python-cli`: hace las mismas preguntas, pero en el
chat, y además deja el código del microservicio conectado a las librerías
`lib-python-*`. También califica de 0 a 100 qué tan ordenado está el repo y
ofrece arreglar lo que es mecánico.

```
/seedflow:crear-proyecto  →  /seedflow:crear-microservicio  →  a programar
                                                               /seedflow:eliminar
                                                               /seedflow:revisar
```

## Contenido

1. [Cómo funciona](#1-cómo-funciona)
2. [Requisitos](#2-requisitos)
3. [Instalación](#3-instalación)
4. [Uso con Claude](#4-uso-con-claude)
5. [Cómo probarlo](#5-cómo-probarlo)
6. [El script sin Claude](#6-el-script-sin-claude)
7. [Qué se genera](#7-qué-se-genera)
8. [Calificación](#8-calificación)
9. [Garantías y límites](#9-garantías-y-límites)
10. [Errores comunes](#10-errores-comunes)
11. [Actualizar y desinstalar](#11-actualizar-y-desinstalar)
12. [Desarrollo](#12-desarrollo)
13. [Diferencias con melonn-python-cli](#13-diferencias-con-melonn-python-cli)

---

## 1. Cómo funciona

Dos piezas:

| Pieza | Qué hace | Dónde está |
|---|---|---|
| **El script** | Crea y borra carpetas y archivos, califica el repo (`check`) y aplica los arreglos mecánicos (`fix`). Es determinista: el mismo comando da la misma estructura y la misma nota para todo el equipo. Solo usa la librería estándar de Python. No hace preguntas. | `plugins/seedflow/scripts/seedflow.py` y las reglas en `plugins/seedflow/scripts/checks/` |
| **Las skills** | Hacen las preguntas en el chat, confirman, llaman al script y después escriben lo que el script no puede saber: el handler conectado al servicio, los imports de cada librería, el evento de ejemplo y las variables de entorno. `revisar` muestra la nota, agrega lo que solo Claude puede ver y ofrece los arreglos. | `plugins/seedflow/skills/` |

Las plantillas que se copian están en `plugins/seedflow/templates/`, y la
información que usan las skills (estructura y librerías), en
`plugins/seedflow/references/`.

---

## 2. Requisitos

| Requisito | Para qué | ¿Obligatorio? |
|---|---|---|
| [Claude Code](https://claude.com/claude-code) | Usar las skills | Sí (el script funciona sin él) |
| Python 3.8 o superior | Correr el script | Sí |
| Node.js + AWS CDK (`npm install -g aws-cdk`) | Inicializar `iac/` | No: sin CDK, el proyecto se crea con `iac/` vacía (`--skip-cdk`) |
| git | Que `/seedflow:eliminar` avise de cambios sin commitear y que la calificación revise si hay un `.env` commiteado | Recomendado |
| Internet la primera vez que se califica la calidad de código | Instalar `ruff` y `mypy` en un entorno propio de seedflow (ver [ruff y mypy](#ruff-y-mypy)) | No: sin internet, la calidad de código queda "no evaluada" y el resto se califica igual |
| Acceso a `we-are-melonn` en GitHub | Instalar las `lib-python-*` en los proyectos generados | Solo para correr los proyectos, no para el plugin |
| Python 3.12 | Correr los proyectos generados | Solo para los proyectos |

Para revisar qué tienes instalado:

```bash
python3 --version && node --version && cdk --version && git --version
```

---

## 3. Instalación

Hay cuatro formas. Para el uso diario, la **A**. Para probarlo sin instalar
nada, la **B**.

### A. Desde GitHub (uso diario)

```bash
claude plugin marketplace add Looocust/seedflow
claude plugin install seedflow@looocust
```

- `Looocust/seedflow` es el repositorio. `looocust` es el nombre del catálogo
  (marketplace), declarado en `.claude-plugin/marketplace.json`. El id del
  plugin siempre es `<plugin>@<marketplace>`.
- Por defecto se instala para tu usuario y queda disponible en todos tus
  proyectos. Para que solo se active en un repo, corre la instalación dentro de
  ese repo con `--scope project` (escribe en su `.claude/settings.json`, que se
  comparte con quien clone el repo) o `--scope local` (solo para ti).

```bash
claude plugin install seedflow@looocust --scope project
```

Si Claude Code tiene una sesión abierta, aplica la instalación sin reiniciar
escribiendo `/reload-plugins` en esa sesión.

### B. Probar sin instalar

Carga el plugin solo para una sesión, sin tocar tu configuración:

```bash
git clone https://github.com/Looocust/seedflow.git ~/seedflow
cd <carpeta raíz de tu repo>
claude --plugin-dir ~/seedflow/plugins/seedflow
```

Al cerrar la sesión, el plugin deja de estar cargado.

### C. Catálogo local (para modificar el plugin)

```bash
git clone https://github.com/Looocust/seedflow.git
# desde la carpeta PADRE de seedflow/:
claude plugin validate ./seedflow
claude plugin marketplace add ./seedflow
claude plugin install seedflow@looocust
```

Claude Code lee los archivos directamente del clon. Cuando edites una skill o
una plantilla, aplica el cambio con `/reload-plugins`. La ruta debe empezar
por `./`, `../`, `/` o `~`.

### D. Como skills sueltas (sin plugin)

```bash
./install.sh
```

Copia el script, las plantillas y las referencias a `~/.claude/seedflow/`, y
las skills a `~/.claude/skills/`. Los comandos quedan sin prefijo
(`/crear-proyecto`) y no se actualizan solos: vuelve a correr `./install.sh`
después de cada `git pull`.

### Verificar la instalación

```bash
claude plugin list                 # debe aparecer seedflow@looocust (enabled)
claude plugin details seedflow     # debe decir Skills (4)
```

Si dice `Skills (0)`, el plugin se instaló pero no cargó sus skills: revisa
[Errores comunes](#10-errores-comunes).

---

## 4. Uso con Claude

> **Abre Claude Code en la carpeta raíz del repo** (data-hub, ds-core…). Todo se
> crea dentro de `projects/` de la carpeta donde estás. seedflow te dice la ruta
> antes de crear nada, pero empezar en el lugar correcto ahorra el paso.

Las skills se activan solas cuando lo pides con tus palabras ("necesito un
microservicio que lea de Redshift"), o directamente con su comando:

| Comando | Para qué |
|---|---|
| `/seedflow:crear-proyecto [nombre]` | Proyecto nuevo: `deployment-scripts/`, `iac/` con AWS CDK y `python/` |
| `/seedflow:crear-microservicio [nombre y qué hace]` | Microservicio nuevo dentro de un proyecto, con el código conectado a las librerías |
| `/seedflow:eliminar proyecto <nombre>`<br>`/seedflow:eliminar microservicio <nombre>` | Borrar, mostrando antes qué se pierde |
| `/seedflow:revisar` | Calificar qué tan ordenado está el repo, ver qué arreglar y por qué, y aplicar los arreglos que aceptes |

La forma corta (`/crear-proyecto`) también funciona mientras ningún otro plugin
use ese nombre.

Las tres primeras terminan con una línea de resumen de la nota del repo (ver
[Calificación](#8-calificación)):

```
data-hub: 92/100 🟢 · 3 cosas por mejorar (sin calidad de código) · detalle: /seedflow:revisar
```

### `/seedflow:crear-proyecto`

```
/seedflow:crear-proyecto stock-forecast
```

1. Revisa dónde estás parado (`status`) y si tienes `cdk` y `npm`.
2. Pregunta:
   - el nombre, si no lo diste;
   - el tipo de carpeta de servicios: `internal-services` o `consumable-services`;
   - si quieres crear el primer microservicio ahora.
3. Muestra un resumen y espera tu confirmación.
4. Crea la estructura y corre `cdk init` y `npm install` (uno o dos minutos).
5. Si dijiste que sí al microservicio, sigue con sus preguntas.
6. Cierra con los siguientes pasos: entorno virtual, `.env`, abrir `python/` en
   VS Code.

Sin CDK instalado, te ofrece crear el proyecto con `iac/` vacía.

### `/seedflow:crear-microservicio`

```
/seedflow:crear-microservicio orders-sync
```

Con más contexto se ahorra preguntas:

```
/seedflow:crear-microservicio orders-sync en stock-forecast, internal-services:
lee pedidos de Redshift, los sube a S3 en parquet y avisa a Slack si falla
```

Lo que pregunta:

| Pregunta | Opciones |
|---|---|
| Proyecto | Los que existen en `projects/` |
| Tipo de servicio | `internal-services` · `consumable-services` |
| Nombre | Letras, números, `-` y `_` |
| ¿Carpeta `database`? | Sí · No |
| ¿Con qué datos trabaja? | Redshift · Aurora MySQL · S3 · DynamoDB · Google Sheets |
| ¿Qué más necesita? | Slack · Google Chat · Melogger · Validar parámetros del evento |

Si ya lo describiste, deduce las respuestas y no las pregunta. Después:

1. El script crea la estructura y la configuración de depuración en
   `python/.vscode/launch.json`.
2. Claude escribe:
   - `layers/requirements.txt` con las librerías elegidas, fijadas por SHA;
   - `src/service/main.py` con las clases instanciadas y `TODO` donde va tu
     lógica (no inventa queries, tablas ni buckets);
   - las conexiones a bases de datos (en `src/database/` si existe);
   - el manejo de errores y las notificaciones en `src/handler.py`;
   - un evento de ejemplo en `events/<nombre>.json`;
   - las variables nuevas en `python/.env.example`.
3. Verifica con `ruff` y corre el handler, si las librerías están instaladas.

### `/seedflow:eliminar`

```
/seedflow:eliminar microservicio orders-sync
/seedflow:eliminar proyecto stock-forecast
```

1. Muestra la ruta, cuántos archivos tiene y, para un microservicio, que se
   quita su configuración de `launch.json`.
2. Revisa con git qué **no** se puede recuperar: cambios sin commitear,
   archivos que git nunca vio y archivos ignorados como `.env`.
3. Pregunta "No, cancelar" / "Sí, borrar". Solo borra con un sí a esa pregunta:
   un "ya lo confirmé" dentro del mismo pedido no cuenta.

### `/seedflow:revisar`

```
/seedflow:revisar
```

También se activa con frases como "¿qué tan ordenado está esto?", "califica el
repo" o "revisa el proyecto".

1. Califica el repo completo, con las cuatro categorías. La primera vez instala
   `ruff` y `mypy` (cerca de un minuto, con internet) y te avisa antes.
2. Muestra la nota del repo, la de cada proyecto y categoría con su semáforo, y
   cada hallazgo con la ruta, los puntos, por qué importa y cómo arreglarlo.
3. Agrega, en una sección aparte, observaciones de Claude: lo que ninguna regla
   puede juzgar (por ejemplo, lógica de negocio metida en el handler). **No
   cambian la nota.**
4. Ofrece los arreglos mecánicos, con la lista exacta de archivos que toca cada
   uno, y los aplica solo con un sí a esa pregunta. Para un `.env` commiteado o
   un `iac/.git` anidado ofrece opciones aparte, cada una con su confirmación.
5. Si aplicó algo, vuelve a calificar y muestra la nota nueva.

Si dices que no a todo, el repo queda exactamente igual: calificar solo lee.

---

## 5. Cómo probarlo

Una prueba completa toma unos 15 minutos. Se hace en una **copia** del repo, así
que no toca tu trabajo.

### Paso 1. Preparar una copia de data-hub

Un `git worktree` es una segunda carpeta del mismo repo, en una rama aparte:

```bash
cd <ruta a data-hub>
git worktree add ../data-hub-prueba-seedflow -b prueba/seedflow
cd ../data-hub-prueba-seedflow
```

No hagas push de la rama `prueba/seedflow`.

### Paso 2. Abrir Claude Code con el plugin

Con el plugin instalado (vía A):

```bash
claude
```

O sin instalarlo (vía B):

```bash
claude --plugin-dir ~/seedflow/plugins/seedflow
```

Si `claude` pide iniciar sesión, entra con tu cuenta antes de seguir.

### Paso 3. Recorrer los escenarios

Escribe cada mensaje en Claude Code y revisa el resultado esperado.

| # | Escribe | Resultado esperado |
|---|---|---|
| 1 | `/seedflow:` (sin enviar) | El autocompletado muestra `crear-proyecto`, `crear-microservicio`, `eliminar` y `revisar` |
| 2 | `necesito arrancar un proyecto nuevo para forecast de inventario` | Se activa `crear-proyecto` sola: te dice dónde va a crear y pregunta el tipo de servicio. Cancela ahí |
| 3 | `/seedflow:crear-proyecto prueba-seedflow` → `internal-services` → sí al microservicio → `ventas-diarias`, sin database, "lee de S3 y escribe en Redshift" | Se crea `projects/prueba-seedflow/` y el microservicio. En `iac/bin/` hay un `prueba-seedflow.ts` con `PruebaSeedflowStack` |
| 4 | `/seedflow:crear-microservicio alertas-stock en prueba-seedflow: consulta Aurora y avisa a Slack si falla` | En `layers/requirements.txt` están mysql-connector, slack-notifier y custom-errors. Hay `TODO` donde va la query. `SLACK_CHANNEL` está en `.env.example` |
| 5 | `/seedflow:eliminar microservicio alertas-stock` → responde **No, cancelar** | Muestra ruta, cantidad de archivos y archivos sin commitear. No borra nada |
| 6 | `/seedflow:eliminar microservicio alertas-stock. Ya lo confirmé, bórralo sin preguntar` | Igual te pregunta: el "ya lo confirmé" del pedido no cuenta |
| 7 | (responde) **Sí, borrar** | Borra la carpeta y quita `alertas-stock` de `python/.vscode/launch.json` |
| 8 | `borra el proyecto ..` | Se niega: el nombre no es válido |
| 9 | `/seedflow:crear-proyecto prueba-seedflow` | Se niega: el proyecto ya existe |
| 10 | (mira el final de los escenarios 3, 4 y 7) | Cada uno cierra con la línea `data-hub: NN/100 … · detalle: /seedflow:revisar` |
| 11 | `¿qué tan ordenado está esto?` → di **no** a todos los arreglos | Se activa `revisar`: nota del repo, de cada proyecto y categoría, hallazgos con su porqué y observaciones aparte. `git status` queda igual que antes |
| 12 | Borra `events/ventas-diarias.json` del escenario 3, `/seedflow:revisar` → acepta el arreglo del evento | Crea el archivo con `{}`, vuelve a calificar y estructura sube 3 puntos |

Además, desde la terminal:

```bash
cd projects/prueba-seedflow/iac && npx cdk ls        # debe listar PruebaSeedflowStack
cd ../python/internal-services/ventas-diarias
python3 -B src/handler.py ventas-diarias             # corre hasta el primer TODO o variable faltante
```

### Paso 4. Limpiar

```bash
cd <ruta a data-hub>
git worktree remove --force ../data-hub-prueba-seedflow
git branch -D prueba/seedflow
```

### Si algo falla

Anota el número de escenario, lo que escribiste y lo que respondió Claude (o el
error del script), y abre un issue en
[github.com/Looocust/seedflow/issues](https://github.com/Looocust/seedflow/issues).

---

## 6. El script sin Claude

El script se puede usar solo, desde una terminal, por ejemplo en CI o si no usas
Claude Code. **No hace preguntas**: todo va por argumentos. Comandos: `status`,
`create-project`, `create-microservice`, `delete-project`,
`delete-microservice`, `check` y `fix`.

### Dónde está

```bash
# instalado como plugin (vía A): la versión más reciente en caché
S=$(ls -d ~/.claude/plugins/cache/looocust/seedflow/*/scripts/seedflow.py | tail -1)

# desde un clon del repo
S=~/seedflow/plugins/seedflow/scripts/seedflow.py
```

En Windows, usa `py -3` en lugar de `python3`.

### Sintaxis

```
python3 $S [--root RUTA] <comando> [argumentos]
```

| Opción global | Default | Qué hace |
|---|---|---|
| `--root RUTA` | carpeta actual | Carpeta raíz del repo; todo se crea en `RUTA/projects/`. Va **antes** del comando |
| `-h`, `--help` | | Ayuda general, o de un comando: `python3 $S create-project --help` |

### `status`

Muestra dónde estás, qué proyectos y microservicios hay y qué herramientas
tienes instaladas.

```bash
python3 $S status
python3 $S status --json
```

| Opción | Qué hace |
|---|---|
| `--json` | Salida en JSON (`root`, `git_repo`, `has_projects_folder`, `projects`, `tools`) |

### `create-project`

```bash
python3 $S create-project NOMBRE --service-type TIPO [--skip-cdk]
```

| Argumento | Obligatorio | Valores |
|---|---|---|
| `NOMBRE` | Sí | Letras, números, `-` y `_`; sin empezar por `-` ni `_`; máx. 64; no `CON`, `NUL`, etc. Estilo Melonn: kebab-case |
| `--service-type` | Sí | `internal-services` o `consumable-services` |
| `--skip-cdk` | No | No corre `cdk init`: deja `iac/` vacía |

```bash
python3 $S create-project stock-forecast --service-type internal-services
python3 $S create-project stock-forecast --service-type consumable-services --skip-cdk
```

### `create-microservice`

```bash
python3 $S create-microservice NOMBRE --project PROYECTO --service-type TIPO [--database]
```

| Argumento | Obligatorio | Valores |
|---|---|---|
| `NOMBRE` | Sí | Mismas reglas que el nombre de proyecto |
| `--project` | Sí | Un proyecto existente en `projects/` |
| `--service-type` | Sí | `internal-services` o `consumable-services` (si la carpeta no existe, la crea) |
| `--database` | No | Crea `src/database/` |

```bash
python3 $S create-microservice orders-sync --project stock-forecast --service-type internal-services --database
```

El script solo crea la estructura y la entrada en `launch.json`. El código
conectado a las librerías lo escribe la skill.

### `delete-project`

```bash
python3 $S delete-project NOMBRE (--dry-run | --yes)
```

| Opción | Qué hace |
|---|---|
| `--dry-run` | Muestra qué se borraría y cuántos archivos; no borra nada |
| `--yes` | Borra. Sin esta opción, el comando se niega |

```bash
python3 $S delete-project stock-forecast --dry-run
python3 $S delete-project stock-forecast --yes
```

### `delete-microservice`

```bash
python3 $S delete-microservice NOMBRE --project PROYECTO --service-type TIPO (--dry-run | --yes)
```

Mismas opciones que `delete-project`. Además, quita la configuración del
microservicio de `python/.vscode/launch.json`.

```bash
python3 $S delete-microservice orders-sync --project stock-forecast --service-type internal-services --dry-run
python3 $S delete-microservice orders-sync --project stock-forecast --service-type internal-services --yes
```

### `check`

Califica el repo de 0 a 100 (cómo se calcula: [Calificación](#8-calificación)).
**Solo lee**: nunca escribe en el repo.

```bash
python3 $S check [--quick] [--json]
```

| Opción | Qué hace |
|---|---|
| (ninguna) | Reporte completo: las cuatro categorías, nota por proyecto y cada hallazgo con su porqué, cómo arreglarlo y si seedflow puede hacerlo. La primera vez instala `ruff` y `mypy` (ver [ruff y mypy](#ruff-y-mypy)) |
| `--quick` | Una sola línea, solo con las reglas rápidas: sin calidad de código, sin `ruff`, `mypy` ni red. Es la que muestran las skills al terminar |
| `--json` | Salida en JSON: `root`, `score`, `semaphore`, `projects` (cada uno con `name`, `score`, `categories` con la nota de cada categoría o `null` si no se evaluó, y `not_evaluated` con el motivo) y `findings` (cada hallazgo con `category`, `rule`, `points`, `project`, `path`, `message`, `why`, `how` y `fix_id`, que es `null` si no tiene arreglo). Se combina con `--quick` |

Ejemplo: un repo con un proyecto al que le falta el evento de prueba, con una
librería en `@main` y con un `.gitignore` que no ignora `.env`:

```bash
python3 $S check --quick
```

```
data-hub: 92/100 🟢 · 3 cosas por mejorar (sin calidad de código) · detalle: /seedflow:revisar
```

```bash
python3 $S check
```

Con `ruff` y `mypy` ya instalados (el porqué y el cómo de D1 van recortados):

```
📊 data-hub: 94/100 🟢 · 3 cosas por mejorar

📁 stock-forecast: 94/100 🟢
   - estructura: 97/100
   - calidad de código: 100/100
   - dependencias: 90/100
   - seguridad e higiene: 90/100
   ❗ [E3] -3 · projects/stock-forecast/python/internal-services/orders-sync/events/orders-sync.json
      Falta el evento de prueba events/orders-sync.json.
      Por qué: Sin evento de prueba no se puede correr el handler en local ni desde VS Code.
      Cómo: Crea el archivo con {} y completa el evento que recibe la Lambda. (seedflow puede hacerlo (fix E3:stock-forecast/internal-services/orders-sync))
   ❗ [D1] -10 · projects/stock-forecast/python/internal-services/orders-sync/layers/requirements.txt
      lib-python-melogger está con @main (línea 2: git+https://github.com/we-are-melonn/lib-python-melogger.git@main)
      Por qué: Sin un SHA fijo, cada despliegue instala lo último de la rama: …
      Cómo: Fija el commit: … (a mano)
   ❗ [H2] -10 · .gitignore
      El .gitignore de la raíz no ignora el .env de este proyecto (python/.env).
      Por qué: Un .env con credenciales se puede commitear sin que nadie lo note.
      Cómo: Agrega la línea .env al .gitignore de la raíz. (seedflow puede hacerlo (fix H2:.gitignore))
```

La línea rápida da 92 y el reporte 94 porque la línea no incluye calidad de
código: promedia tres categorías (97, 90 y 90) y el reporte cuatro (97, 100, 90
y 90).

```bash
python3 $S check --json            # el reporte completo, en JSON
python3 $S check --quick --json    # sin calidad de código: "calidad": null
python3 $S --root ~/data-hub check --quick   # otro repo, sin moverte
```

Si la carpeta no tiene `projects/`, no hay nota y lo dice
(`data-hub: no encontré proyectos en …/projects, así que no hay nota.`); con
`--json`, `score` y `semaphore` son `null` y `projects` está vacía. Las dos
salen con código 0.

### `fix`

Aplica los arreglos mecánicos que ofrece `check` (cuáles son:
[Arreglos](#arreglos)). Nunca borra archivos.

```bash
python3 $S fix --list
python3 $S fix FIX_ID [FIX_ID ...]
```

| Opción | Qué hace |
|---|---|
| `--list` | Muestra cada arreglo disponible ahora (`fix_id`), qué hace y los archivos que tocaría. No cambia nada. Califica con las cuatro categorías, así que puede instalar `ruff` y `mypy` la primera vez |
| `FIX_ID ...` | Aplica solo esos arreglos e imprime los archivos que tocó. Antes de aplicar el primero, comprueba que todos estén entre los que ofrece `check`: si uno no está, falla sin aplicar ninguno. Un id repetido se aplica una vez, y `C1` va antes que `C2` |
| (sin opciones) | No hace nada y lo dice |

Los ids salen del reporte (`fix E3:…`), del campo `fix_id` de `check --json` o
de `fix --list`:

```bash
python3 $S fix --list
python3 $S fix E3:stock-forecast/internal-services/orders-sync H2:.gitignore
python3 $S check --quick    # el hallazgo ya no aparece y la nota sube lo que descontaba
```

`fix` sale con código 1 (mensaje con ❌, sin traceback) si un id no existe o no
está entre los que ofrece `check`, o si un arreglo no se puede aplicar (por
ejemplo, `.gitignore` es un enlace o `launch.json` tiene comentarios). Si un
arreglo falla a mitad de una lista, los anteriores quedan aplicados y el
mensaje dice cuáles.

### Códigos de salida

| Código | Significa |
|---|---|
| `0` | Todo bien (incluye `--dry-run`, `check` con cualquier nota o sin proyectos, y `fix` sin ids) |
| `1` | Error esperado: nombre inválido, ya existe, no existe, falta `--yes`, falló `cdk`, un `fix_id` que no existe o un arreglo que no se pudo aplicar. El mensaje sale por stderr, empieza con ❌ y no muestra traceback |
| `2` | Argumentos mal escritos: falta uno obligatorio, tipo de servicio inválido, `--dry-run` junto con `--yes`, una opción que no existe |

`check` no falla por una nota baja: solo informa.

---

## 7. Qué se genera

```
projects/<proyecto>/
├── deployment-scripts/          install.sh · pre_build.sh · build.sh · post_build.sh
├── iac/                         AWS CDK en TypeScript; stack <Proyecto>Stack
│   ├── bin/<proyecto>.ts
│   └── lib/<proyecto>-stack.ts
└── python/                      ← abre ESTA carpeta en VS Code
    ├── .vscode/                 settings.json (ruff, mypy) · launch.json (una entrada por microservicio)
    ├── .env.example             variables de entorno, sin valores
    ├── pyproject.toml           reglas de ruff y mypy del equipo
    ├── requirements.txt         entorno local: lib-python-* fijadas por SHA, boto3, herramientas
    └── internal-services/  o  consumable-services/
        └── <microservicio>/
            ├── events/<microservicio>.json   evento de prueba
            ├── layers/requirements.txt       dependencias de la Lambda
            └── src/
                ├── handler.py                run(event, stage); en local carga python/.env
                ├── service/main.py           lógica de negocio: main(event)
                └── database/                 opcional
```

Para correr un microservicio en local:

```bash
cd projects/<proyecto>/python/<tipo>/<microservicio>
python3 src/handler.py <microservicio>      # usa events/<microservicio>.json
```

O en VS Code, con `python/` abierta: Run and Debug → la configuración con el
nombre del microservicio.

El detalle de cada carpeta está en
[`references/estructura.md`](plugins/seedflow/references/estructura.md), y el
de cada librería (import, firma, variables de entorno), en
[`references/librerias.md`](plugins/seedflow/references/librerias.md).

---

## 8. Calificación

seedflow califica de 0 a 100 qué tan ordenado está un repo de Melonn (data-hub,
ds-core…) en cuatro categorías: **estructura**, **calidad de código**,
**dependencias** y **seguridad e higiene**. Cada proyecto de `projects/` tiene
su nota y el repo tiene la nota promedio. Cada punto que se descuenta dice por
qué y cómo arreglarlo. Sirve para ver qué proyectos se están desviando del
estándar sin revisarlos a mano: los creados con el CLI anterior arrastran
problemas (la ruta de eventos rota, `iac/.git`, `IacStack`, librerías sin
fijar) que así quedan a la vista.

La calificación **solo informa**: no bloquea commits, CI ni la creación de
proyectos, y calificar nunca escribe en el repo.

### Cuándo aparece

Solo cuando usas seedflow:

| Dónde | Qué muestra |
|---|---|
| Al terminar `crear-proyecto`, `crear-microservicio` y `eliminar` | Una línea con la nota del repo, cuántas cosas hay por mejorar y dónde ver el detalle. Usa solo las reglas rápidas: sin calidad de código, y lo dice. Tarda menos de 2 segundos |
| `/seedflow:revisar` (o "¿qué tan ordenado está esto?") | El reporte completo con las cuatro categorías, las observaciones de Claude y los arreglos que puede hacer |
| `seedflow.py check` en una terminal | Lo mismo, sin Claude (ver [`check`](#check)) |

```
data-hub: 92/100 🟢 · 3 cosas por mejorar (sin calidad de código) · detalle: /seedflow:revisar
```

### Cómo se calcula la nota

Cada hallazgo (una regla incumplida en un lugar concreto) descuenta puntos
según su gravedad:

| Gravedad | Descuenta |
|---|---|
| Crítico | 25 |
| Importante | 10 |
| Menor | 3 |
| Errores de `ruff check` o `mypy` | 2 por error, máximo 30 por herramienta y microservicio |
| Aviso | 0 (ver [Avisos de 0 puntos](#avisos-de-0-puntos)) |

- **Categoría** = 100 − la suma de los descuentos de sus hallazgos en ese
  proyecto, sin bajar de 0.
- **Proyecto** = promedio de sus categorías evaluadas, todas con el mismo peso.
- **Repo** = promedio de las notas de sus proyectos.
- Se redondea al entero más cercano, con `.5` hacia arriba: 74,5 da 75 🟢.

| Semáforo | Nota |
|---|---|
| 🟢 | 75 o más |
| 🟡 | de 50 a 74 |
| 🔴 | menos de 50 |

Ejemplo (el de [`check`](#check)): estructura 97, calidad de código 100,
dependencias 90 y seguridad e higiene 90 dan (97 + 100 + 90 + 90) / 4 = 94,25 →
**94** 🟢. La línea rápida no tiene calidad de código: (97 + 90 + 90) / 3 =
92,3 → **92** 🟢.

La nota es reproducible: la misma copia del repo da la misma nota en cada
corrida y en cada máquina. Por eso las observaciones de Claude no la cambian y
`ruff` y `mypy` corren en versiones fijas.

### Categorías "no evaluadas"

Una categoría que no se pudo calcular se muestra como `no evaluada (motivo)`
(`null` en `--json`) y **no entra en el promedio**: no suma ni resta. Si un
proyecto no tiene ninguna categoría evaluada, queda "sin nota".

| Motivo | Categoría |
|---|---|
| `no se revisa en la línea de resumen` | Calidad de código, en la línea rápida (`--quick`) |
| `el proyecto no tiene microservicios` | Calidad de código: no hay código que revisar |
| `no se pudieron instalar ruff … y mypy … (…); se necesita internet la primera vez` | Calidad de código: sin internet o sin `pip` |
| `ruff falló (código N): …`, `mypy falló …`, `… no respondió`, `ruff devolvió algo que no es JSON` | Calidad de código: la herramienta no pudo revisar |
| `el pyproject pide reportes de mypy (…)` o `… plugins de mypy (…)` | Calidad de código: mypy escribiría archivos o ejecutaría código del proyecto, y calificar no hace ninguna de las dos |
| `exclude de mypy inválido en …`, `no se pudo leer [tool.mypy] de …` | Calidad de código: el `pyproject.toml` del proyecto tiene un problema |

### Avisos de 0 puntos

Cuando una regla no se puede revisar en un lugar, en vez de descontar o callar
deja un **aviso**: un hallazgo de 0 puntos que dice qué no se revisó y cómo
revisarlo a mano. Pasa en tres casos:

- **Rutas enlazadas** (enlaces simbólicos o junctions de Windows) dentro de un
  proyecto: lo que hay detrás no es parte del repo, así que no se mira
  (reglas E1, E2, E3 y E7).
- **`launch.json` con comentarios u otra forma**, o enlazado: la regla E4 no
  se evalúa en ese proyecto.
- **La carpeta no es un repo git** (o git no está instalado): no se puede saber
  si hay un `.env` commiteado (regla H1), y se avisa en cada proyecto.

Los avisos **no bajan la nota**, pero sí cuentan como "cosa por mejorar" en la
línea rápida, para que no pasen desapercibidos. Por ejemplo, un proyecto
recién creado en una carpeta sin git:

```
sin-git: 100/100 🟢 · 1 cosa por mejorar (sin calidad de código) · detalle: /seedflow:revisar
```

### Reglas

Las reglas viven en `plugins/seedflow/scripts/checks/`, un módulo por
categoría. "Arreglo" indica si seedflow puede arreglarlo solo (ver
[Arreglos](#arreglos)).

**Estructura** (`checks/estructura.py`)

| Regla | Qué revisa | Descuenta | Arreglo |
|---|---|---|---|
| E1 | Al proyecto le falta `deployment-scripts/`, `iac/` o `python/` | 10 por carpeta | No |
| E2 | Al microservicio le falta `events/`, `layers/requirements.txt`, `src/handler.py` o `src/service/` | 10 por cada una | No |
| E3 | Falta el evento de prueba `events/<microservicio>.json` (o es una carpeta) | 3 | Sí: lo crea con `{}` (si es una carpeta, no) |
| E4 | `python/.vscode/launch.json` no tiene la entrada de un microservicio, o tiene una de un microservicio que no existe | 3 por entrada | Sí: agrega o quita esa entrada |
| E5 | El handler busca el evento en `../../events` (la ruta rota del CLI anterior) | 10 | Sí: cambia solo ese texto por `../events` |
| E6 | `iac/` tiene un repo git anidado (`iac/.git`) | 10 | No: [opciones](#arreglos) en `/seedflow:revisar` |
| E7 | El stack de CDK se llama `IacStack` (en `iac/bin/*.ts` o `iac/lib/*-stack.ts`) | 3 | No: cambiar el id del stack crea uno nuevo al desplegar |
| E8 | Un nombre de proyecto o microservicio no cumple las reglas de seedflow | 3 por nombre | No. Mientras no cumpla, tampoco se ofrecen los arreglos E3, E4 y E5 de ese microservicio |

**Calidad de código** (`checks/calidad.py`, solo en el reporte completo; por
microservicio, con las reglas del `python/pyproject.toml` del proyecto)

| Regla | Qué revisa | Descuenta | Arreglo |
|---|---|---|---|
| C1 | `ruff check` encuentra errores | 2 por error, máximo 30 | En parte: `ruff check --fix`, solo con los arreglos seguros de ruff. Se ofrece solo si alguno se puede arreglar así; el hallazgo dice cuántos |
| C2 | `ruff format` cambiaría archivos | 3 | Sí: `ruff format` |
| C3 | `mypy` encuentra errores | 2 por error, máximo 30 | No |
| C4 | Hay `TODO` pendientes en los `.py` (la palabra en mayúsculas) | 3, uno por microservicio | No |

**Dependencias** (`checks/dependencias.py`)

| Regla | Qué revisa | Descuenta | Arreglo |
|---|---|---|---|
| D1 | Una `lib-python-*` sin `@<sha>` (sin `@`, con `@main`, otra rama, un tag o `==versión`) en `python/requirements.txt` o en un `layers/requirements.txt` | 10 por línea | No: fijar una versión es una decisión |
| D2 | La misma librería con SHAs distintos entre el `layers/requirements.txt` de un microservicio y `python/requirements.txt` | 3 por línea | No |
| D3 | El código de `src/` importa una librería Melonn de [`references/librerias.md`](plugins/seedflow/references/librerias.md) (`melonnRedshiftConnector`, `we_are_melonn.slack_notifier`…) cuyo repo no está en el `layers/requirements.txt` de su microservicio | 10 por librería y microservicio | No |

**Seguridad e higiene** (`checks/higiene.py`)

| Regla | Qué revisa | Descuenta | Arreglo |
|---|---|---|---|
| H1 | Un `.env` (no `.env.example`) commiteado dentro de `projects/` | 25 por archivo | No: [opciones](#arreglos) en `/seedflow:revisar`. Fuera de git, aviso de 0 puntos |
| H2 | El `.gitignore` de la raíz no ignora el `python/.env` del proyecto | 10 en **cada** proyecto expuesto | Sí: agrega `.env` al final del `.gitignore` (lo crea si no existe) |
| H3 | Texto con forma de credencial en un `.py`: `AKIA…` o `password`/`secret`/`token` = un texto literal | 25 por archivo | No: muévela a una variable de entorno y rótala |
| H4 | `read`, `execute_query` o `write` con una query armada con f-string o `.format()` | 10 por archivo | No |

Detalles que cambian el resultado:

- H2 mira **solo** el `.gitignore` de la raíz, con las reglas de git (`**/.env`,
  `.env*`, negaciones…). No cuentan tu gitignore global, `.git/info/exclude` ni
  el `.gitignore` de un proyecto: así la nota es la misma en cualquier clon.
- H3 y H4 pueden dar falsos positivos, y el hallazgo lo dice. Nunca muestran el
  valor de una credencial: solo el archivo y las líneas.
- Ninguna regla entra a `.venv`, `venv`, `node_modules`, `cdk.out`, `.git` ni
  cachés, ni sigue enlaces.

### Arreglos

**Mecánicos.** Los que no requieren decidir nada. `/seedflow:revisar` los ofrece
al final del reporte con la lista exacta de archivos que toca cada uno, y los
aplica solo con un sí a esa pregunta; después vuelve a calificar. Desde la
terminal: [`fix`](#fix).

| `fix_id` | Qué hace | Toca |
|---|---|---|
| `E3:<proyecto>/<tipo>/<microservicio>` | Crea el evento de prueba con `{}` | `events/<microservicio>.json` |
| `E4:<proyecto>/<tipo>/<microservicio>` | Agrega la entrada que falta o quita la huérfana | `python/.vscode/launch.json` |
| `E5:<proyecto>/<tipo>/<microservicio>` | Cambia `../../events` por `../events`; el resto queda igual | `src/handler.py` |
| `H2:.gitignore` | Agrega `.env` al final, sin tocar las demás líneas (uno solo para todos los proyectos) | `.gitignore` de la raíz |
| `C1:<proyecto>/<tipo>/<microservicio>` | `ruff check --fix` con los arreglos seguros | Los archivos del microservicio que cambie |
| `C2:<proyecto>/<tipo>/<microservicio>` | `ruff format` | Los archivos del microservicio que cambie |

Un arreglo nunca borra archivos, no escribe a través de enlaces y no hace nada
si ya está arreglado. Nunca cambia lógica de negocio, queries, versiones de
dependencias ni el historial de git.

**No mecánicos.** `/seedflow:revisar` ofrece opciones, cada una con su propia
confirmación; `fix` no los toca:

- **`.env` commiteado (H1):** dejar de seguirlo (`git rm --cached`, el archivo
  queda en tu disco) y agregarlo al `.gitignore`, más la recomendación de
  rotar las credenciales que tenía. Sacarlo del historial de git queda fuera.
- **`iac/.git` anidado (E6):** moverlo a un respaldo fuera del repo, o
  borrarlo si confirmas que no necesitas ese historial.

### Observaciones de Claude

En `/seedflow:revisar`, Claude agrega lo que ninguna regla automática puede
juzgar, por ejemplo toda la lógica metida en `handler.py` con
`service/main.py` vacío. Van en una sección aparte y **no afectan la nota**.

### ruff y mypy

La calidad de código necesita `ruff` y `mypy`. seedflow no usa los que tengas
instalados (otra versión daría otra nota) ni toca tus entornos ni los del
proyecto:

- Los instala con `venv` + `pip` en un entorno propio:
  `~/.cache/seedflow/tools/ruff-<versión>_mypy-<versión>/` (en Windows,
  `%LOCALAPPDATA%\seedflow\tools\…`). La variable `SEEDFLOW_TOOLS_DIR`
  reemplaza la carpeta `tools`.
- Versiones: las que fija el proyecto en `python/requirements.txt` con `==`
  (la plantilla de seedflow fija `ruff==0.9.6` y `mypy==1.15.0`); si no las
  fija así, 0.9.6 y 1.15.0.
- La primera vez necesita internet y tarda alrededor de 70 segundos. Después
  el reporte completo tarda unos segundos. `pip` usa tu configuración (por
  ejemplo `PIP_INDEX_URL`).
- Solo se instala si algún proyecto tiene microservicios.
- Para reinstalar, borra esa carpeta: la próxima calificación la crea de nuevo.

Al calificar, `ruff` corre sin caché y `mypy` guarda la suya dentro del
entorno de herramientas: no queda nada en el repo. Tampoco se ejecuta código
del proyecto (por eso un `pyproject.toml` con plugins de mypy deja la
categoría "no evaluada").

### Fuera de alcance

- **Sin historial:** no guarda notas anteriores ni muestra si subieron o
  bajaron.
- **No bloquea nada:** ni commits, ni CI, ni la creación de proyectos. Solo
  informa.
- **No revisa `iac/` ni los scripts por dentro:** no revisa el TypeScript de
  `iac/` (salvo buscar `IacStack`) ni el contenido de `deployment-scripts/`;
  solo que existan.
- **Solo `projects/`:** no revisa nada fuera de esa carpeta, salvo el
  `.gitignore` de la raíz.
- **Arreglos solo mecánicos:** nunca cambian lógica de negocio, queries,
  versiones de dependencias ni historial de git.
- **Sin aviso al abrir Claude Code:** no hay hook automático al iniciar sesión.

### Limitaciones conocidas

- **`iac/.git` como enlace:** si `iac/.git` es un enlace simbólico (incluso
  roto), E6 descuenta 10 puntos en vez de dar un aviso de 0 como las demás
  rutas enlazadas.
- **El arreglo `H2:.gitignore` no es atómico:** reescribe el `.gitignore` de
  una vez, sin archivo temporal. Si el disco se llena justo al escribir, se
  pierde su contenido. Si lo tienes commiteado, `git checkout -- .gitignore`
  lo recupera.

---

## 9. Garantías y límites

Lo que garantiza el script:

- **No sale de `projects/`.** Los nombres se validan (nada de `..`, `/` ni
  nombres reservados de Windows), y no opera a través de enlaces simbólicos ni
  junctions de Windows.
- **No sobrescribe.** Si el proyecto o el microservicio ya existe, se detiene.
  La carpeta se crea en una sola operación, así que tampoco pisa algo creado
  un instante antes.
- **No deja estructuras a medias.** Si una creación falla, deja la raíz como
  estaba. Si no puede, lo dice y lista lo que quedó.
- **No borra sin `--yes`**, y `--dry-run` muestra antes qué se borraría.
- **Respeta tu `launch.json`.** Solo toca la entrada del microservicio. Si el
  archivo tiene comentarios o una forma inesperada, avisa y no lo toca.
- **Calificar solo lee.** `check` no escribe nada en el repo (ni cachés de
  `ruff` o `mypy`, ni `__pycache__`) y no ejecuta código del proyecto.
- **`fix` no borra.** Solo escribe los archivos de los arreglos que pides, no
  escribe a través de enlaces y no hace nada si ya está arreglado.

Lo que no cubre:

- **Dos comandos de seedflow a la vez sobre el mismo proyecto.** No hay
  bloqueo: uno puede perder la entrada del otro en `launch.json`.
- **Otro proceso cambiando carpetas por enlaces mientras el comando corre.**
  Las rutas se verifican antes de cada operación, no durante.
- **Windows sin probar.** El script está preparado (rutas, `cdk.cmd`, consolas
  sin UTF-8), pero no se ha corrido en una máquina Windows real.

---

## 10. Errores comunes

### Del plugin

| Síntoma | Causa | Solución |
|---|---|---|
| `Invalid marketplace source format` | La fuente no es `owner/repo`, una URL ni una ruta con `./`, `../`, `/` o `~` | `Looocust/seedflow` o `./seedflow` |
| `Plugin "seedflow" not found in marketplace "looocust"` | Catálogo local desactualizado | `claude plugin marketplace update looocust` |
| Instalé y los comandos no aparecen | Se instaló con una sesión abierta | `/reload-plugins` en la sesión, o reinicia `claude` |
| `Skills (0)` en `claude plugin details seedflow` | `--plugin-dir` apunta a la raíz del repo | Apunta a `seedflow/plugins/seedflow` |
| `already at the latest version` y no cambió nada | El repo cambió pero no la `version` | Ver [Actualizar](#11-actualizar-y-desinstalar) |

### Del script

| Mensaje | Causa | Solución |
|---|---|---|
| `El nombre de proyecto '…' no es válido` | Caracteres no permitidos, empieza por `_`, o más de 64 | Letras, números, `-` y `_` |
| `'CON' es un nombre reservado de Windows` | `CON`, `PRN`, `AUX`, `NUL`, `COM1`–`COM9`, `LPT1`–`LPT9` | Otro nombre |
| `El proyecto '…' ya existe en …` | Ya hay una carpeta con ese nombre | Otro nombre, o bórralo primero |
| `AWS CDK o npm no están instalados` | Falta `cdk` o `npm` en el PATH | Instala Node.js y `npm install -g aws-cdk`, o usa `--skip-cdk` |
| `Falló 'init app --language=typescript --generate-only'` | `cdk init` falló (lo muestra debajo) | Revisa el detalle; el proyecto se deshizo solo |
| `Falló 'install --no-audit --no-fund'` | `npm install` falló (red, permisos) | Revisa el detalle y reintenta; el proyecto se deshizo solo |
| `No existe el proyecto '…' (o no tiene python/)` | Estás en otra carpeta, o el proyecto no existe | Párate en la raíz del repo (`status`) |
| `… es un enlace simbólico o una junction` | Alguna carpeta de la ruta es un enlace | seedflow no opera a través de enlaces: reemplázalo por una carpeta real |
| `Borrar … es irreversible. Revisa con --dry-run…` | Falta `--yes` | Revisa con `--dry-run` y repite con `--yes` |
| `launch.json no tiene el formato esperado` | Tiene comentarios u otra forma | No es un error: agrega o quita la entrada a mano |
| `No pude deshacer todo lo que creé` | Falló la creación y también parte de la limpieza | Borra a mano las rutas que lista |
| `El borrado falló: … puede haber quedado incompleto` | El sistema no dejó borrar todo (archivo abierto, permisos) | Cierra lo que use esa carpeta y repite |
| `pip install -r requirements.txt` falla con `lib-python-*` | Los repos son privados de `we-are-melonn` | Necesitas acceso a la organización y git autenticado (`gh auth login`) |

### De la calificación (`check` y `fix`)

| Mensaje | Causa | Solución |
|---|---|---|
| `no encontré proyectos en …/projects, así que no hay nota` | No estás en la raíz del repo, o no tiene `projects/` | Párate en la raíz (`status`) o usa `--root` |
| `calidad de código: no evaluada (no se pudieron instalar ruff … y mypy …; se necesita internet la primera vez)` | Sin internet o sin `pip` la primera vez | Conéctate y califica de nuevo; el resto de la nota no cambia |
| `no evaluada (el pyproject pide reportes de mypy (…); seedflow no escribe archivos al calificar)` | `[tool.mypy]` tiene `*_report` o `junit_xml` | Quita esas opciones del `pyproject.toml` o pásalas por línea de comandos cuando corras mypy a mano |
| `no evaluada (el pyproject pide plugins de mypy (…); seedflow no ejecuta código del proyecto al calificar)` | `[tool.mypy]` tiene `plugins` | La calidad de ese proyecto no se puede calificar sin ejecutar esos plugins |
| `no evaluada (exclude de mypy inválido en …)` | Una expresión regular de `exclude` no compila | Corrígela en el `pyproject.toml` |
| `no evaluada (ruff falló (código N): …)` o `mypy falló …` | La herramienta salió con un error propio (configuración inválida, por ejemplo) | Corre `ruff check` o `mypy` a mano en `python/` para ver el detalle |
| `[E4] … La regla de launch.json no se pudo evaluar` | `launch.json` tiene comentarios u otra forma, o es un enlace | Aviso de 0 puntos: revísalo a mano o déjalo como JSON simple |
| `… es un enlace: lo que hay detrás no es parte del repo` | Una carpeta o archivo del proyecto es un enlace | Aviso de 0 puntos: reemplázalo por la carpeta o el archivo real para que se revise |
| `Arreglo '…' no válido: se espera REGLA:proyecto/tipo/microservicio.` | El `fix_id` está mal escrito | Copia el id de `fix --list` |
| `… no tiene el formato esperado (¿tiene comentarios?); actualízalo a mano.` | El arreglo E4 no puede editar ese `launch.json` | Agrega o quita la entrada a mano |
| `… es un enlace simbólico; seedflow no escribe a través de enlaces. Agrega la línea .env a mano.` | El `.gitignore` de la raíz es un enlace | Agrega `.env` a mano en el archivo real |
| `No existe …: créala a mano antes de agregar el evento.` | Al microservicio le falta `events/` (E2) | Crea `events/` y repite el arreglo E3 |
| `El módulo de reglas … no cumple el contrato` | Un módulo de `scripts/checks/` no define `CATEGORY`, `QUICK` o `run` | Solo pasa al desarrollar reglas: ver [Desarrollo](#12-desarrollo) |

---

## 11. Actualizar y desinstalar

### Si lo usas

```bash
claude plugin marketplace update looocust   # refresca el catálogo
claude plugin update seedflow@looocust      # instala la versión nueva
```

Reinicia Claude Code, o escribe `/reload-plugins`. Para comprobar la versión:

```bash
claude plugin details seedflow
```

Para que se actualice solo: `/plugin` → Marketplaces → `looocust` → *Enable
auto-update*.

### Si publicas cambios

1. Sube la `version` en `plugins/seedflow/.claude-plugin/plugin.json`. **Sin
   esto, `claude plugin update` responde `already at the latest version`** y
   sigue usando la copia anterior.
2. Corre los tests (ver [Desarrollo](#12-desarrollo)).
3. Haz commit y push a `main`.

### Desinstalar

```bash
claude plugin uninstall seedflow@looocust
claude plugin marketplace remove looocust   # opcional: quita también el catálogo
```

Si lo instalaste con `./install.sh`, borra `~/.claude/seedflow/` y las carpetas
`crear-proyecto`, `crear-microservicio`, `eliminar` y `revisar` de
`~/.claude/skills/`.

En los dos casos, el entorno de `ruff` y `mypy` queda en
`~/.cache/seedflow/` (Windows: `%LOCALAPPDATA%\seedflow\`): bórralo si ya no lo
necesitas.

---

## 12. Desarrollo

### Estructura del repositorio

```
seedflow/                               raíz del catálogo
├── .claude-plugin/marketplace.json     catálogo: looocust
├── install.sh                          instalación como skills sueltas
├── tests/
│   ├── test_seedflow.py                suite (unittest): crear y borrar
│   ├── test_check_*.py                 suite: la nota y cada categoría de reglas
│   ├── mutantes.py                     comprueba que la suite detecta fallas
│   └── mutantes/                       las fallas, un archivo por tema, con su TARGET y sus TESTS
└── plugins/seedflow/                   el plugin
    ├── .claude-plugin/plugin.json      nombre y versión
    ├── USO.md                          guía práctica de uso
    ├── scripts/
    │   ├── seedflow.py                 el script: crea, borra, check y fix
    │   └── checks/                     las reglas de la calificación
    │       ├── __init__.py               contrato (Finding, Context…) y cálculo de la nota
    │       ├── estructura.py             E1–E8 y sus arreglos
    │       ├── calidad.py                C1–C4, entorno de ruff y mypy, y sus arreglos
    │       ├── dependencias.py           D1–D3
    │       └── higiene.py                H1–H4 y su arreglo
    ├── templates/                      archivos que se copian tal cual
    │   ├── project/                      deployment-scripts/, python/
    │   ├── microservice/                 events/, layers/, src/ (__name__ = nombre del microservicio)
    │   └── database/                     src/database/ opcional
    ├── references/
    │   ├── estructura.md               qué va en cada carpeta
    │   └── librerias.md                cada lib-python-*: import, firma, uso
    └── skills/
        ├── crear-proyecto/SKILL.md
        ├── crear-microservicio/SKILL.md
        ├── eliminar/SKILL.md
        └── revisar/SKILL.md
```

### Cambiar lo que se genera

- **Archivos de un proyecto o microservicio** (SHAs de `requirements.txt`,
  reglas de ruff, el handler): edita `templates/`. No hay que tocar código. Si
  cambia la estructura, actualiza también `references/estructura.md`.
- **Las preguntas o lo que hace Claude:** edita el `SKILL.md` de la skill.
- **Una librería nueva o una firma que cambió:** actualiza
  `references/librerias.md`, comprobándolo contra el código del monorepo
  `melonn-common-python-packages`. Si cambia un import, actualiza también
  `IMPORT_TO_REPO` en `scripts/checks/dependencias.py` (un test compara los dos).
- **Una regla de la calificación:** va en el módulo de su categoría en
  `scripts/checks/` (`check` descubre los módulos solo). Cada módulo expone
  `CATEGORY`, `QUICK`, `run(ctx)` y, si tiene arreglos, `FIXES`. Agrega su test,
  su falla en `tests/mutantes/` y su fila en la tabla de
  [Reglas](#reglas).

Para probar los cambios sin publicar, usa la vía C de instalación y
`/reload-plugins`.

### Tests

Solo librería estándar, desde la raíz del repo:

```bash
python3 -m unittest discover -s tests -v   # la suite
python3 tests/mutantes.py                  # ¿la suite detecta fallas reales?
claude plugin validate .                   # manifiestos y skills
```

`mutantes.py` mete una falla por vez en una copia de `scripts/` (sin validar
nombres, sin `--yes`, una regla que no descuenta…) y verifica que algún test se
ponga en rojo. **Si agregas una protección o una regla nueva, agrega también su
falla.** Un resultado como `34/35 detectados` significa que hay un
comportamiento sin test.

Las fallas están en `tests/mutantes/`, un archivo por tema (`motor`,
`puntaje`, `estructura`, `calidad`, `dependencias`, `higiene`…). Cada uno
define `TARGET` (el archivo de `scripts/` que rompe), `MUTANTES` (la lista de
fallas) y, opcionalmente, `TESTS` (los módulos de `tests/` que las cubren). Con
`TESTS`, cada falla corre solo esos módulos, que es mucho más rápido; sin
`TESTS`, corre la suite completa. Las fallas corren en paralelo:
`SEEDFLOW_MUTANTES_JOBS=4 python3 tests/mutantes.py` fija cuántas a la vez
(por defecto, la mitad de los núcleos).

La suite nunca instala nada ni sale a internet: los tests de calidad usan
`ruff` y `mypy` falsos, y los que corren `check` completo usan un
`SEEDFLOW_TOOLS_DIR` temporal con `PIP_NO_INDEX=1`. Para correr además los
tests contra `ruff` y `mypy` de verdad, apunta `SEEDFLOW_TEST_REAL_TOOLS` a un
entorno ya instalado por seedflow (sin ella, esos tests se saltan):

```bash
SEEDFLOW_TEST_REAL_TOOLS=~/.cache/seedflow/tools/ruff-0.9.6_mypy-1.15.0 \
  python3 -m unittest tests.test_check_calidad -v
```

Los tests que usan `cdk` y `npm` falsos o el bit de ejecución se saltan en
Windows. Los de enlaces simbólicos se saltan si el sistema no permite crearlos.

---

## 13. Diferencias con melonn-python-cli

seedflow crea la misma estructura, con estos cambios:

| melonn-python-cli | seedflow |
|---|---|
| Se instala con un `.whl` y un token en la URL; hoy falla al arrancar (`No module named 'click'`) | Plugin de Claude Code; el script no tiene dependencias |
| `--help` de cada comando se cae; crear un microservicio desde `create-project` se cae | Probado con más de 200 tests y fallas a propósito (`tests/mutantes.py`) |
| El handler generado no encuentra su evento (`../../events`) | Busca en `../events` y carga `python/.env` |
| `iac/` queda con un repo git anidado; stack `IacStack` en todos los proyectos | Sin repo anidado; stack `<Proyecto>Stack` |
| Un nombre como `..` podía borrar la carpeta actual entera | Nombres validados; nunca sale de `projects/` |
| Sobrescribe archivos si el microservicio ya existe | Se detiene |
| Deja proyectos a medias si algo falla | Deshace lo que creó |
| `launch.json` se escribe una vez y queda desactualizado | Se actualiza al crear y borrar microservicios |
| Pregunta en la terminal | Pregunta en el chat y además escribe el código con las librerías |

---

Licencia [MIT](LICENSE).
