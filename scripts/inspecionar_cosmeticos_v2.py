from pathlib import Path
from collections import Counter
import csv
import re
import shutil
import ssl
import tempfile
import urllib.request


URL = (
    "https://dados.anvisa.gov.br/dados/CONSULTAS/PRODUTOS/"
    "TA_CONSULTA_COSMETICOS.CSV"
)

PROCESSOS_TESTE = {
    "2535104549920672",
    "25351045499202672",
}


def digits(value):
    return re.sub(r"\D", "", str(value or ""))


def normalizar(value):
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def achar_coluna(cabecalho, candidatos):
    mapa = {normalizar(coluna): coluna for coluna in cabecalho if coluna}
    for candidato in candidatos:
        if normalizar(candidato) in mapa:
            return mapa[normalizar(candidato)]
    return None


def baixar():
    caminho = Path(tempfile.mkstemp(prefix="cosmeticos_", suffix=".csv")[1])
    requisicao = urllib.request.Request(
        URL,
        headers={"User-Agent": "Mozilla/5.0 base-vigilancia-diagnostico"},
    )
    contexto = ssl._create_unverified_context()
    print("Baixando:", URL)
    with urllib.request.urlopen(
        requisicao, timeout=900, context=contexto
    ) as resposta, caminho.open("wb") as destino:
        shutil.copyfileobj(resposta, destino)
    print("Arquivo baixado:", caminho.stat().st_size, "bytes")
    if caminho.stat().st_size < 1_000_000:
        raise RuntimeError("Arquivo de cosméticos pequeno demais; diagnóstico cancelado.")
    return caminho


def configuracao(caminho):
    amostra = caminho.read_bytes()[:200_000]
    encoding = "latin-1"
    for tentativa in ("utf-8-sig", "utf-8", "latin-1", "cp1252"):
        try:
            amostra.decode(tentativa)
            encoding = tentativa
            break
        except UnicodeDecodeError:
            pass
    texto = amostra.decode(encoding, errors="replace")
    delimitador = ";"
    try:
        delimitador = csv.Sniffer().sniff(texto, delimiters=";,|\t").delimiter
    except csv.Error:
        pass
    return encoding, delimitador


def main():
    caminho = baixar()
    try:
        encoding, delimitador = configuracao(caminho)
        print("Encoding:", encoding, "| delimitador:", repr(delimitador))
        with caminho.open(
            "r", encoding=encoding, errors="replace", newline=""
        ) as arquivo:
            leitor = csv.DictReader(arquivo, delimiter=delimitador)
            cabecalho = leitor.fieldnames or []
            print("COLUNAS COSMÉTICOS:", cabecalho)

            mapa = {
                "processo": achar_coluna(
                    cabecalho,
                    ["NU_PROCESSO", "NUMERO_PROCESSO", "PROCESSO"],
                ),
                "regularizacao": achar_coluna(
                    cabecalho,
                    [
                        "NU_REGULARIZACAO",
                        "NUMERO_REGULARIZACAO",
                        "NU_REGISTRO_PRODUTO",
                        "NUMERO_REGISTRO",
                        "REGISTRO",
                        "NU_REGISTRO",
                    ],
                ),
                "produto": achar_coluna(
                    cabecalho,
                    ["NO_PRODUTO", "NOME_PRODUTO", "PRODUTO", "NOME_COMERCIAL"],
                ),
                "marca": achar_coluna(cabecalho, ["NO_MARCA", "MARCA"]),
                "detentor": achar_coluna(
                    cabecalho,
                    [
                        "NO_RAZAO_SOCIAL_EMPRESA",
                        "NO_RAZAO_SOCIAL",
                        "RAZAO_SOCIAL",
                        "DETENTOR",
                        "EMPRESA",
                    ],
                ),
                "cnpj": achar_coluna(
                    cabecalho,
                    ["NU_CNPJ_EMPRESA", "NU_CNPJ", "CNPJ", "CNPJ_DETENTOR"],
                ),
                "situacao": achar_coluna(
                    cabecalho,
                    ["ST_SITUACAO_PRODUTO", "DS_SITUACAO", "SITUACAO", "STATUS"],
                ),
                "tipo": achar_coluna(
                    cabecalho,
                    [
                        "DS_TIPO_PETICAO",
                        "TIPO_REGULARIZACAO",
                        "DS_TIPO_REGULARIZACAO",
                        "TIPO_PRODUTO",
                    ],
                ),
                "registrado": achar_coluna(cabecalho, ["ST_REGISTRADO"]),
                "vencimento": achar_coluna(cabecalho, ["DT_VENCIMENTO"]),
                "atualizacao": achar_coluna(cabecalho, ["DT_ATUALIZACAO"]),
            }
            print("MAPEAMENTO PROPOSTO:", mapa)

            total = 0
            encontrados = []
            primeiras = []
            processos_unicos = set()
            registros_unicos = set()
            pares_unicos = set()
            sem_processo = 0
            sem_registro = 0
            situacoes = Counter()
            tipos = Counter()
            registrados = Counter()
            for linha in leitor:
                total += 1
                processo = digits(linha.get(mapa["processo"], "")) if mapa["processo"] else ""
                registro = digits(linha.get(mapa["regularizacao"], "")) if mapa["regularizacao"] else ""
                produto = (linha.get(mapa["produto"], "") or "").strip() if mapa["produto"] else ""
                if processo:
                    processos_unicos.add(processo)
                else:
                    sem_processo += 1
                if registro:
                    registros_unicos.add(registro)
                else:
                    sem_registro += 1
                pares_unicos.add((processo, registro, produto))
                if mapa["situacao"]:
                    situacoes[(linha.get(mapa["situacao"], "") or "").strip()] += 1
                if mapa["tipo"]:
                    tipos[(linha.get(mapa["tipo"], "") or "").strip()] += 1
                if mapa["registrado"]:
                    registrados[(linha.get(mapa["registrado"], "") or "").strip()] += 1
                if len(primeiras) < 3:
                    primeiras.append(
                        {destino: linha.get(origem, "") for destino, origem in mapa.items() if origem}
                    )
                numeros_linha = {digits(valor) for valor in linha.values() if valor}
                if numeros_linha.intersection(PROCESSOS_TESTE):
                    encontrados.append(
                        {destino: linha.get(origem, "") for destino, origem in mapa.items() if origem}
                    )

            print("TOTAL DE LINHAS:", total)
            print("PROCESSOS ÚNICOS:", len(processos_unicos), "| SEM PROCESSO:", sem_processo)
            print("REGISTROS ÚNICOS:", len(registros_unicos), "| SEM REGISTRO:", sem_registro)
            print("COMBINAÇÕES ÚNICAS PROCESSO/REGISTRO/PRODUTO:", len(pares_unicos))
            print("SITUAÇÕES:", situacoes.most_common(30))
            print("ST_REGISTRADO:", registrados.most_common(30))
            print("TIPOS DE PETIÇÃO (30 mais frequentes):", tipos.most_common(30))
            print("PRIMEIRAS LINHAS MAPEADAS:", primeiras)
            print("RESULTADO DOS PROCESSOS DE TESTE:", encontrados)
            if not encontrados:
                print("AVISO: nenhuma das duas formas do processo foi localizada.")
    finally:
        caminho.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
