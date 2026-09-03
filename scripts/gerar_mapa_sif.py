#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gerador da base MAPA — SIF / DIPOA
Schema 1.0.0

Fontes oficiais MAPA:
1) Estabelecimentos Registrados no SIF
2) Relatório de Estabelecimentos

Objetivo:
- usar a base cadastral principal do SIGSIF;
- enriquecer por SIF com Área/Categoria/Classe do relatório complementar;
- preservar valores originais;
- criar índices leves;
- não perder múltiplas classificações por SIF;
- falhar com segurança se a estrutura oficial mudar.
"""

import csv
import hashlib
import json
import re
import shutil
import sys
import tempfile
import unicodedata
from collections import defaultdict, Counter
from datetime import datetime, timezone
from pathlib import Path

import requests

URL_PRINCIPAL = (
    "https://dados.agricultura.gov.br/dataset/"
    "062166e3-b515-4274-8e7d-68aadd64b820/resource/"
    "97277e92-264a-4dc0-9aea-f87b8ea93798/download/"
    "sigsifestabelecimentosregistradosnosif.csv"
)

URL_RELATORIO = (
    "https://dados.agricultura.gov.br/dataset/"
    "062166e3-b515-4274-8e7d-68aadd64b820/resource/"
    "7d02af92-e3cf-4ae4-af8a-0dad334ffdfa/download/"
    "sigsifrelatorioestabelecimentos.csv"
)

DEST = Path("dados/mapa/sif")
SCHEMA_VERSION = "1.0.1"
LOTE = 5000

# Estrutura observada no diagnóstico oficial.
OBRIGATORIAS_PRINCIPAL = [
    "CPF_CNPJ",
    "RAZAO_SOCIAL",
    "NOME_FANTASIA",
    "NR_SIF",
    "DATA_RESERVA",
    "DT_REGISTRO",
    "NUMERO_PROCESSO",
    "SITUACAO",
    "LOGRADOURO",
    "BAIRRO",
    "CEP",
    "MUNICIPIO",
    "UF",
    "TELEFONE",
    "EMAIL",
    "AREA_CATEGORIA",
    "CATEGORIA_CLASSE",
    "DATA_OCORRENCIA",
]

OBRIGATORIAS_RELATORIO = [
    "AREA",
    "CATEGORIA",
    "CLASSE",
    "SIF",
    "RAZAO_SOCIAL",
    "LOGRADOURO",
    "MUNICIPIO",
    "UF",
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


def so_digitos(v):
    return re.sub(r"\D", "", "" if v is None else str(v))


def cnpj_valido(v):
    n = so_digitos(v)
    if len(n) != 14 or len(set(n)) == 1:
        return False

    def dv(base, pesos):
        s = sum(int(a) * b for a, b in zip(base, pesos))
        r = s % 11
        return "0" if r < 2 else str(11 - r)

    d1 = dv(n[:12], [5,4,3,2,9,8,7,6,5,4,3,2])
    d2 = dv(n[:12] + d1, [6,5,4,3,2,9,8,7,6,5,4,3,2])
    return n[-2:] == d1 + d2


def sif_norm(v):
    # Preserva original, mas o índice usa apenas dígitos quando existirem.
    dig = so_digitos(v)
    return dig if dig else norm_texto(v)


def decode_csv(raw):
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            txt = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise RuntimeError("Encoding não reconhecido.")

    try:
        dialect = csv.Sniffer().sniff(txt[:20000], delimiters=";,|\t")
        sep = dialect.delimiter
    except Exception:
        sep = ";"

    reader = csv.DictReader(txt.splitlines(), delimiter=sep)
    rows = list(reader)
    return rows, (reader.fieldnames or []), enc, sep


def add(idx, chave, ref):
    if chave:
        idx[chave].append(ref)


def main():
    print("Baixando fonte principal SIF...")
    r1 = requests.get(URL_PRINCIPAL, timeout=180)
    r1.raise_for_status()
    raw1 = r1.content

    print("Baixando relatório complementar SIF...")
    r2 = requests.get(URL_RELATORIO, timeout=180)
    r2.raise_for_status()
    raw2 = r2.content

    sha1 = sha256_bytes(raw1)
    sha2 = sha256_bytes(raw2)
    sha_conjunto = hashlib.sha256((sha1 + "|" + sha2).encode("utf-8")).hexdigest()

    antigo = DEST / "manifest.json"
    if antigo.exists():
        try:
            m = json.loads(antigo.read_text(encoding="utf-8"))
            if (
                m.get("sha256_conjunto") == sha_conjunto
                and m.get("versao_schema") == SCHEMA_VERSION
            ):
                print("SEM_ALTERACAO: fontes e schema não mudaram.")
                return 0
        except Exception:
            pass

    principal, campos1, enc1, sep1 = decode_csv(raw1)
    relatorio, campos2, enc2, sep2 = decode_csv(raw2)

    if not principal:
        raise RuntimeError("Fonte principal retornou zero registros.")
    if not relatorio:
        raise RuntimeError("Relatório complementar retornou zero registros.")

    falt1 = [c for c in OBRIGATORIAS_PRINCIPAL if c not in campos1]
    falt2 = [c for c in OBRIGATORIAS_RELATORIO if c not in campos2]

    if falt1:
        raise RuntimeError(
            "ALTERACAO_ESTRUTURAL_FONTE_PRINCIPAL: faltam "
            + ", ".join(falt1)
            + " | encontradas: "
            + ", ".join(campos1)
        )
    if falt2:
        raise RuntimeError(
            "ALTERACAO_ESTRUTURAL_RELATORIO: faltam "
            + ", ".join(falt2)
            + " | encontradas: "
            + ", ".join(campos2)
        )

    # Agrupa classificações complementares por SIF.
    classificacoes_por_sif = defaultdict(list)
    relatorio_sem_sif = 0

    for row in relatorio:
        origem = {k: (v.strip() if isinstance(v, str) else v) for k, v in row.items()}
        chave = sif_norm(origem.get("SIF"))
        if not chave:
            relatorio_sem_sif += 1
            continue

        item = {
            "area": origem.get("AREA", ""),
            "area_norm": norm_texto(origem.get("AREA", "")),
            "categoria": origem.get("CATEGORIA", ""),
            "categoria_norm": norm_texto(origem.get("CATEGORIA", "")),
            "classe": origem.get("CLASSE", ""),
            "classe_norm": norm_texto(origem.get("CLASSE", "")),
            "razao_social_relatorio": origem.get("RAZAO_SOCIAL", ""),
            "logradouro_relatorio": origem.get("LOGRADOURO", ""),
            "municipio_relatorio": origem.get("MUNICIPIO", ""),
            "uf_relatorio": origem.get("UF", ""),
            "origem_relatorio": origem,
        }

        # Evita duplicata idêntica sem esmagar classificações distintas.
        assinatura = json.dumps(
            [item["area_norm"], item["categoria_norm"], item["classe_norm"]],
            ensure_ascii=False,
        )
        existentes = classificacoes_por_sif[chave]
        if not any(x["_assinatura"] == assinatura for x in existentes):
            item["_assinatura"] = assinatura
            existentes.append(item)

    processados = []
    stats = {
        "fonte_principal_registros": len(principal),
        "fonte_relatorio_registros": len(relatorio),
        "relatorio_sem_sif": relatorio_sem_sif,
        "principal_sem_sif": 0,
        "cnpj_valido": 0,
        "cnpj_invalido": 0,
        "sem_cnpj": 0,
        "sif_com_classificacao_complementar": 0,
        "sif_sem_classificacao_complementar": 0,
        "sif_com_multiplas_classificacoes": 0,
    }

    cont_sif = Counter()

    for i, row in enumerate(principal):
        origem = {k: (v.strip() if isinstance(v, str) else v) for k, v in row.items()}

        sif_original = origem.get("NR_SIF", "")
        sifn = sif_norm(sif_original)
        if not sifn:
            stats["principal_sem_sif"] += 1
        else:
            cont_sif[sifn] += 1

        cnpj_original = origem.get("CPF_CNPJ", "")
        cnpjn = so_digitos(cnpj_original)
        if not cnpjn:
            stats["sem_cnpj"] += 1
        elif len(cnpjn) == 14 and cnpj_valido(cnpjn):
            stats["cnpj_valido"] += 1
        elif len(cnpjn) == 14:
            stats["cnpj_invalido"] += 1

        complementares = classificacoes_por_sif.get(sifn, [])
        if complementares:
            stats["sif_com_classificacao_complementar"] += 1
            if len(complementares) > 1:
                stats["sif_com_multiplas_classificacoes"] += 1
        else:
            stats["sif_sem_classificacao_complementar"] += 1

        # Remove campo técnico _assinatura da saída pública.
        class_publicas = [
            {k: v for k, v in c.items() if k != "_assinatura"}
            for c in complementares
        ]

        rec = {
            "id": i,
            "numero_sif": sif_original,
            "numero_sif_norm": sifn,
            "cnpj_original": cnpj_original,
            "cnpj_norm": cnpjn if len(cnpjn) == 14 else "",
            "razao_social": origem.get("RAZAO_SOCIAL", ""),
            "razao_social_norm": norm_texto(origem.get("RAZAO_SOCIAL", "")),
            "nome_fantasia": origem.get("NOME_FANTASIA", ""),
            "nome_fantasia_norm": norm_texto(origem.get("NOME_FANTASIA", "")),
            "numero_processo": origem.get("NUMERO_PROCESSO", ""),
            "situacao": origem.get("SITUACAO", ""),
            "situacao_norm": norm_texto(origem.get("SITUACAO", "")),
            "data_reserva": origem.get("DATA_RESERVA", ""),
            "data_registro": origem.get("DT_REGISTRO", ""),
            "data_ocorrencia": origem.get("DATA_OCORRENCIA", ""),
            "logradouro": origem.get("LOGRADOURO", ""),
            "bairro": origem.get("BAIRRO", ""),
            "cep": origem.get("CEP", ""),
            "municipio": origem.get("MUNICIPIO", ""),
            "municipio_norm": norm_texto(origem.get("MUNICIPIO", "")),
            "uf": origem.get("UF", ""),
            "telefone": origem.get("TELEFONE", ""),
            "email": origem.get("EMAIL", ""),
            "area_categoria_origem": origem.get("AREA_CATEGORIA", ""),
            "categoria_classe_origem": origem.get("CATEGORIA_CLASSE", ""),
            "classificacoes": class_publicas,
            "origem_principal": origem,
        }
        processados.append(rec)

    tmp_root = Path(tempfile.mkdtemp(prefix="mapa_sif_"))
    out = tmp_root / "sif"
    (out / "lotes").mkdir(parents=True)

    indices = {
        "sif": defaultdict(list),
        "cnpj": defaultdict(list),
        "nome": defaultdict(list),
        "municipio_uf": defaultdict(list),
        "situacao": defaultdict(list),
        "area": defaultdict(list),
        "categoria": defaultdict(list),
        "classe": defaultdict(list),
    }

    fragmentos = []

    for inicio in range(0, len(processados), LOTE):
        n = inicio // LOTE
        nome = f"lotes/{n:04d}.json"
        bloco = processados[inicio:inicio + LOTE]

        (out / nome).write_text(
            json.dumps(bloco, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )

        fragmentos.append({"arquivo": nome, "quantidade": len(bloco)})

        for pos, rec in enumerate(bloco):
            ref = [n, pos]

            add(indices["sif"], rec["numero_sif_norm"], ref)
            add(indices["cnpj"], rec["cnpj_norm"], ref)
            add(indices["nome"], rec["razao_social_norm"], ref)
            add(indices["nome"], rec["nome_fantasia_norm"], ref)
            add(
                indices["municipio_uf"],
                f'{rec["municipio_norm"]}|{norm_texto(rec["uf"])}',
                ref,
            )
            add(indices["situacao"], rec["situacao_norm"], ref)

            for c in rec["classificacoes"]:
                add(indices["area"], c["area_norm"], ref)
                add(indices["categoria"], c["categoria_norm"], ref)
                add(indices["classe"], c["classe_norm"], ref)

    for nome, idx in indices.items():
        (out / f"indice_{nome}.json").write_text(
            json.dumps(dict(idx), ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )

    schema = {
        "versao_schema": SCHEMA_VERSION,
        "fonte_principal_campos": campos1,
        "fonte_complementar_campos": campos2,
        "identificador_principal": "numero_sif",
        "campo_identificador_fiscal_origem": "CPF_CNPJ",
        "relacionamento_fontes": "NR_SIF da fonte principal ↔ SIF do relatório complementar",
        "preserva_multiplas_classificacoes": True,
        "campos_normalizados": [
            "numero_sif_norm",
            "cnpj_norm",
            "razao_social_norm",
            "nome_fantasia_norm",
            "municipio_norm",
            "situacao_norm",
            "classificacoes[].area_norm",
            "classificacoes[].categoria_norm",
            "classificacoes[].classe_norm",
        ],
        "regra": (
            "Valores oficiais são preservados. "
            "A fonte complementar enriquece classificação por SIF sem sobrescrever "
            "os campos da fonte cadastral principal."
        ),
    }

    (out / "schema.json").write_text(
        json.dumps(schema, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    (out / "exemplos.json").write_text(
        json.dumps(processados[:5], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    (out / "fonte_principal.sha256").write_text(sha1 + "\n", encoding="utf-8")
    (out / "fonte_relatorio.sha256").write_text(sha2 + "\n", encoding="utf-8")

    duplicados_sif = sum(1 for _, qtd in cont_sif.items() if qtd > 1)

    manifest = {
        "id": "mapa_sif",
        "nome_base": "MAPA — SIF / DIPOA — Estabelecimentos de Produtos de Origem Animal",
        "orgao": "Ministério da Agricultura e Pecuária — MAPA / DIPOA",
        "fontes": [
            {
                "nome": "Estabelecimentos Registrados no SIF",
                "url": URL_PRINCIPAL,
                "arquivo_origem": "sigsifestabelecimentosregistradosnosif.csv",
                "data_fonte": r1.headers.get("Last-Modified") or "data da fonte não informada",
                "sha256": sha1,
                "encoding_detectado": enc1,
                "separador_detectado": sep1,
                "quantidade_registros": len(principal),
            },
            {
                "nome": "Relatório de Estabelecimentos",
                "url": URL_RELATORIO,
                "arquivo_origem": "sigsifrelatorioestabelecimentos.csv",
                "data_fonte": r2.headers.get("Last-Modified") or "data da fonte não informada",
                "sha256": sha2,
                "encoding_detectado": enc2,
                "separador_detectado": sep2,
                "quantidade_registros": len(relatorio),
            },
        ],
        "data_download": agora(),
        "data_processamento": agora(),
        "quantidade_registros": len(processados),
        "versao_schema": SCHEMA_VERSION,
        "sha256_conjunto": sha_conjunto,
        "identificador_principal": "numero_sif",
        "campo_identificador_fiscal_origem": "CPF_CNPJ",
        "duplicados_numero_sif_na_fonte_principal": duplicados_sif,
        "fragmentacao": {
            "tamanho_lote": LOTE,
            "fragmentos": fragmentos,
        },
        "indices": {
            k: {"arquivo": f"indice_{k}.json", "chaves": len(v)}
            for k, v in indices.items()
        },
        "estatisticas": stats,
        "observacao": (
            "Base cadastral principal enriquecida com todas as classificações "
            "Área/Categoria/Classe disponíveis no relatório complementar por SIF. "
            "Resultado vazio significa apenas 'não localizado nesta base'."
        ),
    }

    (out / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
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

    # Queda crítica: não sobrescrever versão anterior em caso de fonte anômala.
    if antigo.exists():
        try:
            old = json.loads(antigo.read_text(encoding="utf-8")).get("quantidade_registros", 0)
            if old and len(processados) < old * 0.80:
                raise RuntimeError(
                    f"QUEDA_CRITICA: anterior={old}, novo={len(processados)}"
                )
        except RuntimeError:
            raise
        except Exception:
            pass

    backup = DEST.with_name("sif.__backup__")
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
    print("Identificador principal: numero_sif")
    print("Índices:", ", ".join(indices))
    print("Classificações complementares preservadas por SIF.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
