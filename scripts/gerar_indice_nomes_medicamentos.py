#!/usr/bin/env python3
"""Gera índices leves para consulta por nome de medicamento, princípio ativo e IFA.

Os arquivos de medicamentos são fragmentados por número de registro; por isso não
servem para completar uma busca textual no campo. Este gerador cria pequenos
fragmentos por três letras normalizadas. A interface só os busca a partir de três
caracteres e limita os resultados, sem consultar empresas.

A indicação de lista da Portaria SVS/MS nº 344/1998 é feita somente por
correspondência nominal exata do princípio ativo/IFA contra a lista pública local.
Não há inferência por trecho, sal, éster, classe terapêutica ou nome comercial.
"""
from __future__ import annotations

import json
import re
import shutil
import unicodedata
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

MEDICAMENTOS = Path("dados/medicamentos")
IFA = Path("dados/ifa/registros.json")
LISTAS = Path("dados/controlados_portaria344/listas.json")
LISTAS_MANIFEST = Path("dados/controlados_portaria344/manifest.json")
OUT = Path("dados/indices/nome_medicamentos")
MANIFEST_RAIZ = Path("dados/manifest.json")


def texto(v: object) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()


def normalizar(v: object) -> str:
    v = unicodedata.normalize("NFD", texto(v))
    v = "".join(ch for ch in v if unicodedata.category(ch) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", v.lower()).strip()


def chave(v: object) -> str:
    n = normalizar(v).replace(" ", "")
    return n[:3] if len(n) >= 3 else n.ljust(3, "_")


def carregar_listas() -> dict[str, list[dict[str, str]]]:
    """Mapa estrito: nome normalizado da substância -> lista(s) confirmada(s)."""
    payload = json.loads(LISTAS.read_text(encoding="utf-8"))
    out: dict[str, list[dict[str, str]]] = defaultdict(list)
    for grupo in payload.get("listas", []):
        for substancia in grupo.get("substancias", []):
            nome = texto(substancia.get("nome"))
            n = normalizar(nome)
            if n:
                out[n].append({"lista": texto(grupo.get("lista")), "substancia": nome})
    return dict(out)


def listas_confirmadas(principio: object, mapa: dict[str, list[dict[str, str]]]) -> list[dict[str, str]]:
    """Retorna apenas igualdade nominal; combinações são separadas por '+' ou ';'."""
    base = texto(principio)
    candidatos = [base]
    if "+" in base or ";" in base:
        candidatos.extend(x.strip() for x in re.split(r"[+;]", base) if x.strip())
    vistos: set[tuple[str, str]] = set()
    resultado: list[dict[str, str]] = []
    for item in candidatos:
        for achado in mapa.get(normalizar(item), []):
            k = (achado["lista"], achado["substancia"])
            if k not in vistos:
                vistos.add(k)
                resultado.append(achado)
    return sorted(resultado, key=lambda x: (x["lista"], normalizar(x["substancia"])))


def carregar_medicamentos() -> list[dict]:
    registros: list[dict] = []
    for arquivo in MEDICAMENTOS.glob("*.json"):
        try:
            registros.extend(json.loads(arquivo.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Não foi possível ler {arquivo}: {exc}") from exc
    return registros


def resumo_medicamento(r: dict, listas: dict[str, list[dict[str, str]]]) -> dict:
    ativo = texto(r.get("principio_ativo"))
    return {
        "tipo": "medicamento",
        "produto": texto(r.get("produto")),
        "principio_ativo": ativo,
        "registro": texto(r.get("registro")),
        "processo": texto(r.get("processo")),
        "situacao": texto(r.get("situacao")),
        "classe_terapeutica": texto(r.get("classe_terapeutica")),
        "listas_portaria344": listas_confirmadas(ativo, listas),
    }


def resumo_ifa(r: dict, listas: dict[str, list[dict[str, str]]]) -> dict:
    ifa = texto(r.get("ifa"))
    return {
        "tipo": "ifa",
        "ifa": ifa,
        "fabricante_ifa": texto(r.get("fabricante_ifa")),
        "codigo_fabricante_ifa": texto(r.get("codigo_fabricante_ifa")),
        "processo_anvisa": texto(r.get("processo_anvisa")),
        "detentor_peticionante": texto(r.get("detentor_peticionante")),
        "listas_portaria344": listas_confirmadas(ifa, listas),
    }


def adicionar(indice: dict[str, list[dict]], termo: object, resumo: dict) -> None:
    n = normalizar(termo)
    if len(n.replace(" ", "")) < 3:
        return
    item = dict(resumo)
    item["termo"] = n
    indice[chave(n)].append(item)


def deduplicar_e_ordenar(itens: list[dict]) -> list[dict]:
    vistos: set[str] = set()
    final: list[dict] = []
    for item in sorted(itens, key=lambda x: (x["termo"], x["tipo"], x.get("produto", x.get("ifa", "")), x.get("registro", x.get("processo_anvisa", "")))):
        identidade = "|".join([
            item.get("tipo", ""), item.get("termo", ""), item.get("registro", ""),
            item.get("processo_anvisa", ""), item.get("produto", ""), item.get("ifa", ""),
        ])
        if identidade not in vistos:
            vistos.add(identidade)
            final.append(item)
    return final


def gerar() -> dict:
    if not MEDICAMENTOS.exists() or not IFA.exists() or not LISTAS.exists():
        raise RuntimeError("Execute após gerar medicamentos, IFA e listas da Portaria 344.")
    listas = carregar_listas()
    indice: dict[str, list[dict]] = defaultdict(list)
    medicamentos = carregar_medicamentos()
    for r in medicamentos:
        resumo = resumo_medicamento(r, listas)
        adicionar(indice, resumo["produto"], resumo)
        adicionar(indice, resumo["principio_ativo"], resumo)
    ifas_payload = json.loads(IFA.read_text(encoding="utf-8"))
    ifas = ifas_payload.get("registros", [])
    for r in ifas:
        resumo = resumo_ifa(r, listas)
        adicionar(indice, resumo["ifa"], resumo)

    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True, exist_ok=True)
    total = 0
    maior = 0
    for prefixo in sorted(indice):
        itens = deduplicar_e_ordenar(indice[prefixo])
        total += len(itens)
        bruto = json.dumps({"registros": itens}, ensure_ascii=False, separators=(",", ":"))
        maior = max(maior, len(bruto.encode("utf-8")))
        (OUT / f"{prefixo}.json").write_text(bruto, encoding="utf-8")

    listas_manifest = json.loads(LISTAS_MANIFEST.read_text(encoding="utf-8"))
    agora = datetime.now(timezone.utc).isoformat()
    manifest = {
        "versao_esquema": 1,
        "status": "ok",
        "gerado_em": agora,
        "pasta": "indices/nome_medicamentos",
        "fragmentacao": "três primeiras letras normalizadas do termo pesquisável",
        "caracteres_minimos": 3,
        "limite_sugerido": 20,
        "registros_indice": total,
        "fragmentos": len(indice),
        "maior_fragmento_bytes": maior,
        "fontes": {
            "medicamentos": "dados/medicamentos/",
            "ifa": "dados/ifa/registros.json",
            "listas_portaria344": "dados/controlados_portaria344/listas.json",
            "norma_listas": listas_manifest.get("norma_base"),
            "atualizacao_listas": listas_manifest.get("norma_fonte"),
        },
        "regra_portaria344": (
            "Indicação exibida somente por correspondência nominal exata do princípio ativo ou IFA "
            "contra a base local das listas. Não inferir por nome comercial, classe terapêutica, trecho, sal ou derivado."
        ),
        "limitacao_ifa": "A visão de IFA é a exportação pública específica publicada pela Anvisa; ausência no índice não prova ausência de regularização por outra via.",
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    raiz = json.loads(MANIFEST_RAIZ.read_text(encoding="utf-8"))
    raiz.setdefault("bases", {})["indice_nomes_medicamentos"] = {
        **manifest,
        "arquivo_manifesto": "indices/nome_medicamentos/manifest.json",
    }
    MANIFEST_RAIZ.write_text(json.dumps(raiz, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(json.dumps({"medicamentos": len(medicamentos), "ifas": len(ifas), "registros_indice": total, "fragmentos": len(indice), "maior_fragmento_bytes": maior}, ensure_ascii=False))
    return manifest


if __name__ == "__main__":
    gerar()
