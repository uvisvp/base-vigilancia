from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import urlencode, urljoin, urlparse
import gzip
import html
import json
import os
import re
import time
import urllib.error
import urllib.request


PORTAL = "https://api.anvisa.gov.br/"
DOCUMENTACAO = urljoin(PORTAL, "consultas-externas/dossie-doc")
GATEWAY = (
    "https://api-gateway.prd.apps.anvisa.gov.br/"
    "consultas-externas-api"
)
API_V1 = f"{GATEWAY}/api/v1"
TOKEN_URL = (
    "https://acesso.prd.apps.anvisa.gov.br/auth/"
    "realms/externo/protocol/openid-connect/token"
)
SAIDA = Path("diagnostico-produtos-irregulares")
VERSAO_INSPETOR = "2026-08-30-dossie-v5"
MAXIMO_ATIVOS = 80


def requisitar(url, metodo="GET", dados=None, tentativas=3, token=None):
    ultimo_erro = None

    for tentativa in range(1, tentativas + 1):
        corpo = None
        headers = {
            "Accept": "application/json, text/plain, text/html;q=0.8, */*;q=0.5",
            "Accept-Encoding": "gzip",
            "Origin": "https://api.anvisa.gov.br",
            "Referer": DOCUMENTACAO,
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/124 Safari/537.36"
            ),
        }

        if token:
            headers["Authorization"] = f"Bearer {token}"

        if dados is not None:
            corpo = json.dumps(
                dados,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
            headers["Content-Type"] = "application/json;charset=UTF-8"

        pedido = urllib.request.Request(
            url,
            data=corpo,
            headers=headers,
            method=metodo,
        )

        try:
            with urllib.request.urlopen(pedido, timeout=180) as resposta:
                conteudo = resposta.read()
                cabecalhos = dict(resposta.headers.items())
                if "gzip" in resposta.headers.get(
                    "Content-Encoding", ""
                ).lower():
                    conteudo = gzip.decompress(conteudo)
                return resposta.status, cabecalhos, conteudo, ""
        except urllib.error.HTTPError as erro:
            conteudo = erro.read()
            cabecalhos = dict(erro.headers.items())
            if "gzip" in erro.headers.get(
                "Content-Encoding", ""
            ).lower():
                try:
                    conteudo = gzip.decompress(conteudo)
                except OSError:
                    pass

            if erro.code not in (408, 429, 500, 502, 503, 504):
                return erro.code, cabecalhos, conteudo, repr(erro)
            ultimo_erro = erro
        except (urllib.error.URLError, TimeoutError, OSError) as erro:
            ultimo_erro = erro

        if tentativa < tentativas:
            espera = 5 * tentativa
            print(
                "Falha temporária:",
                repr(ultimo_erro),
                "| nova tentativa em",
                espera,
                "segundos",
            )
            time.sleep(espera)

    return 0, {}, b"", repr(ultimo_erro)


def obter_token():
    client_id = os.environ.get("ANVISA_CLIENT_ID", "").strip()
    client_secret = os.environ.get("ANVISA_CLIENT_SECRET", "").strip()

    if not client_id or not client_secret:
        raise RuntimeError(
            "Configure ANVISA_CLIENT_ID e ANVISA_CLIENT_SECRET "
            "nos Secrets do GitHub Actions."
        )

    corpo = urlencode({
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
    }).encode("utf-8")
    pedido = urllib.request.Request(
        TOKEN_URL,
        data=corpo,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/124 Safari/537.36"
            ),
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(pedido, timeout=180) as resposta:
            dados = json.loads(resposta.read().decode("utf-8"))
    except urllib.error.HTTPError as erro:
        texto = erro.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Falha ao obter token da Anvisa: HTTP {erro.code}. "
            f"Resposta: {texto[:500]}"
        ) from erro
    except (urllib.error.URLError, TimeoutError, OSError) as erro:
        raise RuntimeError(
            f"Falha de conexão ao obter token da Anvisa: {erro!r}"
        ) from erro

    token = dados.get("access_token")
    if not token:
        raise RuntimeError(
            "A Anvisa respondeu, mas não devolveu access_token."
        )

    gravar_json(
        SAIDA / "autenticacao-resumo.json",
        {
            "status": "ok",
            "token_type": dados.get("token_type", ""),
            "expires_in": dados.get("expires_in"),
            "scope": dados.get("scope", ""),
            "observacao": "Token e credenciais não foram armazenados.",
        },
    )
    print("Token temporário da Anvisa obtido com sucesso.")
    return token


def nome_seguro(nome):
    return re.sub(r"[^a-z0-9_-]+", "-", nome.lower()).strip("-")


