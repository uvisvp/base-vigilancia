#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Inclui no banco legislativo hierárquico v12:

- RDC 637/2022: cadastro, na Anvisa, de todos os insumos farmacêuticos ativos com que a empresa
  trabalha (vigente). Estruturada pelo motor padrão (artigos, parágrafos e incisos).
- RDC 81/2008: regulamento técnico de bens e produtos importados (vigente com alterações). O
  regulamento é dividido em capítulos cuja numeração de itens recomeça a cada capítulo; os itens
  ficam em <norma>::capitulo::<romano>::item::<n-n>, com alíneas em ...::alinea::<letra>, para que a
  citação "RDC Anvisa nº 81/2008, Capítulo IV, item 2.1" seja resolvida sem ambiguidade. Os artigos
  da resolução (antes do ANEXO) seguem o motor padrão.

Texto obtido diretamente do AnvisaLegis. Sem dependência de pypdf: as duas fontes são HTML.
Uso: python3 scripts/atualizar_legislacao_rdc_637_81.py
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BASE = Path(__file__).resolve().parent.parent
FONTES = BASE / "fontes"
TEXTOS = BASE / "textos"
CATALOGO = FONTES / "normas.csv"
SAIDA = BASE / "dados" / "legislacao_v12"
sys.path.insert(0, str(BASE / "scripts"))
from estruturar_legislacao import estruturar_texto, slug, sha256_texto  # noqa: E402

HEAD = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/128 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.7",
    "Accept-Encoding": "identity",
    "Connection": "close",
}
U637 = "https://anvisalegis.datalegis.net/action/ActionDatalegis.php?acao=abrirTextoAto&cod_menu=9431&cod_modulo=310&link=S&numeroAto=00000637&orgao=RDC%2FDC%2FANVISA%2FMS&seqAto=000&tipo=RDC&valorAno=2022"
U81 = "https://anvisalegis.datalegis.net/action/ActionDatalegis.php?acao=abrirTextoAto&tipo=RDC&numeroAto=00000081&seqAto=000&valorAno=2008&orgao=RDC/DC/ANVISA/MS&codTipo=&desItem=&desItemFim=&cod_menu=9434&cod_modulo=310&pesquisa=true"
NORMAS = [
    {
        "norma_id": "rdc-anvisa-637-2022", "norma": "RDC 637-2022", "grupo": "rdc-anvisa",
        "rotulo": "RDC Anvisa nº 637/2022", "url": U637, "fonte_normativa_oficial": U637, "fonte_status": U637,
        "nota_fonte_texto": "Texto oficial obtido diretamente do AnvisaLegis.",
        "data_fonte": "2022-03-24", "status_vigencia": "vigente", "status_fonte": "AnvisaLegis",
        "min_chars": 1500, "obrig": ["637", "Art. 1", "Art. 3", "insumos farmacêuticos ativos"], "modo": "padrao",
    },
    {
        "norma_id": "rdc-anvisa-81-2008", "norma": "RDC 81-2008", "grupo": "rdc-anvisa",
        "rotulo": "RDC Anvisa nº 81/2008", "url": U81, "fonte_normativa_oficial": U81, "fonte_status": U81,
        "nota_fonte_texto": "Texto consolidado (vigente com alterações) obtido diretamente do AnvisaLegis.",
        "data_fonte": "2008-11-05", "status_vigencia": "vigente com alterações", "status_fonte": "AnvisaLegis",
        "min_chars": 150000, "obrig": ["CAPÍTULO IV", "CAPÍTULO VII", "CAPÍTULO XXXI", "IMPORTAÇÃO TERCEIRIZADA"], "modo": "capitulos",
    },
]


def agora() -> str:
    return datetime.now(timezone.utc).isoformat()


def baixar(url: str):
    erro = None
    for i in range(4):
        try:
            r = requests.get(url, headers=HEAD, timeout=(20, 180), allow_redirects=True)
            r.raise_for_status()
            if len(r.content) < 500:
                raise RuntimeError("resposta curta")
            return r
        except Exception as exc:  # noqa: BLE001
            erro = exc
            if i < 3:
                time.sleep(min(2 ** i, 8))
    raise RuntimeError(f"Falha ao baixar {url}: {erro}")


