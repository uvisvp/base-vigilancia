"""Produtos de cannabis a partir dos dados abertos da Anvisa.

O portal de consultas (consultas.anvisa.gov.br) passou a exigir verificação
humana (Cloudflare Turnstile) em 2026. A Anvisa publica a lista dos produtos
de cannabis (RDC 327/2019) em CSV aberto:

    dados.anvisa.gov.br/dados/CONSULTAS/PRODUTOS/TA_CONSULTA_PRODUTOS_CANNABIS.CSV

O CSV traz produto, processo, registro, empresa, CNPJ, AFE, princípio ativo,
vencimento e situação. Não traz as apresentações (embalagem, conservação,
restrição de prescrição, fabricantes). Por isso:

- produto já publicado: mantém as apresentações e atualiza situação,
  vencimento, empresa e data de atualização pelo CSV;
- produto novo: entra com os dados do CSV, sem apresentações, com aviso;
- produto que saiu do CSV: continua publicado com presente_na_fonte falso.

Grava no mesmo formato de gerar_cannabis.py (catálogo e índices por
registro, processo e CNPJ), sem mudar o app.
"""
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
import csv
import io
import json
import os
import shutil
import tempfile
import urllib.request

from gerar_cannabis import DADOS, DESTINO, digitos, gravar_json

FONTE = "https://dados.anvisa.gov.br/dados/CONSULTAS/PRODUTOS/TA_CONSULTA_PRODUTOS_CANNABIS.CSV"
VERSAO = "2026-10-20-cannabis-dados-abertos-v1"
LIMITE_QUEDA = 0.90
AVISO_NOVO = (
    "Dados abertos da Anvisa: sem apresentações, embalagem e restrição de "
    "prescrição. Confira na consulta da Anvisa."
)


def baixar_csv():
    caminho = os.environ.get("CANNABIS_CSV", "").strip()
    if caminho:
        bruto = Path(caminho).read_bytes()
    else:
        pedido = urllib.request.Request(FONTE, headers={"User-Agent": "base-vigilancia/1.0"})
        with urllib.request.urlopen(pedido, timeout=180) as resposta:
            bruto = resposta.read()
    try:
        texto = bruto.decode("utf-8")
    except UnicodeDecodeError:
        texto = bruto.decode("latin-1")
    linhas = list(csv.DictReader(io.StringIO(texto), delimiter=";"))
    if not linhas or "NU_PROCESSO" not in linhas[0]:
        raise RuntimeError("CSV de cannabis sem a coluna NU_PROCESSO.")
    return linhas


def data_csv(valor):
    """DD/MM/AAAA do CSV para o formato já publicado pela consulta da Anvisa."""
    texto = str(valor or "").strip()[:10]
    partes = texto.split("/")
    if len(partes) != 3 or not all(p.isdigit() for p in partes):
        return None
    dia, mes, ano = partes
    return f"{ano}-{mes.zfill(2)}-{dia.zfill(2)}T00:00:00.000-0300"


def vencimento(linha):
    """Vencimento conferido pelo mês/ano.

    DT_VENCIMENTO_PRODUTO às vezes repete a data de publicação ou soma 10 anos;
    VENCIMENTO_MES_ANO coincide com a consulta da Anvisa em todos os produtos
    conferidos em 20/10/2026. Usa a data só quando o mês/ano bate; senão, o
    último dia do mês/ano (a consulta mostra a data da publicação + 5 anos).
    """
    mes_ano = digitos(linha.get("VENCIMENTO_MES_ANO"))
    data = data_csv(linha.get("DT_VENCIMENTO_PRODUTO"))
    if len(mes_ano) != 6:
        return data
    mes, ano = mes_ano[:2], mes_ano[2:]
    if data and data[:7] == f"{ano}-{mes}":
        return data
    publicacao = data_csv(linha.get("DT_PUBLICACAO"))
    if publicacao and publicacao[5:7] == mes:
        return f"{ano}-{mes}-{publicacao[8:10]}" + publicacao[10:]
    return f"{ano}-{mes}-01T00:00:00.000-0300"


def do_csv(linha):
    return {
        "produto": (linha.get("NO_PRODUTO") or "").strip(),
        "registro": digitos(linha.get("NU_REGISTRO_PRODUTO")),
        "processo": digitos(linha.get("NU_PROCESSO")),
        "situacao": (linha.get("SITUACAO_VALIDADE") or "").strip(),
        "categoria": "Produto de cannabis",
        "principio_ativo": (linha.get("PRINCIPIOS_ATIVOS") or "").strip(),
        "classes_terapeuticas": [],
        "data_autorizacao": data_csv(linha.get("DT_PUBLICACAO")),
        "vencimento_autorizacao": vencimento(linha),
        "empresa": (linha.get("NO_RAZAO_SOCIAL_EMPRESA") or "").strip(),
        "cnpj": digitos(linha.get("NU_CNPJ_EMPRESA")),
        "afe": digitos(linha.get("AUTORIZACAO")),
        "data_atualizacao": data_csv(linha.get("DT_ATUALIZACAO")),
        "apresentacoes": [],
    }


