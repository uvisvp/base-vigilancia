#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Inclui no banco hierárquico (legislacao_v12) as normas que o app Roteiros cita e que
ainda não tinham texto no banco (revisão geral de 25/10/2026):

  - RDC 16/2014 (AFE e AE; Atacadista de medicamentos, situação regulatória);
  - RDC 166/2017 (validação de métodos analíticos; Atacadista, controle de qualidade
    da importadora);
  - RDC 50/2002 (projetos físicos de estabelecimentos assistenciais de saúde; EAC Tipo III,
    infraestrutura). No AnvisaLegis o texto consolidado está em seqAto=002;
  - Portaria SVS/MS 64/2018 (interpretação do teste de sensibilidade aos antimicrobianos
    pelo BrCAST; EAC Tipo III).

Texto oficial do AnvisaLegis (consolidado; as “redações anteriores” ficam só como link
na página e não entram). Mesmo processo de incluir_normas_transporte_imagem.py
(extração, validação, estruturação pelo motor v12 e desambiguação de IDs).
Não reprocessa as demais normas do banco.
Uso: python scripts/incluir_normas_revisao_geral.py [norma ...]"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE / "scripts"))
from estruturar_legislacao import estruturar_texto, slug  # noqa: E402
from atualizar_legislacao_rdc_670_1039 import agora, sha_b, sha_t  # noqa: E402
from incluir_normas_transporte_imagem import (  # noqa: E402
    FONTES, SAIDA, TEXTOS, anvisalegis, desambigua, extrair, garantir_catalogo, obter, rdc, validar)

POR64 = anvisalegis("POR", 64, 2018, "SVS/MS")

NORMAS = [
    rdc(16, 2014, "2014-04-01", ["16", "Art. 1", "Art. 3", "Autorização de Funcionamento"],
        status="vigente_com_alteracoes"),
    rdc(166, 2017, "2017-07-24", ["166", "Art. 1", "validação"]),
    {**rdc(50, 2002, "2002-02-21", ["50", "Art. 1", "projetos físicos"], status="vigente_com_alteracoes",
           min_chars=100000),
     **{k: anvisalegis("RDC", 50, 2002, "RDC/DC/ANVISA/MS").replace("seqAto=000", "seqAto=002")
        for k in ("url", "fonte_normativa_oficial", "fonte_status")}},
    {"norma_id": "portaria-svs-ms-64-2018", "norma": "Portaria SVS MS 64-2018", "grupo": "portaria-svs",
     "rotulo": "Portaria SVS/MS nº 64/2018", "url": POR64, "fonte_normativa_oficial": POR64, "fonte_status": POR64,
     "nota_fonte_texto": "Texto oficial obtido diretamente do AnvisaLegis (normas de interpretação do teste de "
                         "sensibilidade aos antimicrobianos pelo BrCAST).",
     "data_fonte": "2018-12-11", "status_vigencia": "vigente", "status_fonte": "AnvisaLegis",
     "min_chars": 500, "obrig": ["Art. 1", "BrCAST", "Art. 2"]},
]

MARCAS = {
    "rdc-anvisa": r"^Resolu[çc][ãa]o da Diretoria Colegiada - RDC",
    "portaria-svs": r"^PORTARIA N",
}


def recorta(n, txt):
    """Remove o cabeçalho de navegação do AnvisaLegis (antes do título do ato) e o rodapé."""
    ls = txt.split("\n")
    i = next((k for k, l in enumerate(ls) if re.match(MARCAS[n["grupo"]], l, re.I)), None)
    if i is not None:
        ls = ls[i:]
    fim = next((k for k, l in enumerate(ls) if l.startswith("Este texto não substitui")), None)
    if fim is not None:
        ls = ls[:fim]
    return re.sub(r"\n(?=art\.\s*\d)", " ", "\n".join(ls))


def main(argv) -> int:
    normas = [n for n in NORMAS if not argv or n["norma"] in argv or n["norma_id"] in argv]
    garantir_catalogo(normas)
    man_p = SAIDA / "manifest.json"
    man = json.loads(man_p.read_text(encoding="utf-8"))
    rel = {"schema": "relatorio-legislacao-revisao-geral-v1", "gerado_em": agora(), "normas": []}
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
            "escopo_validacao": "citações do app Roteiros (Atacadista de medicamentos e EAC Tipo III); "
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
    (SAIDA / "relatorio-legislacao-revisao-geral.json").write_text(json.dumps(rel, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
