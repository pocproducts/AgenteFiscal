"""Unit tests for ``agente_fiscal.domain.rules_engine``.

Pure unit tests — no database involved. The default ``RulesEngine()``
constructor loads the real data files shipped in the repo
(``calendario_afip.json``, ``feriados.csv``); custom calendars/holidays are
written to ``tmp_path`` when a test needs precise control.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from agente_fiscal.domain.models import ImpuestoInscripto, PadronA5Output, RulesOutput
from agente_fiscal.domain.rules_engine import RulesEngine, calcular_calendario

CUIT = '20301234561'  # ends in group 1


def padron_ri_iva(cuit: str = CUIT) -> PadronA5Output:
    """Responsable inscripto with IVA (impuesto 30) and nothing else."""
    return PadronA5Output(
        **{
            'datosGenerales': {'idPersona': cuit},
            'regimenGeneral': {'impuestos': [{'idImpuesto': 30}]},
        }
    )


def padron_iibb(cuit: str = CUIT) -> PadronA5Output:
    """Responsable inscripto with IIBB only."""
    return PadronA5Output(
        **{
            'datosGenerales': {'idPersona': cuit},
            'regimenGeneral': {'impuestos': [{'idImpuesto': 5902}]},
        }
    )


def _write_feriados(tmp_path: Path, dates: list[str]) -> Path:
    path = tmp_path / 'feriados.csv'
    body = ['date,description'] + [f'{d},test-holiday' for d in dates]
    path.write_text('\n'.join(body) + '\n', encoding='utf-8')
    return path


def _calendario_spec(**meses_overrides) -> dict:
    """Minimal calendar: single obligations (iva_ddjj) with a June day."""
    meses = {'1': 28}
    meses.update(meses_overrides)
    return {
        'version': 'test',
        'fuente': 'test',
        'notas': {},
        'por_tipo': {
            'responsable_inscripto': {
                'iva_ddjj': {
                    'key': 'iva_ddjj',
                    'label': 'IVA DDJJ',
                    'id_impuesto': 30,
                    'grupos_cuit': [{'desde': 0, 'hasta': 9, 'columna': 'IVA DDJJ'}],
                    'meses': meses,
                }
            }
        },
    }


def _write_calendario(tmp_path: Path, spec: dict) -> Path:
    path = tmp_path / 'calendario.json'
    path.write_text(json.dumps(spec), encoding='utf-8')
    return path


# ─── calcular() table-driven vs the real AFIP JSON ──────────────────────────


@pytest.mark.parametrize('last_digit', range(10))
def test_calcular_iva_due_day_from_real_json(last_digit: int) -> None:
    engine = RulesEngine()
    padron = padron_ri_iva(cuit=f'2030123456{last_digit}')

    output = engine.calcular(padron, mes=6, anio=2026)

    assert output.cuit == f'2030123456{last_digit}'
    assert output.periodo == '2026-06'

    iva = next(v for v in output.vencimientos if v.concepto.startswith('IVA'))
    expected_day = (
        engine.calendario.por_tipo['responsable_inscripto']['iva_ddjj'].meses['6']
    )
    expected = engine._proximo_habil(date(2026, 6, expected_day))
    assert iva.fecha == expected
    assert iva.es_fecha_habil is True


def test_calcular_hardcoded_known_values() -> None:
    """Guard against data regressions with hand-computed due dates."""
    engine = RulesEngine()

    def iva_fecha(padron, mes, anio) -> date:
        output = engine.calcular(padron, mes=mes, anio=anio)
        return next(v for v in output.vencimientos if v.concepto.startswith('IVA')).fecha

    # June 2026 -> day 23 (Tuesday, no holiday adjustments).
    assert iva_fecha(padron_ri_iva(), 6, 2026) == date(2026, 6, 23)
    # December 2026 -> day 23 (Wednesday).
    assert iva_fecha(padron_ri_iva(), 12, 2026) == date(2026, 12, 23)
    # January 2026 -> day 22 (Thursday).
    assert iva_fecha(padron_ri_iva(), 1, 2026) == date(2026, 1, 22)


def test_calcular_ri_iva_gets_sicore_retentions() -> None:
    """An IVA-only RI also gets the SICORE/SIRE retentions obligation."""
    engine = RulesEngine()
    output = engine.calcular(padron_ri_iva(), mes=6, anio=2026)

    sicore = next(
        v for v in output.vencimientos if 'SICORE' in v.concepto
    )
    expected_day = (
        engine.calendario.por_tipo['responsable_inscripto']
        ['ret_perc_sicore_sire'].meses['6']
    )
    assert sicore.fecha == engine._proximo_habil(date(2026, 6, expected_day))


def test_calcular_no_cuit_uses_empty_string() -> None:
    engine = RulesEngine()
    padron = padron_ri_iva(cuit='')
    output = engine.calcular(padron, mes=6, anio=2026)
    assert output.cuit == ''
    assert output.periodo == '2026-06'


def test_calcular_non_digit_cuit_uses_zero_digit() -> None:
    engine = RulesEngine()
    padron = padron_ri_iva(cuit='NOT-A-CUIT')
    output = engine.calcular(padron, mes=6, anio=2026)
    assert output.cuit == 'NOT-A-CUIT'
    assert output.vencimientos  # obligations still resolved


# ─── _proximo_habil (weekend / holiday adjustment) ──────────────────────────


def test_proximo_habil_saturday_moves_to_monday(tmp_path) -> None:
    engine = RulesEngine(feriados_path=_write_feriados(tmp_path, []))
    assert engine._proximo_habil(date(2026, 6, 13)) == date(2026, 6, 15)  # Sat


def test_proximo_habil_sunday_moves_to_monday(tmp_path) -> None:
    engine = RulesEngine(feriados_path=_write_feriados(tmp_path, []))
    assert engine._proximo_habil(date(2026, 6, 14)) == date(2026, 6, 15)  # Sun


def test_proximo_habil_saturday_plus_monday_holiday_moves_to_tuesday(tmp_path) -> None:
    engine = RulesEngine(feriados_path=_write_feriados(tmp_path, ['2026-06-15']))
    assert engine._proximo_habil(date(2026, 6, 13)) == date(2026, 6, 16)


def test_proximo_habil_weekday_holiday_moves_to_next_day(tmp_path) -> None:
    engine = RulesEngine(feriados_path=_write_feriados(tmp_path, ['2026-06-22']))
    assert engine._proximo_habil(date(2026, 6, 22)) == date(2026, 6, 23)  # Mon -> Tue


def test_proximo_habil_plain_business_day_is_unchanged(tmp_path) -> None:
    engine = RulesEngine(feriados_path=_write_feriados(tmp_path, []))
    assert engine._proximo_habil(date(2026, 6, 9)) == date(2026, 6, 9)


# ─── Holiday adjustment through calcular() ──────────────────────────────────


def test_calcular_holiday_pushes_due_date(tmp_path) -> None:
    feriados = _write_feriados(tmp_path, ['2026-06-23'])
    engine = RulesEngine(feriados_path=feriados)

    output = engine.calcular(padron_ri_iva(), mes=6, anio=2026)

    iva = next(v for v in output.vencimientos if v.concepto.startswith('IVA'))
    assert iva.fecha == date(2026, 6, 24)
    assert iva.es_fecha_habil is False
    assert output.feriados_presentes == [date(2026, 6, 23)]


def test_calcular_no_holiday_no_adjustment(tmp_path) -> None:
    engine = RulesEngine(feriados_path=_write_feriados(tmp_path, []))
    output = engine.calcular(padron_ri_iva(), mes=6, anio=2026)
    iva = next(v for v in output.vencimientos if v.concepto.startswith('IVA'))
    assert iva.fecha == date(2026, 6, 23)
    assert iva.es_fecha_habil is True
    assert output.feriados_presentes == []


def test_calcular_attribute_holiday_accounting(tmp_path) -> None:
    """Check the 'Día de la Bandera' handling: 2026-06-20 is a Sat holiday
    (before the 23rd), so it must never appear in feriados_presentes."""
    calendario = _write_calendario(tmp_path, _calendario_spec())
    engine = RulesEngine(calendario_path=calendario, feriados_path=_write_feriados(tmp_path, []))
    output = engine.calcular(padron_ri_iva(), mes=6, anio=2026)
    assert output.feriados_presentes == []


# ─── _obligaciones_para_contribuyente ───────────────────────────────────────


def test_obligaciones_iva_only(make_padron) -> None:
    engine = RulesEngine()
    assert engine._obligaciones_para_contribuyente(make_padron()) == [
        'iva_ddjj',
        'ret_perc_sicore_sire',
    ]


def test_obligaciones_monotributo_only(make_padron) -> None:
    engine = RulesEngine()
    assert engine._obligaciones_para_contribuyente(
        make_padron(impuestos=(), monotributo=True)
    ) == ['monotributo']


def test_obligaciones_autonomo_only(make_padron) -> None:
    engine = RulesEngine()
    assert engine._obligaciones_para_contribuyente(
        make_padron(impuestos=(), autonomo=True)
    ) == ['autonomos']


def test_obligaciones_ganancias(make_padron) -> None:
    engine = RulesEngine()
    assert engine._obligaciones_para_contribuyente(make_padron(impuestos=(10,))) == [
        'ganancias_sociedades',
        'anticipos_ganancias',
        'gcias_bienes',
    ]


@pytest.mark.parametrize('impuesto_id', [5902, 5904, 5905, 5906, 215])
def test_obligaciones_iibb_impuesto(make_padron, impuesto_id: int) -> None:
    engine = RulesEngine()
    obligaciones = engine._obligaciones_para_contribuyente(
        make_padron(impuestos=(impuesto_id,))
    )
    assert 'convenio_multilateral' in obligaciones


@pytest.mark.parametrize('provincias', [None, ['CORDOBA'], ['CORDOBA', 'BUENOS AIRES']])
def test_obligaciones_iibb_provincias(make_padron, provincias) -> None:
    """convenio_multilateral is attached for 0, 1 and 2+ provincias (the local
    vs. multilateral split is not yet implemented per-province)."""
    engine = RulesEngine()
    obligaciones = engine._obligaciones_para_contribuyente(
        padron_iibb(), provincias=provincias
    )
    assert 'convenio_multilateral' in obligaciones


def test_obligaciones_unknown_impuesto_ignored(make_padron) -> None:
    engine = RulesEngine()
    assert engine._obligaciones_para_contribuyente(make_padron(impuestos=(999,))) == []


def test_obligaciones_none_impuesto_ignored(make_padron) -> None:
    engine = RulesEngine()
    padron = make_padron(impuestos=(999,))
    padron.regimenGeneral.impuestos = [ImpuestoInscripto(idImpuesto=None)]
    assert engine._obligaciones_para_contribuyente(padron) == []


def test_obligaciones_deduplicated(make_padron) -> None:
    engine = RulesEngine()
    obligaciones = engine._obligaciones_para_contribuyente(
        make_padron(impuestos=(30, 30))
    )
    assert obligaciones.count('iva_ddjj') == 1


def test_obligaciones_iva_plus_ganancias_union(make_padron) -> None:
    engine = RulesEngine()
    obligaciones = engine._obligaciones_para_contribuyente(make_padron(impuestos=(30, 10)))
    for key in ('iva_ddjj', 'ganancias_sociedades', 'anticipos_ganancias',
                'gcias_bienes', 'ret_perc_sicore_sire'):
        assert key in obligaciones


# ─── _observaciones_para_contribuyente ──────────────────────────────────────


def test_observaciones_impuesto_103(make_padron) -> None:
    engine = RulesEngine()
    obstetra = engine._observaciones_para_contribuyente(make_padron(impuestos=(103,)))
    assert any('Régimen de Información' in o for o in obstetra)


@pytest.mark.parametrize('regimen', ['68', '255'])
def test_observaciones_regimenes(make_padron, regimen: str) -> None:
    engine = RulesEngine()
    obs = engine._observaciones_para_contribuyente(make_padron(regimenes=(regimen,)))
    assert obs


def test_observaciones_unknown_regimen_ignored(make_padron) -> None:
    engine = RulesEngine()
    assert engine._observaciones_para_contribuyente(make_padron(regimenes=('999',))) == []


def test_observaciones_none(make_padron) -> None:
    engine = RulesEngine()
    assert engine._observaciones_para_contribuyente(make_padron()) == []


# ─── _dia_vencimiento ───────────────────────────────────────────────────────


def test_dia_vencimiento_known_month() -> None:
    engine = RulesEngine()
    assert engine._dia_vencimiento('iva_ddjj', 1, 6) == 23


def test_dia_vencimiento_missing_month_falls_back(tmp_path) -> None:
    calendario = _write_calendario(tmp_path, _calendario_spec())
    engine = RulesEngine(calendario_path=calendario)
    assert engine._dia_vencimiento('iva_ddjj', 5, 6) == 28


def test_dia_vencimiento_unknown_key_raises() -> None:
    engine = RulesEngine()
    with pytest.raises(KeyError):
        engine._dia_vencimiento('no_such_obligation', 5, 6)


def test_calcular_missing_month_uses_fallback_day(tmp_path) -> None:
    calendario = _write_calendario(tmp_path, _calendario_spec())
    engine = RulesEngine(calendario_path=calendario)
    output = engine.calcular(padron_ri_iva(), mes=6, anio=2026)
    # Fallback day 28 = Sunday 2026-06-28 -> Monday 2026-06-29.
    assert output.vencimientos == [output.vencimientos[0]]
    assert output.vencimientos[0].fecha == date(2026, 6, 29)
    assert output.vencimientos[0].concepto == 'IVA - Período 5/2026'


def test_calcular_invalid_day_skips_obligation(tmp_path) -> None:
    calendario = _write_calendario(tmp_path, _calendario_spec(**{'2': 31}))
    engine = RulesEngine(calendario_path=calendario)
    output = engine.calcular(padron_ri_iva(), mes=2, anio=2026)
    assert output.vencimientos == []


# ─── _generar_concepto ──────────────────────────────────────────────────────


def test_generar_concepto_variants() -> None:
    engine = RulesEngine()
    flat = engine._obligaciones_flat

    assert engine._generar_concepto(flat['iva_ddjj'], 6, 2026) == 'IVA - Período 5/2026'
    assert engine._generar_concepto(flat['iva_ddjj'], 1, 2026) == 'IVA - Período 12/2025'
    assert engine._generar_concepto(flat['monotributo'], 6, 2026) == 'Monotributo - Cuota Mensual 6/2026'
    assert engine._generar_concepto(flat['anticipos_ganancias'], 6, 2026) == 'Ganancias - Anticipo 6/2026'
    assert engine._generar_concepto(flat['autonomos'], 6, 2026) == 'Autónomos - Cuota 6/2026'
    assert engine._generar_concepto(flat['ganancias_sociedades'], 6, 2026) == (
        'Ganancias Sociedades - Período 5/2026'
    )
    assert engine._generar_concepto(flat['ganancias_sociedades'], 1, 2026) == (
        'Ganancias Sociedades - Período 12/2025'
    )
    # Default label path (no special key).
    assert engine._generar_concepto(flat['personal_casas'], 6, 2026) == (
        'Personal Casas Particulares - 6/2026'
    )


# ─── calcular() with monotributo / autonomos / IIBB ─────────────────────────


def test_calcular_monotributo_concept(make_padron) -> None:
    engine = RulesEngine()
    output = engine.calcular(make_padron(impuestos=(), monotributo=True), mes=6, anio=2026)
    assert [v.concepto for v in output.vencimientos] == ['Monotributo - Cuota Mensual 6/2026']
    # Monotributo due day 20 -> 2026-06-20 is a Saturday, so it shifts to Monday.
    assert output.vencimientos[0].fecha == date(2026, 6, 22)


def test_calcular_sorts_vencimientos(make_padron) -> None:
    engine = RulesEngine()
    output = engine.calcular(make_padron(impuestos=(10,)), mes=6, anio=2026)
    fechas = [v.fecha for v in output.vencimientos]
    assert fechas == sorted(fechas)


# ─── Feriados file handling ─────────────────────────────────────────────────


def test_feriados_missing_file_no_crash(tmp_path) -> None:
    engine = RulesEngine(feriados_path=tmp_path / 'nope.csv')
    assert engine.feriados == set()


def test_feriados_unreadable_path_returns_empty(tmp_path) -> None:
    # A directory raises IsADirectoryError (an OSError) on open -> caught.
    engine = RulesEngine(feriados_path=tmp_path)
    assert engine.feriados == set()


def test_feriados_malformed_lines_ignored(tmp_path) -> None:
    path = tmp_path / 'feriados.csv'
    path.write_text(
        'date,description\n'
        'not-a-date,blah\n'
        '# comment line\n'
        '\n'
        '2026-01-01,Año Nuevo\n',
        encoding='utf-8',
    )
    engine = RulesEngine(feriados_path=path)
    assert engine.feriados == {date(2026, 1, 1)}


def test_feriados_empty_field_after_strip_ignored(tmp_path) -> None:
    """A row whose date field strips to empty (``,x``) is skipped."""
    path = tmp_path / 'feriados.csv'
    path.write_text(
        'date,description\n'
        '   ,sin fecha\n'
        '2026-01-01,Año Nuevo\n',
        encoding='utf-8',
    )
    engine = RulesEngine(feriados_path=path)
    assert engine.feriados == {date(2026, 1, 1)}


def test_calendario_missing_raises(tmp_path) -> None:
    with pytest.raises(FileNotFoundError):
        RulesEngine(calendario_path=tmp_path / 'nope.json')


# ─── calcular_calendario() high-level helper ────────────────────────────────


def test_calcular_calendario_helper() -> None:
    padron = padron_ri_iva()
    expected = RulesEngine().calcular(padron, mes=6, anio=2026)
    output = calcular_calendario(padron, mes=6, anio=2026)
    assert output == expected


def test_calcular_calendario_helper_custom_paths(tmp_path) -> None:
    padron = padron_ri_iva()
    calendario = _write_calendario(tmp_path, _calendario_spec(**{'6': 23}))
    feriados = _write_feriados(tmp_path, ['2026-06-23'])
    engine = RulesEngine(calendario_path=calendario, feriados_path=feriados)
    expected = engine.calcular(padron, mes=6, anio=2026)

    output = calcular_calendario(
        padron,
        mes=6,
        anio=2026,
        feriados_path=feriados,
        calendario_path=calendario,
    )
    assert output == expected
    assert output.feriados_presentes == [date(2026, 6, 23)]