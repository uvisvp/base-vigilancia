#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import csv
import hashlib
import io
import json
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

ALIASES = {
    "cnpj": ["cnpj", "cpf_cnpj", "cpf/cnpj", "nr_cnpj", "nu_cnpj", "numero_cnpj"],
    "razao_social": ["razao_social", "razão_social", "nome_empresarial", "nm_razao_social", "razao social", "razão social"],
    "nome_fantasia": ["nome_fantasia", "nm_fantasia", "fantasia", "nome fantasia"],
    "municipio": ["municipio", "município", "nm_municipio", "cidade", "localidade"],
    "uf": ["uf", "sg_uf", "estado", "sigla_uf"],
    "endereco": ["endereco", "endereço", "logradouro", "ds_endereco", "ds_logradouro"],
    "registro_mapa": ["registro", "numero_registro", "número_registro", "nr_registro", "nu_registro", "registro_mapa", "registro_sipeagro", "numero_registro_mapa", "número registro", "registro mapa"],
    "atividade": ["atividade", "ds_atividade", "tipo_atividade"],
    "categoria": ["categoria", "ds_categoria", "tipo", "classe"],
    "produto": ["produto", "nome_produto", "nm_produto", "denominacao", "denominação", "descricao_produto", "descrição_produto"],
    "marca": ["marca", "nome_marca", "nm_marca"],
    "situacao": ["situacao", "situação", "status", "situacao_registro", "situação registro"],
    "data_registro": ["data_registro", "dt_registro", "data_de_registro"],
    "validade": ["validade", "data_validade", "dt_validade", "vencimento"],
}

def agora_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()

def norm_texto(v: Any) -> str:
    if v is None:
        return ""
    s = unicodedata.normalize("NFKD", str(v).strip())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).upper()

def norm_coluna(v: str) -> str:
    s = norm_texto(v).lower()
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")

def so_digitos(v: Any) -> str:
    return re.sub(r"\D", "", "" if v is None else str(v))

def cnpj_valido(v: Any) -> bool:
    cnpj = so_digitos(v)
    if len(cnpj) != 14 or len(set(cnpj)) == 1:
        return False
    def calc(base, pesos):
        soma = sum(int(n) * p for n, p in zip(base, pesos))
        resto = soma % 11
        return "0" if resto < 2 else str(11 - resto)
    d1 = calc(cnpj[:12], [5,4,3,2,9,8,7,6,5,4,3,2])
    d2 = calc(cnpj[:12] + d1, [6,5,4,3,2,9,8,7,6,5,4,3,2])
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
    raise RuntimeError("Encoding da fonte não pôde ser identificado.")

def detectar_dialeto(txt: str) -> csv.Dialect:
    try:
        return csv.Sniffer().sniff(txt[:65536], delimiters=";,|\t,")
    except csv.Error:
        class D(csv.excel):
            delimiter = ";"
        return D

def achar_coluna(fieldnames, aliases):
    mapa = {norm_coluna(c): c for c in fieldnames}
    for alias in aliases:
        k = norm_coluna(alias)
        if k in mapa:
            return mapa[k]
    return None

def baixar():
    r = requests.get(
        URL_FONTE,
        timeout=120,
        headers={"User-Agent": USER_AGENT, "Accept": "text/csv,*/*;q=0.8"},
    )
    r.raise_for_status()
    return r.content, {
        "content_type": r.headers.get("Content-Type"),
        "content_length": r.headers.get("Content-Length"),
        "last_modified": r.headers.get("Last-Modified"),
        "etag": r.headers.get("ETag"),
        "date_http": r.headers.get("Date"),
    }

def escrever_json(path, obj, compacto=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(obj, ensure_ascii=False,
                   indent=None if compacto else 2,
                   separators=(",", ":") if compacto else None),
        encoding="utf-8"
    )

