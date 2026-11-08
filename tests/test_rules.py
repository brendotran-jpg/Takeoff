import copy
import shutil
from pathlib import Path

import pytest

from app.rules import RuleError, RulesLibrary, citation

ROOT = Path(__file__).resolve().parent.parent / "rules"


@pytest.fixture
def lib(tmp_path):
    shutil.copy(ROOT / "schema.json", tmp_path)
    shutil.copy(ROOT / "starter_rules.yaml", tmp_path)
    (tmp_path / "user").mkdir()
    return RulesLibrary(tmp_path)


def test_starter_rules_are_valid_and_unverified(lib):
    assert lib.errors == []
    assert len(lib.rules) >= 10
    for r in lib.rules.values():
        # The starter set must never assert a clause number it has not verified.
        assert r["source"]["clause"] is None
        assert r["source"]["clause_verified"] is False
        assert r["verification"]["status"] == "placeholder_unverified"
        assert citation(r).startswith("[UNVERIFIED]")


def test_user_override_bumps_version(lib):
    r = copy.deepcopy(lib.get("CONC-SLAB-001"))
    r["source"]["clause"] = "X.1"
    r["source"]["clause_verified"] = True
    r["verification"] = {"status": "user_verified", "verified_by": "QS", "verified_on": "2026-11-01"}
    saved = lib.save_user_rule(r)
    assert saved["version"] == 2
    assert lib.origin["CONC-SLAB-001"].startswith("user/")
    assert not citation(saved).startswith("[UNVERIFIED]")


def test_cannot_mark_verified_without_clause(lib):
    r = copy.deepcopy(lib.get("CONC-SLAB-001"))
    r["verification"] = {"status": "user_verified"}
    with pytest.raises(RuleError):
        lib.save_user_rule(r)


def test_invalid_rule_reported_not_loaded(lib, tmp_path):
    (tmp_path / "user" / "bad.yaml").write_text("rules:\n  - id: bad id\n    title: x\n")
    lib.reload()
    assert any("bad.yaml" in e for e in lib.errors)
