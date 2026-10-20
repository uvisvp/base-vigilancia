"""Produtos irregulares a partir dos dados abertos da Anvisa.

A API de dossiês (consultas-externas) deixou de responder em 2026 e o portal
de consultas passou a exigir verificação humana (Cloudflare Turnstile). A
Anvisa publica a mesma lista de dossiês em CSV aberto, atualizado pela carga
semanal do portal de dados abertos:

    dados.anvisa.gov.br/dados/CONSULTAS/EMPRESA_FISCALIZACAO_PRODUTO/
    TA_CONSULTA_PRODUTOS_IRREGULARES_RESULTADO.CSV

O CSV traz o dossiê, a empresa, o tipo e o risco do produto, as ações
(apreensão, suspensão etc.), a data da medida e os produtos com registro.
Não traz a motivação, os lotes nem o número da Resolução-RE. Por isso:

- dossiê já publicado e sem medida nova: mantém o detalhe completo anterior;
- dossiê já publicado com medida mais recente no CSV: mantém o detalhe
  anterior, atualiza ações, data e produtos e avisa que a medida nova não
  tem motivação;
- dossiê novo: entra com os dados do CSV e o mesmo aviso;
- dossiê que saiu do CSV: continua publicado com presente_na_fonte falso.

Grava no mesmo formato de gerar_produtos_irregulares.py (fragmentos por
processo e índices por CNPJ, registro e lote), sem mudar o app.
"""
from collections import defaultdict
import csv
import io
import json
import os
import urllib.request

from gerar_produtos_irregulares import (
    LIMITE_QUEDA,
    MANIFESTO,
    agora_iso,
    gravar_json,
    carregar_existentes,
    construir_publicacao,
    limpar_json,
    limpar_texto,
    publicar,
    atualizar_manifesto,
    somente_numeros,
)

FONTE = (
    "https://dados.anvisa.gov.br/dados/CONSULTAS/EMPRESA_FISCALIZACAO_PRODUTO/"
    "TA_CONSULTA_PRODUTOS_IRREGULARES_RESULTADO.CSV"
)
VERSAO = "2026-10-20-produtos-irregulares-dados-abertos-v1"
AVISO_NOVO = (
    "Dados abertos da Anvisa: o dossiê não traz motivação, lotes nem número "
    "da Resolução-RE. Confira a medida no DOU antes de citá-la."
)


def baixar_csv():
    caminho = os.environ.get("PRODUTOS_IRREGULARES_CSV", "").strip()
    if caminho:
        bruto = open(caminho, "rb").read()
    else:
        pedido = urllib.request.Request(
            FONTE,
            headers={"User-Agent": "base-vigilancia/1.0"},
        )
        with urllib.request.urlopen(pedido, timeout=600) as resposta:
            bruto = resposta.read()
    try:
        texto = bruto.decode("utf-8")
    except UnicodeDecodeError:
        texto = bruto.decode("latin-1")
    linhas = list(csv.DictReader(io.StringIO(texto), delimiter=";"))
    if not linhas or "NU_PROCESSO" not in linhas[0]:
        raise RuntimeError("CSV de produtos irregulares sem a coluna NU_PROCESSO.")
    return linhas


def data_csv(valor):
    """MM/DD/AAAA do CSV para o formato ISO já publicado (meia-noite de Brasília)."""
    texto = str(valor or "").strip()[:10]
    partes = texto.split("/")
    if len(partes) != 3 or not all(p.isdigit() for p in partes):
        return None
    mes, dia, ano = partes
    return f"{ano}-{mes.zfill(2)}-{dia.zfill(2)}T03:00:00+00:00"


def data_br(iso):
    return f"{iso[8:10]}/{iso[5:7]}/{iso[:4]}" if iso else ""


def agrupar(linhas):
    dossies = defaultdict(list)
    for linha in linhas:
        processo = somente_numeros(linha.get("NU_PROCESSO"))
        if processo:
            dossies[processo].append(linha)
    return dossies


def unicos(valores):
    saida = []
    for valor in valores:
        valor = limpar_texto(valor)
        if valor and valor not in saida:
            saida.append(valor)
    return saida


def produtos_csv(linhas):
    produtos, vistos = [], set()
    for linha in linhas:
        nome = limpar_texto(linha.get("PRODUTO"))
        registro = somente_numeros(linha.get("REGISTRO"))
        if not nome and not registro:
            continue
        chave = (nome.casefold(), registro)
        if chave in vistos:
            continue
        vistos.add(chave)
        produtos.append(limpar_json({"produto": nome, "registro": registro}))
    return produtos


def resumo_csv(processo, linhas, gerado_em):
    x = linhas[0]
    datas = sorted(filter(None, (data_csv(l.get("DT_PUBLICACAO_MEDIDA")) for l in linhas)))
    total = max((int(l["TOTAL_MEDIDA_CAUTELAR"]) for l in linhas
                 if str(l.get("TOTAL_MEDIDA_CAUTELAR") or "").isdigit()), default=None)
    investigada = limpar_json({
        "cnpj": somente_numeros(x.get("NU_CNPJ_EMPRESA_INVESTIGADA")),
        "razao_social": limpar_texto(x.get("NO_EMPRESA_INVESTIGADA")),
    })
    return limpar_json({
        "processo": processo,
        "id_dossie": int(x["CO_SEQ_DOSSIE_INVESTIG_MED"])
        if str(x.get("CO_SEQ_DOSSIE_INVESTIG_MED") or "").isdigit() else None,
        "empresa": limpar_json({
            "cnpj": somente_numeros(x.get("NU_CNPJ")),
            "razao_social": limpar_texto(x.get("NO_RAZAO_SOCIAL")),
        }),
        "empresa_investigada": investigada,
        "tipo_produto": limpar_texto(x.get("DS_TIPO_PRODUTO")),
        "codigo_tipo_produto": int(x["CO_TIPO_PRODUTO"])
        if str(x.get("CO_TIPO_PRODUTO") or "").isdigit() else None,
        "risco": limpar_texto(x.get("DS_RISCO_PRODUTO")),
        "codigo_risco": int(x["CO_RISCO"])
        if str(x.get("CO_RISCO") or "").isdigit() else None,
        "produto_resumo": limpar_texto(x.get("PRODUTOS_CONCATENADOS")),
        "acoes_resumo": " | ".join(unicos(l.get("ACAO_ATIVIDADE") for l in linhas)),
        "total_medidas": total,
        "data_ultima_medida": datas[-1] if datas else None,
        "produtos": produtos_csv(linhas),
        "presente_na_fonte": True,
        "consultado_em": gerado_em,
    })


