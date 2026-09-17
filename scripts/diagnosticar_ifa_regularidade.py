#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Diagnóstico não destrutivo dos painéis oficiais CADIFA e CBPF de IFA.

Descobre painéis Power BI a partir de páginas oficiais da Anvisa, inspeciona o
modelo de dados e identifica o painel CADIFA pelos campos publicados. Também
inspeciona o painel oficial de certificados de boas práticas.
"""
from __future__ import annotations

from collections import deque
from pathlib import Path
from urllib.parse import urljoin, urlparse, urlunparse, unquote
import gzip
import html as htmlmod
import json
import re
import ssl
import urllib.request
import uuid

OUT = Path("diagnostico-ifa-regularidade")
OUT.mkdir(exist_ok=True)

CADIFA_FONTES = [
    "https://www.gov.br/anvisa/pt-br/assuntos/noticias-anvisa/2024/anvisa-publica-paineis-sobre-carta-de-adequacao-de-dossie-de-insumo-farmaceutico-ativo",
    "https://www.gov.br/anvisa/pt-br/setorregulado/regularizacao/insumos/cadifa",
    "https://www.gov.br/anvisa/pt-br/centraisdeconteudo/publicacoes/medicamentos/publicacoes-de-insumos-farmaceuticos",
]
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
            "url_final": resp.geturl(),
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


def normalizar_html(texto: str) -> str:
    for _ in range(2):
        texto = htmlmod.unescape(texto)
        texto = texto.replace("\\u0026", "&").replace("\\/", "/")
    return texto


def extrair_urls(texto: str, base: str) -> list[str]:
    texto = normalizar_html(texto)
    candidatos = []
    candidatos += re.findall(r'https?://[^"\'<>\s]+', texto, flags=re.I)
    candidatos += re.findall(r'href=["\']([^"\']+)["\']', texto, flags=re.I)
    candidatos += re.findall(r'(?:url|href)\s*[:=]\s*["\']([^"\']+)["\']', texto, flags=re.I)
    saida = []
    for bruto in candidatos:
        u = unquote(htmlmod.unescape(bruto)).strip().rstrip(".,);]}")
        if not u or u.startswith(("#", "javascript:", "mailto:")):
            continue
        u = urljoin(base, u)
        if u not in saida:
            saida.append(u)
    return saida


def eh_anvisa(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host in {"www.gov.br", "gov.br"} and "/anvisa/" in url.lower()


def interessante_cadifa(url: str) -> bool:
    s = unquote(url).lower()
    return any(x in s for x in ("cadifa", "insumo", "farmaceut", "painel", "powerbi", "publicacoes-de-insumos"))


def descobrir_powerbi_cadifa() -> tuple[list[str], dict]:
    fila = deque((u, 0) for u in CADIFA_FONTES)
    visitados = set()
    powerbis = []
    paginas = []
    erros = []

    while fila and len(visitados) < 35:
        url, nivel = fila.popleft()
        if url in visitados or nivel > 2:
            continue
        visitados.add(url)
        try:
            texto, meta = abrir(url)
        except Exception as exc:
            erros.append({"url": url, "erro": f"{type(exc).__name__}: {exc}"})
            continue
        links = extrair_urls(texto, meta.get("url_final") or url)
        paginas.append({"url": url, "url_final": meta.get("url_final"), "nivel": nivel, "links": len(links)})
        for link in links:
            if "app.powerbi.com" in link.lower():
                if link not in powerbis:
                    powerbis.append(link)
                continue
            if nivel < 2 and eh_anvisa(link) and interessante_cadifa(link) and link not in visitados:
                fila.append((link, nivel + 1))

    return powerbis, {"visitados": sorted(visitados), "paginas": paginas, "erros": erros}


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


def pontuar_cadifa(diag: dict) -> int:
    palavras = " ".join(
        [e.get("entidade", "") + " " + " ".join(e.get("campos", [])) for e in diag.get("entidades", [])]
    ).lower()
    pontos = 0
    for termo, peso in (("cadifa", 5), ("detentor", 4), ("insumo", 3), ("ifa", 3), ("revis", 3), ("carta", 2), ("válid", 2), ("valid", 2)):
        if termo in palavras:
            pontos += peso
    if "notifica" in palavras or "pós-registro" in palavras or "pos-registro" in palavras:
        pontos -= 4
    return pontos


def main():
    resultado = {"fontes": {}, "erros": []}

    try:
        urls, meta_descoberta = descobrir_powerbi_cadifa()
        resultado["fontes"]["cadifa_descoberta"] = {
            "fontes": CADIFA_FONTES,
            "paineis_encontrados": urls,
            "meta": meta_descoberta,
        }
        candidatos = []
        for i, url in enumerate(urls, 1):
            try:
                diag = diagnosticar_painel(f"cadifa_candidato_{i}", url, CADIFA_FONTES[0])
                diag["pontuacao_cadifa"] = pontuar_cadifa(diag)
                candidatos.append(diag)
            except Exception as exc:
                resultado["erros"].append({"fonte": f"cadifa_candidato_{i}", "url": url, "erro": f"{type(exc).__name__}: {exc}"})
        if candidatos:
            candidatos.sort(key=lambda x: x.get("pontuacao_cadifa", 0), reverse=True)
            resultado["fontes"]["cadifa_candidatos"] = candidatos
            if candidatos[0].get("pontuacao_cadifa", 0) >= 5:
                resultado["fontes"]["cadifa"] = candidatos[0]
            else:
                resultado["erros"].append({"fonte": "cadifa", "erro": "Painéis encontrados, mas nenhum modelo apresentou campos suficientes para identificação segura como Painel CADIFA"})
        else:
            resultado["erros"].append({"fonte": "cadifa", "erro": "Nenhum Power BI foi localizado seguindo apenas páginas oficiais da Anvisa"})
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
    descoberta = resultado["fontes"].get("cadifa_descoberta", {})
    linhas += ["## Descoberta CADIFA", "", f"Power BIs encontrados: **{len(descoberta.get('paineis_encontrados', []))}**", ""]
    for u in descoberta.get("paineis_encontrados", []):
        linhas.append(f"- `{u}`")
    linhas.append("")
    if resultado["erros"]:
        linhas += ["## Erros", "", "```json", json.dumps(resultado["erros"], ensure_ascii=False, indent=2), "```", ""]
    (OUT / "RESUMO.md").write_text("\n".join(linhas), encoding="utf-8")
    print("\n".join(linhas))

    if "cadifa" not in resultado["fontes"] and "cbpf_ifa" not in resultado["fontes"]:
        raise SystemExit("Nenhum painel pôde ser diagnosticado")


if __name__ == "__main__":
    main()
