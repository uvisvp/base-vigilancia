#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gerador da base MAPA — SIPEAGRO — Vinhos e Bebidas
Schema 1.1.0

Fonte oficial:
https://dados.agricultura.gov.br/dataset/52a01565-72d6-410e-b21b-64035831a7be/resource/8ef7a4fc-f9d9-495b-b3ae-a2ffe931ff82/download/sipeagrovinhosebebidas.csv

Princípios:
- preserva TODAS as colunas oficiais em `origem`;
- normaliza sem destruir o valor original;
- não inventa campos ausentes;
- publica somente após validação;
- não reescreve a base se o SHA-256 da fonte não mudou.
"""

import csv, hashlib, json, re, shutil, sys, tempfile, unicodedata
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import requests

URL = "https://dados.agricultura.gov.br/dataset/52a01565-72d6-410e-b21b-64035831a7be/resource/8ef7a4fc-f9d9-495b-b3ae-a2ffe931ff82/download/sipeagrovinhosebebidas.csv"
DEST = Path("dados/mapa/bebidas")
SCHEMA_VERSION = "1.1.0"
LOTE = 5000

# Agora baseado no schema REAL observado no CSV oficial.
ALIASES = {
    "cnpj": ["CPF_CNPJ"],
    "razao_social": ["RAZAO_SOCIAL"],
    "municipio": ["MUNICIPIO"],
    "uf": ["UF"],
    "registro_mapa": ["NUMERO_REGISTRO_ESTABELECIMENTO"],
    "situacao": ["STATUS_DO_REGISTRO"],
    "area_atuacao": ["AREA_ATUACAO"],
    "atividade": ["ATIVIDADE"],
    "classificacao": ["CLASSIFICACAO"],
}

def agora():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()

def norm_texto(v):
    v = "" if v is None else str(v).strip()
    v = unicodedata.normalize("NFKD", v)
    v = "".join(c for c in v if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", v).upper().strip()

def so_digitos(v):
    return re.sub(r"\D", "", "" if v is None else str(v))

def cnpj_valido(v):
    n = so_digitos(v)
    if len(n) != 14 or len(set(n)) == 1:
        return False
    def dv(base, pesos):
        s = sum(int(a)*b for a,b in zip(base,pesos))
        r = s % 11
        return "0" if r < 2 else str(11-r)
    d1 = dv(n[:12], [5,4,3,2,9,8,7,6,5,4,3,2])
    d2 = dv(n[:12]+d1, [6,5,4,3,2,9,8,7,6,5,4,3,2])
    return n[-2:] == d1+d2

def detectar(campos, nomes):
    for n in nomes:
        if n in campos:
            return n
    return None

def ler_csv(raw):
    # MAPA pode variar BOM/encoding; UTF-8 primeiro, latin-1 como fallback.
    try:
        txt = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        txt = raw.decode("latin-1")
    amostra = txt[:10000]
    try:
        dialect = csv.Sniffer().sniff(amostra, delimiters=";,|\t")
        delim = dialect.delimiter
    except Exception:
        delim = ";"
    return list(csv.DictReader(txt.splitlines(), delimiter=delim))

def refs_add(indice, chave, ref):
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
                print("SEM_ALTERACAO: SHA-256 da fonte oficial não mudou.")
                return 0
        except Exception:
            pass

    rows = ler_csv(raw)
    if not rows:
        raise RuntimeError("Fonte oficial retornou zero registros.")

    campos = list(rows[0].keys())
    esperado = set(sum(ALIASES.values(), []))
    faltantes = sorted(esperado - set(campos))
    # Proteção estrutural: estas 9 colunas foram verificadas no schema real.
    if faltantes:
        raise RuntimeError(
            "ALTERACAO_ESTRUTURAL_FONTE: colunas obrigatórias ausentes: "
            + ", ".join(faltantes)
            + " | encontradas: " + ", ".join(campos)
        )

    mapa = {k: detectar(campos, v) for k,v in ALIASES.items()}
    processados = []
    stats = {
        "cnpj_valido": 0, "cnpj_invalido": 0, "sem_cnpj": 0,
        "registros_mapa_vazios": 0
    }

    for i, row in enumerate(rows):
        origem = {k: (v.strip() if isinstance(v, str) else v) for k,v in row.items()}
        cnpj_original = origem.get(mapa["cnpj"], "")
        cnpj_norm = so_digitos(cnpj_original)
        # CPF_CNPJ pode conter CPF; só tratamos como CNPJ quando tiver 14 dígitos.
        if not cnpj_norm:
            stats["sem_cnpj"] += 1
        elif len(cnpj_norm) == 14:
            stats["cnpj_valido" if cnpj_valido(cnpj_norm) else "cnpj_invalido"] += 1

        registro = origem.get(mapa["registro_mapa"], "")
        if not str(registro).strip():
            stats["registros_mapa_vazios"] += 1

        rec = {
            "id": i,
            "cnpj_original": cnpj_original,
            "cnpj_norm": cnpj_norm,
            "razao_social": origem.get(mapa["razao_social"], ""),
            "razao_social_norm": norm_texto(origem.get(mapa["razao_social"], "")),
            "municipio": origem.get(mapa["municipio"], ""),
            "municipio_norm": norm_texto(origem.get(mapa["municipio"], "")),
            "uf": origem.get(mapa["uf"], ""),
            "numero_registro_mapa": registro,
            "numero_registro_mapa_norm": norm_texto(registro),
            "situacao": origem.get(mapa["situacao"], ""),
            "situacao_norm": norm_texto(origem.get(mapa["situacao"], "")),
            "area_atuacao": origem.get(mapa["area_atuacao"], ""),
            "area_atuacao_norm": norm_texto(origem.get(mapa["area_atuacao"], "")),
            "atividade": origem.get(mapa["atividade"], ""),
            "atividade_norm": norm_texto(origem.get(mapa["atividade"], "")),
            "classificacao": origem.get(mapa["classificacao"], ""),
            "classificacao_norm": norm_texto(origem.get(mapa["classificacao"], "")),
            "origem": origem,
        }
        processados.append(rec)

    tmp_root = Path(tempfile.mkdtemp(prefix="mapa_bebidas_"))
    out = tmp_root / "bebidas"
    (out / "lotes").mkdir(parents=True)

    indices = {
        "cnpj": defaultdict(list),
        "registro": defaultdict(list),
        "nome": defaultdict(list),
        "municipio_uf": defaultdict(list),
        "classificacao": defaultdict(list),
        "area_atuacao": defaultdict(list),
    }

    fragmentos = []
    for inicio in range(0, len(processados), LOTE):
        n = inicio // LOTE
        nome = f"lotes/{n:04d}.json"
        bloco = processados[inicio:inicio+LOTE]
        (out / nome).write_text(json.dumps(bloco, ensure_ascii=False, separators=(",",":")), encoding="utf-8")
        fragmentos.append({"arquivo": nome, "quantidade": len(bloco)})
        for pos, rec in enumerate(bloco):
            ref = [n, pos]
            if len(rec["cnpj_norm"]) == 14:
                refs_add(indices["cnpj"], rec["cnpj_norm"], ref)
            refs_add(indices["registro"], rec["numero_registro_mapa_norm"], ref)
            refs_add(indices["nome"], rec["razao_social_norm"], ref)
            refs_add(indices["municipio_uf"], f'{rec["municipio_norm"]}|{norm_texto(rec["uf"])}', ref)
            refs_add(indices["classificacao"], rec["classificacao_norm"], ref)
            refs_add(indices["area_atuacao"], rec["area_atuacao_norm"], ref)

    for nome, idx in indices.items():
        (out / f"indice_{nome}.json").write_text(
            json.dumps(dict(idx), ensure_ascii=False, separators=(",",":")), encoding="utf-8"
        )

    schema = {
        "versao_schema": SCHEMA_VERSION,
        "campos_origem": campos,
        "mapeamento_detectado": mapa,
        "campos_normalizados": [
            "cnpj_original","cnpj_norm","razao_social","razao_social_norm",
            "municipio","municipio_norm","uf",
            "numero_registro_mapa","numero_registro_mapa_norm",
            "situacao","situacao_norm","area_atuacao","area_atuacao_norm",
            "atividade","atividade_norm","classificacao","classificacao_norm"
        ],
        "regra": "Todas as colunas oficiais são preservadas em origem; normalização nunca substitui o valor oficial."
    }
    (out/"schema.json").write_text(json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8")

    exemplos = processados[:5]
    (out/"exemplos.json").write_text(json.dumps(exemplos, ensure_ascii=False, indent=2), encoding="utf-8")
    (out/"fonte.sha256").write_text(fonte_sha+"\n", encoding="utf-8")

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
        "mapeamento_detectado": mapa,
        "fragmentacao": {"tamanho_lote": LOTE, "fragmentos": fragmentos},
        "indices": {k: {"arquivo": f"indice_{k}.json", "chaves": len(v)} for k,v in indices.items()},
        "estatisticas": stats,
        "observacao": "Este recurso contém dados de estabelecimentos. Não são inferidos produtos, marcas ou outros campos ausentes da fonte."
    }
    (out/"manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    # Validação final dos JSON e das referências.
    for jf in out.rglob("*.json"):
        json.loads(jf.read_text(encoding="utf-8"))
    for idx in indices.values():
        for refs in idx.values():
            for lote, pos in refs:
                if lote >= len(fragmentos) or pos >= fragmentos[lote]["quantidade"]:
                    raise RuntimeError("Índice contém referência órfã.")

    # Proteção contra queda brusca em relação à versão publicada.
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
    print("Índices:", ", ".join(indices))
    return 0

if __name__ == "__main__":
    sys.exit(main())
