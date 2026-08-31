from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode, urljoin, urlparse
import gzip
import json
import os
import re
import shutil
import time
import urllib.error
import urllib.request


PORTAL = "https://consultas.anvisa.gov.br/"
ROTA_PUBLICA = "https://consultas.anvisa.gov.br/#/cannabis/"
GATEWAY = (
    "https://api-gateway.prd.apps.anvisa.gov.br/"
    "consultas-externas-api"
)
API_V1 = f"{GATEWAY}/api/v1"
TOKEN_URL = (
    "https://acesso.prd.apps.anvisa.gov.br/auth/"
    "realms/externo/protocol/openid-connect/token"
)
SAIDA = Path("diagnostico-cannabis")
VERSAO = "2026-08-31-cannabis-v1"
MAXIMO_ATIVOS = 140
MAXIMO_RESPOSTA = 20 * 1024 * 1024
ATIVOS_OBRIGATORIOS = (
    "scripts/app/cannabis/cannabis.controller.js",
    "scripts/services/cannabis.service.js",
)


def agora_iso():
    return datetime.now(timezone.utc).isoformat()


def nome_seguro(nome):
    return re.sub(r"[^a-z0-9_-]+", "-", nome.casefold()).strip("-")


def gravar_json(caminho, dados):
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(
        json.dumps(dados, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def requisitar(
    url,
    metodo="GET",
    dados=None,
    token=None,
    tentativas=3,
    referer=ROTA_PUBLICA,
):
    ultimo_erro = None

    for tentativa in range(1, tentativas + 1):
        corpo = None
        headers = {
            "Accept": (
                "application/json, text/plain, text/html;q=0.8, "
                "*/*;q=0.5"
            ),
            "Accept-Encoding": "gzip",
            "Origin": "https://consultas.anvisa.gov.br",
            "Referer": referer,
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
                conteudo = resposta.read(MAXIMO_RESPOSTA + 1)
                if len(conteudo) > MAXIMO_RESPOSTA:
                    raise RuntimeError(
                        f"Resposta maior que {MAXIMO_RESPOSTA} bytes: {url}"
                    )
                cabecalhos = dict(resposta.headers.items())
                if "gzip" in resposta.headers.get(
                    "Content-Encoding", ""
                ).casefold():
                    conteudo = gzip.decompress(conteudo)
                return resposta.status, cabecalhos, conteudo, ""
        except urllib.error.HTTPError as erro:
            conteudo = erro.read(MAXIMO_RESPOSTA + 1)
            cabecalhos = dict(erro.headers.items())
            if "gzip" in erro.headers.get(
                "Content-Encoding", ""
            ).casefold():
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
            "User-Agent": "base-vigilancia/1.0",
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
        "tipo_json": (
            type(convertido).__name__ if convertido is not None else ""
        ),
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
    return resumo, convertido, texto


def extrair_ativos_html(conteudo):
    texto = conteudo.decode("utf-8", errors="replace")
    caminhos = re.findall(
        r'(?:src|href)=["\']([^"\']+\.js(?:\?[^"\']*)?)["\']',
        texto,
        flags=re.IGNORECASE,
    )
    unicos = []
    vistos = set()
    for caminho in ATIVOS_OBRIGATORIOS + tuple(caminhos):
        url = urljoin(PORTAL, caminho)
        if url not in vistos:
            vistos.add(url)
            unicos.append(url)
    return unicos[:MAXIMO_ATIVOS]


def ocorrencias_cannabis(texto, origem):
    resultados = []
    for correspondencia in re.finditer("cannabis", texto, re.IGNORECASE):
        inicio = max(0, correspondencia.start() - 1000)
        fim = min(len(texto), correspondencia.end() + 1600)
        trecho = texto[inicio:fim].replace("\x00", "")
        resultados.append(
            f"\n===== {origem} | posição {correspondencia.start()} =====\n"
            f"{trecho}\n"
        )
        if len(resultados) >= 120:
            break
    return resultados


def extrair_endpoints(texto):
    candidatos = set()
    expressoes = [
        r'["\']([^"\']{0,160}cannabis[^"\']{0,160})["\']',
        r'(https?://[^"\'\s]{1,300}cannabis[^"\'\s]{0,200})',
        r'(/api/[^"\'\s]{0,200}cannabis[^"\'\s]{0,200})',
    ]
    for expressao in expressoes:
        for valor in re.findall(expressao, texto, flags=re.IGNORECASE):
            valor = valor.replace("\\/", "/").strip()
            if 2 < len(valor) <= 400:
                candidatos.add(valor)
    return candidatos


def caminho_cannabis(valor):
    valor = valor.strip()
    if not valor:
        return ""
    if ".js" in valor.casefold():
        return ""
    if valor.startswith("http://") or valor.startswith("https://"):
        if "api-gateway.prd.apps.anvisa.gov.br" not in valor:
            return ""
        return valor
    if valor.startswith("/api/"):
        return urljoin(GATEWAY + "/", valor.lstrip("/"))
    if valor.startswith("/"):
        return urljoin(API_V1 + "/", valor.lstrip("/"))
    if re.fullmatch(r"[a-zA-Z0-9_./{}?-]+", valor):
        return urljoin(API_V1 + "/", valor)
    return ""


def parece_json_cannabis(dados):
    if dados is None:
        return False
    texto = json.dumps(dados, ensure_ascii=False).casefold()
    sinais = (
        "cannabis",
        "autorizacao",
        "autorização",
        "principioativo",
        "princípio ativo",
        "apresentacao",
        "apresentação",
    )
    return any(sinal in texto for sinal in sinais)


def main():
    print("Versão do inspetor:", VERSAO)
    if SAIDA.exists():
        shutil.rmtree(SAIDA)
    SAIDA.mkdir(parents=True)

    token = obter_token()
    resumos = []
    endpoints_descobertos = set()
    trechos = []

    status, cabecalhos, conteudo, erro = requisitar(
        PORTAL,
        referer=PORTAL,
    )
    resumo, _, texto_portal = salvar_resposta(
        "portal-consultas",
        status,
        cabecalhos,
        conteudo,
        erro,
    )
    resumos.append(resumo)
    trechos.extend(ocorrencias_cannabis(texto_portal, PORTAL))
    endpoints_descobertos.update(extrair_endpoints(texto_portal))

    ativos = extrair_ativos_html(conteudo)
    print("Ativos JavaScript encontrados:", len(ativos))
    gravar_json(SAIDA / "ativos-javascript.json", ativos)

    for indice, url in enumerate(ativos, start=1):
        status, cabecalhos, corpo, erro = requisitar(
            url,
            referer=PORTAL,
        )
        nome = f"ativo-{indice:02d}-{Path(urlparse(url).path).name}"
        resumo, _, texto = salvar_resposta(
            nome,
            status,
            cabecalhos,
            corpo,
            erro,
        )
        resumos.append(resumo)
        if "cannabis" in texto.casefold():
            trechos.extend(ocorrencias_cannabis(texto, url))
            endpoints_descobertos.update(extrair_endpoints(texto))

    (SAIDA / "ocorrencias-cannabis.txt").write_text(
        "".join(trechos) or "Nenhuma ocorrência localizada.",
        encoding="utf-8",
    )

    documentos = [
        f"{GATEWAY}/v3/api-docs",
        f"{GATEWAY}/swagger-ui/swagger-config",
        f"{GATEWAY}/api-docs",
        "https://api.anvisa.gov.br/consultas-externas/cannabis-doc",
    ]
    for indice, url in enumerate(documentos, start=1):
        status, cabecalhos, corpo, erro = requisitar(url, token=token)
        resumo, convertido, texto = salvar_resposta(
            f"documentacao-{indice}",
            status,
            cabecalhos,
            corpo,
            erro,
        )
        resumos.append(resumo)
        if convertido is not None or "cannabis" in texto.casefold():
            trechos.extend(ocorrencias_cannabis(texto, url))
            endpoints_descobertos.update(extrair_endpoints(texto))

    candidatos = {
        f"{API_V1}/cannabis",
        f"{API_V1}/cannabis/produtos",
        f"{API_V1}/cannabis/substancias",
        f"{API_V1}/produto-cannabis",
        f"{API_V1}/produtos-cannabis",
        f"{API_V1}/produtoCannabis",
        f"{API_V1}/produtosCannabis",
    }
    for valor in endpoints_descobertos:
        url = caminho_cannabis(valor)
        if url:
            candidatos.add(url)

    candidatos = sorted(
        url for url in candidatos
        if "cannabis" in url.casefold() and "{" not in url
    )[:40]
    gravar_json(SAIDA / "endpoints-candidatos.json", candidatos)

    consultas = []
    for url in candidatos:
        consultas.extend([
            ("GET", url, None),
            ("GET", f"{url}?page=0&size=10", None),
            ("GET", f"{url}?page=1&count=10", None),
            ("POST", url, {"page": 0, "size": 10}),
            ("POST", url, {"pagina": 1, "quantidade": 10}),
            (
                "POST",
                url,
                {"substancia": 25722, "page": 0, "size": 10},
            ),
        ])

    sucessos = []
    vistos = set()
    for indice, (metodo, url, dados) in enumerate(consultas, start=1):
        assinatura = (
            metodo,
            url,
            json.dumps(dados, sort_keys=True) if dados is not None else "",
        )
        if assinatura in vistos:
            continue
        vistos.add(assinatura)
        print(metodo, url)
        status, cabecalhos, corpo, erro = requisitar(
            url,
            metodo=metodo,
            dados=dados,
            token=token,
            tentativas=2,
        )
        resumo, convertido, _ = salvar_resposta(
            f"consulta-{indice:03d}-{metodo}",
            status,
            cabecalhos,
            corpo,
            erro,
        )
        resumo["url"] = url
        resumo["metodo"] = metodo
        resumo["corpo_enviado"] = dados
        resumos.append(resumo)
        if status == 200 and parece_json_cannabis(convertido):
            sucessos.append({
                "nome": resumo["nome"],
                "url": url,
                "metodo": metodo,
                "corpo_enviado": dados,
                "chaves_json": resumo["chaves_json"],
                "quantidade_json": resumo["quantidade_json"],
            })

    gravar_json(SAIDA / "respostas-resumo.json", resumos)
    gravar_json(SAIDA / "sucessos-cannabis.json", sucessos)
    gravar_json(
        SAIDA / "execucao.json",
        {
            "versao": VERSAO,
            "executado_em": agora_iso(),
            "rota_publica": ROTA_PUBLICA,
            "ativos_javascript": len(ativos),
            "endpoints_candidatos": len(candidatos),
            "consultas_realizadas": len(vistos),
            "respostas_cannabis": len(sucessos),
        },
    )

    linhas = [
        "# Inspeção da fonte de Produtos de Cannabis",
        "",
        f"- Versão: `{VERSAO}`",
        f"- Ativos JavaScript: **{len(ativos)}**",
        f"- Endpoints candidatos: **{len(candidatos)}**",
        f"- Consultas realizadas: **{len(vistos)}**",
        f"- Respostas JSON de Cannabis: **{len(sucessos)}**",
        "",
        "## Respostas aproveitáveis",
        "",
    ]
    if sucessos:
        for item in sucessos:
            linhas.append(
                f"- `{item['metodo']}` `{item['url']}` "
                f"— arquivo `{nome_seguro(item['nome'])}.json`"
            )
    else:
        linhas.append("Nenhuma resposta JSON de Cannabis foi localizada.")
    (SAIDA / "RESUMO.md").write_text(
        "\n".join(linhas) + "\n",
        encoding="utf-8",
    )

    print("Respostas JSON de Cannabis:", len(sucessos))
    print("Diagnóstico salvo em:", SAIDA)
    if not sucessos:
        raise RuntimeError(
            "A fonte de Cannabis ainda não foi localizada. "
            "Baixe o artifact diagnostico-cannabis para análise."
        )


if __name__ == "__main__":
    main()
