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

BASE = Path(__file__).resolve().parent.parent
DADOS = BASE / "dados"
MANIFESTO = DADOS / "manifest.json"
PREFIXO = 2
VERSAO = "2026-08-31-aditivos-coadjuvantes-v1"

PAINEIS = {
    "aditivos_alimentares": {
        "pagina": "https://app.powerbi.com/view?r=eyJrIjoiZmQ2ZDBjNTItMDFmMi00MmM5LWE4Y2QtMzBhOGZlYTU4OGUzIiwidCI6ImI2N2FmMjNmLWMzZjMtNGQzNS04MGM3LWI3MDg1ZjVlZGQ4MSJ9&pageName=ReportSection08a3239a66872bb5b7a9",
        "consultas": [
            {
                "entidade": "Aditivos Permitidos",
                "campos": [
                    "Número categoria", "INS", "Função", "Aplicação dos limites",
                    "Limite mg/kg", "Restrição de Uso", "Explicação sobre limite",
                    "Restrição de uso?", "Aditivos", "Categoria do alimento",
                    "Limite g/100g", "Regulamento Original",
                    "Regulamento pós consolidação", "Observações",
                ],
                "saida": "registros",
            },
            {
                "entidade": "Categorias",
                "campos": [
                    "Categoria", "Nome Categoria", "Descrição Categoria",
                    "Regulamentos", "Alimentos", "Categoria Codex",
                ],
                "saida": "categorias",
            },
        ],
    },
    "coadjuvantes_tecnologia": {
        "pagina": "https://app.powerbi.com/view?r=eyJrIjoiOWViN2VjMWItNWRkYy00ZGNkLTg0M2UtY2Y0Nzg3NzlhMTY1IiwidCI6ImI2N2FmMjNmLWMzZjMtNGQzNS04MGM3LWI3MDg1ZjVlZGQ4MSJ9&pageName=ReportSection08a3239a66872bb5b7a9",
        "consultas": [
            {
                "entidade": "Coadjuvantes Permitidos",
                "campos": [
                    "CodCategoria", "Categoria", "Categoria do Alimento",
                    "Condições de Uso", "Função tecnológica",
                    "Coadjuvante de Tecnologia", "Aplicação do limite",
                    "Explicação sobre limites", "Legislação",
                    "Limite máximo de resíduo (mg/kg)",
                ],
                "saida": "registros",
            },
        ],
    },
    "enzimas_coadjuvantes": {
        "pagina": "https://app.powerbi.com/view?r=eyJrIjoiZmMzYTQxYmItMWVkNi00MzczLThjODAtOWI5ODdiMjZjNzQ0IiwidCI6ImI2N2FmMjNmLWMzZjMtNGQzNS04MGM3LWI3MDg1ZjVlZGQ4MSJ9&pageName=ReportSection",
        "consultas": [
            {
                "entidade": "Enzimas aprovadas total",
                "campos": [
                    "Enzima", "Fonte", "Empresa peticionante", "Fabricante",
                    "Uso aprovado", "Instrumento de aprovação",
                ],
                "saida": "registros",
            },
        ],
    },
}

MAPAS = {
    "aditivos_alimentares": {
        "Número categoria": "numero_categoria",
        "INS": "ins",
        "Função": "funcao",
        "Aplicação dos limites": "aplicacao_limites",
        "Limite mg/kg": "limite_mg_kg",
        "Restrição de Uso": "restricao_uso",
        "Explicação sobre limite": "explicacao_limite",
        "Restrição de uso?": "possui_restricao",
        "Aditivos": "aditivo",
        "Categoria do alimento": "categoria_alimento",
        "Limite g/100g": "limite_g_100g",
        "Regulamento Original": "regulamento_original",
        "Regulamento pós consolidação": "regulamento_pos_consolidacao",
        "Observações": "observacoes",
    },
    "categorias_aditivos": {
        "Categoria": "categoria",
        "Nome Categoria": "nome_categoria",
        "Descrição Categoria": "descricao_categoria",
        "Regulamentos": "regulamentos",
        "Alimentos": "alimentos",
        "Categoria Codex": "categoria_codex",
    },
    "coadjuvantes_tecnologia": {
        "CodCategoria": "codigo_categoria",
        "Categoria": "categoria",
        "Categoria do Alimento": "categoria_alimento",
        "Condições de Uso": "condicoes_uso",
        "Função tecnológica": "funcao_tecnologica",
        "Coadjuvante de Tecnologia": "coadjuvante",
        "Aplicação do limite": "aplicacao_limite",
        "Explicação sobre limites": "explicacao_limites",
        "Legislação": "legislacao",
        "Limite máximo de resíduo (mg/kg)": "limite_maximo_residuo_mg_kg",
    },
    "enzimas_coadjuvantes": {
        "Enzima": "enzima",
        "Fonte": "fonte",
        "Empresa peticionante": "empresa_peticionante",
        "Fabricante": "fabricante",
        "Uso aprovado": "uso_aprovado",
        "Instrumento de aprovação": "instrumento_aprovacao",
    },
}

