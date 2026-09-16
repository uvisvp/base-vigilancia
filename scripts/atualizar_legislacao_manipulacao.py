#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Atualiza a legislação-base de Farmácia de Manipulação a partir do AnvisaLegis.

Escopo deliberadamente restrito:
- RDC 67/2007 (texto consolidado e todos os anexos disponíveis no AnvisaLegis)
- RDC 87/2008
- RDC 21/2009

O script consulta exclusivamente o AnvisaLegis, preserva a fonte bruta, gera
texto e proveniência, estrutura somente estas três normas e atualiza suas
entradas no manifest sem reprocessar normas não relacionadas.
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import requests

BASE = Path(__file__).resolve().parent.parent
FONTES = BASE / "fontes"
TEXTOS = BASE / "textos"
CATALOGO = FONTES / "normas.csv"
SAIDA = BASE / "dados" / "legislacao_v12"

sys.path.insert(0, str(BASE / "scripts"))
from extrair_textos import extrair_html  # noqa: E402
from estruturar_legislacao import estruturar_texto, slug  # noqa: E402

CABECALHOS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9",
}

NORMAS = [
    {
        "norma_id": "rdc-anvisa-67-2007",
        "norma": "RDC 67-2007",
        "rotulo": "RDC Anvisa nº 67/2007 — texto consolidado e anexos",
        "url": "https://anvisalegis.datalegis.net/action/ActionDatalegis.php?acao=abrirTextoAto&tipo=RDC&numeroAto=00000067&seqAto=002&valorAno=2007&orgao=RDC/DC/ANVISA/MS&codTipo=&desItem=&desItemFim=&cod_menu=1696&cod_modulo=134&pesquisa=true",
        "data_fonte": "2007-10-08",
        "status_vigencia": "vigente_com_alteracoes",
        "min_chars": 100000,
    },
    {
        "norma_id": "rdc-anvisa-87-2008",
        "norma": "RDC 87-2008",
        "rotulo": "RDC Anvisa nº 87/2008",
        "url": "https://anvisalegis.datalegis.net/action/ActionDatalegis.php?acao=abrirTextoAto&codTipo=&cod_menu=1696&cod_modulo=134&desItem=&desItemFim=&numeroAto=00000087&orgao=RDC/DC/ANVISA/MS&pesquisa=true&seqAto=000&tipo=RDC&valorAno=2008",
        "data_fonte": "2008-11-21",
        "status_vigencia": "vigente",
        "min_chars": 4000,
    },
    {
        "norma_id": "rdc-anvisa-21-2009",
        "norma": "RDC 21-2009",
        "rotulo": "RDC Anvisa nº 21/2009",
        "url": "https://anvisalegis.datalegis.net/action/ActionDatalegis.php?acao=abrirTextoAto&cod_menu=8542&cod_modulo=310&link=S&numeroAto=00000021&orgao=RDC/DC/ANVISA/MS&seqAto=000&tipo=RDC&valorAno=2009",
        "data_fonte": "2009-05-20",
        "status_vigencia": "vigente",
        "min_chars": 1800,
    },
]


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_texto(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def agora() -> str:
    return datetime.now(timezone.utc).isoformat()


def garantir_catalogo() -> bool:
    """Inclui no catálogo as normas deste escopo que ainda não estiverem nele."""
    with CATALOGO.open(encoding="utf-8", newline="") as f:
        linhas = list(csv.DictReader(f))
        campos = list(linhas[0].keys()) if linhas else [
            "norma_id", "grupo", "baixar", "url", "rotulo", "observacao"
        ]

    existentes = {x.get("norma_id", "") for x in linhas}
    mudou = False
    for n in NORMAS:
        if n["norma_id"] in existentes:
            continue
        linhas.append({
            "norma_id": n["norma_id"],
            "grupo": "rdc-anvisa",
            "baixar": "sim",
            "url": n["url"],
            "rotulo": n["rotulo"],
            "observacao": "",
        })
        mudou = True

    if mudou:
        with CATALOGO.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=campos, lineterminator="\n")
            w.writeheader()
            w.writerows(linhas)
    return mudou


def baixar(url: str) -> requests.Response:
    ultimo = None
    for tentativa in range(1, 4):
        try:
            r = requests.get(url, headers=CABECALHOS, timeout=90, allow_redirects=True)
            if r.status_code == 200 and len(r.content) >= 500:
                return r
            ultimo = RuntimeError(f"HTTP {r.status_code}; {len(r.content)} bytes")
        except requests.RequestException as e:
            ultimo = e
        if tentativa < 3:
            time.sleep(2 ** tentativa)
    raise RuntimeError(f"Falha ao consultar AnvisaLegis: {ultimo}")