def gravar_json(caminho, dados):
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(
        json.dumps(dados, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def salvar_resposta(nome, status, cabecalhos, conteudo, erro=""):
    base = SAIDA / nome_seguro(nome)
    texto = conteudo.decode("utf-8", errors="replace")
    base.with_suffix(".txt").write_text(texto, encoding="utf-8")

    convertido = None
    try:
        convertido = json.loads(texto)
        gravar_json(base.with_suffix(".json"), convertido)
    except json.JSONDecodeError:
        pass

    resumo = {
        "nome": nome,
        "status": status,
        "bytes": len(conteudo),
        "tipo_conteudo": cabecalhos.get("Content-Type", ""),
        "erro": erro,
        "json": convertido is not None,
        "tipo_json": type(convertido).__name__ if convertido is not None else "",
        "chaves_json": (
            sorted(convertido.keys())
            if isinstance(convertido, dict)
            else []
        ),
        "quantidade_json": (
            len(convertido)
            if isinstance(convertido, (list, dict))
            else None
        ),
        "previa": texto[:2000],
    }
    gravar_json(base.with_name(base.name + "-resumo.json"), resumo)
    return resumo, convertido


def extrair_ativos_html(conteudo):
    texto = conteudo.decode("utf-8", errors="replace")
    caminhos = re.findall(
        r'(?:src|href)=["\']([^"\']+\.js(?:\?[^"\']*)?)["\']',
        texto,
        flags=re.IGNORECASE,
    )
    return [urljoin(PORTAL, html.unescape(caminho)) for caminho in caminhos]


def extrair_ativos_javascript(texto, url_pai):
    caminhos = set()
    padroes = (
        r'import\(["\']([^"\']+\.js(?:\?[^"\']*)?)["\']\)',
        r'from["\']([^"\']+\.js(?:\?[^"\']*)?)["\']',
    )

    for padrao in padroes:
        caminhos.update(re.findall(padrao, texto, flags=re.IGNORECASE))

    return [urljoin(url_pai, html.unescape(caminho)) for caminho in caminhos]


def contextos_relevantes(texto, nome_arquivo):
    padrao = re.compile(
        r"dossi[eê]|tiposProduto|acoesFiscalizacao|classesRisco|"
        r"consultas-externas-api|openapi|swagger|gatewayUrl|"
        r"pageIndex|pageSize|pagin|orden|filtro",
        flags=re.IGNORECASE,
    )
    vistos = set()
    contextos = []

    for encontrado in padrao.finditer(texto):
        inicio = max(0, encontrado.start() - 500)
        fim = min(len(texto), encontrado.end() + 900)
        contexto = texto[inicio:fim].replace("\r", " ").replace("\n", " ")
        contexto = re.sub(r"\s+", " ", contexto).strip()
        chave = contexto.casefold()
        if chave in vistos:
            continue
        vistos.add(chave)
        contextos.append(f"\n### {nome_arquivo}\n{contexto}\n")

    return contextos


def baixar_arvore_javascript(conteudo_html):
    fila = extrair_ativos_html(conteudo_html)
    visitados = set()
    relatorio = []
    contextos = []
    urls_encontradas = set()
    pasta = SAIDA / "javascript"
    pasta.mkdir(parents=True, exist_ok=True)

    while fila and len(visitados) < MAXIMO_ATIVOS:
        url = fila.pop(0)
        url_sem_fragmento = url.split("#", 1)[0]
        if url_sem_fragmento in visitados:
            continue
        if "ruxitagentjs" in url_sem_fragmento or "/cdn-cgi/" in url_sem_fragmento:
            continue

        visitados.add(url_sem_fragmento)
        print("GET JavaScript", url_sem_fragmento)
        status, cabecalhos, conteudo, erro = requisitar(url_sem_fragmento)
        nome_original = Path(urlparse(url_sem_fragmento).path).name
        nome_original = nome_original or f"ativo-{len(visitados)}.js"
        nome = nome_seguro(nome_original.removesuffix(".js")) + ".js"
        caminho = pasta / nome

        if conteudo:
            caminho.write_bytes(conteudo)

        texto = conteudo.decode("utf-8", errors="replace")
        achados = contextos_relevantes(texto, nome)
        contextos.extend(achados)

        for encontrada in re.findall(
            r"https?://[^\"'`\\\s<>]+",
            texto,
            flags=re.IGNORECASE,
        ):
            if any(
                termo in encontrada.casefold()
                for termo in ("anvisa", "dossie", "swagger", "openapi")
            ):
                urls_encontradas.add(encontrada.rstrip(",;.)]"))

        for dependente in extrair_ativos_javascript(texto, url_sem_fragmento):
            if dependente not in visitados and dependente not in fila:
                fila.append(dependente)

        relatorio.append({
            "url": url_sem_fragmento,
            "arquivo": str(caminho),
            "status": status,
            "bytes": len(conteudo),
            "tipo_conteudo": cabecalhos.get("Content-Type", ""),
            "erro": erro,
            "contextos_relevantes": len(achados),
        })

    (SAIDA / "achados-javascript.txt").write_text(
        "\n".join(contextos),
        encoding="utf-8",
    )
    gravar_json(
        SAIDA / "javascript-resumo.json",
        {
            "ativos": relatorio,
            "urls_encontradas": sorted(urls_encontradas),
            "fila_restante": fila,
        },
    )
    return relatorio, contextos, urls_encontradas


def testar_endpoint(nome, url, metodo="GET", dados=None, token=None):
    print(metodo, url)
    status, cabecalhos, conteudo, erro = requisitar(
        url,
        metodo=metodo,
        dados=dados,
        token=token,
    )
    resumo, convertido = salvar_resposta(
        nome,
        status,
        cabecalhos,
        conteudo,
        erro,
    )
    resumo.update({
        "url": url,
        "metodo": metodo,
        "dados_enviados": dados,
    })
    return resumo, convertido


def testar_gateway(token):
    consultas = []

    alvos_get = [
        ("tipos-produto", f"{API_V1}/dossie/tiposProduto"),
        ("acoes-fiscalizacao", f"{API_V1}/dossie/acoesFiscalizacao"),
        ("classes-risco", f"{API_V1}/dossie/classesRisco"),
        (
            "detalhe-dossie-exemplo",
            f"{API_V1}/dossie/25351093571202597",
        ),
        ("swagger-config", f"{GATEWAY}/swagger-ui/swagger-config"),
        ("swagger-api-docs", f"{GATEWAY}/v3/api-docs"),
        ("swagger-index", f"{GATEWAY}/swagger-ui/index.html"),
    ]

    for nome, url in alvos_get:
        resumo, _ = testar_endpoint(nome, url, token=token)
        consultas.append(resumo)

    tipos = "6,2,15,1,8,12,3"
    corpos = [
        {
            "page": 1,
            "count": 5,
            "filter": {
                "tipoAssunto": "1",
                "tiposProduto": tipos,
            },
        },
        {
            "page": 1,
            "count": 5,
            "filter": {
                "tipoAssunto": "2",
                "tiposProduto": tipos,
            },
        },
        {
            "page": 1,
            "count": 5,
            "filter": {
                "tipoAssunto": "3",
                "tiposProduto": tipos,
            },
        },
        {
            "page": 1,
            "count": 5,
            "filter": {
                "parametroProduto": "SUPLEMENTO",
                "tipoAssunto": "2",
                "tiposProduto": "6",
            },
        },
    ]

    for indice, corpo in enumerate(corpos, start=1):
        resumo, _ = testar_endpoint(
            f"busca-dossie-{indice}",
            f"{API_V1}/dossie/",
            metodo="POST",
            dados=corpo,
            token=token,
        )
        consultas.append(resumo)

    gravar_json(SAIDA / "gateway-resumo.json", consultas)
    return consultas


def main():
    print("Versão do inspetor:", VERSAO_INSPETOR)
    SAIDA.mkdir(parents=True, exist_ok=True)
    resumo_geral = {
        "gerado_em": datetime.now(timezone.utc).isoformat(),
        "versao": VERSAO_INSPETOR,
        "documentacao": DOCUMENTACAO,
        "gateway": GATEWAY,
    }

    token = obter_token()

    print("GET", DOCUMENTACAO)
    status, cabecalhos, conteudo, erro = requisitar(DOCUMENTACAO)
    resumo_documentacao, _ = salvar_resposta(
        "documentacao",
        status,
        cabecalhos,
        conteudo,
        erro,
    )

    if conteudo and status == 200:
        ativos, contextos, urls = baixar_arvore_javascript(conteudo)
    else:
        ativos, contextos, urls = [], [], set()
        print(
            "Portal de documentação indisponível; "
            "continuando pelo gateway autenticado."
        )

    consultas_gateway = testar_gateway(token)
    resumo_geral.update({
        "resumo_documentacao": resumo_documentacao,
        "ativos_javascript": len(ativos),
        "contextos_relevantes": len(contextos),
        "urls_encontradas": sorted(urls),
        "consultas_gateway": consultas_gateway,
    })
    gravar_json(SAIDA / "resumo-geral.json", resumo_geral)

    json_validos = sum(1 for item in consultas_gateway if item["json"])
    buscas_validas = sum(
        1
        for item in consultas_gateway
        if item["nome"].startswith("busca-dossie-")
        and item["json"]
        and item["status"] == 200
    )
    print("Ativos JavaScript:", len(ativos))
    print("Contextos relevantes:", len(contextos))
    print("Respostas JSON no gateway:", json_validos)
    print("Buscas de dossiê válidas:", buscas_validas)

    if buscas_validas == 0:
        raise RuntimeError(
            "A autenticação e os metadados funcionaram, mas nenhuma "
            "busca de dossiê devolveu JSON válido. Baixe o artifact "
            "para análise."
        )

    print("Diagnóstico do gateway de Produtos Irregulares concluído.")


if __name__ == "__main__":
    main()
