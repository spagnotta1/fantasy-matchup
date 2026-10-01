"""The DuckDB helpers resolve from every command that uses them.

They used to live in ``nflfp/db.py``, beside the ``nflfp/db/`` package. A
package shadows a module of the same name, so ``from . import db`` handed
``ingest``, ``explore`` and ``scripts/verify_parity.py`` the SQLAlchemy package
and every one of them died on ``db.connect()``. Nothing failed until somebody
ran the documented command, because nothing imported the path under test.

No database, and no network: these only check that the names resolve.
"""

from __future__ import annotations

import importlib

import pytest


@pytest.mark.parametrize("module", ["nflfp.ingest", "nflfp.explore"])
def test_the_command_modules_reach_the_duckdb_helpers(module):
    loaded = importlib.import_module(module)
    assert callable(loaded.duck.connect)
    assert callable(loaded.duck.db_path)


def test_the_database_path_is_overridable(monkeypatch, tmp_path):
    from nflfp import duck

    target = tmp_path / "elsewhere.duckdb"
    monkeypatch.setenv("NFLFP_DB", str(target))
    assert duck.db_path() == target


def test_no_module_shares_a_name_with_the_sqlalchemy_package():
    # `nflfp.db` must be the package. If a `db.py` reappears beside it, the
    # package still wins the import and the module is dead on arrival.
    import nflfp.db

    assert hasattr(nflfp.db, "__path__")
