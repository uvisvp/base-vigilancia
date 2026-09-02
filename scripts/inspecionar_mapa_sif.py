#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Inspeciona as duas fontes oficiais MAPA/DIPOA do SIF sem publicar banco."""

import csv, hashlib, json, sys
from pathlib import Path
from datetime import datetime, timezone
import requests

FONTES = [
    {
        "id": "estabelecimentos_registrados",
        "nome": "Estabelecimentos Registrados no SIF",
        "url": "https://dados.agricultura.gov.br/dataset/062166e3-b515-4274-8e7d-68aadd64b820/resource/97277e92-264a-4dc0-9aea-f87b8ea93798/download/sigsifestabelecimentosregistradosnosif.csv",
    },
    {
        "id": "relatorio_estabelecimentos",
        "nome": "Relatório de Estabelecimentos",
        "url": "https://dados.agricultura.gov.br/dataset/062166e3-b515-4274-8e7d-68aadd64b820/resource/7d02af92-e3cf-4ae4-af8a-0dad334ffdfa/download/sigsifrelatorioestabelecimentos.csv",
    },
]

OUT = Path("diagnosticos/mapa_sif")

def decode(raw):
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            pass
    raise RuntimeError("Encoding não reconhecido.")

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    resumo = {
        "gerado_em": datetime.now(timezone.utc).isoformat(),
        "orgao": "Ministério da Agricultura e Pecuária — MAPA / DIPOA",
        "fontes": [],
    }

    for fonte in FONTES:
        print("\n===", fonte["nome"], "===")
        r = requests.get(fonte["url"], timeout=180)
        r.raise_for_status()
        raw = r.content
        text, enc = decode(raw)

        try:
            dialect = csv.Sniffer().sniff(text[:20000], delimiters=";,|\t")
            sep = dialect.delimiter
        except Exception:
            sep = ";"

        reader = csv.DictReader(text.splitlines(), delimiter=sep)
        rows = list(reader)
        colunas = reader.fieldnames or []

        item = {
            **fonte,
            "http_status": r.status_code,
            "tamanho_bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "last_modified_http": r.headers.get("Last-Modified") or "data da fonte não informada",
            "encoding_detectado": enc,
            "separador_detectado": sep,
            "quantidade_registros": len(rows),
            "quantidade_colunas": len(colunas),
            "colunas": colunas,
            "exemplos": rows[:3],
        }
        resumo["fontes"].append(item)

        print("Bytes:", len(raw))
        print("Registros:", len(rows))
        print("Colunas:", len(colunas))
        print("Encoding:", enc)
        print("Separador:", repr(sep))
        print("SHA-256:", item["sha256"])
        print("Last-Modified:", item["last_modified_http"])
        print("COLUNAS:")
        for c in colunas:
            print(" -", c)

        (OUT / f'{fonte["id"]}.json').write_text(
            json.dumps(item, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    (OUT / "resumo.json").write_text(
        json.dumps(resumo, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("\nOK: diagnóstico salvo em", OUT)
    return 0

if __name__ == "__main__":
    sys.exit(main())
