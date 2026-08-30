from pathlib import Path
from collections import defaultdict
from datetime import datetime, timezone
from urllib.parse import urlparse, urlunparse
import gzip
import json
import re
import shutil
import tempfile
import time
import unicodedata
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
BASE = Path(__file__).resolve().parent.parent
DADOS = BASE / "dados"
DESTINO = DADOS / "suplementos_constituintes"
MANIFESTO = DADOS / "manifest.json"
PREFIXO = 2

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

CAMPOS_SAIDA = {
    "Categoria": "categoria",
    "Constituintes Autorizados": "constituinte",
    "CAS": "cas",
    "Função": "funcao",
    "0 a 6 meses": "limite_0_6_meses",
    "7 a 11 meses": "limite_7_11_meses",
    "1 a 3 anos": "limite_1_3_anos",
    "4 a 8 anos ": "limite_4_8_anos",
    "9 a 18 anos": "limite_9_18_anos",
    "Maiores 19 anos ": "limite_19_mais",
    "Gestantes ": "limite_gestantes",
    "Lactantes": "limite_lactantes",
    "Alegações autorizadas e requisitos para uso da alegação": "alegacoes",
    "Requisitos de Rotulagem Complementar e outros": "rotulagem_complementar",
    "Especificações": "especificacoes",
    "Observações": "observacoes",
    "Outras Informações": "outras_informacoes",
    "Nutriente/Substância Bioativa/Enzima": "nutriente_substancia_enzima",
    "Link de acesso a especificações publicadas": "link_especificacoes",
}


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


def gravar_json(caminho, dados, identado=False):
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(
        json.dumps(
            dados,
            ensure_ascii=False,
            indent=2 if identado else None,
            separators=None if identado else (",", ":"),
        ),
        encoding="utf-8",
    )


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


def limpar_texto(valor):
    if valor is None:
        return ""

    texto = str(valor).replace("\r\n", "\n").replace("\r", "\n")
    texto = "\n".join(linha.rstrip() for linha in texto.split("\n"))
    return texto.strip()


def normalizar_busca(valor):
    texto = unicodedata.normalize("NFKD", limpar_texto(valor))
    texto = "".join(
        caractere
        for caractere in texto
        if not unicodedata.combining(caractere)
    )
    return re.sub(r"[^a-z0-9]+", "", texto.casefold())


def fragmento_do_constituinte(valor):
    chave = normalizar_busca(valor)
    if not chave:
        return "00"
    return chave[:PREFIXO].ljust(PREFIXO, "_")


def mapear_linhas(linhas):
    registros = []

    for linha in linhas:
        registro = {
            destino: limpar_texto(linha.get(origem))
            for origem, destino in CAMPOS_SAIDA.items()
        }
        registros.append(registro)

    registros.sort(
        key=lambda item: (
            normalizar_busca(item["constituinte"]),
            normalizar_busca(item["categoria"]),
            normalizar_busca(item["funcao"]),
        )
    )
    return registros


