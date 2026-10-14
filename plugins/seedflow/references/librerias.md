# Librerías Melonn (`lib-python-*`)

Fuente: el monorepo `we-are-melonn/melonn-common-python-packages`. Cada paquete
se replica a su propio repo `we-are-melonn/lib-python-*` y se instala desde ahí
con `pip install git+https://...`. **No están en PyPI.** Todas requieren
Python ≥ 3.12.

`boto3` no viene en las dependencias de ninguna: se asume que lo trae el
entorno (Lambda), y en local está en el `requirements.txt` del proyecto.

## Cómo fijar la versión

Siempre `git+https://github.com/we-are-melonn/<repo>.git@<sha>`, nunca sin `@`.

1. Si el `python/requirements.txt` del proyecto ya tiene esa librería, usa el
   mismo SHA.
2. Si no, obtén el último commit (requiere acceso a la organización):
   `git ls-remote https://github.com/we-are-melonn/<repo>.git HEAD`
3. Si eso falla por permisos, escribe `@main  # TODO: fijar SHA` y avísale al
   usuario.

## Índice

Las primeras columnas son las opciones que pregunta `crear-microservicio`.

| Opción | Repo | Import | Variables de entorno |
|---|---|---|---|
| Redshift | `lib-python-redshift-connector` | `from melonnRedshiftConnector.redshift import Redshift` | `DATABASE_RS_URL_READER`, `DATABASE_RS_USER`, `DATABASE_RS_PASSWORD`, `DATABASE_RS_PORT`, `DATABASE_RS_NAME` |
| Aurora MySQL | `lib-python-mysql-connector` | `from melonnMySQLConnector.aurora_mysql import AuroraMySQL` | `DATABASE_URL_READER`, `DATABASE_USER`, `DATABASE_PASSWORD`, `DATABASE_PORT`, `DATABASE_NAME` |
| S3 | `lib-python-aws-utils` | `from melonnAWSUtils.s3 import S3` | un `*_BUCKET_NAME` (ver sección S3); `AWS_*` solo en local |
| DynamoDB | `lib-python-aws-utils` | `from melonnAWSUtils.dynamo import DynamoDB` | nombre de tabla como variable; `AWS_*` solo en local |
| Google Sheets | `lib-python-google-connector` | `from melonnGoogleConnector.google_connector import GoogleSheet` | credenciales de cuenta de servicio + id de la hoja |
| Notificar a Slack | `lib-python-slack-notifier` | `from we_are_melonn.slack_notifier import SlackNotifier` | `SLACK_CHANNEL` |
| Notificar a Google Chat | `lib-python-google-chat-notifier` | `from we_are_melonn.google_notifier import GoogleChatNotifier` | `GOOGLE_CHAT_WEBHOOK_URL` |
| Logs con Melogger | `lib-python-melogger` | `from we_are_melonn.melogger import Melogger` (+ `System`, `Cluster`, un import por línea) | `MELOGGER_URL`, `MELOGGER_API_KEY`, `MELOGGER_LOG_LEVEL` |
| Validar parámetros del evento | `lib-python-validator` | `from melonnValidator.event_validator import EventValidator` | — |
| (siempre que uses `LambdaExecutionError`) | `lib-python-custom-errors` | `from melonnCustomErrors.custom_errors import LambdaExecutionError` | — |
| Validar headers de contexto | `lib-python-validator` | `from melonnValidator.request_validator import context_check` | — |

`lib-python-router-utils` es un stub sin lógica: **no lo uses**.

Ojo con los imports: solo los paquetes `we_are_melonn.*` exportan sus clases
desde `__init__.py`. En los `melonn*` hay que importar desde el módulo
(`melonnAWSUtils.s3`, no `melonnAWSUtils`).

---

## Redshift: `lib-python-redshift-connector`

```python
Redshift(connection_parameters: Mapping[str, Any], is_connection_string: bool = False)
.read(query: str, params: Mapping[str, Any] = {}) -> DataFrame
.write(query: str) -> None
```

- Diccionario: `{"host", "user", "password", "port", "database"}`.
- Como string (`is_connection_string=True`): `{"database_url": "user:password@host:port/database"}`.
- Variables del `.env.example` del proyecto: `DATABASE_RS_URL_READER`,
  `DATABASE_RS_USER`, `DATABASE_RS_PASSWORD`, `DATABASE_RS_PORT`,
  `DATABASE_RS_NAME`.