PRIMARIO = {
    "aditivos_alimentares": "aditivo",
    "coadjuvantes_tecnologia": "coadjuvante",
    "enzimas_coadjuvantes": "enzima",
}


def abrir_url(url, headers=None, dados=None, tentativas=4):
    ultimo = None
    for tentativa in range(1, tentativas + 1):
        req = urllib.request.Request(
            url,
            data=dados,
            headers=headers or {"User-Agent": "Mozilla/5.0 base-vigilancia"},
        )
        try:
            return urllib.request.urlopen(req, timeout=240)
        except urllib.error.HTTPError as erro:
            ultimo = erro
            if erro.code not in (408, 429, 500, 502, 503, 504):
                corpo = erro.read().decode("utf-8", errors="replace")
                raise RuntimeError(f"HTTP {erro.code}: {corpo[:1000]}") from erro
        except (urllib.error.URLError, TimeoutError, OSError) as erro:
            ultimo = erro
        if tentativa < tentativas:
            time.sleep(min(5 * tentativa, 15))
    raise RuntimeError(f"Falha após {tentativas} tentativas: {url}") from ultimo


def baixar_bytes(url, headers=None, dados=None):
    with abrir_url(url, headers, dados) as resposta:
        conteudo = resposta.read()
        if "gzip" in resposta.headers.get("Content-Encoding", "").lower():
            conteudo = gzip.decompress(conteudo)
        return conteudo, resposta.status


def baixar_texto(url, headers=None):
    conteudo, status = baixar_bytes(url, headers)
    return conteudo.decode("utf-8", errors="replace"), status


def localizar_json(html, nome):
    prefixo = rf"var\s+{re.escape(nome)}\s*=\s*"
    como_texto = re.search(prefixo + r"JSON\.parse\('((?:\\.|[^'])*)'\)", html, flags=re.DOTALL)
    if como_texto:
        bruto = como_texto.group(1)
        decodificado = json.loads('"' + bruto.replace('"', '\\"').replace('\\"', '\"') + '"')
        return json.loads(decodificado)
    achou = re.search(prefixo, html, flags=re.DOTALL)
    if achou:
        restante = html[achou.end():].lstrip()
        try:
            obj, _ = json.JSONDecoder().raw_decode(restante)
            return obj
        except json.JSONDecodeError:
            pass
    raise RuntimeError(f"Variável {nome} não localizada")


def api_do_cluster(cluster_uri):
    partes = urlparse(cluster_uri)
    pedacos = (partes.hostname or "").split(".")
    primeiro = pedacos[0].replace("-redirect", "").replace("global-", "")
    pedacos[0] = primeiro + "-api"
    return urlunparse((partes.scheme or "https", ".".join(pedacos), "", "", "", "")).rstrip("/")


def headers_powerbi(resource_key, pagina, json_post=False):
    headers = {
        "Accept": "application/json",
        "ActivityId": str(uuid.uuid4()),
        "RequestId": str(uuid.uuid4()),
        "X-PowerBI-ResourceKey": resource_key,
        "Origin": "https://app.powerbi.com",
        "Referer": pagina,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
    }
    if json_post:
        headers["Content-Type"] = "application/json;charset=UTF-8"
    return headers


def consulta_semantica(entidade, campos):
    selecoes = []
    for campo in campos:
        selecoes.append({
            "Column": {"Expression": {"SourceRef": {"Source": "x"}}, "Property": campo},
            "Name": f"{entidade}.{campo}",
        })
    return {
        "Version": 2,
        "From": [{"Name": "x", "Entity": entidade, "Type": 0}],
        "Select": selecoes,
    }


def montar_payload(model_id, entidade, campos):
    return {
        "version": "1.0.0",
        "queries": [{
            "Query": {"Commands": [{
                "SemanticQueryDataShapeCommand": {
                    "Query": consulta_semantica(entidade, campos),
                    "Binding": {
                        "Primary": {"Groupings": [{"Projections": list(range(len(campos)))}]},
                        "DataReduction": {"DataVolume": 6, "Primary": {"Window": {"Count": 50000}}},
                        "Version": 1,
                    },
                    "ExecutionMetricsKind": 1,
                }
            }]},
            "CacheKey": "",
        }],
        "cancelQueries": [],
        "modelId": model_id,
    }


