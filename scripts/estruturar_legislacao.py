#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Gera banco legislativo hierarquico a partir dos textos integrais extraidos.

Objetivo: impedir colisoes entre dispositivos de anexos diferentes e impedir
que numeros existentes dentro de tabelas (ex.: 2.000 kcal, 300 mg) sejam
interpretados como numeros de dispositivos juridicos.

Entrada:
  textos/*.txt
  dados/legislacao_curada/*.json (opcional; registros revisados manualmente)

Saida:
  dados/legislacao_v12/normas/<norma>.json
  dados/legislacao_v12/manifest.json

O texto integral continua sendo a fonte de verdade. Este script NAO inventa,
resume ou corrige redacao normativa. Registros curados sao aceitos apenas em
arquivo separado, com fonte e referencia explicitas.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
TEXTOS = BASE / "textos"
CURADA = BASE / "dados" / "legislacao_curada"
SAIDA = BASE / "dados" / "legislacao_v12"

RE_ANEXO = re.compile(r"^\s*ANEXO\s+([IVXLCDM]+|\d+[A-Z]?)\b(?:\s*[-–—:]\s*(.*))?$", re.I)
RE_ARTIGO = re.compile(r"^\s*Art\.?\s*(\d+[A-Z]?)\s*[ºo°.]?\s*(.*)$", re.I)
RE_PARAGRAFO = re.compile(r"^\s*§\s*(\d+[A-Z]?)\s*[ºo°.]?\s*(.*)$", re.I)
RE_PU = re.compile(r"^\s*Par[aá]grafo\s+[uú]nico\.?\s*(.*)$", re.I)
RE_INCISO = re.compile(r"^\s*([IVXLCDM]+)\s*[-–—]\s+(.+)$")
# Item/subitem so e reconhecido quando ha pontuacao juridica e texto logo depois.
# Numeros com separador de milhar/decimal + unidade NAO passam por este padrao.
RE_ITEM = re.compile(r"^\s*(\d+(?:\.\d+){0,4})\s*[.)-]\s+([A-Za-zÀ-ÿ].+)$")
RE_VALOR_TABELA = re.compile(
    r"^\s*[<>≤≥~]?\s*\d{1,3}(?:[.\s]\d{3})*(?:,\d+)?\s*"
    r"(?:kcal|kj|g|mg|µg|mcg|ml|l|%|ui)\b", re.I
)
RE_TITULO_TABELA = re.compile(r"^\s*(TABELA|QUADRO)\s+([A-Z0-9IVXLCDM.-]+)\b", re.I)


def slug(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()
    return s or "norma"


def sha256_texto(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def chave(norma: str, anexo: str | None, tipo: str, numero: str) -> str:
    partes = [slug(norma)]
    if anexo:
        partes.append("anexo-" + slug(anexo))
    partes.extend([slug(tipo), slug(numero)])
    return "::".join(partes)


def novo_no(norma, anexo, tipo, numero, rotulo, texto, ordem, pai=None, meta=None):
    n = {
        "id": chave(norma, anexo, tipo, numero),
        "norma": norma,
        "anexo": anexo,
        "tipo": tipo,
        "numero": str(numero),
        "rotulo": rotulo,
        "texto": texto,
        "ordem": ordem,
    }
    if pai:
        n["pai"] = pai
    if meta:
        n.update(meta)
    return n


def estruturar_texto(norma: str, texto: str) -> dict:
    linhas = [x.strip() for x in texto.splitlines() if x.strip()]
    nos = []
    anexo = None
    artigo_id = None
    paragrafo_id = None
    inciso_id = None
    em_tabela = False
    tabela = None
    ordem = 0

    for linha in linhas:
        ordem += 1

        m = RE_ANEXO.match(linha)
        if m:
            anexo = m.group(1).upper()
            titulo = (m.group(2) or "").strip()
            nid = chave(norma, anexo, "anexo", anexo)
            nos.append({
                "id": nid, "norma": norma, "anexo": anexo,
                "tipo": "anexo", "numero": anexo,
                "rotulo": f"Anexo {anexo}", "texto": titulo,
                "ordem": ordem,
            })
            artigo_id = paragrafo_id = inciso_id = None
            em_tabela = False
            tabela = None
            continue

        m = RE_TITULO_TABELA.match(linha)
        if m:
            tabela = m.group(2)
            em_tabela = True
            nos.append(novo_no(
                norma, anexo, "tabela", tabela,
                f"Tabela {tabela}", linha, ordem,
                pai=chave(norma, anexo, "anexo", anexo) if anexo else None,
            ))
            continue

        # Uma linha que comeca como valor de tabela nunca pode criar dispositivo.
        if em_tabela or RE_VALOR_TABELA.match(linha):
            numero = f"linha-{ordem}"
            nos.append(novo_no(
                norma, anexo, "linha_tabela", numero,
                "Linha de tabela", linha, ordem,
                pai=(chave(norma, anexo, "tabela", tabela) if tabela else
                     (chave(norma, anexo, "anexo", anexo) if anexo else None)),
                meta={"estrutural": False},
            ))
            # Artigo explicito encerra tabela; testado abaixo na proxima linha.
            if not RE_ARTIGO.match(linha):
                continue
            em_tabela = False
            tabela = None

        m = RE_ARTIGO.match(linha)
        if m:
            numero, corpo = m.group(1), m.group(2)
            n = novo_no(norma, anexo, "artigo", numero, f"Art. {numero}", linha, ordem)
            nos.append(n); artigo_id = n["id"]
            paragrafo_id = inciso_id = None
            em_tabela = False; tabela = None
            continue

        m = RE_PU.match(linha)
        if m:
            n = novo_no(norma, anexo, "paragrafo", "unico", "Parágrafo único", linha,
                        ordem, pai=artigo_id)
            nos.append(n); paragrafo_id = n["id"]; inciso_id = None
            continue

        m = RE_PARAGRAFO.match(linha)
        if m:
            numero = m.group(1)
            n = novo_no(norma, anexo, "paragrafo", numero, f"§ {numero}º", linha,
                        ordem, pai=artigo_id)
            nos.append(n); paragrafo_id = n["id"]; inciso_id = None
            continue

        m = RE_INCISO.match(linha)
        if m and artigo_id:
            numero = m.group(1).upper()
            n = novo_no(norma, anexo, "inciso", numero, f"Inciso {numero}", linha,
                        ordem, pai=paragrafo_id or artigo_id)
            nos.append(n); inciso_id = n["id"]
            continue

        m = RE_ITEM.match(linha)
        if m and (anexo or artigo_id):
            numero = m.group(1)
            # Bloqueio adicional: 2.000 / 3.500 etc. sem contexto juridico nao vira item.
            if re.fullmatch(r"\d{1,3}\.\d{3}", numero) and not artigo_id:
                nos.append(novo_no(norma, anexo, "linha_tabela", f"linha-{ordem}",
                                   "Linha de tabela", linha, ordem,
                                   pai=chave(norma, anexo, "anexo", anexo) if anexo else None,
                                   meta={"estrutural": False, "motivo": "numero_tabela"}))
                continue
            n = novo_no(norma, anexo, "item", numero, f"Item {numero}", linha,
                        ordem, pai=inciso_id or paragrafo_id or artigo_id or
                        (chave(norma, anexo, "anexo", anexo) if anexo else None))
            nos.append(n)
            continue

        # Texto nao reconhecido e preservado como bloco, mas nunca recebe identidade
        # juridica baseada apenas em um numero encontrado no conteudo.
        nos.append(novo_no(norma, anexo, "bloco", f"b{ordem}", "Texto", linha, ordem,
                           pai=inciso_id or paragrafo_id or artigo_id or
                           (chave(norma, anexo, "anexo", anexo) if anexo else None),
                           meta={"estrutural": False}))

    ids = [n["id"] for n in nos if n.get("estrutural", True)]
    repetidos = sorted({x for x in ids if ids.count(x) > 1})
    return {
        "schema": "legislacao-hierarquica-v12",
        "norma": norma,
        "sha256_texto": sha256_texto(texto),
        "nos": nos,
        "validacao": {"ids_estruturais_repetidos": repetidos},
    }


def carregar_curados() -> list[dict]:
    itens = []
    if not CURADA.exists():
        return itens
    for arq in sorted(CURADA.glob("*.json")):
        obj = json.loads(arq.read_text(encoding="utf-8"))
        regs = obj if isinstance(obj, list) else obj.get("registros", [])
        for r in regs:
            obrig = {"norma", "anexo", "tipo", "numero", "texto", "fonte_oficial"}
            faltam = sorted(obrig - set(r))
            if faltam:
                raise RuntimeError(f"{arq.name}: registro curado sem {', '.join(faltam)}")
            r = dict(r)
            r["id"] = chave(r["norma"], r.get("anexo"), r["tipo"], str(r["numero"]))
            r["curado"] = True
            r["arquivo_curado"] = arq.name
            itens.append(r)
    return itens


def processar(textos=TEXTOS, saida=SAIDA):
    textos, saida = Path(textos), Path(saida)
    normas_dir = saida / "normas"
    normas_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema": "legislacao-hierarquica-v12",
        "gerado_em": datetime.now(timezone.utc).isoformat(),
        "normas": {},
        "curados": 0,
    }
    documentos = {}
    for arq in sorted(textos.glob("*.txt")):
        norma = arq.stem.split("--", 1)[0]
        texto = arq.read_text(encoding="utf-8")
        doc = estruturar_texto(norma, texto)
        documentos[norma] = doc

    for r in carregar_curados():
        norma = r["norma"]
        doc = documentos.setdefault(norma, {
            "schema": "legislacao-hierarquica-v12", "norma": norma,
            "sha256_texto": None, "nos": [],
            "validacao": {"ids_estruturais_repetidos": []},
        })
        # Curado substitui somente a mesma chave hierarquica, nunca outro anexo.
        doc["nos"] = [n for n in doc["nos"] if n["id"] != r["id"]]
        doc["nos"].append(r)
        manifest["curados"] += 1

    for norma, doc in sorted(documentos.items()):
        ids = [n["id"] for n in doc["nos"] if n.get("estrutural", True)]
        repetidos = sorted({x for x in ids if ids.count(x) > 1})
        doc["validacao"]["ids_estruturais_repetidos"] = repetidos
        if repetidos:
            raise RuntimeError(f"{norma}: IDs estruturais duplicados: {repetidos[:10]}")
        destino = normas_dir / f"{slug(norma)}.json"
        destino.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")),
                           encoding="utf-8")
        manifest["normas"][norma] = {"arquivo": destino.name, "nos": len(doc["nos"]),
                                      "sha256_texto": doc.get("sha256_texto")}

    (saida / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"OK: {len(documentos)} norma(s); {manifest['curados']} registro(s) curado(s).")
    return manifest


def autoteste():
    amostra = """INSTRUÇÃO NORMATIVA\nANEXO II\nTABELA 1\n2.000 kcal Carboidratos 300 g\n300 mg Colesterol\nANEXO XV\n15. Açúcares adicionados\nArt. 17. Aplicam-se as disposições.\n§ 1º Exceção.\nI - primeiro inciso\nANEXO XVI\n15. Bebidas alcoólicas.\n"""
    d = estruturar_texto("IN 75/2020", amostra)
    ids = [n["id"] for n in d["nos"]]
    assert not any("item::2-000" in x for x in ids), ids
    assert len(ids) == len(set(ids)), "IDs colidiram entre anexos"
    assert any("anexo-xv" in x for x in ids)
    assert any("anexo-xvi" in x for x in ids)
    print("AUTOTESTE OK")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--autoteste", action="store_true")
    p.add_argument("--textos", default=str(TEXTOS))
    p.add_argument("--saida", default=str(SAIDA))
    a = p.parse_args()
    if a.autoteste:
        autoteste()
    else:
        processar(a.textos, a.saida)


if __name__ == "__main__":
    main()
