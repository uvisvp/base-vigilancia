from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict
from urllib.parse import urlencode
import json
import re
import time
import urllib.error
import urllib.request

BASE = Path(__file__).resolve().parent.parent
DADOS = BASE / "dados"
PASTA = DADOS / "afe_ae"
API = "https://consultas.anvisa.gov.br/api/empresa/funcionamento"
PREFIXO = 3
COUNT = 500

def digitos(v):
    return re.sub(r"\D", "", str(v or ""))

def txt(v):
    return re.sub(r"\s+", " ", str(v or "").strip())

def get_json(url, tentativas=5):
    ultimo = None
    for n in range(1, tentativas + 1):
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 base-vigilancia",
            "Authorization": "Guest",
            "Accept": "application/json",
        })
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.loads(r.read().decode("utf-8", errors="replace"))
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, json.JSONDecodeError) as e:
            ultimo = e
            if n < tentativas:
                time.sleep(3 * n)
    raise RuntimeError(f"Falha consultando {url}: {ultimo!r}")

def primeiro(d, nomes):
    for nome in nomes:
        if nome in d and d[nome] not in (None, ""):
            return d[nome]
    return None

def normalizar_api(x):
    processo = digitos(primeiro(x, ["numeroProcesso","processo","nuProcesso","numero_processo"]))
    autorizacao = txt(primeiro(x, ["numeroAutorizacao","autorizacao","nuAutorizacao","numero_autorizacao"]))
    cnpj = digitos(primeiro(x, ["cnpj","nuCnpj","numeroCnpj"]))
    out = {}
    if processo: out["processo"] = processo
    if autorizacao: out["autorizacao"] = autorizacao
    if len(cnpj) == 14: out["cnpj"] = cnpj

    mapa = {
        "tipo": ["tipoAutorizacao","tipo","tipoAFEAE","descricaoTipoAutorizacao"],
        "situacao": ["situacao","situacaoAutorizacao","status","descricaoSituacao"],
        "data_publicacao": ["dataPublicacao","dtPublicacao","dataResolucao"],
        "resolucao": ["resolucao","numeroResolucao","atoPublicacao"],
        "classe": ["classe","classeProduto","descricaoClasse"],
        "atividade": ["atividade","atividades","atividadeAutorizada","descricaoAtividade"],
        "razao_social": ["razaoSocial","nomeRazaoSocial"],
        "nome_fantasia": ["nomeFantasia"],
        "municipio": ["municipio","cidade"],
        "uf": ["uf","siglaUf"],
    }
    for destino, nomes in mapa.items():
        v = primeiro(x, nomes)
        if v not in (None, ""):
            if isinstance(v, (dict, list)):
                out[destino] = v
            else:
                out[destino] = txt(v)
    return out

def chave(item):
    return (digitos(item.get("processo")), digitos(item.get("autorizacao")), digitos(item.get("cnpj")))

def carregar_local():
    registros = {}
    por_processo = defaultdict(list)
    por_autorizacao = defaultdict(list)
    por_cnpj = defaultdict(list)
    for arq in sorted(PASTA.glob("*.json")):
        itens = json.loads(arq.read_text(encoding="utf-8"))
        for item in itens:
            k = chave(item)
            registros[k] = item
            if k[0]: por_processo[k[0]].append(k)
            if k[1]: por_autorizacao[k[1]].append(k)
            if k[2]: por_cnpj[k[2]].append(k)
    return registros, por_processo, por_autorizacao, por_cnpj

def aplicar(registros, indices, api_item):
    norm = normalizar_api(api_item)
    candidatos = []
    p, a, c = digitos(norm.get("processo")), digitos(norm.get("autorizacao")), digitos(norm.get("cnpj"))
    if p: candidatos += indices[0].get(p, [])
    if not candidatos and a: candidatos += indices[1].get(a, [])
    if not candidatos and c: candidatos += indices[2].get(c, [])
    vistos = set()
    alterados = 0
    for k in candidatos:
        if k in vistos: continue
        vistos.add(k)
        item = registros[k]
        # Cruzamento forte: processo; na falta dele, autorização. CNPJ isolado só
        # é aceito se houver uma única autorização local para o CNPJ.
        if p and digitos(item.get("processo")) != p: continue
        if not p and a and digitos(item.get("autorizacao")) != a: continue
        if not p and not a and c and len(indices[2].get(c, [])) != 1: continue
        for campo, valor in norm.items():
            if campo in ("processo","autorizacao","cnpj"): continue
            if valor not in (None, "", [], {}):
                item[campo] = valor
        item["fonte_enriquecimento"] = API
        alterados += 1
    return alterados

def main():
    registros, pp, pa, pc = carregar_local()
    if not registros:
        raise RuntimeError("Base afe_ae local ausente.")
    pagina = 0
    total_paginas = None
    alterados = 0
    chaves_api = set()
    while total_paginas is None or pagina < total_paginas:
        qs = urlencode({"count": COUNT, "page": pagina})
        data = get_json(API + "?" + qs)
        conteudo = data.get("content")
        if not isinstance(conteudo, list):
            raise RuntimeError("API de funcionamento sem content.")
        if total_paginas is None:
            total_paginas = int(data.get("totalPages") or 1)
            print("Páginas API:", total_paginas)
        for x in conteudo:
            chaves_api.update(x.keys())
            alterados += aplicar(registros, (pp, pa, pc), x)
        pagina += 1
        if pagina % 50 == 0:
            print("Página", pagina, "/", total_paginas, "| vínculos", alterados)
        time.sleep(0.03)

    grupos = defaultdict(list)
    for item in registros.values():
        cnpj = digitos(item.get("cnpj"))
        if len(cnpj) == 14:
            grupos[cnpj[:PREFIXO]].append(item)
    for prefixo, itens in grupos.items():
        (PASTA / f"{prefixo}.json").write_text(
            json.dumps(itens, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8"
        )

    agora = datetime.now(timezone.utc).isoformat()
    schema = {
        "versao": 1,
        "gerado_em": agora,
        "fonte_primaria": "https://dados.anvisa.gov.br/dados/CONSULTAS/EMPRESA_FISCALIZACAO_PRODUTO/TA_CONSULTA_FUNCIONAMENTO_EMPRESA_NACIONAL.CSV",
        "fonte_enriquecimento": API,
        "campos_api_observados": sorted(chaves_api),
        "registros_locais": len(registros),
        "vinculos_enriquecidos": alterados,
        "regra": "Nenhum tipo AFE/AE, situação ou publicação é inferido pelo formato do número. Só é gravado quando devolvido pela fonte oficial.",
    }
    (DADOS / "afe_ae_schema.json").write_text(
        json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    manifest_path = DADOS / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    b = manifest.setdefault("bases", {}).setdefault("afe_ae", {})
    b["fonte_enriquecimento"] = API
    b["enriquecimento_gerado_em"] = agora
    b["vinculos_enriquecidos"] = alterados
    b["schema"] = "afe_ae_schema.json"
    b["campos_enriquecimento"] = ["tipo","situacao","data_publicacao","resolucao","classe","atividade"]
    b["regra_enriquecimento"] = "Sem inferência: somente dados retornados pela fonte oficial."
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print("AFE/AE enriquecida:", alterados, "vínculos.")

if __name__ == "__main__":
    main()
