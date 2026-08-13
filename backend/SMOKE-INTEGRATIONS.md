# SMOKE: External Integrations

This document explains how to enable and smoke-test the external integrations
behind feature flags. Every external integration is **disabled by default** so a
fresh deploy never touches the network. Each one fails with a clean
`INTEGRATION_DISABLED` error instead of crashing.

## Feature flags

| Integration | Env var | Default | Impact when disabled |
| --- | --- | --- | --- |
| ARCA (WSAA SOAP + Padrón A5) | `ARCA_ENABLED` | `false` | `get_ta()` returns `(None, None)`, no WSAA network calls; worker runs fail with `INTEGRATION_DISABLED`; health reports `ta=disabled` |
| Composio browser | `BROWSER_ENABLED` | `false` | Browser never built; `POST /v1/extract` and `POST /v1/report` return 503 `INTEGRATION_DISABLED`; worker fails with `INTEGRATION_DISABLED`; health reports `composio=disabled` |
| PDF generation (local) | `PDF_ENABLED` | `true` | PDF never generated; pipeline reports `INTEGRATION_DISABLED` if requested |

`true`/`false` (also `1`/`0`) are accepted as boolean values.

Inspect the effective flags at runtime:

```bash
curl http://localhost:8000/v1/system/features
# {"status":"success","result":{"arca_enabled":false,"browser_enabled":false,"pdf_enabled":true}}
```

## ARCA (`ARCA_ENABLED=true`)

### Prerequisites

- Certificates and private key under `backend/.certificados-arca/`
  (`cert.crt`, `key.key`) — paths come from `CERT_PATH` / `KEY_PATH`.
- `REPRESENTANTE_CUIT` (or the corresponding config) set.

### Smoke

```bash
# Health shows TA check active (version omitted = token lookup ran)
curl http://localhost:8000/v1/health | grep '"ta"'

# CLI: full report for a CUIT (padrón A5 + calendario + browser + PDF)
cd backend && .venv/bin/agente-fiscal report 20000000001
```

With `ARCA_ENABLED=false` the same commands do NOT perform WSAA calls: the CLI
report still runs (returns `(None, None)` TA), health reports
`ta: {status: healthy, version: disabled}`, and queued worker runs fail with
`INTEGRATION_DISABLED`.

## Composio browser (`BROWSER_ENABLED=true`)

### Prerequisites

- `COMPOSIO_API_KEY` in `.env`.
- `ESTUDIO_CLAVE_FISCAL` in `.env` (used with `REPRESENTANTE_CUIT` to log into
  AFIP ctacte.cloud / Mis Facilidades / RUT).

### Smoke

```bash
curl -X POST http://localhost:8000/v1/extract \
  -H 'Content-Type: application/json' \
  -d '{"cuit":"20000000001","tasks":["deuda","facilidades","registro"]}'
```

With `BROWSER_ENABLED=false` the same request returns:

```json
{
  "status": "error",
  "error": {
    "code": "INTEGRATION_DISABLED",
    "cause": "La integración de browser (Composio) está deshabilitada. Activá BROWSER_ENABLED=true para habilitarla",
    "remediation": "Habilitar la integración Composio vía su flag de configuración para poder usarla"
  }
}
```

with HTTP 503. No Composio cloud call is made.

## PDF (`PDF_ENABLED=true`)

On by default. Set `PDF_ENABLED=false` to disable generation (purely local —
useful for storage-cost testing). The pipeline reports `INTEGRATION_DISABLED`
instead of producing a file.
