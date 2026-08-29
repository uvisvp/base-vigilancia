from collections import Counter
from pathlib import Path
import csv
import re
import shutil
import ssl
import tempfile
import urllib.request


FONTES = {
    "ALIMENTOS": (
        "https://dados.anvisa.gov.br/dados/CONSULTAS/PRODUTOS/"
        "TA_CONSULTA_ALIMENTOS.CSV"
    ),
    "ALIMENTOS_RESULTADO": (
        "https://dados.anvisa.gov.br/dados/CONSULTAS/PRODUTOS/"
        "TA_CONSULTA_ALIMENTOS_RESULTADO.CSV"
    ),
}


CANDIDATOS = {
    "processo": [
        "NU_PROCESSO", "NUMERO_PROCESSO", "PROCESSO",
    ],
    "regularizacao": [
        "NU_REGISTRO", "NUMERO_REGISTRO", "REGISTRO",
        "NU_NOTIFICACAO", "NUMERO_NOTIFICACAO", "NOTIFICACAO",
        "NU_REGULARIZACAO", "NUMERO_REGULARIZACAO",
    ],
    "produto": [
        "NO_PRODUTO", "NOME_PRODUTO", "PRODUTO",
        "DS_PRODUTO", "NO_ALIMENTO",
    ],
    "marca": [
        "NO_MARCA", "NOME_MARCA", "MARCA",
        "DS_MARCA", "MARCAS",
    ],
    "cnpj": [
        "NU_CNPJ_EMPRESA", "NU_CNPJ", "CNPJ_EMPRESA", "CNPJ",
    ],
    "empresa": [
        "NO_RAZAO_SOCIAL_EMPRESA", "NO_RAZAO_SOCIAL",
        "RAZAO_SOCIAL_EMPRESA", "RAZAO_SOCIAL", "EMPRESA",
        "NO_EMPRESA", "DETENTOR",
    ],
    "categoria": [
        "NO_CATEGORIA", "DS_CATEGORIA", "CATEGORIA",
        "NO_CATEGORIA_PRODUTO", "DS_CATEGORIA_PRODUTO",
    ],
    "tipo": [
        "DS_TIPO_PETICAO", "TIPO_PETICAO", "TIPO_PRODUTO",
        "DS_TIPO_PRODUTO", "TIPO_REGULARIZACAO",
        "DS_TIPO_REGULARIZACAO",
    ],
    "situacao": [
        "ST_SITUACAO_PRODUTO", "SITUACAO_PRODUTO", "SITUACAO",
        "DS_SITUACAO", "ST_ATIVO", "ATIVO",
    ],
    "registrado": [
        "ST_REGISTRADO", "REGISTRADO",
    ],
    "vencimento": [
        "DT_VENCIMENTO", "DATA_VENCIMENTO", "DT_VALIDADE",
        "DATA_VALIDADE", "VALIDADE",
    ],
    "regularizado_em": [
        "DT_REGULARIZACAO", "DATA_REGULARIZACAO",
        "DT_PUBLICACAO", "DATA_PUBLICACAO",
    ],
    "alegacoes": [
        "DS_ALEGACOES", "ALEGACOES", "DS_ALEGACAO", "ALEGACAO",
        "DS_ALEGACOES_APROVADAS", "ALEGACOES_APROVADAS",
    ],
    "atualizacao": [
        "DT_ATUALIZACAO", "DATA_ATUALIZACAO",
        "DT_CARGA_ETL", "DATA_CARGA_ETL",
    ],
}


def normalizar_nome(valor):
    return re.sub(r"[^A-Z0-9]", "", str(valor or "").upper())


def texto(valor):
    return re.sub(r"\s+", " ", str(valor or "").strip())


def achar_coluna(cabecalho, candidatos):
    mapa = {
        normalizar_nome(coluna): coluna
        for coluna in cabecalho
        if coluna
    }

    for candidato in candidatos:
        coluna = mapa.get(normalizar_nome(candidato))
        if coluna:
            return coluna

    return None


