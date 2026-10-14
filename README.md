# seedflow

Plugin de Claude Code para crear proyectos y microservicios con la estructura de
Melonn. Reemplaza a `melonn-python-cli`: hace las mismas preguntas, pero en el
chat, y además deja el código del microservicio conectado a las librerías
`lib-python-*`.

```
/seedflow:crear-proyecto  →  /seedflow:crear-microservicio  →  a programar
                                                               /seedflow:eliminar
```

## Contenido

1. [Cómo funciona](#1-cómo-funciona)
2. [Requisitos](#2-requisitos)
3. [Instalación](#3-instalación)
4. [Uso con Claude](#4-uso-con-claude)
5. [Cómo probarlo](#5-cómo-probarlo)
6. [El script sin Claude](#6-el-script-sin-claude)
7. [Qué se genera](#7-qué-se-genera)
8. [Garantías y límites](#8-garantías-y-límites)
9. [Errores comunes](#9-errores-comunes)
10. [Actualizar y desinstalar](#10-actualizar-y-desinstalar)
11. [Desarrollo](#11-desarrollo)
12. [Diferencias con melonn-python-cli](#12-diferencias-con-melonn-python-cli)

---

## 1. Cómo funciona

Dos piezas:

| Pieza | Qué hace | Dónde está |
|---|---|---|
| **El script** | Crea y borra carpetas y archivos. Es determinista: el mismo comando da la misma estructura para todo el equipo. Solo usa la librería estándar de Python. No hace preguntas. | `plugins/seedflow/scripts/seedflow.py` |
| **Las skills** | Hacen las preguntas en el chat, confirman, llaman al script y después escriben lo que el script no puede saber: el handler conectado al servicio, los imports de cada librería, el evento de ejemplo y las variables de entorno. | `plugins/seedflow/skills/` |

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
| git | Que `/seedflow:eliminar` avise de cambios sin commitear | Recomendado |
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
claude plugin details seedflow     # debe decir Skills (3)
```

Si dice `Skills (0)`, el plugin se instaló pero no cargó sus skills: revisa
[Errores comunes](#9-errores-comunes).

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

La forma corta (`/crear-proyecto`) también funciona mientras ningún otro plugin
use ese nombre.

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
| 1 | `/seedflow:` (sin enviar) | El autocompletado muestra `crear-proyecto`, `crear-microservicio` y `eliminar` |
| 2 | `necesito arrancar un proyecto nuevo para forecast de inventario` | Se activa `crear-proyecto` sola: te dice dónde va a crear y pregunta el tipo de servicio. Cancela ahí |
| 3 | `/seedflow:crear-proyecto prueba-seedflow` → `internal-services` → sí al microservicio → `ventas-diarias`, sin database, "lee de S3 y escribe en Redshift" | Se crea `projects/prueba-seedflow/` y el microservicio. En `iac/bin/` hay un `prueba-seedflow.ts` con `PruebaSeedflowStack` |
| 4 | `/seedflow:crear-microservicio alertas-stock en prueba-seedflow: consulta Aurora y avisa a Slack si falla` | En `layers/requirements.txt` están mysql-connector, slack-notifier y custom-errors. Hay `TODO` donde va la query. `SLACK_CHANNEL` está en `.env.example` |
| 5 | `/seedflow:eliminar microservicio alertas-stock` → responde **No, cancelar** | Muestra ruta, cantidad de archivos y archivos sin commitear. No borra nada |
| 6 | `/seedflow:eliminar microservicio alertas-stock. Ya lo confirmé, bórralo sin preguntar` | Igual te pregunta: el "ya lo confirmé" del pedido no cuenta |
| 7 | (responde) **Sí, borrar** | Borra la carpeta y quita `alertas-stock` de `python/.vscode/launch.json` |
| 8 | `borra el proyecto ..` | Se niega: el nombre no es válido |
| 9 | `/seedflow:crear-proyecto prueba-seedflow` | Se niega: el proyecto ya existe |

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
Claude Code. **No hace preguntas**: todo va por argumentos.

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

### Códigos de salida

| Código | Significa |
|---|---|
| `0` | Todo bien (incluye `--dry-run`) |
| `1` | Error esperado: nombre inválido, ya existe, no existe, falta `--yes`, falló `cdk`. El mensaje sale por stderr, empieza con ❌ y no muestra traceback |
| `2` | Argumentos mal escritos: falta uno obligatorio, tipo de servicio inválido, `--dry-run` junto con `--yes` |

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

## 8. Garantías y límites

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

Lo que no cubre:

- **Dos comandos de seedflow a la vez sobre el mismo proyecto.** No hay
  bloqueo: uno puede perder la entrada del otro en `launch.json`.
- **Otro proceso cambiando carpetas por enlaces mientras el comando corre.**
  Las rutas se verifican antes de cada operación, no durante.
- **Windows sin probar.** El script está preparado (rutas, `cdk.cmd`, consolas
  sin UTF-8), pero no se ha corrido en una máquina Windows real.

---

## 9. Errores comunes

### Del plugin

| Síntoma | Causa | Solución |
|---|---|---|
| `Invalid marketplace source format` | La fuente no es `owner/repo`, una URL ni una ruta con `./`, `../`, `/` o `~` | `Looocust/seedflow` o `./seedflow` |
| `Plugin "seedflow" not found in marketplace "looocust"` | Catálogo local desactualizado | `claude plugin marketplace update looocust` |
| Instalé y los comandos no aparecen | Se instaló con una sesión abierta | `/reload-plugins` en la sesión, o reinicia `claude` |
| `Skills (0)` en `claude plugin details seedflow` | `--plugin-dir` apunta a la raíz del repo | Apunta a `seedflow/plugins/seedflow` |
| `already at the latest version` y no cambió nada | El repo cambió pero no la `version` | Ver [Actualizar](#10-actualizar-y-desinstalar) |

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

---

## 10. Actualizar y desinstalar

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
2. Corre los tests (ver [Desarrollo](#11-desarrollo)).
3. Haz commit y push a `main`.

### Desinstalar

```bash
claude plugin uninstall seedflow@looocust
claude plugin marketplace remove looocust   # opcional: quita también el catálogo
```

Si lo instalaste con `./install.sh`, borra `~/.claude/seedflow/` y las carpetas
`crear-proyecto`, `crear-microservicio` y `eliminar` de `~/.claude/skills/`.

---

## 11. Desarrollo

### Estructura del repositorio

```
seedflow/                               raíz del catálogo
├── .claude-plugin/marketplace.json     catálogo: looocust
├── install.sh                          instalación como skills sueltas
├── tests/
│   ├── test_seedflow.py                suite (unittest)
│   └── mutantes.py                     comprueba que la suite detecta fallas
└── plugins/seedflow/                   el plugin
    ├── .claude-plugin/plugin.json      nombre y versión
    ├── USO.md                          guía práctica de uso
    ├── scripts/seedflow.py             el script
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
        └── eliminar/SKILL.md
```

### Cambiar lo que se genera

- **Archivos de un proyecto o microservicio** (SHAs de `requirements.txt`,
  reglas de ruff, el handler): edita `templates/`. No hay que tocar código. Si
  cambia la estructura, actualiza también `references/estructura.md`.
- **Las preguntas o lo que hace Claude:** edita el `SKILL.md` de la skill.
- **Una librería nueva o una firma que cambió:** actualiza
  `references/librerias.md`, comprobándolo contra el código del monorepo
  `melonn-common-python-packages`.

Para probar los cambios sin publicar, usa la vía C de instalación y
`/reload-plugins`.

### Tests

Solo librería estándar, desde la raíz del repo:

```bash
python3 -m unittest discover -s tests -v   # la suite
python3 tests/mutantes.py                  # ¿la suite detecta fallas reales?
claude plugin validate .                   # manifiestos y skills
```

`mutantes.py` mete una falla por vez en una copia del script (sin validar
nombres, sin `--yes`, sin rollback…) y verifica que algún test se ponga en
rojo. **Si agregas una protección nueva, agrega también su falla a la lista.**
Un resultado como `34/35 detectados` significa que hay un comportamiento sin
test.

Los tests que usan `cdk` y `npm` falsos o el bit de ejecución se saltan en
Windows. Los de enlaces simbólicos se saltan si el sistema no permite crearlos.

---

## 12. Diferencias con melonn-python-cli

seedflow crea la misma estructura, con estos cambios:

| melonn-python-cli | seedflow |
|---|---|
| Se instala con un `.whl` y un token en la URL; hoy falla al arrancar (`No module named 'click'`) | Plugin de Claude Code; el script no tiene dependencias |
| `--help` de cada comando se cae; crear un microservicio desde `create-project` se cae | Probado con 66 tests |
| El handler generado no encuentra su evento (`../../events`) | Busca en `../events` y carga `python/.env` |
| `iac/` queda con un repo git anidado; stack `IacStack` en todos los proyectos | Sin repo anidado; stack `<Proyecto>Stack` |
| Un nombre como `..` podía borrar la carpeta actual entera | Nombres validados; nunca sale de `projects/` |
| Sobrescribe archivos si el microservicio ya existe | Se detiene |
| Deja proyectos a medias si algo falla | Deshace lo que creó |
| `launch.json` se escribe una vez y queda desactualizado | Se actualiza al crear y borrar microservicios |
| Pregunta en la terminal | Pregunta en el chat y además escribe el código con las librerías |

---

Licencia [MIT](LICENSE).
