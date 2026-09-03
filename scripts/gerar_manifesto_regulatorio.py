#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Gera um manifesto regulatório único para consumo pelo app.

Integra, sem misturar texto literal com regra operacional:
- legislação hierárquica estruturada (dados/legislacao_v12);
- base completa da IN 75/2020 e seus 23 anexos;
- limites curados do Anexo XV da IN 75/2020;
- regras operacionais de regularização de cosméticos e saneantes;
- listas operacionais da Portaria 344/98.

O manifesto referencia arquivos existentes e falha quando uma base obrigatória está
ausente ou estruturalmente incompleta.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
DADOS = BASE / "dados"
CURADA = DADOS / "legislacao_curada"
SAIDA = DADOS / "regulatorio"

IN75_FONTE_OFICIAL = (
    "https://anvisalegis.datalegis.net/action/ActionDatalegis.php?"
    "acao=abrirTextoAto&tipo=INM&numeroAto=00000075&seqAto=000&valorAno=2020&"
    "orgao=DC/ANVISA/MS&codTipo=&desItem=&desItemFim=&cod_menu=9434&"
    "cod_modulo=310&pesquisa=true"
)
IN75_ANEXOS = [
    "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI",
    "XII", "XIII", "XIV", "XV", "XVI", "XVII", "XVIII", "XIX", "XX",
    "XXI", "XXII", "XXIII",
]
COSMETICOS_REGISTRO = {
    "Bronzeador",
    "Gel antisséptico para as mãos",
    "Produto para alisar os cabelos",
    "Produto para alisar e tingir os cabelos",
    "Produto para ondular os cabelos",
    "Protetor solar",
    "Protetor solar infantil",
    "Repelente de insetos",
    "Repelente de insetos infantil",
}
COSMETICOS_COMPLEMENTARES = {"RDC 906/2024", "RDC 898/2024"}
SANEANTES_MARCO_ATUAL = {"RDC 989/2025", "IN 394/2025", "RDC 1.040/2026", "IN 468/2026"}


