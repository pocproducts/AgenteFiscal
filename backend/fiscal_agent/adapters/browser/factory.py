"""BrowserTask factory — centralized task creation from flags."""

from __future__ import annotations

from fiscal_agent.adapters.browser.task import (
	BrowserTask,
	FacilidadesTask,
	IIBBTask,
	RegistroTask,
	VencimientosDeudasTask,
)


def build_browser_tasks(
	cuit: str,
	clave: str,
	cliente_cuit: str,
	*,
	with_deuda: bool = False,
	with_facilidades: bool = False,
	with_registro: bool = False,
	with_iibb: bool = False,
	provincia: str | None = None,
) -> list[BrowserTask]:
	"""Build a list of BrowserTask instances based on boolean flags.

	Order is preserved: deuda -> facilidades -> registro -> iibb.
	Each task receives (cuit, clave, cliente_cuit) constructor args.
	"""
	tasks: list[BrowserTask] = []

	if with_deuda:
		tasks.append(VencimientosDeudasTask(cuit=cuit, clave=clave, cliente_cuit=cliente_cuit))
	if with_facilidades:
		tasks.append(FacilidadesTask(cuit=cuit, clave=clave, cliente_cuit=cliente_cuit))
	if with_registro:
		tasks.append(RegistroTask(cuit=cuit, clave=clave, cliente_cuit=cliente_cuit))
	if with_iibb:
		tasks.append(
			IIBBTask(
				cuit=cuit,
				clave=clave,
				cliente_cuit=cliente_cuit,
				provincia=provincia or 'CORDOBA',
			)
		)

	return tasks
