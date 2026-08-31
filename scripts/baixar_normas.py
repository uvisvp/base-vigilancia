#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Baixa os arquivos de legislacao listados em fontes/normas.csv.

Grava o conteudo bruto, sem alterar nada, em:
    fontes/<norma_id>/texto_bruto.html   (ou .pdf)

Principios:
  - so baixa o que esta marcado 'sim' na coluna 'baixar';
  - grava os bytes como vieram; a decodificacao fica com o extrator;
  - falha de rede e registrada, nunca substituida por conteudo inventado;
  - nao regrava arquivo ja existente, salvo com --forcar;
  - pausa entre requisicoes para nao sobrecarregar os portais oficiais.

Uso:
    python scripts/baixar_normas.py
    python scripts/baixar_normas.py --somente rdc-anvisa
    python scripts/baixar_normas.py --forcar
"""
from __future__ import annotations

import argparse
import csv
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

BASE = Path(__file__).resolve().parent.parent
CATALOGO_PADRAO = BASE / "fontes" / "normas.csv"
DESTINO_PADRAO = BASE / "fontes"
RELATORIO_PADRAO = BASE / "fontes" / "relatorio-download"

CABECALHOS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml,application/pdf;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9",
}

TIMEOUT = 60
TENTATIVAS = 3
PAUSA = 1.5          # segundos entre requisicoes
TAMANHO_MINIMO = 500  # resposta menor que isto quase sempre e erro ou bloqueio


def extensao(resp, url: str) -> str:
    tipo = (resp.headers.get("Content-Type") or "").lower()
    if "pdf" in tipo or url.lower().split("?")[0].endswith(".pdf"):
        return ".pdf"
    if resp.content[:5] == b"%PDF-":
        return ".pdf"
    return ".html"


def ler_catalogo(caminho: Path) -> list[dict]:
    if not caminho.exists():
        raise SystemExit(f"Catalogo nao encontrado: {caminho}")
    with caminho.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def baixar_um(url: str) -> requests.Response:
    ultimo = None
    for tentativa in range(1, TENTATIVAS + 1):
        try:
            r = requests.get(url, headers=CABECALHOS, timeout=TIMEOUT, allow_redirects=True)
            if r.status_code == 200:
                return r
            ultimo = RuntimeError(f"HTTP {r.status_code}")
            # 4xx definitivo (404, 403, 401...) nao melhora repetindo.
            if 400 <= r.status_code < 500 and r.status_code not in (408, 429):
                raise ultimo
        except requests.RequestException as e:
            ultimo = e
        if tentativa < TENTATIVAS:
            espera = 2 ** tentativa
            print(f"      tentativa {tentativa} falhou ({ultimo}); aguardando {espera}s")
            time.sleep(espera)
    raise ultimo


def processar(catalogo: Path, destino: Path, relatorio: Path,
              somente: str | None, forcar: bool) -> dict:
    inicio = datetime.now(timezone.utc)
    linhas = ler_catalogo(catalogo)

    fila, ignoradas = [], []
    for l in linhas:
        nid = (l.get("norma_id") or "").strip()
        if not nid:
            continue
        if (l.get("baixar") or "").strip().lower() != "sim":
            ignoradas.append({"norma_id": nid, "motivo": l.get("observacao") or "marcada 'nao' no catalogo"})
            continue
        if somente and not (nid.startswith(somente) or (l.get("grupo") or "") == somente):
            continue
        if not (l.get("url") or "").strip():
            ignoradas.append({"norma_id": nid, "motivo": "sem URL"})
            continue
        fila.append(l)

    print(f"Catalogo : {catalogo}")
    print(f"Destino  : {destino}")
    print(f"Na fila  : {len(fila)}   |   ignoradas: {len(ignoradas)}\n")

    baixadas, falhas, puladas = [], [], []
    for i, l in enumerate(fila, 1):
        nid, url = l["norma_id"].strip(), l["url"].strip()
        pasta = destino / nid
        existentes = list(pasta.glob("texto_bruto.*")) if pasta.exists() else []
        print(f"[{i}/{len(fila)}] {nid}")

        if existentes and not forcar:
            puladas.append({"norma_id": nid, "arquivo": existentes[0].name})
            print("      ja existe; use --forcar para regravar")
            continue

        try:
            r = baixar_um(url)
            if len(r.content) < TAMANHO_MINIMO:
                raise RuntimeError(
                    f"resposta muito pequena ({len(r.content)} bytes) — "
                    f"provavel bloqueio ou pagina de erro; nada foi gravado")
            pasta.mkdir(parents=True, exist_ok=True)
            for antigo in pasta.glob("texto_bruto.*"):
                antigo.unlink()
            alvo = pasta / f"texto_bruto{extensao(r, url)}"
            alvo.write_bytes(r.content)
            reg = {"norma_id": nid, "url": url, "arquivo": str(alvo.relative_to(destino)),
                   "bytes": len(r.content), "http": r.status_code,
                   "content_type": r.headers.get("Content-Type", ""),
                   "url_final": r.url if r.url != url else None,
                   "observacao": l.get("observacao") or None}
            baixadas.append({k: v for k, v in reg.items() if v is not None})
            print(f"      OK  {len(r.content):,} bytes -> {alvo.name}".replace(",", "."))
        except Exception as e:
            falhas.append({"norma_id": nid, "url": url, "erro": str(e),
                           "observacao": l.get("observacao") or ""})
            print(f"      FALHA: {e}")

        if i < len(fila):
            time.sleep(PAUSA)

    fim = datetime.now(timezone.utc)
    res = {
        "gerado_em": fim.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "duracao_s": round((fim - inicio).total_seconds(), 1),
        "na_fila": len(fila), "baixadas": len(baixadas), "puladas": len(puladas),
        "falhas": len(falhas), "ignoradas": len(ignoradas),
        "detalhe_baixadas": baixadas, "detalhe_falhas": falhas,
        "detalhe_puladas": puladas, "detalhe_ignoradas": ignoradas,
    }
    relatorio.parent.mkdir(parents=True, exist_ok=True)
    relatorio.with_suffix(".json").write_text(
        json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")

    md = ["# Relatorio de download", "",
          f"- Gerado em: {res['gerado_em']}", f"- Duracao: {res['duracao_s']} s",
          f"- Na fila: {res['na_fila']}", f"- Baixadas: {res['baixadas']}",
          f"- Ja existiam: {res['puladas']}", f"- Falharam: {res['falhas']}",
          f"- Ignoradas pelo catalogo: {res['ignoradas']}", ""]
    if falhas:
        md += ["## Falharam", "", "| Norma | Motivo | Observacao do catalogo |", "|---|---|---|"]
        md += [f"| {f['norma_id']} | {f['erro']} | {f['observacao']} |" for f in falhas]
        md.append("")
    if baixadas:
        md += ["## Baixadas", "", "| Norma | Bytes | Arquivo |", "|---|---|---|"]
        md += [f"| {b['norma_id']} | {b['bytes']} | {b['arquivo']} |" for b in baixadas]
        md.append("")
    if ignoradas:
        md += ["## Ignoradas pelo catalogo", "", "| Norma | Motivo |", "|---|---|"]
        md += [f"| {g['norma_id']} | {g['motivo']} |" for g in ignoradas]
        md.append("")
    relatorio.with_suffix(".md").write_text("\n".join(md), encoding="utf-8")

    print(f"\nResumo: {res['baixadas']} baixada(s), {res['puladas']} ja existia(m), "
          f"{res['falhas']} falha(s), {res['ignoradas']} ignorada(s).")
    print(f"Relatorio: {relatorio.with_suffix('.md')}")
    return res


def main() -> int:
    ap = argparse.ArgumentParser(description="Baixa os arquivos de legislacao do catalogo.")
    ap.add_argument("--catalogo", default=str(CATALOGO_PADRAO))
    ap.add_argument("--destino", default=str(DESTINO_PADRAO))
    ap.add_argument("--relatorio", default=str(RELATORIO_PADRAO))
    ap.add_argument("--somente", default=None,
                    help="baixa so um grupo ou prefixo (ex.: rdc-anvisa, lei-federal)")
    ap.add_argument("--forcar", action="store_true", help="regrava arquivos ja existentes")
    ap.add_argument("--falhar-se-houver-erro", action="store_true")
    a = ap.parse_args()

    res = processar(Path(a.catalogo), Path(a.destino), Path(a.relatorio), a.somente, a.forcar)
    return 1 if (a.falhar_se_houver_erro and res["falhas"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
