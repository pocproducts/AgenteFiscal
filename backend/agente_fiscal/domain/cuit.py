"""Argentine CUIT/CUIL validation (11-digit mod-11 checksum).

A CUIT is 11 digits: the first two identify the type (person/company prefix),
digits 3-10 encode the DNI/number, and the last digit is a verifier computed
by the AFIP mod-11 algorithm over the first 10 digits with fixed weights.
"""

from __future__ import annotations

import re

_CUIT_RE = re.compile(r'^\d{11}$')

#: Fixed AFIP weights for the first 10 digits.
_WEIGHTS = (5, 4, 3, 2, 7, 6, 5, 4, 3, 2)

#: CUIT prefixes whose verifier special-case (rest of 10) yields 9.
_PREFIXES_VER_9 = ('20', '23', '24', '27', '30', '33', '34', '36')


def is_valid_cuit(cuit: str) -> bool:
	"""Return ``True`` if *cuit* is an 11-digit value with a valid checksum."""
	if not _CUIT_RE.fullmatch(cuit):
		return False
	digits = [int(d) for d in cuit]
	total = sum(d * w for d, w in zip(digits[:10], _WEIGHTS))
	verifier = 11 - (total % 11)
	if verifier == 11:
		verifier = 0
	elif verifier == 10:
		# Prefixes in _PREFIXES_VER_9 map to 9, everything else to 4.
		verifier = 9 if cuit[:2] in _PREFIXES_VER_9 else 4
	return verifier == digits[10]