CORTE = {"Voltar", "Imprimir", "Compartilhar:", "Redefinir Cookies", "COPIAR LINK", "CRIAR TAGS", "IMPRIMIR", "PDF",
         "VER NOTAS DE ALTERAÇÃO", "FECHAR NOTAS DE ALTERAÇÃO", "+", "|", "-", "Ver mais detalhes", "Carregando...",
         "Redações Anteriores", "NORMAS REGULATÓRIAS DA ANVISA", "NORMAS POR TEMAS"}


def extrair(r) -> str:
    soup = BeautifulSoup(r.content, "html.parser")
    for x in soup(["script", "style", "noscript", "nav", "footer"]):
        x.decompose()
    linhas = []
    for ln in soup.get_text("\n").splitlines():
        ln = re.sub(r"\s+", " ", ln).strip()
        if not ln or ln in CORTE or ln.startswith("-->"):
            continue
        linhas.append(ln)
    # trechos ligados (normas citadas viram links e quebram a linha): reúne o que não abre dispositivo
    abre = re.compile(r"^(Art\.?\s*\d|§|Par[áa]grafo\s+[úu]nico|CAP[ÍI]TULO\b|Cap[íi]tulo\s+[IVXLC]|SE[ÇC][ÃA]O\b|ANEXO\b|"
                      r"\d{1,3}(\.\d{1,3})*\.?\s|[a-z]\)|[ivx]{1,4}\)|[IVXLC]+\s*[-–—]\s|\(Redação|\(Incluíd|\(Revogad|\(Suprimid|Nota Anvisa)")
    junto = []
    for ln in linhas:
        cola = junto and (ln[0] in ",.;:)" or re.match(r"^(e|ou|nos?|nas?|da|do|de)\b", ln) or not re.search(r"[.;:)]\s*$", junto[-1]))
        if cola and not abre.match(ln):
            junto[-1] = (junto[-1] + ("" if ln[0] in ",.;:)" else " ") + ln).strip()
        else:
            junto.append(ln)
    # notas de alteração: "(Redação dada pela RDC nº 208, de 05/01/2018)" numa linha só, presa ao dispositivo
    out = []
    for ln in junto:
        if re.match(r"^\((Redação|Incluíd|Revogad|Suprimid)", ln) and out:
            out[-1] = out[-1] + " " + ln
        else:
            out.append(ln)
    return "\n".join(out).strip()


def validar(n: dict, txt: str):
    if len(txt) < n["min_chars"]:
        raise RuntimeError(f"{n['norma']}: texto curto ({len(txt)})")
    falt = [x for x in n["obrig"] if x.casefold() not in txt.casefold()]
    if falt:
        raise RuntimeError(f"{n['norma']}: faltam marcadores {falt}")


RE_CAP = re.compile(r"^CAP[ÍI]TULO\s+([IVXLC]+(?:-[A-Z])?)\s*(.*)$", re.I)
RE_SEC = re.compile(r"^SE[ÇC][ÃA]O\s+([IVXLC]+(?:-[A-Z])?)\s*(.*)$", re.I)
RE_IT = re.compile(r"^(\d{1,3}(?:\.\d{1,3})*)\.?\s+(\S.*)$")
RE_AL = re.compile(r"^([a-z]{1,4})\)\s*(.*)$")
ROMANOS = {"i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x"}


