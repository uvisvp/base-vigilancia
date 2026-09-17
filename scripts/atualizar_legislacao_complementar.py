#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Atualiza normas complementares do banco legislativo v12 pelo AnvisaLegis.

Escopo:
- RDC 63/2011
- RDC 430/2020
- RDC 204/2006
- IN 62/2020

A RDC 204/2006 possui ANEXO sem número; ele é normalizado como raiz própria
`rdc-204-2006::regulamento-tecnico`, preservando os itens do regulamento fora
do Art. 9º.
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
        "norma_id": "rdc-anvisa-63-2011",
        "norma": "RDC 63-2011",
        "rotulo": "RDC Anvisa nº 63/2011",
        "url": "https://anvisalegis.datalegis.net/action/ActionDatalegis.php?acao=abrirTextoAto&cod_menu=9431&cod_modulo=310&link=S&numeroAto=00000063&orgao=RDC%2FDC%2FANVISA%2FMS&seqAto=000&tipo=RDC&valorAno=2011",
        "data_fonte": "2011-11-25",
        "status_vigencia": "vigente",
        "min_chars": 12000,
        "obrigatorios": ["RESOLUÇÃO-RDC Nº 63", "Art. 35", "Art. 67"],
    },
    {
        "norma_id": "rdc-anvisa-430-2020",
        "norma": "RDC 430-2020",
        "rotulo": "RDC Anvisa nº 430/2020 — texto consolidado",
        "url": "https://anvisalegis.datalegis.net/action/ActionDatalegis.php?acao=abrirTextoAto&cod_menu=9434&cod_modulo=310&numeroAto=00000430&orgao=RDC%2FDC%2FANVISA%2FMS&seqAto=000&tipo=RDC&valorAno=2020",
        "data_fonte": "2020-10-08",
        "status_vigencia": "vigente_com_alteracoes",
        "min_chars": 18000,
        "obrigatorios": ["RDC Nº 430", "Boas Práticas de Distribuição", "Art. 1"],
    },
    {
        "norma_id": "rdc-anvisa-204-2006",
        "norma": "RDC 204-2006",
        "rotulo": "RDC Anvisa nº 204/2006 — texto consolidado e Regulamento Técnico",
        "url": "https://anvisalegis.datalegis.net/action/ActionDatalegis.php?acao=abrirTextoAto&cod_menu=9431&cod_modulo=310&link=S&numeroAto=00000204&orgao=RDC%2FDC%2FANVISA%2FMS&seqAto=002&tipo=RDC&valorAno=2006",
        "data_fonte": "2006-11-14",
        "status_vigencia": "vigente_com_alteracoes",
        "min_chars": 30000,
        "obrigatorios": ["RDC Nº 204", "REGULAMENTO TÉCNICO", "7.2.", "16. RECLAMAÇÃO"],
    },
    {
        "norma_id": "in-anvisa-62-2020",
        "norma": "IN 62-2020",
        "rotulo": "IN Anvisa nº 62/2020",
        "url": "https://anvisalegis.datalegis.net/action/ActionDatalegis.php?acao=abrirTextoAto&cod_menu=9431&cod_modulo=310&link=S&numeroAto=00000062&orgao=DC%2FANVISA%2FMS&seqAto=000&tipo=INM&valorAno=2020",
        "data_fonte": "2020-06-16",
        "status_vigencia": "vigente",
        "min_chars": 3500,
        "obrigatorios": ["IN Nº 62", "item 7.2", "Art. 8"],
    },
]


