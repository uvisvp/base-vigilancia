#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Gerador da base MAPA — SIPEAGRO / Vinhos e Bebidas
Projeto: base-vigilancia

Princípios:
- Fonte oficial MAPA.
- Não presume campos inexistentes.
- Preserva todas as colunas originais da fonte.
- Detecta colunas úteis por aliases conhecidos.
- Só cria índices quando a coluna correspondente é realmente encontrada.
- Falha de forma segura se a estrutura mudar de forma incompatível.
- Não substitui a base publicada antes de concluir todas as validações.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import shutil
import sys
import tempfile
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

URL_FONTE = (
    "https://dados.agricultura.gov.br/dataset/"
    "52a01565-72d6-410e-b21b-64035831a7be/resource/"
    "8ef7a4fc-f9d9-495b-b3ae-a2ffe931ff82/download/"
    "sipeagrovinhosebebidas.csv"
)

PAGINA_FONTE = (
    "https://dados.agricultura.gov.br/dataset/sipeagro/resource/"
    "8ef7a4fc-f9d9-495b-b3ae-a2ffe931ff82"
)

BASE_DIR = Path(__file__).resolve().parents[1]
DESTINO = BASE_DIR / "dados" / "mapa" / "bebidas"
SCHEMA_VERSION = "1.0.0"
USER_AGENT = "base-vigilancia/1.0 (+https://github.com/uvisvp/base-vigilancia)"

# Não são colunas obrigatórias da fonte.
# São apenas aliases usados para descobrir o que a fonte realmente oferece.
ALIASES = {
    "cnpj": [
        "cnpj", "cpf_cnpj", "cpf/cnpj", "nr_cnpj", "nu_cnpj", "numero_cnpj",
    ],
    "razao_social": [
        "razao_social", "razão_social", "nome_empresarial", "nm_razao_social",
        "nm_razao", "razao social", "razão social",
    ],
    "nome_fantasia": [
        "nome_fantasia", "nm_fantasia", "fantasia", "nome fantasia",
    ],
    "municipio": [
        "municipio", "município", "nm_municipio", "cidade", "localidade",
    ],
    "uf": [
        "uf", "sg_uf", "estado", "sigla_uf",
    ],
    "endereco": [
        "endereco", "endereço", "logradouro", "ds_endereco", "ds_logradouro",
    ],
    "registro_mapa": [
        "registro", "numero_registro", "número_registro", "nr_registro",
        "nu_registro", "registro_mapa", "registro_sipeagro",
        "numero_registro_mapa", "número registro", "registro mapa",
    ],
    "atividade": [
        "atividade", "ds_atividade", "tipo_atividade",
    ],
    "categoria": [
        "categoria", "ds_categoria", "tipo", "classe",
    ],
    "produto": [
        "produto", "nome_produto", "nm_produto", "denominacao",
        "denominação", "descricao_produto", "descrição_produto",
    ],
    "marca": [
        "marca", "nome_marca", "nm_marca",
    ],
    "situacao": [
        "situacao", "situação", "status", "situacao_registro", "situação registro",
    ],
    "data_registro": [
        "data_registro", "dt_registro", "data_de_registro",
    ],
    "validade": [
        "validade", "data_validade", "dt_validade", "vencimento",
    ],
}

def utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()

def norm_texto(v: Any) -> str:
    if v is None:
        return ""
    s = str(v).strip()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"\s+", " ", s).upper()
    return s

def norm_coluna(v: str) -> str:
    s = norm_texto(v).lower()
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return s

def so_digitos(v: Any) -> str:
    return re.sub(r"\D", "", "" if v is None else str(v))

