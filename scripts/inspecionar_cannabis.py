from datetime import datetime, timezone
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.parse import urlencode
import gzip
import json
import re
import shutil
import urllib.error
import urllib.request


PORTAL = "https://consultas.anvisa.gov.br/"
API = PORTAL + "api/consulta/cannabis"
ROTA = PORTAL + "#/cannabis/"
PROCESSO_TESTE = "25351117796202112"
SAIDA = Path("diagnostico-cannabis")
VERSAO = "2026-08-31-cannabis-portal-v2"


def seguro(valor):
    return re.sub(r"[^a-z0-9_-]+", "-", valor.casefold()).strip("-")


def gravar_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


class Sessao:
    def __init__(self):
        self.authorization = "Guest"
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(CookieJar())
        )

    def requisitar(self, url, params=None):
        if params:
            url += ("&" if "?" in url else "?") + urlencode(params)
        pedido = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json, text/plain, */*",
                "Accept-Encoding": "gzip",
                "Authorization": self.authorization,
                "Referer": ROTA,
                "User-Agent": "Mozilla/5.0 Chrome/124 Safari/537.36",
            },
        )
        try:
            resposta = self.opener.open(pedido, timeout=180)
        except urllib.error.HTTPError as erro:
            resposta = erro
        corpo = resposta.read()
        if "gzip" in resposta.headers.get("Content-Encoding", "").casefold():
            corpo = gzip.decompress(corpo)
        novo_token = resposta.headers.get("Set-Authorization")
        if novo_token:
            self.authorization = novo_token
        return resposta.status, dict(resposta.headers.items()), corpo


def salvar(nome, url, status, headers, corpo):
    texto = corpo.decode("utf-8", errors="replace")
    base = SAIDA / seguro(nome)
    base.with_suffix(".txt").write_text(texto, encoding="utf-8")
    dados = None
    try:
        dados = json.loads(texto)
        gravar_json(base.with_suffix(".json"), dados)
    except json.JSONDecodeError:
        pass
    resumo = {
        "nome": nome,
        "url": url,
        "status": status,
        "bytes": len(corpo),
        "tipo": headers.get("Content-Type", ""),
        "json": dados is not None,
        "chaves": sorted(dados) if isinstance(dados, dict) else [],
        "previa": texto[:1500],
    }
    gravar_json(base.with_name(base.name + "-resumo.json"), resumo)
    return resumo, dados


def main():
    print("Versão do inspetor:", VERSAO)
    if SAIDA.exists():
        shutil.rmtree(SAIDA)
    SAIDA.mkdir(parents=True)
    sessao = Sessao()
    testes = [
        ("portal", PORTAL, None),
        ("filtro-html", PORTAL + "scripts/app/cannabis/cannabis.filtro.html", None),
        ("resultado-html", PORTAL + "scripts/app/cannabis/cannabis.result.html", None),
        ("detalhe-html", PORTAL + "scripts/app/cannabis/cannabis.detail.html", None),
        ("detalhe-processo", API + "/produtos/" + PROCESSO_TESTE, None),
        ("lista-processo", API + "/produtos/", {
            "page": 1, "count": 10,
            "filter[numeroProcesso]": PROCESSO_TESTE,
        }),
        ("lista-registro", API + "/produtos/", {
            "page": 1, "count": 10,
            "filter[numeroRegistro]": "145590001",
        }),
        ("download-processo", API + "/download", {
            "filter[numeroProcesso]": PROCESSO_TESTE,
        }),
    ]
    resumos = []
    sucessos = []
    for nome, url, params in testes:
        print("GET", url, params or "")
        status, headers, corpo = sessao.requisitar(url, params)
        resumo, dados = salvar(nome, url, status, headers, corpo)
        resumos.append(resumo)
        if status == 200 and dados is not None:
            sucessos.append(nome)
    gravar_json(SAIDA / "respostas-resumo.json", resumos)
    gravar_json(SAIDA / "execucao.json", {
        "versao": VERSAO,
        "executado_em": datetime.now(timezone.utc).isoformat(),
        "api": API,
        "processo_teste": PROCESSO_TESTE,
        "respostas_json": sucessos,
        "set_authorization_recebido": sessao.authorization != "Guest",
    })
    (SAIDA / "RESUMO.md").write_text(
        "# Diagnóstico Cannabis\n\n"
        f"- Versão: `{VERSAO}`\n"
        f"- API testada: `{API}`\n"
        f"- Respostas JSON: **{len(sucessos)}** ({', '.join(sucessos) or 'nenhuma'})\n",
        encoding="utf-8",
    )
    print("Respostas JSON:", sucessos)
    if "detalhe-processo" not in sucessos and "lista-processo" not in sucessos:
        raise RuntimeError("A API Cannabis não devolveu JSON; baixe o artifact.")


if __name__ == "__main__":
    main()
