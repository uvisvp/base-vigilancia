from pathlib import Path
from urllib.parse import urlparse, urlunparse
import gzip
import json
import re
import urllib.request
import uuid

PAINEIS = {
    "aditivos_alimentares": "https://app.powerbi.com/view?r=eyJrIjoiZmQ2ZDBjNTItMDFmMi00MmM5LWE4Y2QtMzBhOGZlYTU4OGUzIiwidCI6ImI2N2FmMjNmLWMzZjMtNGQzNS04MGM3LWI3MDg1ZjVlZGQ4MSJ9&pageName=ReportSection08a3239a66872bb5b7a9",
    "coadjuvantes_tecnologia": "https://app.powerbi.com/view?r=eyJrIjoiOWViN2VjMWItNWRkYy00ZGNkLTg0M2UtY2Y0Nzg3NzlhMTY1IiwidCI6ImI2N2FmMjNmLWMzZjMtNGQzNS04MGM3LWI3MDg1ZjVlZGQ4MSJ9&pageName=ReportSection08a3239a66872bb5b7a9",
    "enzimas_coadjuvantes": "https://app.powerbi.com/view?r=eyJrIjoiZmMzYTQxYmItMWVkNi00MzczLThjODAtOWI5ODdiMjZjNzQ0IiwidCI6ImI2N2FmMjNmLWMzZjMtNGQzNS04MGM3LWI3MDg1ZjVlZGQ4MSJ9&pageName=ReportSection",
}

SAIDA = Path(__file__).resolve().parent.parent / "dados" / "diagnostico_aditivos_powerbi.json"


def baixar(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {"User-Agent": "Mozilla/5.0 base-vigilancia"})
    with urllib.request.urlopen(req, timeout=180) as resp:
        corpo = resp.read()
        if "gzip" in resp.headers.get("Content-Encoding", "").lower():
            corpo = gzip.decompress(corpo)
        return corpo.decode("utf-8", errors="replace")


def localizar_json(html, nome):
    prefixo = rf"var\s+{re.escape(nome)}\s*=\s*"
    m = re.search(prefixo + r"JSON\.parse\('((?:\\.|[^'])*)'\)", html, re.DOTALL)
    if m:
        bruto = m.group(1)
        dec = json.loads('"' + bruto.replace('"', '\\"').replace('\\"', '\"') + '"')
        return json.loads(dec)
    m = re.search(prefixo, html, re.DOTALL)
    if m:
        restante = html[m.end():].lstrip()
        return json.JSONDecoder().raw_decode(restante)[0]
    raise RuntimeError(f"Variável {nome} não localizada")


def api_do_cluster(uri):
    p = urlparse(uri)
    partes = (p.hostname or "").split(".")
    primeiro = partes[0].replace("-redirect", "").replace("global-", "")
    partes[0] = primeiro + "-api"
    return urlunparse((p.scheme or "https", ".".join(partes), "", "", "", "")).rstrip("/")


def headers(resource_key, pagina):
    return {
        "Accept": "application/json",
        "ActivityId": str(uuid.uuid4()),
        "RequestId": str(uuid.uuid4()),
        "X-PowerBI-ResourceKey": resource_key,
        "Origin": "https://app.powerbi.com",
        "Referer": pagina,
        "User-Agent": "Mozilla/5.0 base-vigilancia",
    }


def extrair_entidades(obj):
    encontrados = []
    vistos = set()

    def andar(x, caminho=""):
        if isinstance(x, dict):
            nome = x.get("name") or x.get("Name")
            props = x.get("properties") or x.get("Properties")
            if nome and isinstance(props, (list, dict)):
                campos = []
                seq = props.values() if isinstance(props, dict) else props
                for p in seq:
                    if isinstance(p, dict):
                        pn = p.get("name") or p.get("Name")
                        if pn:
                            campos.append(str(pn))
                    elif isinstance(p, str):
                        campos.append(p)
                chave = (str(nome), tuple(campos))
                if campos and chave not in vistos:
                    vistos.add(chave)
                    encontrados.append({"entidade": str(nome), "campos": campos, "caminho": caminho})
            for k, v in x.items():
                andar(v, f"{caminho}/{k}")
        elif isinstance(x, list):
            for i, v in enumerate(x):
                andar(v, f"{caminho}/{i}")
        elif isinstance(x, str) and len(x) > 2 and x[:1] in "[{":
            try:
                andar(json.loads(x), caminho + "/json")
            except Exception:
                pass

    andar(obj)
    return encontrados


def diagnosticar(nome, pagina):
    html = baixar(pagina)
    descriptor = localizar_json(html, "resourceDescriptor")
    cluster = localizar_json(html, "clusterAssignmentRecord")
    resource_key = descriptor["k"]
    api = api_do_cluster(cluster["FixedClusterUri"])
    base = f"{api}/public/reports/{resource_key}"
    modelos = json.loads(baixar(base + "/modelsAndExploration?preferReadOnlySession=true", headers(resource_key, pagina)))
    schema = json.loads(baixar(base + "/conceptualschema", headers(resource_key, pagina)))
    entidades = extrair_entidades(schema)
    return {
        "painel": nome,
        "fonte": pagina,
        "resource_key": resource_key,
        "api": api,
        "modelos": [{"id": m.get("id"), "dbName": m.get("dbName")} for m in modelos.get("models", [])],
        "chaves_schema": list(schema.keys()) if isinstance(schema, dict) else [],
        "entidades": entidades,
    }


def main():
    saida = {"paineis": {}}
    for nome, pagina in PAINEIS.items():
        print("Diagnosticando", nome)
        try:
            saida["paineis"][nome] = diagnosticar(nome, pagina)
            print("OK", nome, "| entidades", len(saida["paineis"][nome]["entidades"]))
        except Exception as e:
            saida["paineis"][nome] = {"painel": nome, "fonte": pagina, "erro": repr(e)}
            print("ERRO", nome, repr(e))
    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    SAIDA.write_text(json.dumps(saida, ensure_ascii=False, indent=2), encoding="utf-8")
    if not any(v.get("entidades") for v in saida["paineis"].values() if isinstance(v, dict)):
        raise RuntimeError("Nenhuma estrutura Power BI pôde ser identificada.")


if __name__ == "__main__":
    main()
