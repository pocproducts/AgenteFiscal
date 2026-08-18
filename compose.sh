#!/usr/bin/env bash
#
# compose.sh — orquestador local del stack Docker Compose de Agente Fiscal.
#
# Uso:
#   ./compose.sh up [--build] [--migrate]  Levanta redis + backend (:8000) +
#                                           frontend (:3000). --build reconstruye
#                                           las imágenes, --migrate aplica
#                                           Alembic antes de arrancar.
#   ./compose.sh down                      Detiene el stack (conserva volume
#                                           redis-data y af-storage).
#   ./compose.sh restart [--migrate]       down + up.
#   ./compose.sh status                    Estado de los contenedores + health
#                                           HTTP de backend y frontend.
#   ./compose.sh logs [backend|frontend|redis]  Seguir logs de un servicio.
#   ./compose.sh build                     Construye backend y frontend.
#   ./compose.sh migrate                   Alembic upgrade head (backend).
#   ./compose.sh help                      Esta ayuda.
#
# Notas:
#   - Reutiliza los secrets de backend/.env y frontend/.env vía env_file en
#     docker-compose.yml. El script SOLO exporta los build-args públicos del
#     frontend (NEXT_PUBLIC_* / IS_DEMO) y nunca imprime valores de secrets.
#   - La base de datos queda remota (Neon): no levanta postgres local.
#   - El worker fiscal corre in-process dentro de uvicorn: un solo contenedor
#     backend ejecuta API + worker (igual que en Fly).
#   - Los logs de cada corrida de docker compose quedan en .run/compose.log.
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FRONTEND_DIR="$ROOT/frontend"
RUN_DIR="$ROOT/.run"
COMPOSE_LOG="$RUN_DIR/compose.log"

log()   { printf '\033[1;36m[compose]\033[0m %s\n' "$*"; }
warn()  { printf '\033[1;33m[compose]\033[0m %s\n' "$*" >&2; }
err()   { printf '\033[1;31m[compose]\033[0m %s\n' "$*" >&2; }

# Renglon en compose.log (sin imprimir valores en pantalla).
log_file() {
  mkdir -p "$RUN_DIR"
  printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >> "$COMPOSE_LOG"
}

http_code() {
  curl -s -o /dev/null -w '%{http_code}' --max-time 3 "$1" 2>/dev/null || echo "000"
}

dev_stack_up() {
  # Si dev.sh levanto sus servicios, sus pidfiles vivos delatan el stack dev.
  local pid
  for f in backend frontend; do
    if [ -f "$RUN_DIR/$f.pid" ]; then
      pid="$(cat "$RUN_DIR/$f.pid" 2>/dev/null || true)"
      if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
        return 0
      fi
    fi
  done
  return 1
}

warn_if_ports_busy() {
  local p busy=false
  for p in 3000 8000; do
    if ss -ltn 2>/dev/null | awk '{print $4}' | grep -q ":$p$"; then
      warn "Puerto $p está ocupado."
      busy=true
    fi
  done
  if [ "$busy" = true ]; then
    if dev_stack_up; then
      warn "Parece el stack de dev.sh — detenelo con: ./dev.sh down"
    else
      warn "No es gestionado por este script. Liberá el puerto antes de levantar compose."
    fi
  fi
}

# Carga SOLO los build-args públicos del Dockerfile del frontend desde
# frontend/.env (y .env de la raíz si existe). Lee KEY=VALUE línea por línea,
# salta vacías y comentarios, exporta únicamente las 4 claves permitidas y no
# imprime ningún valor.
load_build_env() {
  local files=("$FRONTEND_DIR/.env")
  [ -f "$ROOT/.env" ] && files+=("$ROOT/.env")
  local file line key value
  for file in "${files[@]}"; do
    [ -f "$file" ] || continue
    while IFS= read -r line || [ -n "$line" ]; do
      line="${line%%$'\r'*}"
      [ -z "$line" ] && continue
      case "$line" in \#*) continue ;; esac
      key="${line%%=*}"
      value="${line#*=}"
      case "$key" in
        NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY|NEXT_PUBLIC_SENTRY_DSN|NEXT_PUBLIC_BASE_PATH|IS_DEMO)
          export "$key=$value"
          log "build-arg $key cargado desde $(basename "$file")"
          ;;
      esac
    done < "$file"
  done
}