def baixar(nome, url):
    temporario = tempfile.NamedTemporaryFile(
        prefix=f"anvisa_{nome.lower()}_",
        suffix=".csv",
        delete=False,
    )
    caminho = Path(temporario.name)
    temporario.close()

    print(f"\nBaixando {nome}: {url}", flush=True)
    requisicao = urllib.request.Request(
        url,
        headers={"User-Agent": "Base-Vigilancia/1.0"},
    )

    contexto = ssl._create_unverified_context()

    with urllib.request.urlopen(
        requisicao,
        timeout=300,
        context=contexto,
    ) as resposta, caminho.open("wb") as destino:
        shutil.copyfileobj(resposta, destino)

    tamanho = caminho.stat().st_size
    print(f"Arquivo baixado: {tamanho} bytes", flush=True)

    if tamanho < 100_000:
        raise RuntimeError(
            f"Download de {nome} parece incompleto: {tamanho} bytes"
        )

    return caminho


def configuracao_csv(caminho):
    encodings = ("utf-8-sig", "latin-1")

    for encoding in encodings:
        try:
            with caminho.open(
                "r", encoding=encoding, newline="", errors="strict"
            ) as arquivo:
                amostra = arquivo.read(65_536)

            delimitador = csv.Sniffer().sniff(
                amostra, delimiters=";,|\t"
            ).delimiter
            return encoding, delimitador
        except (UnicodeDecodeError, csv.Error):
            continue

    return "latin-1", ";"


def mostrar_top(titulo, contador, limite=25):
    if not contador:
        return

    print(f"{titulo}: {contador.most_common(limite)}", flush=True)


def inspecionar(nome, url):
    caminho = baixar(nome, url)

    try:
        encoding, delimitador = configuracao_csv(caminho)
        print(
            f"Encoding: {encoding} | delimitador: {delimitador!r}",
            flush=True,
        )

        with caminho.open(
            "r",
            encoding=encoding,
            newline="",
            errors="replace",
        ) as arquivo:
            leitor = csv.DictReader(arquivo, delimiter=delimitador)
            cabecalho = leitor.fieldnames or []

            print(f"COLUNAS {nome}: {cabecalho}", flush=True)

            mapeamento = {
                campo: achar_coluna(cabecalho, candidatos)
                for campo, candidatos in CANDIDATOS.items()
            }
            print(f"MAPEAMENTO PROPOSTO: {mapeamento}", flush=True)

            total = 0
            nao_vazios = Counter()
            categorias = Counter()
            tipos = Counter()
            situacoes = Counter()
            registrados = Counter()
            suplementos = 0
            amostras = []
            amostras_suplementos = []

            for linha in leitor:
                total += 1
                item = {
                    campo: texto(linha.get(coluna, "")) if coluna else ""
                    for campo, coluna in mapeamento.items()
                }

                for campo, valor in item.items():
                    if valor:
                        nao_vazios[campo] += 1

                if item["categoria"]:
                    categorias[item["categoria"]] += 1
                if item["tipo"]:
                    tipos[item["tipo"]] += 1
                if item["situacao"]:
                    situacoes[item["situacao"]] += 1
                if item["registrado"]:
                    registrados[item["registrado"]] += 1

                if len(amostras) < 5:
                    amostras.append(item)

                busca_suplemento = " ".join(
                    (
                        item["produto"],
                        item["categoria"],
                        item["tipo"],
                    )
                ).upper()

                if "SUPLEMENT" in busca_suplemento:
                    suplementos += 1
                    if len(amostras_suplementos) < 5:
                        amostras_suplementos.append(item)

        print(f"TOTAL DE LINHAS: {total}", flush=True)
        print(f"CAMPOS NÃO VAZIOS: {dict(nao_vazios)}", flush=True)
        print(
            f"LINHAS IDENTIFICADAS COMO SUPLEMENTO: {suplementos}",
            flush=True,
        )
        mostrar_top("CATEGORIAS (30 mais frequentes)", categorias, 30)
        mostrar_top("TIPOS (30 mais frequentes)", tipos, 30)
        mostrar_top("SITUAÇÕES", situacoes, 30)
        mostrar_top("ST_REGISTRADO", registrados, 30)
        print(f"PRIMEIRAS LINHAS MAPEADAS: {amostras}", flush=True)
        print(
            f"AMOSTRAS DE SUPLEMENTOS: {amostras_suplementos}",
            flush=True,
        )

    finally:
        caminho.unlink(missing_ok=True)


def main():
    for nome, url in FONTES.items():
        try:
            inspecionar(nome, url)
        except Exception as erro:
            print(f"ERRO AO INSPECIONAR {nome}: {erro}", flush=True)
            raise

    print("\nInspeção de alimentos concluída com sucesso.", flush=True)


if __name__ == "__main__":
    main()
