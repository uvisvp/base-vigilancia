#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Gera o manifest próprio da base de Alertas Sanitários.

O objetivo é oferecer um ponto estável de descoberta em
`dados/alertas_sanitarios/manifest.json`, sem obrigar consumidores a conhecer
previamente a fragmentação interna da base.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
DADOS = BASE / "dados"
DESTINO = DADOS / "alertas_sanitarios"
MANIFEST_GERAL = DADOS / "manifest.json"
MANIFEST_LOCAL = DESTINO / "manifest.json"

CAMPOS_ALERTA = [
    "_versao_parser",
    "id_alerta",
    "numero_alerta",
    "tipo_alerta",
    "area",
    "tipo_produto",
    "data_publicacao",
    "data_atualizacao",
    "titulo",
    "resumo",
    "identificacao_produto",
    "descricao_produto",
    "problema",
    "acao",
    "motivacao",
    "fabricante",
    "recomendacoes",
    "informacoes_complementares",
    "registros",
    "cnpjs",
    "identificadores",
    "outras_publicacoes",
    "anexos",
    "url_oficial",
]

CAMPOS_BUSCA_ANO = [
    "a",
    "i",
    "d",
    "t",
    "area",
    "tipo_produto",
    "registros",
    "cnpjs",
]

CAMPOS_REFERENCIA_INDICE = ["a", "i", "d", "t"]


def agora() -> str:
    return datetime.now(timezone.utc).isoformat()


