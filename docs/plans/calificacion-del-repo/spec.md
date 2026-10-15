---
plan: calificacion-del-repo
titulo: Calificación de qué tan organizado está el repo
estado: aprobado          # borrador | aprobado
creado: 2026-10-14
aprobado_en: 2026-10-14
validado_con: [auditoria, escenarios]   # auditoria | escenarios | spec-check
spec_check:               # LISTO | HUECOS | BLOQUEADO
---

# Calificación de qué tan organizado está el repo

## Resumen

seedflow califica de 0 a 100 qué tan organizado está un repo de Melonn (data-hub,
ds-core…) en cuatro categorías: estructura, calidad de código, dependencias, y
seguridad e higiene. Cada proyecto de `projects/` tiene su nota y el repo tiene
la nota promedio. Cada punto que se descuenta viene con el porqué y cómo
arreglarlo. La nota aparece solo cuando se usa seedflow: una línea de resumen
al terminar de crear o eliminar algo, y el reporte completo cuando se pide.
Después del reporte, seedflow ofrece hacer los arreglos mecánicos y seguros;
nada cambia sin un sí explícito.

## Usuario

- **Quien mantiene el estándar (tú):** ve qué proyectos se están
  desordenando y qué tienen mal.
- **El equipo que usa seedflow:** ve cómo está el repo cuando crea o elimina
  algo, y decide si pide el detalle o acepta arreglos. Lo que haga con la
  información depende de cada persona.
- Nivel técnico: desarrolladores Python que usan Claude Code.
- Frecuencia: cada vez que se usa seedflow. No hace falta verlo todo el tiempo.

## Problema

Hoy nadie sabe qué tan desviado está cada proyecto del estándar sin revisarlo a
mano. Los proyectos creados con el CLI anterior arrastran problemas que nadie
ve: el handler con la ruta de eventos rota, un `.git` anidado en `iac/`, el
stack `IacStack` repetido, librerías sin versión fijada. Y nada avisa si
alguien commitea un `.env` o arma queries con valores del evento.

## Éxito medible

- [ ] Un proyecto recién creado con seedflow, sin microservicios y con uno,
      saca 100 en estructura, dependencias y seguridad e higiene, en un repo
      cuyo `.gitignore` ignora `.env`.
- [ ] La misma copia del repo, sin cambios, da exactamente la misma nota en dos
      corridas seguidas.
- [ ] La línea de resumen aparece al final de `crear-proyecto`,
      `crear-microservicio` y `eliminar`, y el cálculo tarda menos de 2
      segundos en un repo con 20 proyectos y 100 microservicios.
- [ ] Cada descuento del reporte nombra: proyecto, ruta, regla, puntos
      descontados, por qué importa, cómo arreglarlo y si seedflow puede hacerlo
      solo.
- [ ] Después de aceptar un arreglo, calificar de nuevo muestra ese hallazgo
      resuelto y la nota de su categoría sube en los puntos que descontaba.
- [ ] Si el usuario no acepta ningún arreglo, `git status` queda igual que
      antes de calificar.
- [ ] Con `ruff` y `mypy` instalados por seedflow, dos personas con la misma
      copia del repo obtienen la misma nota de calidad de código.

## Alcance

- Nota de 0 a 100 por categoría, por proyecto y del repo.
- Las cuatro categorías: estructura, calidad de código, dependencias, y
  seguridad e higiene.
- Semáforo: 🟢 75 o más · 🟡 de 50 a 74 · 🔴 menos de 50.
- Línea de resumen al terminar `crear-proyecto`, `crear-microservicio` y
  `eliminar`. Usa solo las reglas rápidas (sin calidad de código) y lo dice.
- Reporte completo a pedido (`/seedflow:revisar` o pidiéndolo con palabras):
  las cuatro categorías, nota por proyecto, cada hallazgo con su porqué y cómo
  arreglarlo.
- Después del reporte, ofrecer los arreglos mecánicos (ver "Arreglos") y
  aplicarlos solo con un sí.
- Para los problemas que no son mecánicos (`.env` commiteado, `iac/.git`
  anidado), ofrecer opciones para resolverlos, cada una con su confirmación.
- Instalar lo necesario para evaluar calidad de código (`ruff` y `mypy`) en un
  entorno propio de seedflow, en las versiones que fija el equipo.
- Observaciones de Claude (lo que ninguna regla automática puede juzgar, como
  lógica de negocio metida en el handler): van en el reporte, aparte, y no
  afectan la nota.
- Los proyectos creados con el CLI anterior se califican igual que los demás:
  una nota baja está bien siempre que diga por qué.
- Documentar en el README cómo se calcula la nota, las reglas y lo que queda
  fuera de alcance.