def inverter_dicionario(dicionario):
    if isinstance(dicionario, list):
        return {i: v for i, v in enumerate(dicionario)}
    if not isinstance(dicionario, dict):
        return {}
    saida = {}
    for chave, valor in dicionario.items():
        if isinstance(valor, int):
            saida[valor] = chave
        else:
            try:
                saida[int(chave)] = valor
            except (TypeError, ValueError):
                pass
    return saida


def localizar_datasets(resposta):
    datasets = []
    for resultado in resposta.get("results", []):
        dsr = resultado.get("result", {}).get("data", {}).get("dsr", {})
        datasets.extend(dsr.get("DS", []))
    return datasets


def decodificar_linhas(resposta, campos):
    saida = []
    for dataset in localizar_datasets(resposta):
        dicionarios = {
            nome: inverter_dicionario(valores)
            for nome, valores in dataset.get("ValueDicts", {}).items()
        }
        for bloco in dataset.get("PH", []):
            for matriz in bloco.values():
                if not isinstance(matriz, list):
                    continue
                esquema = []
                anterior = [None] * len(campos)
                for linha in matriz:
                    if not isinstance(linha, dict):
                        continue
                    if linha.get("S"):
                        esquema = linha["S"]
                    celulas = list(linha.get("C", []))
                    repetidos = int(linha.get("R", 0) or 0)
                    nulos = int(linha.get("Ø", 0) or 0)
                    valores = []
                    cursor = 0
                    for indice in range(len(campos)):
                        mascara = 1 << indice
                        if repetidos & mascara:
                            valor = anterior[indice]
                        elif nulos & mascara:
                            valor = None
                        elif cursor < len(celulas):
                            valor = celulas[cursor]
                            cursor += 1
                        else:
                            valor = None
                        if indice < len(esquema):
                            dn = esquema[indice].get("DN")
                            if dn and isinstance(valor, int):
                                valor = dicionarios.get(dn, {}).get(valor, valor)
                        valores.append(valor)
                    anterior = valores
                    if any(v not in (None, "") for v in valores):
                        saida.append(dict(zip(campos, valores)))
    return saida


def limpar(valor):
    if valor is None:
        return ""
    texto = str(valor).replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(x.rstrip() for x in texto.split("\n")).strip()


def normalizar(valor):
    texto = unicodedata.normalize("NFKD", limpar(valor))
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "", texto.casefold())


def fragmento(valor):
    chave = normalizar(valor)
    return (chave[:PREFIXO] if chave else "00").ljust(PREFIXO, "_")


def gravar_json(path, dados, identado=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(dados, ensure_ascii=False, indent=2 if identado else None,
                   separators=None if identado else (",", ":")),
        encoding="utf-8",
    )


def obter_modelo(pagina):
    html, status = baixar_texto(pagina)
    if status != 200:
        raise RuntimeError(f"Painel não abriu: HTTP {status}")
    descriptor = localizar_json(html, "resourceDescriptor")
    cluster = localizar_json(html, "clusterAssignmentRecord")
    resource_key = descriptor["k"]
    api = api_do_cluster(cluster["FixedClusterUri"])
    base = f"{api}/public/reports/{resource_key}"
    modelos_txt, _ = baixar_texto(
        base + "/modelsAndExploration?preferReadOnlySession=true",
        headers_powerbi(resource_key, pagina),
    )
    modelos = json.loads(modelos_txt)
    if not modelos.get("models"):
        raise RuntimeError("Power BI não informou modelId")
    return resource_key, api, modelos["models"][0]["id"]


def consultar(pagina, resource_key, api, model_id, entidade, campos):
    payload = montar_payload(model_id, entidade, campos)
    corpo = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    conteudo, status = baixar_bytes(
        f"{api}/public/reports/querydata?synchronous=true",
        headers_powerbi(resource_key, pagina, json_post=True),
        corpo,
    )
    if status != 200:
        raise RuntimeError(f"Query Power BI falhou: HTTP {status}")
    return decodificar_linhas(json.loads(conteudo.decode("utf-8", errors="replace")), campos)


def mapear(nome_base, linhas):
    mapa = MAPAS[nome_base]
    registros = []
    for linha in linhas:
        registros.append({destino: limpar(linha.get(origem)) for origem, destino in mapa.items()})
    return registros


def validar(nome_base, registros):
    minimo = {
        "aditivos_alimentares": 1000,
        "coadjuvantes_tecnologia": 100,
        "enzimas_coadjuvantes": 10,
    }[nome_base]
    if len(registros) < minimo:
        raise RuntimeError(f"{nome_base}: apenas {len(registros)} registros; publicação cancelada")
    primario = PRIMARIO[nome_base]
    validos = sum(bool(x.get(primario)) for x in registros)
    if validos < len(registros) * 0.90:
        raise RuntimeError(f"{nome_base}: muitos registros sem {primario}")