def main():
    print("Versão do gerador:", VERSAO)
    catalogo = DESTINO / "catalogo.json"
    anteriores = json.loads(catalogo.read_text(encoding="utf-8")) if catalogo.exists() else []
    por_processo = {x.get("processo"): x for x in anteriores if x.get("processo")}
    linhas = baixar_csv()
    novos = {}
    for linha in linhas:
        item = do_csv(linha)
        if item["processo"]:
            novos[item["processo"]] = item
    print("Publicados:", len(por_processo), "| no CSV:", len(novos))
    presentes = sum(1 for x in anteriores if x.get("presente_na_fonte", True))
    if presentes and len(novos) < presentes * LIMITE_QUEDA:
        raise RuntimeError(
            f"O CSV caiu de {presentes} para {len(novos)} produtos. Publicação cancelada."
        )

    produtos, contagem = [], defaultdict(int)
    for processo, novo in sorted(novos.items()):
        anterior = por_processo.get(processo)
        if not anterior:
            novo["observacao"] = AVISO_NOVO
            produtos.append(novo)
            contagem["novos"] += 1
            continue
        item = dict(anterior)
        item.pop("presente_na_fonte", None)
        item.pop("ausente_desde", None)
        mudou = False
        for campo in ("situacao", "empresa", "cnpj", "afe", "registro", "produto"):
            if novo[campo] and novo[campo] != item.get(campo):
                item[campo] = novo[campo]
                mudou = True
        # Vencimento só muda quando muda o mês/ano (renovação ou correção).
        venc = novo["vencimento_autorizacao"]
        if venc and venc[:7] != str(item.get("vencimento_autorizacao") or "")[:7]:
            item["vencimento_autorizacao"] = venc
            mudou = True
        if mudou and novo["data_atualizacao"]:
            item["data_atualizacao"] = novo["data_atualizacao"]
        contagem["alterados" if mudou else "mantidos"] += 1
        produtos.append(item)
    gerado_em = datetime.now(timezone.utc).isoformat()
    for processo, anterior in sorted(por_processo.items()):
        if processo in novos:
            continue
        item = dict(anterior)
        item["presente_na_fonte"] = False
        item.setdefault("ausente_desde", gerado_em)
        produtos.append(item)
        contagem["ausentes"] += 1

    registros, processos, cnpjs = defaultdict(list), defaultdict(list), defaultdict(list)
    for produto in produtos:
        if produto.get("registro"):
            registros[produto["registro"][:3]].append(produto)
        if produto.get("processo"):
            processos[produto["processo"][5:8]].append(produto)
        if len(produto.get("cnpj") or "") == 14:
            cnpjs[produto["cnpj"][:3]].append(produto)

    temporario = Path(tempfile.mkdtemp(prefix="cannabis_", dir=DADOS))
    try:
        gravar_json(temporario / "catalogo.json", produtos)
        for pasta, mapa in (("registros", registros), ("processos", processos), ("cnpj", cnpjs)):
            for shard, itens in mapa.items():
                gravar_json(temporario / pasta / f"{shard}.json", itens)
        if DESTINO.exists():
            shutil.rmtree(DESTINO)
        temporario.rename(DESTINO)
    except Exception:
        shutil.rmtree(temporario, ignore_errors=True)
        raise

    manifesto_path = DADOS / "manifest.json"
    manifesto = json.loads(manifesto_path.read_text(encoding="utf-8"))
    ativos = [x for x in produtos if x.get("presente_na_fonte", True)]
    manifesto.setdefault("bases", {})["cannabis"] = {
        "status": "ok",
        "fonte": FONTE,
        "tipo_fonte": "Dados abertos da Anvisa (CSV)",
        "gerado_em": gerado_em,
        "versao_gerador": VERSAO,
        "registros": len(produtos),
        "apresentacoes": sum(len(x.get("apresentacoes") or []) for x in produtos),
        "ativos": sum(x.get("situacao") == "Válido" for x in ativos),
        "cancelados_caducos": sum(x.get("situacao") != "Válido" for x in ativos),
        "novos_dados_abertos": contagem["novos"],
        "alterados_dados_abertos": contagem["alterados"],
        "ausentes_na_fonte": contagem["ausentes"],
        "indices": ["registro", "processo", "cnpj"],
        "observacao": (
            "Situação e vencimento vêm do CSV aberto. Apresentações só nos produtos "
            "obtidos pela consulta da Anvisa até 22/09/2026."
        ),
    }
    gravar_json(manifesto_path, manifesto)
    print("cannabis:", len(produtos), "produtos |", dict(contagem))


if __name__ == "__main__":
    main()
