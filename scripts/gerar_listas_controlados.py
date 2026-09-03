#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Gera base estruturada das listas vigentes da Portaria SVS/MS 344/1998.

Fonte oficial atual: texto consolidado publicado pela Anvisa na RDC 1.036/2026,
que atualiza o Anexo I da Portaria 344/98.

Saida:
  dados/controlados_portaria344/listas.json
  dados/controlados_portaria344/manifest.json

Principios:
- lista (A1, A2, A3, B1, B2, C1, C2, C3, C5, D1, D2, E, F1-F4) faz parte
  da identidade do registro;
- o cabecalho-pai "LISTA - F" nao e tratado como lista de substancias; F1-F4
  sao reconhecidas como sublistas, inclusive quando o titulo vem na mesma linha;
- numeracao de substancia so e reconhecida dentro de uma LISTA valida;
- ADENDO e seus itens sao guardados em colecao separada e nao colidem com a
  numeracao das substancias;
- nenhum valor numerico no corpo de um adendo vira substancia por inferencia.
"""
from __future__ import annotations

import hashlib
import json
import re
import urllib.request
from datetime import datetime, timezone
from html import unescape
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
SAIDA = BASE / "dados" / "controlados_portaria344"
URL_FONTE = (
    "https://anvisalegis.datalegis.net/action/ActionDatalegis.php?"
    "acao=abrirTextoAto&codTipo=&cod_menu=1696&cod_modulo=134&desItem=&"
    "desItemFim=&numeroAto=00001036&orgao=RDC%2FDC%2FANVISA%2FMS&"
    "pesquisa=true&seqAto=000&tipo=RDC&valorAno=2026"
)
NORMA_FONTE = "RDC Anvisa 1.036/2026"
NORMA_BASE = "Portaria SVS/MS 344/1998 - Anexo I"

RE_TAG = re.compile(r"<[^>]+>")
# Cabecalhos oficiais simples: LISTA - A1, LISTA - E etc.
RE_LISTA_SIMPLES = re.compile(r"^LISTA\s*[-–—]\s*(A1|A2|A3|B1|B2|C1|C2|C3|C5|D1|D2|E)\s*$", re.I)
# Na Lista F existe um cabecalho-pai "LISTA - F" e depois sublistas no formato
# "LISTA F1 - SUBSTANCIAS ENTORPECENTES". So F1-F4 sao unidades consultaveis.
RE_LISTA_F = re.compile(r"^LISTA\s*[-–—]?\s*(F[1-4])(?:\s*[-–—:]\s*(.+))?\s*$", re.I)
RE_LISTA_F_PAI = re.compile(r"^LISTA\s*[-–—]\s*F\s*$", re.I)
RE_SUBSTANCIA = re.compile(r"^(\d+)\.\s+(.+)$")
RE_ADENDO = re.compile(r"^ADENDO\s*:?\s*$", re.I)
RE_ITEM_ADENDO = re.compile(r"^(\d+(?:\.\d+)*)\)??\.?\s+(.+)$")
LISTAS_ESPERADAS = {"A1","A2","A3","B1","B2","C1","C2","C3","C5","D1","D2","E","F1","F2","F3","F4"}


def baixar() -> tuple[str, dict]:
    req = urllib.request.Request(URL_FONTE, headers={"User-Agent": "base-vigilancia/1.0"})
    with urllib.request.urlopen(req, timeout=120) as r:
        bruto = r.read()
        meta = {
            "data_fonte": r.headers.get("Last-Modified") or r.headers.get("Date") or "nao informada",
            "etag": r.headers.get("ETag"),
        }
    for enc in ("utf-8", "windows-1252", "latin-1"):
        try:
            return bruto.decode(enc), meta
        except UnicodeDecodeError:
            pass
    return bruto.decode("utf-8", errors="replace"), meta


def html_para_linhas(html: str) -> list[str]:
    x = re.sub(r"</?(?:p|div|li|tr|td|th|br|h\d)\b[^>]*>", "\n", html, flags=re.I)
    x = unescape(RE_TAG.sub(" ", x)).replace("\xa0", " ")
    linhas = []
    for ln in x.splitlines():
        ln = re.sub(r"\s+", " ", ln).strip()
        if ln:
            linhas.append(ln)
    return linhas


def id_registro(lista: str, tipo: str, numero: str) -> str:
    return f"portaria-344-1998::anexo-i::lista-{lista.lower()}::{tipo}::{numero.lower()}"


def nova_lista(listas: dict, codigo: str, titulo: str = "") -> None:
    listas.setdefault(codigo, {
        "id": f"portaria-344-1998::anexo-i::lista-{codigo.lower()}",
        "lista": codigo,
        "titulo": titulo.strip(),
        "substancias": [],
        "adendos": [],
    })
    if titulo.strip() and not listas[codigo]["titulo"]:
        listas[codigo]["titulo"] = titulo.strip()


def parsear(linhas: list[str]) -> dict:
    listas: dict[str, dict] = {}
    atual = None
    modo_adendo = False
    titulo_pendente = []

    for linha in linhas:
        # O cabecalho geral da familia F nao deve alterar a lista corrente nem
        # gerar um registro "F". As unidades normativas consultaveis sao F1-F4.
        if RE_LISTA_F_PAI.match(linha):
            atual = None
            modo_adendo = False
            titulo_pendente = []
            continue

        mf = RE_LISTA_F.match(linha)
        if mf:
            atual = mf.group(1).upper()
            titulo_inline = (mf.group(2) or "").strip()
            nova_lista(listas, atual, titulo_inline)
            modo_adendo = False
            titulo_pendente = []
            continue

        m = RE_LISTA_SIMPLES.match(linha)
        if m:
            atual = m.group(1).upper()
            nova_lista(listas, atual)
            modo_adendo = False
            titulo_pendente = []
            continue

        if not atual:
            continue

        if RE_ADENDO.match(linha):
            modo_adendo = True
            continue

        if not listas[atual]["substancias"] and not modo_adendo:
            if linha.upper().startswith("LISTA "):
                continue
            if linha.startswith("(") and linha.endswith(")"):
                if titulo_pendente and not listas[atual]["titulo"]:
                    listas[atual]["titulo"] = " ".join(titulo_pendente)
                continue

        if modo_adendo:
            ma = RE_ITEM_ADENDO.match(linha)
            if ma:
                numero, texto = ma.group(1), ma.group(2).strip()
                listas[atual]["adendos"].append({
                    "id": id_registro(atual, "adendo", numero),
                    "lista": atual,
                    "tipo": "adendo",
                    "numero": numero,
                    "texto": texto,
                })
            elif listas[atual]["adendos"]:
                listas[atual]["adendos"][-1]["texto"] += " " + linha
            continue

        ms = RE_SUBSTANCIA.match(linha)
        if ms:
            numero, nome = ms.group(1), ms.group(2).strip()
            listas[atual]["substancias"].append({
                "id": id_registro(atual, "substancia", numero),
                "lista": atual,
                "tipo": "substancia",
                "numero": numero,
                "nome": nome,
            })
            continue

        if not listas[atual]["substancias"] and not modo_adendo:
            if not linha.upper().startswith("MINISTERIO") and not linha.upper().startswith("AGENCIA"):
                titulo_pendente.append(linha)
                if not listas[atual]["titulo"]:
                    listas[atual]["titulo"] = " ".join(titulo_pendente)

    return listas


def validar(listas: dict[str, dict]) -> None:
    faltantes = sorted(LISTAS_ESPERADAS - set(listas))
    extras = sorted(set(listas) - LISTAS_ESPERADAS)
    if faltantes:
        raise RuntimeError("Listas ausentes na fonte: " + ", ".join(faltantes))
    if extras:
        raise RuntimeError("Listas inesperadas na extracao: " + ", ".join(extras))

    ids = []
    total_substancias = 0
    for codigo, obj in listas.items():
        if not obj["substancias"]:
            raise RuntimeError(f"Lista {codigo} sem substancias extraidas")
        total_substancias += len(obj["substancias"])
        ids.extend(x["id"] for x in obj["substancias"])
        ids.extend(x["id"] for x in obj["adendos"])

    repetidos = sorted({x for x in ids if ids.count(x) > 1})
    if repetidos:
        raise RuntimeError("IDs duplicados: " + ", ".join(repetidos[:20]))
    if total_substancias < 300:
        raise RuntimeError(f"Extracao suspeita: apenas {total_substancias} substancias")


def gerar() -> dict:
    html, meta = baixar()
    linhas = html_para_linhas(html)
    listas = parsear(linhas)
    validar(listas)

    SAIDA.mkdir(parents=True, exist_ok=True)
    gerado_em = datetime.now(timezone.utc).isoformat()
    payload = {
        "schema": "controlados-portaria344-v1",
        "norma_base": NORMA_BASE,
        "norma_fonte": NORMA_FONTE,
        "fonte_oficial": URL_FONTE,
        "gerado_em": gerado_em,
        "listas": [listas[k] for k in sorted(listas)],
    }
    serial = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    (SAIDA / "listas.json").write_text(serial, encoding="utf-8")

    total_substancias = sum(len(x["substancias"]) for x in listas.values())
    total_adendos = sum(len(x["adendos"]) for x in listas.values())
    manifest = {
        "schema": payload["schema"],
        "status": "ok",
        "norma_base": NORMA_BASE,
        "norma_fonte": NORMA_FONTE,
        "fonte_oficial": URL_FONTE,
        "data_fonte": meta["data_fonte"],
        "gerado_em": gerado_em,
        "listas": len(listas),
        "substancias": total_substancias,
        "adendos": total_adendos,
        "sha256": hashlib.sha256(serial.encode("utf-8")).hexdigest(),
    }
    if meta.get("etag"):
        manifest["etag_fonte"] = meta["etag"]
    (SAIDA / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"OK: {len(listas)} listas, {total_substancias} substancias, {total_adendos} adendos")
    return manifest


def autoteste() -> None:
    amostra = [
        "LISTA - A1",
        "LISTA DAS SUBSTANCIAS ENTORPECENTES",
        '(Sujeitas a Notificacao de Receita "A")',
        "1. Acetilmetadol",
        "2. Morfina",
        "ADENDO:",
        "1) ficam tambem sob controle:",
        "1.1. os sais e isomeros das substancias acima",
        "LISTA - B1",
        "LISTA DAS SUBSTANCIAS PSICOTROPICAS",
        "1. Alprazolam",
        "LISTA - F",
        "LISTA DAS SUBSTANCIAS DE USO PROSCRITO NO BRASIL",
        "LISTA F1 - SUBSTANCIAS ENTORPECENTES",
        "1. Dimetocaina",
        "LISTA F2 - SUBSTANCIAS PSICOTROPICAS",
        "1. Exemplo F2",
        "LISTA F3 - SUBSTANCIAS PRECURSORAS",
        "1. Exemplo F3",
        "LISTA F4 - OUTRAS SUBSTANCIAS",
        "1. Fenibut",
    ]
    d = parsear(amostra)
    assert d["A1"]["substancias"][0]["nome"] == "Acetilmetadol"
    assert d["A1"]["substancias"][0]["id"] != d["B1"]["substancias"][0]["id"]
    assert d["A1"]["adendos"][0]["tipo"] == "adendo"
    assert "F" not in d
    assert d["F1"]["substancias"][0]["nome"] == "Dimetocaina"
    assert d["F4"]["substancias"][0]["nome"] == "Fenibut"
    assert d["F1"]["titulo"] == "SUBSTANCIAS ENTORPECENTES"
    print("AUTOTESTE OK")


if __name__ == "__main__":
    import sys
    if "--autoteste" in sys.argv:
        autoteste()
    else:
        gerar()
