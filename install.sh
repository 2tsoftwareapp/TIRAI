#!/usr/bin/env sh
# TIRAI installer for macOS and Linux.
#   curl -fsSL https://raw.githubusercontent.com/2tsoftwareapp/TIRAI/main/install.sh | sh
#   curl -fsSL .../install.sh | sh -s -- --yes --agent claude     # other args go to `tirai setup`
#   sh install.sh --binary | --source                             # force one install method
# Methods: --binary downloads the prebuilt executable from GitHub Releases (no Python needed);
#          --source builds from source into a virtualenv; uses Python >= 3.10 if present, otherwise
#          downloads uv + a private Python 3.12 into TIRAI_HOME (system Python is never touched).
#          Default (auto): binary when a release asset exists for this OS/arch, otherwise source.
# Env: TIRAI_INSTALL_MODE (auto|binary|source), TIRAI_VERSION (release tag, default latest),
#      TIRAI_BINARY (local path or URL of a prebuilt executable), TIRAI_REPO, TIRAI_REF (branch/tag for source),
#      TIRAI_SOURCE (local checkout or archive URL), TIRAI_HOME (default ~/.tirai),
#      TIRAI_BIN_DIR (default ~/.local/bin), TIRAI_EXTRAS (default postgres), TIRAI_NO_SETUP=1 to only install.
set -eu

MODE="${TIRAI_INSTALL_MODE:-auto}"
for a; do
  shift
  case "$a" in
    --binary) MODE=binary ;;
    --source) MODE=source ;;
    *) set -- "$@" "$a" ;;
  esac
done

REPO="${TIRAI_REPO:-2tsoftwareapp/TIRAI}"
REF="${TIRAI_REF:-main}"
SOURCE="${TIRAI_SOURCE:-https://github.com/${REPO}/archive/${REF}.zip}"
TIRAI_HOME="${TIRAI_HOME:-$HOME/.tirai}"
BIN_DIR="${TIRAI_BIN_DIR:-$HOME/.local/bin}"
EXTRAS="${TIRAI_EXTRAS:-postgres,excel}"

log() { printf '[tirai] %s\n' "$*"; }
die() { printf '[tirai] ERROR: %s\n' "$*" >&2; exit 1; }

fetch() { # fetch URL DEST
  if command -v curl >/dev/null 2>&1; then curl -fsSL "$1" -o "$2"
  elif command -v wget >/dev/null 2>&1; then wget -q "$1" -O "$2"
  else return 1; fi
}

sha256_of() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | cut -d' ' -f1
  else shasum -a 256 "$1" | cut -d' ' -f1; fi
}

asset_name() {
  case "$(uname -s)" in Darwin) os=macos ;; Linux) os=linux ;; *) return 1 ;; esac
  case "$(uname -m)" in x86_64|amd64) arch=x64 ;; arm64|aarch64) arch=arm64 ;; *) return 1 ;; esac
  printf 'tirai-%s-%s' "$os" "$arch"
}

install_binary() {
  dest="$TIRAI_HOME/bin/tirai"
  mkdir -p "$TIRAI_HOME/bin"
  if [ -n "${TIRAI_BINARY:-}" ] && [ -f "${TIRAI_BINARY}" ]; then
    log "Using prebuilt binary ${TIRAI_BINARY}"
    cp "$TIRAI_BINARY" "$dest.tmp"
  else
    if [ -n "${TIRAI_BINARY:-}" ]; then
      url="$TIRAI_BINARY"
    else
      asset="$(asset_name)" || { log "No prebuilt binary for $(uname -s)/$(uname -m)"; return 1; }
      if [ -n "${TIRAI_VERSION:-}" ]; then base="https://github.com/${REPO}/releases/download/${TIRAI_VERSION}"
      else base="https://github.com/${REPO}/releases/latest/download"; fi
      url="$base/$asset"
    fi
    log "Downloading ${url}"
    fetch "$url" "$dest.tmp" 2>/dev/null || { rm -f "$dest.tmp"; log "Download failed: ${url}"; return 1; }
    if fetch "$url.sha256" "$dest.sha256" 2>/dev/null; then
      [ "$(cut -d' ' -f1 < "$dest.sha256")" = "$(sha256_of "$dest.tmp")" ] || { rm -f "$dest.tmp"; die "Checksum mismatch for ${url}"; }
      log "Checksum OK"
    fi
    rm -f "$dest.sha256"
  fi
  chmod +x "$dest.tmp"
  "$dest.tmp" --version >/dev/null 2>&1 || { rm -f "$dest.tmp"; log "Prebuilt binary does not run on this machine"; return 1; }
  mv -f "$dest.tmp" "$dest"
  TIRAI_EXE="$dest"
}