```python
redshift = Redshift({
    "host": os.environ["DATABASE_RS_URL_READER"],
    "user": os.environ["DATABASE_RS_USER"],
    "password": os.environ["DATABASE_RS_PASSWORD"],
    "port": os.environ["DATABASE_RS_PORT"],
    "database": os.environ["DATABASE_RS_NAME"],
})
df = redshift.read("SELECT ... WHERE id = {id}", {"id": 10})
```

**Escribir:** `write` solo recibe SQL. Para guardar un DataFrame con muchas
filas, lo normal en Redshift es subirlo a S3 (`S3.upload_parquet`) y cargarlo
con `COPY`. Un `INSERT` armado con valores del DataFrame tiene el mismo riesgo
de inyección que `params`: escapa los valores o usa `COPY`. Las variables
`DATABASE_RS_*` del `.env.example` son de lectura (`_URL_READER`); para
escribir hacen falta credenciales de escritura.

**Cuidado con `params`:** `read` hace `query.format(**params)`. Los
placeholders son `{nombre}` (no `%s`) y los valores se pegan como texto dentro
de la query: **no es una query parametrizada**. Nunca pases ahí valores que
vengan del evento sin validarlos antes (tipo con `EventValidator`, o una lista
cerrada de valores permitidos); si no, hay inyección SQL. Los strings van entre
comillas en la query: `WHERE name = '{name}'`. Una llave literal en el SQL
se escribe doble: `{{` y `}}`.

## Aurora MySQL: `lib-python-mysql-connector`

```python
AuroraMySQL(connection_parameters: Mapping[str, Any], is_connection_string: bool = False, raise_mysql_error: bool = False)
.execute_query(query: str, params: Mapping[str, Any] = {}) -> DataFrame
```

- Mismas claves que Redshift (`host`, `user`, `password`, `port`, `database`,
  o `database_url`).
- Variables del `.env.example`: `DATABASE_URL_READER`, `DATABASE_USER`,
  `DATABASE_PASSWORD`, `DATABASE_PORT`. Falta el nombre de la base: agrega
  `DATABASE_NAME` siempre que uses Aurora. Sin él la conexión queda sin base
  por defecto y cada query tendría que escribir `base.tabla`.
- Fija `mysql-connector-python==9.0.0`. No lo cambies.
- `params` funciona igual que en Redshift (`query.format(**params)`, con
  placeholders `{nombre}`): aplica la misma advertencia de inyección SQL.
- Errores: `execute_query` siempre lanza si la query falla. Por defecto lo
  envuelve en un `ValueError` genérico ("An error occurred…") y el error real
  queda en `__cause__`. Con `raise_mysql_error=True` relanza el error original
  de MySQL. Úsalo en `True` en código nuevo: el mensaje es más útil.

## S3: `lib-python-aws-utils`

```python
S3(bucket_name: str)
.upload_json(data, object_key) / .upload_parquet(df, object_key) / .upload_csv(df, object_key)
.upload_xlsx(df, object_key) / .upload_bytes(data, object_key)
.read_json(object_key) -> Mapping / .read_parquet(object_key) -> DataFrame
.read_csv(object_key, sep=",") -> DataFrame / .read_xlsx(object_key, sheet_name="") -> DataFrame
.read_bytes(object_key) -> bytes
```

- Credenciales: las de boto3 (rol IAM en Lambda; `AWS_*` del `.env` en local).
- El bucket va como variable de entorno. `DS_CORE_BUCKET_NAME` ya está en el
  `.env.example`; reutilízala solo si el usuario dijo que es ese bucket. Si no,
  crea `<NOMBRE_DEL_SERVICIO>_BUCKET_NAME`.

## DynamoDB: `lib-python-aws-utils`

```python
DynamoDB()
.execute_query(table_name: str, pk: str | int, sk: str, condition: str, limit: int = 1, scan_index_forward: bool = False) -> Mapping | str
.write_data(table_name: str, data: list[Mapping[str, Any]]) -> None
```

## Google Sheets: `lib-python-google-connector`

```python
GoogleSheet(credentials: dict, sheet_id: str, protection_name: str = None, allow_users: list = None)
.read_data_from_sheets(sheet_name: str, evaluate_formulas: bool = True) -> DataFrame
.write_data_to_gsheets(sheet_name: str, base_df: DataFrame, worksheet_number: int, resize: bool = True, string_escaping: str = "default") -> bool
.lock_sheet(worksheet) / .unlock_sheet(worksheet) / .get_worksheet(worksheet_number)
```

- `credentials` es el JSON de una cuenta de servicio de Google. No lo pongas en
  el código: léelo de un secreto o de una variable de entorno.
- Reintenta 3 veces con 2 segundos de espera.

## Slack: `lib-python-slack-notifier`

