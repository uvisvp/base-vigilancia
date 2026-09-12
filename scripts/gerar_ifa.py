#!/usr/bin/env python3
"""Gera uma visão compacta da base pública de IFA da Anvisa.

Fonte primária: TA_EXPORT_IFA.csv. Esse arquivo público é um export sem cabeçalho.
A visão abaixo usa somente posições cuja semântica foi validada no diagnóstico da
fonte e por confronto com publicações oficiais: assunto, IFA, fabricante do IFA,
peticionante/detentor, CNPJ, país/endereço do fabricante e processo Anvisa.

Não é inferido registro de medicamento e não se assume que processo Anvisa seja
um número de registro. O processo é publicado como identificador regulatório do
registro/petição de IFA disponível nessa fonte.
"""
from __future__ import annotations

import csv
import io
import json
import re
import ssl
import unicodedata
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

FONTE = "https://dados.anvisa.gov.br/dados/TA_EXPORT_IFA.csv"
OUT = Path("dados/ifa")
MANIFEST_RAIZ = Path("dados/manifest.json")


def baixar() -> tuple[bytes, dict]:
    req = urllib.request.Request(
        FONTE,
        headers={
            "User-Agent": "uvisvp-base-vigilancia/1.0 (+https://github.com/uvisvp/base-vigilancia)",
            "Accept": "text/csv,text/plain,*/*",
        },
    )
    contexto_ssl = ssl._create_unverified_context()
    with urllib.request.urlopen(req, timeout=90, context=contexto_ssl) as resp:
        body = resp.read()
        meta = {
            "url": FONTE,
            "data_fonte": resp.headers.get("Last-Modified"),
            "etag_fonte": resp.headers.get("ETag"),
            "content_type": resp.headers.get("Content-Type"),
            "bytes_fonte": len(body),
        }
    return body, meta


def decodificar(body: bytes) -> tuple[str, str]:
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return body.decode(enc), enc
        except UnicodeDecodeError:
            pass
    return body.decode("latin-1", errors="replace"), "latin-1-replace"


def limpar(v: str) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()


def norm(v: str) -> str:
    v = unicodedata.normalize("NFD", limpar(v))
    v = "".join(ch for ch in v if unicodedata.category(ch) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", v.lower()).strip()


def fabricante(raw: str) -> tuple[str, str]:
    raw = limpar(raw)
    m = re.search(r"\s+-\s+(B\.?\s*0*\d+)\s*$", raw, flags=re.I)
    if not m:
        return raw, ""
    codigo = re.sub(r"[.\s]", "", m.group(1)).upper()
    return limpar(raw[: m.start()]), codigo


def linha_valida(row: list[str]) -> bool:
    return len(row) >= 10 and limpar(row[3]) and limpar(row[4]) and re.search(r"\d", limpar(row[9])) is not None


def gerar() -> dict:
    body, meta = baixar()
    texto, encoding = decodificar(body)
    rows = csv.reader(io.StringIO(texto), delimiter=";")
    registros = []
    ignoradas = 0
    for row in rows:
        if not linha_valida(row):
            ignoradas += 1
            continue
        fab_nome, fab_codigo = fabricante(row[4])
        processo = limpar(row[9])
        item = {
            "ifa": limpar(row[3]),
            "fabricante_ifa": fab_nome,
            "codigo_fabricante_ifa": fab_codigo,
            "pais_fabricante": limpar(row[7]),
            "endereco_fabricante": limpar(row[8]),
            "detentor_peticionante": limpar(row[5]),
            "cnpj_detentor_peticionante": re.sub(r"\D", "", limpar(row[6])),
            "processo_anvisa": processo,
            "identificador_tipo": "processo_anvisa",
            "identificador": processo,
            "assunto_codigo": limpar(row[1]),
            "assunto": limpar(row[2]),
        }
        registros.append(item)

    # Elimina duplicações literais da exportação, preservando relações distintas.
    vistos = set()
    unicos = []
    for r in registros:
        chave = (
            norm(r["ifa"]), norm(r["fabricante_ifa"]), r["codigo_fabricante_ifa"],
            re.sub(r"\D", "", r["processo_anvisa"]), r["assunto_codigo"],
        )
        if chave in vistos:
            continue
        vistos.add(chave)
        unicos.append(r)
    unicos.sort(key=lambda r: (norm(r["ifa"]), norm(r["fabricante_ifa"]), re.sub(r"\D", "", r["processo_anvisa"])))

    OUT.mkdir(parents=True, exist_ok=True)
    agora = datetime.now(timezone.utc).isoformat()
    payload = {
        "versao_esquema": 1,
        "gerado_em": agora,
        "fonte": FONTE,
        "observacao": (
            "Visão da exportação pública de IFA da Anvisa. O identificador exposto é o processo Anvisa; "
            "não é tratado como registro de medicamento. A ausência de resultado não prova ausência de regularização por outras vias."
        ),
        "registros": unicos,
    }
    (OUT / "registros.json").write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )

    manifest = {
        "versao_esquema": 1,
        "status": "ok",
        "fonte": FONTE,
        "data_fonte": meta.get("data_fonte"),
        "etag_fonte": meta.get("etag_fonte"),
        "gerado_em": agora,
        "atualizado_em": agora,
        "encoding_fonte": encoding,
        "registros": len(unicos),
        "linhas_ignoradas": ignoradas,
        "arquivo": "registros.json",
        "chaves_consulta": ["ifa", "fabricante_ifa", "codigo_fabricante_ifa", "processo_anvisa", "cnpj_detentor_peticionante"],
        "identificador_regulatorio": "processo_anvisa",
        "limitacao": (
            "TA_EXPORT_IFA é uma exportação pública específica e não representa necessariamente todas as formas atuais de regularização de IFA. "
            "Não vincular automaticamente o fabricante do medicamento acabado ao fabricante do IFA."
        ),
    }
    (OUT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )

    if MANIFEST_RAIZ.exists():
        raiz = json.loads(MANIFEST_RAIZ.read_text(encoding="utf-8"))
        raiz.setdefault("bases", {})["ifa"] = manifest
        raiz["bases"]["ifa"]["arquivo_manifesto"] = "ifa/manifest.json"
        MANIFEST_RAIZ.write_text(
            json.dumps(raiz, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
        )

    print(json.dumps({"registros": len(unicos), "ignoradas": ignoradas, "fonte": FONTE}, ensure_ascii=False))
    return manifest


if __name__ == "__main__":
    gerar()
