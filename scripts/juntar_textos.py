#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Junta os .txt gerados por extrair_textos.py em documentos prontos para colar.

Nao altera o texto: apenas concatena, na ordem, com um cabecalho por norma.

Por que fatiar: o conjunto completo passa de varios MB e nao cabe em uma
mensagem. O script corta em partes de tamanho definido, sempre em quebra de
linha, e marca continuacao quando uma norma atravessa duas partes.

Uso:
    python scripts/juntar_textos.py
    python scripts/juntar_textos.py --limite 60000
    python scripts/juntar_textos.py --por-norma
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
ENTRADA_PADRAO = BASE / "textos"
SAIDA_PADRAO = BASE / "documento"

LIMITE_PADRAO = 80_000  # caracteres por parte

# Ordem dos grupos no documento. O prefixo do norma_id decide o grupo.
GRUPOS = [
    ("lei-municipal",       "LEIS MUNICIPAIS"),
    ("decreto-municipal",   "DECRETOS MUNICIPAIS"),
    ("portaria-sms",        "PORTARIAS SMS"),
    ("portaria-cvs",        "PORTARIAS CVS"),
    ("protocolo",           "PROTOCOLOS MUNICIPAIS"),
    ("lei-estadual",        "LEIS ESTADUAIS"),
    ("lei-federal",         "LEIS FEDERAIS"),
    ("decreto-lei",         "DECRETOS-LEI FEDERAIS"),
    ("decreto-federal",     "DECRETOS FEDERAIS"),
    ("rdc-anvisa",          "RDC ANVISA"),
    ("in-anvisa",           "INSTRUCOES NORMATIVAS ANVISA"),
    ("re-anvisa",           "RESOLUCOES-RE ANVISA"),
    ("resolucao-anvisa",    "RESOLUCOES ANVISA"),
    ("portaria-svs",        "PORTARIAS SVS/MS"),
    ("portaria-gm",         "PORTARIAS GM/MS"),
    ("portaria-mj",         "PORTARIAS MJ"),
    ("portaria-inmetro",    "PORTARIAS INMETRO"),
    ("resolucao-conjunta",  "RESOLUCOES CONJUNTAS"),
    ("resolucao-antt",      "RESOLUCOES ANTT"),
    ("nr-",                 "NORMAS REGULAMENTADORAS"),
]
OUTROS = "OUTRAS NORMAS"


def grupo_de(norma_id: str) -> tuple[int, str]:
    for i, (pref, rotulo) in enumerate(GRUPOS):
        if norma_id.startswith(pref):
            return i, rotulo
    return len(GRUPOS), OUTROS


def coletar(entrada: Path) -> list[dict]:
    itens = []
    for p in sorted(entrada.glob("*.txt")):
        nid = p.stem.split("--")[0]
        ordem, rotulo = grupo_de(nid)
        texto = p.read_text(encoding="utf-8")
        itens.append({"arquivo": p.name, "norma_id": nid, "grupo": rotulo,
                      "ordem": ordem, "texto": texto, "chars": len(texto)})
    itens.sort(key=lambda x: (x["ordem"], x["norma_id"], x["arquivo"]))
    return itens


def cabecalho(it: dict, parte: int | None = None, total: int | None = None) -> str:
    cont = f"  [PARTE {parte} DE {total} DESTA NORMA]" if parte else ""
    return (f"\n\n{'=' * 78}\n"
            f"### NORMA: {it['norma_id']}{cont}\n"
            f"### GRUPO: {it['grupo']}\n"
            f"### ARQUIVO: {it['arquivo']}  ({it['chars']} caracteres)\n"
            f"{'=' * 78}\n\n")



