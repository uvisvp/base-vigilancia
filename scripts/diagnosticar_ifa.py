#!/usr/bin/env python3
"""Diagnóstico não destrutivo das bases públicas de IFA/insumo farmacêutico da Anvisa.

Baixa as fontes oficiais, detecta encoding/delimitador, registra cabeçalhos e uma pequena
amostra. Não publica banco e não altera dados existentes.
"""
from __future__ import annotations

import csv
import io
import json
import os
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE = "https://dados.anvisa.gov.br/dados/"
FONTES = [
    "TA_FABRICANTE_MEDICAMENTO_IFA.CSV",
    "TA_EXPORT_IFA.csv",
    "CICLO_ANALISE_PETICOES_INSUMO_FARMACEUTICO.CSV",
    "FILA_ANALISE_INSUMO FARMACEUTICO.csv",
]
OUT = Path("diagnostico-ifa")
OUT.mkdir(exist_ok=True)


def baixar(nome: str) -> tuple[bytes, dict]:
    url = BASE + urllib.parse.quote(nome)
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "uvisvp-base-vigilancia/1.0 (+https://github.com/uvisvp/base-vigilancia)",
            "Accept": "text/csv,text/plain,*/*",
        },
    )
    with urllib.request.urlopen(req, timeout=90) as resp:
        body = resp.read()
        meta = {
            "url": url,
            "status": getattr(resp, "status", None),
            "content_type": resp.headers.get("Content-Type"),
            "content_length_header": resp.headers.get("Content-Length"),
            "etag": resp.headers.get("ETag"),
            "last_modified": resp.headers.get("Last-Modified"),
            "bytes": len(body),
        }
    return body, meta


def decodificar(body: bytes) -> tuple[str, str]:
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return body.decode(enc), enc
        except UnicodeDecodeError:
            pass
    return body.decode("latin-1", errors="replace"), "latin-1-replace"


def detectar_delimitador(texto: str) -> str:
    amostra = texto[:20000]
    try:
        return csv.Sniffer().sniff(amostra, delimiters=";,|\t,").delimiter
    except csv.Error:
        primeira = next((l for l in texto.splitlines() if l.strip()), "")
        candidatos = [";", ",", "|", "\t"]
        return max(candidatos, key=primeira.count) if primeira else ";"


def limpar(v: str, limite: int = 240) -> str:
    v = re.sub(r"\s+", " ", str(v or "")).strip()
    return v[:limite] + ("…" if len(v) > limite else "")


def inspecionar(nome: str) -> dict:
    body, meta = baixar(nome)
    texto, enc = decodificar(body)
    delim = detectar_delimitador(texto)
    reader = csv.DictReader(io.StringIO(texto), delimiter=delim)
    cabecalho = reader.fieldnames or []
    amostra = []
    for i, row in enumerate(reader):
        amostra.append({k: limpar(v) for k, v in row.items() if k is not None})
        if i >= 4:
            break
    linhas = max(0, texto.count("\n") - 1)
    return {
        "arquivo": nome,
        "meta_http": meta,
        "encoding": enc,
        "delimitador": "TAB" if delim == "\t" else delim,
        "colunas": cabecalho,
        "linhas_aproximadas": linhas,
        "amostra": amostra,
    }


def main() -> None:
    resultado = {
        "gerado_em": datetime.now(timezone.utc).isoformat(),
        "fonte_base": BASE,
        "fontes": [],
    }
    erros = []
    for nome in FONTES:
        print(f"\n=== {nome} ===", flush=True)
        try:
            item = inspecionar(nome)
            resultado["fontes"].append(item)
            print("encoding:", item["encoding"])
            print("delimitador:", repr(item["delimitador"]))
            print("colunas:", json.dumps(item["colunas"], ensure_ascii=False))
            print("linhas_aproximadas:", item["linhas_aproximadas"])
            print("amostra:", json.dumps(item["amostra"][:2], ensure_ascii=False, indent=2))
        except Exception as exc:
            msg = f"{type(exc).__name__}: {exc}"
            erros.append({"arquivo": nome, "erro": msg})
            print("ERRO:", msg, flush=True)
    resultado["erros"] = erros
    (OUT / "diagnostico.json").write_text(json.dumps(resultado, ensure_ascii=False, indent=2), encoding="utf-8")

    md = ["# Diagnóstico das fontes oficiais de IFA — Anvisa", "", f"Gerado em: `{resultado['gerado_em']}`", ""]
    for item in resultado["fontes"]:
        md += [f"## {item['arquivo']}", "", f"- URL: `{item['meta_http']['url']}`", f"- Encoding: `{item['encoding']}`", f"- Delimitador: `{item['delimitador']}`", f"- Linhas aproximadas: **{item['linhas_aproximadas']}**", "", "**Colunas**", "", "```text", " | ".join(item["colunas"]), "```", ""]
        if item["amostra"]:
            md += ["**Primeiro registro (amostra)**", "", "```json", json.dumps(item["amostra"][0], ensure_ascii=False, indent=2), "```", ""]
    if erros:
        md += ["## Erros", "", "```json", json.dumps(erros, ensure_ascii=False, indent=2), "```", ""]
    (OUT / "RESUMO.md").write_text("\n".join(md), encoding="utf-8")

    # Ao menos uma fonte precisa ser inspecionada; falhas parciais ficam documentadas.
    if not resultado["fontes"]:
        raise SystemExit("Nenhuma fonte oficial pôde ser inspecionada.")


if __name__ == "__main__":
    main()
