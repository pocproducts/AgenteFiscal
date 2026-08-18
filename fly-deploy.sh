#!/usr/bin/env bash
# fly-deploy.sh — aplica secrets de Fly.io a partir de los .env locales.
# Nunca imprime valores de secrets; en --dry-run muestra solo nombres de claves.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_APP="agente-fiscal-backend"
FRONTEND_APP="agente-fiscal-frontend"

usage() {
  cat <<EOF
Uso: $0 [--dry-run] [backend|frontend|all]

  --dry-run     muestra solo los nombres de claves, sin valores
  backend       aplica secrets del backend (agente-fiscal-backend)
  frontend      aplica secrets del frontend (agente-fiscal-frontend)
  all           aplica ambos (default)
EOF
}

DRY_RUN=0
TARGET="all"
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    backend|frontend|all) TARGET="$arg" ;;
    -h|--help) usage; exit 0 ;;
    *)
      echo "[fly] opción desconocida: $arg" >&2
      usage >&2
      exit 2
      ;;
  esac
done

# Asegura el CLI de Fly en el PATH (fallback al instalador estándar).
if ! command -v fly >/dev/null 2>&1 && [ -x "$HOME/.fly/bin/fly" ]; then
  export PATH="$HOME/.fly/bin:$PATH"
fi
if ! command -v fly >/dev/null 2>&1; then
  echo "[fly] error: CLI 'fly' no encontrada en PATH ni en \$HOME/.fly/bin" >&2
  exit 1
fi

# load_env <file> — imprime las líneas KEY=VALUE (sin exportar), saltando
# líneas vacías y comentarios (#).
load_env() {
  local file="$1" line
  while IFS= read -r line || [ -n "$line" ]; do
    # Quita whitespace final para no romper claves con \r (CRLF).
    line="${line%"${line##*[![:space:]]}"}"
    [ -z "$line" ] && continue
    case "$line" in
      \#*) continue ;;
    esac
    printf '%s\n' "$line"
  done < "$file"
}

# build_backend_pairs — pares KEY=VALUE del backend: .env sin overrides +
# overrides de infra + certs ARCA en base64.
build_backend_pairs() {
  local pairs=() line key
  local env_file="$SCRIPT_DIR/backend/.env"

  if [ -f "$env_file" ]; then
    while IFS= read -r line; do
      [ -z "$line" ] && continue
      key="${line%%=*}"
      case "$key" in
        REDIS_URL|CORS_ORIGINS|APP_ENV) continue ;;
      esac
      pairs+=("$line")
    done < <(load_env "$env_file")
  fi

  # Overrides: infra interna de Fly (Redis) y CORS del appserver frente al frontend.
  pairs+=("REDIS_URL=redis://agente-fiscal-redis.internal:6379")
  pairs+=("CORS_ORIGINS=https://agente-fiscal-frontend.fly.dev,http://localhost:3000")
  pairs+=("APP_ENV=production")

  # Certs ARCA como secrets base64; entrypoint los materializa al boot.
  local crt="$SCRIPT_DIR/backend/.certificados-arca/produccion.crt"
  local crt_key="$SCRIPT_DIR/backend/.certificados-arca/produccion.key"
  if [ -f "$crt" ]; then
    pairs+=("CERT_CRT_B64=$(base64 -w0 "$crt")")
  fi
  if [ -f "$crt_key" ]; then
    pairs+=("CERT_KEY_B64=$(base64 -w0 "$crt_key")")
  fi

  printf '%s\n' "${pairs[@]}"
}

# build_frontend_pairs — pares KEY=VALUE del frontend: .env sin API_BASE_URL ni
# NEXT_PUBLIC_* (build-time), + override de API_BASE_URL hacia el backend de Fly.
build_frontend_pairs() {
  local pairs=() line key
  local env_file="$SCRIPT_DIR/frontend/.env"

  if [ -f "$env_file" ]; then
    while IFS= read -r line; do
      [ -z "$line" ] && continue
      key="${line%%=*}"
      case "$key" in
        API_BASE_URL|NEXT_PUBLIC_*) continue ;;
      esac
      pairs+=("$line")
    done < <(load_env "$env_file")
  fi

  pairs+=("API_BASE_URL=https://agente-fiscal-backend.fly.dev")

  printf '%s\n' "${pairs[@]}"
}

# apply_secrets — un solo `fly secrets set` por app; en --dry-run solo nombres.
apply_secrets() {
  local app="$1"
  shift

  if [ "$DRY_RUN" -eq 1 ]; then
    local keys=() pair
    for pair in "$@"; do
      keys+=("${pair%%=*}")
    done
    echo "[dry-run] $app: ${keys[*]}"
    return 0
  fi

  # fly imprime confirmación sin valores; acá la silenciamos y damos nuestro resumen.
  fly secrets set -a "$app" "$@" >/dev/null
  echo "[fly] $app: $# secrets set"
}

deploy_target() {
  local target="$1" pairs=()
  case "$target" in
    backend)
      mapfile -t pairs < <(build_backend_pairs)
      apply_secrets "$BACKEND_APP" "${pairs[@]}"
      ;;
    frontend)
      mapfile -t pairs < <(build_frontend_pairs)
      apply_secrets "$FRONTEND_APP" "${pairs[@]}"
      ;;
    all)
      deploy_target backend
      deploy_target frontend
      ;;
  esac
}

deploy_target "$TARGET"