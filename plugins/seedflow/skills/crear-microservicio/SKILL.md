---
name: crear-microservicio
argument-hint: "nombre del microservicio y, si quieres, qué debe hacer"
description: Crea un microservicio (Lambda en Python) dentro de un proyecto Melonn con la estructura estándar (events, layers, src/service, src/database opcional) y lo deja conectado con las librerías lib-python-* que necesita (Redshift, Aurora MySQL, S3, DynamoDB, Slack, Google Chat, Melogger, Google Sheets, validator). Úsala cuando el usuario diga "crea un microservicio", "nuevo microservicio", "agrega una lambda al proyecto", "create-microservice", o describa un servicio nuevo que debe leer, escribir o notificar algo dentro de un proyecto de data-hub o ds-core.
---

# Crear microservicio

Dos partes, en este orden:

1. **La estructura**, que la crea siempre el script del plugin (igual para todo
   el equipo).
2. **El esqueleto de código**, que escribes tú: el handler conectado al
   servicio, las librerías Melonn que va a usar, un evento de ejemplo y las
   variables de entorno.

Habla con el usuario en español.

## El script

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/seedflow.py" <comando> [opciones]
```

Si `python3` no existe (Windows), usa `py -3` o `python`. Córrelo desde la
carpeta raíz del repo del usuario (data-hub, ds-core…).

Referencias del plugin (léelas cuando las necesites, no todas de entrada):

- `${CLAUDE_PLUGIN_ROOT}/references/estructura.md`: qué va en cada carpeta.
- `${CLAUDE_PLUGIN_ROOT}/references/librerias.md`: cada `lib-python-*`, cómo se
  instala, se importa y se usa. **Léela antes de escribir cualquier import de
  una librería Melonn**; no adivines rutas de import.

## Paso 1 — Dónde estás parado

Corre `status --json`. Si `projects` viene vacío, no hay proyectos en esta
carpeta: o el usuario está en la carpeta equivocada o tiene que crear el
proyecto primero (skill `crear-proyecto`). Díselo y no sigas.

## Paso 2 — Las preguntas

Usa `AskUserQuestion` cuando esté disponible; si no, pregunta en texto, todo
junto. No preguntes lo que ya viene en `$ARGUMENTS` o en el mensaje.

Las del CLI:

1. **Proyecto**: opciones a partir de `status` (si hay más de 4, pídelo en
   texto mostrando la lista).
2. **Tipo de servicio**: `internal-services` o `consumable-services`. Si el
   proyecto solo tiene uno, propón ese primero.
3. **Nombre**: texto libre. Letras, números, `-` y `_`. Si ya existe en ese
   proyecto y tipo, pide otro.
4. **¿Carpeta `database`?** Sí / No. Sugiere que sí si va a leer o escribir en
   Redshift o Aurora MySQL.

Las que agrega seedflow (selección múltiple):

5. **¿Con qué datos trabaja?**: Redshift · Aurora MySQL · S3 · DynamoDB (Google
   Sheets entra por "Otro").
6. **¿Qué más necesita?**: Notificar a Slack · Notificar a Google Chat ·
   Logs con Melogger · Validar parámetros del evento (API Gateway).

Si el usuario ya describió qué hace el servicio, deduce las respuestas de 5 y 6
y no las preguntes. Por ejemplo, "recibe seller_id por query string" implica
"Validar parámetros del evento", y "avisa si falla" implica notificar (si no
dice el canal, pregunta solo eso). Incluye lo que dedujiste en el resumen del
paso 3, para que el usuario lo vea.

Si el usuario no sabe todavía, sigue sin librerías: el esqueleto vacío también
sirve.

## Paso 3 — Crear la estructura

Muestra un resumen de una línea (proyecto, tipo, nombre, `database`, librerías).
Si el usuario ya confirmó en su mensaje, no vuelvas a pedir confirmación: muestra
el resumen y sigue. Si no, espera su sí. Luego:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/seedflow.py" create-microservice <nombre> --project <proyecto> --service-type <tipo> [--database]
```

El script crea las carpetas, `handler.py`, `service/main.py`, el evento vacío y
la entrada en `python/.vscode/launch.json`. Si falla, muestra el error tal cual
y no crees nada a mano.

## Paso 4 — El esqueleto de código

Solo si en el paso 2 eligió alguna librería o describió qué hace el servicio.
Ruta base: `projects/<proyecto>/python/<tipo>/<nombre>/`. La tabla "Índice" de
`librerias.md` dice, para cada opción del paso 2, qué repo, qué import y qué
variables de entorno corresponden.

`src/` es la raíz de los imports, tanto en la Lambda como al correr
`python3 src/handler.py`: se importa `from service.main import main` y
`from database.redshift import ...`, nunca `from src....`.

1. **`layers/requirements.txt`**: una línea `git+https://...@<sha>` por cada
   librería `lib-python-*` que el código importe, incluidas las que agregues tú
   (por ejemplo, `lib-python-custom-errors` si usas `LambdaExecutionError`). No
   agregues `pandas` ni `boto3`: llegan con las librerías o con la Lambda. Solo
   agrega otra dependencia de terceros si el código la importa directo y
   ninguna librería la trae. Usa el SHA que ya
   tenga el `python/requirements.txt` del proyecto para esa librería; si no está
   ahí, sigue lo que dice `librerias.md` sobre cómo fijarlo. Las que no estaban
   en `python/requirements.txt`, agrégalas también ahí con el mismo SHA, para que
   el entorno local pueda correr el microservicio.
