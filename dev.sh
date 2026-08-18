#!/usr/bin/env bash
#
# dev.sh — local orchestration for Agente Fiscal (backend + frontend).
#
# Usage:
#   ./dev.sh up [--migrate]   Start Redis + backend (:8000) + frontend (:3000).
#                             --migrate applies Alembic migrations first.
#   ./dev.sh down             Stop backend + frontend + Redis.
#   ./dev.sh restart [--migrate]  down + up.
#   ./dev.sh status           Show running state + health for all services.
#   ./dev.sh logs [backend|frontend]  Tail the log file.
#   ./dev.sh migrate          Apply Alembic migrations (backend).
#   ./dev.sh seed             Run the idempotent seed script (backend).
#   ./dev.sh help             This help.
#
# Notes:
#   - The fiscal worker runs IN-PROCESS inside uvicorn (FastAPI lifespan), so
#     starting the backend also starts the worker.
#   - Redis is started locally as a daemon (port 6379) only when no Redis is
#     already responding; its dump file lives in .run/redis/ (gitignored) so
#     the repo root never gets a stray dump.rdb.
#   - Runtime artifacts (pid files + logs) live in .run/ (gitignored).
#   - Env: DATABASE_URL / REDIS_URL / CLERK_* are read from backend/.env and
#     frontend/.env.local; no secrets are needed here.
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$ROOT/backend"
FRONTEND_DIR="$ROOT/frontend"
RUN_DIR="$ROOT/.run"
BACKEND_LOG="$RUN_DIR/backend.log"
FRONTEND_LOG="$RUN_DIR/frontend.log"
BACKEND_PID="$RUN_DIR/backend.pid"
FRONTEND_PID="$RUN_DIR/frontend.pid"

BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-3000}"
BACKEND_URL="http://localhost:$BACKEND_PORT"
FRONTEND_URL="http://localhost:$FRONTEND_PORT"
REDIS_PORT="${REDIS_PORT:-6379}"
REDIS_PID="$RUN_DIR/redis.pid"
REDIS_LOG="$RUN_DIR/redis.log"
REDIS_DATA_DIR="$RUN_DIR/redis"

PY="$BACKEND_DIR/.venv/bin/python"
UVICORN="$BACKEND_DIR/.venv/bin/uvicorn"
ALEMBIC="$BACKEND_DIR/.venv/bin/alembic"

log()  { printf '\033[1;36m[dev]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[dev]\033[0m %s\n' "$*" >&2; }
err()  { printf '\033[1;31m[dev]\033[0m %s\n' "$*" >&2; }

