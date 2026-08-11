"""PadronApiTask — consulta al Padrón A5 vía SOAP como ApiTask."""

from __future__ import annotations

from fiscal_agent.adapters.arca_ws import consultar_cuit
from fiscal_agent.adapters.tasks.base import ApiTask, TaskResult


class PadronApiTask(ApiTask):
	"""Wrapping de consultar_cuit() del WS ARCA A5."""

	name = 'padron_a5'
	needs_ta = True
	needs_certs = True
	timeout = 60

	def __init__(self, cuit: str) -> None:
		self._cuit = cuit

	def execute(self, context: dict) -> TaskResult:
		token = context['token']
		sign = context['sign']
		representante_cuit = context['representante_cuit']
		result = consultar_cuit(self._cuit, token, sign, representante_cuit)
		output = result.to_output()
		if output.errorConstancia:
			return TaskResult(
				task_name=self.name,
				success=False,
				parsed_data=result.to_dict(),
				error='; '.join(output.errorConstancia.error),
			)
		return TaskResult(
			task_name=self.name,
			success=True,
			parsed_data=result.to_dict(),
		)