def estruturar_capitulos(norma: str, texto: str) -> dict:
    """Artigos da resolução pelo motor padrão; regulamento anexo por capítulo, item e alínea."""
    linhas = texto.splitlines()
    k = next((i for i, l in enumerate(linhas) if re.match(r"^ANEXO\b", l.strip())), None)
    if k is None:
        raise RuntimeError(f"{norma}: linha ANEXO não encontrada")
    doc = estruturar_texto(norma, "\n".join(linhas[:k]))
    nos = doc["nos"]
    ordem = len(nos)
    sn = slug(norma)
    cap = cap_id = None
    item = None      # nó do item corrente
    alinea = None    # nó da alínea corrente
    ultima_letra = None
    vistos: dict[str, int] = {}

    def novo(tipo, nid, rotulo, texto, pai=None, estrutural=True, numero=""):
        nonlocal ordem
        ordem += 1
        if estrutural:
            vistos[nid] = vistos.get(nid, 0) + 1
            if vistos[nid] > 1:
                nid = f"{nid}::ocorrencia-{vistos[nid]}"
        n = {"id": nid, "norma": norma, "anexo": "regulamento", "tipo": tipo, "numero": numero, "rotulo": rotulo,
             "texto": texto, "ordem": ordem}
        if pai:
            n["pai"] = pai
        if not estrutural:
            n["estrutural"] = False
        nos.append(n)
        return n

    pendente_titulo = None
    for bruta in linhas[k + 1:]:
        l = bruta.strip()
        if not l:
            continue
        m = RE_CAP.match(l)
        if m:
            cap = m.group(1).upper()
            cap_id = f"{sn}::capitulo::{cap.lower()}"
            no = novo("capitulo", cap_id, f"Capítulo {cap}", l, numero=cap)
            pendente_titulo = None if m.group(2).strip() else no
            item = alinea = None
            ultima_letra = None
            continue
        if pendente_titulo is not None and not RE_IT.match(l) and not RE_SEC.match(l):
            pendente_titulo["texto"] = f"{pendente_titulo['texto']} — {l}"
            pendente_titulo = None
            continue
        pendente_titulo = None
        if cap_id is None:
            novo("bloco", f"{sn}::regulamento::bloco::{ordem + 1}", "Texto", l, estrutural=False)
            continue
        if RE_SEC.match(l):
            novo("bloco", f"{cap_id}::bloco::{ordem + 1}", "Seção", l, pai=cap_id, estrutural=False)
            item = alinea = None
            continue
        m = RE_IT.match(l)
        if m:
            num = m.group(1)
            item = novo("item", f"{cap_id}::item::{num.replace('.', '-')}", f"Capítulo {cap}, item {num}", l, pai=cap_id, numero=num)
            alinea = None
            ultima_letra = None
            continue
        m = RE_AL.match(l)
        if m and item is not None:
            letra = m.group(1)
            esperada = chr(ord(ultima_letra) + 1) if ultima_letra and len(ultima_letra) == 1 else "a"
            sub = letra in ROMANOS and letra != esperada and alinea is not None
            item["texto"] += "\n" + l
            if sub:
                alinea["texto"] += "\n" + l
            else:
                alinea = novo("alinea", f"{item['id']}::alinea::{letra}", f"{item['rotulo']}, alínea “{letra}”", l, pai=item["id"], numero=letra)
                ultima_letra = letra
            continue
        if item is not None:
            item["texto"] += "\n" + l
            if alinea is not None:
                alinea["texto"] += "\n" + l
            continue
        novo("bloco", f"{cap_id}::bloco::{ordem + 1}", "Texto", l, pai=cap_id, estrutural=False)

    ids = [n["id"] for n in nos if n.get("estrutural", True)]
    rep = sorted({x for x in ids if ids.count(x) > 1})
    doc["nos"] = nos
    doc["sha256_texto"] = sha256_texto(texto)
    doc["validacao"]["ids_estruturais_repetidos"] = rep
    doc["validacao"]["estrutura_regulamento"] = "capitulo::item::alinea (numeração de itens recomeça a cada capítulo)"
    return doc


