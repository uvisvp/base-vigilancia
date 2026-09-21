#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Inclui no banco legislativo v12 normas de certificação relacionadas a IFA.

- RDC 362/2020: norma histórica, revogada pela RDC 672/2022.
- RDC 497/2021: procedimentos administrativos de CBPF/CBPDA, vigente com alterações.

Os arquivos são estruturados pelo mesmo motor hierárquico do v12 e incorporados ao
manifest existente, sem substituir as demais normas.
"""
from __future__ import annotations

import csv
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
CATALOGO = FONTES / "normas.csv"
SAIDA = BASE / "dados" / "legislacao_v12"
sys.path.insert(0, str(BASE / "scripts"))
from estruturar_legislacao import estruturar_texto, slug

HEAD = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/128 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/pdf,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.7",
    "Accept-Encoding": "identity",
    "Connection": "close",
}

NORMAS = [
    {
        "norma_id": "rdc-anvisa-653-2022",
        "norma": "RDC 653-2022",
        "grupo": "rdc-anvisa",
        "rotulo": "RDC Anvisa nº 653/2022",
        "url": "https://anvisalegis.datalegis.net/action/ActionDatalegis.php?acao=abrirTextoAto&cod_menu=9428&cod_modulo=310&link=S&numeroAto=00000653&orgao=RDC%2FDC%2FANVISA%2FMS&seqAto=000&tipo=RDC&valorAno=2022",
        "fonte_normativa_oficial": "https://anvisalegis.datalegis.net/action/ActionDatalegis.php?acao=abrirTextoAto&cod_menu=9428&cod_modulo=310&link=S&numeroAto=00000653&orgao=RDC%2FDC%2FANVISA%2FMS&seqAto=000&tipo=RDC&valorAno=2022",
        "fonte_status": "https://anvisalegis.datalegis.net/action/ActionDatalegis.php?acao=abrirTextoAto&cod_menu=9428&cod_modulo=310&link=S&numeroAto=00000653&orgao=RDC%2FDC%2FANVISA%2FMS&seqAto=000&tipo=RDC&valorAno=2022",
        "nota_fonte_texto": "Texto oficial obtido diretamente do AnvisaLegis.",
        "data_fonte": "2022-03-24",
        "status_vigencia": "vigente",
        "status_fonte": "AnvisaLegis",
        "min_chars": 1200,
        "obrig": ["RDC", "653", "Art. 1", "Art. 2", "Art. 3"],
    },
    {
        "norma_id": "rdc-anvisa-670-2022",
        "norma": "RDC 670-2022",
        "grupo": "rdc-anvisa",
        "rotulo": "RDC Anvisa nº 670/2022",
        "url": "https://anvisalegis.datalegis.net/action/ActionDatalegis.php?acao=abrirTextoAto&cod_menu=8542&cod_modulo=310&link=S&numeroAto=00000670&orgao=RDC%2FDC%2FANVISA%2FMS&seqAto=000&tipo=RDC&valorAno=2022",
        "fonte_normativa_oficial": "https://anvisalegis.datalegis.net/action/ActionDatalegis.php?acao=abrirTextoAto&cod_menu=8542&cod_modulo=310&link=S&numeroAto=00000670&orgao=RDC%2FDC%2FANVISA%2FMS&seqAto=000&tipo=RDC&valorAno=2022",
        "fonte_status": "https://anvisalegis.datalegis.net/action/ActionDatalegis.php?acao=abrirTextoAto&cod_menu=8542&cod_modulo=310&link=S&numeroAto=00000670&orgao=RDC%2FDC%2FANVISA%2FMS&seqAto=000&tipo=RDC&valorAno=2022",
        "nota_fonte_texto": "Texto oficial/consolidado obtido diretamente do AnvisaLegis.",
        "data_fonte": "2022-03-30",
        "status_vigencia": "vigente",
        "status_fonte": "AnvisaLegis",
        "min_chars": 3000,
        "obrig": ["RDC", "670", "Art. 7", "Art. 8"],
    },
    {
        "norma_id": "rdc-anvisa-1039-2026",
        "norma": "RDC 1039-2026",
        "grupo": "rdc-anvisa",
        "rotulo": "RDC Anvisa nº 1.039/2026",
        "url": "https://anvisalegis.datalegis.net/action/ActionDatalegis.php?acao=abrirTextoAto&cod_menu=8542&cod_modulo=310&link=S&numeroAto=00001039&orgao=RDC%2FDC%2FANVISA%2FMS&seqAto=000&tipo=RDC&valorAno=2026",
        "fonte_normativa_oficial": "https://anvisalegis.datalegis.net/action/ActionDatalegis.php?acao=abrirTextoAto&cod_menu=8542&cod_modulo=310&link=S&numeroAto=00001039&orgao=RDC%2FDC%2FANVISA%2FMS&seqAto=000&tipo=RDC&valorAno=2026",
        "fonte_status": "https://anvisalegis.datalegis.net/action/ActionDatalegis.php?acao=abrirTextoAto&cod_menu=8542&cod_modulo=310&link=S&numeroAto=00001039&orgao=RDC%2FDC%2FANVISA%2FMS&seqAto=000&tipo=RDC&valorAno=2026",
        "nota_fonte_texto": "Texto oficial/consolidado obtido diretamente do AnvisaLegis.",
        "data_fonte": "2026-08-26",
        "status_vigencia": "vigente",
        "status_fonte": "AnvisaLegis",
        "min_chars": 3000,
        "obrig": ["RDC", "1.039", "Art. 1", "Art. 2"],
    },
]


def agora() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha_b(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha_t(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def baixar(url: str):
    erro = None
    for i in range(4):
        try:
            r = requests.get(url, headers=HEAD, timeout=(20, 120), allow_redirects=True)
            r.raise_for_status()
            if len(r.content) < 500:
                raise RuntimeError("resposta curta")
            return r
        except Exception as exc:
            erro = exc
            if i < 3:
                time.sleep(min(2**i, 8))
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
        texto = "\n".join((p.extract_text() or "") for p in reader.pages)
        return limpar_linhas(texto), "pdf"
    soup = BeautifulSoup(r.content, "html.parser")
    for x in soup(["script", "style", "noscript", "nav", "footer"]):
        x.decompose()
    return limpar_linhas(soup.get_text("\n")), "html"


def validar(n: dict, txt: str):
    if len(txt) < n["min_chars"]:
        raise RuntimeError(f"{n['norma']}: texto curto ({len(txt)})")
    faltantes = [x for x in n["obrig"] if x.casefold() not in txt.casefold()]
    if faltantes:
        raise RuntimeError(f"{n['norma']}: faltam marcadores {faltantes}")


def garantir_catalogo():
    with CATALOGO.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
        fields = list(rows[0]) if rows else ["norma_id", "grupo", "baixar", "url", "rotulo", "observacao"]
    por_id = {r["norma_id"]: r for r in rows}
    mudou = False
    for n in NORMAS:
        url_catalogo = n["fonte_normativa_oficial"]
        observacao = n.get("nota_fonte_texto", "")
        if n["norma_id"] not in por_id:
            novo = {
                "norma_id": n["norma_id"], "grupo": n["grupo"], "baixar": "sim",
                "url": url_catalogo, "rotulo": n["rotulo"], "observacao": observacao,
            }
            rows.append(novo)
            por_id[n["norma_id"]] = novo
            mudou = True
        else:
            r = por_id[n["norma_id"]]
            if r.get("url") != url_catalogo or r.get("rotulo") != n["rotulo"] or r.get("observacao", "") != observacao:
                r.update(url=url_catalogo, rotulo=n["rotulo"], observacao=observacao)
                mudou = True
    if mudou:
        with CATALOGO.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
            w.writeheader()
            w.writerows(rows)
    return mudou


def main() -> int:
    catalogo_atualizado = garantir_catalogo()
    (SAIDA / "normas").mkdir(parents=True, exist_ok=True)
    TEXTOS.mkdir(exist_ok=True)
    manifest_path = SAIDA / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    relatorio = {
        "schema": "relatorio-legislacao-rdc-670-1039-v1",
        "gerado_em": agora(),
        "catalogo_atualizado": catalogo_atualizado,
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
            "fonte_oficial": n["fonte_normativa_oficial"],
            "fonte_texto_utilizada": n["url"],
            "fonte_status": n["fonte_status"],
            "nota_fonte_texto": n["nota_fonte_texto"],
            "url_final": r.url,
            "consultado_em": agora(),
            "data_fonte": n["data_fonte"],
            "tipo_data_fonte": "data_do_ato; situação regulatória conferida nas fontes oficiais indicadas",
            "formato_fonte": formato,
            "sha256_fonte": sha_b(r.content),
            "sha256_texto": sha_t(txt),
            "status_vigencia": n["status_vigencia"],
            "status_fonte": n["status_fonte"],
            "texto": str(txt_path.relative_to(BASE)),
            "data_processamento": agora(),
            "schema": "proveniencia-legislativa-v1",
            "estruturar_alineas": True,
            "escopo_validacao": "texto estruturado para consulta; alterações e revogações específicas seguem a fonte oficial e a proveniência",
        }
        txt_path.with_suffix(".meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

        doc = estruturar_texto(n["norma"], txt)
        doc["proveniencia"] = meta
        for no in doc.get("nos", []):
            no["status_vigencia"] = n["status_vigencia"]

        # O estruturador v12 já diferencia artigos repetidos por ::ocorrencia-N.
        # Parágrafos/incisos/itens ligados a essas ocorrências também precisam herdar
        # um identificador único. Quando a fonte oficial repete um dispositivo (por
        # exemplo, texto original + redação alterada), desambiguamos somente os IDs
        # duplicados, preservando o primeiro ID canônico para o resolvedor do app.
        vistos = {}
        remap = {}
        for no in doc.get("nos", []):
            if not no.get("estrutural", True):
                continue
            oid = no["id"]
            vistos[oid] = vistos.get(oid, 0) + 1
            if vistos[oid] > 1:
                novo_id = f"{oid}::ocorrencia-{vistos[oid]}"
                remap[(oid, vistos[oid])] = novo_id
                no["id"] = novo_id
                no["ocorrencia_id"] = vistos[oid]
                no["id_repetido_na_fonte"] = True

        # Reaponta pais para a ocorrência estrutural imediatamente anterior quando
        # necessário. O primeiro dispositivo mantém o ID canônico.
        ultimo = {}
        for no in doc.get("nos", []):
            pai = no.get("pai")
            if pai:
                no["pai"] = ultimo.get(pai, pai)
            if no.get("estrutural", True):
                base = no["id"].split("::ocorrencia-")[0]
                ultimo[base] = no["id"]

        ids = [x["id"] for x in doc.get("nos", []) if x.get("estrutural", True)]
        if len(ids) != len(set(ids)):
            raise RuntimeError(f"{n['norma']}: IDs estruturais repetidos após desambiguação")

        arquivo = slug(n["norma"]) + ".json"
        (SAIDA / "normas" / arquivo).write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
        manifest["normas"][n["norma"]] = {
            "arquivo": arquivo,
            "nos": len(doc.get("nos", [])),
            "sha256_texto": doc["sha256_texto"],
            "proveniencia": meta,
        }
        relatorio["normas"].append({
            "norma": n["norma"], "arquivo": arquivo, "nos": len(doc.get("nos", [])),
            "chars": len(txt), "status_vigencia": n["status_vigencia"],
            "status_fonte": n["status_fonte"], "fonte_oficial": n["fonte_normativa_oficial"],
        })

    manifest["gerado_em"] = agora()
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    relatorio["total_normas_manifest"] = len(manifest["normas"])
    (SAIDA / "relatorio-legislacao-rdc-670-1039.json").write_text(
        json.dumps(relatorio, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(relatorio, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
