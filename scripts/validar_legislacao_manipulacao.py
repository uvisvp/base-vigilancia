#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Validação final das RDCs de manipulação já extraídas do AnvisaLegis.

Mantém em `alteracoes_encontradas` somente marcações editoriais explícitas da
fonte oficial e exige os oito anexos numerados da RDC 67/2007 antes da
publicação.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
TEXTOS = BASE / "textos"
SAIDA = BASE / "dados" / "legislacao_v12"

NORMAS = ("RDC 67-2007", "RDC 87-2008", "RDC 21-2009")


def marcadores_editoriais(texto: str) -> list[str]:
    vistos: set[str] = set()
    saida: list[str] = []

    # As anotações do AnvisaLegis às vezes são quebradas por hyperlinks no HTML.
    # A compactação serve apenas para detectar o marcador; o texto normativo
    # armazenado continua intocado.
    compacto = re.sub(r"\s+", " ", texto)
    padrao = re.compile(
        r"\((?:Reda[cç][aã]o dada|Inclu[ií]d[oa]|Revogad[oa]|Alterad[oa]) "
        r"pela Resolu[cç][aã]o[^)]{0,500}\)",
        re.I,
    )
    for m in padrao.finditer(compacto):
        s = m.group(0).strip()
        chave = s.casefold()
        if chave not in vistos:
            vistos.add(chave)
            saida.append(s)

    linhas = [x.strip() for x in texto.splitlines() if x.strip()]
    for i, linha in enumerate(linhas):
        if not linha.casefold().startswith("nota:"):
            continue
        s = linha
        # Quando o link da RDC citada foi separado em outra linha pelo portal,
        # agrega somente a linha imediatamente seguinte.
        if re.search(r"\bpela\s*$", s, re.I) and i + 1 < len(linhas):
            prox = linhas[i + 1]
            if re.search(r"\bResolu[cç][aã]o\b|\bRDC\b", prox, re.I):
                s += " " + prox
        s = re.sub(r"\s+", " ", s).strip()
        chave = s.casefold()
        if chave not in vistos:
            vistos.add(chave)
            saida.append(s)

    return saida


def atualizar_proveniencia(norma: str) -> None:
    txt_path = TEXTOS / f"{norma}--oficial.txt"
    meta_path = txt_path.with_suffix(".meta.json")
    texto = txt_path.read_text(encoding="utf-8")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["alteracoes_encontradas"] = marcadores_editoriais(texto)
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    slug = norma.lower().replace(" ", "-")
    doc_path = SAIDA / "normas" / f"{slug}.json"
    doc = json.loads(doc_path.read_text(encoding="utf-8"))
    doc["proveniencia"] = meta
    doc_path.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    manifest_path = SAIDA / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["normas"][norma]["proveniencia"] = meta
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def validar_rdc67() -> dict:
    doc_path = SAIDA / "normas" / "rdc-67-2007.json"
    doc = json.loads(doc_path.read_text(encoding="utf-8"))
    anexos = {n.get("numero") for n in doc.get("nos", []) if n.get("tipo") == "anexo"}
    esperados = {"I", "II", "III", "IV", "V", "VI", "VII", "VIII"}
    faltam = sorted(esperados - anexos)
    if faltam:
        raise RuntimeError(f"RDC 67-2007 incompleta: anexos ausentes: {faltam}")

    itens_27 = [
        n for n in doc.get("nos", [])
        if n.get("anexo") == "III" and n.get("tipo") == "item" and n.get("numero") == "2.7"
    ]
    if not itens_27:
        raise RuntimeError("RDC 67-2007: item 2.7 do Anexo III não estruturado")

    return {
        "anexos_confirmados": sorted(esperados),
        "item_2_7_anexo_iii": itens_27[0]["id"],
    }


def atualizar_relatorio(validacao: dict) -> None:
    rel_path = SAIDA / "relatorio-manipulacao.json"
    rel = json.loads(rel_path.read_text(encoding="utf-8"))
    rel.setdefault("validacao", {}).update(validacao)
    rel["validacao"]["rdc67_anexos"] = validacao["anexos_confirmados"]
    rel["validacao"]["fonte_exclusiva"] = "AnvisaLegis"
    rel["validacao"]["metadados_alteracoes"] = "somente marcadores editoriais explícitos da fonte"
    rel_path.write_text(json.dumps(rel, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    for norma in NORMAS:
        atualizar_proveniencia(norma)
    validacao = validar_rdc67()
    atualizar_relatorio(validacao)
    print(json.dumps(validacao, ensure_ascii=False, indent=2))
    print("OK: anexos I a VIII e metadados editoriais validados.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
