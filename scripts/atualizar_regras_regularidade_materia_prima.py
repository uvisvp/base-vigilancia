#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Publica regras de aplicabilidade para matéria-prima/IFA.

A finalidade é impedir que consumidores do banco tratem CADIFA/CBPF como
requisito universal de matéria-prima magistral ou de qualquer produto
comercializado por atacadista. As regras separam o escopo de Farmácia de
Manipulação do escopo de Distribuidor/Atacadista de insumos farmacêuticos.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json

BASE = Path(__file__).resolve().parent.parent
SAIDA = BASE / "dados" / "ifa_regularidade"


def agora():
    return datetime.now(timezone.utc).isoformat()


def sha_obj(obj):
    raw = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def main():
    SAIDA.mkdir(parents=True, exist_ok=True)
    gerado = agora()

    regras = {
        "schema": "regularidade-materia-prima-ifa-v1",
        "gerado_em": gerado,
        "principio": (
            "A ferramenta verifica evidências regulatórias públicas e pendências documentais. "
            "Não deve converter ausência em banco público em irregularidade automática."
        ),
        "conceitos": {
            "materia_prima": {
                "descricao": (
                    "Categoria ampla no contexto magistral: substância ativa ou inativa empregada na preparação."
                ),
                "regra": "Nem toda matéria-prima é IFA."
            },
            "principio_ativo_magistral": {
                "descricao": (
                    "Matéria-prima ativa utilizada na preparação magistral. Pode corresponder a um IFA, "
                    "mas sua conformidade na farmácia é avaliada prioritariamente pelas regras de aquisição, "
                    "qualificação de fornecedor, recebimento, certificado de análise, controle de qualidade, "
                    "armazenamento e rastreabilidade da RDC 67/2007."
                ),
                "regra": "CADIFA/CBPF não são tratados como requisito universal da matéria-prima magistral."
            },
            "ifa": {
                "descricao": (
                    "Insumo farmacêutico ativo. A RDC 359/2020 disciplina DIFA/CADIFA para IFA utilizado na "
                    "fabricação de medicamentos novos, inovadores, genéricos e similares."
                ),
                "regra": "Aplicabilidade de CADIFA/CBPF deve ser determinada pelo contexto regulatório."
            }
        },
        "escopos": {
            "farmacia_manipulacao": {
                "objeto_principal": "materia_prima",
                "pergunta_central": (
                    "A matéria-prima foi adquirida de fabricante/fornecedor regular e qualificado, recebida, "
                    "identificada, analisada, aprovada, armazenada e rastreada conforme os requisitos aplicáveis?"
                ),
                "normas_principais": [
                    {"slug": "rdc-67-2007", "dispositivos": ["7.1.3 a 7.1.8", "7.3.7 a 7.3.10"]}
                ],
                "verificacoes_banco": [
                    {"id": "fornecedor_afe_ae", "fonte": "dados/afe_ae", "resultado": "evidencia_publica"},
                    {"id": "atividade_autorizada", "fonte": "dados/afe_ae_atividades", "resultado": "evidencia_publica"},
                    {"id": "controle_especial", "fonte": "dados/controlados_portaria344/listas.json", "resultado": "condicional"},
                    {"id": "alertas", "fonte": "dados/alertas_sanitarios", "resultado": "evidencia_publica"},
                    {"id": "produtos_irregulares", "fonte": "dados/produtos_irregulares", "resultado": "evidencia_publica"}
                ],
                "verificacoes_documentais": [
                    "qualificacao_do_fabricante_fornecedor",
                    "especificacao_da_materia_prima",
                    "certificado_de_analise_do_lote",
                    "avaliacao_do_certificado",
                    "controle_de_qualidade_no_recebimento",
                    "identificacao_e_quarentena",
                    "armazenamento",
                    "rastreabilidade_do_lote"
                ],
                "quando_principio_ativo": {
                    "usar_bancos_ifa_como": "camada_complementar",
                    "fontes": [
                        "dados/ifa/registros.json",
                        "dados/ifa_regularidade/cadifa.json",
                        "dados/ifa_regularidade/cbpf_ifa.json"
                    ],
                    "cadifa": "condicional_nao_universal",
                    "cbpf_ifa": "condicional_nao_universal",
                    "regra_conclusao": (
                        "A ausência de CADIFA ou CBPF não deve, isoladamente, classificar a matéria-prima magistral como irregular."
                    )
                }
            },
            "atacadista_distribuidor_insumos": {
                "objeto_principal": "produto_comercializado",
                "pergunta_inicial": "O produto comercializado é IFA ou outra matéria-prima farmacêutica?",
                "normas_principais": [
                    {"slug": "rdc-204-2006", "dispositivos": ["Regulamento Técnico"]},
                    {"slug": "in-62-2020", "dispositivos": ["qualificação de fornecedores"]}
                ],
                "verificacoes_banco": [
                    {"id": "empresa_afe_ae", "fonte": "dados/afe_ae", "resultado": "evidencia_publica"},
                    {"id": "atividade_autorizada", "fonte": "dados/afe_ae_atividades", "resultado": "evidencia_publica"},
                    {"id": "controle_especial", "fonte": "dados/controlados_portaria344/listas.json", "resultado": "condicional"},
                    {"id": "alertas", "fonte": "dados/alertas_sanitarios", "resultado": "evidencia_publica"},
                    {"id": "produtos_irregulares", "fonte": "dados/produtos_irregulares", "resultado": "evidencia_publica"}
                ],
                "se_ifa": {
                    "fontes_adicionais": [
                        "dados/ifa/registros.json",
                        "dados/ifa_regularidade/cadifa.json",
                        "dados/ifa_regularidade/cbpf_ifa.json"
                    ],
                    "normas_contextuais": [
                        {"slug": "rdc-359-2020", "papel": "DIFA/CADIFA no escopo definido pela norma"},
                        {"slug": "rdc-361-2020", "papel": "CADIFA/CBPF no registro e pós-registro de medicamentos"},
                        {"slug": "rdc-57-2009", "papel": "regime histórico/legado; revogada em 01/03/2021"}
                    ],
                    "cadifa": "evidencia_regulatoria_condicional",
                    "cbpf_ifa": "evidencia_regulatoria_condicional",
                    "registro_legado_rdc57": "verificar_quando_aplicavel",
                    "regra_conclusao": (
                        "CADIFA não é tratada como licença universal de comercialização de todo IFA. "
                        "A ferramenta deve informar situação encontrada e aplicabilidade."
                    )
                },
                "se_nao_ifa": {
                    "regra": "Não aplicar automaticamente CADIFA, CBPF de IFA ou registro legado de IFA."
                }
            }
        },
        "marco_ifa": {
            "rdc_359_2020": {
                "slug": "rdc-359-2020",
                "aplicabilidade_chave": (
                    "IFA utilizados na fabricação de medicamentos novos, inovadores, genéricos e similares."
                )
            },
            "rdc_361_2020": {
                "slug": "rdc-361-2020",
                "papel": (
                    "Relaciona DIFA/CADIFA e CBPF ao registro e pós-registro de medicamentos e estabelece transição."
                )
            },
            "rdc_57_2009": {
                "slug": "rdc-57-2009",
                "status": "revogada_em_2021-03-01",
                "papel": (
                    "Referência histórica para registros de IFA concedidos no regime anterior. Registros vigentes "
                    "podem manter ciclo de vida até caducidade ou cancelamento, conforme orientação atual da Anvisa."
                )
            }
        },
        "resultados_permitidos": [
            "evidencias_publicas_compativeis",
            "verificacao_incompleta_confirmacao_documental",
            "incompatibilidade_identificada",
            "nao_aplicavel",
            "aplicabilidade_nao_determinada"
        ],
        "resultado_proibido_como_conclusao_automatica": ["ifa_regular", "ifa_irregular", "materia_prima_regular", "materia_prima_irregular"],
        "limitacoes": [
            "Bancos públicos não comprovam qualificação interna do fornecedor pela farmácia ou distribuidor.",
            "Bancos públicos não comprovam identidade e conformidade de um lote físico específico.",
            "Certificado de análise e controle de qualidade do lote permanecem dependentes de conferência documental/técnica.",
            "Ausência em CADIFA, CBPF ou base legada não equivale automaticamente a irregularidade."
        ]
    }

    regras["sha256_conteudo"] = sha_obj({k: v for k, v in regras.items() if k != "sha256_conteudo"})
    arq = SAIDA / "regras_aplicabilidade.json"
    arq.write_text(json.dumps(regras, ensure_ascii=False, indent=2), encoding="utf-8")

    manifest_path = SAIDA / "manifest.json"
    manifest = {"schema": "ifa-regularidade-manifest-v1", "gerado_em": gerado, "fontes": {}}
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    manifest["schema"] = "ifa-regularidade-manifest-v1"
    manifest["gerado_em"] = gerado
    manifest.setdefault("fontes", {})["regras_aplicabilidade"] = {
        "arquivo": "regras_aplicabilidade.json",
        "schema": regras["schema"],
        "sha256": regras["sha256_conteudo"],
        "escopos": list(regras["escopos"].keys()),
        "normas_v12": ["rdc-67-2007", "rdc-204-2006", "in-62-2020", "rdc-359-2020", "rdc-361-2020", "rdc-57-2009"]
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({
        "arquivo": str(arq.relative_to(BASE)),
        "schema": regras["schema"],
        "escopos": list(regras["escopos"].keys()),
        "sha256": regras["sha256_conteudo"]
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
