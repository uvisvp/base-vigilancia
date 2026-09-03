#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Diagnóstico V2 do painel público e-SISBI / SISBI-POA (MAPA).

Objetivo:
- inspecionar HTML e JavaScript públicos do painel Qlik Sense;
- localizar App ID, openApp(), IDs de objetos, getObject(), createCube(),
  dimensões/medidas/campos e referências à aba Gestão dos Produtos;
- separar recursos Qlik de verdade de bibliotecas genéricas;
- NÃO contornar autenticação, CAPTCHA, sessão ou controles de acesso;
- NÃO criar o banco definitivo.

Saídas:
  diagnosticos/mapa_sisbi/resumo.json
  diagnosticos/mapa_sisbi/assets.json
  diagnosticos/mapa_sisbi/qlik.json
  diagnosticos/mapa_sisbi/referencias_produtos.json
  diagnosticos/mapa_sisbi/amostra_textual.json
"""

from __future__ import annotations

import hashlib
import json
import re
import ssl
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BASE = Path(__file__).resolve().parent.parent
SAIDA = BASE / "diagnosticos" / "mapa_sisbi"

PAINEL = (
    "https://mapa-indicadores.agricultura.gov.br/publico/"
    "extensions/DSN_ESISBI_2/DSN_ESISBI_2.html"
)

UA = (
    "Mozilla/5.0 (compatible; BaseVigilancia/2.0; "
    "+https://github.com/uvisvp/base-vigilancia)"
)

MAX_ASSET = 10_000_000

TERMOS_PRODUTO = (
    "gestão dos produtos",
    "gestao dos produtos",
    "gestaoprodutos",
    "produto",
    "produtos",
    "situação do produto",
    "situacao do produto",
    "comercialização",
    "comercializacao",
    "selo sisbi",
    "registro do produto",
)

TERMOS_QLIK = (
    "openapp",
    "getobject",
    "createcube",
    "createhypercube",
    "qlik.openapp",
    "qlik.getglobal",
    "qhypercube",
    "qdimensions",
    "qmeasures",
    "qfielddefs",
    "app.getobject",
    "app.createcube",
    "websocket",
    "qliksense",
)


def agora() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def salvar(nome: str, obj: Any) -> None:
    SAIDA.mkdir(parents=True, exist_ok=True)
    (SAIDA / nome).write_text(
        json.dumps(obj, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def get(
    url: str,
    timeout: int = 90,
    tentativas: int = 4,
) -> tuple[bytes, dict[str, str], int]:
    ultimo_erro: Exception | None = None

    for tentativa in range(1, tentativas + 1):
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": UA,
                "Accept": "*/*",
                "Cache-Control": "no-cache",
            },
        )
        try:
            with urllib.request.urlopen(
                req,
                timeout=timeout,
                context=ssl.create_default_context(),
            ) as resp:
                return (
                    resp.read(),
                    {k.lower(): v for k, v in resp.headers.items()},
                    int(getattr(resp, "status", 200)),
                )
        except Exception as exc:
            ultimo_erro = exc
            if tentativa >= tentativas:
                break
            espera = tentativa * 5
            print(
                f"Tentativa {tentativa}/{tentativas} falhou para {url}: "
                f"{type(exc).__name__}: {exc}. "
                f"Nova tentativa em {espera}s.",
                file=sys.stderr,
            )
            time.sleep(espera)

    assert ultimo_erro is not None
    raise ultimo_erro


def decodificar(data: bytes, headers: dict[str, str]) -> str:
    ct = headers.get("content-type", "")
    m = re.search(r"charset=([^\s;]+)", ct, re.I)
    encs: list[str] = []
    if m:
        encs.append(m.group(1).strip("\"'"))
    encs.extend(["utf-8-sig", "utf-8", "latin-1"])
    for enc in encs:
        try:
            return data.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", errors="replace")


def extrair_assets(html: str) -> list[str]:
    encontrados: set[str] = set()
    for padrao in (
        r'<script[^>]+src=["\']([^"\']+)["\']',
        r'<link[^>]+href=["\']([^"\']+)["\']',
    ):
        for valor in re.findall(padrao, html, re.I):
            valor = valor.strip()
            if not valor or valor.startswith(("data:", "javascript:", "#")):
                continue
            url = urllib.parse.urljoin(PAINEL, valor)
            if url.startswith(("http://", "https://")):
                encontrados.add(url)
    return sorted(encontrados)


def eh_js_relevante(url: str) -> bool:
    nome = Path(urllib.parse.urlparse(url).path).name.lower()
    if not nome.endswith(".js"):
        return False
    genericos = (
        "jquery",
        "bootstrap",
        "popper",
        "moment",
        "sweetalert",
        "datatables",
    )
    return not any(x in nome for x in genericos)


def contexto(texto: str, pos: int, raio: int = 450) -> str:
    return texto[max(0, pos - raio): min(len(texto), pos + raio)].strip()


def ocorrencias(texto: str, termos: tuple[str, ...], limite: int = 100) -> list[dict[str, Any]]:
    low = texto.lower()
    saida: list[dict[str, Any]] = []
    vistos: set[tuple[str, int]] = set()

    for termo in termos:
        inicio = 0
        termo_low = termo.lower()
        while True:
            pos = low.find(termo_low, inicio)
            if pos < 0:
                break
            chave = (termo_low, pos)
            if chave not in vistos:
                vistos.add(chave)
                saida.append(
                    {
                        "termo": termo,
                        "posicao": pos,
                        "contexto": contexto(texto, pos),
                    }
                )
            inicio = pos + len(termo_low)
            if len(saida) >= limite:
                return saida
    return saida


def extrair_chamadas(texto: str) -> dict[str, list[dict[str, Any]]]:
    saida: dict[str, list[dict[str, Any]]] = {
        "openApp": [],
        "getObject": [],
        "createCube": [],
        "createHyperCube": [],
    }

    padroes = {
        "openApp": r'(?:qlik\.)?openApp\s*\(\s*["\']([^"\']+)["\']',
        "getObject": r'(?:app\.)?getObject\s*\(\s*["\']([^"\']+)["\'](?:\s*,\s*["\']([^"\']+)["\'])?',
        "createCube": r'(?:app\.)?createCube\s*\(',
        "createHyperCube": r'createHyperCube\s*\(',
    }

    for tipo, padrao in padroes.items():
        for m in re.finditer(padrao, texto, re.I):
            item: dict[str, Any] = {
                "posicao": m.start(),
                "contexto": contexto(texto, m.start(), 650),
            }
            if tipo == "openApp":
                item["app_id"] = m.group(1)
            elif tipo == "getObject":
                item["argumento_1"] = m.group(1)
                if m.lastindex and m.lastindex >= 2 and m.group(2):
                    item["argumento_2"] = m.group(2)
            saida[tipo].append(item)

    return saida


def extrair_app_ids_variaveis(texto: str) -> list[dict[str, Any]]:
    resultados: list[dict[str, Any]] = []
    padroes = (
        r'\bappId\s*[:=]\s*["\']([^"\']+)["\']',
        r'\bappid\s*[:=]\s*["\']([^"\']+)["\']',
        r'\bapp_id\s*[:=]\s*["\']([^"\']+)["\']',
        r'\bappname\s*[:=]\s*["\']([^"\']+)["\']',
    )
    for padrao in padroes:
        for m in re.finditer(padrao, texto, re.I):
            resultados.append(
                {
                    "valor": m.group(1),
                    "posicao": m.start(),
                    "contexto": contexto(texto, m.start()),
                }
            )
    return resultados


def extrair_configuracoes(texto: str) -> list[dict[str, Any]]:
    resultados: list[dict[str, Any]] = []
    for termo in ("host", "prefix", "port", "isSecure", "webIntegrationId"):
        padrao = rf'\b{re.escape(termo)}\s*:\s*([^,\n\r}}]+)'
        for m in re.finditer(padrao, texto, re.I):
            resultados.append(
                {
                    "campo": termo,
                    "valor_bruto": m.group(1).strip()[:500],
                    "contexto": contexto(texto, m.start()),
                }
            )
    return resultados


def extrair_campos_qlik(texto: str) -> list[str]:
    campos: set[str] = set()

    # qFieldDefs: ["Campo"] ou qFieldDefs: ['Campo']
    for bloco in re.findall(
        r'qFieldDefs\s*:\s*\[([^\]]{0,2000})\]',
        texto,
        re.I | re.S,
    ):
        for valor in re.findall(r'["\']([^"\']+)["\']', bloco):
            valor = valor.strip()
            if valor:
                campos.add(valor)

    # qDef: { qFieldDefs: [...] } já é coberto acima; procura também qLabel.
    for valor in re.findall(r'qLabel\s*:\s*["\']([^"\']+)["\']', texto, re.I):
        valor = valor.strip()
        if valor:
            campos.add(valor)

    return sorted(campos)


def extrair_ids_qlik(texto: str) -> list[str]:
    ids: set[str] = set()

    # IDs explicitamente usados em getObject.
    for m in re.finditer(
        r'getObject\s*\(\s*["\']([^"\']+)["\'](?:\s*,\s*["\']([^"\']+)["\'])?',
        texto,
        re.I,
    ):
        for g in m.groups():
            if g and 1 <= len(g) <= 120:
                ids.add(g)

    return sorted(ids)


def main() -> int:
    SAIDA.mkdir(parents=True, exist_ok=True)

    resumo: dict[str, Any] = {
        "status": "iniciado",
        "versao_diagnostico": "2.1.0",
        "orgao": "Ministério da Agricultura e Pecuária — MAPA",
        "sistema": "e-SISBI / SISBI-POA",
        "painel": PAINEL,
        "executado_em": agora(),
        "observacao": (
            "Diagnóstico passivo de recursos públicos do painel Qlik Sense. "
            "Não contorna autenticação, CAPTCHA, sessão ou controles de acesso."
        ),
    }

    try:
        data, headers, status = get(PAINEL)
    except Exception as exc:
        resumo.update(status="erro", erro=f"{type(exc).__name__}: {exc}")
        salvar("resumo.json", resumo)
        print(json.dumps(resumo, ensure_ascii=False, indent=2))
        return 1

    html = decodificar(data, headers)
    assets = extrair_assets(html)

    fontes: list[tuple[str, str]] = [(PAINEL, html)]
    inventario: list[dict[str, Any]] = []

    for url in assets:
        item: dict[str, Any] = {"url": url}
        path = urllib.parse.urlparse(url).path.lower()

        if not path.endswith((".js", ".html", ".htm", ".json")):
            item.update(inspecionado=False, motivo="recurso fora do escopo textual")
            inventario.append(item)
            continue

        if path.endswith(".js") and not eh_js_relevante(url):
            item.update(inspecionado=False, motivo="biblioteca JavaScript genérica ignorada")
            inventario.append(item)
            continue

        try:
            d, h, st = get(url)
            item.update(
                inspecionado=True,
                http_status=st,
                content_type=h.get("content-type"),
                tamanho_bytes=len(d),
                sha256=sha256(d),
            )
            if len(d) > MAX_ASSET:
                item.update(analisado=False, motivo="recurso maior que 10 MB")
                inventario.append(item)
                continue

            t = decodificar(d, h)
            item["analisado"] = True
            item["qlik_score"] = sum(1 for x in TERMOS_QLIK if x in t.lower())
            item["produto_score"] = sum(1 for x in TERMOS_PRODUTO if x in t.lower())
            fontes.append((url, t))
        except Exception as exc:
            item.update(
                inspecionado=False,
                erro=f"{type(exc).__name__}: {exc}",
            )

        inventario.append(item)

    qlik: dict[str, Any] = {
        "app_ids": [],
        "app_ids_variaveis": [],
        "configuracoes": [],
        "objetos_getObject": [],
        "ids_qlik": [],
        "campos_qlik": [],
        "createCube": [],
        "createHyperCube": [],
        "fontes_analisadas": [u for u, _ in fontes],
    }

    refs_produtos: list[dict[str, Any]] = []
    amostras: list[dict[str, Any]] = []

    app_ids: set[str] = set()
    ids: set[str] = set()
    campos: set[str] = set()

    for origem, t in fontes:
        chamadas = extrair_chamadas(t)

        for x in chamadas["openApp"]:
            app_id = x.get("app_id")
            if app_id:
                app_ids.add(app_id)
            qlik["app_ids"].append({"origem": origem, **x})

        for x in chamadas["getObject"]:
            qlik["objetos_getObject"].append({"origem": origem, **x})

        for x in chamadas["createCube"]:
            qlik["createCube"].append({"origem": origem, **x})

        for x in chamadas["createHyperCube"]:
            qlik["createHyperCube"].append({"origem": origem, **x})

        for x in extrair_app_ids_variaveis(t):
            qlik["app_ids_variaveis"].append({"origem": origem, **x})

        for x in extrair_configuracoes(t):
            qlik["configuracoes"].append({"origem": origem, **x})

        for x in extrair_ids_qlik(t):
            ids.add(x)

        for x in extrair_campos_qlik(t):
            campos.add(x)

        ocorr_prod = ocorrencias(t, TERMOS_PRODUTO, limite=120)
        if ocorr_prod:
            refs_produtos.append(
                {
                    "origem": origem,
                    "quantidade": len(ocorr_prod),
                    "ocorrencias": ocorr_prod,
                }
            )

        ocorr_q = ocorrencias(t, TERMOS_QLIK, limite=80)
        if ocorr_q:
            amostras.append(
                {
                    "origem": origem,
                    "ocorrencias_qlik": ocorr_q,
                }
            )

    qlik["app_ids_unicos"] = sorted(app_ids)
    qlik["ids_qlik"] = sorted(ids)
    qlik["campos_qlik"] = sorted(campos)

    # Não tratamos JS como "candidato de exportação".
    resumo.update(
        status="diagnostico_qlik_concluido",
        http_status=status,
        content_type=headers.get("content-type"),
        last_modified=headers.get("last-modified"),
        etag=headers.get("etag"),
        tamanho_bytes=len(data),
        sha256_html=sha256(data),
        quantidade_assets=len(assets),
        assets_inspecionados=sum(1 for x in inventario if x.get("inspecionado")),
        fontes_analisadas=len(fontes),
        contem_gestao_produtos=(
            "gestão dos produtos" in html.lower()
            or "gestao dos produtos" in html.lower()
        ),
        contem_qlik=("qlik" in html.lower()),
        app_ids_encontrados=len(app_ids),
        objetos_getObject=len(qlik["objetos_getObject"]),
        ids_qlik_encontrados=len(ids),
        campos_qlik_encontrados=len(campos),
        referencias_produtos=sum(x["quantidade"] for x in refs_produtos),
    )

    if not app_ids and not qlik["objetos_getObject"]:
        resumo["conclusao_preliminar"] = (
            "O painel é Qlik Sense, mas App ID/objetos não ficaram expostos "
            "em chamadas literais nos recursos públicos analisados. "
            "Será necessário interpretar a configuração pública encontrada "
            "antes de qualquer tentativa de geração de banco."
        )
    else:
        resumo["conclusao_preliminar"] = (
            "Foram encontradas referências estruturais do Qlik. "
            "Revisar qlik.json e referencias_produtos.json antes de criar "
            "qualquer coletor ou banco definitivo."
        )

    salvar("assets.json", inventario)
    salvar("qlik.json", qlik)
    salvar("referencias_produtos.json", refs_produtos)
    salvar("amostra_textual.json", amostras)
    salvar("resumo.json", resumo)

    # Remove arquivo obsoleto do diagnóstico V1, se existir.
    antigo = SAIDA / "candidatos_exportacao.json"
    if antigo.exists():
        antigo.unlink()

    print(json.dumps(resumo, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
