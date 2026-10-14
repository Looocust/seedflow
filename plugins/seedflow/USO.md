# Cómo se usa

Guía práctica: qué escribes, qué pasa y qué decides tú.

Las skills se activan solas cuando lo pides con tus palabras ("crea un
microservicio que lea de Redshift"), pero escribir el comando es más directo.
Instalado como plugin, los comandos llevan prefijo (`/seedflow:crear-proyecto`).
Esta guía usa la forma corta.

> **Siempre desde la carpeta raíz del repo** (data-hub, ds-core…). seedflow te
> dice dónde va a crear las cosas antes de hacerlo, pero abrir Claude Code en la
> carpeta correcta te ahorra el paso.

---

## Crear un proyecto

```
/crear-proyecto warehouses-operation
```

1. Revisa dónde estás parado y si tienes AWS CDK instalado.
2. Te pregunta lo mismo que el CLI: tipo de carpeta de servicios
   (`internal-services` o `consumable-services`) y si quieres crear el primer
   microservicio ya.
3. Te muestra un resumen y espera tu sí.
4. Crea la estructura y corre `cdk init` (uno o dos minutos).
5. Si dijiste que sí al microservicio, sigue con las preguntas del microservicio.

Si no tienes CDK, te ofrece crear el proyecto con `iac/` vacía.

---

## Crear un microservicio

```
/crear-microservicio orders-sync
```

O con más contexto, que ahorra preguntas:

```
/crear-microservicio orders-sync en warehouses-operation: lee pedidos de Redshift,
los sube a S3 en parquet y avisa a Slack si falla
```

Preguntas:

| Pregunta | Igual que el CLI |
|---|---|
| Proyecto | ✔ (te muestra los que existen) |
| `internal-services` o `consumable-services` | ✔ |
| Nombre | ✔ |
| ¿Carpeta `database`? | ✔ |
| ¿Con qué datos trabaja? (Redshift, Aurora, S3, DynamoDB…) | nueva |
| ¿Qué más necesita? (Slack, Google Chat, Melogger, validar el evento) | nueva |

Después de crear la estructura, escribe:

- `layers/requirements.txt` con las librerías elegidas, fijadas por SHA.
- `src/service/main.py` con las clases instanciadas y `TODO` donde va tu lógica.
- `src/database/` con la conexión, si aplica.
- `events/<nombre>.json` con un evento de ejemplo.
- Las variables nuevas en `python/.env.example`.

No inventa queries, tablas ni buckets: si no los dijiste, quedan como `TODO`.

Para probarlo:

```bash
cd projects/<proyecto>/python/<tipo>/<nombre>
python3 src/handler.py <nombre>
```

O en VS Code, con la carpeta `python/` abierta: Run and Debug → `<nombre>`.

---

## Eliminar

```
/eliminar microservicio orders-sync
/eliminar proyecto warehouses-operation
```

Antes de borrar te muestra la ruta exacta, cuántos archivos tiene y lo que no
se puede recuperar: cambios sin commitear, archivos que git nunca vio y
archivos ignorados como `.env`. Solo borra con un sí explícito a esa pregunta;
un "ya lo confirmé" dentro del mismo pedido no cuenta.

---

## Preguntas frecuentes

**¿Puedo seguir usando `melonn-python-cli`?** No: hoy falla al instalarse y al
arrancar. seedflow crea la misma estructura y corrige sus bugs (ver
`references/estructura.md`, sección "Diferencias").

**Quiero cambiar lo que se genera.** Edita `templates/`: es lo que se copia tal
cual. Si cambias la estructura, actualiza también `references/estructura.md`.

**El proyecto quedó a medias.** No debería: si algo falla, el script deshace lo
que creó. Si no pudo deshacerlo todo, lo dice y lista las rutas que quedaron:
bórralas a mano y vuelve a empezar.

**¿Dónde está la referencia completa?** En el README del repo: instalación,
guía de prueba, todos los comandos del script con sus opciones, errores comunes
y cómo actualizar.
