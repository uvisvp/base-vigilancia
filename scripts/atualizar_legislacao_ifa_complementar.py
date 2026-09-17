#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Inclui no v12 normas complementares do marco regulatório de IFA/CBPF."""
from __future__ import annotations

import hashlib
import io
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader

BASE = Path(__file__).resolve().parent.parent
FONTES = BASE / "fontes"
TEXTOS = BASE / "textos"
SAIDA = BASE / "dados" / "legislacao_v12"
sys.path.insert(0, str(BASE / "scripts"))
from estruturar_legislacao import estruturar_texto, slug

HEAD = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/128 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/pdf,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.7",
    "Accept-Encoding": "identity",
    "Connection": "close",
}

NORMAS = [
    {
        "norma_id": "rdc-anvisa-362-2020",
        "norma": "RDC 362-2020",
        "rotulo": "RDC Anvisa nº 362/2020 — revogada",
        "url": "https://cvs.saude.sp.gov.br/zip/U_RS-MS-ANVISA-RDC-362_270320.pdf",
        "fonte_oficial": "https://bvsms.saude.gov.br/bvs/saudelegis/anvisa/2020/RDC_362_2020_.pdf",
        "fonte_status": "https://anvisalegis.datalegis.net/action/ActionDatalegis.php?acao=abrirTextoAto&cod_menu=8542&cod_modulo=310&link=S&numeroAto=00000672&orgao=RDC%2FDC%2FANVISA%2FMS&seqAto=000&tipo=RDC&valorAno=2022",
        "nota_fonte_texto": "Espelho institucional do Centro de Vigilância Sanitária do Estado de São Paulo utilizado para extração técnica. A referência normativa oficial permanece BVS/MS; a revogação é conferida na RDC 672/2022 da Anvisa.",
        "data_fonte": "2020-03-27",
        "status_vigencia": "revogada_pela_rdc_672_2022",
        "status_fonte": "Anvisa: RDC 672/2022, art. 12, revogou expressamente a RDC 362/2020; mantida no v12 para histórico regulatório",
        "min_chars": 4000,
        "obrig": ["RDC Nº 362", "Boas Práticas de Fabricação", "insumos farmacêuticos ativos", "Art. 1"],
    },
    {
        "norma_id": "rdc-anvisa-497-2021",
        "norma": "RDC 497-2021",
        "rotulo": "RDC Anvisa nº 497/2021",
        "url": "https://anvisalegis.datalegis.net/action/ActionDatalegis.php?acao=abrirTextoAto&cod_menu=8542&cod_modulo=310&link=S&numeroAto=00000497&orgao=RDC%2FDC%2FANVISA%2FMS&seqAto=000&tipo=RDC&valorAno=2021",
        "fonte_oficial": "https://anvisalegis.datalegis.net/action/ActionDatalegis.php?acao=abrirTextoAto&cod_menu=8542&cod_modulo=310&link=S&numeroAto=00000497&orgao=RDC%2FDC%2FANVISA%2FMS&seqAto=000&tipo=RDC&valorAno=2021",
        "data_fonte": "2021-05-20",
        "status_vigencia": "vigente_com_alteracoes",
        "status_fonte": "AnvisaLegis: texto consolidado vigente com alterações posteriores",
        "min_chars": 12000,
        "obrig": ["RDC Nº 497", "Certificação de Boas Práticas", "Insumos Farmacêuticos Ativos", "Art. 1"],
    },
]


