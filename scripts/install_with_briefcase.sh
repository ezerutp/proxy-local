#!/usr/bin/env bash
set -Eeuo pipefail

APP_NAME="redirect"
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
BRIEFCASE_VENV="${BRIEFCASE_VENV:-$PROJECT_ROOT/.venv-briefcase}"
INSTALL_DIR="${INSTALL_DIR:-$HOME/.local/bin}"
APP_INSTALL_DIR="${APP_INSTALL_DIR:-$HOME/.local/share/$APP_NAME/briefcase}"
SKIP_TESTS="${SKIP_TESTS:-0}"
SKIP_PACKAGE="${SKIP_PACKAGE:-0}"
BRIEFCASE_PLATFORM="${BRIEFCASE_PLATFORM:-}"
BRIEFCASE_FORMAT="${BRIEFCASE_FORMAT:-}"

log() {
  printf '\n==> %s\n' "$*"
}

briefcase() {
  "$BRIEFCASE_VENV/bin/python" -m briefcase "$@"
}

ensure_briefcase() {
  if [ ! -x "$BRIEFCASE_VENV/bin/python" ]; then
    log "Creating Briefcase virtualenv at $BRIEFCASE_VENV"
    "$PYTHON_BIN" -m venv "$BRIEFCASE_VENV"
  fi

  if ! "$BRIEFCASE_VENV/bin/python" -c "import briefcase" >/dev/null 2>&1; then
    log "Installing Briefcase in $BRIEFCASE_VENV"
    "$BRIEFCASE_VENV/bin/python" -m pip install --upgrade pip
    "$BRIEFCASE_VENV/bin/python" -m pip install briefcase
  fi
}

briefcase_target_args() {
  if [ -n "$BRIEFCASE_PLATFORM" ]; then
    printf '%s\n' "$BRIEFCASE_PLATFORM"
  fi
  if [ -n "$BRIEFCASE_FORMAT" ]; then
    printf '%s\n' "$BRIEFCASE_FORMAT"
  fi
}

find_executable() {
  find "$PROJECT_ROOT/build" "$PROJECT_ROOT/dist" \
    -type f \
    \( -name "$APP_NAME" -o -name "$APP_NAME*.AppImage" -o -name "$APP_NAME*.appimage" \) \
    -perm -111 \
    2>/dev/null \
    | sort \
    | tail -n 1
}

install_appimage() {
  local appimage_path="$1"
  local installed_appimage="$APP_INSTALL_DIR/$APP_NAME.AppImage"
  mkdir -p "$APP_INSTALL_DIR" "$INSTALL_DIR"
  cp "$appimage_path" "$installed_appimage"
  chmod +x "$installed_appimage"

  cat > "$INSTALL_DIR/$APP_NAME" <<EOF
#!/usr/bin/env bash
exec "$installed_appimage" "\$@"
EOF
  chmod +x "$INSTALL_DIR/$APP_NAME"
}

install_bundle() {
  local executable_path="$1"
  local bundle_root
  local relative_executable

  case "$executable_path" in
    *.AppDir/usr/bin/$APP_NAME)
      bundle_root="${executable_path%%.AppDir/usr/bin/$APP_NAME}.AppDir"
      relative_executable="usr/bin/$APP_NAME"
      ;;
    */usr/bin/$APP_NAME)
      bundle_root="${executable_path%/usr/bin/$APP_NAME}"
      relative_executable="usr/bin/$APP_NAME"
      ;;
    *)
      bundle_root="$(dirname "$executable_path")"
      relative_executable="$APP_NAME"
      ;;
  esac

  mkdir -p "$APP_INSTALL_DIR" "$INSTALL_DIR"
  rm -rf "$APP_INSTALL_DIR/app.tmp" "$APP_INSTALL_DIR/app"
  mkdir -p "$APP_INSTALL_DIR/app.tmp"
  cp -a "$bundle_root/." "$APP_INSTALL_DIR/app.tmp/"
  mv "$APP_INSTALL_DIR/app.tmp" "$APP_INSTALL_DIR/app"

  cat > "$INSTALL_DIR/$APP_NAME" <<EOF
#!/usr/bin/env bash
exec "$APP_INSTALL_DIR/app/$relative_executable" "\$@"
EOF
  chmod +x "$INSTALL_DIR/$APP_NAME"
}

main() {
  cd "$PROJECT_ROOT"

  if [ "$SKIP_TESTS" != "1" ]; then
    log "Running tests"
    env PYTHONDONTWRITEBYTECODE=1 "$PYTHON_BIN" -m unittest discover -s tests
  fi

  ensure_briefcase

  mapfile -t target_args < <(briefcase_target_args)

  if [ -d "$PROJECT_ROOT/build/$APP_NAME" ]; then
    log "Updating Briefcase app"
    briefcase update "${target_args[@]}"
  else
    log "Creating Briefcase app"
    briefcase create "${target_args[@]}"
  fi

  log "Building Briefcase app"
  briefcase build "${target_args[@]}"

  if [ "$SKIP_PACKAGE" != "1" ]; then
    log "Packaging Briefcase app"
    briefcase package "${target_args[@]}"
  fi

  executable_path="$(find_executable)"
  if [ -z "$executable_path" ]; then
    printf 'Could not find a Briefcase executable named %s under build/ or dist/.\n' "$APP_NAME" >&2
    exit 1
  fi

  log "Installing launcher in $INSTALL_DIR"
  case "$executable_path" in
    *.AppImage|*.appimage)
      install_appimage "$executable_path"
      ;;
    *)
      install_bundle "$executable_path"
      ;;
  esac

  log "Verifying installed command"
  "$INSTALL_DIR/$APP_NAME" --help

  printf '\nInstalled: %s\n' "$INSTALL_DIR/$APP_NAME"
  case ":$PATH:" in
    *":$INSTALL_DIR:"*) ;;
    *)
      printf 'Add this to your shell profile if needed:\n'
      printf '  export PATH="%s:$PATH"\n' "$INSTALL_DIR"
      ;;
  esac
}

main "$@"
