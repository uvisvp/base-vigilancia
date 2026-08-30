from pathlib import Path
from datetime import datetime, timezone
import gzip
import html
import json
import re
import time
import urllib.error
import urllib.request


BASE_API = "https://api.anvisa.gov.br/consultas-externas"
PAGINA_CONSULTA = "https://consultas.anvisa.gov.br/#/dossie/"
SAIDA = Path("diagnostico-produtos-irregulares")


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
                "Falha temporária:",
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


def main():
    SAIDA.mkdir(parents=True, exist_ok=True)
    resumo_geral = {
        "gerado_em": datetime.now(timezone.utc).isoformat(),
        "base_api": BASE_API,
        "consultas": [],
    }

    consultas_get = [
        ("documentacao", f"{BASE_API}/dossie-doc"),
        ("tipos-produto", f"{BASE_API}/dossie/tiposProduto"),
        ("acoes-fiscalizacao", f"{BASE_API}/dossie/acoesFiscalizacao"),
        ("classes-risco", f"{BASE_API}/dossie/classesRisco"),
    ]

    for nome, url in consultas_get:
        print("GET", url)
        status, cabecalhos, conteudo, erro = requisitar(url)
        resumo, _ = salvar_resposta(
            nome,
            status,
            cabecalhos,
            conteudo,
            erro,
        )
        resumo_geral["consultas"].append(resumo)

        if nome == "documentacao" and conteudo:
            (SAIDA / "documentacao-limpa.txt").write_text(
                texto_da_documentacao(conteudo),
                encoding="utf-8",
            )

    tentativas_post = [
        {
            "sorting": {"processo": "DESC"},
            "order": "DESC",
            "page": "1",
            "count": 20,
            "filter": {"tipoAssunto": "1"},
        },
        {
            "sorting": {"processo": "DESC"},
            "page": 1,
            "count": 20,
            "filter": {
                "tipoAssunto": "1",
                "parametroProduto": "SUPLEMENTO",
            },
        },
        {
            "sorting": {"processo": "DESC"},
            "order": "DESC",
            "page": "1",
            "count": 20,
            "filter": {
                "tipoAssunto": "1",
                "parametroProduto": "",
                "processo": "",
                "empresaEnvolvidaCnpj": "",
                "empresaEnvolvidaRazaoSocial": "",
            },
        },
    ]

    post_valido = False
    for indice, payload in enumerate(tentativas_post, start=1):
        nome = f"busca-post-{indice}"
        gravar_json(SAIDA / f"{nome}-payload.json", payload)
        print("POST", f"{BASE_API}/dossie", "| tentativa", indice)
        status, cabecalhos, conteudo, erro = requisitar(
            f"{BASE_API}/dossie",
            metodo="POST",
            dados=payload,
        )
        resumo, convertido = salvar_resposta(
            nome,
            status,
            cabecalhos,
            conteudo,
            erro,
        )
        resumo_geral["consultas"].append(resumo)

        if status == 200 and isinstance(convertido, (dict, list)):
            post_valido = True
            break

    resumo_geral["post_valido"] = post_valido
    gravar_json(SAIDA / "resumo-geral.json", resumo_geral)

    for item in resumo_geral["consultas"]:
        print(
            item["nome"],
            "| status",
            item["status"],
            "|",
            item["bytes"],
            "bytes | JSON",
            item["json"],
        )

    if not post_valido:
        raise RuntimeError(
            "Nenhuma consulta POST devolveu JSON válido. "
            "Baixe o artifact para análise."
        )

    print("Diagnóstico da API concluído com sucesso.")


if __name__ == "__main__":
    main()
