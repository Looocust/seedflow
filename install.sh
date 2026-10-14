#!/usr/bin/env bash
# Instalación manual (sin plugin): copia seedflow a ~/.claude/seedflow y las
# skills a ~/.claude/skills/. La vía recomendada es el marketplace — ver README.md.
set -euo pipefail
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/plugins/seedflow"
DEST="${CLAUDE_HOME:-$HOME/.claude}"
ROOT="$DEST/seedflow"

# Script, plantillas y referencias: las skills los buscan en $ROOT.
rm -rf "$ROOT"; mkdir -p "$ROOT"
cp -R "$SRC/scripts" "$SRC/templates" "$SRC/references" "$ROOT/"
echo "  motor  $ROOT"

mkdir -p "$DEST/skills"
for skill in "$SRC"/skills/*/; do
  name="$(basename "$skill")"
  rm -rf "$DEST/skills/$name"; cp -R "$skill" "$DEST/skills/$name"
  # Sin plugin no existe ${CLAUDE_PLUGIN_ROOT}: se reemplaza por la ruta real.
  sed -i.bak "s|\${CLAUDE_PLUGIN_ROOT}|$ROOT|g" "$DEST/skills/$name/SKILL.md"
  rm -f "$DEST/skills/$name/SKILL.md.bak"
  echo "  skill  $name"
done

cat <<MSG

Listo. Sin prefijo de plugin, los comandos son:

  /crear-proyecto        nuevo proyecto (deployment-scripts, iac con CDK, python)
  /crear-microservicio   nuevo microservicio dentro de un proyecto
  /eliminar              borrar un proyecto o un microservicio

Párate en la carpeta raíz del repo (data-hub, ds-core…) y empieza con:  /crear-proyecto
MSG