## Fuera de alcance

- **Sin historial:** no guarda notas anteriores ni muestra si subieron o
  bajaron.
- **No bloquea nada:** ni commits, ni CI, ni la creación de proyectos. Solo
  informa.
- **Sin revisar `iac/` ni scripts por dentro:** no revisa el TypeScript de
  `iac/` ni el contenido de `deployment-scripts/`; solo que existan.
- **Solo `projects/`:** no revisa nada fuera de esa carpeta, salvo el
  `.gitignore` de la raíz.
- **Arreglos solo mecánicos:** nunca cambian lógica de negocio, queries,
  versiones de dependencias ni historial de git.
- **Sin aviso al abrir Claude Code:** no hay hook automático al iniciar sesión.

Todo esto también va en el README.

## Restricciones

| Restricción | Por qué existe |
|---|---|
| El script sigue usando solo la librería estándar de Python 3.8+ | Es lo que hoy permite instalar seedflow sin dependencias |
| La línea de resumen no corre `ruff`, `mypy` ni consultas de red | Tiene que salir en menos de 2 s y no depender de herramientas instaladas |
| La nota tiene que ser reproducible | Si cambia entre corridas sin cambios en el repo, nadie confía en ella. Por eso las observaciones de Claude no la afectan y `ruff`/`mypy` van en versiones fijas |
| `ruff` y `mypy` se instalan en un entorno propio de seedflow, fuera del repo | No tocar los entornos del usuario ni del proyecto |
| Calificar es de solo lectura | Los arreglos son un paso aparte y explícito |
| Mismo patrón que el resto de seedflow: reglas en el script, juicio en la skill | Lo determinista se testea; Claude completa lo que no se puede automatizar |

## Datos

- **Lee:** `projects/**`, el `.gitignore` de la raíz, `git ls-files` (para
  saber qué está commiteado) y, en el reporte completo, la salida de `ruff` y
  `mypy`.
- **Escribe:** nada al calificar. Al aplicar un arreglo aceptado, solo los
  archivos de ese arreglo.
- **No se puede perder nunca:** código, historial de git ni archivos del
  usuario. Ningún arreglo borra.

## Términos

| Término | Qué significa exactamente |
|---|---|
| Proyecto | Cada carpeta directa dentro de `projects/` |
| Microservicio | Cada carpeta dentro de `projects/<p>/python/internal-services/` o `.../consumable-services/` |
| Hallazgo | Una regla incumplida en un lugar concreto (proyecto + ruta) |
| Gravedad | Crítico (−25), importante (−10) o menor (−3): los puntos que descuenta un hallazgo. Los errores de `ruff` y `mypy` descuentan por cantidad (ver Reglas) |
| Observación | Algo que Claude nota al revisar y que ninguna regla automática puede juzgar. Va en el reporte, no afecta la nota |
| Nota de categoría | 100 menos la suma de los descuentos de sus hallazgos en ese proyecto, mínimo 0 |
| Nota del proyecto | Promedio de sus categorías evaluadas, con el mismo peso cada una |
| Nota del repo | Promedio de las notas de sus proyectos |
| Categoría no evaluada | Una categoría que no se pudo calcular (p. ej. calidad de código sin `ruff`); se muestra como "no evaluada" y no entra en el promedio |
| Reglas rápidas | Las de estructura, dependencias y seguridad e higiene que no necesitan herramientas externas ni red |
| Arreglo mecánico | Un cambio que no requiere decidir nada: crear un archivo que falta con contenido fijo, agregar una entrada a `launch.json`, aplicar `ruff format` |

## Reglas (versión 1)

Propuesta inicial; su gravedad se ajusta en la validación.

### Estructura

| Regla | Gravedad | Arreglo mecánico |
|---|---|---|
| Falta `deployment-scripts/`, `iac/` o `python/` en el proyecto | Importante | No |
| El microservicio no tiene `events/`, `layers/requirements.txt`, `src/handler.py` o `src/service/` | Importante | No |
| Falta `events/<microservicio>.json` | Menor | Sí: crea `{}` |
| El microservicio no tiene entrada en `python/.vscode/launch.json`, o hay una entrada a un microservicio que no existe | Menor | Sí |
| El handler busca el evento en `../../events` (la ruta rota del CLI anterior) | Importante | Sí: cambia a `../events` |
| Hay un repo git anidado en `iac/.git` | Importante | No: borrarlo pierde ese historial; se recomienda |
| El stack de CDK se llama `IacStack` | Menor | No |
| Un nombre de proyecto o microservicio no cumple las reglas de seedflow | Menor | No |

### Calidad de código (solo en el reporte completo)

