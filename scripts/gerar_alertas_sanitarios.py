from collections import defaultdict
from datetime import date, datetime, timezone
from html import unescape
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.parse import urlencode
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
DESTINO = DADOS / "alertas_sanitarios"
API = "https://consultas.anvisa.gov.br/api/consulta/alertasSanitarios"
ROTA = "https://consultas.anvisa.gov.br/#/alertas-sanitarios/"
VERSAO = "2026-08-31-alertas-completo-v1"
ANO_INICIAL = 2000


def digitos(valor):
    return re.sub(r"\D", "", str(valor or ""))


def normalizar(valor):
    valor = unescape(str(valor or "")).upper()
    return re.sub(r"[^A-Z0-9]", "", valor)


def texto_html(valor):
    texto = unescape(str(valor or ""))
    texto = re.sub(r"(?i)<\s*(?:br|/p|/li|/div)\s*/?>", "\n", texto)
    texto = re.sub(r"<[^>]+>", " ", texto)
    texto = re.sub(r"[ \t\r\f\v]+", " ", texto)
    texto = re.sub(r"\n\s*\n+", "\n", texto)
    return texto.strip()


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

    def json(self, url, params=None, tentativas=10):
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
                if tentativa >= tentativas:
                    break
                if isinstance(erro, urllib.error.HTTPError) and erro.code == 429:
                    try:
                        espera = max(30, int(erro.headers.get("Retry-After", "")))
                    except (TypeError, ValueError):
                        espera = min(180, 20 * tentativa)
                    print("HTTP 429 | nova tentativa em", espera, "segundos")
                else:
                    espera = min(60, 5 * tentativa)
                    print("Falha temporária:", repr(erro), "| espera", espera)
                time.sleep(espera)
        raise RuntimeError(f"Falha na API de alertas: {url}: {ultimo!r}")


def listar_periodo(sessao, ano):
    pagina = 1
    itens = []
    while True:
        dados = sessao.json(API + "/listagem", {
            "page": pagina,
            "count": 100,
            "column": "numeroSeqAlerta",
            "order": "asc",
            "filter[dataInicial]": f"{ano}-01-01T00:00:00.000Z",
            "filter[dataFinal]": f"{ano}-12-31T23:59:59.999Z",
        })
        pagina_itens = dados.get("content") or []
        itens.extend(pagina_itens)
        print(
            "Ano", ano, "| página", pagina, "de", dados.get("totalPages"),
            "| alertas", len(itens),
        )
        if dados.get("last", True) or not pagina_itens:
            break
        pagina += 1
        if pagina > 500:
            raise RuntimeError(f"Paginação excessiva no ano {ano}.")
        time.sleep(0.3)
    return itens