def garantir_catalogo():
    with CATALOGO.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
        fields = list(rows[0]) if rows else ["norma_id", "grupo", "baixar", "url", "rotulo", "observacao"]
    por_id = {r["norma_id"]: r for r in rows}
    mudou = False
    for n in NORMAS:
        if n["norma_id"] not in por_id:
            rows.append({"norma_id": n["norma_id"], "grupo": n["grupo"], "baixar": "sim", "url": n["fonte_normativa_oficial"],
                         "rotulo": n["rotulo"], "observacao": n["nota_fonte_texto"]})
            mudou = True
    if mudou:
        with CATALOGO.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields, lineterminator="\n", extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
    return mudou


def main() -> int:
    cat = garantir_catalogo()
    (SAIDA / "normas").mkdir(parents=True, exist_ok=True)
    TEXTOS.mkdir(exist_ok=True)
    mpath = SAIDA / "manifest.json"
    manifest = json.loads(mpath.read_text(encoding="utf-8"))
    rel = {"schema": "relatorio-legislacao-rdc-637-81-v1", "gerado_em": agora(), "catalogo_atualizado": cat, "normas": []}
    for n in NORMAS:
        print("Baixando", n["norma"])
        r = baixar(n["url"])
        txt = extrair(r)
        validar(n, txt)
        pasta = FONTES / n["norma_id"]
        pasta.mkdir(parents=True, exist_ok=True)
        (pasta / "texto_bruto.html").write_bytes(r.content)
        tpath = TEXTOS / f"{n['norma']}--oficial.txt"
        tpath.write_text(txt, encoding="utf-8")
        meta = {
            "norma": n["norma"], "rotulo": n["rotulo"], "fonte_oficial": n["fonte_normativa_oficial"],
            "fonte_texto_utilizada": n["url"], "fonte_status": n["fonte_status"], "nota_fonte_texto": n["nota_fonte_texto"],
            "url_final": r.url, "consultado_em": agora(), "data_fonte": n["data_fonte"],
            "tipo_data_fonte": "data_do_ato; texto consolidado conferido no AnvisaLegis", "formato_fonte": "html",
            "sha256_fonte": hashlib.sha256(r.content).hexdigest(), "sha256_texto": sha256_texto(txt),
            "status_vigencia": n["status_vigencia"], "status_fonte": n["status_fonte"], "texto": str(tpath.relative_to(BASE)),
            "data_processamento": agora(), "schema": "proveniencia-legislativa-v1",
        }
        tpath.with_suffix(".meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        doc = estruturar_texto(n["norma"], txt) if n["modo"] == "padrao" else estruturar_capitulos(n["norma"], txt)
        doc["proveniencia"] = meta
        for no in doc["nos"]:
            no["status_vigencia"] = n["status_vigencia"]
        # artigo repetido na fonte (o AnvisaLegis repete o art. 1º da RDC 81): ocorrência numerada
        vistos: dict[str, int] = {}
        for no in doc["nos"]:
            if not no.get("estrutural", True) or "::ocorrencia-" in no["id"]:
                continue
            vistos[no["id"]] = vistos.get(no["id"], 0) + 1
            if vistos[no["id"]] > 1:
                no["id"] = f"{no['id']}::ocorrencia-{vistos[no['id']]}"
                no["id_repetido_na_fonte"] = True
        ids = [x["id"] for x in doc["nos"] if x.get("estrutural", True)]
        if len(ids) != len(set(ids)):
            raise RuntimeError(f"{n['norma']}: IDs estruturais repetidos")
        arquivo = slug(n["norma"]) + ".json"
        (SAIDA / "normas" / arquivo).write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
        manifest["normas"][n["norma"]] = {"arquivo": arquivo, "nos": len(doc["nos"]), "sha256_texto": doc["sha256_texto"], "proveniencia": meta}
        rel["normas"].append({"norma": n["norma"], "arquivo": arquivo, "nos": len(doc["nos"]), "chars": len(txt),
                              "status_vigencia": n["status_vigencia"], "fonte_oficial": n["fonte_normativa_oficial"]})
    manifest["gerado_em"] = agora()
    mpath.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    rel["total_normas_manifest"] = len(manifest["normas"])
    (SAIDA / "relatorio-legislacao-rdc-637-81.json").write_text(json.dumps(rel, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(rel, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