def mesclar_produtos(anteriores, novos):
    saida = [dict(p) for p in anteriores or []]
    registros = {somente_numeros(p.get("registro")) for p in saida if p.get("registro")}
    nomes = {limpar_texto(p.get("produto")).casefold() for p in saida if p.get("produto")}
    for p in novos:
        if p.get("registro") and p["registro"] in registros:
            continue
        if not p.get("registro") and limpar_texto(p.get("produto")).casefold() in nomes:
            continue
        saida.append(p)
    return saida


def atualizar(existentes, dossies, gerado_em):
    registros = {}
    contagem = defaultdict(int)
    for processo, linhas in sorted(dossies.items()):
        novo = resumo_csv(processo, linhas, gerado_em)
        anterior = existentes.get(processo)
        if not anterior:
            novo["detalhe_status"] = "dados_abertos"
            novo["observacao"] = AVISO_NOVO
            registros[processo] = novo
            contagem["novos"] += 1
            continue
        item = dict(anterior)
        item["presente_na_fonte"] = True
        item.pop("ausente_desde", None)
        data_ant = str(anterior.get("data_ultima_medida") or "")[:10]
        data_nova = str(novo.get("data_ultima_medida") or "")[:10]
        if data_nova and data_nova > data_ant:
            for campo in ("acoes_resumo", "total_medidas", "data_ultima_medida",
                          "tipo_produto", "risco"):
                if novo.get(campo):
                    item[campo] = novo[campo]
            item["produtos"] = mesclar_produtos(anterior.get("produtos"), novo.get("produtos", []))
            item["detalhe_status"] = "parcial"
            item["observacao"] = (
                f"Medida de {data_br(novo['data_ultima_medida'])} vinda dos dados abertos "
                "da Anvisa, sem motivação nem número da Resolução-RE; as medidas "
                "detalhadas abaixo são as anteriores. Confira no DOU."
            )
            item["consultado_em"] = gerado_em
            contagem["atualizados"] += 1
        else:
            contagem["mantidos"] += 1
        registros[processo] = item
    for processo, anterior in existentes.items():
        if processo in dossies:
            continue
        item = dict(anterior)
        item["presente_na_fonte"] = False
        item.setdefault("ausente_desde", gerado_em)
        registros[processo] = item
        contagem["ausentes"] += 1
    return registros, contagem


def main():
    print("Versão do gerador:", VERSAO)
    gerado_em = agora_iso()
    existentes = carregar_existentes()
    print("Dossiês publicados anteriormente:", len(existentes))
    linhas = baixar_csv()
    dossies = agrupar(linhas)
    print("Linhas do CSV:", len(linhas), "| dossiês:", len(dossies))

    presentes = sum(1 for x in existentes.values() if x.get("presente_na_fonte", True))
    if presentes and len(dossies) < presentes * LIMITE_QUEDA:
        raise RuntimeError(
            f"O CSV caiu de {presentes} para {len(dossies)} dossiês. "
            "Publicação cancelada para proteger a base."
        )

    registros, contagem = atualizar(existentes, dossies, gerado_em)
    publicacao = construir_publicacao(registros, gerado_em)
    detalhes_ok = sum(1 for x in registros.values() if x.get("detalhe_status") == "ok")
    metadados = {
        "status": "ok",
        "fonte": FONTE,
        "tipo_fonte": "Dados abertos da Anvisa (CSV)",
        "gerado_em": gerado_em,
        "atualizado_em": gerado_em,
        "versao_gerador": VERSAO,
        "registros": len(registros),
        "presentes_na_fonte": len(dossies),
        "ausentes_na_fonte": contagem["ausentes"],
        "novos_dados_abertos": contagem["novos"],
        "atualizados_dados_abertos": contagem["atualizados"],
        "mantidos_com_detalhe": contagem["mantidos"],
        "detalhes_validos": detalhes_ok,
        "fragmentos": len(publicacao["fragmentos"]),
        "chave": "processo",
        "fragmentacao": "dígitos 6 a 8 do processo normalizado",
        "observacao": (
            "Detalhe completo (motivação, lotes, Resolução-RE) só nos dossiês "
            "obtidos pela API até 31/08/2026; os demais vêm do CSV aberto."
        ),
    }
    maiores = publicar(registros, publicacao, metadados)
    atualizar_manifesto(metadados, publicacao, maiores)
    # atualizar_manifesto grava identado; a base principal publica o manifesto compacto.
    gravar_json(MANIFESTO, json.loads(MANIFESTO.read_text(encoding="utf-8")))
    print("Produtos irregulares gerados com sucesso.")
    for chave in ("novos", "atualizados", "mantidos", "ausentes"):
        print(f"{chave}:", contagem[chave])
    print("Registros:", len(registros), "| fragmentos:", len(publicacao["fragmentos"]))


if __name__ == "__main__":
    main()
