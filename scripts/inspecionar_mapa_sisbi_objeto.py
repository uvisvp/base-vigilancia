#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Diagnóstico V3 do objeto público "Gestão dos Produtos" do e-SISBI / MAPA.

Usa navegador real apenas para executar o mesmo mashup público que o usuário vê.
Não tenta autenticação, não contorna CAPTCHA, não usa credenciais e não acessa
áreas protegidas.

Alvo confirmado no mashup público:
- App ID: cce5fdb4-1444-4088-b557-2e49d7d1035e
- Objeto Qlik: YwuSG
- Container: tabela-gestao-produtos-full

Saídas:
  diagnosticos/mapa_sisbi/objeto_produtos.json
  diagnosticos/mapa_sisbi/layout_produtos.json
  diagnosticos/mapa_sisbi/cabecalhos_produtos.json
  diagnosticos/mapa_sisbi/resumo_objeto.json
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from playwright.sync_api import sync_playwright
except Exception as exc:
    print(
        "Playwright não está instalado. O workflow V3 deverá instalar "
        "'playwright' e o navegador Chromium.",
        file=sys.stderr,
    )
    raise

BASE = Path(__file__).resolve().parent.parent
SAIDA = BASE / "diagnosticos" / "mapa_sisbi"

PAINEL = (
    "https://mapa-indicadores.agricultura.gov.br/publico/"
    "extensions/DSN_ESISBI_2/DSN_ESISBI_2.html"
)

APP_ID = "cce5fdb4-1444-4088-b557-2e49d7d1035e"
OBJETO_ID = "YwuSG"
CONTAINER_ID = "tabela-gestao-produtos-full"


def agora() -> str:
    return datetime.now(timezone.utc).isoformat()


