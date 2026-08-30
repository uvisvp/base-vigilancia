from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse
import gzip
import html
import json
import re
import time
import urllib.error
import urllib.request


BASE_API = "https://api.anvisa.gov.br/consultas-externas"
PORTAL_API = "https://api.anvisa.gov.br/"
PAGINA_CONSULTA = "https://consultas.anvisa.gov.br/#/dossie/"
SAIDA = Path("diagnostico-produtos-irregulares")
VERSAO_INSPETOR = "2026-08-30-javascript-v2"


def requisitar(url, metodo="GET", dados=None, tentativas=3):
    ultimo_erro = None

    for tentativa in range(1, tentativas + 1):
        corpo = None
        headers = {
            "Accept": "application/json, text/html;q=0.9, */*;q=0.8",
            "Accept-Encoding": "gzip",
            "Origin": "https://consultas.anvisa.gov.br",
            "Referer": PAGINA_CONSULTA,
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/124 Safari/537.36"
            ),
        }

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
                "Falha temporÃ¡ria:",
                repr(ultimo_erro),
                "| nova tentativa em",
                espera,
                "segundos",
            )
            time.sleep(espera)

    return 0, {}, b"", repr(ultimo_erro)


def nome_seguro(nome):
    return re.sub(r"[^a-z0-9_-]+", "-", nome.lower()).strip("-")


def gravar_json(caminho, dados):
    caminho.write_text(
        json.dumps(dados, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def salvar_resposta(nome, status, cabecalhos, conteudo, erro=""):
    base = SAIDA / nome_seguro(nome)
    texto = conteudo.decode("utf-8", errors="replace")
    (base.with_suffix(".txt")).write_text(texto, encoding="utf-8")

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
        "previa": texto[:1000],
    }
    gravar_json(base.with_name(base.name + "-resumo.json"), resumo)
    return resumo, convertido


def texto_da_documentacao(conteudo):
    bruto = conteudo.decode("utf-8", errors="replace")
    sem_scripts = re.sub(
        r"<(script|style)\b[^>]*>.*?</\1>",
        " ",
        bruto,
        flags=re.IGNORECASE | re.DOTALL,
    )
    texto = re.sub(r"<[^>]+>", "\n", sem_scripts)
    texto = html.unescape(texto)
    texto = re.sub(r"[ \t]+", " ", texto)
    texto = re.sub(r"\n\s*\n+", "\n", texto)
    return texto.strip()


def extrair_ativos_javascript(conteudo_html):
    texto = conteudo_html.decode("utf-8", errors="replace")
    caminhos = re.findall(
        r'(?:src|href)=["\']([^"\']+\.js(?:\?[^"\']*)?)["\']',
        texto,
        flags=re.IGNORECASE,
    )
    ativos = []

    for caminho in caminhos:
        url = urljoin(PORTAL_API, html.unescape(caminho))
        if (
            "ruxitagentjs" in url
            or "/cdn-cgi/" in url
            or url in ativos
        ):
            continue
        ativos.append(url)

    return ativos


def contextos_relevantes(texto, nome_arquivo):
    padrao = re.compile(
        r"dossi[eÃª]|consultas-externas|openapi|swagger|"
        r"api[_-]?url|base[_-]?url|environment",
        flags=re.IGNORECASE,
    )
    vistos = set()
    contextos = []

    for encontrado in padrao.finditer(texto):
        inicio = max(0, encontrado.start() - 350)
        fim = min(len(texto), encontrado.end() + 500)
        contexto = texto[inicio:fim].replace("\r", " ").replace("\n", " ")
        contexto = re.sub(r"\s+", " ", contexto).strip()
        chave = contexto.casefold()
        if chave in vistos:
            continue
        vistos.add(chave)
        contextos.append(f"\n### {nome_arquivo}\n{contexto}\n")

    return contextos


def analisar_javascript(conteudo_html):
    ativos = extrair_ativos_javascript(conteudo_html)
    relatorio = []
    contextos = []
    urls_encontradas = set()
    pasta_ativos = SAIDA / "javascript"
    pasta_ativos.mkdir(parents=True, exist_ok=True)

    for indice, url in enumerate(ativos, start=1):
        print("GET JavaScript", url)
        status, cabecalhos, conteudo, erro = requisitar(url)
        nome = Path(urlparse(url).path).name or f"ativo-{indice}.js"
        nome = nome_seguro(nome.removesuffix(".js")) + ".js"
        caminho = pasta_ativos / nome

        if conteudo:
            caminho.write_bytes(conteudo)

        texto = conteudo.decode("utf-8", errors="replace")
        achados_ativo = contextos_relevantes(texto, nome)
        contextos.extend(achados_ativo)

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

        relatorio.append({
            "url": url,
            "arquivo": str(caminho),
            "status": status,
            "bytes": len(conteudo),
            "tipo_conteudo": cabecalhos.get("Content-Type", ""),
            "erro": erro,
            "contextos_relevantes": len(achados_ativo),
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
        },
    )
    return relatorio, contextos, urls_encontradas


def testar_configuracoes():
    candidatos = [
        "assets/config.json",
        "assets/config/config.json",
        "assets/environment.json",
        "config.json",
        "swagger.json",
        "openapi.json",
        "v3/api-docs",
    ]
    resultados = []

    for indice, caminho in enumerate(candidatos, start=1):
        url = urljoin(PORTAL_API, caminho)
        print("GET configuraÃ§Ã£o", url)
        status, cabecalhos, conteudo, erro = requisitar(url)
        resumo, _ = salvar_resposta(
            f"configuracao-{indice}",
            status,
            cabecalhos,
            conteudo,
            erro,
        )
        resumo["url"] = url
        resultados.append(resumo)

    gravar_json(SAIDA / "configuracoes-resumo.json", resultados)
    return resultados


def main():
    print("VersÃ£o do inspetor:", VERSAO_INSPETOR)
    SAIDA.mkdir(parents=True, exist_ok=True)
    resumo_geral = {
        "gerado_em": datetime.now(timezone.utc).isoformat(),
        "base_api": BASE_API,
        "portal_api": PORTAL_API,
        "consultas": [],
    }

    url_documentacao = f"{BASE_API}/dossie-doc"
    print("GET", url_documentacao)
    status, cabecalhos, conteudo, erro = requisitar(url_documentacao)
    resumo, _ = salvar_resposta(
        "documentacao",
        status,
        cabecalhos,
        conteudo,
        erro,
    )
    resumo_geral["consultas"].append(resumo)

    if not conteudo:
        raise RuntimeError("O portal da API nÃ£o devolveu conteÃºdo.")

    (SAIDA / "documentacao-limpa.txt").write_text(
        texto_da_documentacao(conteudo),
        encoding="utf-8",
    )

    ativos, contextos, urls = analisar_javascript(conteudo)
    configuracoes = testar_configuracoes()
    resumo_geral.update({
        "ativos_javascript": len(ativos),
        "contextos_relevantes": len(contextos),
        "urls_encontradas": sorted(urls),
        "configuracoes_testadas": len(configuracoes),
    })
    gravar_json(SAIDA / "resumo-geral.json", resumo_geral)

    print("Ativos JavaScript:", len(ativos))
    print("Contextos relevantes:", len(contextos))
    print("URLs encontradas:", len(urls))

    if not ativos:
        raise RuntimeError(
            "Nenhum arquivo JavaScript foi localizado no portal."
        )

    print("DiagnÃ³stico dos arquivos da API concluÃ­do.")


if __name__ == "__main__":
    main()