read_pid()  { [ -f "$1" ] && cat "$1" 2>/dev/null || echo ""; }
pid_alive() { local pid="$1"; [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; }

# HTTP code of a url; curl -w prints "000" on a failed/absent connection, so the
# value is taken as-is (no `|| echo 000` which would double-print).
http_code() { curl -s -o /dev/null -w '%{http_code}' --max-time 3 "$1" 2>/dev/null; }
backend_http() { local c; c="$(http_code "$BACKEND_URL/v1/system/features")"; echo "${c:-000}"; }
frontend_http() { local c; c="$(http_code "$FRONTEND_URL/ping")"; echo "${c:-000}"; }

port_in_use() { ss -ltn 2>/dev/null | awk '{print $4}' | grep -q ":$1$"; }

redis_up() { command -v redis-cli >/dev/null 2>&1 && redis-cli -p "$REDIS_PORT" ping >/dev/null 2>&1; }

start_redis() {
  if redis_up; then
    log "Redis ya está corriendo en localhost:$REDIS_PORT"
    return 0
  fi
  if ! command -v redis-server >/dev/null 2>&1; then
    err "redis-server no está en el PATH. Instalalo (apt install redis-server o brew install redis)."
    return 1
  fi
  if port_in_use "$REDIS_PORT"; then
    err "Puerto $REDIS_PORT ocupado por un proceso ajeno — Redis no puede arrancar."
    return 1
  fi
  log "Arrancando Redis en localhost:$REDIS_PORT ..."
  mkdir -p "$RUN_DIR" "$REDIS_DATA_DIR"
  redis-server \
    --port "$REDIS_PORT" \
    --daemonize yes \
    --pidfile "$REDIS_PID" \
    --logfile "$REDIS_LOG" \
    --dir "$REDIS_DATA_DIR" \
    --dbfilename dump.rdb \
    --save 900 1 \
    --save 300 10 \
    --save 60 10000 \
    --appendonly no
  sleep 0.5
  if redis_up; then
    log "Redis listo (pid $(cat "$REDIS_PID" 2>/dev/null || echo '?'))"
    return 0
  fi
  err "Redis no respondió tras arrancar. Log: $REDIS_LOG"
  return 1
}

stop_redis() {
  # Solo detiene el Redis que levantó este script (pidfile propio), nunca un
  # Redis externo que ya estuviera corriendo.
  local pid
  pid="$(read_pid "$REDIS_PID")"
  if [ -n "$pid" ] && pid_alive "$pid"; then
    log "Deteniendo Redis (pid $pid) ..."
    redis-cli -p "$REDIS_PORT" shutdown nosave >/dev/null 2>&1 || kill -TERM "$pid" 2>/dev/null || true
    local i=0
    while pid_alive "$pid" && [ "$i" -lt 20 ]; do sleep 0.5; i=$((i + 1)); done
    [ -f "$REDIS_PID" ] && rm -f "$REDIS_PID"
  elif redis_up; then
    log "Redis externo corriendo en localhost:$REDIS_PORT — no lo detengo (no lo levanté yo)."
  else
    log "Redis no estaba corriendo."
  fi
}

check_prereqs() {
  if [ ! -x "$PY" ] || [ ! -x "$UVICORN" ] || [ ! -x "$ALEMBIC" ]; then
    err "Backend venv incompleto en backend/.venv. Creálo con: cd backend && python3 -m venv .venv && .venv/bin/pip install -e ."
    return 1
  fi
  if command -v pnpm >/dev/null 2>&1; then :; else
    err "pnpm no está en el PATH. Instalalo (corepack enable o npm i -g pnpm)."
    return 1
  fi
  if command -v redis-cli >/dev/null 2>&1 && ! redis_up; then
    warn "Redis no responde en localhost:$REDIS_PORT — ./dev.sh up lo intentará levantar automáticamente."
  fi
  if [ ! -f "$BACKEND_DIR/.env" ]; then
    warn "No existe backend/.env — copialo desde backend/.env.example y completá DATABASE_URL, REDIS_URL, CLERK_*"
  fi
  if [ ! -f "$FRONTEND_DIR/.env.local" ]; then
    warn "No existe frontend/.env.local — sin CLERK_PUBLISHABLE_KEY/CLERK_SECRET_KEY el login no funciona."
  fi
}

start_backend() {
  if [ -n "$1" ] && pid_alive "$1"; then
    log "Backend ya está corriendo (pid $1, $BACKEND_URL)"
    return 0
  fi
  if port_in_use "$BACKEND_PORT"; then
    err "Puerto $BACKEND_PORT ocupado por un proceso ajeno (no gestionado por este script)."
    return 1
  fi
  log "Arrancando backend en $BACKEND_URL ..."
  mkdir -p "$RUN_DIR"
  (
    cd "$BACKEND_DIR"
    setsid nohup "$UVICORN" agente_fiscal.api.server:app --host 0.0.0.0 --port "$BACKEND_PORT" \
      >"$BACKEND_LOG" 2>&1 &
    echo $! >"$BACKEND_PID"
  )
  wait_http "Backend" "$BACKEND_URL/v1/system/features" any 60 || return 1
}

start_frontend() {
  if [ -n "$1" ] && pid_alive "$1"; then
    log "Frontend ya está corriendo (pid $1, $FRONTEND_URL)"
    return 0
  fi
  if port_in_use "$FRONTEND_PORT"; then
    err "Puerto $FRONTEND_PORT ocupado por un proceso ajeno (no gestionado por este script)."
    return 1
  fi
  log "Arrancando frontend en $FRONTEND_URL ..."
  mkdir -p "$RUN_DIR"
  (
    cd "$FRONTEND_DIR"
    setsid nohup pnpm dev >"$FRONTEND_LOG" 2>&1 &
    echo $! >"$FRONTEND_PID"
  )
  wait_http "Frontend" "$FRONTEND_URL/ping" 200 90 || return 1
}

wait_http() {
  local name="$1" url="$2" expect="$3" timeout_s="$4"
  local i=0 code=000
  while [ "$i" -lt $((timeout_s * 2)) ]; do
    code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 3 "$url" 2>/dev/null || true)"
    code="${code:-000}"
    if [ "$expect" = "any" ] && [ "$code" != "000" ]; then
      log "$name listo (HTTP $code)"
      return 0
    fi
    if [ "$expect" != "any" ] && [ "$code" = "$expect" ]; then
      log "$name listo (HTTP $code)"
      return 0
    fi
    i=$((i + 1))
    sleep 0.5
  done
  err "$name no respondió en ${timeout_s}s (último HTTP $code). Logs: $BACKEND_LOG / $FRONTEND_LOG"
  return 1
}

