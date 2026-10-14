# Estructura de un proyecto Melonn

Todo se crea desde la **carpeta raíz del repo** (data-hub, ds-core…), dentro de
`projects/`. El script resuelve las rutas desde la carpeta donde se corre.

```
projects/<proyecto>/
├── deployment-scripts/          # fases del pipeline de despliegue
│   ├── install.sh               #   instalar dependencias
│   ├── pre_build.sh             #   antes de construir
│   ├── build.sh                 #   construir
│   └── post_build.sh            #   después de construir
├── iac/                         # infraestructura como código: AWS CDK en TypeScript
│   ├── bin/<proyecto>.ts        #   (lo genera `cdk init app --language=typescript`)
│   ├── lib/<proyecto>-stack.ts  #   stack <Proyecto>Stack, p. ej. StockForecastStack
│   └── package.json cdk.json …
└── python/                      # abre ESTA carpeta en VS Code
    ├── .vscode/
    │   ├── settings.json        #   ruff, mypy, autoDocstring numpy
    │   └── launch.json          #   una configuración por microservicio
    ├── .env.example             # variables de entorno (sin valores)
    ├── pyproject.toml           # reglas de ruff y mypy del equipo
    ├── requirements.txt         # entorno local: lib-python-* fijadas por SHA, boto3, herramientas
    ├── internal-services/       # microservicios internos
    └── consumable-services/     # microservicios que consumen otros (APIs)
```

Un proyecto puede tener una o las dos carpetas de servicios. `create-project`
crea la elegida; `create-microservice` crea la otra si hace falta.

## Microservicio

```
python/<tipo>/<microservicio>/
├── events/
│   └── <microservicio>.json     # evento de prueba para correr en local
├── layers/
│   └── requirements.txt         # dependencias que van en la layer de la Lambda
└── src/
    ├── handler.py               # punto de entrada: run(event, stage)
    ├── service/
    │   ├── __init__.py
    │   └── main.py              # lógica de negocio: main(event)
    └── database/                # opcional: conexiones a Redshift / Aurora
        └── __init__.py
```

### Correrlo en local

```bash
cd python/<tipo>/<microservicio>
python3 src/handler.py <microservicio>     # lee events/<microservicio>.json
```

O en VS Code (con `python/` abierta): Run and Debug → configuración
`<microservicio>`.

### Dependencias: dónde va cada una

| Archivo | Para qué |
|---|---|
| `python/requirements.txt` | Tu entorno local de desarrollo (todo el proyecto) |
| `<microservicio>/layers/requirements.txt` | Lo que la Lambda necesita en producción |

Una librería que use el microservicio va en `layers/requirements.txt`. Si
también la necesitas para probar en local y no está en `python/requirements.txt`,
agrégala ahí con el mismo SHA.

## Diferencias con `melonn-python-cli`

seedflow crea la misma estructura, con estos cambios:

- `iac/` ya no queda con un repo git anidado (`cdk init --generate-only` +
  `npm install`).
- El stack de CDK lleva el nombre del proyecto (`StockForecastStack`) en vez
  del genérico `IacStack`, así dos proyectos no chocan al desplegarse en la
  misma cuenta y región.
- El handler busca el evento en `../events/` (en el CLI la ruta tenía un nivel
  de más y no funcionaba).
- `handler.py` llama a `service.main.main(event)`.
- Al correrlo en local, `handler.py` carga `python/.env` (con `python-dotenv`), y
  la configuración de VS Code usa `envFile` con ese mismo archivo.
- `launch.json` se actualiza con cada microservicio que se crea o se borra.
- Los nombres se validan: no pueden salirse de `projects/` ni usar nombres
  reservados de Windows (`CON`, `NUL`…). Tampoco opera a través de enlaces
  simbólicos.
- Los comandos que borran exigen `--yes` y tienen `--dry-run` para ver antes
  qué se borraría.
- `launch.json` solo cambia la configuración del microservicio: lo demás que
  tenga el archivo queda igual.
- La carpeta de servicios nueva lleva un `.gitkeep`, para que git la guarde
  aunque esté vacía.
- No sobrescribe: si el proyecto o el microservicio ya existe, se detiene.
- Si algo falla a mitad de camino, deshace lo que creó y deja la raíz como
  estaba; si no puede, lo dice y lista lo que quedó.
