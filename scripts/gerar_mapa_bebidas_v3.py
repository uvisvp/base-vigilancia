#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gerador da base MAPA — SIPEAGRO — Vinhos e Bebidas
Schema 1.2.0

Fonte oficial:
https://dados.agricultura.gov.br/dataset/52a01565-72d6-410e-b21b-64035831a7be/resource/8ef7a4fc-f9d9-495b-b3ae-a2ffe931ff82/download/sipeagrovinhosebebidas.csv

Regras:
- preserva todas as colunas oficiais em `origem`;
- NÃO reconstrói CNPJ/CPF mascarado;
- NÃO cria índice de CNPJ quando a fonte não fornece identificador completo;
- usa o número de registro MAPA como identificador principal;
- normaliza sem destruir o valor oficial;
- publica somente após validação;
- não reescreve a base se fonte e schema não mudaram.
"""

import csv, hashlib, json, re, shutil, sys, tempfile, unicodedata
from collections import defaultdict, Counter
from datetime import datetime, timezone
from pathlib import Path

import requests

URL = "https://dados.agricultura.gov.br/dataset/52a01565-72d6-410e-b21b-64035831a7be/resource/8ef7a4fc-f9d9-495b-b3ae-a2ffe931ff82/download/sipeagrovinhosebebidas.csv"
DEST = Path("dados/mapa/bebidas")
SCHEMA_VERSION = "1.2.0"
LOTE = 5000

COLUNAS_OBRIGATORIAS = [
    "UF",
    "MUNICIPIO",
    "NUMERO_REGISTRO_ESTABELECIMENTO",
    "STATUS_DO_REGISTRO",
    "CPF_CNPJ",
    "RAZAO_SOCIAL",
    "AREA_ATUACAO",
    "ATIVIDADE",
    "CLASSIFICACAO",
]

def agora():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()

def norm_texto(v):
    v = "" if v is None else str(v).strip()
    v = unicodedata.normalize("NFKD", v)
    v = "".join(c for c in v if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", v).upper().strip()

def parcial_norm(v):
    # Mantém apenas dígitos realmente visíveis na fonte.
    # Nunca é tratado como CNPJ/CPF completo.
    return re.sub(r"\D", "", "" if v is None else str(v))

def ler_csv(raw):
    try:
        txt = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        txt = raw.decode("latin-1")
    try:
        dialect = csv.Sniffer().sniff(txt[:10000], delimiters=";,|\t")
        delim = dialect.delimiter
    except Exception:
        delim = ";"
    return list(csv.DictReader(txt.splitlines(), delimiter=delim))

def add(indice, chave, ref):
    if chave:
        indice[chave].append(ref)

def main():
    print("Baixando fonte oficial MAPA...")
    r = requests.get(URL, timeout=180)
    r.raise_for_status()
    raw = r.content
    fonte_sha = sha256_bytes(raw)

    antigo = DEST / "manifest.json"
    if antigo.exists():
        try:
            m = json.loads(antigo.read_text(encoding="utf-8"))
            if m.get("sha256") == fonte_sha and m.get("versao_schema") == SCHEMA_VERSION:
                print("SEM_ALTERACAO: fonte e schema não mudaram.")
                return 0
        except Exception:
            pass

    rows = ler_csv(raw)
    if not rows:
        raise RuntimeError("Fonte oficial retornou zero registros.")

    campos = list(rows[0].keys())
    faltantes = [c for c in COLUNAS_OBRIGATORIAS if c not in campos]
    if faltantes:
        raise RuntimeError(
            "ALTERACAO_ESTRUTURAL_FONTE: colunas obrigatórias ausentes: "
            + ", ".join(faltantes)
            + " | encontradas: " + ", ".join(campos)
        )

    processados = []
    stats = {
        "identificador_fiscal_mascarado": 0,
        "identificador_fiscal_vazio": 0,
        "identificador_fiscal_completo_detectado": 0,
        "registros_mapa_vazios": 0,
        "registros_mapa_duplicados": 0,
    }

    cont_registros = Counter()

    for i, row in enumerate(rows):
        origem = {k: (v.strip() if isinstance(v, str) else v) for k,v in row.items()}

        fiscal_original = origem.get("CPF_CNPJ", "")
        fiscal_parcial = parcial_norm(fiscal_original)

        if not str(fiscal_original).strip():
            stats["identificador_fiscal_vazio"] += 1
        elif "*" in str(fiscal_original):
            stats["identificador_fiscal_mascarado"] += 1
        else:
            # Detecta apenas para auditoria. Não cria cnpj_norm automaticamente.
            if len(fiscal_parcial) in (11, 14):
                stats["identificador_fiscal_completo_detectado"] += 1

        registro = str(origem.get("NUMERO_REGISTRO_ESTABELECIMENTO", "") or "").strip()
        registro_norm = norm_texto(registro)
        if not registro:
            stats["registros_mapa_vazios"] += 1
        else:
            cont_registros[registro_norm] += 1

        rec = {
            "id": i,
            "cpf_cnpj_original": fiscal_original,
            "cpf_cnpj_parcial_norm": fiscal_parcial,
            "razao_social": origem.get("RAZAO_SOCIAL", ""),
            "razao_social_norm": norm_texto(origem.get("RAZAO_SOCIAL", "")),
            "municipio": origem.get("MUNICIPIO", ""),
            "municipio_norm": norm_texto(origem.get("MUNICIPIO", "")),
            "uf": origem.get("UF", ""),
            "numero_registro_mapa": registro,
            "numero_registro_mapa_norm": registro_norm,
            "situacao": origem.get("STATUS_DO_REGISTRO", ""),
            "situacao_norm": norm_texto(origem.get("STATUS_DO_REGISTRO", "")),
            "area_atuacao": origem.get("AREA_ATUACAO", ""),
            "area_atuacao_norm": norm_texto(origem.get("AREA_ATUACAO", "")),
            "atividade": origem.get("ATIVIDADE", ""),
            "atividade_norm": norm_texto(origem.get("ATIVIDADE", "")),
            "classificacao": origem.get("CLASSIFICACAO", ""),
            "classificacao_norm": norm_texto(origem.get("CLASSIFICACAO", "")),
            "origem": origem,
        }
        processados.append(rec)

    stats["registros_mapa_duplicados"] = sum(1 for _, qtd in cont_registros.items() if qtd > 1)

    tmp_root = Path(tempfile.mkdtemp(prefix="mapa_bebidas_"))
    out = tmp_root / "bebidas"
    (out / "lotes").mkdir(parents=True)

    indices = {
        "registro": defaultdict(list),
        "nome": defaultdict(list),
        "municipio_uf": defaultdict(list),
        "classificacao": defaultdict(list),
        "area_atuacao": defaultdict(list),
        "situacao": defaultdict(list),
        "atividade": defaultdict(list),
    }

    fragmentos = []
    for inicio in range(0, len(processados), LOTE):
        n = inicio // LOTE
        nome = f"lotes/{n:04d}.json"
        bloco = processados[inicio:inicio+LOTE]
        (out / nome).write_text(
            json.dumps(bloco, ensure_ascii=False, separators=(",",":")),
            encoding="utf-8"
        )
        fragmentos.append({"arquivo": nome, "quantidade": len(bloco)})

        for pos, rec in enumerate(bloco):
            ref = [n, pos]
            add(indices["registro"], rec["numero_registro_mapa_norm"], ref)
            add(indices["nome"], rec["razao_social_norm"], ref)
            add(indices["municipio_uf"], f'{rec["municipio_norm"]}|{norm_texto(rec["uf"])}', ref)
            add(indices["classificacao"], rec["classificacao_norm"], ref)
            add(indices["area_atuacao"], rec["area_atuacao_norm"], ref)
            add(indices["situacao"], rec["situacao_norm"], ref)
            add(indices["atividade"], rec["atividade_norm"], ref)

    for nome, idx in indices.items():
        (out / f"indice_{nome}.json").write_text(
            json.dumps(dict(idx), ensure_ascii=False, separators=(",",":")),
            encoding="utf-8"
        )

    schema = {
        "versao_schema": SCHEMA_VERSION,
        "campos_origem": campos,
        "mapeamento": {
            "cpf_cnpj_original": "CPF_CNPJ",
            "cpf_cnpj_parcial_norm": "CPF_CNPJ (somente dígitos visíveis; não é CNPJ/CPF completo)",
            "razao_social": "RAZAO_SOCIAL",
            "municipio": "MUNICIPIO",
            "uf": "UF",
            "numero_registro_mapa": "NUMERO_REGISTRO_ESTABELECIMENTO",
            "situacao": "STATUS_DO_REGISTRO",
            "area_atuacao": "AREA_ATUACAO",
            "atividade": "ATIVIDADE",
            "classificacao": "CLASSIFICACAO",
        },
        "identificador_principal": "numero_registro_mapa",
        "indice_cnpj": False,
        "motivo_sem_indice_cnpj": "A fonte pública fornece CPF/CNPJ mascarado; não é possível consulta exata por CNPJ.",
        "regra": "Todas as colunas oficiais são preservadas em origem; campos ausentes não são inferidos."
    }
    (out / "schema.json").write_text(
        json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    (out / "exemplos.json").write_text(
        json.dumps(processados[:5], ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out / "fonte.sha256").write_text(fonte_sha + "\n", encoding="utf-8")

    manifest = {
        "id": "mapa_bebidas",
        "nome_base": "MAPA — SIPEAGRO — Vinhos e Bebidas — Estabelecimentos",
        "orgao": "Ministério da Agricultura e Pecuária — MAPA",
        "fonte": "Portal de Dados Abertos do MAPA / SIPEAGRO",
        "url_fonte": URL,
        "arquivo_origem": "sipeagrovinhosebebidas.csv",
        "data_fonte": r.headers.get("Last-Modified") or "data da fonte não informada",
        "data_download": agora(),
        "data_processamento": agora(),
        "quantidade_registros": len(processados),
        "versao_schema": SCHEMA_VERSION,
        "sha256": fonte_sha,
        "campos_origem": campos,
        "identificador_principal": "numero_registro_mapa",
        "consulta_exata_por_cnpj": False,
        "limitacao_cnpj": "CPF/CNPJ é mascarado na fonte pública do SIPEAGRO; não reconstruir nem inferir.",
        "fragmentacao": {
            "tamanho_lote": LOTE,
            "fragmentos": fragmentos
        },
        "indices": {
            k: {"arquivo": f"indice_{k}.json", "chaves": len(v)}
            for k,v in indices.items()
        },
        "estatisticas": stats,
        "observacao": (
            "Este recurso contém dados de estabelecimentos de Vinhos e Bebidas. "
            "Não são inferidos produtos, marcas ou outros campos ausentes da fonte."
        )
    }
    (out / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Validação dos JSONs.
    for jf in out.rglob("*.json"):
        json.loads(jf.read_text(encoding="utf-8"))

    # Validação das referências.
    for idx in indices.values():
        for refs in idx.values():
            for lote, pos in refs:
                if lote >= len(fragmentos) or pos >= fragmentos[lote]["quantidade"]:
                    raise RuntimeError("Índice contém referência órfã.")

    # Proteção contra queda brusca de volume.
    if antigo.exists():
        try:
            old = json.loads(antigo.read_text(encoding="utf-8")).get("quantidade_registros", 0)
            if old and len(processados) < old * 0.80:
                raise RuntimeError(f"QUEDA_CRITICA: anterior={old}, novo={len(processados)}")
        except RuntimeError:
            raise
        except Exception:
            pass

    backup = DEST.with_name("bebidas.__backup__")
    if backup.exists():
        shutil.rmtree(backup)
    if DEST.exists():
        DEST.rename(backup)

    try:
        shutil.copytree(out, DEST)
        if backup.exists():
            shutil.rmtree(backup)
    except Exception:
        if DEST.exists():
            shutil.rmtree(DEST)
        if backup.exists():
            backup.rename(DEST)
        raise
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)

    print(f"OK: {len(processados)} registros; schema {SCHEMA_VERSION}")
    print("Identificador principal: numero_registro_mapa")
    print("Índice exato por CNPJ: NÃO (fonte mascarada)")
    print("Índices:", ", ".join(indices))
    return 0

if __name__ == "__main__":
    sys.exit(main())
