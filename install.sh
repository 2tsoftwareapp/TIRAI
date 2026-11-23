#!/usr/bin/env sh
# TIRAI installer for macOS and Linux.
#   curl -fsSL https://raw.githubusercontent.com/2tsoftwareapp/TIRAI/main/install.sh | sh
#   curl -fsSL .../install.sh | sh -s -- --yes --agent claude     # args go to `tirai setup`
# Env: TIRAI_REPO, TIRAI_REF (branch/tag), TIRAI_SOURCE (local checkout or archive URL),
#      TIRAI_HOME (default ~/.tirai), TIRAI_BIN_DIR (default ~/.local/bin), TIRAI_EXTRAS (default postgres),
#      TIRAI_NO_SETUP=1 to only install the CLI.
set -eu

REPO="${TIRAI_REPO:-2tsoftwareapp/TIRAI}"
REF="${TIRAI_REF:-main}"
SOURCE="${TIRAI_SOURCE:-https://github.com/${REPO}/archive/${REF}.zip}"
TIRAI_HOME="${TIRAI_HOME:-$HOME/.tirai}"
BIN_DIR="${TIRAI_BIN_DIR:-$HOME/.local/bin}"
EXTRAS="${TIRAI_EXTRAS:-postgres}"

log() { printf '[tirai] %s\n' "$*"; }
die() { printf '[tirai] ERROR: %s\n' "$*" >&2; exit 1; }

PY=""
for c in python3.13 python3.12 python3.11 python3.10 python3 python; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; then
    PY="$c"; break
  fi
done
[ -n "$PY" ] || die "Python >= 3.10 is required (macOS: brew install python; Debian/Ubuntu: sudo apt install python3 python3-venv)."
"$PY" -c 'import venv, ensurepip' 2>/dev/null || die "Python venv/ensurepip missing (Debian/Ubuntu: sudo apt install python3-venv)."

if [ -d "$SOURCE" ]; then
  SOURCE="file://$(cd "$SOURCE" && pwd)"
fi

log "Python: $("$PY" --version 2>&1) ($PY)"
log "Creating virtualenv in ${TIRAI_HOME}/venv"
mkdir -p "$TIRAI_HOME"
"$PY" -m venv "$TIRAI_HOME/venv"
VPY="$TIRAI_HOME/venv/bin/python"
"$VPY" -m pip install --quiet --upgrade pip
log "Installing tirai[${EXTRAS}] from ${SOURCE}"
"$VPY" -m pip install --quiet --upgrade "tirai[${EXTRAS}] @ ${SOURCE}"

mkdir -p "$BIN_DIR"
ln -sf "$TIRAI_HOME/venv/bin/tirai" "$BIN_DIR/tirai"
log "Linked ${BIN_DIR}/tirai"

case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *)
    line="export PATH=\"${BIN_DIR}:\$PATH\""
    for profile in "$HOME/.zshrc" "$HOME/.bashrc" "$HOME/.profile"; do
      if [ -f "$profile" ] && ! grep -Fq "$BIN_DIR" "$profile"; then
        printf '\n# tirai\n%s\n' "$line" >> "$profile"
        log "Added ${BIN_DIR} to PATH in ${profile} (open a new terminal)"
      fi
    done
    PATH="$BIN_DIR:$PATH"; export PATH
    ;;
esac

"$BIN_DIR/tirai" --version
if [ "${TIRAI_NO_SETUP:-0}" != "1" ]; then
  # When piped (curl | sh) stdin is the script, so read prompts from the terminal.
  if [ -t 0 ] || ! (: < /dev/tty) 2>/dev/null; then
    "$BIN_DIR/tirai" setup "$@"
  else
    "$BIN_DIR/tirai" setup "$@" < /dev/tty
  fi
fi