def contar_registros_publicados():
    if not DESTINO.exists():
        return 0

    total = 0
    for arquivo in DESTINO.glob("*.json"):
        if arquivo.name == "catalogo.json":
            continue

        try:
            dados = json.loads(arquivo.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue

        if isinstance(dados, list):
            total += len(dados)

    return total


def validar_registros(registros, total_anterior):
    if not 400 <= len(registros) <= 5000:
        raise RuntimeError(
            "Quantidade inesperada de constituintes: "
            f"{len(registros)}. A publicação foi cancelada."
        )

    campos_esperados = set(CAMPOS_SAIDA.values())
    obrigatorios = (
        "categoria",
        "constituinte",
        "funcao",
        "nutriente_substancia_enzima",
    )

    for indice, registro in enumerate(registros, start=1):
        if set(registro) != campos_esperados:
            raise RuntimeError(
                f"Linha {indice} não possui os 19 campos esperados."
            )

        faltantes = [
            campo for campo in obrigatorios if not registro[campo]
        ]
        if faltantes:
            raise RuntimeError(
                f"Linha {indice} sem campo obrigatório: "
                + ", ".join(faltantes)
            )

    constituintes_normalizados = {
        normalizar_busca(item["constituinte"])
        for item in registros
    }
    constituintes = {
        item["constituinte"]
        for item in registros
    }
    categorias = {
        item["categoria"]
        for item in registros
        if item["categoria"]
    }

    if len(constituintes_normalizados) < 400:
        raise RuntimeError(
            "Foram encontrados apenas "
            f"{len(constituintes_normalizados)} constituintes distintos."
        )

    if len(categorias) < 8:
        raise RuntimeError(
            "Foram encontradas apenas "
            f"{len(categorias)} categorias."
        )

    if total_anterior and len(registros) < total_anterior * 0.90:
        queda = (1 - len(registros) / total_anterior) * 100
        raise RuntimeError(
            "A base caiu "
            f"{queda:.1f}% ({total_anterior} -> {len(registros)}). "
            "A publicação foi cancelada para proteger a base atual."
        )

    return constituintes, categorias


def publicar_registros(registros, gerado_em):
    fragmentos = defaultdict(list)

    for registro in registros:
        fragmento = fragmento_do_constituinte(
            registro["constituinte"]
        )
        fragmentos[fragmento].append(registro)

    catalogo_vistos = set()
    catalogo = []

    for registro in registros:
        fragmento = fragmento_do_constituinte(
            registro["constituinte"]
        )
        chave = (
            registro["constituinte"],
            registro["categoria"],
            fragmento,
        )
        if chave in catalogo_vistos:
            continue
        catalogo_vistos.add(chave)
        catalogo.append({
            "constituinte": registro["constituinte"],
            "categoria": registro["categoria"],
            "fragmento": fragmento,
        })

    DADOS.mkdir(parents=True, exist_ok=True)
    temporario = Path(tempfile.mkdtemp(
        prefix="suplementos_constituintes_",
        dir=DADOS,
    ))

    try:
        for fragmento, itens in sorted(fragmentos.items()):
            gravar_json(temporario / f"{fragmento}.json", itens)

        gravar_json(
            temporario / "catalogo.json",
            {
                "versao_esquema": 1,
                "gerado_em": gerado_em,
                "itens": catalogo,
            },
        )

        if DESTINO.exists():
            shutil.rmtree(DESTINO)
        temporario.rename(DESTINO)
    except Exception:
        shutil.rmtree(temporario, ignore_errors=True)
        raise

    tamanhos = [
        arquivo.stat().st_size
        for arquivo in DESTINO.glob("*.json")
        if arquivo.name != "catalogo.json"
    ]
    return len(fragmentos), max(tamanhos, default=0), len(catalogo)


def atualizar_manifesto(
    registros,
    constituintes,
    categorias,
    fragmentos,
    maior_fragmento,
    itens_catalogo,
    gerado_em,
):
    if MANIFESTO.exists():
        manifesto = json.loads(MANIFESTO.read_text(encoding="utf-8"))
    else:
        manifesto = {
            "versao_esquema": 2,
            "projeto": "Base Vigilância Sanitária",
            "bases": {},
        }

    if not isinstance(manifesto, dict):
        raise RuntimeError("Manifesto principal inválido.")

    bases = manifesto.setdefault("bases", {})
    manifesto["gerado_em"] = gerado_em
    bases["suplementos_constituintes"] = {
        "status": "ok",
        "fonte": PAGINA_RELATORIO,
        "tipo_fonte": "Painel público Power BI da Anvisa",
        "gerado_em": gerado_em,
        "atualizado_em": gerado_em,
        "registros": len(registros),
        "constituintes_unicos": len(constituintes),
        "categorias": sorted(categorias),
        "quantidade_categorias": len(categorias),
        "campos": list(CAMPOS_SAIDA.values()),
        "quantidade_campos": len(CAMPOS_SAIDA),
        "fragmentos": fragmentos,
        "prefixo": PREFIXO,
        "maior_fragmento": maior_fragmento,
        "chave": "constituinte",
        "fragmentacao": (
            "2 primeiros caracteres alfanuméricos do "
            "constituinte, sem acentos"
        ),
        "catalogo": "suplementos_constituintes/catalogo.json",
        "itens_catalogo": itens_catalogo,
    }
    gravar_json(MANIFESTO, manifesto, identado=True)


def main():
    print("\n=== CONSTITUINTES DE SUPLEMENTOS ===")
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

    corpo = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")

    url_query = (
        f"{api}/public/reports/querydata"
        "?synchronous=true"
    )

    conteudo, status_query, _ = (
        baixar_bytes(
            url_query,
            headers_powerbi(
                resource_key,
                json_post=True,
            ),
            corpo,
        )
    )

    texto_query = conteudo.decode("utf-8", errors="replace")

    try:
        resposta_query = json.loads(texto_query)
    except json.JSONDecodeError as erro:
        raise RuntimeError(
            "O Power BI não devolveu JSON válido. "
            f"Status {status_query}; início da resposta: "
            f"{texto_query[:500]}"
        ) from erro

    linhas, diagnostico_decoder = decodificar_linhas(
        resposta_query
    )
    registros = mapear_linhas(linhas)
    total_anterior = contar_registros_publicados()
    constituintes, categorias = validar_registros(
        registros,
        total_anterior,
    )
    gerado_em = datetime.now(timezone.utc).isoformat()
    fragmentos, maior_fragmento, itens_catalogo = (
        publicar_registros(registros, gerado_em)
    )
    atualizar_manifesto(
        registros,
        constituintes,
        categorias,
        fragmentos,
        maior_fragmento,
        itens_catalogo,
        gerado_em,
    )

    print("Querydata:", status_query)
    print("Bytes recebidos:", len(conteudo))
    print("Decoder:", diagnostico_decoder)
    print(
        "suplementos_constituintes:",
        len(registros),
        "registros |",
        len(constituintes),
        "constituintes únicos |",
        len(categorias),
        "categorias |",
        fragmentos,
        "fragmentos | maior",
        round(maior_fragmento / 1024),
        "KB",
    )
    print("Base de constituintes gerada com sucesso.")


if __name__ == "__main__":
    main()