def limpar_residuos_portal(texto: str) -> str:
    linhas = []
    for ln in texto.splitlines():
        if ln.strip() in {"[Input]", "[Button]"}:
            continue
        linhas.append(ln)
    return "\n".join(linhas).strip()


def alteracoes_encontradas(texto: str) -> list[str]:
    """Registra marcadores editoriais presentes na própria fonte, sem inferência."""
    padrao = re.compile(
        r"(?:\(?(?:Reda[cç][aã]o dada|Inclu[ií]d[oa]|Revogad[oa]|Alterad[oa])[^\n]{0,260}\)?|"
        r"Nota:\s*[^\n]{0,300})",
        re.I,
    )
    vistos, saida = set(), []
    for m in padrao.finditer(texto):
        s = re.sub(r"\s+", " ", m.group(0)).strip()
        chave = s.casefold()
        if chave not in vistos:
            vistos.add(chave)
            saida.append(s)
    return saida


def validar_texto(n: dict, texto: str) -> None:
    if len(texto) < n["min_chars"]:
        raise RuntimeError(
            f"{n['norma']}: texto curto demais ({len(texto)} caracteres); publicação interrompida"
        )
    if n["norma"] == "RDC 67-2007":
        obrigatorios = [
            "RESOLUÇÃO-RDC Nº 67",
            "ANEXO I", "ANEXO II", "ANEXO III", "ANEXO IV",
            "ANEXO V", "ANEXO VI", "ANEXO VII",
            "2.7.", "ROTEIRO DE INSPEÇÃO PARA FARMÁCIA",
        ]
    elif n["norma"] == "RDC 87-2008":
        obrigatorios = ["RDC Nº 87", "Art. 7", "ANEXO III", "ANEXO VII"]
    else:
        obrigatorios = ["RDC Nº 21", "ANEXO III", "2.7.3.2"]
    faltam = [x for x in obrigatorios if x.casefold() not in texto.casefold()]
    if faltam:
        raise RuntimeError(f"{n['norma']}: conteúdo obrigatório ausente: {faltam}")


