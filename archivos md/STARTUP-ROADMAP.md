# Startup Roadmap — Agente Fiscal

> **Estado**: borrador de trabajo — evaluación cruzada del feedback de auditoría con el estado real del código.
> **Alcance**: estabilización técnica + hoja de ruta post-migración del backend.
> Documentos relacionados: [`ARCHITECTURE-ROADMAP.md`](ARCHITECTURE-ROADMAP.md) (frontend) · [`BACKEND-MIGRATION.md`](BACKEND-MIGRATION.md) (migración).

---

## 1. Contexto

Startup de automatizaciones para el mundo fiscal argentino (contadores, estudios contables y empresas): agentes de IA que automatizan calendario de vencimientos ARCA (AFIP), verificación de deuda/registro/IIBB y reportes.

Monorepo con dos servicios:

| Carpeta | Servicio | Stack |
|---|---|---|
| `frontend/` | UI + BFF | Next.js 16, React 19, AI SDK 6, Clerk, Tailwind 4, shadcn/ui, SWR |
| `backend/` | API + worker | Python 3.12, FastAPI, SQLAlchemy 2 async, Alembic, PostgreSQL, Redis, PyJWT |

---

## 2. Dónde estamos hoy (evaluación con evidencia del código)

### Lo que está bien y es real ✅

- **Confianza / auth**: separación correcta. BFF en Next reenvía el JWT de Clerk, y el backend **verifica el JWT por su cuenta** (`backend/agente_fiscal/api/middleware/clerk.py` — HS256 en dev, RS256+JWKS en prod, cache en Redis `jwks:clerk`).
- **Multi-tenancy real**: `users.clerk_user_id`, `tenants.clerk_org_id`, scoping por `tenant_id`, API keys con hash (nunca plaintext).
- **Migración de backend avanzada**: Postgres + Alembic (migraciones + seed + UUIDv7), worker con `report_runs` como máquina de estados (audit trail de corridas), hexagonal selectivo (`ports/` + `adapters/`), backoff en browser, rate limiting.
- **Human-in-the-loop como concepto**: `report.py` expone `human_approval_required=bool(next_actions)`.

### Eslabones débiles ⚠️ (el riesgo real)

1. **El core fiscal NO tiene tests.** Cero archivos de test cubren `rules_engine`, `arca_ws`, `pdf_generator`, `billing`, ni la máquina de estados de `report_runs`. Los ~14 tests del backend cubren chat/memory/worker — no lo que cobra el producto. Confirmado por los "gaps" de `BACKEND-MIGRATION.md`.
2. **Observabilidad ~2/10**: sin Sentry, sin logs estructurados con correlación. Hay métricas en memoria (`RequestMetricsStore` + `/v1/system/metrics`) que se pierden al reiniciar y no alertan a nadie. Un agente que falla en silencio = un contador que pierde confianza.
3. **Sin test de aislamiento multi-tenant** — el bug #1 en SaaS B2B: tenant A leyendo datos de tenant B.
4. **E2E del frontend en 3/10**: solo 4 tests de auth; el chat autenticado no tiene cobertura (pendiente de setup `@clerk/testing`).
5. **Deuda cosmetica de rebrand incompleto**: root `package.json` sigue siendo `chatbot-monorepo`; `BACKEND-MIGRATION.md:109` dice que el backend "trusts" al frontend (obsoleto, hoy verifica); falta `.env.example` en frontend.

### Veredicto

| Dimensión | Nota |
|---|---|
| Arquitectura | 8/10 |
| Core backend | 6/10 |
| Testing del core fiscal | 1/10 |
| Observabilidad | 2/10 |
| E2E frontend | 3/10 |

El esqueleto está bien construido. El riesgo real: los flujos fiscales críticos son los **menos testeados y los menos observables** — exactamente donde la confianza se gana o se pierde.

---

## 3. Principios rectores (del feedback de auditoría)

- En fiscal, **la confianza es el producto**: un error silencioso es una relación perdida.
- **Human-in-the-loop obligatorio** en acciones de alto riesgo: el agente propone, el humano aprueba.
- Cada automatización nueva debe demostrar **ahorro medible** de tiempo o de riesgo de error.
- **No lanzar a todo el mundo**: pilotos de pago primero, con un workflow estrecho.
- **No vender enterprise temprano**: más compliance, más soporte, más riesgo.
- La deuda técnica no debe crecer mientras se agregan features.
- El comprador es el contador/estudio — su confianza y su tiempo son el producto.

---

## 4. Hoja de ruta

### Fase 1 — Production readiness (semanas 1-6, ANTES de vender)

**Objetivo**: que el sistema no se caiga, no pierda datos y tenga trazabilidad completa.

1. **Observabilidad**
   - Sentry en frontend y backend (errores + trazabilidad).
   - Logs estructurados JSON con request-id correlacionado BFF → backend.
   - Alertas de uptime, latencia (p95) y tasa de fallo de `report_runs`.