def cnpj_valido(v: Any) -> bool:
    cnpj = so_digitos(v)
    if len(cnpj) != 14 or len(set(cnpj)) == 1:
        return False
    def dv(base, pesos):
        soma = sum(int(n) * p for n, p in zip(base, pesos))
        r = soma % 11
        return "0" if r < 2 else str(11 - r)
    d1 = dv(cnpj[:12], [5,4,3,2,9,8,7,6,5,4,3,2])
    d2 = dv(cnpj[:12] + d1, [6,5,4,3,2,9,8,7,6,5,4,3,2])
    return cnpj[-2:] == d1 + d2

def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()

def detectar_encoding(b: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            b.decode(enc)
            return enc
        except UnicodeDecodeError:
            pass
    raise RuntimeError("Não foi possível detectar encoding compatível.")

def detectar_dialeto(txt: str) -> csv.Dialect:
    amostra = txt[:65536]
    try:
        return csv.Sniffer().sniff(amostra, delimiters=";,|\t,")
    except csv.Error:
        class D(csv.excel):
            delimiter = ";"
        return D

def achar_coluna(fieldnames: list[str], aliases: list[str]) -> str | None:
    mapa = {norm_coluna(c): c for c in fieldnames}
    for a in aliases:
        k = norm_coluna(a)
        if k in mapa:
            return mapa[k]
    return None

def baixar() -> tuple[bytes, dict]:
    r = requests.get(
        URL_FONTE,
        timeout=120,
        headers={"User-Agent": USER_AGENT, "Accept": "text/csv,*/*;q=0.8"},
    )
    r.raise_for_status()
    meta = {
        "content_type": r.headers.get("Content-Type"),
        "content_length": r.headers.get("Content-Length"),
        "last_modified": r.headers.get("Last-Modified"),
        "etag": r.headers.get("ETag"),
        "date_http": r.headers.get("Date"),
    }
    return r.content, meta

def main() -> int:
    print("== MAPA / SIPEAGRO / Vinhos e Bebidas ==")
    bruto, http = baixar()

    if len(bruto) < 100:
        raise RuntimeError("Arquivo oficial retornou conteúdo pequeno demais.")

    encoding = detectar_encoding(bruto)
    texto = bruto.decode(encoding)
    dialeto = detectar_dialeto(texto)

    reader = csv.DictReader(io.StringIO(texto), dialect=dialeto)
    fieldnames = reader.fieldnames or []
    fieldnames = [str(x).strip() for x in fieldnames if x is not None]

    if not fieldnames:
        raise RuntimeError("CSV sem cabeçalho.")

    # Proteção estrutural: não exigimos nomes inventados,
    # mas exigimos que exista ao menos uma coluna e registros utilizáveis.
    detectadas = {
        alvo: achar_coluna(fieldnames, aliases)
        for alvo, aliases in ALIASES.items()
    }

    registros = []
    linhas_vazias = 0
    for i, row in enumerate(reader, start=2):
        original = {str(k).strip(): ("" if v is None else str(v).strip())
                    for k, v in row.items() if k is not None}

        if not any(original.values()):
            linhas_vazias += 1
            continue

        rec = {
            "id": f"bebidas-{len(registros)+1:08d}",
            "origem": original,
        }

        # Campos locais são criados somente quando a coluna correspondente existe.
        if detectadas["cnpj"]:
            val = original.get(detectadas["cnpj"], "")
            rec["cnpj_original"] = val
            rec["cnpj_norm"] = so_digitos(val)
            rec["cnpj_valido"] = cnpj_valido(val) if rec["cnpj_norm"] else None

        for alvo in (
            "razao_social", "nome_fantasia", "municipio", "uf", "endereco",
            "registro_mapa", "atividade", "categoria", "produto", "marca",
            "situacao", "data_registro", "validade"
        ):
            col = detectadas[alvo]
            if col:
                val = original.get(col, "")
                rec[alvo] = val
                if alvo in {"razao_social", "nome_fantasia", "municipio",
                            "categoria", "produto", "marca"}:
                    rec[alvo + "_norm"] = norm_texto(val)

        registros.append(rec)

    if not registros:
        raise RuntimeError("Nenhum registro utilizável foi encontrado.")

    # Validações
    total = len(registros)
    stats = {
        "quantidade_registros": total,
        "linhas_vazias_descartadas": linhas_vazias,
        "colunas_origem": fieldnames,
        "colunas_detectadas": detectadas,
    }

    if detectadas["cnpj"]:
        cnpjs = [r.get("cnpj_norm", "") for r in registros]
        stats["registros_sem_cnpj"] = sum(not x for x in cnpjs)
        stats["cnpjs_validos"] = sum(r.get("cnpj_valido") is True for r in registros)
        stats["cnpjs_invalidos"] = sum(
            bool(r.get("cnpj_norm")) and r.get("cnpj_valido") is False
            for r in registros
        )

    if detectadas["registro_mapa"]:
        vals = [norm_texto(r.get("registro_mapa", "")) for r in registros]
        c = Counter(x for x in vals if x)
        stats["registros_mapa_duplicados"] = sum(1 for _, n in c.items() if n > 1)

    # Diretório temporário: só substitui o publicado ao final.
    temp_root = Path(tempfile.mkdtemp(prefix="mapa-bebidas-"))
    temp_dest = temp_root / "bebidas"
    temp_dest.mkdir(parents=True)

    # Fragmentação por prefixo simples e estável.
    # Banco geral em lotes de 5000 para evitar arquivo gigante.
    lotes_dir = temp_dest / "lotes"
    lotes_dir.mkdir()
    lote_size = 5000
    lotes = []
    for n in range(0, total, lote_size):
        nome = f"{(n//lote_size)+1:04d}.json"
        bloco = registros[n:n+lote_size]
        (lotes_dir / nome).write_text(
            json.dumps(bloco, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8"
        )
        lotes.append({"arquivo": f"lotes/{nome}", "quantidade": len(bloco)})

    indices = {}

    def gerar_indice(nome: str, pares: list[tuple[str, str]]):
        idx = defaultdict(list)
        for chave, rid in pares:
            if chave:
                idx[chave].append(rid)
        out = dict(sorted(idx.items()))
        p = temp_dest / f"indice_{nome}.json"
        p.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")),
                     encoding="utf-8")
        indices[nome] = {
            "arquivo": p.name,
            "quantidade_chaves": len(out),
            "quantidade_referencias": sum(len(v) for v in out.values()),
        }

    if detectadas["cnpj"]:
        gerar_indice("cnpj", [(r.get("cnpj_norm", ""), r["id"]) for r in registros])

    if detectadas["registro_mapa"]:
        gerar_indice(
            "registro",
            [(norm_texto(r.get("registro_mapa", "")), r["id"]) for r in registros]
        )

    if detectadas["razao_social"] or detectadas["nome_fantasia"]:
        pares = []
        for r in registros:
            for campo in ("razao_social_norm", "nome_fantasia_norm"):
                if r.get(campo):
                    pares.append((r[campo], r["id"]))
        gerar_indice("nome", pares)

    if detectadas["municipio"] and detectadas["uf"]:
        gerar_indice(
            "municipio_uf",
            [(f"{r.get('municipio_norm','')}|{norm_texto(r.get('uf',''))}", r["id"])
             for r in registros]
        )

    if detectadas["produto"]:
        gerar_indice(
            "produto",
            [(r.get("produto_norm", ""), r["id"]) for r in registros]
        )

    if detectadas["categoria"]:
        gerar_indice(
            "categoria",
            [(r.get("categoria_norm", ""), r["id"]) for r in registros]
        )

    # Snapshot de exemplos reais, sem escolher por conteúdo.
    exemplos = registros[:5]
    (temp_dest / "exemplos.json").write_text(
        json.dumps(exemplos, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Esquema e relatório técnico
    schema = {
        "versao_schema": SCHEMA_VERSION,
        "campos_origem": fieldnames,
        "mapeamento_detectado": detectadas,
        "campos_locais_condicionais": [
            "cnpj_original", "cnpj_norm", "cnpj_valido",
            "razao_social", "razao_social_norm",
            "nome_fantasia", "nome_fantasia_norm",
            "municipio", "municipio_norm", "uf", "endereco",
            "registro_mapa", "atividade", "categoria", "categoria_norm",
            "produto", "produto_norm", "marca", "marca_norm",
            "situacao", "data_registro", "validade",
        ],
        "observacao": (
            "Campos locais só são criados quando a coluna equivalente existe "
            "na fonte oficial. Todas as colunas originais permanecem em origem."
        ),
    }
    (temp_dest / "schema.json").write_text(
        json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Proveniência
    origem_nome = "sipeagrovinhosebebidas.csv"
    (temp_dest / "fonte.sha256").write_text(
        sha256_bytes(bruto) + "  " + origem_nome + "\n", encoding="utf-8"
    )

    manifest = {
        "id": "mapa_bebidas",
        "nome_base": "MAPA — SIPEAGRO — Vinhos e Bebidas",
        "orgao": "Ministério da Agricultura e Pecuária — MAPA",
        "fonte": "Sistema Integrado de Produtos e Estabelecimentos Agropecuários — SIPEAGRO",
        "url_fonte": PAGINA_FONTE,
        "url_arquivo": URL_FONTE,
        "arquivo_origem": origem_nome,
        "formato_origem": "CSV",
        "encoding_detectado": encoding,
        "delimitador_detectado": dialeto.delimiter,
        "data_fonte": http.get("last_modified") or "data da fonte não informada",
        "data_download": utcnow_iso(),
        "data_processamento": utcnow_iso(),
        "quantidade_registros": total,
        "versao_schema": SCHEMA_VERSION,
        "sha256": sha256_bytes(bruto),
        "http": http,
        "indices": indices,
        "fragmentacao": {
            "tipo": "lotes",
            "tamanho_lote": lote_size,
            "arquivos": lotes,
        },
        "validacoes": stats,
    }
    (temp_dest / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Validação final dos JSONs
    for p in temp_dest.rglob("*.json"):
        json.loads(p.read_text(encoding="utf-8"))

    # Conferência dos índices: todos os IDs devem existir.
    ids = {r["id"] for r in registros}
    for nome, meta in indices.items():
        obj = json.loads((temp_dest / meta["arquivo"]).read_text(encoding="utf-8"))
        for chave, refs in obj.items():
            for rid in refs:
                if rid not in ids:
                    raise RuntimeError(f"Referência órfã no índice {nome}: {rid}")

    # Proteção adicional contra queda abrupta da base já publicada.
    old_manifest = DESTINO / "manifest.json"
    if old_manifest.exists():
        try:
            antigo = json.loads(old_manifest.read_text(encoding="utf-8"))
            anterior = int(antigo.get("quantidade_registros", 0))
            if anterior > 0 and total < anterior * 0.80:
                raise RuntimeError(
                    f"Queda maior que 20%: anterior={anterior}, novo={total}. "
                    "Banco publicado foi preservado."
                )
        except json.JSONDecodeError:
            raise RuntimeError("Manifest anterior inválido; publicação cancelada.")

    # Publicação atômica local
    backup = DESTINO.with_name(DESTINO.name + ".bak")
    if backup.exists():
        shutil.rmtree(backup)
    if DESTINO.exists():
        DESTINO.rename(backup)
    DESTINO.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(temp_dest, DESTINO)

    if backup.exists():
        shutil.rmtree(backup)
    shutil.rmtree(temp_root)

    print(json.dumps({
        "status": "OK",
        "destino": str(DESTINO),
        "quantidade_registros": total,
        "indices": indices,
        "colunas_detectadas": detectadas,
        "sha256": sha256_bytes(bruto),
    }, ensure_ascii=False, indent=2))

    return 0

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:
        print(f"ERRO SEGURO: {e}", file=sys.stderr)
        raise