def ler_json(path: Path):
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_arquivo(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validar_ids_unicos(itens, campo="id", contexto="base"):
    ids = [x.get(campo) for x in itens if isinstance(x, dict) and x.get(campo)]
    dup = sorted({x for x in ids if ids.count(x) > 1})
    if dup:
        raise RuntimeError(f"{contexto}: IDs duplicados: {dup[:10]}")


def registrar_arquivo(manifest, nome, path, schema_esperado=None, contagem=None):
    obj = ler_json(path)
    if obj is None:
        manifest["bases"][nome] = {"status": "ausente", "arquivo": str(path.relative_to(BASE))}
        return None
    schema = obj.get("schema") if isinstance(obj, dict) else None
    if schema_esperado and schema != schema_esperado:
        raise RuntimeError(f"{nome}: schema {schema!r}; esperado {schema_esperado!r}")
    reg = {
        "status": "ok",
        "arquivo": str(path.relative_to(BASE)).replace('\\','/'),
        "schema": schema,
        "sha256": sha256_arquivo(path),
    }
    if contagem is not None:
        reg["registros"] = contagem(obj)
    manifest["bases"][nome] = reg
    return obj


def validar_regularizacao_base(obj, categoria, contexto):
    if obj.get("categoria") != categoria:
        raise RuntimeError(f"{contexto}: categoria inesperada {obj.get('categoria')!r}")
    regras = obj.get("regras")
    if not isinstance(regras, list) or not regras:
        raise RuntimeError(f"{contexto}: regras ausentes")
    if any(not isinstance(r, dict) or not r.get("id") for r in regras):
        raise RuntimeError(f"{contexto}: regra sem ID")
    validar_ids_unicos(regras, contexto=contexto)
    return regras


def validar_cosmeticos(obj):
    regras = validar_regularizacao_base(obj, "cosmeticos", "regularizacao_cosmeticos")
    if obj.get("norma_principal") != "RDC 907/2024":
        raise RuntimeError("Cosméticos: norma principal deve ser RDC 907/2024")

    complementares = {
        x.get("norma") if isinstance(x, dict) else x
        for x in obj.get("normas_complementares", [])
    }
    faltam_comp = COSMETICOS_COMPLEMENTARES - complementares
    if faltam_comp:
        raise RuntimeError(f"Cosméticos: normas complementares ausentes: {sorted(faltam_comp)}")

    regras_registro = [r for r in regras if r.get("regularizacao") == "registro"]
    produtos_registro = {r.get("produto") for r in regras_registro}
    if len(regras_registro) != 9 or produtos_registro != COSMETICOS_REGISTRO:
        raise RuntimeError(
            "Cosméticos: lista de produtos sujeitos a registro divergente; "
            f"quantidade={len(regras_registro)}, produtos={sorted(x for x in produtos_registro if x)}"
        )

    notificacao = [r for r in regras if r.get("id") == "cosmeticos::notificacao::demais"]
    if len(notificacao) != 1 or notificacao[0].get("regularizacao") != "notificacao":
        raise RuntimeError("Cosméticos: regra residual de notificação ausente ou inválida")

    # A RDC 752/2022 pode existir em observação histórica de revogação, mas nunca
    # em campos estruturados que definem o marco vigente.
    ativos = [obj.get("norma_principal", "")] + [x for x in complementares if x]
    if any("752/2022" in x for x in ativos):
        raise RuntimeError("Cosméticos: RDC 752/2022 não pode integrar o marco vigente")
    return regras


def validar_saneantes(obj):
    regras = validar_regularizacao_base(obj, "saneantes", "regularizacao_saneantes")
    principal = obj.get("norma_principal", "")
    complementares = {
        x.get("norma") if isinstance(x, dict) else x
        for x in obj.get("normas_complementares", [])
    }
    marco = {principal} | complementares
    faltam = SANEANTES_MARCO_ATUAL - marco
    if faltam:
        raise RuntimeError(f"Saneantes: normas obrigatórias ausentes: {sorted(faltam)}")

    por_id = {r["id"]: r for r in regras}
    risco1 = por_id.get("saneantes::risco-1::notificacao")
    risco2 = por_id.get("saneantes::risco-2::registro")
    if not risco1 or risco1.get("regularizacao") != "notificacao":
        raise RuntimeError("Saneantes: regra Risco 1 -> notificação ausente ou inválida")
    if not risco2 or risco2.get("regularizacao") != "registro":
        raise RuntimeError("Saneantes: regra Risco 2 -> registro ausente ou inválida")

    pos = obj.get("norma_pos_regularizacao_geral")
    if not isinstance(pos, dict) or pos.get("norma") != "RDC 899/2024":
        raise RuntimeError("Saneantes: RDC 899/2024 deve constar como norma geral de pós-regularização")
    if "RDC 899/2024" not in complementares:
        raise RuntimeError("Saneantes: RDC 899/2024 ausente das normas complementares")

    ativos = [principal] + [x for x in complementares if x] + [pos.get("norma", "")]
    if any("59/2010" in x for x in ativos):
        raise RuntimeError("Saneantes: RDC 59/2010 não pode integrar o marco vigente")
    return regras


def main():
    SAIDA.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema": "manifesto-regulatorio-v1",
        "gerado_em": datetime.now(timezone.utc).isoformat(),
        "bases": {},
    }

    leg_manifest = DADOS / "legislacao_v12" / "manifest.json"
    if leg_manifest.exists():
        obj = registrar_arquivo(manifest, "legislacao_hierarquica", leg_manifest,
                                "legislacao-hierarquica-v12")
        if obj:
            manifest["bases"]["legislacao_hierarquica"]["normas"] = len(obj.get("normas", {}))
            manifest["bases"]["legislacao_hierarquica"]["curados"] = obj.get("curados", 0)
    else:
        manifest["bases"]["legislacao_hierarquica"] = {
            "status": "ausente",
            "arquivo": "dados/legislacao_v12/manifest.json"
        }

    in75_completa = registrar_arquivo(
        manifest,
        "in75_completa",
        DADOS / "legislacao_v12" / "normas" / "in-75-2020.json",
        "legislacao-hierarquica-v12",
        lambda o: len(o.get("nos", [])),
    )
    if in75_completa:
        nos = in75_completa.get("nos", [])
        anexos_nos = [n for n in nos if n.get("tipo") == "anexo"]
        anexos = [n.get("anexo") for n in anexos_nos]
        if len(anexos_nos) != 23 or set(anexos) != set(IN75_ANEXOS):
            raise RuntimeError(
                f"IN 75/2020 completa: anexos inválidos; quantidade={len(anexos_nos)}, "
                f"achados={sorted(set(anexos))}"
            )
        ids_estruturais = [n.get("id") for n in nos if n.get("estrutural", True)]
        validar_ids_unicos(
            [{"id": x} for x in ids_estruturais if x],
            contexto="IN 75/2020 completa",
        )
        repetidos = in75_completa.get("validacao", {}).get("ids_estruturais_repetidos", [])
        if repetidos:
            raise RuntimeError(f"IN 75/2020 completa: IDs estruturais repetidos: {repetidos[:10]}")
        reg = manifest["bases"]["in75_completa"]
        reg.update({
            "norma": in75_completa.get("norma"),
            "fonte_oficial": IN75_FONTE_OFICIAL,
            "data_norma": "2020-10-08",
            "sha256_texto": in75_completa.get("sha256_texto"),
            "anexos": len(anexos_nos),
            "anexos_incluidos": IN75_ANEXOS,
            "tabelas": len([n for n in nos if n.get("tipo") == "tabela"]),
            "linhas_tabela": len([n for n in nos if n.get("tipo") == "linha_tabela"]),
        })

    in75 = registrar_arquivo(
        manifest,
        "in75_anexo_xv",
        CURADA / "in-75-2020-anexo-xv.json",
        "legislacao-curada-v1",
        lambda o: len(o.get("registros", [])),
    )
    if in75:
        regs = in75.get("registros", [])
        validar_ids_unicos([
            {"id": f"{r.get('norma')}::{r.get('anexo')}::{r.get('tipo')}::{r.get('numero')}"}
            for r in regs
        ], contexto="IN 75/2020 Anexo XV")
        obrig = {"acucares-adicionados", "gorduras-saturadas", "sodio"}
        achados = {r.get("numero") for r in regs}
        if obrig - achados:
            raise RuntimeError("IN 75/2020 Anexo XV incompleto")
        manifest["bases"]["in75_anexo_xv"].update({
            "escopo": "operacional_complementar",
            "fonte_oficial": IN75_FONTE_OFICIAL,
        })

    cosmeticos = registrar_arquivo(
        manifest, "regularizacao_cosmeticos", CURADA / "regularizacao-cosmeticos.json",
        "regularizacao-produtos-v1", lambda o: len(o.get("regras", [])))
    if cosmeticos:
        regras = validar_cosmeticos(cosmeticos)
        reg = manifest["bases"]["regularizacao_cosmeticos"]
        reg.update({
            "categoria": cosmeticos.get("categoria"),
            "fonte_oficial": cosmeticos.get("fonte_oficial"),
            "data_fonte": cosmeticos.get("data_fonte"),
            "tipo_data_fonte": cosmeticos.get("tipo_data_fonte"),
            "norma_principal": cosmeticos.get("norma_principal"),
            "normas_complementares": cosmeticos.get("normas_complementares", []),
            "produtos_registro_obrigatorio": len([r for r in regras if r.get("regularizacao") == "registro"]),
            "regra_demais_produtos": "notificacao",
        })

    saneantes = registrar_arquivo(
        manifest, "regularizacao_saneantes", CURADA / "regularizacao-saneantes.json",
        "regularizacao-produtos-v1", lambda o: len(o.get("regras", [])))
    if saneantes:
        validar_saneantes(saneantes)
        reg = manifest["bases"]["regularizacao_saneantes"]
        reg.update({
            "categoria": saneantes.get("categoria"),
            "fonte_oficial": saneantes.get("fonte_oficial"),
            "data_fonte": saneantes.get("data_fonte"),
            "tipo_data_fonte": saneantes.get("tipo_data_fonte"),
            "norma_principal": saneantes.get("norma_principal"),
            "normas_complementares": saneantes.get("normas_complementares", []),
            "norma_pos_regularizacao_geral": saneantes.get("norma_pos_regularizacao_geral"),
            "norma_revogada_relevante": saneantes.get("norma_revogada_relevante"),
            "risco_1": "notificacao",
            "risco_2": "registro",
        })

    ctrl_manifest = DADOS / "controlados_portaria344" / "manifest.json"
    ctrl = registrar_arquivo(manifest, "controlados_portaria344", ctrl_manifest,
                             "controlados-portaria344-v2")
    if ctrl:
        listas_esperadas = ["A1","A2","A3","B1","B2","C1","C2","C3","C5"]
        if ctrl.get("status") != "ok" or ctrl.get("escopo") != "operacional":
            raise RuntimeError("Portaria 344: base operacional inválida")
        if ctrl.get("listas_incluidas") != listas_esperadas:
            raise RuntimeError("Portaria 344: escopo de listas inesperado")
        manifest["bases"]["controlados_portaria344"].update({
            "escopo": ctrl.get("escopo"),
            "listas_incluidas": ctrl.get("listas_incluidas"),
            "listas": ctrl.get("listas"),
            "substancias": ctrl.get("substancias"),
            "adendos": ctrl.get("adendos"),
            "norma_fonte": ctrl.get("norma_fonte"),
            "data_fonte": ctrl.get("data_fonte"),
        })

    faltantes = [k for k,v in manifest["bases"].items() if v.get("status") != "ok"]
    manifest["status"] = "ok" if not faltantes else "parcial"
    manifest["faltantes"] = faltantes

    out = SAIDA / "manifest.json"
    out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": manifest["status"], "faltantes": faltantes}, ensure_ascii=False))


if __name__ == "__main__":
    main()