| Regla | Gravedad | Arreglo mecánico |
|---|---|---|
| `ruff check` con errores, con las reglas del proyecto | −2 por error, máximo −30 por microservicio | No (algunos los arregla `ruff --fix`; se ofrece como arreglo aparte) |
| `ruff format` cambiaría archivos | Menor (uno por microservicio) | Sí |
| `mypy` con errores | −2 por error, máximo −30 por microservicio | No |
| El microservicio tiene `TODO` pendientes | Menor (uno por microservicio) | No |

### Dependencias

| Regla | Gravedad | Arreglo mecánico |
|---|---|---|
| Una `lib-python-*` sin `@<sha>` o con `@main` | Importante | No |
| La misma librería con SHAs distintos entre `layers/requirements.txt` y `python/requirements.txt` | Menor | No |
| El código importa una `lib-python-*` que no está en el `layers/requirements.txt` de su microservicio | Importante | No |

### Seguridad e higiene

| Regla | Gravedad | Arreglo mecánico |
|---|---|---|
| Un `.env` (no `.env.example`) está commiteado | Crítico | No: sacarlo del historial requiere decisión |
| El `.gitignore` no ignora `.env` | Importante, en **cada** proyecto (todos quedan expuestos) | Sí: agrega la línea |
| Texto con forma de credencial en el código (`AKIA…`, `password = "…"`) | Crítico | No |
| `read`/`execute_query`/`write` con una query armada con `format()` o f-string | Importante | No |

## Arreglos

- Se ofrecen al final del reporte, agrupados, con la lista exacta de archivos
  que tocaría cada uno.
- Los problemas no mecánicos se ofrecen como opciones, cada una con su
  confirmación aparte:
  - `.env` commiteado: dejar de seguirlo (`git rm --cached`) y agregarlo al
    `.gitignore`, más la recomendación de rotar las credenciales que tenía.
    Reescribir el historial de git queda fuera de alcance.
  - `iac/.git` anidado: moverlo a un respaldo fuera del repo, o borrarlo si el
    usuario confirma que no necesita ese historial.
- Solo se aplican con un sí a esa pregunta, en esa conversación.
- Después de aplicarlos, se califica de nuevo y se muestra la nota nueva.

## Casos borde

- La carpeta no tiene `projects/` → no hay nota; dice que no encontró
  proyectos y en qué carpeta buscó.
- Un proyecto sin microservicios → se califica igual (estructura del
  proyecto, higiene).
- `ruff` o `mypy` no están instalados → seedflow los instala en su entorno
  propio y sigue. Si no puede (sin internet, sin pip), calidad de código queda
  "no evaluada" con el motivo.
- La carpeta no es un repo git → las reglas que dependen de git quedan "no
  evaluadas".
- `launch.json` con comentarios → la regla de `launch.json` queda "no
  evaluada" para ese proyecto, sin descontar.

## Escenarios validados

| Escenario | Qué debe pasar |
|---|---|
| Toda la lógica está en `handler.py` y `service/main.py` está vacío | Va como observación en el reporte; no descuenta |
| El `.gitignore` del repo no ignora `.env` y se crea un proyecto nuevo | Descuenta en seguridad e higiene de todos los proyectos: un `.env` no se puede subir |
| Un proyecto viejo tiene `iac/.git` anidado y un `.env` commiteado, y el usuario pide aplicar todos los arreglos | No se aplican como mecánicos; se ofrecen opciones para resolverlos, cada una con su confirmación |
| Alguien pide el reporte sin `ruff` ni `mypy` | seedflow los instala (versiones del equipo, entorno propio) para hacer la evaluación completa |
| Un microservicio con 40 errores de `ruff` y otro con 1 | El descuento crece con la cantidad: −2 por error, máximo −30 por microservicio |

## Dependencias externas

| Dependencia | ¿Confirmada? | Quién la provee |
|---|---|---|
| `git` instalado | Sí (ya es requisito recomendado) | Usuario |
| `ruff` y `mypy` para calidad de código | Sí: seedflow los instala en su entorno propio | PyPI (requiere internet la primera vez) |

## Definición de terminado

- [ ] Tests automatizados que prueban el comportamiento (no la implementación)
- [ ] Suite completa en verde
- [ ] `tests/mutantes.py` actualizado con una falla por cada regla nueva, todas
      detectadas
- [ ] Revisado y aprobado por un agente distinto al que escribió el código
- [ ] README actualizado: cómo se calcula la nota, las reglas y lo que queda
      fuera de alcance
- [ ] Commit propio y descriptivo

## Preguntas abiertas

Ninguna. Resueltas en la validación:

- [x] Lo que solo Claude puede juzgar → observaciones, sin afectar la nota.
- [x] El `.gitignore` sin `.env` → descuenta en cada proyecto.