def carregar(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def contar_json(path: Path) -> int:
    return len(list(path.glob("*.json"))) if path.exists() else 0


def main() -> int:
    if not MANIFEST_GERAL.exists():
        raise RuntimeError(f"Manifest geral ausente: {MANIFEST_GERAL}")

    geral = carregar(MANIFEST_GERAL)
    bloco = geral.get("bases", {}).get("alertas_sanitarios")
    if not isinstance(bloco, dict):
        raise RuntimeError("Bloco bases.alertas_sanitarios ausente no manifest geral")

    obrigatorias = [
        DESTINO / "alertas",
        DESTINO / "busca",
        DESTINO / "indices" / "registros",
        DESTINO / "indices" / "cnpj",
        DESTINO / "indices" / "lotes_series_modelos",
    ]
    faltantes = [str(p.relative_to(BASE)) for p in obrigatorias if not p.exists()]
    if faltantes:
        raise RuntimeError("Estrutura de alertas incompleta: " + ", ".join(faltantes))

    anos = sorted(p.stem for p in (DESTINO / "busca").glob("*.json"))

    amostra = None
    for arquivo in sorted((DESTINO / "alertas").glob("*.json")):
        dados = carregar(arquivo)
        if isinstance(dados, list) and dados and isinstance(dados[0], dict):
            amostra = dados[0]
            break
    if amostra is None:
        raise RuntimeError("Nenhum alerta disponível para validar o schema")

    ausentes = [campo for campo in CAMPOS_ALERTA if campo not in amostra]
    if ausentes:
        raise RuntimeError("Campos esperados ausentes na amostra: " + ", ".join(ausentes))

    manifest = {
        "schema": "alertas-sanitarios-manifest-v1",
        "status": bloco.get("status", "ok"),
        "fonte": bloco.get("fonte"),
        "rota_oficial": "https://consultas.anvisa.gov.br/#/alertas-sanitarios/",
        "gerado_em": bloco.get("gerado_em"),
        "manifest_gerado_em": agora(),
        "versao_gerador": bloco.get("versao_gerador"),
        "total_alertas": bloco.get("alertas"),
        "cobertura": {
            "com_registro": bloco.get("com_registro"),
            "com_cnpj": bloco.get("com_cnpj"),
            "com_lote_serie_modelo": bloco.get("com_lote_serie_modelo"),
        },
        "campos_alerta": CAMPOS_ALERTA,
        "campos_busca_ano": CAMPOS_BUSCA_ANO,
        "campos_referencia_indice": CAMPOS_REFERENCIA_INDICE,
        "estrutura": {
            "alertas": {
                "pasta": "alertas/",
                "padrao": "alertas/{prefixo_3}.json",
                "fragmentacao": "3 primeiros dígitos de numero_alerta após zfill(5)",
                "fragmentos": contar_json(DESTINO / "alertas"),
                "conteudo": "registros completos dos alertas",
            },
            "busca_ano": {
                "pasta": "busca/",
                "padrao": "busca/{ano}.json",
                "fragmentacao": "ano de data_publicacao; sem_data quando indisponível",
                "arquivos": contar_json(DESTINO / "busca"),
                "anos_disponiveis": anos,
                "conteudo": "referências compactas para descoberta por período",
            },
            "indice_registro": {
                "pasta": "indices/registros/",
                "padrao": "indices/registros/{prefixo_3}.json",
                "fragmentacao": "3 primeiros dígitos do registro normalizado",
                "fragmentos": contar_json(DESTINO / "indices" / "registros"),
                "chave": "registro Anvisa normalizado apenas com dígitos",
            },
            "indice_cnpj": {
                "pasta": "indices/cnpj/",
                "padrao": "indices/cnpj/{prefixo_3}.json",
                "fragmentacao": "3 primeiros dígitos do CNPJ normalizado",
                "fragmentos": contar_json(DESTINO / "indices" / "cnpj"),
                "chave": "CNPJ normalizado com 14 dígitos",
            },
            "indice_lote_serie_modelo": {
                "pasta": "indices/lotes_series_modelos/",
                "padrao": "indices/lotes_series_modelos/{prefixo_2}.json",
                "fragmentacao": "2 primeiros caracteres da chave normalizada A-Z0-9",
                "fragmentos": contar_json(DESTINO / "indices" / "lotes_series_modelos"),
                "chave": "lote, série ou modelo extraído do texto do alerta",
            },
        },
        "semantica": {
            "a": "numero_alerta",
            "i": "id_alerta",
            "d": "data_publicacao",
            "t": "titulo",
            "identificadores": "lista de objetos {tipo, valor, chave}, em que tipo pode ser lote, serie ou modelo",
        },
        "qualidade_dados": {
            "registros": "Extraídos do texto por contexto de 'registro' ou 'regularização Anvisa'. Ausência não prova inexistência de registro relacionado ao alerta.",
            "cnpjs": "Extraídos quando aparecem no texto no formato NN.NNN.NNN/NNNN-NN. Ausência não prova inexistência de empresa relacionada.",
            "identificadores": "Lotes, séries e modelos são extraídos por rótulos contextuais do texto. Devem ser usados como evidência de correspondência, não como identidade automática isolada.",
            "fabricante": "Campo textual da fonte; pode conter fabricante, distribuidor ou ambos. Não usar como chave única sem normalização e confirmação por outra base.",
            "registro_como_chave": "É a chave preferencial para cruzar alertas com bases de produtos quando presente.",
            "cnpj_como_chave": "É a chave preferencial para cruzar alertas com AFE/AE e dados cadastrais de empresa quando presente.",
        },
        "regras_cruzamento": {
            "forte": ["registro", "cnpj"],
            "moderada": ["lote", "serie", "modelo"],
            "contextual": ["titulo", "descricao_produto", "fabricante", "problema", "acao", "motivacao"],
            "nao_concluir_por_ausencia": True,
        },
        "observacao": bloco.get("observacao", "Versão completa sem cópia local dos PDFs anexos."),
    }

    MANIFEST_LOCAL.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps({
        "arquivo": str(MANIFEST_LOCAL.relative_to(BASE)),
        "total_alertas": manifest["total_alertas"],
        "fragmentos_alerta": manifest["estrutura"]["alertas"]["fragmentos"],
        "anos": len(anos),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
