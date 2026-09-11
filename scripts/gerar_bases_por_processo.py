#!/usr/bin/env python3
"""Gera visões por processo das bases de saneantes e medicamentos.

As bases históricas permanecem fragmentadas por registro para preservar
compatibilidade. Estas visões incluem também produtos sem número de registro,
como saneantes notificados, e permitem consulta direta pelo processo Anvisa.
"""

from collections import defaultdict
from datetime import datetime, timezone
import csv
import json

import gerar_base as gb


def primeira_coluna(campos, candidatos):
    return gb.achar_coluna(campos, candidatos)


def metadados(url, total, fragmentos, maior, sem_registro):
    meta = gb.metadados_base(url, total, fragmentos, 3, maior)
    meta.update({
        "chave": "processo",
        "fragmentacao": "dígitos 6 a 8 do processo normalizado",
        "inclui_sem_registro": True,
        "processos_sem_registro": sem_registro,
    })
    return meta


def gerar_medicamentos_processos():
    arquivo = gb.baixar_csv(gb.URL_MEDICAMENTOS, "anvisa_medicamentos_processos_")
    try:
        encoding, delimitador = gb.detectar_configuracao(arquivo)
        grupos = defaultdict(list)
        total = 0
        sem_registro = 0

        with arquivo.open("r", encoding=encoding, errors="replace", newline="") as f:
            leitor = csv.DictReader(f, delimiter=delimitador)
            if not leitor.fieldnames:
                raise RuntimeError("CSV de medicamentos sem cabeçalho.")

            col_processo = primeira_coluna(leitor.fieldnames, ["NUMERO_PROCESSO", "NU_PROCESSO", "PROCESSO"])
            col_registro = primeira_coluna(leitor.fieldnames, ["NUMERO_REGISTRO_PRODUTO", "NUMERO_REGISTRO", "REGISTRO_PRODUTO", "NU_REGISTRO_PRODUTO", "REGISTRO"])
            col_produto = primeira_coluna(leitor.fieldnames, ["NOME_PRODUTO", "NO_PRODUTO", "PRODUTO"])
            col_principio = primeira_coluna(leitor.fieldnames, ["PRINCIPIO_ATIVO", "PRINCÍPIO_ATIVO"])
            col_empresa = primeira_coluna(leitor.fieldnames, ["EMPRESA_DETENTORA_REGISTRO", "EMPRESA_DETENTORA", "DETENTOR_REGISTRO", "RAZAO_SOCIAL", "NO_RAZAO_SOCIAL_EMPRESA"])
            col_cnpj = primeira_coluna(leitor.fieldnames, ["CNPJ_EMPRESA", "CNPJ_DETENTOR", "NU_CNPJ_EMPRESA", "CNPJ"])
            col_categoria = primeira_coluna(leitor.fieldnames, ["CATEGORIA_REGULATORIA", "CATEGORIA_REGULATÓRIA", "CATEGORIA"])
            col_classe = primeira_coluna(leitor.fieldnames, ["CLASSE_TERAPEUTICA", "CLASSE_TERAPÊUTICA"])
            col_vencimento = primeira_coluna(leitor.fieldnames, ["DATA_VENCIMENTO_REGISTRO", "VENCIMENTO_REGISTRO", "VENCIMENTO"])
            col_situacao = primeira_coluna(leitor.fieldnames, ["SITUACAO_REGISTRO", "SITUACAO", "STATUS"])

            if not col_processo or not col_produto:
                raise RuntimeError("Não foi possível localizar processo e produto na base de medicamentos.")

            for linha in leitor:
                processo = gb.somente_numeros(linha.get(col_processo, ""))
                produto = gb.texto(linha.get(col_produto, ""))
                if not processo or not produto:
                    continue

                registro = gb.somente_numeros(linha.get(col_registro, "")) if col_registro else ""
                if not registro:
                    sem_registro += 1

                item = {
                    "processo": processo,
                    "registro": registro,
                    "produto": produto,
                }
                if col_principio:
                    item["principio_ativo"] = gb.texto(linha.get(col_principio, ""))
                if col_empresa:
                    item["detentor"] = gb.texto(linha.get(col_empresa, ""))
                if col_cnpj:
                    item["cnpj"] = gb.somente_numeros(linha.get(col_cnpj, ""))
                if col_categoria:
                    item["categoria"] = gb.texto(linha.get(col_categoria, ""))
                if col_classe:
                    item["classe_terapeutica"] = gb.texto(linha.get(col_classe, ""))
                if col_vencimento:
                    item["vencimento"] = gb.texto(linha.get(col_vencimento, ""))
                if col_situacao:
                    item["situacao"] = gb.texto(linha.get(col_situacao, ""))

                item = gb.limpar_json(item)
                grupos[gb.prefixo_processo(processo)].append(item)
                total += 1

        if total < 1000:
            raise RuntimeError(f"Visão por processo de medicamentos gerou apenas {total} registros.")

        maior = gb.gravar_fragmentos(gb.DADOS / "medicamentos_processos", grupos)
        print("medicamentos_processos:", total, "registros |", len(grupos), "fragmentos |", sem_registro, "sem registro | maior", f"{maior / 1024:.0f} KB")
        return metadados(gb.URL_MEDICAMENTOS, total, len(grupos), maior, sem_registro)
    finally:
        arquivo.unlink(missing_ok=True)