def agora() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha_texto(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def baixar(url: str):
    erro = None
    for tentativa in range(4):
        try:
            r = requests.get(url, headers=HEAD, timeout=(20, 120), allow_redirects=True)
            r.raise_for_status()
            if len(r.content) < 500:
                raise RuntimeError("resposta curta")
            return r
        except Exception as exc:
            erro = exc
            if tentativa < 3:
                time.sleep(min(2 ** tentativa, 8))
    raise RuntimeError(f"Falha ao baixar {url}: {erro}")


def limpar_linhas(txt: str) -> str:
    linhas = []
    for ln in txt.splitlines():
        ln = re.sub(r"\s+", " ", ln).strip()
        if not ln:
            continue
        if ln in {"Voltar", "Imprimir", "Compartilhar:", "Redefinir Cookies"}:
            continue
        ln = re.sub(r"^Artigo\s+(\d+(?:-[A-Z]|[A-Z])?)\s*[º°o]?\s*[-–—]?", r"Art. \1 ", ln, flags=re.I)
        linhas.append(ln)
    return "\n".join(linhas).strip()


def extrair(r):
    ctype = (r.headers.get("content-type") or "").lower()
    if r.url.lower().endswith(".pdf") or "application/pdf" in ctype or r.content[:4] == b"%PDF":
        reader = PdfReader(io.BytesIO(r.content))
        txt = "\n".join((p.extract_text() or "") for p in reader.pages)
        return limpar_linhas(txt), "pdf"
    soup = BeautifulSoup(r.content, "html.parser")
    for tag in soup(["script", "style", "noscript", "nav", "footer"]):
        tag.decompose()
    return limpar_linhas(soup.get_text("\n")), "html"


def validar(n: dict, txt: str) -> None:
    if len(txt) < n["min_chars"]:
        raise RuntimeError(f"{n['norma']}: texto curto ({len(txt)} caracteres)")
    faltantes = [x for x in n["obrig"] if x.casefold() not in txt.casefold()]
    if faltantes:
        raise RuntimeError(f"{n['norma']}: faltam marcadores {faltantes}")


def main() -> int:
    (SAIDA / "normas").mkdir(parents=True, exist_ok=True)
    TEXTOS.mkdir(exist_ok=True)
    manifest_path = SAIDA / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    relatorio = {
        "schema": "relatorio-legislacao-ifa-complementar-v1",
        "gerado_em": agora(),
        "normas": [],
    }

    for n in NORMAS:
        print("Baixando", n["norma"])
        r = baixar(n["url"])
        txt, formato = extrair(r)
        validar(n, txt)

        pasta = FONTES / n["norma_id"]
        pasta.mkdir(parents=True, exist_ok=True)
        (pasta / f"texto_bruto.{formato}").write_bytes(r.content)

        txt_path = TEXTOS / f"{n['norma']}--oficial.txt"
        txt_path.write_text(txt, encoding="utf-8")

        meta = {
            "norma": n["norma"],
            "fonte_oficial": n["fonte_oficial"],
            "fonte_texto_utilizada": n["url"],
            "fonte_status": n.get("fonte_status"),
            "nota_fonte_texto": n.get("nota_fonte_texto"),
            "url_final": r.url,
            "consultado_em": agora(),
            "data_fonte": n["data_fonte"],
            "tipo_data_fonte": "data_do_ato; texto consultado em fonte institucional identificada na proveniência",
            "formato_fonte": formato,
            "sha256_fonte": sha_bytes(r.content),
            "sha256_texto": sha_texto(txt),
            "status_vigencia": n["status_vigencia"],
            "status_fonte": n["status_fonte"],
            "texto": str(txt_path.relative_to(BASE)),
            "data_processamento": agora(),
            "schema": "proveniencia-legislativa-v1",
            "estruturar_alineas": True,
            "escopo_validacao": "texto estruturado para consulta; vigência e alterações registradas segundo as fontes oficiais identificadas na proveniência",
        }
        txt_path.with_suffix(".meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        doc = estruturar_texto(n["norma"], txt)
        doc["proveniencia"] = meta
        for no in doc.get("nos", []):
            no["status_vigencia"] = n["status_vigencia"]

        ids = [x["id"] for x in doc["nos"] if x.get("estrutural", True)]
        repetidos = sorted({x for x in ids if ids.count(x) > 1})
        if repetidos:
            raise RuntimeError(f"{n['norma']}: IDs estruturais repetidos: {repetidos[:10]}")

        arquivo = slug(n["norma"]) + ".json"
        (SAIDA / "normas" / arquivo).write_text(
            json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        manifest["normas"][n["norma"]] = {
            "arquivo": arquivo,
            "nos": len(doc["nos"]),
            "sha256_texto": doc["sha256_texto"],
            "proveniencia": meta,
        }
        relatorio["normas"].append({
            "norma": n["norma"],
            "arquivo": arquivo,
            "nos": len(doc["nos"]),
            "chars": len(txt),
            "status_vigencia": n["status_vigencia"],
            "status_fonte": n["status_fonte"],
            "fonte_oficial": n["fonte_oficial"],
            "fonte_texto_utilizada": n["url"],
            "formato_fonte": formato,
        })

    manifest["gerado_em"] = agora()
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    relatorio["total_normas_manifest"] = len(manifest["normas"])
    (SAIDA / "relatorio-legislacao-ifa-complementar.json").write_text(
        json.dumps(relatorio, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(relatorio, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