find_python() {
  for c in python3.13 python3.12 python3.11 python3.10 python3 python; do
    if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys, venv, ensurepip; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; then
      printf '%s' "$c"; return 0
    fi
  done
  return 1
}

# No usable system Python: fetch uv and let it download a private Python into TIRAI_HOME.
ensure_uv() {
  UV="$(command -v uv 2>/dev/null || true)"
  [ -n "$UV" ] && return 0
  UV="$TIRAI_HOME/uv/uv"
  [ -x "$UV" ] && return 0
  log "No Python >= 3.10 found; installing uv into ${TIRAI_HOME}/uv to provide one"
  mkdir -p "$TIRAI_HOME/uv"
  fetch https://astral.sh/uv/install.sh "$TIRAI_HOME/uv/install.sh" || die "Could not download uv; install Python >= 3.10 and retry."
  UV_INSTALL_DIR="$TIRAI_HOME/uv" UV_NO_MODIFY_PATH=1 sh "$TIRAI_HOME/uv/install.sh" >/dev/null 2>&1 \
    || die "uv install failed; install Python >= 3.10 and retry."
  rm -f "$TIRAI_HOME/uv/install.sh"
}

install_source() {
  src="$SOURCE"
  if [ -d "$src" ]; then src="file://$(cd "$src" && pwd)"; fi
  mkdir -p "$TIRAI_HOME"
  rm -rf "$TIRAI_HOME/venv"
  VPY="$TIRAI_HOME/venv/bin/python"
  if PY="$(find_python)"; then
    log "Python: $("$PY" --version 2>&1) ($PY)"
    "$PY" -m venv "$TIRAI_HOME/venv"
    "$VPY" -m pip install --quiet --upgrade pip
    log "Building tirai[${EXTRAS}] from ${src}"
    "$VPY" -m pip install --quiet --upgrade "tirai[${EXTRAS}] @ ${src}"
  else
    ensure_uv
    export UV_PYTHON_INSTALL_DIR="$TIRAI_HOME/python" RUST_LOG=warn
    "$UV" venv --quiet --python 3.12 "$TIRAI_HOME/venv" || die "uv could not create a Python 3.12 virtualenv."
    log "Python: $("$VPY" --version 2>&1) (uv-managed, ${UV_PYTHON_INSTALL_DIR})"
    log "Building tirai[${EXTRAS}] from ${src}"
    "$UV" pip install --quiet --python "$VPY" "tirai[${EXTRAS}] @ ${src}"
  fi
  TIRAI_EXE="$TIRAI_HOME/venv/bin/tirai"
}

TIRAI_EXE=""
case "$MODE" in
  binary) install_binary || die "Binary install failed (try --source)." ;;
  source) install_source ;;
  auto) install_binary || { log "Falling back to building from source"; install_source; } ;;
  *) die "Unknown TIRAI_INSTALL_MODE: $MODE (auto|binary|source)" ;;
esac

mkdir -p "$BIN_DIR"
ln -sf "$TIRAI_EXE" "$BIN_DIR/tirai"
log "Linked ${BIN_DIR}/tirai -> ${TIRAI_EXE}"

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
