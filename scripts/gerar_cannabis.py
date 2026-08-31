from datetime import datetime, timezone
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.parse import urlencode
from collections import defaultdict
import gzip
import json
import re
import shutil
import tempfile
import time
import urllib.error
import urllib.request


BASE = Path(__file__).resolve().parent.parent
DADOS = BASE / "dados"
DESTINO = DADOS / "cannabis"
API = "https://consultas.anvisa.gov.br/api/consulta/cannabis"
ROTA = "https://consultas.anvisa.gov.br/#/cannabis/"
VERSAO = "2026-08-31-cannabis-v1"


def digitos(valor):
    return re.sub(r"\D", "", str(valor or ""))


def gravar_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )


class Sessao:
    def __init__(self):
        self.authorization = "Guest"
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(CookieJar())
        )

    def json(self, url, params=None, tentativas=4):
        if params:
            url += ("&" if "?" in url else "?") + urlencode(params)
        ultimo = None
        for tentativa in range(1, tentativas + 1):
            pedido = urllib.request.Request(url, headers={
                "Accept": "application/json, text/plain, */*",
                "Accept-Encoding": "gzip",
                "Authorization": self.authorization,
                "Referer": ROTA,
                "User-Agent": "base-vigilancia/1.0",
            })
            try:
                with self.opener.open(pedido, timeout=180) as resposta:
                    corpo = resposta.read()
                    if "gzip" in resposta.headers.get("Content-Encoding", "").casefold():
                        corpo = gzip.decompress(corpo)
                    token = resposta.headers.get("Set-Authorization")
                    if token:
                        self.authorization = token
                    return json.loads(corpo.decode("utf-8"))
            except (urllib.error.URLError, urllib.error.HTTPError,
                    TimeoutError, OSError, json.JSONDecodeError) as erro:
                ultimo = erro
                if tentativa < tentativas:
                    time.sleep(5 * tentativa)
        raise RuntimeError(f"Falha na API Cannabis: {url}: {ultimo!r}")


def listar(sessao, situacao):
    pagina = 1
    encontrados = []
    while True:
        dados = sessao.json(API + "/produtos/", {
            "page": pagina,
            "count": 100,
            "filter[situacaoRegistro]": situacao,
        })
        itens = dados.get("content") or []
        encontrados.extend(itens)
        print(
            "Situação", situacao, "| página", pagina,
            "de", dados.get("totalPages"), "| itens", len(encontrados),
        )
        if dados.get("last", True) or not itens:
            break
        pagina += 1
        if pagina > 1000:
            raise RuntimeError("Paginação Cannabis excedeu o limite de segurança.")
    return encontrados


def limpar_apresentacao(item):
    return {
        "codigo": item.get("codigo"),
        "registro": digitos(item.get("registro")),
        "numero": item.get("numero"),
        "apresentacao": item.get("apresentacao"),
        "formas_farmaceuticas": item.get("formasFarmaceuticas") or [],
        "principios_ativos": item.get("principiosAtivos") or [],
        "data_publicacao": item.get("dataPublicacao"),
        "prazo_validade": item.get("validade"),
        "tipo_validade": item.get("tipoValidade"),
        "embalagem_primaria": item.get("embalagemPrimaria"),
        "embalagem_secundaria": item.get("embalagemSecundaria"),
        "envoltorios": item.get("envoltorios") or [],
        "acessorios": item.get("acessorios") or [],
        "acondicionamento": item.get("acondicionamento"),
        "fabricantes_nacionais": item.get("fabricantesNacionais") or [],
        "fabricantes_internacionais": item.get("fabricantesInternacionais") or [],
        "vias_administracao": item.get("viasAdministracao") or [],
        "conservacao": item.get("conservacao") or [],
        "restricao_prescricao": item.get("restricaoPrescricao") or [],
        "restricao_uso": item.get("restricaoUso") or [],
        "destinacao": item.get("destinacao") or [],
        "restricao_hospitalar": item.get("restricaoHospitais"),
        "tarja": item.get("tarja"),
        "fracionada": item.get("apresentacaoFracionada"),
        "ativa": bool(item.get("ativa")),
    }