stop_service() {
  local name="$1" pid_file="$2" pid
  pid="$(read_pid "$pid_file")"
  if pid_alive "$pid"; then
    log "Deteniendo $name (pid $pid) ..."
    # Kill the whole process group (services are started under `setsid`, so
    # their children — e.g. pnpm → next-server — die too, not just the parent).
    kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true
    local i=0
    while pid_alive "$pid" && [ "$i" -lt 20 ]; do sleep 0.5; i=$((i + 1)); done
    if pid_alive "$pid"; then
      kill -KILL -- "-$pid" 2>/dev/null || kill -KILL "$pid" 2>/dev/null || true
    fi
  else
    log "$name no estaba corriendo."
  fi
  rm -f "$pid_file"
}

cmd_up() {
  check_prereqs
  local MIGRATE=false
  [ "${1:-}" = "--migrate" ] && MIGRATE=true
  start_redis || return 1
  if [ "$MIGRATE" = true ]; then
    cmd_migrate
  fi
  start_backend "$(read_pid "$BACKEND_PID")" || { warn "Backend no levantó — revisá $BACKEND_LOG"; return 1; }
  start_frontend "$(read_pid "$FRONTEND_PID")" || { warn "Frontend no levantó — revisá $FRONTEND_LOG"; return 1; }
  log "Sistema arriba:"
  log "  Redis    → localhost:$REDIS_PORT"
  log "  Backend  → $BACKEND_URL   (docs en $BACKEND_URL/docs)"
  log "  Frontend → $FRONTEND_URL"
  log "  Logs     → $BACKEND_LOG / $FRONTEND_LOG / $REDIS_LOG"
}

cmd_down() {
  stop_service "backend" "$BACKEND_PID"
  stop_service "frontend" "$FRONTEND_PID"
  stop_redis
  log "Sistema detenido."
}

cmd_status() {
  local bp fp
  bp="$(read_pid "$BACKEND_PID")"
  fp="$(read_pid "$FRONTEND_PID")"
  if redis_up; then
    printf 'Redis    : up   (localhost:%s)\n' "$REDIS_PORT"
  else
    printf 'Redis    : down (localhost:%s)\n' "$REDIS_PORT"
  fi
  printf 'Backend  : pid=%s estado=%s http=%s\n' \
    "${bp:-—}" \
    "$(pid_alive "$bp" && echo up || echo down)" \
    "$(backend_http)"
  printf 'Frontend : pid=%s estado=%s http=%s\n' \
    "${fp:-—}" \
    "$(pid_alive "$fp" && echo up || echo down)" \
    "$(frontend_http)"
  [ -f "$BACKEND_LOG" ] && { log "backend log:"; tail -5 "$BACKEND_LOG"; }
  [ -f "$FRONTEND_LOG" ] && { log "frontend log:"; tail -5 "$FRONTEND_LOG"; }
}

cmd_logs() {
  local target="${1:-both}"
  case "$target" in
    backend) tail -f "$BACKEND_LOG" ;;
    frontend) tail -f "$FRONTEND_LOG" ;;
    both) tail -f "$BACKEND_LOG" "$FRONTEND_LOG" ;;
    *) err "Log target inválido: $target (backend|frontend|both)"; return 1 ;;
  esac
}

cmd_migrate() {
  check_prereqs
  log "Aplicando migraciones Alembic (backend) ..."
  (cd "$BACKEND_DIR" && "$ALEMBIC" upgrade head)
}

cmd_seed() {
  check_prereqs
  log "Ejecutando seed idempotente (backend) ..."
  (cd "$BACKEND_DIR" && "$PY" -m agente_fiscal.db.seed)
}

cmd_help() {
  sed -n '2,22p' "$0"
}

case "${1:-help}" in
  up) shift || true; cmd_up "${1:-}" ;;
  down) cmd_down ;;
  restart) cmd_down; cmd_up "${2:-}" ;;
  status) cmd_status ;;
  logs) cmd_logs "${2:-both}" ;;
  migrate) cmd_migrate ;;
  seed) cmd_seed ;;
  help|--help|-h) cmd_help ;;
  *) err "Comando desconocido: $1 — usá ./dev.sh help"; exit 1 ;;
esac