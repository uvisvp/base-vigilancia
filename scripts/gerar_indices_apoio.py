#!/usr/bin/env python3
"""Gera dois índices leves de apoio à inspeção.

1. dados/indices/nome_alimentos/ — busca de alimento regularizado por nome do
   produto ou marca. Mesmo formato e fragmentação do índice de nomes de
   medicamentos (três letras; ramos grandes subdivididos pelas letras seguintes).

2. dados/indices/apresentacoes_registro/ — apresentações de medicamento por
   número de registro (9 dígitos), a partir da lista CMED: número de registro
   da apresentação (13 dígitos), descrição, laboratório e EAN. Fragmentado pelos
   4 primeiros dígitos do registro, como dados/medicamentos/.

Nada é inferido: o índice só reproduz campos das bases já publicadas.
Execute após gerar_base.py.
"""
from __future__ import annotations

import json
import re
import shutil
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gerar_indice_nomes_medicamentos import (  # noqa: E402
    LIMITE_FRAGMENTO_BYTES,
    chave,
    escrever_no,
    normalizar,
    serializar,
    texto,
)

ALIMENTOS = Path("dados/alimentos")
CMED = Path("dados/cmed")
OUT_ALI = Path("dados/indices/nome_alimentos")
OUT_APR = Path("dados/indices/apresentacoes_registro")
MANIFEST_RAIZ = Path("dados/manifest.json")


def digitos(v: object) -> str:
    return re.sub(r"\D", "", str(v or ""))


def ler_lista(pasta: Path) -> list[dict]:
    out: list[dict] = []
    for arquivo in sorted(pasta.glob("*.json")):
        dado = json.loads(arquivo.read_text(encoding="utf-8"))
        if isinstance(dado, dict):
            dado = dado.get("registros", [])
        out.extend(dado)
    return out


# ------------------------------------------------------------------ alimentos
def resumo_alimento(r: dict) -> dict:
    """Campos mínimos; o detalhe completo vem de dados/alimentos/ pelo registro."""
    out = {
        "produto": texto(r.get("produto")),
        "registro": texto(r.get("registro")),
        "cnpj": texto(r.get("cnpj")),
        "detentor": texto(r.get("detentor")),
        "categoria": texto(r.get("categoria")),
        "situacao": texto(r.get("situacao")),
    }
    proc = texto(r.get("processo"))
    if proc and proc != out["registro"]:
        out["processo"] = proc
    return out


def marca_limpa(m: str) -> str:
    """Tira anotações como “(CNPJ nº …)” ou “(marca própria de …)”."""
    return texto(re.sub(r"\([^)]*\)", " ", m))


def termos_alimento(r: dict) -> list[tuple[str, str]]:
    """(termo, marca) — marca vazia quando o termo é o nome do produto."""
    termos = [(texto(r.get("produto")), "")]
    termos += [(marca_limpa(m), marca_limpa(m)) for m in re.split(r"\s*;\s*", texto(r.get("marcas")))]
    vistos: set[str] = set()
    final: list[tuple[str, str]] = []
    for t, m in termos:
        n = normalizar(t)
        if len(n.replace(" ", "")) < 3 or n in vistos:
            continue
        vistos.add(n)
        final.append((t, m))
    return final


def ordenar(itens: list[dict]) -> list[dict]:
    vistos: set[str] = set()
    final: list[dict] = []
    ativo = lambda x: 0 if normalizar(x.get("situacao")).startswith("ativ") else 1  # noqa: E731
    for item in sorted(itens, key=lambda x: (x["termo"], ativo(x), x["produto"], x["registro"])):
        ident = "|".join([item["termo"], item["registro"], item.get("processo", "")])
        if ident not in vistos:
            vistos.add(ident)
            final.append(item)
    return final


def gerar_alimentos() -> dict:
    indice: dict[str, list[dict]] = defaultdict(list)
    registros = ler_lista(ALIMENTOS)
    for r in registros:
        resumo = resumo_alimento(r)
        for termo, marca in termos_alimento(r):
            item = dict(resumo)
            if marca:
                item["marca"] = marca
            item["termo"] = normalizar(termo)
            indice[chave(item["termo"])].append(item)

    if OUT_ALI.exists():
        shutil.rmtree(OUT_ALI)
    OUT_ALI.mkdir(parents=True, exist_ok=True)
    metricas = {"arquivos": 0, "roteadores": 0, "maior": 0}
    total = 0
    for prefixo in sorted(indice):
        itens = ordenar(indice[prefixo])
        total += len(itens)
        escrever_no(itens, OUT_ALI / f"{prefixo}.json", OUT_ALI, 3, metricas)

    manifest = {
        "versao_esquema": 1,
        "status": "ok",
        "gerado_em": datetime.now(timezone.utc).isoformat(),
        "tipo": "alimento",
        "pasta": "indices/nome_alimentos",
        "fonte": "dados/alimentos/",
        "fragmentacao": (
            "três primeiras letras normalizadas; fragmentos acima do limite são "
            "subdivididos adaptativamente pelas letras seguintes"
        ),
        "caracteres_minimos": 3,
        "termos_indexados": ["nome do produto", "cada marca informada (sem anotações entre parênteses)"],
        "campos": "produto, registro, processo (quando difere do registro), cnpj, detentor, categoria, situacao, marca (quando o termo é marca), termo",
        "alimentos": len(registros),
        "registros_indice": total,
        "fragmentos": metricas["arquivos"],
        "fragmentos_subdivididos": metricas["roteadores"],
        "maior_fragmento_bytes": metricas["maior"],
        "limite_fragmento_bytes": LIMITE_FRAGMENTO_BYTES,
        "limitacao": (
            "Abrange os alimentos com registro ou notificação na exportação pública da Anvisa. "
            "Produtos dispensados de registro não constam; ausência no índice não prova irregularidade."
        ),
    }
    (OUT_ALI / "manifest.json").write_text(serializar(manifest), encoding="utf-8")
    return manifest


