"""Tests del adapter ARCA WS (arca_ws.py): SOAP Fault de persona inexistente y retry de conexión.

Cubre el comportamiento corregido de ``consultar_cuit``:
- HTTP 500 con ``<faultstring>No existe persona con ese Id</faultstring>`` →
  ``PadronNotFoundError`` (dominio), NO el 500 crudo.
- HTTP 500 con otro fault → ``HTTPError`` con el mensaje del fault.
- Errores de conexión transitorios → un único reintento acotado.
"""

from __future__ import annotations

import pytest

from agente_fiscal.adapters import arca_ws
from agente_fiscal.adapters.arca_ws import PadronNotFoundError

SOAP_OK = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">'
    '<soap:Body>'
    '<ns2:getPersonaResponse xmlns:ns2="http://a5.soap.ws.server.puc.sr/">'
    '<personaReturn><datosGenerales><idPersona>20324837796</idPersona>'
    '<razonSocial>HORMAECHE</razonSocial></datosGenerales></personaReturn>'
    '</ns2:getPersonaResponse>'
    '</soap:Body></soap:Envelope>'
)

FAULT_MISSING_PERSONA = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">'
    '<soap:Body><soap:Fault><faultcode>soap:Server</faultcode>'
    '<faultstring>No existe persona con ese Id</faultstring>'
    '<detail><ns1:SRValidationError xmlns:ns1="http://a5.soap.ws.server.puc.sr/">...</ns1:SRValidationError></detail>'
    '</soap:Fault></soap:Body></soap:Envelope>'
)

FAULT_OTHER = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">'
    '<soap:Body><soap:Fault><faultcode>soap:Server</faultcode>'
    '<faultstring>Servicio temporalmente no disponible</faultstring>'
    '</soap:Fault></soap:Body></soap:Envelope>'
)


class _Resp:
    def __init__(self, status_code: int, text: str):
        self.status_code = status_code
        self.text = text

    def raise_for_status(self):
        if self.status_code >= 400:
            from requests.exceptions import HTTPError

            raise HTTPError(f'{self.status_code} Server Error for url: http://arca.invalid', response=self)


def _monkey(monkeypatch, responses):
    """Patch requests.post to consume ``responses`` (list of responses or exceptions)."""
    calls = []

    def fake_post(*_a, **_k):
        calls.append(1)
        item = responses[len(calls) - 1]
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(arca_ws.requests, 'post', fake_post)
    return calls


def test_parse_soap_fault_extracts_faultstring():
    assert arca_ws._parse_soap_fault(FAULT_MISSING_PERSONA) == 'No existe persona con ese Id'
    assert arca_ws._parse_soap_fault(FAULT_OTHER) == 'Servicio temporalmente no disponible'
    assert arca_ws._parse_soap_fault('<html>not soap</html>') is None
    assert arca_ws._parse_soap_fault('not xml at all') is None


def test_missing_persona_fault_raises_domain_error(monkeypatch):
    monkeypatch.setattr('agente_fiscal.adapters.arca_ws.time.sleep', lambda _s: None)
    calls = _monkey(monkeypatch, [_Resp(500, FAULT_MISSING_PERSONA)])

    with pytest.raises(PadronNotFoundError, match='No existe persona con ese Id'):
        arca_ws.consultar_cuit('20324837796', 'tok', 'sig', '20324837796')

    # Sin reintento: un SOAP Fault 500 es determinístico, no transitorio.
    assert calls == [1]


def test_missing_persona_fault_render_clean(monkeypatch):
    """El fault de persona inexistente no debe filtrar '500 Server Error'."""
    monkeypatch.setattr('agente_fiscal.adapters.arca_ws.time.sleep', lambda _s: None)
    _monkey(monkeypatch, [_Resp(500, FAULT_MISSING_PERSONA)])

    with pytest.raises(PadronNotFoundError) as exc_info:
        arca_ws.consultar_cuit('20324837796', 'tok', 'sig', '20324837796')
    assert '500' not in str(exc_info.value)
    assert 'No existe persona' in str(exc_info.value)


def test_other_fault_raises_http_error_with_fault_message(monkeypatch):
    monkeypatch.setattr('agente_fiscal.adapters.arca_ws.time.sleep', lambda _s: None)
    calls = _monkey(monkeypatch, [_Resp(500, FAULT_OTHER)])

    with pytest.raises(Exception) as exc_info:
        arca_ws.consultar_cuit('20324837796', 'tok', 'sig', '20324837796')
    assert 'Servicio temporalmente no disponible' in str(exc_info.value)
    assert calls == [1]


def test_connection_error_retries_once_then_raises(monkeypatch):
    from requests.exceptions import ConnectionError

    monkeypatch.setattr('agente_fiscal.adapters.arca_ws.time.sleep', lambda _s: None)
    calls = _monkey(monkeypatch, [ConnectionError('reset'), ConnectionError('reset')])

    with pytest.raises(ConnectionError):
        arca_ws.consultar_cuit('20324837796', 'tok', 'sig', '20324837796')
    assert len(calls) == 2  # intento inicial + 1 retry


def test_connection_error_retries_then_succeeds(monkeypatch):
    from requests.exceptions import ConnectionError

    monkeypatch.setattr('agente_fiscal.adapters.arca_ws.time.sleep', lambda _s: None)
    calls = _monkey(monkeypatch, [ConnectionError('reset'), _Resp(200, SOAP_OK)])

    result = arca_ws.consultar_cuit('20324837796', 'tok', 'sig', '20324837796')
    assert isinstance(result, arca_ws.PadronA5Result)
    assert len(calls) == 2
    assert result.to_dict()['razon_social'] == 'HORMAECHE'