needs_compose() {
  if ! docker compose version >/dev/null 2>&1; then
    err "Docker Compose (plugin v2) no está disponible."
    err "Instalalo (Linux): sudo apt install docker-compose-plugin, o seguí"
    err "docs.docker.com/compose/install/. Alternativa v1: sudo apt install docker-compose."
    return 1
  fi
}

wait_http() {
  local name="$1" url="$2" timeout_s="$3" i=0 code=000
  while [ "$i" -lt $((timeout_s * 2)) ]; do
    code="$(http_code "$url")"
    if [ "$code" != "000" ] && [ "$code" != "502" ] && [ "$code" != "503" ]; then
      log "$name listo (HTTP $code)"
      return 0
    fi
    i=$((i + 1))
    sleep 0.5
  done
  err "$name no respondió en ${timeout_s}s (último HTTP $code). Ver: ./compose.sh logs"
  return 1
}

wait_services() {
  wait_http "Backend"  "http://localhost:8000/v1/health" 90 || return 1
  wait_http "Frontend" "http://localhost:3000/ping"      90 || return 1
}

cmd_up() {
  needs_compose || return 1
  load_build_env
  local BUILD=false MIGRATE=false arg
  for arg in "$@"; do
    case "$arg" in
      --build)   BUILD=true ;;
      --migrate) MIGRATE=true ;;
      *) err "Argumento desconocido: $arg — usá ./compose.sh up [--build] [--migrate]"; return 1 ;;
    esac
  done
  warn_if_ports_busy
  if [ "$MIGRATE" = true ]; then
    cmd_migrate
  fi
  docker compose config --quiet
  log_file "docker compose up -d"
  if [ "$BUILD" = true ]; then
    log_file "docker compose up -d (--build)"
    docker compose up -d --build
  else
    docker compose up -d
  fi
  wait_services || return 1
  log "Stack arriba:"
  log "  Backend  → http://localhost:8000  (docs en /docs)"
  log "  Frontend → http://localhost:3000"
  log "  Logs     → ./compose.sh logs [backend|frontend|redis]"
}

cmd_down() {
  needs_compose || return 1
  log_file "docker compose down"
  docker compose down
  log "Stack detenido. Volúmenes preservados (redis-data, af-storage)."
}

cmd_restart() {
  cmd_down
  local arg="${1:-}"
  if [ -n "$arg" ]; then
    cmd_up "$arg"
  else
    cmd_up
  fi
}

cmd_status() {
  needs_compose || return 1
  docker compose ps
  printf 'Backend  : http=%s (http://localhost:8000/v1/health)\n' "$(http_code http://localhost:8000/v1/health)"
  printf 'Frontend : http=%s (http://localhost:3000/ping)\n'      "$(http_code http://localhost:3000/ping)"
}

cmd_logs() {
  needs_compose || return 1
  local target="${1:-all}"
  case "$target" in
    all|"")        docker compose logs -f ;;
    backend|frontend|redis) docker compose logs -f "$target" ;;
    *) err "Log target inválido: $target (backend|frontend|redis|all)"; return 1 ;;
  esac
}

cmd_build() {
  needs_compose || return 1
  load_build_env
  docker compose config --quiet
  log_file "docker compose build"
  docker compose build
  log "Build completo: backend y frontend listos."
}

cmd_migrate() {
  needs_compose || return 1
  log_file "docker compose exec backend alembic upgrade head"
  docker compose exec backend alembic upgrade head
}

cmd_help() {
  sed -n '2,26p' "$0"
}

case "${1:-help}" in
  up)      shift || true; cmd_up "$@" ;;
  down)    cmd_down ;;
  restart) shift || true; cmd_restart "${1:-}" ;;
  status)  cmd_status ;;
  logs)    cmd_logs "${2:-all}" ;;
  build)   cmd_build ;;
  migrate) cmd_migrate ;;
  help|--help|-h) cmd_help ;;
  *) err "Comando desconocido: $1 — usá ./compose.sh help"; exit 1 ;;
esac