def main():
    print("== MAPA / SIPEAGRO / Vinhos e Bebidas ==")
    bruto, http = baixar()
    if len(bruto) < 100:
        raise RuntimeError("Arquivo oficial retornou conteúdo pequeno demais.")

    hash_fonte = sha256_bytes(bruto)
    manifest_atual = DESTINO / "manifest.json"
    anterior = None

    if manifest_atual.exists():
        anterior = json.loads(manifest_atual.read_text(encoding="utf-8"))
        if anterior.get("sha256") == hash_fonte:
            print(json.dumps({
                "status": "SEM_ALTERACAO",
                "motivo": "SHA-256 da fonte oficial não mudou",
                "sha256": hash_fonte
            }, ensure_ascii=False, indent=2))
            return 0

    encoding = detectar_encoding(bruto)
    texto = bruto.decode(encoding)
    dialeto = detectar_dialeto(texto)

    reader = csv.DictReader(io.StringIO(texto), dialect=dialeto)
    fieldnames = [str(x).strip() for x in (reader.fieldnames or []) if x is not None]
    if not fieldnames:
        raise RuntimeError("CSV oficial sem cabeçalho.")

    detectadas = {k: achar_coluna(fieldnames, v) for k, v in ALIASES.items()}

    registros = []
    linhas_vazias = 0
    for row in reader:
        original = {
            str(k).strip(): ("" if v is None else str(v).strip())
            for k, v in row.items() if k is not None
        }
        if not any(original.values()):
            linhas_vazias += 1
            continue

        rec = {"id": f"bebidas-{len(registros)+1:08d}", "origem": original}

        if detectadas["cnpj"]:
            val = original.get(detectadas["cnpj"], "")
            rec["cnpj_original"] = val
            rec["cnpj_norm"] = so_digitos(val)
            rec["cnpj_valido"] = cnpj_valido(val) if rec["cnpj_norm"] else None

        for alvo in ("razao_social","nome_fantasia","municipio","uf","endereco",
                     "registro_mapa","atividade","categoria","produto","marca",
                     "situacao","data_registro","validade"):
            col = detectadas[alvo]
            if not col:
                continue
            val = original.get(col, "")
            rec[alvo] = val
            if alvo in {"razao_social","nome_fantasia","municipio","categoria","produto","marca"}:
                rec[f"{alvo}_norm"] = norm_texto(val)

        registros.append(rec)

    if not registros:
        raise RuntimeError("Nenhum registro utilizável foi encontrado.")

    total = len(registros)
    stats = {
        "quantidade_registros": total,
        "linhas_vazias_descartadas": linhas_vazias,
        "colunas_origem": fieldnames,
        "colunas_detectadas": detectadas,
    }

    if detectadas["cnpj"]:
        stats["registros_sem_cnpj"] = sum(not r.get("cnpj_norm") for r in registros)
        stats["cnpjs_validos"] = sum(r.get("cnpj_valido") is True for r in registros)
        stats["cnpjs_invalidos"] = sum(bool(r.get("cnpj_norm")) and r.get("cnpj_valido") is False for r in registros)

    if detectadas["registro_mapa"]:
        vals = [norm_texto(r.get("registro_mapa","")) for r in registros]
        cont = Counter(x for x in vals if x)
        stats["numeros_registro_duplicados"] = sum(1 for _, n in cont.items() if n > 1)

    if anterior:
        anterior_qtd = int(anterior.get("quantidade_registros", 0))
        if anterior_qtd > 0 and total < anterior_qtd * 0.80:
            raise RuntimeError(
                f"Queda >20% detectada: anterior={anterior_qtd}, novo={total}. Base publicada preservada."
            )

    temp_root = Path(tempfile.mkdtemp(prefix="mapa-bebidas-"))
    temp_dest = temp_root / "bebidas"
    temp_dest.mkdir(parents=True)

    lote_size = 5000
    lotes = []
    for inicio in range(0, total, lote_size):
        nome = f"{inicio // lote_size + 1:04d}.json"
        bloco = registros[inicio:inicio+lote_size]
        escrever_json(temp_dest/"lotes"/nome, bloco, compacto=True)
        lotes.append({"arquivo": f"lotes/{nome}", "quantidade": len(bloco)})

    indices = {}
    def gerar_indice(nome, pares):
        idx = defaultdict(list)
        for chave, rid in pares:
            if chave:
                idx[chave].append(rid)
        out = dict(sorted(idx.items()))
        arq = f"indice_{nome}.json"
        escrever_json(temp_dest/arq, out, compacto=True)
        indices[nome] = {
            "arquivo": arq,
            "quantidade_chaves": len(out),
            "quantidade_referencias": sum(len(v) for v in out.values()),
        }

    if detectadas["cnpj"]:
        gerar_indice("cnpj", [(r.get("cnpj_norm",""), r["id"]) for r in registros])
    if detectadas["registro_mapa"]:
        gerar_indice("registro", [(norm_texto(r.get("registro_mapa","")), r["id"]) for r in registros])
    if detectadas["razao_social"] or detectadas["nome_fantasia"]:
        pares = []
        for r in registros:
            for campo in ("razao_social_norm","nome_fantasia_norm"):
                if r.get(campo):
                    pares.append((r[campo], r["id"]))
        gerar_indice("nome", pares)
    if detectadas["municipio"] and detectadas["uf"]:
        gerar_indice("municipio_uf", [
            (f"{r.get('municipio_norm','')}|{norm_texto(r.get('uf',''))}", r["id"])
            for r in registros
        ])
    if detectadas["produto"]:
        gerar_indice("produto", [(r.get("produto_norm",""), r["id"]) for r in registros])
    if detectadas["categoria"]:
        gerar_indice("categoria", [(r.get("categoria_norm",""), r["id"]) for r in registros])

    escrever_json(temp_dest/"exemplos.json", registros[:5])
    escrever_json(temp_dest/"schema.json", {
        "versao_schema": SCHEMA_VERSION,
        "campos_origem": fieldnames,
        "mapeamento_detectado": detectadas,
        "regra": "Todas as colunas oficiais são preservadas em origem; campos locais só são criados quando identificados na fonte."
    })
    (temp_dest/"fonte.sha256").write_text(
        f"{hash_fonte}  sipeagrovinhosebebidas.csv\n", encoding="utf-8"
    )

    escrever_json(temp_dest/"manifest.json", {
        "id": "mapa_bebidas",
        "nome_base": "MAPA — SIPEAGRO — Vinhos e Bebidas",
        "orgao": "Ministério da Agricultura e Pecuária — MAPA",
        "fonte": "SIPEAGRO",
        "url_fonte": PAGINA_FONTE,
        "url_arquivo": URL_FONTE,
        "arquivo_origem": "sipeagrovinhosebebidas.csv",
        "formato_origem": "CSV",
        "data_fonte": http.get("last_modified") or "data da fonte não informada",
        "data_download": agora_iso(),
        "data_processamento": agora_iso(),
        "quantidade_registros": total,
        "versao_schema": SCHEMA_VERSION,
        "sha256": hash_fonte,
        "http": http,
        "indices": indices,
        "fragmentacao": {"tipo":"lotes","tamanho_lote":lote_size,"arquivos":lotes},
        "validacoes": stats,
    })

    for p in temp_dest.rglob("*.json"):
        json.loads(p.read_text(encoding="utf-8"))

    ids = {r["id"] for r in registros}
    for nome, meta in indices.items():
        idx = json.loads((temp_dest/meta["arquivo"]).read_text(encoding="utf-8"))
        for refs in idx.values():
            for rid in refs:
                if rid not in ids:
                    raise RuntimeError(f"Referência órfã no índice {nome}: {rid}")

    DESTINO.parent.mkdir(parents=True, exist_ok=True)
    backup = DESTINO.with_name(DESTINO.name + ".bak")
    if backup.exists():
        shutil.rmtree(backup)
    if DESTINO.exists():
        DESTINO.rename(backup)

    try:
        shutil.copytree(temp_dest, DESTINO)
    except Exception:
        if DESTINO.exists():
            shutil.rmtree(DESTINO)
        if backup.exists():
            backup.rename(DESTINO)
        raise
    else:
        if backup.exists():
            shutil.rmtree(backup)

    shutil.rmtree(temp_root)

    print(json.dumps({
        "status":"OK",
        "quantidade_registros": total,
        "colunas_detectadas": detectadas,
        "indices": indices,
        "sha256": hash_fonte,
        "destino": str(DESTINO),
    }, ensure_ascii=False, indent=2))
    return 0

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERRO SEGURO: {exc}", file=sys.stderr)
        raise
