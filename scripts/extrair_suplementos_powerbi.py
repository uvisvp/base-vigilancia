from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import urlparse, urlunparse
import gzip
import json
import re
import ssl
import time
import urllib.error
import urllib.request
import uuid


PAGINA_RELATORIO = (
    "https://app.powerbi.com/view?"
    "r=eyJrIjoiNDU4Y2UxNmEtZjc0Yi00ZTkyLTk3N2EtZTEyZTI5MjdkNzQ2Iiw"
    "idCI6ImI2N2FmMjNmLWMzZjMtNGQzNS04MGM3LWI3MDg1ZjVlZGQ4MSJ9"
    "&pageName=ReportSection"
)

ENTIDADE = "Contituintes IN 28"
SAIDA = Path("diagnostico-extracao-suplementos")

CAMPOS = [
    "Categoria",
    "Constituintes Autorizados",
    "CAS",
    "Função",
    "0 a 6 meses",
    "7 a 11 meses",
    "1 a 3 anos",
    "4 a 8 anos ",
    "9 a 18 anos",
    "Maiores 19 anos ",
    "Gestantes ",
    "Lactantes",
    "Alegações autorizadas e requisitos para uso da alegação",
    "Requisitos de Rotulagem Complementar e outros",
    "Especificações",
    "Observações",
    "Outras Informações",
    "Nutriente/Substância Bioativa/Enzima",
    "Link de acesso a especificações publicadas",
]


def abrir_url(
    url,
    headers=None,
    dados=None,
    tentativas=4,
):
    ultimo_erro = None

    for tentativa in range(1, tentativas + 1):
        requisicao = urllib.request.Request(
            url,
            data=dados,
            headers=headers or {
                "User-Agent": "Mozilla/5.0 base-vigilancia"
            },
        )

        try:
            return urllib.request.urlopen(
                requisicao,
                timeout=240,
                context=ssl._create_unverified_context(),
            )
        except urllib.error.HTTPError as erro:
            ultimo_erro = erro
            if erro.code not in (
                408,
                429,
                500,
                502,
                503,
                504,
            ):
                corpo = erro.read().decode(
                    "utf-8",
                    errors="replace",
                )
                raise RuntimeError(
                    f"HTTP {erro.code}: {corpo[:1000]}"
                ) from erro
        except (
            urllib.error.URLError,
            TimeoutError,
            OSError,
        ) as erro:
            ultimo_erro = erro

        if tentativa < tentativas:
            espera = min(5 * tentativa, 15)
            print(
                "Falha temporária:",
                repr(ultimo_erro),
                "| nova tentativa em",
                espera,
                "segundos",
            )
            time.sleep(espera)

    raise RuntimeError(
        f"Falha após {tentativas} tentativas: {url}"
    ) from ultimo_erro


def baixar_bytes(url, headers=None, dados=None):
    with abrir_url(url, headers, dados) as resposta:
        conteudo = resposta.read()
        status = resposta.status
        cabecalhos = dict(resposta.headers.items())

        codificacao = resposta.headers.get(
            "Content-Encoding",
            "",
        ).lower()

        if "gzip" in codificacao:
            conteudo = gzip.decompress(conteudo)

    return conteudo, status, cabecalhos


def baixar_texto(url, headers=None):
    conteudo, status, cabecalhos = baixar_bytes(
        url,
        headers,
    )
    return (
        conteudo.decode("utf-8", errors="replace"),
        status,
        cabecalhos,
    )


def localizar_json(html, nome_variavel):
    prefixo = (
        rf"var\s+{re.escape(nome_variavel)}"
        rf"\s*=\s*"
    )

    como_texto = re.search(
        prefixo
        + r"JSON\.parse\('((?:\\.|[^'])*)'\)",
        html,
        flags=re.DOTALL,
    )

    if como_texto:
        bruto = como_texto.group(1)
        decodificado = json.loads(
            '"'
            + bruto.replace('"', '\\"')
            .replace('\\"', '\"')
            + '"'
        )
        return json.loads(decodificado)

    como_objeto = re.search(
        prefixo,
        html,
        flags=re.DOTALL,
    )

    if como_objeto:
        restante = html[como_objeto.end():].lstrip()
        try:
            objeto, _ = json.JSONDecoder().raw_decode(
                restante
            )
            return objeto
        except json.JSONDecodeError:
            pass

    raise RuntimeError(
        f"Variável {nome_variavel} não localizada."
    )


