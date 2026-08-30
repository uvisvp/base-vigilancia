from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import urlparse, urlunparse
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

SAIDA = Path("diagnostico-powerbi-suplementos")


def abrir_url(url, headers=None, tentativas=3):
    ultimo_erro = None

    for tentativa in range(1, tentativas + 1):
        requisicao = urllib.request.Request(
            url,
            headers=headers or {
                "User-Agent":
                "Mozilla/5.0 base-vigilancia"
            }
        )

        try:
            return urllib.request.urlopen(
                requisicao,
                timeout=180,
                context=ssl._create_unverified_context()
            )

        except urllib.error.HTTPError as erro:
            ultimo_erro = erro

            if erro.code not in (
                408, 429, 500, 502, 503, 504
            ):
                raise

        except (
            urllib.error.URLError,
            TimeoutError,
            OSError
        ) as erro:
            ultimo_erro = erro

        if tentativa < tentativas:
            espera = 5 * tentativa
            print(
                "Falha temporária:",
                repr(ultimo_erro),
                "| nova tentativa em",
                espera,
                "segundos"
            )
            time.sleep(espera)

    raise RuntimeError(
        f"Falha após {tentativas} tentativas: {url}"
    ) from ultimo_erro


def baixar_texto(url, headers=None):
    with abrir_url(url, headers) as resposta:
        conteudo = resposta.read()
        status = resposta.status
        cabecalhos = dict(resposta.headers.items())

    return (
        conteudo.decode("utf-8", errors="replace"),
        status,
        cabecalhos
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
        flags=re.DOTALL
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
        flags=re.DOTALL
    )

    if como_objeto:
        restante = html[
            como_objeto.end():
        ].lstrip()

        try:
            objeto, _ = (
                json.JSONDecoder().raw_decode(
                    restante
                )
            )
            return objeto
        except json.JSONDecodeError:
            pass

    raise RuntimeError(
        f"Variável {nome_variavel} não localizada."
    )


def api_do_cluster(cluster_uri):
    partes = urlparse(cluster_uri)
    hostname = partes.hostname or ""
    pedacos = hostname.split(".")

    if not pedacos:
        raise RuntimeError(
            "Cluster do Power BI inválido."
        )

    primeiro = pedacos[0]
    primeiro = primeiro.replace(
        "-redirect",
        ""
    )
    primeiro = primeiro.replace(
        "global-",
        ""
    )
    pedacos[0] = primeiro + "-api"

    return urlunparse((
        partes.scheme or "https",
        ".".join(pedacos),
        "",
        "",
        "",
        ""
    )).rstrip("/")


def headers_powerbi(resource_key):
    return {
        "Accept": "application/json",
        "ActivityId": str(uuid.uuid4()),
        "RequestId": str(uuid.uuid4()),
        "X-PowerBI-ResourceKey": resource_key,
        "Origin": "https://app.powerbi.com",
        "Referer": PAGINA_RELATORIO,
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 Chrome/124 Safari/537.36"
        )
    }


