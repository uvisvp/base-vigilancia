"""Produtos não regularizados como dispositivos médicos (lista da Anvisa).

A Anvisa publica, na página de regularização de produtos para saúde, a lista de
produtos que não são regularizados como dispositivos médicos (não exigem
notificação nem registro), organizada em categorias numeradas:

    www.gov.br/anvisa/pt-br/setorregulado/regularizacao/produtos-para-saude/
    produtos-nao-regulados

Muitos itens trazem exceção ("exceto indicado para diagnóstico clínico (IVD)"):
a exceção faz parte do texto e é mantida literal, porque é ela que decide se o
produto precisa ou não de regularização.

Grava dados/produtos_nao_regulados/lista.json e a entrada no manifesto.
Uso: python scripts/gerar_produtos_nao_regulados.py
(PRODUTOS_NAO_REGULADOS_HTML=arquivo.html usa um HTML já baixado.)
"""
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
import json
import os
import re
import urllib.request

BASE = Path(__file__).resolve().parent.parent
DADOS = BASE / "dados"
DESTINO = DADOS / "produtos_nao_regulados"
FONTE = ("https://www.gov.br/anvisa/pt-br/setorregulado/regularizacao/"
         "produtos-para-saude/produtos-nao-regulados")
VERSAO = "2026-10-22-produtos-nao-regulados-v1"
LIMITE_QUEDA = 0.90


class Texto(HTMLParser):
    """Texto do conteúdo principal, uma linha por bloco (p, li, título, linha de tabela)."""
    BLOCOS = {"p", "li", "h1", "h2", "h3", "h4", "h5", "tr", "div", "br"}

    def __init__(self):
        super().__init__()
        self.linhas, self.atual, self.pula = [], [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.pula += 1
        elif tag in self.BLOCOS:
            self.quebra()

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.pula -= 1
        elif tag in self.BLOCOS:
            self.quebra()

    def handle_data(self, data):
        if not self.pula:
            self.atual.append(data)

    def quebra(self):
        linha = re.sub(r"\s+", " ", "".join(self.atual)).strip()
        if linha:
            self.linhas.append(linha)
        self.atual = []


def baixar():
    caminho = os.environ.get("PRODUTOS_NAO_REGULADOS_HTML", "").strip()
    if caminho:
        return Path(caminho).read_text(encoding="utf-8", errors="replace")
    pedido = urllib.request.Request(FONTE, headers={"User-Agent": "Mozilla/5.0 (base-vigilancia)"})
    with urllib.request.urlopen(pedido, timeout=120) as resposta:
        return resposta.read().decode("utf-8", errors="replace")


def extrair(html):
    inicio = html.find('id="content-core"')
    if inicio < 0:
        inicio = html.find("documentFirstHeading")
    fim = html.find("Links de compartilhamento", inicio)
    trecho = html[inicio:fim if fim > 0 else None]
    p = Texto()
    p.feed(trecho)
    p.quebra()
    atualizado = ""
    for linha in p.linhas[:6]:
        m = re.search(r"Atualizado em (\d{2}/\d{2}/\d{4})", linha)
        if m:
            atualizado = m.group(1)
    categorias, cat, item = [], None, None
    for linha in p.linhas:
        m = re.match(r"^CATEGORIA\s+(\d+)\s*[:\-–]\s*(.+)$", linha, re.I)
        if m:
            cat = {"numero": int(m.group(1)), "titulo": m.group(2).strip().rstrip("."), "itens": []}
            categorias.append(cat)
            item = None
            continue
        if not cat:
            continue
        m = re.match(r"^(\d+)\.\s*(.+)$", linha)
        if m:
            item = {"n": int(m.group(1)), "texto": m.group(2).strip()}
            cat["itens"].append(item)
            continue
        m = re.match(r"^([a-z])\.\s*(.+)$", linha)
        if m and item:
            item.setdefault("sub", []).append(m.group(2).strip())
            continue
        if item is None and not cat["itens"]:
            cat.setdefault("nota", []).append(linha)
    return atualizado, categorias


def main():
    print("Versão do gerador:", VERSAO)
    atualizado, categorias = extrair(baixar())
    total = sum(len(c["itens"]) for c in categorias)
    print("Categorias:", len(categorias), "| itens:", total, "| atualizado na fonte:", atualizado or "?")
    if len(categorias) < 5 or total < 100:
        raise RuntimeError("Página sem a lista esperada (categorias numeradas). Publicação cancelada.")
    arquivo = DESTINO / "lista.json"
    if arquivo.exists():
        anterior = json.loads(arquivo.read_text(encoding="utf-8")).get("total", 0)
        if anterior and total < anterior * LIMITE_QUEDA:
            raise RuntimeError(f"A lista caiu de {anterior} para {total} itens. Publicação cancelada.")
    gerado_em = datetime.now(timezone.utc).isoformat()
    DESTINO.mkdir(parents=True, exist_ok=True)
    dados = {
        "fonte": FONTE,
        "titulo": "Produtos não regularizados como dispositivos médicos",
        "atualizado_na_fonte": atualizado,
        "gerado_em": gerado_em,
        "total": total,
        "categorias": categorias,
    }
    arquivo.write_text(json.dumps(dados, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    manifesto_path = DADOS / "manifest.json"
    bruto = manifesto_path.read_text(encoding="utf-8")
    manifesto = json.loads(bruto)
    manifesto.setdefault("bases", {})["produtos_nao_regulados"] = {
        "status": "ok",
        "fonte": FONTE,
        "tipo_fonte": "Página da Anvisa (gov.br)",
        "gerado_em": gerado_em,
        "atualizado_na_fonte": atualizado,
        "versao_gerador": VERSAO,
        "registros": total,
        "categorias": len(categorias),
        "arquivo": "produtos_nao_regulados/lista.json",
        "observacao": "Produtos que não exigem notificação ou registro como dispositivo médico; as exceções de cada item ficam no texto.",
    }
    # mantém o formato em que o manifesto já está (compacto ou com recuo)
    recuo = 2 if bruto.lstrip().startswith("{\n") else None
    texto = json.dumps(manifesto, ensure_ascii=False, indent=recuo, separators=None if recuo else (",", ":"))
    manifesto_path.write_text(texto + ("\n" if bruto.endswith("\n") else ""), encoding="utf-8")
    print("Gravado:", arquivo)


if __name__ == "__main__":
    main()
