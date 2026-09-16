#!/usr/bin/env python3
"""Gera índices leves separados para busca por nome de medicamento e de IFA.

Medicamentos são indexados por nome comercial, pela expressão completa de princípio
ativo e por cada componente nominal de associações. Assim, uma associação como
"losartan potássico, hidroclorotiazida" pode ser localizada tanto por "losartan"
quanto por "hidroclorotiazida", sem carregar a base completa no navegador.

Fragmentos grandes são subdivididos de forma adaptativa. O arquivo das três
primeiras letras vira um pequeno roteador com prévia; conforme o usuário digita
mais letras, a Central carrega apenas o ramo necessário.

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

# Mantém cada download de busca pequeno. Um roteador com prévia substitui
# automaticamente qualquer fragmento que ultrapasse este limite.
LIMITE_FRAGMENTO_BYTES = 450_000
PREVIEW_MAX = 120
MAX_PROFUNDIDADE = 32


def texto(v: object) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()


def normalizar(v: object) -> str:
    v = unicodedata.normalize("NFD", texto(v))
    v = "".join(ch for ch in v if unicodedata.category(ch) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", v.lower()).strip()


def compacto(v: object) -> str:
    return normalizar(v).replace(" ", "")


def chave(v: object) -> str:
    n = compacto(v)
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


def identidade_resultado(item: dict) -> str:
    if item.get("tipo") == "ifa":
        return "|".join([
            "ifa",
            item.get("processo_anvisa", ""),
            item.get("ifa", ""),
            item.get("fabricante_ifa", ""),
        ])
    return "|".join([
        "med",
        item.get("registro", ""),
        item.get("processo", ""),
        item.get("produto", ""),
    ])


def classe_situacao(item: dict) -> str:
    s = normalizar(item.get("situacao"))
    if re.match(r"^(ativo|ativa|valido|valida|vigente)\b", s):
        return "ativo"
    if re.match(r"^(inativo|inativa|cancelado|cancelada|caducado|caducada)\b", s):
        return "inativo"
    return "outro"


def previsualizar(itens: list[dict]) -> list[dict]:
    """Prévia leve e diversificada para buscas ainda amplas (ex.: só 3 letras)."""
    buckets: dict[str, list[dict]] = {"ativo": [], "inativo": [], "outro": []}
    vistos: set[str] = set()
    for item in itens:
        ident = identidade_resultado(item)
        if ident in vistos:
            continue
        vistos.add(ident)
        buckets[classe_situacao(item)].append(item)

    selecionados: list[dict] = []
    por_classe = max(20, PREVIEW_MAX // 3)
    for nome in ("ativo", "inativo", "outro"):
        selecionados.extend(buckets[nome][:por_classe])

    if len(selecionados) < PREVIEW_MAX:
        usados = {identidade_resultado(x) for x in selecionados}
        for item in itens:
            ident = identidade_resultado(item)
            if ident in usados:
                continue
            usados.add(ident)
            selecionados.append(item)
            if len(selecionados) >= PREVIEW_MAX:
                break
    return selecionados[:PREVIEW_MAX]


def serializar(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def caminho_filhos(arquivo: Path) -> Path:
    """abc.json -> abc/ ; abc/a.json -> abc/a/."""
    return arquivo.with_suffix("")


def escrever_no(
    itens: list[dict],
    arquivo: Path,
    pasta_raiz: Path,
    profundidade: int,
    metricas: dict[str, int],
) -> None:
    bruto_folha = serializar({"registros": itens})
    tamanho_folha = len(bruto_folha.encode("utf-8"))

    if tamanho_folha <= LIMITE_FRAGMENTO_BYTES:
        arquivo.parent.mkdir(parents=True, exist_ok=True)
        arquivo.write_text(bruto_folha, encoding="utf-8")
        metricas["arquivos"] += 1
        metricas["maior"] = max(metricas["maior"], tamanho_folha)
        return

    # Se todos os termos terminaram neste ponto (ou atingimos uma salvaguarda),
    # não gravamos um arquivo gigante: publicamos somente a prévia representativa.
    grupos: dict[str, list[dict]] = defaultdict(list)
    if profundidade < MAX_PROFUNDIDADE:
        for item in itens:
            termo = compacto(item.get("termo"))
            if len(termo) > profundidade:
                grupos[termo[profundidade]].append(item)

    filhos: dict[str, str] = {}
    base_filhos = caminho_filhos(arquivo)

    for caractere, grupo in sorted(grupos.items()):
        filho = base_filhos / f"{caractere}.json"
        filhos[caractere] = filho.relative_to(pasta_raiz).as_posix()
        escrever_no(grupo, filho, pasta_raiz, profundidade + 1, metricas)

    payload = {
        "subfragmentado": True,
        "profundidade": profundidade,
        "total_registros": len(itens),
        "registros": previsualizar(itens),
        "fragmentos": filhos,
    }
    bruto = serializar(payload)
    tamanho = len(bruto.encode("utf-8"))
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    arquivo.write_text(bruto, encoding="utf-8")
    metricas["arquivos"] += 1
    metricas["roteadores"] += 1
    metricas["maior"] = max(metricas["maior"], tamanho)


def escrever_indice(indice: dict[str, list[dict]], pasta: Path) -> dict[str, int]:
    if pasta.exists():
        shutil.rmtree(pasta)
    pasta.mkdir(parents=True, exist_ok=True)

    total = 0
    metricas = {"arquivos": 0, "roteadores": 0, "maior": 0}
    for prefixo in sorted(indice):
        itens = deduplicar_e_ordenar(indice[prefixo])
        total += len(itens)
        escrever_no(itens, pasta / f"{prefixo}.json", pasta, 3, metricas)

    return {
        "registros_indice": total,
        "fragmentos": metricas["arquivos"],
        "fragmentos_subdivididos": metricas["roteadores"],
        "maior_fragmento_bytes": metricas["maior"],
        "limite_fragmento_bytes": LIMITE_FRAGMENTO_BYTES,
        "preview_max": PREVIEW_MAX,
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
        "versao_esquema": 3,
        "status": "ok",
        "gerado_em": agora,
        "fragmentacao": (
            "três primeiras letras normalizadas; fragmentos acima do limite são "
            "subdivididos adaptativamente pelas letras seguintes"
        ),
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
        serializar(manifest_med), encoding="utf-8"
    )
    (OUT_IFA / "manifest.json").write_text(
        serializar(manifest_ifa), encoding="utf-8"
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
    MANIFEST_RAIZ.write_text(serializar(raiz), encoding="utf-8")

    resumo_saida = {
        "medicamentos": len(medicamentos),
        "ifas": len(ifas),
        "medicamentos_indice": met_med["registros_indice"],
        "ifas_indice": met_ifa["registros_indice"],
        "fragmentos_medicamentos": met_med["fragmentos"],
        "fragmentos_ifas": met_ifa["fragmentos"],
        "subdivisoes_medicamentos": met_med["fragmentos_subdivididos"],
        "subdivisoes_ifas": met_ifa["fragmentos_subdivididos"],
        "maior_fragmento_medicamentos_bytes": met_med["maior_fragmento_bytes"],
        "maior_fragmento_ifas_bytes": met_ifa["maior_fragmento_bytes"],
        "situacao_ifa_disponivel": situacao_ifa_disponivel,
    }
    print(json.dumps(resumo_saida, ensure_ascii=False))
    return {"medicamentos": manifest_med, "ifa": manifest_ifa}


if __name__ == "__main__":
    gerar()
