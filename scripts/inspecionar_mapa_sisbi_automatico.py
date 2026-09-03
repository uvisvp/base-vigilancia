#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Diagnóstico V4 — viabilidade de atualização automática e-SISBI / SISBI-POA.

Objetivo:
- testar SOMENTE acesso público/anônimo ao Qlik Engine;
- confirmar se o App ID e o objeto "Gestão dos Produtos" podem ser lidos
  automaticamente sem navegador, login, CAPTCHA ou credenciais;
- se não houver acesso público anônimo, registrar a base como inviável para
  atualização automática e ENCERRAR a investigação.

Não publica banco e não altera dados existentes.
"""

from __future__ import annotations

import json
import ssl
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import websocket

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "diagnosticos" / "mapa_sisbi"

HOST = "mapa-indicadores.agricultura.gov.br"
APP_ID = "cce5fdb4-1444-4088-b557-2e49d7d1035e"
OBJETO_ID = "YwuSG"
ORIGIN = f"https://{HOST}"

CANDIDATOS = [
    f"wss://{HOST}/publico/app/{APP_ID}",
    f"wss://{HOST}/app/{APP_ID}",
]


def agora() -> str:
    return datetime.now(timezone.utc).isoformat()


def salvar(nome: str, data: Any) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / nome).write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def rpc(ws: websocket.WebSocket, handle: int, method: str, params: list[Any], msg_id: int) -> dict[str, Any]:
    payload = {
        "jsonrpc": "2.0",
        "id": msg_id,
        "handle": handle,
        "method": method,
        "params": params,
    }
    ws.send(json.dumps(payload, ensure_ascii=False))

    limite = time.time() + 30
    while time.time() < limite:
        raw = ws.recv()
        if raw is None:
            raise RuntimeError("WebSocket encerrado sem resposta.")
        data = json.loads(raw)

        # Qlik pode enviar notificações sem id; esperamos a resposta do nosso RPC.
        if data.get("id") == msg_id:
            return data

    raise TimeoutError(f"Sem resposta RPC para {method}.")


def testar_endpoint(url: str) -> dict[str, Any]:
    r: dict[str, Any] = {
        "url": url,
        "conectou_websocket": False,
        "abriu_app": False,
        "obteve_objeto": False,
        "obteve_layout": False,
    }

    ws = None
    try:
        # websocket-client adiciona Origin automaticamente; suppress_origin evita duplicidade
        # e permite enviar exatamente o Origin público do próprio MAPA.
        ws = websocket.create_connection(
            url,
            timeout=45,
            origin=ORIGIN,
            host=HOST,
            sslopt={"cert_reqs": ssl.CERT_REQUIRED},
            header=[
                "User-Agent: Mozilla/5.0 (GitHub Actions; e-SISBI public diagnostic)",
                "Pragma: no-cache",
                "Cache-Control: no-cache",
            ],
        )
        r["conectou_websocket"] = True

        open_doc = rpc(
            ws,
            -1,
            "OpenDoc",
            [APP_ID, "", "", "", False],
            1,
        )
        r["open_doc"] = open_doc

        if "error" in open_doc:
            r["erro_fase"] = "OpenDoc"
            r["erro"] = open_doc["error"]
            return r

        doc_handle = (
            open_doc.get("result", {})
            .get("qReturn", {})
            .get("qHandle")
        )
        r["doc_handle"] = doc_handle

        if not isinstance(doc_handle, int):
            r["erro_fase"] = "OpenDoc"
            r["erro"] = "OpenDoc respondeu sem qHandle de documento."
            return r

        r["abriu_app"] = True

        get_object = rpc(
            ws,
            doc_handle,
            "GetObject",
            [OBJETO_ID],
            2,
        )
        r["get_object"] = get_object

        if "error" in get_object:
            r["erro_fase"] = "GetObject"
            r["erro"] = get_object["error"]
            return r

        obj_handle = (
            get_object.get("result", {})
            .get("qReturn", {})
            .get("qHandle")
        )
        r["obj_handle"] = obj_handle

        if not isinstance(obj_handle, int):
            r["erro_fase"] = "GetObject"
            r["erro"] = "GetObject respondeu sem qHandle do objeto."
            return r

        r["obteve_objeto"] = True

        layout = rpc(
            ws,
            obj_handle,
            "GetLayout",
            [],
            3,
        )
        r["get_layout"] = layout

        if "error" in layout:
            r["erro_fase"] = "GetLayout"
            r["erro"] = layout["error"]
            return r

        qlayout = layout.get("result", {}).get("qLayout") or {}
        hc = qlayout.get("qHyperCube") or {}
        qsize = hc.get("qSize") or {}

        r["obteve_layout"] = True
        r["qType"] = qlayout.get("qInfo", {}).get("qType")
        r["qId"] = qlayout.get("qInfo", {}).get("qId")
        r["qcx"] = qsize.get("qcx")
        r["qcy"] = qsize.get("qcy")
        r["dimensoes"] = [
            x.get("qFallbackTitle")
            for x in (hc.get("qDimensionInfo") or [])
        ]
        r["medidas"] = [
            x.get("qFallbackTitle")
            for x in (hc.get("qMeasureInfo") or [])
        ]

        return r

    except Exception as exc:
        r["erro_fase"] = r.get("erro_fase") or "conexao"
        r["erro"] = f"{type(exc).__name__}: {exc}"
        return r

    finally:
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)

    resultados = []
    viavel = False
    endpoint_funcional = None

    for url in CANDIDATOS:
        resultado = testar_endpoint(url)
        resultados.append(resultado)

        if resultado.get("obteve_layout"):
            viavel = True
            endpoint_funcional = url
            break

    resumo = {
        "status": (
            "viavel_para_atualizacao_automatica"
            if viavel
            else "inviavel_para_atualizacao_automatica"
        ),
        "versao_diagnostico": "4.0.0",
        "orgao": "Ministério da Agricultura e Pecuária — MAPA",
        "sistema": "e-SISBI / SISBI-POA",
        "executado_em": agora(),
        "app_id": APP_ID,
        "objeto_id": OBJETO_ID,
        "endpoint_funcional": endpoint_funcional,
        "criterio": (
            "Só considerar viável se um processo não interativo conseguir, "
            "sem autenticação/credenciais/CAPTCHA, abrir o app público, obter "
            "o objeto YwuSG e ler seu layout."
        ),
        "continuar_projeto": viavel,
        "resultados": resultados,
    }

    salvar("viabilidade_automatica.json", resumo)

    print(json.dumps(resumo, ensure_ascii=False, indent=2))

    # Importante: mesmo quando inviável, o diagnóstico em si foi concluído.
    # Retorna 0 para que o workflow possa salvar o resultado e não ficar vermelho
    # apenas porque a conclusão técnica foi "inviável".
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
