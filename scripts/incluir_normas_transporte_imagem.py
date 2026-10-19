#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Inclui no banco hierárquico (legislacao_v12) as normas dos roteiros novos do app
Roteiros (pedido de 19/10/2026):

Transporte de material biológico humano (transportadora):
  - RDC 504/2021 (boas práticas para o transporte de material biológico humano);
  - RDC 34/2014 (boas práticas no ciclo do sangue; vigente com alterações — seção
    de transporte de hemocomponentes);
  - RDC 707/2022 (boas práticas em tecidos humanos para uso terapêutico; inclui o
    transporte de tecidos);
  - Resolução ANTT 5.998/2022 (texto da Resolução, consolidado com as Resoluções
    6.016/2023 e 6.056/2024; as Instruções Complementares ficam como fonte citada);
  - Portaria SMS 266/2025 (licenciamento sanitário no Município de São Paulo;
    art. 22 — veículos como extensão do estabelecimento).
Serviços de diagnóstico por imagem:
  - RDC 611/2022 (radiologia diagnóstica ou intervencionista);
  - IN 90/2021 (radiografia médica convencional), IN 91/2021 (fluoroscopia e
    radiologia intervencionista — hemodinâmica), IN 92/2021 (mamografia), IN 93/2021
    (tomografia computadorizada), IN 96/2021 (ultrassom), IN 97/2021 (ressonância
    magnética);
  - RDC 36/2013 (segurança do paciente em serviços de saúde).