```python
SlackNotifier(title: str | None = None, channel: str | None = None)
.notify(title: str | None = None, error: str | Exception | None = None, data: dict | None = None) -> None
```

- Sin `channel`, lee `SLACK_CHANNEL` (el path del webhook de hooks.slack.com).
- Si no hay canal, imprime una advertencia y no envía nada. Sin `error` ni
  `data`, tampoco envía nada.

## Google Chat: `lib-python-google-chat-notifier`

```python
GoogleChatNotifier(title: str | None = None, webhook_url: str | None = None)
.notify(title=None, error=None, data=None, blocks=None, cards_v2=None) -> None
```

- Sin `webhook_url`, lee `GOOGLE_CHAT_WEBHOOK_URL`.
- Reintenta 3 veces con 2 segundos de espera.

## Melogger: `lib-python-melogger`

```python
Melogger(system: System, sub_system: Cluster, project: str, component: str, service: str,
         runtime: str = None, logger_override=None, slack_notifier=None, log_level: LogLevel = None)
.info(event_data: dict, trace_id: str = None, entity: dict = None)
.warn(...) / .error(...)
```

- Variables: `MELOGGER_URL`, `MELOGGER_API_KEY` y `MELOGGER_LOG_LEVEL`.
- **Sin `MELOGGER_LOG_LEVEL` (o sin `log_level` en el constructor), el nivel es
  `ERROR`**: los `info` y `warn` se descartan sin aviso. Si el usuario quiere
  logs, agrega `MELOGGER_LOG_LEVEL` al `.env.example` y dile que la ponga en
  `INFO`.
- Argumentos, para un microservicio creado con seedflow: `system=System.BACKEND`,
  `sub_system=Cluster.<el que diga el usuario>`, `project="<proyecto>"`,
  `component="<internal-services | consumable-services>"`,
  `service="<microservicio>"`. `runtime` no lo pases: lo toma de `NODE_ENV`.
- Importa cada nombre en su propia línea (`from we_are_melonn.melogger import
  Melogger`, `from we_are_melonn.melogger import System`…) y solo los que uses.
- `System`: `BACKEND`, `FRONTEND`, `OPS_PORTAL`, `ADMIN_PORTAL`, `USER_PORTAL`,
  `SUPPORT_PORTAL`, `SELLER_PORTAL`, `SELLER_SIGN_UP_PORTAL`, `TRACKING_PORTAL`.
  Para microservicios de datos lo normal es `System.BACKEND`.
- `Cluster` (`sub_system`): `DATA_HUB` y `FORECAST` son los de datos; también
  existen `WAREHOUSE_MGMT`, `STOCK_MGMT`, `SELL_ORDERS`, `TRANSPORT`,
  `FINANCIAL`, etc. Pregunta si no es obvio.
- `slack_notifier`: le puedes pasar un `SlackNotifier` para que los errores
  también lleguen a Slack.

## Errores: `lib-python-custom-errors`

```python
LambdaExecutionError(message: str = "La ejecución de la función Lambda falló",
                     status_code: int | None = None, error_details: dict | None = None)
```

Es el error estándar para cortar una Lambda con un código HTTP y detalle.

## Validación: `lib-python-validator`

```python
EventValidator.validate(  # método estático
    event: dict, key_name: str, required_parameters: list[str],
    type_required_parameters: list[type] = (), default_value_required_parameters: dict = {},
    optional_parameters: list[str] = (), type_optional_parameters: list[type] = (),
    all_errors: bool = True,
) -> tuple[bool, str]

context_check(headers: dict[str, str]) -> tuple[dict | None, str | None]
```

- `validate` devuelve `(es_valido, mensaje)` en vez de lanzar excepciones. Revisa
  el booleano y, si falla, lanza `LambdaExecutionError(mensaje, 400)`.
- **Modifica el evento:** convierte los tipos dentro de `event[key_name]`. Desde
  API Gateway los query string llegan como `str`; después de validar, ya son del
  tipo pedido y puedes leerlos directo.
- **Revienta si no hay query string.** API Gateway manda
  `"queryStringParameters": null` cuando no viene ninguno, y con `all_errors=True`
  (el default) `validate` lanza `TypeError` en vez de devolver `False`. Normaliza
  antes de validar:
  `event["queryStringParameters"] = event.get("queryStringParameters") or {}`.
- `key_name` suele ser `"queryStringParameters"`.
- Validar el tipo no hace seguro un string libre: si un parámetro `str` va a
  una query (Redshift o Aurora usan `format`), deja en el TODO de la query que
  hay que compararlo contra una lista cerrada de valores.
