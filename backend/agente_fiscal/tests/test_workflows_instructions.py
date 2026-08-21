"""Regression tests for the Composio browser-tool NL instruction templates.

These templates are plain (NON-f-string) module-level strings in
``agente_fiscal/adapters/browser/workflows/``. They are rendered at runtime in
``composio.py:_run_single`` via ``instruction.replace(f'{{{key}}}', str(value))``.

This suite guards against regressions already fixed on ``fix/bugs-tools-browser``:

  - double-brace literals (``{{`` / ``}}``) that were sent literally to Composio,
    producing malformed JSON in the ``done(...)`` examples (templates are NOT
    f-strings, so ``{{`` would reach the agent as a literal double brace);
  - placeholder wiring drift between each ``BrowserTask`` and its ``template``
    (every declared ``template_param`` must appear in the template and be fully
    substituted at render time);
  - accidental re-introduction of deleted dead templates
    (``TEMPLATE_EXTRACT``, ``TEMPLATE_IIBB_JUJUY``).
"""

from __future__ import annotations

import pytest

from agente_fiscal.adapters.browser import workflows
from agente_fiscal.adapters.browser.task import (
    ExtractV2Task,
    FacilidadesTask,
    IIBBTask,
    LoginTask,
    RegistroTask,
    VencimientosDeudasTask,
)
from agente_fiscal.adapters.browser.workflows import (
    LOGIN_STEPS,
    TEMPLATE_FACILIDADES,
    TEMPLATE_VENCIMIENTOSDEUDAS,
    TEMPLATE_IIBB,
    TEMPLATE_IIBB_CORDOBA,
    TEMPLATE_LOGIN,
    TEMPLATE_REGISTRO,
)

DUMMY = {'cuit': '20123456781', 'clave': 's3cr3t', 'cliente_cuit': '20987654321'}

# (task class, constructor arg names) — LoginTask omits cliente_cuit.
CONSTRUCT = {
    VencimientosDeudasTask: ('cuit', 'clave', 'cliente_cuit'),
    ExtractV2Task: ('cuit', 'clave', 'cliente_cuit'),
    LoginTask: ('cuit', 'clave'),
    FacilidadesTask: ('cuit', 'clave', 'cliente_cuit'),
    RegistroTask: ('cuit', 'clave', 'cliente_cuit'),
    IIBBTask: ('cuit', 'clave', 'cliente_cuit'),
}

EXTRACTION_TEMPLATES = [
    TEMPLATE_VENCIMIENTOSDEUDAS,
    TEMPLATE_FACILIDADES,
    TEMPLATE_REGISTRO,
    TEMPLATE_IIBB_CORDOBA,
    TEMPLATE_IIBB,
]
LOGIN_CAPABLE_TEMPLATES = [*EXTRACTION_TEMPLATES, TEMPLATE_LOGIN]


def _render(template: str, params: dict) -> str:
    """Replicate composio.py:_run_single placeholder substitution exactly."""
    rendered = template
    for key, value in params.items():
        rendered = rendered.replace(f'{{{key}}}', str(value))
    return rendered


# ── 1. No double-brace literals (the fixed bug) ──────────────────────────────


@pytest.mark.parametrize('template', LOGIN_CAPABLE_TEMPLATES)
def test_no_double_braces(template: str) -> None:
    assert '{{' not in template, 'found literal {{ (templates are not f-strings)'
    assert '}}' not in template, 'found literal }} (templates are not f-strings)'


# ── 2. Placeholder wiring: each task's params are used and fully substituted ──


@pytest.mark.parametrize(('task_cls', 'arg_names'), list(CONSTRUCT.items()))
def test_task_template_placeholders(task_cls, arg_names) -> None:
    task = task_cls(*(DUMMY[k] for k in arg_names))
    template = task.template
    params = task.template_params

    assert set(params) == set(arg_names)
    # every declared param must appear as a placeholder in the raw template
    for key in params:
        assert f'{{{key}}}' in template, f'template does not use {{{key}}}'
    # and must be fully substituted after the runtime render
    rendered = _render(template, params)
    for key in params:
        assert f'{{{key}}}' not in rendered, f'leftover {{{key}}} after render'


# ── 3. ARCA error handling + done() JSON contract ────────────────────────────


@pytest.mark.parametrize('template', LOGIN_CAPABLE_TEMPLATES)
def test_arca_error_handling_present(template: str) -> None:
    assert 'ARCA-4' in template, 'template missing ARCA-4 credential-error handling'
    assert 'ARCA-6' in template, 'template missing ARCA-6 2FA handling'


@pytest.mark.parametrize('template', EXTRACTION_TEMPLATES)
def test_done_call_present(template: str) -> None:
    assert 'done(' in template, 'extraction template must call done() with JSON'


# ── 4. Dead templates must stay removed ─────────────────────────────────────


def test_dead_templates_removed() -> None:
    assert not hasattr(workflows, 'TEMPLATE_EXTRACT'), 'TEMPLATE_EXTRACT was deleted'
    assert not hasattr(workflows, 'TEMPLATE_IIBB_JUJUY'), 'TEMPLATE_IIBB_JUJUY was deleted'


# ── 5. Login-success criterion must be unified across all templates ───────────

LOGIN_SUCCESS_URL = 'cloud.afip.gob.ar'


@pytest.mark.parametrize('template', LOGIN_CAPABLE_TEMPLATES)
def test_login_success_criterion_unified(template: str) -> None:
    assert LOGIN_SUCCESS_URL in template, (
        f'template must use the unified login-success URL {LOGIN_SUCCESS_URL}'
    )
    assert 'www.afip.gob.ar/landing/default.asp' not in template, (
        'stale landing-page criterion must be gone'
    )


# ── 6. Login steps must come from the single shared fragment ─────────────────


def test_login_steps_is_single_source() -> None:
    for template in LOGIN_CAPABLE_TEMPLATES:
        assert LOGIN_STEPS in template, (
            f'{template!r} must embed the shared LOGIN_STEPS fragment'
        )