2. **Tests del core fiscal** (el eslabón más débil)
   - `rules_engine`: tests table-driven (barato, alto valor).
   - Máquina de estados `report_runs` (queued → running → done/failed).
   - **Aislamiento multi-tenant** (el test de seguridad #1).
   - CRUD de `clients` y `api_keys`.
   - `arca_ws` / `pdf_generator` / `browser`: integración detrás de flags; smoke manual.
3. **Human-in-the-loop real (bloqueante, no informativo)**
   - Definir acciones de alto riesgo (presentar, firmar, enviar a AFIP/ARCA, facturar).
   - Persistir en `report_runs` el estado "esperando aprobación explícita" — el agente NUNCA las ejecuta solo.
4. **Resiliencia**
   - Backup/restore probado + runbook.
   - Staging mínimo (mismo schema, env vars separadas).
5. **Deuda chica que duele hoy**
   - Corregir `BACKEND-MIGRATION.md` (línea 109 obsoleta).
   - Renombrar root `package.json` (`chatbot-monorepo` → `agente-fiscal`).
   - Crear `.env.example` en frontend.
   - Setup `@clerk/testing` para E2E del chat autenticado (o feature-flag en staging).

**Definition of done**: los flujos críticos fiscales tienen tests verdes, los errores alertan, el restore se probó de verdad, y el agente no ejecuta acciones de alto riesgo sin aprobación.

### Fase 2 — Pilotos de pago (meses 1-3)

**Objetivo**: validar valor real con 5-15 estudios contables que paguen (aunque sea poco).

- **Un solo workflow estrecho de alto valor**:
  - Candidato A: **calendario fiscal ARCA + avisos** — puro `rules_engine`, el módulo más testeable, valor inmediato, bajo riesgo.
  - Candidato B: **reporte de deuda/registro** con `human_approval_required` — el pipeline ya existe.
- **Métricas del piloto**: tiempo ahorrado, % de tareas resueltas sin intervención, tasa de error vs proceso manual, NPS/satisfacción del contador.
- **Feedback estructurado semanal**; los edge cases que rompen el 20% de los casos → convertirlos en tests.
- **Siempre**: agente propone → humano aprueba. Un error que llegue a ARCA hunde la relación.

**Definition of done**: 5-15 pilotos pagos con el workflow estrecho, métricas de valor registradas, edge cases documentados y convertidos en tests.

### Fase 3 — Cumplimiento, seguridad y confianza (paralelo, no opcional)

- **Audit trail administrativo**: tabla de acciones "quién hizo qué" (export de historial incluido).
- **Documentación del agente**: qué datos usa, qué reglas aplica, limitaciones. Los contadores serios la van a pedir.
- **Políticas**: privacidad, términos, DPA, responsabilidad sobre outputs de los agentes.
- **Penetration test externo** cuando haya tracción real.
- **Actualización de reglas fiscales como proceso formal**: feriados, calendario, thresholds cambian todo el tiempo — automatizar lo más posible (assets ya existen en repo; formalizar pipeline de actualización + tests).

### Fase 4 — Producto (con feedback real)

- Onboarding guiado + plantillas por tipo de cliente/estudio.
- **Integraciones prioritarias**: sistemas contables del mercado objetivo, bancos, facturación electrónica.
- **Dashboard del contador**: qué hizo el agente, qué necesita revisión, historial.
- **Roles multi-usuario** dentro del estudio (admin/member) — el tenant ya está, falta UI y permisos.
- Mejoras de precisión de los agentes con casos reales (prompting + RAG con normativa actualizada).
- **Nada de feature creep**: cada automatización nueva demuestra reducción medible de tiempo o riesgo.

### Fase 5 — Escalar (solo cuando retención y soporte estén controlados)

- **Unidad económica clara**: CAC, LTV, margen después de costos de IA/infra.
- **Pricing orientado a valor**: por agente/proceso automatizado, por cliente del estudio o por volumen de declaraciones — no solo por usuario.
- Customer Success temprano (aunque sea el founder) para implementación y feedback.
- Soporte documentado + knowledge base cuando llegues a 20-50 clientes.
- Canales del vertical: partnerships con software contable, asociaciones de contadores, contenido técnico (webinars de casos reales), referidos de pilotos.

---

## 5. Errores clásicos a evitar

- ❌ Lanzar sin human-in-the-loop en decisiones fiscales.
- ❌ Ignorar edge cases y "prometer" que el agente lo resuelve todo.
- ❌ No medir ni comunicar el ahorro real de tiempo/errores.
- ❌ Dejar crecer la deuda técnica mientras se agregan features.
- ❌ Vender a empresas grandes demasiado pronto.
- ❌ Olvidar que el comprador es el contador/estudio, no solo el dueño de la empresa.

---

## 6. Secuencia recomendada resumida

1. **Estabilizar e instrumentar** (Fase 1 — ahora).
2. **5-15 pilotos de pago** con un workflow estrecho y medible (Fase 2).
3. Iterar precisión + confianza + onboarding (Fases 3-4, en paralelo).
4. Integraciones clave + pricing definitivo (Fase 4).
5. Escalar adquisición solo cuando retención y soporte estén bajo control (Fase 5).
