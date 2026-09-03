#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Gera um manifesto regulatório único para consumo pelo app.

Integra, sem misturar texto literal com regra operacional:
- legislação hierárquica estruturada (dados/legislacao_v12);
- limites curados da IN 75/2020;
- regras operacionais de regularização de cosméticos e saneantes;
- listas vigentes da Portaria 344/98, quando já geradas.

O manifesto apenas referencia arquivos existentes e valida seus schemas/IDs.
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


def main():
    SAIDA.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema": "manifesto-regulatorio-v1",
        "gerado_em": datetime.now(timezone.utc).isoformat(),
        "bases": {},
    }

    # Legislação hierárquica já estruturada/curada.
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

    # IN 75/2020 - Anexo XV: dados numéricos usados pela lupa.
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

    # Bases operacionais de regularização.
    for nome, arquivo, categoria in [
        ("regularizacao_cosmeticos", "regularizacao-cosmeticos.json", "cosmeticos"),
        ("regularizacao_saneantes", "regularizacao-saneantes.json", "saneantes"),
    ]:
        obj = registrar_arquivo(
            manifest, nome, CURADA / arquivo, "regularizacao-produtos-v1",
            lambda o: len(o.get("regras", [])))
        if obj:
            if obj.get("categoria") != categoria:
                raise RuntimeError(f"{nome}: categoria inesperada")
            validar_ids_unicos(obj.get("regras", []), contexto=nome)

    # Portaria 344/98 é produzida por workflow separado; ausência não invalida
    # o manifesto, mas fica explicitamente visível para o app/diagnóstico.
    ctrl_manifest = DADOS / "controlados_portaria344" / "manifest.json"
    ctrl = registrar_arquivo(manifest, "controlados_portaria344", ctrl_manifest,
                             "controlados-portaria344-v1")
    if ctrl:
        manifest["bases"]["controlados_portaria344"].update({
            "listas": ctrl.get("listas"),
            "substancias": ctrl.get("substancias"),
            "adendos": ctrl.get("adendos"),
            "norma_fonte": ctrl.get("norma_fonte"),
            "data_fonte": ctrl.get("data_fonte"),
        })

    # Estado global: pronto apenas quando todas as quatro famílias estão presentes.
    faltantes = [k for k,v in manifest["bases"].items() if v.get("status") != "ok"]
    manifest["status"] = "ok" if not faltantes else "parcial"
    manifest["faltantes"] = faltantes

    out = SAIDA / "manifest.json"
    out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": manifest["status"], "faltantes": faltantes}, ensure_ascii=False))


if __name__ == "__main__":
    main()