def gerar_saneantes_processos():
    arquivo = gb.baixar_csv(gb.URL_SANEANTES, "anvisa_saneantes_processos_")
    try:
        encoding, delimitador = gb.detectar_configuracao(arquivo)
        grupos = defaultdict(list)
        total = 0
        sem_registro = 0

        with arquivo.open("r", encoding=encoding, errors="replace", newline="") as f:
            leitor = csv.DictReader(f, delimiter=delimitador)
            if not leitor.fieldnames:
                raise RuntimeError("CSV de saneantes sem cabeçalho.")

            col_processo = primeira_coluna(leitor.fieldnames, ["NU_PROCESSO", "NUMERO_PROCESSO", "PROCESSO"])
            col_registro = primeira_coluna(leitor.fieldnames, ["NU_REGISTRO_PRODUTO", "NUMERO_REGISTRO_PRODUTO", "NUMERO_REGISTRO", "REGISTRO", "NUM_REGISTRO"])
            col_produto = primeira_coluna(leitor.fieldnames, ["NO_PRODUTO", "NOME_PRODUTO", "PRODUTO", "NOME_COMERCIAL"])
            col_empresa = primeira_coluna(leitor.fieldnames, ["NO_RAZAO_SOCIAL_EMPRESA", "RAZAO_SOCIAL", "EMPRESA", "DETENTOR"])
            col_cnpj = primeira_coluna(leitor.fieldnames, ["NU_CNPJ_EMPRESA", "CNPJ", "CNPJ_EMPRESA"])
            col_categoria = primeira_coluna(leitor.fieldnames, ["NO_CATEGORIA_PRODUTO", "DS_CATEGORIA_PRODUTO", "CATEGORIA", "TIPO_PRODUTO", "CLASSE_PRODUTO"])
            col_situacao = primeira_coluna(leitor.fieldnames, ["ST_PRODUTO_ATIVO", "ST_SITUACAO_PRODUTO", "SITUACAO", "STATUS"])
            col_vencimento = primeira_coluna(leitor.fieldnames, ["DT_VENCIMENTO_PRODUTO", "DT_VENCIMENTO", "VALIDADE", "DATA_VENCIMENTO", "VENCIMENTO"])
            col_registrado = primeira_coluna(leitor.fieldnames, ["IS_REGISTRADO", "ST_REGISTRADO", "REGISTRADO"])
            col_marca = primeira_coluna(leitor.fieldnames, ["NO_MARCA", "MARCA"])
            col_tipo_peticao = primeira_coluna(leitor.fieldnames, ["DS_TIPO_PETICAO", "TIPO_PETICAO"])
            col_atualizacao = primeira_coluna(leitor.fieldnames, ["DT_ATUALIZACAO", "DATA_ATUALIZACAO"])

            if not col_processo or not col_produto:
                raise RuntimeError("Não foi possível localizar processo e produto na base de saneantes.")

            for linha in leitor:
                processo = gb.somente_numeros(linha.get(col_processo, ""))
                produto = gb.texto(linha.get(col_produto, ""))
                if not processo or not produto:
                    continue

                registro = gb.somente_numeros(linha.get(col_registro, "")) if col_registro else ""
                if not registro:
                    sem_registro += 1

                item = {
                    "processo": processo,
                    "registro": registro,
                    "produto": produto,
                }
                if col_empresa:
                    item["detentor"] = gb.texto(linha.get(col_empresa, ""))
                if col_cnpj:
                    item["cnpj"] = gb.somente_numeros(linha.get(col_cnpj, ""))
                if col_categoria:
                    item["categoria"] = gb.texto(linha.get(col_categoria, ""))
                if col_situacao:
                    item["situacao"] = gb.texto(linha.get(col_situacao, ""))
                if col_vencimento:
                    item["vencimento"] = gb.texto(linha.get(col_vencimento, ""))
                if col_registrado:
                    item["registrado"] = gb.texto(linha.get(col_registrado, ""))
                if col_marca:
                    item["marca"] = gb.texto(linha.get(col_marca, ""))
                if col_tipo_peticao:
                    item["tipo_peticao"] = gb.texto(linha.get(col_tipo_peticao, ""))
                if col_atualizacao:
                    item["atualizado_em"] = gb.texto(linha.get(col_atualizacao, ""))

                item = gb.limpar_json(item)
                grupos[gb.prefixo_processo(processo)].append(item)
                total += 1

        if total < 10000:
            raise RuntimeError(f"Visão por processo de saneantes gerou apenas {total} registros.")

        maior = gb.gravar_fragmentos(gb.DADOS / "saneantes_processos", grupos)
        print("saneantes_processos:", total, "registros |", len(grupos), "fragmentos |", sem_registro, "sem registro | maior", f"{maior / 1024:.0f} KB")
        return metadados(gb.URL_SANEANTES, total, len(grupos), maior, sem_registro)
    finally:
        arquivo.unlink(missing_ok=True)


def atualizar_manifesto(novas_bases):
    caminho = gb.DADOS / "manifest.json"
    manifesto = {}
    if caminho.exists():
        with caminho.open("r", encoding="utf-8") as f:
            manifesto = json.load(f)

    manifesto.setdefault("bases", {}).update(novas_bases)
    manifesto["atualizado_em"] = datetime.now(timezone.utc).isoformat()

    with caminho.open("w", encoding="utf-8") as f:
        json.dump(manifesto, f, ensure_ascii=False, separators=(",", ":"))
        f.write("\n")


def main():
    novas = {
        "medicamentos_processos": gerar_medicamentos_processos(),
        "saneantes_processos": gerar_saneantes_processos(),
    }
    atualizar_manifesto(novas)
    print("Visões completas por processo geradas e manifest atualizada.")


if __name__ == "__main__":
    main()