2. **Conexiones a bases de datos**: una función `get_redshift_connection() ->
   Redshift` (o `get_aurora_connection() -> AuroraMySQL`) que arma la conexión
   desde variables de entorno **al llamarla**, no al importar el módulo. Con
   `src/database/`, va en un archivo por motor (`database/redshift.py`,
   `database/aurora_mysql.py`). Sin esa carpeta (el usuario dijo que no), va en
   `src/service/main.py`.
   - Si el servicio **escribe**, no uses las variables `*_URL_READER`: esas
     apuntan a lectura. Pregúntale qué host y usuario usar para escribir. Si
     no sabe, usa variables nuevas con sufijo `_WRITER` (por ejemplo
     `DATABASE_RS_URL_WRITER`) y avísale en el cierre.
3. **`src/service/main.py`**: la función `main(event)` que ya existe, con las
   clases instanciadas con su firma real (la de `librerias.md`) y el flujo que
   describió el usuario.
   - **No inventes lógica de negocio, queries, tablas, buckets ni rutas de
     objetos en S3.** Lo que el usuario no dijo va así:
     - Recursos que cambian por ambiente (bucket, tabla, canal): variable de
       entorno. Para el bucket, reutiliza una variable `*_BUCKET_NAME` del
       `.env.example` solo si el usuario dijo que es ese bucket. Si no, crea
       `<NOMBRE_DEL_SERVICIO>_BUCKET_NAME` (por ejemplo `ORDERS_SYNC_BUCKET_NAME`).
     - Lo que es código (la query, la ruta del objeto, una transformación): una
       función o constante marcada con `# TODO:` que, si se ejecuta sin
       completar, lance `NotImplementedError("TODO: <qué falta>")`. Nunca un
       string vacío que falle más adelante con un error confuso.
4. **`src/handler.py`**: mantén `run(event, stage)` y el bloque `__main__` que
   lee `events/<nombre>.json`. Puedes envolver el cuerpo de `run` en
   `try/except`. Si el usuario eligió notificar (Slack o Google Chat):
   - La notificación va en el `except` del handler, no en `service/`.
   - Instancia el notificador con `title="<nombre del microservicio>"` y llama
     `notify(error=error, data={"stage": stage})`.
   - Después relanza como `LambdaExecutionError(str(error), 500)`, encadenado
     con `from error`. Si el error ya era un `LambdaExecutionError` (por
     ejemplo, un 400 de validación), relánzalo tal cual.

   Si eligió **Melogger**, va también en el handler: se instancia dentro de
   `run` (argumentos en `librerias.md`), un `info` al empezar y al terminar y un
   `error` en el `except`. `service/` no loguea salvo que el usuario lo pida.

   **No cambies la forma de la respuesta.** `run` devuelve lo que devuelve
   `main(event)`. No la conviertas a formato proxy de API Gateway
   (`statusCode`/`body`) ni cambies cómo se mapean los errores a HTTP: eso
   depende de cómo esté configurada la Lambda en `iac/`. Si el usuario lo pide,
   pregúntale el formato.
5. **`events/<nombre>.json`**: si el servicio lee algo del evento, un ejemplo
   con esa forma. Si valida parámetros de API Gateway, usa
   `queryStringParameters` con valores en string. Si no lee nada del evento
   (por ejemplo, un proceso programado), déjalo en `{}`.
6. **`python/.env.example`** del proyecto: agrega las variables nuevas que use
   el servicio, sin valores. No repitas las que ya están.

Respeta el estilo del `pyproject.toml` del proyecto: líneas de 80 caracteres,
comillas dobles, docstrings numpy, type hints en todo, un import por línea.

## Paso 5 — Verificar

1. Si `ruff` está disponible, corre sobre la carpeta del microservicio
   `ruff format` y después `ruff check`, y corrige lo que marque. Revisa a mano
   que haya un solo import por línea: el `select` del proyecto no lo valida.
2. Elige el intérprete: el del proyecto si existe (`python/.venv/bin/python`,
   o `python\.venv\Scripts\python.exe` en Windows); si no, `python3`, y dile
   al usuario que lo probaste con el Python global, no con el del proyecto.
   Con ese intérprete, comprueba si las librerías que agregaste se pueden
   importar (`<python> -c "import melonnAWSUtils.s3"`, etc.):
   - **Si están todas** (o no agregaste ninguna), corre el handler:
     `cd <ruta del microservicio> && <python> -B src/handler.py <nombre>`
     (`-B` evita dejar carpetas `__pycache__`). El
     handler carga `python/.env` si existe. Si falla solo por un
     `NotImplementedError` de tus TODOs o por una variable de entorno que el
     usuario todavía no llenó, está bien: dilo.
   - **Si falta alguna**, no lo ejecutes. Revisa la sintaxis sin dejar
     `__pycache__` en el proyecto:
     `python3 -c "import ast, sys; [ast.parse(open(f, encoding='utf-8').read(), f) for f in sys.argv[1:]]" <archivos>`.
     Después dile al usuario qué instalar para probarlo.

## Paso 6 — Cierre

Resume en pocas líneas qué quedó, qué TODOs dejaste y qué variables de entorno
tiene que completar. Para depurarlo: abrir `python/` en VS Code y elegir la
configuración `<nombre>` en Run and Debug. No hagas commit.

Termina con la nota del repo. Corre, desde la carpeta raíz del repo:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/seedflow.py" check --quick
```

y muestra su línea tal cual, al final (es rápida: no revisa calidad de
código). Si falla, no afecta lo creado: omítela.