def gerar(entrada: Path, saida: Path, limite: int, por_norma: bool) -> dict:
    itens = coletar(entrada)
    saida.mkdir(parents=True, exist_ok=True)
    for antigo in saida.glob("parte-*.md"):
        antigo.unlink()
    for antigo in saida.glob("norma-*.md"):
        antigo.unlink()

    print(f"Entrada: {entrada}")
    print(f"Saida  : {saida}")
    print(f"Normas encontradas: {len(itens)}")
    if not itens:
        print("\nNenhum .txt encontrado. Rode antes: python scripts/extrair_textos.py")
        (saida / "INDICE.md").write_text(
            "# Indice\n\nNenhum texto extraido encontrado em `textos/`.\n", encoding="utf-8")
        return {"normas": 0, "partes": 0, "arquivos": []}

    gerados = []

    if por_norma:
        for it in itens:
            alvo = saida / f"norma-{it['norma_id']}.md"
            alvo.write_text(cabecalho(it).lstrip() + it["texto"] + "\n", encoding="utf-8")
            gerados.append({"arquivo": alvo.name, "chars": alvo.stat().st_size,
                            "normas": [it["norma_id"]]})
            print(f"  {alvo.name}  ({it['chars']} caracteres)")
    else:
        buf, buf_chars, buf_normas, n_parte = [], 0, [], 1

        def fechar():
            nonlocal buf, buf_chars, buf_normas, n_parte
            if not buf:
                return
            alvo = saida / f"parte-{n_parte:02d}.md"
            corpo = "".join(buf).strip() + "\n"
            alvo.write_text(
                f"# Textos de legislacao — parte {n_parte:02d}\n"
                f"<!-- normas nesta parte: {', '.join(buf_normas)} -->\n" + corpo,
                encoding="utf-8")
            gerados.append({"arquivo": alvo.name, "chars": len(corpo),
                            "normas": list(buf_normas)})
            print(f"  {alvo.name}  ({len(corpo)} caracteres, {len(buf_normas)} norma(s))")
            buf, buf_chars, buf_normas = [], 0, []
            n_parte += 1

        # Preenchimento continuo: percorre as linhas e so fecha a parte quando
        # o limite e atingido. Assim todas as partes ficam cheias, e uma norma
        # grande atravessa varias partes com cabecalho de continuacao.
        for it in itens:
            linhas_norma = it["texto"].split("\n")
            trecho = 1
            cab = cabecalho(it)
            if buf and buf_chars + len(cab) + 200 > limite:
                fechar()
                cab = cabecalho(it)
            buf.append(cab)
            buf_chars += len(cab)
            buf_normas.append(it["norma_id"])
            for linha in linhas_norma:
                n = len(linha) + 1
                if buf_chars + n > limite:
                    fechar()
                    trecho += 1
                    cont = (f"\n{'=' * 78}\n"
                            f"### NORMA: {it['norma_id']}  [CONTINUACAO — trecho {trecho}]\n"
                            f"### GRUPO: {it['grupo']}\n"
                            f"{'=' * 78}\n\n")
                    buf.append(cont)
                    buf_chars += len(cont)
                    buf_normas.append(f"{it['norma_id']} (cont. {trecho})")
                buf.append(linha + "\n")
                buf_chars += n
        fechar()

    total = sum(g["chars"] for g in gerados)
    linhas = [
        "# Indice dos documentos gerados", "",
        f"- Gerado em: {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}",
        f"- Normas: {len(itens)}",
        f"- Arquivos gerados: {len(gerados)}",
        f"- Total: {total:,} caracteres".replace(",", "."),
        "",
        "Cole um arquivo por mensagem, na ordem.", "",
        "| # | Arquivo | Caracteres | Normas |", "|---|---|---|---|",
    ]
    for i, g in enumerate(gerados, 1):
        linhas.append(f"| {i} | {g['arquivo']} | {g['chars']} | {', '.join(g['normas'])} |")
    linhas += ["", "## Normas incluidas", "",
               "| Norma | Grupo | Caracteres |", "|---|---|---|"]
    for it in itens:
        linhas.append(f"| {it['norma_id']} | {it['grupo']} | {it['chars']} |")
    (saida / "INDICE.md").write_text("\n".join(linhas) + "\n", encoding="utf-8")

    res = {"normas": len(itens), "partes": len(gerados),
           "total_chars": total, "arquivos": gerados}
    (saida / "indice.json").write_text(
        json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n{len(gerados)} arquivo(s), {total:,} caracteres no total.".replace(",", "."))
    print(f"Indice: {saida / 'INDICE.md'}")
    return res


def main() -> int:
    ap = argparse.ArgumentParser(description="Junta os textos extraidos em documentos para colar.")
    ap.add_argument("--entrada", default=str(ENTRADA_PADRAO))
    ap.add_argument("--saida", default=str(SAIDA_PADRAO))
    ap.add_argument("--limite", type=int, default=LIMITE_PADRAO,
                    help=f"caracteres por parte (padrao {LIMITE_PADRAO})")
    ap.add_argument("--por-norma", action="store_true",
                    help="gera um arquivo por norma em vez de partes fatiadas")
    a = ap.parse_args()
    gerar(Path(a.entrada), Path(a.saida), a.limite, a.por_norma)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
