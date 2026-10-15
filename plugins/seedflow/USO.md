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

## Revisar qué tan ordenado está

Al terminar de crear o eliminar algo, seedflow cierra con una línea así:

```
data-hub: 92/100 🟢 · 3 cosas por mejorar (sin calidad de código) · detalle: /seedflow:revisar
```

Para ver el detalle:

```
/revisar
```

O con tus palabras: "¿qué tan ordenado está esto?", "califica el repo".

1. Califica de 0 a 100 cada proyecto en cuatro categorías: estructura, calidad
   de código, dependencias, y seguridad e higiene. 🟢 75 o más · 🟡 de 50 a 74
   · 🔴 menos de 50.
2. Por cada cosa que descuenta te dice dónde está, cuántos puntos quita, por
   qué importa y cómo arreglarlo.
3. Aparte, anota lo que nota Claude y ninguna regla mide (por ejemplo, toda la
   lógica en el handler). Eso no cambia la nota.
4. Te ofrece los arreglos que son mecánicos (crear un evento que falta,
   agregar `.env` al `.gitignore`, `ruff format`…) con los archivos que tocaría
   cada uno. Solo los aplica si dices que sí; después vuelve a calificar.

Para un `.env` commiteado o un `iac/.git` anidado no hay arreglo automático:
te da opciones y cada una pide su propia confirmación.

La primera vez instala `ruff` y `mypy` en un entorno propio de seedflow (no
toca los tuyos): necesita internet y tarda cerca de un minuto. Sin internet, la
calidad de código queda "no evaluada" y el resto se califica igual.

Calificar solo lee: si no aceptas ningún arreglo, el repo queda igual. Las
reglas completas y cómo se calcula la nota están en el README, sección
"Calificación".

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
guía de prueba, todos los comandos del script con sus opciones (también
`check` y `fix`, para calificar y arreglar sin Claude), las reglas de la
calificación, errores comunes y cómo actualizar.
