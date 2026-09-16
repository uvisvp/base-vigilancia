#!/usr/bin/env python3
"""Gera índices leves separados para busca por nome de medicamento e de IFA.

Medicamentos são indexados por nome comercial, pela expressão completa de princípio
ativo e por cada componente nominal de associações. Assim, uma associação como
"losartan potássico, hidroclorotiazida" pode ser localizada tanto por "losartan"
quanto por "hidroclorotiazida", sem carregar a base completa no navegador.

IFA é mantido em índice próprio. A situação regulatória só é publicada quando a
fonte de IFA trouxer esse campo; não há inferência de "ativo/inativo".

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
OUT_MED = Path("dados/indices/nome_medicamentos")
OUT_IFA = Path("dados/indices/nome_ifas")
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


def componentes(v: object, *, aceitar_virgula: bool = True) -> list[str]:
    """Separa componentes nominais de uma lista/associação, preservando a ordem."""
    base = texto(v)
    if not base:
        return []
    if aceitar_virgula:
        partes = re.split(r"\s*(?:[;,]|\+)\s*", base)
    else:
        partes = re.split(r"\s*\+\s*", base)

    vistos: set[str] = set()
    out: list[str] = []
    for parte in partes:
        parte = texto(parte)
        n = normalizar(parte)
        if len(n.replace(" ", "")) < 3 or n in vistos:
            continue
        vistos.add(n)
        out.append(parte)
    return out


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
    """Compara a expressão e cada componente nominal, sempre por igualdade exata."""
    base = texto(principio)
    candidatos = [base, *componentes(base)]
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
        "situacao": texto(r.get("situacao")),
        "listas_portaria344": listas_confirmadas(ifa, listas),
    }


def termos_medicamento(resumo: dict) -> list[str]:
    """Termos pesquisáveis: produto, fórmula completa e cada componente."""
    termos = [
        texto(resumo.get("produto")),
        texto(resumo.get("principio_ativo")),
        *componentes(resumo.get("principio_ativo")),
    ]

    # Alguns registros antigos têm o princípio ativo vazio, mas o próprio nome
    # genérico do produto explicita a associação com "+".
    produto = texto(resumo.get("produto"))
    if "+" in produto:
        termos.extend(componentes(produto, aceitar_virgula=False))

    vistos: set[str] = set()
    final: list[str] = []
    for termo in termos:
        n = normalizar(termo)
        if len(n.replace(" ", "")) < 3 or n in vistos:
            continue
        vistos.add(n)
        final.append(termo)
    return final


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
    for item in sorted(
        itens,
        key=lambda x: (
            x["termo"],
            x["tipo"],
            x.get("produto", x.get("ifa", "")),
            x.get("registro", x.get("processo_anvisa", "")),
        ),
    ):
        identidade = "|".join([
            item.get("tipo", ""),
            item.get("termo", ""),
            item.get("registro", ""),
            item.get("processo", ""),
            item.get("processo_anvisa", ""),
            item.get("produto", ""),
            item.get("ifa", ""),
        ])
        if identidade not in vistos:
            vistos.add(identidade)
            final.append(item)
    return final


def escrever_indice(indice: dict[str, list[dict]], pasta: Path) -> dict[str, int]:
    if pasta.exists():
        shutil.rmtree(pasta)
    pasta.mkdir(parents=True, exist_ok=True)

    total = 0
    maior = 0
    for prefixo in sorted(indice):
        itens = deduplicar_e_ordenar(indice[prefixo])
        total += len(itens)
        bruto = json.dumps({"registros": itens}, ensure_ascii=False, separators=(",", ":"))
        maior = max(maior, len(bruto.encode("utf-8")))
        (pasta / f"{prefixo}.json").write_text(bruto, encoding="utf-8")

    return {
        "registros_indice": total,
        "fragmentos": len(indice),
        "maior_fragmento_bytes": maior,
    }


def gerar() -> dict:
    if not MEDICAMENTOS.exists() or not IFA.exists() or not LISTAS.exists():
        raise RuntimeError("Execute após gerar medicamentos, IFA e listas da Portaria 344.")

    listas = carregar_listas()
    indice_med: dict[str, list[dict]] = defaultdict(list)
    indice_ifa: dict[str, list[dict]] = defaultdict(list)

    medicamentos = carregar_medicamentos()
    for r in medicamentos:
        resumo = resumo_medicamento(r, listas)
        for termo in termos_medicamento(resumo):
            adicionar(indice_med, termo, resumo)

    ifas_payload = json.loads(IFA.read_text(encoding="utf-8"))
    ifas = ifas_payload.get("registros", [])
    for r in ifas:
        resumo = resumo_ifa(r, listas)
        adicionar(indice_ifa, resumo["ifa"], resumo)

    met_med = escrever_indice(indice_med, OUT_MED)
    met_ifa = escrever_indice(indice_ifa, OUT_IFA)

    listas_manifest = json.loads(LISTAS_MANIFEST.read_text(encoding="utf-8"))
    agora = datetime.now(timezone.utc).isoformat()
    situacao_ifa_disponivel = any(texto(r.get("situacao")) for r in ifas)

    comum = {
        "versao_esquema": 2,
        "status": "ok",
        "gerado_em": agora,
        "fragmentacao": "três primeiras letras normalizadas do termo pesquisável",
        "caracteres_minimos": 3,
        "limite_sugerido": 20,
        "listas_portaria344": "dados/controlados_portaria344/listas.json",
        "norma_listas": listas_manifest.get("norma_base"),
        "atualizacao_listas": listas_manifest.get("norma_fonte"),
        "regra_portaria344": (
            "Indicação exibida somente por correspondência nominal exata do princípio ativo ou IFA "
            "contra a base local das listas. Não inferir por nome comercial, classe terapêutica, trecho, sal ou derivado."
        ),
    }

    manifest_med = {
        **comum,
        **met_med,
        "tipo": "medicamento",
        "pasta": "indices/nome_medicamentos",
        "fonte": "dados/medicamentos/",
        "termos_indexados": [
            "nome do produto",
            "expressão completa do princípio ativo",
            "cada componente nominal do princípio ativo/associação",
            "componentes explícitos em nomes genéricos com '+' quando o princípio ativo estiver ausente",
        ],
        "situacao_disponivel": True,
    }
    manifest_ifa = {
        **comum,
        **met_ifa,
        "tipo": "ifa",
        "pasta": "indices/nome_ifas",
        "fonte": "dados/ifa/registros.json",
        "termos_indexados": ["nome do IFA"],
        "situacao_disponivel": situacao_ifa_disponivel,
        "limitacao_ifa": (
            "A visão de IFA é a exportação pública específica publicada pela Anvisa; ausência no índice "
            "não prova ausência de regularização por outra via."
        ),
        "limitacao_situacao": (
            "" if situacao_ifa_disponivel else
            "A exportação TA_EXPORT_IFA usada nesta visão não informa situação regulatória. "
            "Não inferir Ativo/Inativo a partir de assunto, processo ou presença na exportação."
        ),
    }

    (OUT_MED / "manifest.json").write_text(
        json.dumps(manifest_med, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )
    (OUT_IFA / "manifest.json").write_text(
        json.dumps(manifest_ifa, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )

    raiz = json.loads(MANIFEST_RAIZ.read_text(encoding="utf-8"))
    bases = raiz.setdefault("bases", {})
    bases["indice_nomes_medicamentos"] = {
        **manifest_med,
        "arquivo_manifesto": "indices/nome_medicamentos/manifest.json",
    }
    bases["indice_nomes_ifas"] = {
        **manifest_ifa,
        "arquivo_manifesto": "indices/nome_ifas/manifest.json",
    }
    MANIFEST_RAIZ.write_text(
        json.dumps(raiz, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )

    resumo_saida = {
        "medicamentos": len(medicamentos),
        "ifas": len(ifas),
        "medicamentos_indice": met_med["registros_indice"],
        "ifas_indice": met_ifa["registros_indice"],
        "fragmentos_medicamentos": met_med["fragmentos"],
        "fragmentos_ifas": met_ifa["fragmentos"],
        "maior_fragmento_medicamentos_bytes": met_med["maior_fragmento_bytes"],
        "maior_fragmento_ifas_bytes": met_ifa["maior_fragmento_bytes"],
        "situacao_ifa_disponivel": situacao_ifa_disponivel,
    }
    print(json.dumps(resumo_saida, ensure_ascii=False))
    return {"medicamentos": manifest_med, "ifa": manifest_ifa}


if __name__ == "__main__":
    gerar()