def gravar_json(nome, dados):
    caminho = SAIDA / nome
    caminho.write_text(
        json.dumps(
            dados,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )
    return caminho


def percorrer(objeto, caminho="$"):
    if isinstance(objeto, dict):
        yield caminho, objeto

        for chave, valor in objeto.items():
            yield from percorrer(
                valor,
                f"{caminho}.{chave}"
            )

    elif isinstance(objeto, list):
        for indice, valor in enumerate(objeto):
            yield from percorrer(
                valor,
                f"{caminho}[{indice}]"
            )


def resumir_modelo(modelos):
    resumo = {
        "chaves_raiz": (
            sorted(modelos.keys())
            if isinstance(modelos, dict)
            else []
        ),
        "secoes": [],
        "visuais_relevantes": []
    }

    termos = (
        "constitu",
        "alega",
        "rotulag",
        "nutriente",
        "bioativa",
        "enzima",
        "gestante",
        "lactante",
        "cas",
        "especifica"
    )

    vistos_secoes = set()
    vistos_visuais = set()

    for caminho, objeto in percorrer(modelos):
        nome = str(
            objeto.get("displayName")
            or objeto.get("name")
            or objeto.get("title")
            or ""
        )

        if (
            "sections" in objeto
            and isinstance(
                objeto.get("sections"),
                list
            )
        ):
            for secao in objeto["sections"]:
                if not isinstance(secao, dict):
                    continue

                item = {
                    "name": secao.get("name"),
                    "displayName": secao.get(
                        "displayName"
                    ),
                    "visualContainers": len(
                        secao.get(
                            "visualContainers",
                            []
                        )
                    )
                }
                chave = json.dumps(
                    item,
                    sort_keys=True
                )

                if chave not in vistos_secoes:
                    vistos_secoes.add(chave)
                    resumo["secoes"].append(item)

        serializado = json.dumps(
            objeto,
            ensure_ascii=False
        )
        minusculo = serializado.lower()

        if not any(
            termo in minusculo
            for termo in termos
        ):
            continue

        if not any(
            chave in objeto
            for chave in (
                "query",
                "prototypeQuery",
                "config",
                "dataTransforms",
                "visualType"
            )
        ):
            continue

        amostra = {
            "caminho": caminho,
            "nome": nome,
            "chaves": sorted(objeto.keys()),
            "conteudo": objeto
        }
        chave = caminho

        if chave not in vistos_visuais:
            vistos_visuais.add(chave)
            resumo["visuais_relevantes"].append(
                amostra
            )

    return resumo


def resumir_esquema(esquema):
    resumo = {
        "chaves_raiz": (
            sorted(esquema.keys())
            if isinstance(esquema, dict)
            else []
        ),
        "objetos_relevantes": []
    }

    termos = (
        "constitu",
        "alega",
        "rotulag",
        "nutriente",
        "bioativa",
        "enzima",
        "gestante",
        "lactante",
        "especifica"
    )

    for caminho, objeto in percorrer(esquema):
        serializado = json.dumps(
            objeto,
            ensure_ascii=False
        )
        minusculo = serializado.lower()

        if not any(
            termo in minusculo
            for termo in termos
        ):
            continue

        if not any(
            chave in objeto
            for chave in (
                "entities",
                "properties",
                "name",
                "caption"
            )
        ):
            continue

        resumo["objetos_relevantes"].append({
            "caminho": caminho,
            "chaves": sorted(objeto.keys()),
            "conteudo": objeto
        })

    return resumo


def main():
    SAIDA.mkdir(
        parents=True,
        exist_ok=True
    )

    print("Abrindo painel público:", PAGINA_RELATORIO)
    html, status, _ = baixar_texto(
        PAGINA_RELATORIO
    )
    print(
        "Página:",
        status,
        "|",
        len(html),
        "caracteres"
    )

    descriptor = localizar_json(
        html,
        "resourceDescriptor"
    )
    cluster = localizar_json(
        html,
        "clusterAssignmentRecord"
    )

    resource_key = descriptor["k"]
    tenant_id = descriptor.get("t")
    cluster_uri = cluster["FixedClusterUri"]
    api = api_do_cluster(cluster_uri)

    print("Resource key:", resource_key)
    print("Tenant:", tenant_id)
    print("Cluster:", cluster_uri)
    print("API:", api)

    base = (
        f"{api}/public/reports/"
        f"{resource_key}"
    )

    url_modelos = (
        base
        + "/modelsAndExploration"
        + "?preferReadOnlySession=true"
    )
    url_esquema = base + "/conceptualschema"

    texto_modelos, status_modelos, _ = (
        baixar_texto(
            url_modelos,
            headers_powerbi(resource_key)
        )
    )
    texto_esquema, status_esquema, _ = (
        baixar_texto(
            url_esquema,
            headers_powerbi(resource_key)
        )
    )

    modelos = json.loads(texto_modelos)
    esquema = json.loads(texto_esquema)

    caminho_modelos = gravar_json(
        "modelos-e-exploracao.json",
        modelos
    )
    caminho_esquema = gravar_json(
        "esquema-conceitual.json",
        esquema
    )

    resumo = {
        "gerado_em": datetime.now(
            timezone.utc
        ).isoformat(),
        "pagina": PAGINA_RELATORIO,
        "resource_key": resource_key,
        "tenant_id": tenant_id,
        "cluster_uri": cluster_uri,
        "api": api,
        "modelos": {
            "status": status_modelos,
            "bytes": len(
                texto_modelos.encode("utf-8")
            ),
            "arquivo": str(caminho_modelos),
            "resumo": resumir_modelo(modelos)
        },
        "esquema": {
            "status": status_esquema,
            "bytes": len(
                texto_esquema.encode("utf-8")
            ),
            "arquivo": str(caminho_esquema),
            "resumo": resumir_esquema(esquema)
        }
    }

    caminho_resumo = gravar_json(
        "resumo.json",
        resumo
    )

    print(
        "Modelos:",
        status_modelos,
        "|",
        len(texto_modelos),
        "caracteres"
    )
    print(
        "Esquema:",
        status_esquema,
        "|",
        len(texto_esquema),
        "caracteres"
    )
    print(
        "Seções encontradas:",
        len(
            resumo["modelos"]
            ["resumo"]
            ["secoes"]
        )
    )
    print(
        "Visuais relevantes:",
        len(
            resumo["modelos"]
            ["resumo"]
            ["visuais_relevantes"]
        )
    )
    print("Resumo salvo em:", caminho_resumo)
    print("DIAGNÓSTICO POWER BI CONCLUÍDO")


if __name__ == "__main__":
    main()
