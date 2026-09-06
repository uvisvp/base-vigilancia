"""Checks that the Drogaria UI catalog only points to validated current nodes."""
from __future__ import annotations

import json
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
CATALOG = BASE / "dados" / "roteiros" / "drogaria.json"


def test_catalog_shape_and_stable_question_ids():
    data = json.loads(CATALOG.read_text(encoding="utf-8"))
    assert data["schema"] == "roteiro-estruturado-v1"
    assert len(data["cards"]) == 8
    ids = [q["id"] for q in data["perguntas"]]
    assert len(ids) == len(set(ids))
    assert all(q.get("id") and q.get("card") in range(1, 9) for q in data["perguntas"])


def test_references_have_current_unique_nodes_and_matching_source_hashes():
    data = json.loads(CATALOG.read_text(encoding="utf-8"))
    for node_id, ref in data["referencias"].items():
        path = BASE / "dados" / ref["arquivo"]
        norm = json.loads(path.read_text(encoding="utf-8"))
        assert norm["sha256_texto"] == ref["sha256_texto"]
        assert norm.get("proveniencia", {}).get("sha256_texto") == norm["sha256_texto"]
        assert str(norm.get("proveniencia", {}).get("fonte_oficial", "")).startswith("http")
        matches = [n for n in norm["nos"] if n.get("id") == node_id]
        assert len(matches) == 1, node_id
        assert str(matches[0].get("status_vigencia", "")).startswith("vigente"), node_id
        assert not matches[0].get("ambiguidade_na_fonte"), node_id


def test_revoked_norms_are_not_used_as_current_references():
    data = json.loads(CATALOG.read_text(encoding="utf-8"))
    names = {ref["norma"] for ref in data["referencias"].values()}
    assert "RDC 327/2019" not in names
    assert "RDC 565/2021" not in names
    assert "RDC 786/2023" not in names


def test_pending_items_are_explicit_and_do_not_auto_classify():
    data = json.loads(CATALOG.read_text(encoding="utf-8"))
    assert any(x["norma"] == "Portaria CVS-SP 23/2003" for x in data["pendencias"])
    pending = [q for q in data["perguntas"] if q.get("pendencia_validacao")]
    assert pending
    assert all(not q.get("gera_irregularidade") for q in pending)