def api_do_cluster(cluster_uri):
    partes = urlparse(cluster_uri)
    pedacos = (partes.hostname or "").split(".")

    primeiro = pedacos[0]
    primeiro = primeiro.replace("-redirect", "")
    primeiro = primeiro.replace("global-", "")
    pedacos[0] = primeiro + "-api"

    return urlunparse((
        partes.scheme or "https",
        ".".join(pedacos),
        "",
        "",
        "",
        "",
    )).rstrip("/")


def headers_powerbi(resource_key, json_post=False):
    headers = {
        "Accept": "application/json",
        "ActivityId": str(uuid.uuid4()),
        "RequestId": str(uuid.uuid4()),
        "X-PowerBI-ResourceKey": resource_key,
        "Origin": "https://app.powerbi.com",
        "Referer": PAGINA_RELATORIO,
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 Chrome/124 Safari/537.36"
        ),
    }

    if json_post:
        headers["Content-Type"] = "application/json;charset=UTF-8"

    return headers


def gravar_json(nome, dados):
    caminho = SAIDA / nome
    caminho.write_text(
        json.dumps(
            dados,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return caminho


def consulta_completa():
    selecoes = []

    for campo in CAMPOS:
        selecoes.append({
            "Column": {
                "Expression": {
                    "SourceRef": {
                        "Source": "c",
                    }
                },
                "Property": campo,
            },
            "Name": f"Consulta1.{campo}",
        })

    return {
        "Version": 2,
        "From": [
            {
                "Name": "c",
                "Entity": ENTIDADE,
                "Type": 0,
            }
        ],
        "Select": selecoes,
        "OrderBy": [
            {
                "Direction": 1,
                "Expression": {
                    "Column": {
                        "Expression": {
                            "SourceRef": {
                                "Source": "c",
                            }
                        },
                        "Property": "Constituintes Autorizados",
                    }
                },
            }
        ],
    }


def montar_payload(model_id):
    return {
        "version": "1.0.0",
        "queries": [
            {
                "Query": {
                    "Commands": [
                        {
                            "SemanticQueryDataShapeCommand": {
                                "Query": consulta_completa(),
                                "Binding": {
                                    "Primary": {
                                        "Groupings": [
                                            {
                                                "Projections": list(
                                                    range(len(CAMPOS))
                                                )
                                            }
                                        ]
                                    },
                                    "DataReduction": {
                                        "DataVolume": 6,
                                        "Primary": {
                                            "Window": {
                                                "Count": 30000,
                                            }
                                        },
                                    },
                                    "Version": 1,
                                },
                                "ExecutionMetricsKind": 1,
                            }
                        }
                    ]
                },
                "CacheKey": "",
            }
        ],
        "cancelQueries": [],
        "modelId": model_id,
    }


def localizar_datasets(resposta):
    datasets = []

    for resultado in resposta.get("results", []):
        data = (
            resultado.get("result", {})
            .get("data", {})
            .get("dsr", {})
        )

        for dataset in data.get("DS", []):
            datasets.append(dataset)

    return datasets


def inverter_dicionario(dicionario):
    if isinstance(dicionario, list):
        return {
            indice: valor
            for indice, valor in enumerate(dicionario)
        }

    if not isinstance(dicionario, dict):
        return {}

    invertido = {}

    for chave, valor in dicionario.items():
        if isinstance(valor, int):
            invertido[valor] = chave
        else:
            try:
                invertido[int(chave)] = valor
            except (TypeError, ValueError):
                pass

    return invertido


def decodificar_linhas(resposta):
    linhas_saida = []
    diagnostico = []

    for dataset in localizar_datasets(resposta):
        value_dicts = dataset.get("ValueDicts", {})
        dicionarios = {
            nome: inverter_dicionario(valores)
            for nome, valores in value_dicts.items()
        }

        for bloco in dataset.get("PH", []):
            for nome_matriz, matriz in bloco.items():
                if not isinstance(matriz, list):
                    continue

                esquema = []
                anterior = [None] * len(CAMPOS)

                for indice_linha, linha in enumerate(matriz):
                    if not isinstance(linha, dict):
                        continue

                    if linha.get("S"):
                        esquema = linha["S"]

                    celulas = list(linha.get("C", []))
                    repetidos = int(linha.get("R", 0) or 0)
                    nulos = int(linha.get("Ø", 0) or 0)
                    valores = []
                    cursor = 0

                    for indice_coluna in range(len(CAMPOS)):
                        mascara = 1 << indice_coluna

                        if repetidos & mascara:
                            valor = anterior[indice_coluna]
                        elif nulos & mascara:
                            valor = None
                        elif cursor < len(celulas):
                            valor = celulas[cursor]
                            cursor += 1
                        else:
                            valor = None

                        if indice_coluna < len(esquema):
                            nome_dicionario = esquema[
                                indice_coluna
                            ].get("DN")
                            if (
                                nome_dicionario
                                and isinstance(valor, int)
                            ):
                                valor = dicionarios.get(
                                    nome_dicionario,
                                    {},
                                ).get(valor, valor)

                        valores.append(valor)

                    anterior = valores
                    registro = {
                        campo: valor
                        for campo, valor in zip(CAMPOS, valores)
                    }

                    if any(
                        valor not in (None, "")
                        for valor in valores
                    ):
                        linhas_saida.append(registro)

                diagnostico.append({
                    "matriz": nome_matriz,
                    "linhas_brutas": len(matriz),
                    "campos_esquema": len(esquema),
                })

    return linhas_saida, diagnostico


def main():
    SAIDA.mkdir(parents=True, exist_ok=True)

    print("Abrindo painel:", PAGINA_RELATORIO)
    html, status_pagina, _ = baixar_texto(
        PAGINA_RELATORIO
    )
    print(
        "Página:",
        status_pagina,
        "|",
        len(html),
        "caracteres",
    )

    descriptor = localizar_json(
        html,
        "resourceDescriptor",
    )
    cluster = localizar_json(
        html,
        "clusterAssignmentRecord",
    )

    resource_key = descriptor["k"]
    tenant_id = descriptor.get("t")
    cluster_uri = cluster["FixedClusterUri"]
    api = api_do_cluster(cluster_uri)

    base = f"{api}/public/reports/{resource_key}"
    url_modelos = (
        base
        + "/modelsAndExploration"
        + "?preferReadOnlySession=true"
    )

    texto_modelos, status_modelos, _ = baixar_texto(
        url_modelos,
        headers_powerbi(resource_key),
    )
    modelos = json.loads(texto_modelos)

    if not modelos.get("models"):
        raise RuntimeError(
            "O Power BI não informou o modelo de dados."
        )

    model_id = modelos["models"][0]["id"]
    report_id = modelos.get("exploration", {}).get(
        "reportId"
    )

    print("Resource key:", resource_key)
    print("Tenant:", tenant_id)
    print("API:", api)
    print("Model ID:", model_id)
    print("Report ID:", report_id)
    print("Campos solicitados:", len(CAMPOS))

    payload = montar_payload(model_id)
    gravar_json("payload-querydata.json", payload)

    corpo = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")

    url_query = (
        f"{api}/public/reports/querydata"
        "?synchronous=true"
    )

    conteudo, status_query, cabecalhos_query = (
        baixar_bytes(
            url_query,
            headers_powerbi(
                resource_key,
                json_post=True,
            ),
            corpo,
        )
    )

    texto_query = conteudo.decode(
        "utf-8",
        errors="replace",
    )
    (SAIDA / "resposta-querydata.txt").write_text(
        texto_query,
        encoding="utf-8",
    )

    try:
        resposta_query = json.loads(texto_query)
    except json.JSONDecodeError as erro:
        gravar_json(
            "diagnostico-erro.json",
            {
                "status": status_query,
                "cabecalhos": cabecalhos_query,
                "erro": str(erro),
                "previa": texto_query[:1000],
            },
        )
        raise

    gravar_json(
        "resposta-querydata.json",
        resposta_query,
    )

    linhas, diagnostico_decoder = decodificar_linhas(
        resposta_query
    )

    gravar_json(
        "suplementos-extraidos.json",
        linhas,
    )
    gravar_json(
        "resumo-extracao.json",
        {
            "gerado_em": datetime.now(
                timezone.utc
            ).isoformat(),
            "pagina": PAGINA_RELATORIO,
            "resource_key": resource_key,
            "tenant_id": tenant_id,
            "api": api,
            "model_id": model_id,
            "report_id": report_id,
            "entidade": ENTIDADE,
            "campos": CAMPOS,
            "quantidade_campos": len(CAMPOS),
            "status_modelos": status_modelos,
            "status_querydata": status_query,
            "bytes_querydata": len(conteudo),
            "linhas_extraidas": len(linhas),
            "decoder": diagnostico_decoder,
            "amostra": linhas[:5],
        },
    )

    print("Querydata:", status_query)
    print("Bytes recebidos:", len(conteudo))
    print("Linhas extraídas:", len(linhas))
    print("EXTRAÇÃO DE SUPLEMENTOS CONCLUÍDA")


if __name__ == "__main__":
    main()

