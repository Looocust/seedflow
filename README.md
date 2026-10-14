# seedflow

Plugin de Claude Code para crear proyectos y microservicios con la estructura de
Melonn. Es el reemplazo de `melonn-python-cli`: hace las mismas preguntas, pero
en el chat, y además deja el código conectado a las librerías `lib-python-*`.

```
/crear-proyecto → /crear-microservicio → (a programar)      /eliminar
 estructura        estructura + esqueleto                    con confirmación
```

Cómo está armado:

- **Un script** (`scripts/seedflow.py`) crea las carpetas y archivos. Es
  determinista: el mismo comando da la misma estructura para todo el equipo.
  Solo usa la librería estándar de Python, así que no hay nada que instalar.
- **Las skills** hacen las preguntas, llaman al script y después escriben lo
  que el script no puede saber: el handler conectado al servicio, los imports
  correctos de cada librería, el evento de ejemplo y las variables de entorno.

---

## Requisitos

| Requisito | Necesidad |
|---|---|
| Claude Code | Obligatorio |
| Python 3.8+ | Obligatorio, para correr el script (los proyectos generados usan 3.12) |
| Node.js + AWS CDK (`npm install -g aws-cdk`) | Para inicializar `iac/`. Sin CDK, el proyecto se crea igual con `iac/` vacía |
| git | Recomendado: `/eliminar` lo usa para avisar de cambios sin commitear |
| Acceso a `we-are-melonn` en GitHub | Solo para instalar las `lib-python-*` en los proyectos generados, no para el plugin |

---

## Instalación

### 1. Desde GitHub (recomendada)

```bash
claude plugin marketplace add Looocust/seedflow
claude plugin install seedflow@looocust
```

`Looocust/seedflow` es el repositorio; `looocust` es el nombre del marketplace
declarado en `marketplace.json`. El id de instalación es `<plugin>@<marketplace>`.

Para dejarlo fijo solo en un repo (por ejemplo, data-hub):

```bash
claude plugin install seedflow@looocust --scope project
```

### 2. Como marketplace local

Para trabajar sobre las skills sin publicar cambios:

```bash
git clone https://github.com/Looocust/seedflow.git
# desde la carpeta PADRE de seedflow/
claude plugin validate ./seedflow
claude plugin marketplace add ./seedflow
claude plugin install seedflow@looocust
```

Editas una skill o una plantilla y aplicas el cambio con `/reload-plugins`, sin
reinstalar.

### 3. Como skills independientes

Sin plugin:

```bash
./install.sh
```

Copia el script, las plantillas y las referencias a `~/.claude/seedflow/`, y las
skills a `~/.claude/skills/`. Los comandos quedan sin prefijo (`/crear-proyecto`).

### Verificación

```bash
claude plugin list                 # seedflow@looocust  Status: ✔ enabled
claude plugin details seedflow     # Skills (3)
```

Instalado como plugin, los comandos llevan prefijo: `/seedflow:crear-proyecto`.
La forma corta `/crear-proyecto` funciona mientras ningún otro comando use ese
nombre.

---

## Actualización

Sube los cambios **incluyendo el campo `version` de
`plugins/seedflow/.claude-plugin/plugin.json`**, y luego:

```bash
claude plugin marketplace update looocust
claude plugin update seedflow@looocust
```

`claude plugin update` compara el string `version`: si no lo subes, responde
`already at the latest version` y sigue usando la copia anterior.

---

## El script sin Claude

Funciona solo, desde la carpeta raíz del repo:

```bash
S=~/.claude/plugins/cache/looocust/seedflow/<versión>/scripts/seedflow.py   # o la ruta de tu clon

python3 $S status
python3 $S create-project mi-proyecto --service-type internal-services
python3 $S create-microservice mi-servicio --project mi-proyecto --service-type internal-services --database
python3 $S delete-microservice mi-servicio --project mi-proyecto --service-type internal-services --dry-run
python3 $S delete-microservice mi-servicio --project mi-proyecto --service-type internal-services --yes
python3 $S delete-project mi-proyecto --yes
```

No hace preguntas: todo va por argumentos. Los comandos que borran exigen
`--yes`, y con `--dry-run` muestran qué se borraría sin borrar nada.

Lo que garantiza:

- Nunca opera fuera de `<raíz>/projects/` ni a través de enlaces simbólicos.
- Nunca sobrescribe: si lo que va a crear ya existe, se detiene.
- Si una creación falla a mitad de camino, deja la raíz como estaba. Si no
  puede, lo dice y lista lo que quedó.
- En `launch.json` solo toca la configuración del microservicio.

Lo que no garantiza:

- **Dos comandos de seedflow a la vez sobre el mismo proyecto.** No hay
  bloqueo: si corren en paralelo, uno puede perder la entrada del otro en
  `launch.json`. El rollback nunca borra una carpeta contenedora que tenga
  algo ajeno, pero no corras dos comandos a la vez.
- **Otro proceso cambiando carpetas por enlaces mientras el comando corre.**
  Las rutas se verifican antes de crear o borrar, no en cada operación. Es una
  herramienta local: quien puede hacer eso en tu repo ya puede borrar lo que
  quiera.

---

## Tests

Solo librería estándar, desde la raíz del repo:

```bash
python3 -m unittest discover -s tests -v   # la suite
python3 tests/mutantes.py                  # comprueba que la suite detecta fallas reales
```

`mutantes.py` mete una falla por vez en una copia del script (sin validar
nombres, sin `--yes`, sin rollback…) y verifica que algún test se ponga en rojo.
Si agregas una protección nueva, agrega también su falla a la lista.

Los tests que usan `cdk`/`npm` falsos o enlaces simbólicos se saltan en Windows;
el script no se ha probado todavía en Windows.

---

## Estructura del repositorio

```
seedflow/                               # raíz del marketplace
├── .claude-plugin/marketplace.json     # marketplace: looocust
├── install.sh                          # instalación como skills independientes
├── tests/                              # suite (unittest) y mutantes.py
└── plugins/seedflow/                   # el plugin
    ├── .claude-plugin/plugin.json
    ├── USO.md
    ├── scripts/seedflow.py             # el motor
    ├── templates/                      # archivos que se copian tal cual
    │   ├── project/                    #   deployment-scripts/, python/
    │   ├── microservice/               #   events/, layers/, src/
    │   └── database/                   #   src/database/ opcional
    ├── references/
    │   ├── estructura.md               # qué va en cada carpeta
    │   └── librerias.md                # cada lib-python-*: import, firma y uso
    └── skills/
        ├── crear-proyecto/
        ├── crear-microservicio/
        └── eliminar/
```

Para cambiar lo que se genera (por ejemplo, los SHAs del `requirements.txt` o
las reglas de ruff), edita el archivo en `templates/`. No hay que tocar código.

---

## Limitaciones conocidas

- **Solo la estructura de Melonn.** Las plantillas y las referencias son las de
  data-hub y ds-core; no es un generador genérico.
- **Los SHAs de `templates/project/python/requirements.txt` se actualizan a
  mano.** Son los mismos que tenía `melonn-python-cli`.
- **El esqueleto de código no trae lógica de negocio.** Queries, tablas y
  buckets quedan como `TODO` o como variables de entorno si no se dieron.
