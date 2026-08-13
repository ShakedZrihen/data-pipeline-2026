"""Rami Levi — Cerberus portal.

Nothing chain-specific beyond the account name: the >1000-file pagination that
this chain needs is handled once in ``CerberusStoreSource._list_files``.
"""
from __future__ import annotations

from sources.cerberus import CerberusStoreSource


class RamiLeviStoreSource(CerberusStoreSource):
    name = "rami_levi"
    user_name = "RamiLevi"