def publicar_base(nome_base, registros, gerado_em, extras=None):
    destino = DADOS / nome_base
    primario = PRIMARIO[nome_base]
    grupos = defaultdict(list)
    for item in registros:
        grupos[fragmento(item.get(primario))].append(item)

    tmp = Path(tempfile.mkdtemp(prefix=nome_base + "_", dir=DADOS))
    try:
        for frag, itens in sorted(grupos.items()):
            itens.sort(key=lambda x: (normalizar(x.get(primario)), normalizar(json.dumps(x, ensure_ascii=False))))
            gravar_json(tmp / f"{frag}.json", itens)

        vistos = set()
        catalogo = []
        for item in registros:
            nome = item.get(primario, "")
            chave = normalizar(nome)
            if not chave or chave in vistos:
                continue
            vistos.add(chave)
            entrada = {primario: nome, "fragmento": fragmento(nome)}
            if nome_base == "aditivos_alimentares":
                ins = sorted({x.get("ins", "") for x in registros if normalizar(x.get(primario)) == chave and x.get("ins")})
                entrada["ins"] = ins
            catalogo.append(entrada)
        catalogo.sort(key=lambda x: normalizar(x.get(primario)))
        gravar_json(tmp / "catalogo.json", {"versao_esquema": 1, "gerado_em": gerado_em, "itens": catalogo})

        if extras:
            for nome, conteudo in extras.items():
                gravar_json(tmp / nome, conteudo)

        if destino.exists():
            shutil.rmtree(destino)
        tmp.rename(destino)
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        raise

    maior = max((x.stat().st_size for x in destino.glob("*.json") if x.name != "catalogo.json"), default=0)
    return len(grupos), maior, len(catalogo)


def atualizar_manifesto(resultados, gerado_em):
    manifesto = json.loads(MANIFESTO.read_text(encoding="utf-8")) if MANIFESTO.exists() else {"versao_esquema": 2, "projeto": "Base Vigilância Sanitária", "bases": {}}
    bases = manifesto.setdefault("bases", {})
    manifesto["gerado_em"] = gerado_em
    for nome, meta in resultados.items():
        bases[nome] = meta
    gravar_json(MANIFESTO, manifesto, identado=True)


def main():
    DADOS.mkdir(parents=True, exist_ok=True)
    gerado_em = datetime.now(timezone.utc).isoformat()
    metas = {}

    for nome_base, config in PAINEIS.items():
        print(f"\n=== {nome_base.upper()} ===")
        pagina = config["pagina"]
        resource_key, api, model_id = obter_modelo(pagina)
        conjuntos = {}
        for consulta in config["consultas"]:
            linhas = consultar(
                pagina, resource_key, api, model_id,
                consulta["entidade"], consulta["campos"],
            )
            conjuntos[consulta["saida"]] = linhas
            print(consulta["entidade"], ":", len(linhas), "linhas")

        registros = mapear(nome_base, conjuntos["registros"])
        validar(nome_base, registros)
        extras = {}
        categorias_qtd = None
        if nome_base == "aditivos_alimentares":
            categorias = mapear("categorias_aditivos", conjuntos.get("categorias", []))
            categorias = [x for x in categorias if x.get("categoria") or x.get("nome_categoria")]
            categorias_qtd = len(categorias)
            extras["categorias.json"] = {
                "versao_esquema": 1,
                "gerado_em": gerado_em,
                "itens": categorias,
            }

        fragmentos, maior, itens_catalogo = publicar_base(nome_base, registros, gerado_em, extras)
        primario = PRIMARIO[nome_base]
        unicos = len({normalizar(x.get(primario)) for x in registros if normalizar(x.get(primario))})
        meta = {
            "status": "ok",
            "fonte": pagina,
            "tipo_fonte": "Painel público Power BI da Anvisa",
            "gerado_em": gerado_em,
            "atualizado_em": gerado_em,
            "versao_gerador": VERSAO,
            "registros": len(registros),
            "chave": primario,
            "itens_unicos": unicos,
            "fragmentos": fragmentos,
            "prefixo": PREFIXO,
            "maior_fragmento": maior,
            "catalogo": f"{nome_base}/catalogo.json",
            "itens_catalogo": itens_catalogo,
            "campos": list(MAPAS[nome_base].values()),
        }
        if categorias_qtd is not None:
            meta["categorias"] = categorias_qtd
            meta["arquivo_categorias"] = f"{nome_base}/categorias.json"
        metas[nome_base] = meta
        print(nome_base, ":", len(registros), "registros |", unicos, "itens únicos |", fragmentos, "fragmentos")

    atualizar_manifesto(metas, gerado_em)
    print("\nTrês bases geradas com sucesso.")


if __name__ == "__main__":
    main()