def gravar_norma(n: dict) -> dict:
    print(f"Consultando {n['norma']} no AnvisaLegis...")
    r = baixar(n["url"])

    pasta = FONTES / n["norma_id"]
    pasta.mkdir(parents=True, exist_ok=True)
    bruto = pasta / "texto_bruto.html"
    bruto.write_bytes(r.content)

    texto, meta_extracao = extrair_html(bruto)
    texto = limpar_residuos_portal(texto)
    validar_texto(n, texto)

    TEXTOS.mkdir(parents=True, exist_ok=True)
    txt = TEXTOS / f"{n['norma']}--oficial.txt"
    txt.write_text(texto, encoding="utf-8")

    processado = agora()
    meta = {
        "norma": n["norma"],
        "fonte_oficial": n["url"],
        "url_final": r.url,
        "consultado_em": processado,
        "data_fonte": n["data_fonte"],
        "tipo_data_fonte": "data_do_ato; texto consultado no AnvisaLegis",
        "sha256_fonte": sha256_bytes(r.content),
        "sha256_texto": sha256_texto(texto),
        "alteracoes_encontradas": alteracoes_encontradas(texto),
        "status_vigencia": n["status_vigencia"],
        "texto": str(txt.relative_to(BASE)),
        "data_processamento": processado,
        "schema": "proveniencia-legislativa-v1",
        "estruturar_alineas": True,
        "escopo_validacao": (
            "texto integral e anexos obtidos do AnvisaLegis; validação estrutural específica "
            "para Farmácia de Manipulação"
        ),
        "extracao": meta_extracao,
    }
    txt.with_suffix(".meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {"norma": n["norma"], "chars": len(texto), "meta": meta}


def aplicar_proveniencia(doc: dict, meta: dict) -> None:
    """Aplica às normas-alvo as mesmas regras do estruturador v12."""
    if meta.get("sha256_texto") != doc.get("sha256_texto"):
        raise RuntimeError(f"{meta['norma']}: hash do texto não confere com a proveniência")
    doc["proveniencia"] = meta

    for no in doc["nos"]:
        no["status_vigencia"] = (
            "revogado" if re.search(r"\(Revogad[oa]", no.get("texto", ""), re.I)
            else meta.get("status_vigencia", "pendente_validacao")
        )
        m = re.match(r"^([a-z])\)\s+", no.get("texto", "")) if no.get("tipo") == "bloco" else None
        if m and no.get("pai") and meta.get("estruturar_alineas"):
            no.update(
                tipo="alinea",
                numero=m.group(1),
                rotulo=f"Alínea {m.group(1)}",
                estrutural=True,
            )
            no["id"] = no["pai"] + "::alinea::" + m.group(1)

    contagem = Counter(no["id"] for no in doc["nos"])
    ocorrencias = Counter()
    for no in doc["nos"]:
        if contagem[no["id"]] > 1:
            original = no["id"]
            ocorrencias[original] += 1
            no["id"] = original + "::ocorrencia-" + str(ocorrencias[original])
            no["ambiguidade_na_fonte"] = True
            no["status_vigencia"] = "pendente_validacao"

    ids = [no["id"] for no in doc["nos"] if no.get("estrutural", True)]
    repetidos = sorted({x for x in ids if ids.count(x) > 1})
    doc["validacao"]["ids_estruturais_repetidos"] = repetidos
    if repetidos:
        raise RuntimeError(f"{meta['norma']}: IDs estruturais duplicados: {repetidos[:10]}")


def estruturar_normas_alvo() -> dict:
    """Atualiza apenas as três normas, preservando as demais entradas já publicadas."""
    SAIDA.mkdir(parents=True, exist_ok=True)
    normas_dir = SAIDA / "normas"
    normas_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = SAIDA / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    else:
        manifest = {
            "schema": "legislacao-hierarquica-v12",
            "gerado_em": agora(),
            "normas": {},
            "curados": 0,
        }

    manifest.setdefault("schema", "legislacao-hierarquica-v12")
    manifest.setdefault("normas", {})

    for n in NORMAS:
        txt = TEXTOS / f"{n['norma']}--oficial.txt"
        meta_path = txt.with_suffix(".meta.json")
        texto = txt.read_text(encoding="utf-8")
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        doc = estruturar_texto(n["norma"], texto)
        aplicar_proveniencia(doc, meta)
        destino = normas_dir / f"{slug(n['norma'])}.json"
        destino.write_text(
            json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
        )
        manifest["normas"][n["norma"]] = {
            "arquivo": destino.name,
            "nos": len(doc["nos"]),
            "sha256_texto": doc.get("sha256_texto"),
            "proveniencia": meta,
        }

    manifest["gerado_em"] = agora()
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def validar_banco() -> dict:
    manifest = json.loads((SAIDA / "manifest.json").read_text(encoding="utf-8"))
    esperadas = {n["norma"] for n in NORMAS}
    ausentes = sorted(esperadas - set(manifest.get("normas", {})))
    if ausentes:
        raise RuntimeError(f"Normas ausentes do manifest final: {ausentes}")

    rdc67 = json.loads((SAIDA / "normas" / "rdc-67-2007.json").read_text(encoding="utf-8"))
    anexos = {x.get("numero") for x in rdc67["nos"] if x.get("tipo") == "anexo"}
    esperados_anexos = {"I", "II", "III", "IV", "V", "VI", "VII"}
    if not esperados_anexos.issubset(anexos):
        raise RuntimeError(
            f"RDC 67-2007: anexos estruturados incompletos; encontrados {sorted(anexos)}"
        )

    itens_27_iii = [
        x for x in rdc67["nos"]
        if x.get("anexo") == "III" and x.get("tipo") == "item" and x.get("numero") == "2.7"
    ]
    if not itens_27_iii:
        raise RuntimeError("RDC 67-2007: item 2.7 do Anexo III não foi estruturado")

    return {
        "normas_manifest": len(manifest.get("normas", {})),
        "rdc67_nos": len(rdc67["nos"]),
        "rdc67_anexos": sorted(anexos),
        "item_2_7_anexo_iii": itens_27_iii[0]["id"],
    }


def main() -> int:
    mudou_catalogo = garantir_catalogo()
    resultados = []
    for n in NORMAS:
        resultados.append(gravar_norma(n))
        time.sleep(1.0)

    print("Estruturando somente as normas de manipulação...")
    estruturar_normas_alvo()
    validacao = validar_banco()

    rel = {
        "gerado_em": agora(),
        "fonte": "AnvisaLegis",
        "catalogo_atualizado": mudou_catalogo,
        "normas": [{"norma": x["norma"], "caracteres": x["chars"]} for x in resultados],
        "validacao": validacao,
    }
    (SAIDA / "relatorio-manipulacao.json").write_text(
        json.dumps(rel, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(rel, ensure_ascii=False, indent=2))
    print("OK: legislação de manipulação atualizada e validada.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