Texto oficial do AnvisaLegis (consolidado; as “redações anteriores” ficam só como
link na página e não entram), do ANTTlegis, do Catálogo de Legislação Municipal e,
para a RDC 707/2022, do PDF do DOU arquivado pela SES-SP (o AnvisaLegis não abriu o
ato). Estruturação pelo motor v12 (estruturar_legislacao.estruturar_texto), com
desambiguação de IDs repetidos como em atualizar_legislacao_rdc_670_1039.py.
Não reprocessa as demais normas do banco.
Uso: python scripts/incluir_normas_transporte_imagem.py [norma ...]"""
from __future__ import annotations

import csv
import io
import json
import re
import sys
from pathlib import Path

from bs4 import BeautifulSoup
from pypdf import PdfReader

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE / "scripts"))
from estruturar_legislacao import estruturar_texto, slug  # noqa: E402
from atualizar_legislacao_rdc_670_1039 import agora, baixar, limpar_linhas, sha_b, sha_t  # noqa: E402

FONTES = BASE / "fontes"
TEXTOS = BASE / "textos"
CATALOGO = FONTES / "normas.csv"
SAIDA = BASE / "dados" / "legislacao_v12"


def anvisalegis(tipo, num, ano, orgao):
    from urllib.parse import quote
    return ("https://anvisalegis.datalegis.net/action/ActionDatalegis.php?acao=abrirTextoAto&link=S"
            f"&tipo={tipo}&numeroAto={int(num):08d}&seqAto=000&valorAno={ano}&orgao={quote(orgao, safe='')}"
            "&cod_modulo=310&cod_menu=9431")


def rdc(num, ano, data, obrig, status="vigente", min_chars=3000, nota="Texto oficial/consolidado obtido diretamente do AnvisaLegis.", rot=None):
    u = anvisalegis("RDC", num, ano, "RDC/DC/ANVISA/MS")
    return {"norma_id": f"rdc-anvisa-{num}-{ano}", "norma": f"RDC {num}-{ano}", "grupo": "rdc-anvisa",
            "rotulo": rot or f"RDC Anvisa nº {num}/{ano}", "url": u, "fonte_normativa_oficial": u, "fonte_status": u,
            "nota_fonte_texto": nota, "data_fonte": data, "status_vigencia": status, "status_fonte": "AnvisaLegis",
            "min_chars": min_chars, "obrig": obrig}


def inm(num, ano, data, assunto):
    u = anvisalegis("INM", num, ano, "DC/ANVISA/MS")
    return {"norma_id": f"in-anvisa-{num}-{ano}", "norma": f"IN {num}-{ano}", "grupo": "in-anvisa",
            "rotulo": f"IN Anvisa nº {num}/{ano}", "url": u, "fonte_normativa_oficial": u, "fonte_status": u,
            "nota_fonte_texto": f"Texto oficial obtido diretamente do AnvisaLegis ({assunto}).", "data_fonte": data,
            "status_vigencia": "vigente", "status_fonte": "AnvisaLegis", "min_chars": 3000,
            "obrig": ["Instrução Normativa", "Art. 1", "Art. 2"]}


ANTT = ("https://anttlegis.datalegis.inf.br/action/UrlPublicasAction.php?acao=abrirAtoPublico&num_ato=00005998"
        "&sgl_tipo=RES&sgl_orgao=DG/ANTT/MI&vlr_ano=2022&seq_ato=000")
SMS266 = "https://legislacao.prefeitura.sp.gov.br/portaria-secretaria-municipal-da-saude-sms-266-de-6-de-maio-de-2025"
R707_DOU = "https://ses.sp.bvs.br/wp-content/uploads/2022/07/U_RS-MS-ANVISA-RDC-707_010722.pdf"

NORMAS = [
    # ---- transporte de material biológico humano
    rdc(504, 2021, "2021-05-27", ["504", "Art. 1", "Art. 23", "Art. 34", "Art. 42"]),
    rdc(34, 2014, "2014-06-11", ["34", "Art. 1", "transporte"], status="vigente_com_alteracoes", min_chars=50000),
    dict(rdc(707, 2022, "2022-07-01", ["707", "Art. 1", "transporte"], min_chars=20000,
             nota="Texto do DOU (Seção 1, 06/07/2022) arquivado pela SES-SP; o AnvisaLegis não abriu o ato na data da inclusão."),
         url=R707_DOU, fonte_status=anvisalegis("RDC", 707, 2022, "RDC/DC/ANVISA/MS"), status_fonte="DOU (cópia SES-SP)"),
    {"norma_id": "resolucao-antt-5998-2022", "norma": "Resolucao ANTT 5998-2022", "grupo": "antt",
     "rotulo": "Resolução ANTT nº 5.998/2022", "url": ANTT, "fonte_normativa_oficial": ANTT, "fonte_status": ANTT,
     "nota_fonte_texto": "Texto da Resolução no ANTTlegis, consolidado com as Resoluções ANTT 6.016/2023 e 6.056/2024. "
                         "As Instruções Complementares (Partes 1 a 7, Relação de Produtos Perigosos) não são transcritas: "
                         "são publicadas como anexos em PDF no próprio ANTTlegis.",
     "data_fonte": "2022-11-03", "status_vigencia": "vigente_com_alteracoes", "status_fonte": "ANTTlegis",
     "min_chars": 20000, "obrig": ["5.998", "Art. 1", "Art. 46", "Art. 48"]},
    {"norma_id": "portaria-sms-sp-266-2025", "norma": "Portaria SMS SP 266-2025", "grupo": "municipal-sp",
     "rotulo": "Portaria SMS nº 266/2025", "url": SMS266, "fonte_normativa_oficial": SMS266, "fonte_status": SMS266,
     "nota_fonte_texto": "Texto do Catálogo de Legislação Municipal (legislacao.prefeitura.sp.gov.br). Os anexos (lista de "
                         "CNAE, formulários e documentos) são publicados à parte no site da Covisa.",
     "data_fonte": "2025-05-06", "status_vigencia": "vigente", "status_fonte": "Catálogo de Legislação Municipal",
     "min_chars": 15000, "obrig": ["266", "Art. 1", "Art. 22", "veículos"]},
    # ---- diagnóstico por imagem
    rdc(611, 2022, "2022-03-09", ["611", "Art. 1", "Art. 3", "Art. 85"]),
    inm(90, 2021, "2021-05-27", "radiografia médica convencional"),
    inm(91, 2021, "2021-05-27", "fluoroscopia e radiologia intervencionista"),
    inm(92, 2021, "2021-05-27", "mamografia"),
    inm(93, 2021, "2021-05-27", "tomografia computadorizada médica"),
    inm(96, 2021, "2021-05-27", "ultrassom diagnóstico ou terapêutico"),
    inm(97, 2021, "2021-05-27", "ressonância magnética nuclear"),
    rdc(36, 2013, "2013-07-25", ["36", "Art. 1", "Art. 8"]),
]

BLOCOS = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "table", "blockquote", "center"}
RUIDO_PDF = re.compile(r"^(Este documento pode ser verificado|Documento assinado digitalmente|ISSN 1677-7042|Nº \d+, (segunda|terça|quarta|quinta|sexta)-feira|DIÁRIO OFICIAL DA UNIÃO|Publicado em: |Edição: |Seção: |Página: |Órgão: )", re.I)
RUIDO = {"Redações Anteriores", "Série Histórica", "Veja Também", "Voltar ao Topo", "Carregando...", "Carregando…"}


def extrair(r):
    """HTML: um parágrafo por linha, com links e ênfases inline unidos ao texto."""
    ctype = (r.headers.get("content-type") or "").lower()
    if r.url.lower().endswith(".pdf") or "application/pdf" in ctype or r.content[:4] == b"%PDF":
        try:  # pymupdf separa melhor as palavras do PDF do DOU (pypdf parte "tec idos")
            import pymupdf
            doc = pymupdf.open(stream=r.content, filetype="pdf")
            bruto = "\n".join(p.get_text() for p in doc)
        except ImportError:
            bruto = "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(r.content)).pages)
        bruto = "\n".join(l for l in bruto.split("\n") if not RUIDO_PDF.match(l.strip()))
        return limpar_linhas(bruto), "pdf"
    soup = BeautifulSoup(r.content, "html.parser")
    for x in soup(["script", "style", "noscript", "nav", "footer", "header"]):
        x.decompose()
    for el in soup.find_all(BLOCOS):
        el.insert_before("\n")
        el.insert_after("\n")
    linhas = [ln for ln in (re.sub(r"\s+", " ", x).strip() for x in soup.get_text("").split("\n"))
              if ln and ln not in RUIDO]
    return limpar_linhas("\n".join(linhas)), "html"


def recorta(n, txt):
    """Remove o cabeçalho de navegação dos portais (antes do título do ato)."""
    marcas = {
        "rdc-anvisa": r"^Resolu[çc][ãa]o da Diretoria Colegiada - RDC",
        "in-anvisa": r"^Instru[çc][ãa]o Normativa - IN",
        "antt": r"^RESOLUÇÃO Nº 5\.998",
        "municipal-sp": r"^PORTARIA SECRETARIA MUNICIPAL DA SAÚDE",
    }
    rx = marcas.get(n["grupo"])
    if rx and n["status_fonte"] != "DOU (cópia SES-SP)":
        ls = txt.split("\n")
        i = next((k for k, l in enumerate(ls) if re.match(rx, l, re.I)), None)
        if i is not None:
            txt = "\n".join(ls[i:])
    # quebra de linha do PDF no meio de citação (“... o disposto no\nart. 10 da Lei ...”):
    # “art.” minúsculo no início de linha continua a linha anterior, não abre artigo
    txt = re.sub(r"\n(?=art\.\s*\d)", " ", txt)
    # rodapé do ANTTlegis: a lista de anexos não é texto da Resolução
    if n["grupo"] == "antt":
        txt = re.split(r"\nANEXOS\n", txt)[0]
    return txt


class _Local:
    """Resposta a partir da cópia já arquivada em fontes/<norma_id>/ (quando a fonte cai)."""
    def __init__(self, caminho, url):
        self.content = caminho.read_bytes(); self.url = url; self.headers = {"content-type": "application/pdf"}


def obter(n):
    try:
        return baixar(n["url"])
    except Exception:
        arq = FONTES / n["norma_id"] / "texto_bruto.pdf"
        if n["url"].lower().endswith(".pdf") and arq.exists():
            print("  fonte indisponível; usando a cópia arquivada", arq.relative_to(BASE), flush=True)
            return _Local(arq, n["url"])
        raise


def validar(n, txt):
    if len(txt) < n["min_chars"]:
        raise RuntimeError(f"{n['norma']}: texto curto ({len(txt)})")
    falta = [x for x in n["obrig"] if x.casefold() not in txt.casefold()]
    if falta:
        raise RuntimeError(f"{n['norma']}: faltam marcadores {falta}")


def garantir_catalogo(normas):
    with CATALOGO.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
        fields = list(rows[0]) if rows else ["norma_id", "grupo", "baixar", "url", "rotulo", "observacao"]
    por_id = {r["norma_id"]: r for r in rows}
    for n in normas:
        novo = {"norma_id": n["norma_id"], "grupo": n["grupo"], "baixar": "sim", "url": n["fonte_normativa_oficial"],
                "rotulo": n["rotulo"], "observacao": n["nota_fonte_texto"]}
        if n["norma_id"] in por_id:
            por_id[n["norma_id"]].update(novo)
        else:
            rows.append(novo)
    with CATALOGO.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def desambigua(doc, norma):
    vistos, ultimo = {}, {}
    for no in doc.get("nos", []):
        if not no.get("estrutural", True):
            continue
        oid = no["id"]
        vistos[oid] = vistos.get(oid, 0) + 1
        if vistos[oid] > 1:
            no["id"] = f"{oid}::ocorrencia-{vistos[oid]}"
            no["ocorrencia_id"] = vistos[oid]
            no["id_repetido_na_fonte"] = True
    for no in doc.get("nos", []):
        if no.get("pai"):
            no["pai"] = ultimo.get(no["pai"], no["pai"])
        if no.get("estrutural", True):
            ultimo[no["id"].split("::ocorrencia-")[0]] = no["id"]
    ids = [x["id"] for x in doc.get("nos", []) if x.get("estrutural", True)]
    if len(ids) != len(set(ids)):
        raise RuntimeError(f"{norma}: IDs estruturais repetidos após desambiguação")


def main(argv) -> int:
    normas = [n for n in NORMAS if not argv or n["norma"] in argv or n["norma_id"] in argv]
    garantir_catalogo(normas)
    man_p = SAIDA / "manifest.json"
    man = json.loads(man_p.read_text(encoding="utf-8"))
    rel = {"schema": "relatorio-legislacao-transporte-imagem-v1", "gerado_em": agora(), "normas": []}
    for n in normas:
        print("Baixando", n["norma"], flush=True)
        r = obter(n)
        txt, formato = extrair(r)
        txt = recorta(n, txt)
        validar(n, txt)
        pasta = FONTES / n["norma_id"]
        pasta.mkdir(parents=True, exist_ok=True)
        (pasta / f"texto_bruto.{formato}").write_bytes(r.content)
        txt_path = TEXTOS / f"{n['norma']}--oficial.txt"
        txt_path.write_text(txt, encoding="utf-8")
        meta = {
            "norma": n["norma"], "rotulo": n["rotulo"], "fonte_oficial": n["fonte_normativa_oficial"],
            "fonte_texto_utilizada": n["url"], "fonte_status": n["fonte_status"], "nota_fonte_texto": n["nota_fonte_texto"],
            "url_final": r.url, "consultado_em": agora(), "data_fonte": n["data_fonte"],
            "tipo_data_fonte": "data_do_ato; situação regulatória conferida nas fontes oficiais indicadas",
            "formato_fonte": formato, "sha256_fonte": sha_b(r.content), "sha256_texto": sha_t(txt),
            "status_vigencia": n["status_vigencia"], "status_fonte": n["status_fonte"],
            "texto": str(txt_path.relative_to(BASE)), "data_processamento": agora(),
            "schema": "proveniencia-legislativa-v1", "estruturar_alineas": True,
            "escopo_validacao": "roteiros de transporte de material biológico e de diagnóstico por imagem (app Roteiros); "
                                "demais usos exigem revisão própria",
        }
        txt_path.with_suffix(".meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        doc = estruturar_texto(n["norma"], txt)
        doc["proveniencia"] = meta
        for no in doc.get("nos", []):
            no["status_vigencia"] = n["status_vigencia"]
        desambigua(doc, n["norma"])
        arquivo = slug(n["norma"]) + ".json"
        (SAIDA / "normas" / arquivo).write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
        man["normas"][n["norma"]] = {"arquivo": arquivo, "nos": len(doc["nos"]), "sha256_texto": doc["sha256_texto"],
                                     "proveniencia": meta}
        arts = sum(1 for x in doc["nos"] if x.get("tipo") == "artigo")
        rel["normas"].append({"norma": n["norma"], "arquivo": arquivo, "nos": len(doc["nos"]), "artigos": arts,
                              "chars": len(txt), "status_vigencia": n["status_vigencia"], "fonte": n["status_fonte"]})
        print(f"  {arquivo}: {len(doc['nos'])} nós, {arts} artigos, {len(txt)} caracteres", flush=True)
    man["gerado_em"] = agora()
    man_p.write_text(json.dumps(man, ensure_ascii=False, indent=2), encoding="utf-8")
    (SAIDA / "relatorio-legislacao-transporte-imagem.json").write_text(json.dumps(rel, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
