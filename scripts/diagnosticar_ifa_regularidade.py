#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Diagnóstico não destrutivo dos painéis oficiais CADIFA e CBPF de IFA.

Descobre o link Power BI do Painel CADIFA a partir da página oficial da Anvisa,
inspeciona também o painel oficial de empresas certificadas em Insumos
Farmacêuticos e registra entidades/campos do modelo sem publicar banco.
"""
from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse, urlunparse
import gzip
import html as htmlmod
import json
import re
import ssl
import urllib.request
import uuid

OUT = Path("diagnostico-ifa-regularidade")
OUT.mkdir(exist_ok=True)

CADIFA_FONTE = (
    "https://www.gov.br/anvisa/pt-br/assuntos/noticias-anvisa/2024/"
    "anvisa-publica-paineis-sobre-carta-de-adequacao-de-dossie-de-insumo-farmaceutico-ativo"
)
CBPF_IFA_PAINEL = (
    "https://app.powerbi.com/view?"
    "r=eyJrIjoiNTU3MDE4OTgtYzc5NS00NGRhLWI0ODMtOWUzN2E2Njc5MzdlIiwidCI6ImI2N2FmMjNmLWMzZjMtNGQzNS04MGM3LWI3MDg1ZjVlZGQ4MSJ9"
)
CBPF_FONTE = "https://www.gov.br/anvisa/pt-br/setorregulado/certificados-de-boas-praticas"


def abrir(url: str, headers: dict | None = None) -> tuple[str, dict]:
    req = urllib.request.Request(
        url,
        headers=headers or {
            "User-Agent": "Mozilla/5.0 base-vigilancia",
            "Accept": "text/html,application/json,*/*",
        },
    )
    with urllib.request.urlopen(req, timeout=180, context=ssl._create_unverified_context()) as resp:
        corpo = resp.read()
        if "gzip" in resp.headers.get("Content-Encoding", "").lower():
            corpo = gzip.decompress(corpo)
        return corpo.decode("utf-8", errors="replace"), {
            "status": getattr(resp, "status", None),
            "etag": resp.headers.get("ETag"),
            "last_modified": resp.headers.get("Last-Modified"),
            "content_type": resp.headers.get("Content-Type"),
            "bytes": len(corpo),
        }


def localizar_json(html: str, nome: str):
    prefixo = rf"var\s+{re.escape(nome)}\s*=\s*"
    m = re.search(prefixo + r"JSON\.parse\('((?:\\.|[^'])*)'\)", html, re.DOTALL)
    if m:
        bruto = m.group(1)
        dec = json.loads('"' + bruto.replace('"', '\\"').replace('\\"', '\"') + '"')
        return json.loads(dec)
    m = re.search(prefixo, html, re.DOTALL)
    if m:
        restante = html[m.end():].lstrip()
        return json.JSONDecoder().raw_decode(restante)[0]
    raise RuntimeError(f"Variável {nome} não localizada")


def api_do_cluster(uri: str) -> str:
    p = urlparse(uri)
    partes = (p.hostname or "").split(".")
    primeiro = partes[0].replace("-redirect", "").replace("global-", "")
    partes[0] = primeiro + "-api"
    return urlunparse((p.scheme or "https", ".".join(partes), "", "", "", "")).rstrip("/")


def headers_powerbi(resource_key: str, pagina: str) -> dict:
    return {
        "Accept": "application/json",
        "ActivityId": str(uuid.uuid4()),
        "RequestId": str(uuid.uuid4()),
        "X-PowerBI-ResourceKey": resource_key,
        "Origin": "https://app.powerbi.com",
        "Referer": pagina,
        "User-Agent": "Mozilla/5.0 base-vigilancia",
    }


def extrair_entidades(obj):
    encontrados = []
    vistos = set()

    def andar(x, caminho=""):
        if isinstance(x, dict):
            nome = x.get("name") or x.get("Name")
            props = x.get("properties") or x.get("Properties")
            if nome and isinstance(props, (list, dict)):
                campos = []
                seq = props.values() if isinstance(props, dict) else props
                for p in seq:
                    if isinstance(p, dict):
                        pn = p.get("name") or p.get("Name")
                        if pn:
                            campos.append(str(pn))
                    elif isinstance(p, str):
                        campos.append(p)
                chave = (str(nome), tuple(campos))
                if campos and chave not in vistos:
                    vistos.add(chave)
                    encontrados.append({"entidade": str(nome), "campos": campos, "caminho": caminho})
            for k, v in x.items():
                andar(v, f"{caminho}/{k}")
        elif isinstance(x, list):
            for i, v in enumerate(x):
                andar(v, f"{caminho}/{i}")
        elif isinstance(x, str) and len(x) > 2 and x[:1] in "[{":
            try:
                andar(json.loads(x), caminho + "/json")
            except Exception:
                pass

    andar(obj)
    return encontrados


def achar_powerbi_cadifa() -> tuple[str, dict]:
    texto, meta = abrir(CADIFA_FONTE)
    texto = htmlmod.unescape(texto).replace("\\u0026", "&")
    urls = re.findall(r'https?://app\.powerbi\.com/view\?[^"\'<>\s]+', texto, flags=re.I)
    limpas = []
    for u in urls:
        u = u.rstrip(".,);]")
        if u not in limpas:
            limpas.append(u)
    if not limpas:
        # Links Plone podem vir com &amp; ou redirecionadores; procura hrefs de modo mais amplo.
        hrefs = re.findall(r'href=["\']([^"\']+)["\']', texto, flags=re.I)
        limpas = [htmlmod.unescape(x) for x in hrefs if "powerbi.com" in x.lower()]
    if not limpas:
        raise RuntimeError("Link Power BI do Painel CADIFA não localizado na página oficial")
    # O primeiro painel referido no texto é o de CADIFAs emitidas; o segundo é a fila de notificações.
    return limpas[0], {**meta, "links_powerbi_encontrados": limpas}


def diagnosticar_painel(nome: str, pagina: str, fonte_oficial: str) -> dict:
    html, meta_pagina = abrir(pagina)
    descriptor = localizar_json(html, "resourceDescriptor")
    cluster = localizar_json(html, "clusterAssignmentRecord")
    resource_key = descriptor["k"]
    api = api_do_cluster(cluster["FixedClusterUri"])
    base = f"{api}/public/reports/{resource_key}"
    modelos_txt, _ = abrir(base + "/modelsAndExploration?preferReadOnlySession=true", headers_powerbi(resource_key, pagina))
    schema_txt, _ = abrir(base + "/conceptualschema", headers_powerbi(resource_key, pagina))
    modelos = json.loads(modelos_txt)
    schema = json.loads(schema_txt)
    entidades = extrair_entidades(schema)
    return {
        "painel": nome,
        "fonte_oficial": fonte_oficial,
        "pagina_powerbi": pagina,
        "meta_pagina": meta_pagina,
        "resource_key": resource_key,
        "api": api,
        "modelos": [{"id": m.get("id"), "dbName": m.get("dbName")} for m in modelos.get("models", [])],
        "report_id": modelos.get("exploration", {}).get("reportId"),
        "entidades": entidades,
    }


def main():
    resultado = {"fontes": {}, "erros": []}

    try:
        cadifa_url, meta_cadifa = achar_powerbi_cadifa()
        resultado["fontes"]["cadifa_descoberta"] = {
            "fonte": CADIFA_FONTE,
            "painel": cadifa_url,
            "meta": meta_cadifa,
        }
        resultado["fontes"]["cadifa"] = diagnosticar_painel("cadifa", cadifa_url, CADIFA_FONTE)
    except Exception as exc:
        resultado["erros"].append({"fonte": "cadifa", "erro": f"{type(exc).__name__}: {exc}"})

    try:
        resultado["fontes"]["cbpf_ifa"] = diagnosticar_painel("cbpf_ifa", CBPF_IFA_PAINEL, CBPF_FONTE)
    except Exception as exc:
        resultado["erros"].append({"fonte": "cbpf_ifa", "erro": f"{type(exc).__name__}: {exc}"})

    (OUT / "diagnostico.json").write_text(json.dumps(resultado, ensure_ascii=False, indent=2), encoding="utf-8")

    linhas = ["# Diagnóstico CADIFA + CBPF de IFA", ""]
    for chave in ("cadifa", "cbpf_ifa"):
        item = resultado["fontes"].get(chave)
        if not item:
            continue
        linhas += [f"## {chave}", "", f"Painel: `{item['pagina_powerbi']}`", f"Entidades: **{len(item['entidades'])}**", ""]
        for ent in item["entidades"]:
            linhas += [f"- **{ent['entidade']}**: " + " | ".join(ent["campos"])]
        linhas.append("")
    if resultado["erros"]:
        linhas += ["## Erros", "", "```json", json.dumps(resultado["erros"], ensure_ascii=False, indent=2), "```", ""]
    (OUT / "RESUMO.md").write_text("\n".join(linhas), encoding="utf-8")
    print("\n".join(linhas))

    if "cadifa" not in resultado["fontes"] and "cbpf_ifa" not in resultado["fontes"]:
        raise SystemExit("Nenhum painel pôde ser diagnosticado")


if __name__ == "__main__":
    main()