def carregar_publicados():
    publicados = {}
    pasta = DESTINO / "alertas"
    if not pasta.exists():
        return publicados
    for arquivo in pasta.glob("*.json"):
        try:
            dados = json.loads(arquivo.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for item in dados if isinstance(dados, list) else []:
            if isinstance(item, dict) and item.get("id_alerta") is not None:
                publicados[str(item["id_alerta"])] = item
    return publicados


def extrair_contextuais(texto, rotulos):
    encontrados = []
    padrao = "|".join(rotulos)
    for valor in re.findall(
        rf"(?im)(?:{padrao})\s*:\s*([^\n]+)", texto
    ):
        for parte in re.split(r"\s*;\s*|\s*,\s*(?=[A-Z0-9])", valor):
            parte = parte.strip(" .;-–—")
            if parte and len(parte) <= 180:
                encontrados.append(parte)
    return encontrados


def identificadores(textos):
    unido = "\n".join(textos)
    saida = []
    categorias = {
        "lote": [r"lotes? afetad[oa]s?", r"n[uú]meros? dos? lotes?", r"lotes?"],
        "serie": [r"n[uú]meros? de s[eé]rie afetad[oa]s?", r"s[eé]ries? afetad[oa]s?"],
        "modelo": [r"modelos? afetad[oa]s?", r"modelos?"],
    }
    vistos = set()
    for tipo, rotulos in categorias.items():
        for valor in extrair_contextuais(unido, rotulos):
            chave = normalizar(valor)
            if not chave or chave in {"TODOSOSLOTES", "TODOS", "NAOSEAPLICA"}:
                continue
            assinatura = (tipo, chave)
            if assinatura not in vistos:
                vistos.add(assinatura)
                saida.append({"tipo": tipo, "valor": valor, "chave": chave})
    return saida


def extrair_registros(textos):
    unido = "\n".join(textos)
    registros = set()
    for valor in re.findall(
        r"(?i)(?:registro|regulariza[cç][aã]o)(?:\s+ANVISA)?\s*:\s*([0-9./-]{8,24})",
        unido,
    ):
        numero = digitos(valor)
        if 8 <= len(numero) <= 14:
            registros.add(numero)
    return sorted(registros)


def extrair_cnpjs(textos):
    unido = "\n".join(textos)
    return sorted({
        digitos(valor)
        for valor in re.findall(r"\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}", unido)
    })


def limpar(detalhe):
    campos_html = (
        "titulo", "resumo", "identificacaoProduto", "descricaoProduto",
        "descricaoProblema", "acao", "motivacao", "fabricante",
        "recomendacoes", "informacoesComplementares",
    )
    textos = {campo: texto_html(detalhe.get(campo)) for campo in campos_html}
    valores = [valor for valor in textos.values() if valor]
    numero = detalhe.get("numeroSeqAlerta")
    return {
        "id_alerta": detalhe.get("idAlerta"),
        "numero_alerta": numero,
        "tipo_alerta": detalhe.get("tipoAlerta"),
        "area": detalhe.get("area"),
        "tipo_produto": detalhe.get("tipoProduto"),
        "data_publicacao": detalhe.get("dataPublicacao"),
        "data_atualizacao": detalhe.get("dataUltimaAtualizacao"),
        **{
            "titulo": textos["titulo"], "resumo": textos["resumo"],
            "identificacao_produto": textos["identificacaoProduto"],
            "descricao_produto": textos["descricaoProduto"],
            "problema": textos["descricaoProblema"],
            "acao": textos["acao"], "motivacao": textos["motivacao"],
            "fabricante": textos["fabricante"],
            "recomendacoes": textos["recomendacoes"],
            "informacoes_complementares": textos["informacoesComplementares"],
        },
        "registros": extrair_registros(valores),
        "cnpjs": extrair_cnpjs(valores),
        "identificadores": identificadores(valores),
        "outras_publicacoes": detalhe.get("itemsAlertasOutrasPublicacoes") or [],
        "anexos": [
            {"id": x.get("idAnexo"), "nome": x.get("nome"), "tipo": x.get("tipo")}
            for x in detalhe.get("anexos") or [] if isinstance(x, dict)
        ],
        "url_oficial": ROTA + str(detalhe.get("idAlerta") or ""),
    }


def referencia(alerta):
    return {
        "a": alerta.get("numero_alerta"),
        "i": alerta.get("id_alerta"),
        "d": alerta.get("data_publicacao"),
        "t": alerta.get("titulo"),
    }


def main():
    print("Versão do gerador:", VERSAO)
    sessao = Sessao()
    listagem = {}
    for ano in range(ANO_INICIAL, date.today().year + 1):
        for item in listar_periodo(sessao, ano):
            if item.get("idAlerta") is not None:
                listagem[str(item["idAlerta"])] = item
    if len(listagem) < 1000:
        raise RuntimeError(f"A fonte informou somente {len(listagem)} alertas.")

    anteriores = carregar_publicados()
    alertas = []
    reutilizados = 0
    baixados = 0
    for indice, (chave, resumo) in enumerate(
        sorted(listagem.items(), key=lambda x: int(x[0])), start=1
    ):
        anterior = anteriores.get(chave)
        if anterior and anterior.get("data_atualizacao") == resumo.get("dataUltimaAtualizacao"):
            alertas.append(anterior)
            reutilizados += 1
        else:
            detalhe = sessao.json(API + "/detalhes/" + chave)
            alertas.append(limpar(detalhe))
            baixados += 1
            time.sleep(1.2)
        if indice % 25 == 0 or indice == len(listagem):
            print(
                "Detalhes:", indice, "de", len(listagem),
                "| novos/alterados", baixados, "| reutilizados", reutilizados,
            )

    antigo = len(anteriores)
    if antigo and len(alertas) < antigo * 0.90:
        raise RuntimeError(
            f"Queda anormal de alertas: {antigo} -> {len(alertas)}."
        )

    por_alerta = defaultdict(list)
    por_registro = defaultdict(lambda: defaultdict(list))
    por_cnpj = defaultdict(lambda: defaultdict(list))
    por_identificador = defaultdict(lambda: defaultdict(list))
    por_ano = defaultdict(list)
    for alerta in alertas:
        numero = str(alerta.get("numero_alerta") or "0").zfill(5)
        por_alerta[numero[:3]].append(alerta)
        ref = referencia(alerta)
        for registro in alerta.get("registros") or []:
            por_registro[registro[:3]][registro].append(ref)
        for cnpj in alerta.get("cnpjs") or []:
            por_cnpj[cnpj[:3]][cnpj].append(ref)
        for identificador in alerta.get("identificadores") or []:
            chave = identificador.get("chave", "")
            if chave:
                shard = (chave[:2] if len(chave) >= 2 else chave + "_")
                por_identificador[shard][chave].append({
                    **ref, "tipo": identificador.get("tipo"),
                    "valor": identificador.get("valor"),
                })
        ano = str(alerta.get("data_publicacao") or "")[:4]
        por_ano[ano if ano.isdigit() else "sem_data"].append({
            **ref,
            "area": alerta.get("area"),
            "tipo_produto": alerta.get("tipo_produto"),
            "registros": alerta.get("registros") or [],
            "cnpjs": alerta.get("cnpjs") or [],
        })

    temporario = Path(tempfile.mkdtemp(prefix="alertas_", dir=DADOS))
    try:
        for shard, itens in por_alerta.items():
            gravar_json(temporario / "alertas" / f"{shard}.json", itens)
        for shard, mapa in por_registro.items():
            gravar_json(temporario / "indices" / "registros" / f"{shard}.json", dict(mapa))
        for shard, mapa in por_cnpj.items():
            gravar_json(temporario / "indices" / "cnpj" / f"{shard}.json", dict(mapa))
        for shard, mapa in por_identificador.items():
            gravar_json(temporario / "indices" / "lotes_series_modelos" / f"{shard}.json", dict(mapa))
        for ano, itens in por_ano.items():
            gravar_json(temporario / "busca" / f"{ano}.json", itens)
        if DESTINO.exists():
            shutil.rmtree(DESTINO)
        temporario.rename(DESTINO)
    except Exception:
        shutil.rmtree(temporario, ignore_errors=True)
        raise

    manifesto_path = DADOS / "manifest.json"
    manifesto = json.loads(manifesto_path.read_text(encoding="utf-8"))
    manifesto.setdefault("bases", {})["alertas_sanitarios"] = {
        "status": "ok", "fonte": API,
        "gerado_em": datetime.now(timezone.utc).isoformat(),
        "alertas": len(alertas), "novos_ou_alterados": baixados,
        "reutilizados": reutilizados,
        "com_registro": sum(bool(x.get("registros")) for x in alertas),
        "com_cnpj": sum(bool(x.get("cnpjs")) for x in alertas),
        "com_lote_serie_modelo": sum(bool(x.get("identificadores")) for x in alertas),
        "indices": ["numero_alerta", "registro", "cnpj", "lote_serie_modelo", "ano"],
        "observacao": "Versão completa sem cópia local dos PDFs anexos.",
    }
    gravar_json(manifesto_path, manifesto)
    print(
        "alertas_sanitarios:", len(alertas), "alertas |",
        baixados, "baixados |", reutilizados, "reutilizados",
    )


if __name__ == "__main__":
    main()
