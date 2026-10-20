#!/usr/bin/env python3
"""Sonda as fontes da Anvisa que deixaram de responder às atualizações agendadas
(out/2026): Cannabis e Alertas Sanitários (consultas.anvisa.gov.br, HTTP 403) e
Produtos irregulares (API de dossiês, "recurso não encontrado"). Só lê e imprime o
status de cada tentativa; não grava nada. Roda no GitHub Actions, de onde rodam as
atualizações (o portal bloqueia por IP outros ambientes)."""
import json, os, urllib.error, urllib.parse, urllib.request

NAV = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0 Safari/537.36",
       "Accept": "application/json, text/plain, */*", "Accept-Language": "pt-BR,pt;q=0.9", "Authorization": "Guest"}


def pede(rotulo, url, headers=None, dados=None, metodo=None):
    try:
        req = urllib.request.Request(url, data=dados, headers=headers or {}, method=metodo)
        with urllib.request.urlopen(req, timeout=60) as r:
            corpo = r.read(400).decode("utf-8", "replace")
            print(f"{rotulo}: HTTP {r.status} | {corpo[:240]!r}")
            return r.status, corpo
    except urllib.error.HTTPError as e:
        corpo = e.read(400).decode("utf-8", "replace")
        print(f"{rotulo}: HTTP {e.code} | {corpo[:240]!r}")
        return e.code, corpo
    except Exception as e:
        print(f"{rotulo}: ERRO {type(e).__name__}: {e}")
        return 0, ""


def consultas():
    for nome, rota, url in [
        ("cannabis", "https://consultas.anvisa.gov.br/#/cannabis/",
         "https://consultas.anvisa.gov.br/api/consulta/cannabis/produtos/?page=1&count=10&filter%5BsituacaoRegistro%5D=V"),
        ("alertas", "https://consultas.anvisa.gov.br/#/alertas-sanitarios/",
         "https://consultas.anvisa.gov.br/api/consulta/alertasSanitarios/listagem?page=1&count=10&column=numeroSeqAlerta&order=asc"),
    ]:
        pede(f"{nome} | identificação atual", url, {"Authorization": "Guest", "Referer": rota, "User-Agent": "base-vigilancia/1.0", "Accept": "application/json"})
        pede(f"{nome} | navegador", url, dict(NAV, Referer=rota))
        pede(f"{nome} | navegador + Origin", url, dict(NAV, Referer=rota, Origin="https://consultas.anvisa.gov.br"))
    pede("portal consultas (página)", "https://consultas.anvisa.gov.br/", {"User-Agent": NAV["User-Agent"]})


def dossies():
    cid, sec = os.environ.get("ANVISA_CLIENT_ID", ""), os.environ.get("ANVISA_CLIENT_SECRET", "")
    gw = "https://api-gateway.prd.apps.anvisa.gov.br/consultas-externas-api"
    for p in ["/v3/api-docs", "/v2/api-docs", "/api-docs", "/swagger-ui/index.html", "/api/v1/v3/api-docs"]:
        st, corpo = pede(f"documentação {p}", gw + p, {"User-Agent": NAV["User-Agent"]})
        if st == 200 and corpo.lstrip().startswith("{"):
            try:
                with urllib.request.urlopen(gw + p, timeout=60) as r:
                    print("caminhos:", sorted(json.loads(r.read()).get("paths", {}))[:80])
            except Exception as e:
                print("caminhos: erro", e)
    pede("documentação pública", "https://api.anvisa.gov.br/consultas-externas/dossie-doc", {"User-Agent": NAV["User-Agent"]})
    if not (cid and sec):
        print("dossiês: sem credenciais (ANVISA_CLIENT_ID/SECRET)")
        return
    corpo = urllib.parse.urlencode({"grant_type": "client_credentials", "client_id": cid, "client_secret": sec}).encode()
    st, tok = pede("token", "https://acesso.prd.apps.anvisa.gov.br/auth/realms/externo/protocol/openid-connect/token", {"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"}, corpo)
    if st != 200:
        return
    try:
        req = urllib.request.Request("https://acesso.prd.apps.anvisa.gov.br/auth/realms/externo/protocol/openid-connect/token", data=corpo, headers={"Content-Type": "application/x-www-form-urlencoded"})
        token = json.loads(urllib.request.urlopen(req, timeout=60).read())["access_token"]
    except Exception as e:
        print("token: erro", e)
        return
    h = {"Authorization": "Bearer " + token, "Content-Type": "application/json", "Accept": "application/json"}
    filtro = json.dumps({"page": 1, "size": 5, "count": 5, "column": "processo", "order": "ASC", "filter": {"tipoAssunto": "2", "tiposProduto": "6,2,15,1,8,12,3"}}).encode()
    for p in ["/api/v1/dossie/", "/api/v1/dossie", "/api/v1/dossies", "/api/v1/dossie/pesquisa", "/api/v1/dossie/consulta", "/api/v2/dossie", "/api/v2/dossie/"]:
        pede(f"POST {p}", gw + p, h, filtro, "POST")
    for p in ["/api/v1/dossie?page=1&size=5", "/api/v1/dossie/1", "/api/v1/tipos-produto", "/api/v1/tipoProduto"]:
        pede(f"GET {p}", gw + p, h)


if __name__ == "__main__":
    print("== consultas.anvisa.gov.br =="); consultas()
    print("== API de dossiês =="); dossies()