# -------------------------------------------------------------- apresentações
def gerar_apresentacoes() -> dict:
    por_registro: dict[str, dict[str, dict]] = defaultdict(dict)
    for arquivo in sorted(CMED.glob("*.json")):
        dado = json.loads(arquivo.read_text(encoding="utf-8"))
        linhas = [x for v in dado.values() for x in v] if isinstance(dado, dict) else dado
        for r in linhas:
            reg = digitos(r.get("registro"))
            ra = digitos(r.get("registro_apresentacao"))
            if len(reg) != 9:
                continue
            chave_apr = ra or normalizar(r.get("apresentacao"))
            atual = por_registro[reg].get(chave_apr)
            eans = [digitos(e) for e in (r.get("eans") or []) if digitos(e)]
            if atual:
                atual["eans"] = sorted(set(atual["eans"]) | set(eans))
                continue
            por_registro[reg][chave_apr] = {
                "registro_apresentacao": ra,
                "apresentacao": texto(r.get("apresentacao")),
                "produto": texto(r.get("produto")),
                "laboratorio": texto(r.get("laboratorio")),
                "eans": sorted(set(eans)),
            }

    if OUT_APR.exists():
        shutil.rmtree(OUT_APR)
    OUT_APR.mkdir(parents=True, exist_ok=True)
    fragmentos: dict[str, dict[str, list[dict]]] = defaultdict(dict)
    for reg, aps in por_registro.items():
        fragmentos[reg[:4]][reg] = sorted(aps.values(), key=lambda a: (a["registro_apresentacao"], a["apresentacao"]))
    maior = 0
    for pref, conteudo in sorted(fragmentos.items()):
        bruto = serializar(dict(sorted(conteudo.items())))
        maior = max(maior, len(bruto.encode("utf-8")))
        (OUT_APR / f"{pref}.json").write_text(bruto, encoding="utf-8")

    manifest = {
        "versao_esquema": 1,
        "status": "ok",
        "gerado_em": datetime.now(timezone.utc).isoformat(),
        "pasta": "indices/apresentacoes_registro",
        "fonte": "dados/cmed/ (lista de preços CMED)",
        "fragmentacao": "4 primeiros dígitos do registro do medicamento (9 dígitos)",
        "formato": "{registro: [{registro_apresentacao, apresentacao, produto, laboratorio, eans}]}",
        "registros": len(por_registro),
        "apresentacoes": sum(len(v) for v in por_registro.values()),
        "fragmentos": len(fragmentos),
        "maior_fragmento_bytes": maior,
        "limitacao": (
            "A CMED só lista apresentações com preço aprovado. Medicamentos isentos de preço "
            "(p. ex. alguns notificados e fitoterápicos) podem não ter apresentação no índice."
        ),
    }
    (OUT_APR / "manifest.json").write_text(serializar(manifest), encoding="utf-8")
    return manifest


def gerar() -> None:
    if not ALIMENTOS.exists() or not CMED.exists():
        raise RuntimeError("Execute após gerar_base.py (alimentos e CMED).")
    ali = gerar_alimentos()
    apr = gerar_apresentacoes()
    raiz = json.loads(MANIFEST_RAIZ.read_text(encoding="utf-8"))
    bases = raiz.setdefault("bases", {})
    bases["indice_nomes_alimentos"] = {**ali, "arquivo_manifesto": "indices/nome_alimentos/manifest.json"}
    bases["indice_apresentacoes_registro"] = {**apr, "arquivo_manifesto": "indices/apresentacoes_registro/manifest.json"}
    MANIFEST_RAIZ.write_text(serializar(raiz), encoding="utf-8")
    print(json.dumps({
        "alimentos": ali["alimentos"], "alimentos_indice": ali["registros_indice"],
        "fragmentos_alimentos": ali["fragmentos"], "maior_alimentos_bytes": ali["maior_fragmento_bytes"],
        "registros_com_apresentacao": apr["registros"], "apresentacoes": apr["apresentacoes"],
        "fragmentos_apresentacoes": apr["fragmentos"], "maior_apresentacoes_bytes": apr["maior_fragmento_bytes"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    gerar()