def salvar(nome: str, obj: Any) -> None:
    SAIDA.mkdir(parents=True, exist_ok=True)
    (SAIDA / nome).write_text(
        json.dumps(obj, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def simplificar_layout(layout: dict[str, Any]) -> dict[str, Any]:
    hc = layout.get("qHyperCube") or {}

    dimensoes = []
    for item in hc.get("qDimensionInfo") or []:
        dimensoes.append(
            {
                "titulo": item.get("qFallbackTitle"),
                "cardinalidade": item.get("qCardinal"),
                "tags": item.get("qTags"),
                "erro": item.get("qError"),
            }
        )

    medidas = []
    for item in hc.get("qMeasureInfo") or []:
        medidas.append(
            {
                "titulo": item.get("qFallbackTitle"),
                "min": item.get("qMin"),
                "max": item.get("qMax"),
                "tags": item.get("qTags"),
                "erro": item.get("qError"),
            }
        )

    tamanho = hc.get("qSize") or {}
    modo = hc.get("qMode")

    return {
        "qType": layout.get("qInfo", {}).get("qType"),
        "qId": layout.get("qInfo", {}).get("qId"),
        "titulo": layout.get("title"),
        "subtitulo": layout.get("subtitle"),
        "rodape": layout.get("footnote"),
        "qMode": modo,
        "qSize": {
            "qcx": tamanho.get("qcx"),
            "qcy": tamanho.get("qcy"),
        },
        "dimensoes": dimensoes,
        "medidas": medidas,
    }


def cabecalhos(layout: dict[str, Any]) -> list[dict[str, Any]]:
    hc = layout.get("qHyperCube") or {}
    saida = []

    for i, item in enumerate(hc.get("qDimensionInfo") or []):
        saida.append(
            {
                "ordem": len(saida),
                "tipo": "dimensao",
                "indice_qlik": i,
                "titulo": item.get("qFallbackTitle"),
                "cardinalidade": item.get("qCardinal"),
            }
        )

    for i, item in enumerate(hc.get("qMeasureInfo") or []):
        saida.append(
            {
                "ordem": len(saida),
                "tipo": "medida",
                "indice_qlik": i,
                "titulo": item.get("qFallbackTitle"),
            }
        )

    return saida


def main() -> int:
    SAIDA.mkdir(parents=True, exist_ok=True)

    resumo: dict[str, Any] = {
        "status": "iniciado",
        "versao_diagnostico": "3.0.0",
        "orgao": "Ministério da Agricultura e Pecuária — MAPA",
        "sistema": "e-SISBI / SISBI-POA",
        "painel": PAINEL,
        "app_id": APP_ID,
        "objeto_id": OBJETO_ID,
        "container_id": CONTAINER_ID,
        "executado_em": agora(),
        "observacao": (
            "Execução do mashup público em navegador. Sem autenticação, "
            "credenciais, CAPTCHA ou contorno de controle de acesso."
        ),
    }

    console_msgs: list[str] = []

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(
                viewport={"width": 1440, "height": 1000},
                locale="pt-BR",
            )

            page.on(
                "console",
                lambda msg: console_msgs.append(f"{msg.type}: {msg.text}") if len(console_msgs) < 100 else None,
            )

            response = page.goto(
                PAINEL,
                wait_until="domcontentloaded",
                timeout=120_000,
            )

            resumo["http_status"] = response.status if response else None

            # Aguarda o mashup definir a variável global app.
            page.wait_for_function(
                "() => typeof window.app !== 'undefined' && window.app",
                timeout=120_000,
            )

            # Garante um container temporário independente do container visual.
            page.evaluate(
                """
                () => {
                  if (!document.getElementById('diagnostico-produtos-temp')) {
                    const d = document.createElement('div');
                    d.id = 'diagnostico-produtos-temp';
                    d.style.width = '1200px';
                    d.style.height = '800px';
                    d.style.position = 'absolute';
                    d.style.left = '-5000px';
                    d.style.top = '0';
                    document.body.appendChild(d);
                  }
                }
                """
            )

            # Obtém o objeto público pela mesma Capability API já usada pelo mashup.
            resultado = page.evaluate(
                """
                async ({objetoId}) => {
                  const vis = await window.app.getObject(
                    'diagnostico-produtos-temp',
                    objetoId
                  );

                  if (!vis) {
                    return {ok:false, erro:'app.getObject retornou vazio'};
                  }

                  let layout = null;
                  let propriedades = null;

                  try {
                    if (vis.getLayout) {
                      layout = await vis.getLayout();
                    } else if (vis.model && vis.model.getLayout) {
                      layout = await vis.model.getLayout();
                    }
                  } catch (e) {
                    layout = {__erro: String(e)};
                  }

                  try {
                    if (vis.getProperties) {
                      propriedades = await vis.getProperties();
                    } else if (vis.model && vis.model.getProperties) {
                      propriedades = await vis.model.getProperties();
                    }
                  } catch (e) {
                    propriedades = {__erro: String(e)};
                  }

                  return {
                    ok: true,
                    temGetLayout: !!vis.getLayout,
                    temModel: !!vis.model,
                    temBackendApi: !!vis.backendApi,
                    layout,
                    propriedades
                  };
                }
                """,
                {"objetoId": OBJETO_ID},
            )

            browser.close()

    except Exception as exc:
        resumo.update(
            status="erro",
            erro=f"{type(exc).__name__}: {exc}",
            console=console_msgs[-30:],
        )
        salvar("resumo_objeto.json", resumo)
        print(json.dumps(resumo, ensure_ascii=False, indent=2))
        return 1

    if not resultado or not resultado.get("ok"):
        resumo.update(
            status="erro_objeto",
            erro=(resultado or {}).get("erro", "resultado vazio"),
            console=console_msgs[-30:],
        )
        salvar("resumo_objeto.json", resumo)
        print(json.dumps(resumo, ensure_ascii=False, indent=2))
        return 1

    layout = resultado.get("layout") or {}
    propriedades = resultado.get("propriedades") or {}

    info = simplificar_layout(layout)
    cols = cabecalhos(layout)

    objeto = {
        "app_id": APP_ID,
        "objeto_id": OBJETO_ID,
        "container_id": CONTAINER_ID,
        "tem_get_layout": resultado.get("temGetLayout"),
        "tem_model": resultado.get("temModel"),
        "tem_backend_api": resultado.get("temBackendApi"),
        "resumo_layout": info,
        "propriedades": propriedades,
    }

    resumo.update(
        status="diagnostico_objeto_concluido",
        qType=info.get("qType"),
        qId=info.get("qId"),
        titulo=info.get("titulo"),
        qMode=info.get("qMode"),
        colunas_qcx=info.get("qSize", {}).get("qcx"),
        linhas_qcy=info.get("qSize", {}).get("qcy"),
        quantidade_dimensoes=len(info.get("dimensoes") or []),
        quantidade_medidas=len(info.get("medidas") or []),
        quantidade_cabecalhos=len(cols),
        cabecalhos=[x.get("titulo") for x in cols],
        console=console_msgs[-20:],
    )

    salvar("layout_produtos.json", layout)
    salvar("objeto_produtos.json", objeto)
    salvar("cabecalhos_produtos.json", cols)
    salvar("resumo_objeto.json", resumo)

    print(json.dumps(resumo, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
