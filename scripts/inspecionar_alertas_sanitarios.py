from datetime import date, datetime, timezone
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
API = PORTAL + "api/consulta/alertasSanitarios"
ROTA = PORTAL + "#/alertas-sanitarios/"
SAIDA = Path("diagnostico-alertas-sanitarios")
VERSAO = "2026-08-31-alertas-v1"


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
        pedido = urllib.request.Request(url, headers={
            "Accept": "application/json, text/plain, text/html, */*",
            "Accept-Encoding": "gzip",
            "Authorization": self.authorization,
            "Referer": ROTA,
            "User-Agent": "Mozilla/5.0 Chrome/124 Safari/537.36",
        })
        try:
            resposta = self.opener.open(pedido, timeout=180)
        except urllib.error.HTTPError as erro:
            resposta = erro
        corpo = resposta.read()
        if "gzip" in resposta.headers.get("Content-Encoding", "").casefold():
            corpo = gzip.decompress(corpo)
        token = resposta.headers.get("Set-Authorization")
        if token:
            self.authorization = token
        return resposta.status, dict(resposta.headers.items()), corpo, url


def salvar(nome, status, headers, corpo, url):
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
        "nome": nome, "url": url, "status": status,
        "bytes": len(corpo), "tipo": headers.get("Content-Type", ""),
        "json": dados is not None,
        "chaves": sorted(dados) if isinstance(dados, dict) else [],
        "previa": texto[:3000],
    }
    gravar_json(base.with_name(base.name + "-resumo.json"), resumo)
    return resumo, dados


def main():
    print("Versão do inspetor:", VERSAO)
    if SAIDA.exists():
        shutil.rmtree(SAIDA)
    SAIDA.mkdir(parents=True)
    sessao = Sessao()
    resumos = []

    testes = [
        ("portal", PORTAL, None),
        ("filtro-html", PORTAL + "scripts/app/alertasSanitarios/alertasSanitarios.filtro.html", None),
        ("resultado-html", PORTAL + "scripts/app/alertasSanitarios/alertasSanitarios.result.html", None),
        ("detalhe-html", PORTAL + "scripts/app/alertasSanitarios/alertasSanitarios.detail.html", None),
    ]
    for nome, url, params in testes:
        print("GET", url)
        resumo, _ = salvar(nome, *sessao.requisitar(url, params))
        resumos.append(resumo)

    filtros = {
        "page": 1,
        "count": 20,
        "column": "numeroSeqAlerta",
        "direction": "desc",
        "filter[dataInicial]": "2000-01-01T00:00:00.000Z",
        "filter[dataFinal]": date.today().isoformat() + "T23:59:59.999Z",
    }
    print("GET", API + "/listagem")
    resultado = sessao.requisitar(API + "/listagem", filtros)
    resumo, listagem = salvar("listagem-periodo", *resultado)
    resumos.append(resumo)

    alertas = (listagem or {}).get("content") or []
    if alertas:
        primeiro = alertas[0]
        id_alerta = (
            primeiro.get("idAlerta") or primeiro.get("codSeqAlerta")
            or primeiro.get("codigo") or primeiro.get("id")
        )
        gravar_json(SAIDA / "primeiro-alerta-listagem.json", primeiro)
        if id_alerta is not None:
            url = API + "/detalhes/" + str(id_alerta)
            print("GET", url)
            resumo, _ = salvar("detalhe-primeiro-alerta", *sessao.requisitar(url))
            resumos.append(resumo)

    gravar_json(SAIDA / "respostas-resumo.json", resumos)
    gravar_json(SAIDA / "execucao.json", {
        "versao": VERSAO,
        "executado_em": datetime.now(timezone.utc).isoformat(),
        "total_informado": (listagem or {}).get("totalElements"),
        "itens_na_amostra": len(alertas),
        "campos_listagem": sorted(alertas[0]) if alertas else [],
    })
    (SAIDA / "RESUMO.md").write_text(
        "# Diagnóstico de Alertas Sanitários\n\n"
        f"- Total informado: **{(listagem or {}).get('totalElements', 0)}**\n"
        f"- Itens na amostra: **{len(alertas)}**\n",
        encoding="utf-8",
    )
    if not alertas:
        raise RuntimeError("A API não devolveu alertas; baixe o artifact.")
    print("Total informado:", listagem.get("totalElements"))
    print("Diagnóstico concluído.")


if __name__ == "__main__":
    main()