def agora() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_texto(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def garantir_catalogo() -> bool:
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
        grupo = "in-anvisa" if n["norma_id"].startswith("in-") else "rdc-anvisa"
        linhas.append({
            "norma_id": n["norma_id"],
            "grupo": grupo,
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
    lixo = {
        "[Input]", "[Button]", "Voltar", "COPIAR LINK", "CRIAR TAGS",
        "IMPRIMIR", "PDF", "VER NOTAS DE ALTERAÇÃO", "+ | -",
    }
    return "\n".join(
        ln for ln in texto.splitlines() if ln.strip() not in lixo
    ).strip()


def alteracoes_encontradas(texto: str) -> list[str]:
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
    faltam = [x for x in n["obrigatorios"] if x.casefold() not in texto.casefold()]
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
        "escopo_validacao": "texto integral obtido do AnvisaLegis e estruturado para consulta por dispositivo",
        "extracao": meta_extracao,
    }
    txt.with_suffix(".meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {"norma": n["norma"], "chars": len(texto), "meta": meta}


def aplicar_proveniencia(doc: dict, meta: dict) -> None:
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


def normalizar_rdc204(doc: dict) -> None:
    nos = list(doc.get("nos", []))
    marcador = next(
        (n for n in nos if n.get("tipo") == "bloco" and str(n.get("texto", "")).strip().upper() == "ANEXO"),
        None,
    )
    if not marcador:
        raise RuntimeError("RDC 204-2006: marcador ANEXO sem número não localizado")

    ordem_inicio = int(marcador.get("ordem", 0))
    titulo = next(
        (
            n for n in nos
            if int(n.get("ordem", 0)) > ordem_inicio
            and str(n.get("texto", "")).strip().upper().startswith("REGULAMENTO TÉCNICO")
        ),
        None,
    )
    if not titulo:
        raise RuntimeError("RDC 204-2006: título do Regulamento Técnico não localizado")

    root_id = "rdc-204-2006::regulamento-tecnico"
    old_parent = "rdc-204-2006::artigo::9"
    remover = {marcador.get("id"), titulo.get("id")}
    nos = [n for n in nos if n.get("id") not in remover]

    raiz = {
        "id": root_id,
        "norma": "RDC 204-2006",
        "anexo": None,
        "tipo": "regulamento_tecnico",
        "numero": "geral",
        "rotulo": "Regulamento Técnico",
        "texto": str(titulo.get("texto", "")).strip(),
        "ordem": ordem_inicio,
        "status_vigencia": doc.get("proveniencia", {}).get("status_vigencia", "pendente_validacao"),
        "origem_estrutura": "anexo_sem_numero",
    }

    alterados = 0
    for no in nos:
        if int(no.get("ordem", 0)) <= ordem_inicio:
            continue
        nid = str(no.get("id") or "")
        pai = str(no.get("pai") or "")
        if nid.startswith(old_parent + "::"):
            no["id"] = root_id + nid[len(old_parent):]
            alterados += 1
        if pai == old_parent or pai.startswith(old_parent + "::"):
            no["pai"] = root_id + pai[len(old_parent):]

    nos.append(raiz)
    nos.sort(key=lambda n: (int(n.get("ordem", 0)), str(n.get("id", ""))))
    doc["nos"] = nos

    item_72 = root_id + "::item::7-2"
    if not any(n.get("id") == item_72 for n in nos):
        raise RuntimeError(f"RDC 204-2006: item 7.2 não localizado em {item_72}")

    presos = [
        n.get("id") for n in nos
        if int(n.get("ordem", 0)) > ordem_inicio
        and (
            str(n.get("id") or "").startswith(old_parent + "::")
            or str(n.get("pai") or "").startswith(old_parent)
        )
    ]
    if presos:
        raise RuntimeError("RDC 204-2006: dispositivos ainda presos ao Art. 9º: " + ", ".join(presos[:10]))

    doc.setdefault("validacao", {})["regulamento_tecnico"] = {
        "id": root_id,
        "item_7_2": item_72,
        "ids_reparentados": alterados,
        "vinculos_artigo_9_remanescentes": 0,
    }


def validar_ids(doc: dict, norma: str) -> None:
    ids = [n["id"] for n in doc["nos"] if n.get("estrutural", True)]
    repetidos = sorted({x for x in ids if ids.count(x) > 1})
    doc.setdefault("validacao", {})["ids_estruturais_repetidos"] = repetidos
    if repetidos:
        raise RuntimeError(f"{norma}: IDs estruturais duplicados: {repetidos[:10]}")


def estruturar_normas_alvo() -> dict:
    SAIDA.mkdir(parents=True, exist_ok=True)
    normas_dir = SAIDA / "normas"
    normas_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = SAIDA / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    else:
        manifest = {"schema": "legislacao-hierarquica-v12", "gerado_em": agora(), "normas": {}, "curados": 0}

    manifest.setdefault("schema", "legislacao-hierarquica-v12")
    manifest.setdefault("normas", {})

    for n in NORMAS:
        txt = TEXTOS / f"{n['norma']}--oficial.txt"
        meta = json.loads(txt.with_suffix(".meta.json").read_text(encoding="utf-8"))
        doc = estruturar_texto(n["norma"], txt.read_text(encoding="utf-8"))
        aplicar_proveniencia(doc, meta)
        if n["norma"] == "RDC 204-2006":
            normalizar_rdc204(doc)
        validar_ids(doc, n["norma"])

        destino = normas_dir / f"{slug(n['norma'])}.json"
        destino.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        entrada = {
            "arquivo": destino.name,
            "nos": len(doc["nos"]),
            "sha256_texto": doc.get("sha256_texto"),
            "proveniencia": meta,
        }
        if n["norma"] == "RDC 204-2006":
            entrada["regulamento_tecnico"] = {
                "id": "rdc-204-2006::regulamento-tecnico",
                "item_7_2": "rdc-204-2006::regulamento-tecnico::item::7-2",
            }
        manifest["normas"][n["norma"]] = entrada

    manifest["gerado_em"] = agora()
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def validar_banco() -> dict:
    manifest = json.loads((SAIDA / "manifest.json").read_text(encoding="utf-8"))
    esperadas = {n["norma"] for n in NORMAS}
    ausentes = sorted(esperadas - set(manifest.get("normas", {})))
    if ausentes:
        raise RuntimeError(f"Normas ausentes do manifest final: {ausentes}")

    verificacoes = {
        "RDC 63-2011": "rdc-63-2011::artigo::35",
        "RDC 430-2020": "rdc-430-2020::artigo::1",
        "RDC 204-2006": "rdc-204-2006::regulamento-tecnico::item::7-2",
        "IN 62-2020": "in-62-2020::artigo::1",
    }
    encontrados = {}
    for norma, esperado in verificacoes.items():
        arq = SAIDA / "normas" / f"{slug(norma)}.json"
        doc = json.loads(arq.read_text(encoding="utf-8"))
        if not any(n.get("id") == esperado for n in doc.get("nos", [])):
            raise RuntimeError(f"{norma}: dispositivo de teste ausente: {esperado}")
        encontrados[norma] = esperado

    return {
        "normas_manifest": len(manifest.get("normas", {})),
        "normas_adicionadas": sorted(esperadas),
        "dispositivos_teste": encontrados,
    }


def main() -> int:
    mudou_catalogo = garantir_catalogo()
    resultados = []
    for n in NORMAS:
        resultados.append(gravar_norma(n))
        time.sleep(1.0)

    estruturar_normas_alvo()
    validacao = validar_banco()
    rel = {
        "gerado_em": agora(),
        "fonte": "AnvisaLegis",
        "catalogo_atualizado": mudou_catalogo,
        "normas": [{"norma": x["norma"], "caracteres": x["chars"]} for x in resultados],
        "validacao": validacao,
    }
    (SAIDA / "relatorio-legislacao-complementar.json").write_text(
        json.dumps(rel, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(rel, ensure_ascii=False, indent=2))
    print("OK: legislação complementar atualizada e validada.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