def limpar_produto(detalhe, resumo):
    empresa = detalhe.get("empresa") or resumo.get("empresa") or {}
    processo = detalhe.get("processo") or resumo.get("processo") or {}
    produto_resumo = resumo.get("produto") or {}
    numero = digitos(processo.get("numero"))
    registro = digitos(detalhe.get("numeroRegistro") or produto_resumo.get("numeroRegistro"))
    apresentacoes = [
        limpar_apresentacao(x)
        for x in detalhe.get("apresentacoes") or []
        if isinstance(x, dict)
    ]
    return {
        "produto": detalhe.get("nomeComercial") or produto_resumo.get("nome"),
        "registro": registro,
        "processo": numero,
        "situacao": produto_resumo.get("situacaoApresentacao"),
        "categoria": detalhe.get("categoriaRegulatoria") or "Produto de cannabis",
        "principio_ativo": detalhe.get("principioAtivo") or produto_resumo.get("principioAtivo"),
        "classes_terapeuticas": detalhe.get("classesTerapeuticas") or [],
        "data_autorizacao": detalhe.get("dataProduto") or produto_resumo.get("dataRegistro"),
        "vencimento_autorizacao": detalhe.get("dataVencimentoRegistro") or produto_resumo.get("dataVencimentoRegistro"),
        "empresa": empresa.get("razaoSocial"),
        "cnpj": digitos(empresa.get("cnpj")),
        "afe": digitos(empresa.get("numeroAutorizacao")),
        "data_atualizacao": detalhe.get("dataAtualizacao") or resumo.get("dataCarga"),
        "apresentacoes": apresentacoes,
    }


def main():
    print("Versão do gerador:", VERSAO)
    sessao = Sessao()
    resumos = {}
    for situacao in ("V", "C"):
        for item in listar(sessao, situacao):
            processo = digitos((item.get("processo") or {}).get("numero"))
            if processo:
                resumos[processo] = item
    if len(resumos) < 5:
        raise RuntimeError(f"A fonte devolveu somente {len(resumos)} produtos.")

    produtos = []
    for indice, (processo, resumo) in enumerate(sorted(resumos.items()), start=1):
        detalhe = sessao.json(API + "/produtos/" + processo)
        produtos.append(limpar_produto(detalhe, resumo))
        print("Detalhes:", indice, "de", len(resumos), "|", processo)

    registros = defaultdict(list)
    processos = defaultdict(list)
    cnpjs = defaultdict(list)
    for produto in produtos:
        if produto["registro"]:
            registros[produto["registro"][:3]].append(produto)
        if produto["processo"]:
            processos[produto["processo"][5:8]].append(produto)
        if len(produto["cnpj"]) == 14:
            cnpjs[produto["cnpj"][:3]].append(produto)

    temporario = Path(tempfile.mkdtemp(prefix="cannabis_", dir=DADOS))
    try:
        gravar_json(temporario / "catalogo.json", produtos)
        for shard, itens in registros.items():
            gravar_json(temporario / "registros" / f"{shard}.json", itens)
        for shard, itens in processos.items():
            gravar_json(temporario / "processos" / f"{shard}.json", itens)
        for shard, itens in cnpjs.items():
            gravar_json(temporario / "cnpj" / f"{shard}.json", itens)
        if DESTINO.exists():
            shutil.rmtree(DESTINO)
        temporario.rename(DESTINO)
    except Exception:
        shutil.rmtree(temporario, ignore_errors=True)
        raise

    manifesto_path = DADOS / "manifest.json"
    manifesto = json.loads(manifesto_path.read_text(encoding="utf-8"))
    manifesto.setdefault("bases", {})["cannabis"] = {
        "status": "ok",
        "fonte": API,
        "gerado_em": datetime.now(timezone.utc).isoformat(),
        "registros": len(produtos),
        "apresentacoes": sum(len(x["apresentacoes"]) for x in produtos),
        "ativos": sum(x["situacao"] == "Válido" for x in produtos),
        "cancelados_caducos": sum(x["situacao"] != "Válido" for x in produtos),
        "indices": ["registro", "processo", "cnpj"],
        "observacao": "Sem histórico de expedientes ou alterações.",
    }
    gravar_json(manifesto_path, manifesto)
    print("cannabis:", len(produtos), "produtos | base gerada com sucesso")


if __name__ == "__main__":
    main()
