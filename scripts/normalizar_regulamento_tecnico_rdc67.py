#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Normaliza o ANEXO sem número da RDC 67/2007 como Regulamento Técnico.

O estruturador genérico reconhece anexos numerados. Na RDC 67/2007, porém,
existe primeiro um `ANEXO` sem numeral, intitulado `REGULAMENTO TÉCNICO ...`,
antes dos Anexos I a VIII. Esta etapa específica do pipeline de manipulação:

- cria a raiz estável `rdc-67-2007::regulamento-tecnico`;
- retira os dispositivos do Regulamento Técnico do Art. 8º;
- preserva integralmente o padrão dos Anexos I a VIII;
- falha antes da publicação se o item 5.1 não ficar na nova raiz.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
SAIDA = BASE / "dados" / "legislacao_v12"
DOC_PATH = SAIDA / "normas" / "rdc-67-2007.json"
MANIFEST_PATH = SAIDA / "manifest.json"
RELATORIO_PATH = SAIDA / "relatorio-manipulacao.json"

ROOT_ID = "rdc-67-2007::regulamento-tecnico"
OLD_PARENT = "rdc-67-2007::artigo::8"
ITEM_51 = ROOT_ID + "::item::5-1"


def agora() -> str:
    return datetime.now(timezone.utc).isoformat()


def _texto(no: dict) -> str:
    return str(no.get("texto") or "").strip()


def normalizar(doc: dict) -> dict:
    nos = list(doc.get("nos", []))

    marcador = next(
        (n for n in nos if n.get("tipo") == "bloco" and _texto(n).upper() == "ANEXO"),
        None,
    )
    if not marcador:
        raise RuntimeError("RDC 67-2007: marcador ANEXO sem número não localizado")

    ordem_inicio = int(marcador.get("ordem", 0))
    titulo = next(
        (
            n for n in nos
            if int(n.get("ordem", 0)) > ordem_inicio
            and _texto(n).upper().startswith("REGULAMENTO TÉCNICO")
        ),
        None,
    )
    if not titulo:
        raise RuntimeError("RDC 67-2007: título do Regulamento Técnico não localizado")

    anexos_numerados = [
        n for n in nos
        if n.get("tipo") == "anexo" and int(n.get("ordem", 0)) > ordem_inicio
    ]
    if not anexos_numerados:
        raise RuntimeError("RDC 67-2007: nenhum anexo numerado após o Regulamento Técnico")
    ordem_fim = min(int(n.get("ordem", 0)) for n in anexos_numerados)

    # Substitui as duas linhas editoriais (ANEXO + título) por uma raiz estrutural.
    remover_ids = {marcador.get("id"), titulo.get("id")}
    nos = [n for n in nos if n.get("id") not in remover_ids]

    status = doc.get("proveniencia", {}).get("status_vigencia", "pendente_validacao")
    raiz = {
        "id": ROOT_ID,
        "norma": "RDC 67-2007",
        "anexo": None,
        "tipo": "regulamento_tecnico",
        "numero": "geral",
        "rotulo": "Regulamento Técnico",
        "texto": _texto(titulo),
        "ordem": ordem_inicio,
        "status_vigencia": status,
        "origem_estrutura": "anexo_sem_numero",
    }

    alterados = 0
    for no in nos:
        ordem = int(no.get("ordem", 0))
        if not (ordem_inicio < ordem < ordem_fim):
            continue

        nid = str(no.get("id") or "")
        pai = str(no.get("pai") or "")

        if nid.startswith(OLD_PARENT + "::"):
            no["id"] = ROOT_ID + nid[len(OLD_PARENT):]
            alterados += 1
        if pai == OLD_PARENT or pai.startswith(OLD_PARENT + "::"):
            no["pai"] = ROOT_ID + pai[len(OLD_PARENT):]

        # Blocos não estruturais têm ID independente do pai; ainda assim devem
        # pertencer semanticamente ao Regulamento Técnico e não ao Art. 8º.
        if no.get("pai") == OLD_PARENT:
            no["pai"] = ROOT_ID

    nos.append(raiz)
    nos.sort(key=lambda n: (int(n.get("ordem", 0)), str(n.get("id", ""))))
    doc["nos"] = nos

    ids_estruturais = [n["id"] for n in nos if n.get("estrutural", True)]
    repetidos = sorted({x for x in ids_estruturais if ids_estruturais.count(x) > 1})
    if repetidos:
        raise RuntimeError(f"RDC 67-2007: IDs duplicados após normalização: {repetidos[:10]}")

    item_51 = next((n for n in nos if n.get("id") == ITEM_51), None)
    if not item_51:
        raise RuntimeError(f"RDC 67-2007: item 5.1 não encontrado em {ITEM_51}")

    presos_art8 = [
        n.get("id") for n in nos
        if ordem_inicio < int(n.get("ordem", 0)) < ordem_fim
        and (
            str(n.get("id") or "").startswith(OLD_PARENT + "::")
            or str(n.get("pai") or "").startswith(OLD_PARENT)
        )
    ]
    if presos_art8:
        raise RuntimeError(
            "RDC 67-2007: dispositivos do Regulamento Técnico ainda vinculados ao Art. 8º: "
            + ", ".join(presos_art8[:10])
        )

    doc.setdefault("validacao", {})["regulamento_tecnico"] = {
        "id": ROOT_ID,
        "item_5_1": ITEM_51,
        "ordem_inicio": ordem_inicio,
        "ordem_primeiro_anexo_numerado": ordem_fim,
        "ids_reparentados": alterados,
        "vinculos_artigo_8_remanescentes": 0,
    }
    return doc


def main() -> int:
    if not DOC_PATH.exists():
        raise RuntimeError(f"Arquivo não encontrado: {DOC_PATH}")

    doc = json.loads(DOC_PATH.read_text(encoding="utf-8"))
    doc = normalizar(doc)
    DOC_PATH.write_text(
        json.dumps(doc, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )

    if MANIFEST_PATH.exists():
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        entrada = manifest.setdefault("normas", {}).setdefault("RDC 67-2007", {})
        entrada["nos"] = len(doc["nos"])
        entrada["regulamento_tecnico"] = {
            "id": ROOT_ID,
            "item_5_1": ITEM_51,
        }
        MANIFEST_PATH.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    if RELATORIO_PATH.exists():
        rel = json.loads(RELATORIO_PATH.read_text(encoding="utf-8"))
        rel.setdefault("validacao", {})["regulamento_tecnico"] = doc["validacao"]["regulamento_tecnico"]
        rel["normalizado_em"] = agora()
        RELATORIO_PATH.write_text(
            json.dumps(rel, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    print(json.dumps(doc["validacao"]["regulamento_tecnico"], ensure_ascii=False, indent=2))
    print("OK: Regulamento Técnico da RDC 67/2007 normalizado fora do Art. 8º.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
