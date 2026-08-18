#!/bin/sh
# entrypoint.sh — materializa los certs ARCA desde secrets (base64) y arranca uvicorn.
# Si los archivos ya existen (compose/local, bind mount), no hace nada.
set -eu

CERT_DIR="${CERT_DIR:-.certificados-arca}"
PORT="${PORT:-8000}"

if [ ! -f "$CERT_DIR/produccion.crt" ] || [ ! -f "$CERT_DIR/produccion.key" ]; then
  mkdir -p "$CERT_DIR"
  if [ -n "${CERT_CRT_B64:-}" ]; then
    printf '%s' "$CERT_CRT_B64" | base64 -d > "$CERT_DIR/produccion.crt"
  fi
  if [ -n "${CERT_KEY_B64:-}" ]; then
    printf '%s' "$CERT_KEY_B64" | base64 -d > "$CERT_DIR/produccion.key"
  fi
  chmod 600 "$CERT_DIR/produccion.crt" "$CERT_DIR/produccion.key" 2>/dev/null || true
fi

exec uvicorn agente_fiscal.api.server:app --host 0.0.0.0 --port "$PORT" --workers 2