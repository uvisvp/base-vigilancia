from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict
import csv
import json
import os
import re
import urllib.request
import tempfile
import shutil
import ssl

BASE = Path(__file__).resolve().parent.parent
DADOS = BASE / "dados"

LIMITE_REDUCAO = 0.20
METADADOS_FONTES = {}

URL_DISPOSITIVOS = (
    "https://dados.anvisa.gov.br/dados/"
    "TA_PRODUTO_SAUDE_SITE.csv"
)

URL_AFE_AE = (
    "https://dados.anvisa.gov.br/dados/"
    "CONSULTAS/EMPRESA_FISCALIZACAO_PRODUTO/"
    "TA_CONSULTA_FUNCIONAMENTO_EMPRESA_NACIONAL.CSV"
)

URL_MEDICAMENTOS = (
    "https://dados.anvisa.gov.br/dados/"
    "DADOS_ABERTOS_MEDICAMENTOS.csv"
)

URL_SANEANTES = (
    "https://dados.anvisa.gov.br/dados/"
    "CONSULTAS/PRODUTOS/"
    "TA_CONSULTA_SANEANTES.CSV"
)

# O prefixo é publicado no manifesto. Assim, o HTML funciona com a base atual
# de três dígitos e também após a redistribuição em fragmentos menores.
PREFIXOS_BASE = {
    "dispositivos": 5,
    "afe_ae": 3,
    "medicamentos": 4,
    "saneantes": 4,
}
PREFIXO_INDICE_CNPJ = 3
PREFIXO_INDICE_AUTORIZACAO = 3
TETO_FRAGMENTO = 300_000
def somente_numeros(valor):
    return re.sub(r"\D", "", str(valor or ""))


def texto(valor):
    return re.sub(
        r"\s+",
        " ",
        str(valor or "").strip()
    )


def normalizar_nome(valor):
    return re.sub(
        r"[^A-Z0-9]",
        "",
        str(valor or "").upper()
    )


def achar_coluna(cabecalho, possibilidades):
    mapa = {
        normalizar_nome(c): c
        for c in cabecalho
        if c
    }

    for nome in possibilidades:
        chave = normalizar_nome(nome)

        if chave in mapa:
            return mapa[chave]

    return None


def baixar_csv(url, prefixo):
    print("Baixando:", url)

    temporario = Path(
        tempfile.mkstemp(
            prefix=prefixo,
            suffix=".csv"
        )[1]
    )

    requisicao = urllib.request.Request(
        url,
        headers={
            "User-Agent":
            "Mozilla/5.0 base-vigilancia"
        }
    )

    contexto_ssl = (
        ssl._create_unverified_context()
    )

    with urllib.request.urlopen(
        requisicao,
        timeout=600,
        context=contexto_ssl
    ) as resposta, temporario.open(
        "wb"
    ) as arquivo:

        METADADOS_FONTES[url] = {
            "data_fonte": (
                resposta.headers.get(
                    "Last-Modified"
                )
                or resposta.headers.get("Date")
                or "não informada"
            ),
            "etag": resposta.headers.get("ETag")
        }

        shutil.copyfileobj(
            resposta,
            arquivo
        )

    tamanho = temporario.stat().st_size

    print(
        "Arquivo baixado:",
        tamanho,
        "bytes"
    )

    if tamanho < 100000:
        raise RuntimeError(
            "Arquivo baixado pequeno demais. "
            "Atualização cancelada."
        )

    return temporario


def detectar_configuracao(arquivo):
    amostra = arquivo.read_bytes()[:200000]

    encoding = "latin-1"

    for tentativa in [
        "utf-8-sig",
        "utf-8",
        "latin-1",
        "cp1252"
    ]:
        try:
            amostra.decode(tentativa)
            encoding = tentativa
            break
        except UnicodeDecodeError:
            pass

    texto_amostra = amostra.decode(
        encoding,
        errors="replace"
    )

    delimitador = ";"

    try:
        dialeto = csv.Sniffer().sniff(
            texto_amostra,
            delimiters=";,|\t"
        )
        delimitador = dialeto.delimiter

    except csv.Error:
        pass

    print(
        "Encoding:",
        encoding,
        "| delimitador:",
        repr(delimitador)
    )

    return encoding, delimitador


def limpar_json(item):
    return {
        chave: valor
        for chave, valor in item.items()
        if valor not in ("", None)
    }


def carregar_manifesto_anterior():
    caminho = DADOS / "manifest.json"

    if not caminho.exists():
        return {}

    try:
        with caminho.open(
            "r",
            encoding="utf-8"
        ) as f:
            return json.load(f)
    except (
        OSError,
        json.JSONDecodeError
    ):
        return {}


def validar_reducao(nome, total):
    if os.environ.get(
        "PERMITIR_REDUCAO_ANORMAL"
    ) == "1":
        return

    anterior = (
        carregar_manifesto_anterior()
        .get("bases", {})
        .get(nome, {})
        .get("registros")
    )

    if not isinstance(anterior, int):
        return

    minimo = int(
        anterior * (
            1 - LIMITE_REDUCAO
        )
    )

    if total < minimo:
        percentual = (
            100 * (anterior - total)
            / anterior
        )
        raise RuntimeError(
            f"Base {nome} caiu de "
            f"{anterior} para {total} "
            f"registros ({percentual:.1f}%): "
            "atualização cancelada. "
            "Revise a fonte ou use "
            "PERMITIR_REDUCAO_ANORMAL=1 "
            "após validação manual."
        )


def metadados_base(
    url,
    total,
    fragmentos,
    prefixo,
    maior_fragmento
):
    gerado_em = datetime.now(
        timezone.utc
    ).isoformat()

    fonte = METADADOS_FONTES.get(
        url,
        {}
    )

    resultado = {
        "status": "ok",
        "fonte": url,
        "data_fonte": fonte.get(
            "data_fonte",
            "não informada"
        ),
        "gerado_em": gerado_em,
        "atualizado_em": gerado_em,
        "registros": total,
        "fragmentos": fragmentos,
        "prefixo": prefixo,
        "maior_fragmento": maior_fragmento
    }

    if fonte.get("etag"):
        resultado["etag_fonte"] = (
            fonte["etag"]
        )

    return resultado


def prefixo_processo(processo):
    numero = somente_numeros(processo)

    if len(numero) >= 8:
        return numero[5:8]

    return numero[:3]


def extrair_cnpj_item(item):
    cnpj = somente_numeros(
        item.get("cnpj", "")
    )

    if len(cnpj) == 14:
        return cnpj

    correspondencia = re.search(
        r"(?<!\d)(\d{14})(?!\d)",
        item.get("detentor", "")
    )

    return (
        correspondencia.group(1)
        if correspondencia
        else ""
    )


def gravar_fragmentos(destino, grupos):
    destino.mkdir(
        parents=True,
        exist_ok=True
    )

    for antigo in destino.glob("*.json"):
        antigo.unlink()

    maior = 0

    for prefixo, itens in grupos.items():

        caminho = destino / (
            prefixo + ".json"
        )

        with caminho.open(
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                itens,
                f,
                ensure_ascii=False,
                separators=(",", ":")
            )

        maior = max(
            maior,
            caminho.stat().st_size
        )

    return maior


# ==================================================
# DISPOSITIVOS MÉDICOS
# ==================================================

def gerar_dispositivos():

    arquivo = baixar_csv(
        URL_DISPOSITIVOS,
        "anvisa_dispositivos_"
    )

    try:
        encoding, delimitador = (
            detectar_configuracao(
                arquivo
            )
        )

        grupos = defaultdict(list)

        with arquivo.open(
            "r",
            encoding=encoding,
            errors="replace",
            newline=""
        ) as f:

            leitor = csv.DictReader(
                f,
                delimiter=delimitador
            )

            if not leitor.fieldnames:
                raise RuntimeError(
                    "CSV de dispositivos "
                    "sem cabeçalho."
                )

            print(
                "Colunas dispositivos:",
                leitor.fieldnames
            )

            col_registro = achar_coluna(
                leitor.fieldnames,
                [
                    "NUMERO_REGISTRO_CADASTRO",
                    "NUMERO_REGISTRO",
                    "REGISTRO",
                    "NUM_REGISTRO",
                    "NUMERO_CADASTRO"
                ]
            )

            col_produto = achar_coluna(
                leitor.fieldnames,
                [
                    "NOME_PRODUTO",
                    "PRODUTO",
                    "NOME_COMERCIAL"
                ]
            )

            col_processo = achar_coluna(
                leitor.fieldnames,
                [
                    "NUMERO_PROCESSO",
                    "PROCESSO"
                ]
            )

            col_detentor = achar_coluna(
                leitor.fieldnames,
                [
                    "DETENTOR_REGISTRO_CADASTRO",
                    "DETENTOR_REGISTRO",
                    "DETENTOR",
                    "RAZAO_SOCIAL"
                ]
            )

            col_cnpj = achar_coluna(
                leitor.fieldnames,
                [
                    "CNPJ_DETENTOR",
                    "CNPJ",
                    "CNPJ_EMPRESA"
                ]
            )

            col_fabricante = achar_coluna(
                leitor.fieldnames,
                [
                    "NOME_FABRICANTE",
                    "FABRICANTE",
                    "FABRICANTE_LEGAL"
                ]
            )

            col_pais = achar_coluna(
                leitor.fieldnames,
                [
                    "NOME_PAIS_FABRIC",
                    "PAIS_FABRICANTE",
                    "PAIS"
                ]
            )

            col_classe = achar_coluna(
                leitor.fieldnames,
                [
                    "CLASSE_RISCO",
                    "CLASSIFICACAO_RISCO",
                    "CLASSE",
                    "CLASSIFICACAO"
                ]
            )

            col_situacao = achar_coluna(
                leitor.fieldnames,
                [
                    "SITUACAO",
                    "STATUS",
                    "SITUACAO_REGISTRO"
                ]
            )

            if (
                not col_registro
                or not col_produto
            ):
                raise RuntimeError(
                    "Colunas essenciais de "
                    "dispositivos não encontradas."
                )

            total = 0

            for linha in leitor:

                registro = somente_numeros(
                    linha.get(
                        col_registro,
                        ""
                    )
                )

                produto = texto(
                    linha.get(
                        col_produto,
                        ""
                    )
                )

                if not registro or not produto:
                    continue

                item = {
                    "registro": registro,
                    "produto": produto
                }

                if col_processo:
                    item["processo"] = (
                        somente_numeros(
                            linha.get(
                                col_processo,
                                ""
                            )
                        )
                    )

                if col_detentor:
                    item["detentor"] = texto(
                        linha.get(
                            col_detentor,
                            ""
                        )
                    )

                if col_cnpj:
                    item["cnpj"] = (
                        somente_numeros(
                            linha.get(
                                col_cnpj,
                                ""
                            )
                        )
                    )

                if col_fabricante:
                    item["fabricante"] = texto(
                        linha.get(
                            col_fabricante,
                            ""
                        )
                    )

                if col_pais:
                    item["pais"] = texto(
                        linha.get(
                            col_pais,
                            ""
                        )
                    )

                if col_classe:
                    item["classe"] = texto(
                        linha.get(
                            col_classe,
                            ""
                        )
                    )

                if col_situacao:
                    item["situacao"] = texto(
                        linha.get(
                            col_situacao,
                            ""
                        )
                    )

                item = limpar_json(item)

                prefixo = registro[:PREFIXOS_BASE["dispositivos"]]

                grupos[prefixo].append(
                    item
                )

                total += 1

        if total < 1000:
            raise RuntimeError(
                "Base de dispositivos "
                "gerou poucos registros."
            )

        validar_reducao(
            "dispositivos",
            total
        )

        maior = gravar_fragmentos(
            DADOS / "dispositivos",
            grupos
        )

        print(
            "dispositivos:", total, "registros |",
            len(grupos), "fragmentos | prefixo",
            PREFIXOS_BASE["dispositivos"], "| maior",
            f"{maior / 1024:.0f} KB"
        )

        return metadados_base(
            URL_DISPOSITIVOS,
            total,
            len(grupos),
            PREFIXOS_BASE["dispositivos"],
            maior
        )

    finally:
        arquivo.unlink(
            missing_ok=True
        )


# ==================================================
# AFE / AE
# ==================================================

def gerar_afe_ae():

    arquivo = baixar_csv(
        URL_AFE_AE,
        "anvisa_afe_ae_"
    )

    try:
        encoding, delimitador = (
            detectar_configuracao(
                arquivo
            )
        )

        grupos = defaultdict(list)

        with arquivo.open(
            "r",
            encoding=encoding,
            errors="replace",
            newline=""
        ) as f:

            leitor = csv.DictReader(
                f,
                delimiter=delimitador
            )

            if not leitor.fieldnames:
                raise RuntimeError(
                    "CSV AFE/AE sem cabeçalho."
                )

            print(
                "Colunas AFE/AE:",
                leitor.fieldnames
            )

            col_cnpj = achar_coluna(
                leitor.fieldnames,
                [
                    "CNPJ",
                    "CNPJ_EMPRESA",
                    "NU_CNPJ"
                ]
            )

            col_razao = achar_coluna(
                leitor.fieldnames,
                [
                    "RAZAO_SOCIAL",
                    "NOME_EMPRESA",
                    "EMPRESA"
                ]
            )

            col_fantasia = achar_coluna(
                leitor.fieldnames,
                [
                    "NOME_FANTASIA",
                    "NO_FANTASIA",
                    "FANTASIA"
                ]
            )

            col_autorizacao = achar_coluna(
                leitor.fieldnames,
                [
                    "NU_AUTORIZACAO",
                    "NR_AUTORIZACAO",
                    "NO_AUTORIZACAO",
                    "CO_AUTORIZACAO",
                    "NU_AUTORIZACAO_ESPECIAL",
                    "NR_AUTORIZACAO_ESPECIAL",
                    "NUMERO_AUTORIZACAO_ESPECIAL",
                    "AUTORIZACAO_ESPECIAL",
                    "NUMERO_AUTORIZACAO",
                    "NUM_AUTORIZACAO",
                    "NUMERO_AFE",
                    "NU_AFE",
                    "NUMERO_AE",
                    "NU_AE",
                    "NR_AE",
                    "AUTORIZACAO",
                    "AFE",
                    "AE"
                ]
            )

            col_processo = achar_coluna(
                leitor.fieldnames,
                [
                    "NUMERO_PROCESSO",
                    "NU_PROCESSO",
                    "PROCESSO_ANVISA",
                    "PROCESSO"
                ]
            )

            col_tipo = achar_coluna(
                leitor.fieldnames,
                [
                    "TIPO_AUTORIZACAO",
                    "TIPO_AUTORIZACAO_ESPECIAL",
                    "TIPO_AFE",
                    "TIPO_AE",
                    "TIPO"
                ]
            )

            col_classe = achar_coluna(
                leitor.fieldnames,
                [
                    "CLASSE_PRODUTO",
                    "TIPO_PRODUTO",
                    "CATEGORIA_PRODUTO",
                    "CLASSE"
                ]
            )

            col_atividade = achar_coluna(
                leitor.fieldnames,
                [
                    "ATIVIDADE",
                    "ATIVIDADES",
                    "ATIVIDADE_AUTORIZADA"
                ]
            )

            col_situacao = achar_coluna(
                leitor.fieldnames,
                [
                    "SITUACAO",
                    "STATUS"
                ]
            )

            col_data = achar_coluna(
                leitor.fieldnames,
                [
                    "DATA_AUTORIZACAO",
                    "DATA_PUBLICACAO",
                    "DATA_RESOLUCAO",
                    "DATA"
                ]
            )

            col_endereco = achar_coluna(
                leitor.fieldnames,
                [
                    "ENDERECO"
                ]
            )

            col_municipio = achar_coluna(
                leitor.fieldnames,
                [
                    "MUNICIPIO",
                    "CIDADE"
                ]
            )

            col_uf = achar_coluna(
                leitor.fieldnames,
                [
                    "UF",
                    "ESTADO"
                ]
            )

            if not col_cnpj:
                raise RuntimeError(
                    "Coluna de CNPJ da base "
                    "AFE/AE não encontrada."
                )

            total = 0

            for linha in leitor:

                cnpj = somente_numeros(
                    linha.get(
                        col_cnpj,
                        ""
                    )
                )

                if len(cnpj) != 14:
                    continue

                item = {
                    "cnpj": cnpj
                }

                if col_razao:
                    item["razao_social"] = texto(
                        linha.get(
                            col_razao,
                            ""
                        )
                    )

                if col_fantasia:
                    item["nome_fantasia"] = texto(
                        linha.get(
                            col_fantasia,
                            ""
                        )
                    )

                if col_autorizacao:
                    item["autorizacao"] = texto(
                        linha.get(
                            col_autorizacao,
                            ""
                        )
                    )

                if col_processo:
                    item["processo"] = somente_numeros(
                        linha.get(
                            col_processo,
                            ""
                        )
                    )

                if col_tipo:
                    item["tipo"] = texto(
                        linha.get(
                            col_tipo,
                            ""
                        )
                    )

                if col_classe:
                    item["classe"] = texto(
                        linha.get(
                            col_classe,
                            ""
                        )
                    )

                if col_atividade:
                    item["atividade"] = texto(
                        linha.get(
                            col_atividade,
                            ""
                        )
                    )

                if col_situacao:
                    item["situacao"] = texto(
                        linha.get(
                            col_situacao,
                            ""
                        )
                    )

                if col_data:
                    item["data"] = texto(
                        linha.get(
                            col_data,
                            ""
                        )
                    )

                if col_endereco:
                    item["endereco"] = texto(
                        linha.get(
                            col_endereco,
                            ""
                        )
                    )

                if col_municipio:
                    item["municipio"] = texto(
                        linha.get(
                            col_municipio,
                            ""
                        )
                    )

                if col_uf:
                    item["uf"] = texto(
                        linha.get(
                            col_uf,
                            ""
                        )
                    )

                item = limpar_json(item)

                prefixo = cnpj[:PREFIXOS_BASE["afe_ae"]]

                grupos[prefixo].append(
                    item
                )

                total += 1

        if total < 1000:
            raise RuntimeError(
                "Base AFE/AE gerou apenas "
                f"{total} registros."
            )

        validar_reducao(
            "afe_ae",
            total
        )

        maior = gravar_fragmentos(
            DADOS / "afe_ae",
            grupos
        )

        print(
            "afe_ae:", total, "registros |",
            len(grupos), "fragmentos | prefixo",
            PREFIXOS_BASE["afe_ae"], "| maior",
            f"{maior / 1024:.0f} KB"
        )

        return metadados_base(
            URL_AFE_AE,
            total,
            len(grupos),
            PREFIXOS_BASE["afe_ae"],
            maior
        )

    finally:
        arquivo.unlink(
            missing_ok=True
        )


# ==================================================
# MEDICAMENTOS
# ==================================================

def gerar_medicamentos():

    arquivo = baixar_csv(
        URL_MEDICAMENTOS,
        "anvisa_medicamentos_"
    )

    try:
        encoding, delimitador = (
            detectar_configuracao(
                arquivo
            )
        )

        grupos = defaultdict(list)

        with arquivo.open(
            "r",
            encoding=encoding,
            errors="replace",
            newline=""
        ) as f:

            leitor = csv.DictReader(
                f,
                delimiter=delimitador
            )

            if not leitor.fieldnames:
                raise RuntimeError(
                    "CSV de medicamentos "
                    "sem cabeçalho."
                )

            print(
                "Colunas medicamentos:",
                leitor.fieldnames
            )

            col_registro = achar_coluna(
                leitor.fieldnames,
                [
                    "NUMERO_REGISTRO_PRODUTO",
                    "NUMERO_REGISTRO",
                    "REGISTRO_PRODUTO",
                    "REGISTRO"
                ]
            )

            col_produto = achar_coluna(
                leitor.fieldnames,
                [
                    "NOME_PRODUTO",
                    "PRODUTO"
                ]
            )

            col_principio = achar_coluna(
                leitor.fieldnames,
                [
                    "PRINCIPIO_ATIVO",
                    "PRINCÍPIO_ATIVO"
                ]
            )

            col_processo = achar_coluna(
                leitor.fieldnames,
                [
                    "NUMERO_PROCESSO",
                    "PROCESSO"
                ]
            )

            col_empresa = achar_coluna(
                leitor.fieldnames,
                [
                    "EMPRESA_DETENTORA_REGISTRO",
                    "EMPRESA_DETENTORA",
                    "DETENTOR_REGISTRO",
                    "RAZAO_SOCIAL"
                ]
            )

            col_cnpj = achar_coluna(
                leitor.fieldnames,
                [
                    "CNPJ_EMPRESA",
                    "CNPJ_DETENTOR",
                    "CNPJ"
                ]
            )

            col_categoria = achar_coluna(
                leitor.fieldnames,
                [
                    "CATEGORIA_REGULATORIA",
                    "CATEGORIA_REGULATÓRIA",
                    "CATEGORIA"
                ]
            )

            col_classe = achar_coluna(
                leitor.fieldnames,
                [
                    "CLASSE_TERAPEUTICA",
                    "CLASSE_TERAPÊUTICA"
                ]
            )

            col_vencimento = achar_coluna(
                leitor.fieldnames,
                [
                    "DATA_VENCIMENTO_REGISTRO",
                    "VENCIMENTO_REGISTRO",
                    "VENCIMENTO"
                ]
            )

            col_situacao = achar_coluna(
                leitor.fieldnames,
                [
                    "SITUACAO_REGISTRO",
                    "SITUACAO",
                    "STATUS"
                ]
            )

            if (
                not col_registro
                or not col_produto
            ):
                raise RuntimeError(
                    "Não foi possível localizar "
                    "registro e produto na base "
                    "de medicamentos."
                )

            total = 0

            for linha in leitor:

                registro = somente_numeros(
                    linha.get(
                        col_registro,
                        ""
                    )
                )

                produto = texto(
                    linha.get(
                        col_produto,
                        ""
                    )
                )

                if not registro or not produto:
                    continue

                item = {
                    "registro": registro,
                    "produto": produto
                }

                if col_principio:
                    item["principio_ativo"] = texto(
                        linha.get(
                            col_principio,
                            ""
                        )
                    )

                if col_processo:
                    item["processo"] = somente_numeros(
                        linha.get(
                            col_processo,
                            ""
                        )
                    )

                if col_empresa:
                    item["detentor"] = texto(
                        linha.get(
                            col_empresa,
                            ""
                        )
                    )

                if col_cnpj:
                    item["cnpj"] = somente_numeros(
                        linha.get(
                            col_cnpj,
                            ""
                        )
                    )
                elif col_empresa:
                    item["cnpj"] = (
                        extrair_cnpj_item(item)
                    )

                if col_categoria:
                    item["categoria"] = texto(
                        linha.get(
                            col_categoria,
                            ""
                        )
                    )

                if col_classe:
                    item["classe_terapeutica"] = texto(
                        linha.get(
                            col_classe,
                            ""
                        )
                    )

                if col_vencimento:
                    item["vencimento"] = texto(
                        linha.get(
                            col_vencimento,
                            ""
                        )
                    )

                if col_situacao:
                    item["situacao"] = texto(
                        linha.get(
                            col_situacao,
                            ""
                        )
                    )

                item = limpar_json(item)

                prefixo = registro[:PREFIXOS_BASE["medicamentos"]]

                grupos[prefixo].append(
                    item
                )

                total += 1

        if total < 1000:
            raise RuntimeError(
                "Base de medicamentos gerou "
                f"apenas {total} registros."
            )

        validar_reducao(
            "medicamentos",
            total
        )

        maior = gravar_fragmentos(
            DADOS / "medicamentos",
            grupos
        )

        print(
            "medicamentos:", total, "registros |",
            len(grupos), "fragmentos | prefixo",
            PREFIXOS_BASE["medicamentos"], "| maior",
            f"{maior / 1024:.0f} KB"
        )

        return metadados_base(
            URL_MEDICAMENTOS,
            total,
            len(grupos),
            PREFIXOS_BASE["medicamentos"],
            maior
        )

    finally:
        arquivo.unlink(
            missing_ok=True
        )

# ==================================================
# SANEANTES
# ==================================================

def gerar_saneantes():

    arquivo = baixar_csv(
        URL_SANEANTES,
        "anvisa_saneantes_"
    )

    try:
        encoding, delimitador = (
            detectar_configuracao(
                arquivo
            )
        )

        grupos = defaultdict(list)

        with arquivo.open(
            "r",
            encoding=encoding,
            errors="replace",
            newline=""
        ) as f:

            leitor = csv.DictReader(
                f,
                delimiter=delimitador
            )

            if not leitor.fieldnames:
                raise RuntimeError(
                    "CSV de saneantes "
                    "sem cabeçalho."
                )

            print(
                "Colunas saneantes:",
                leitor.fieldnames
            )

            col_registro = achar_coluna(
                leitor.fieldnames,
                [
                    "NU_REGISTRO_PRODUTO",
                    "NUMERO_REGISTRO",
                    "REGISTRO",
                    "NUM_REGISTRO"
                ]
            )

            col_produto = achar_coluna(
                leitor.fieldnames,
                [
                    "NO_PRODUTO",
                    "NOME_PRODUTO",
                    "PRODUTO",
                    "NOME_COMERCIAL"
                ]
            )

            col_processo = achar_coluna(
                leitor.fieldnames,
                [
                    "NU_PROCESSO",
                    "NUMERO_PROCESSO",
                    "PROCESSO"
                ]
            )

            col_empresa = achar_coluna(
                leitor.fieldnames,
                [
                    "NO_RAZAO_SOCIAL_EMPRESA",
                    "RAZAO_SOCIAL",
                    "NO_RAZAO_SOCIAL",
                    "EMPRESA",
                    "DETENTOR"
                ]
            )

            col_cnpj = achar_coluna(
                leitor.fieldnames,
                [
                    "NU_CNPJ_EMPRESA",
                    "CNPJ",
                    "CNPJ_EMPRESA"
                ]
            )

            col_categoria = achar_coluna(
                leitor.fieldnames,
                [
                    "CATEGORIA",
                    "TIPO_PRODUTO",
                    "CLASSE_PRODUTO"
                ]
            )

            col_situacao = achar_coluna(
                leitor.fieldnames,
                [
                    "ST_PRODUTO_ATIVO",
                    "SITUACAO",
                    "STATUS"
                ]
            )

            col_vencimento = achar_coluna(
                leitor.fieldnames,
                [
                    "DT_VENCIMENTO_PRODUTO",
                    "VALIDADE",
                    "DATA_VENCIMENTO",
                    "VENCIMENTO"
                ]
            )
            if (
                not col_registro
                or not col_produto
            ):
                raise RuntimeError(
                    "Não foi possível localizar "
                    "registro e produto na base "
                    "de saneantes."
                )

            total = 0

            for linha in leitor:

                registro = somente_numeros(
                    linha.get(
                        col_registro,
                        ""
                    )
                )

                produto = texto(
                    linha.get(
                        col_produto,
                        ""
                    )
                )

                if not registro or not produto:
                    continue

                item = {
                    "registro": registro,
                    "produto": produto
                }

                if col_processo:
                    item["processo"] = somente_numeros(
                        linha.get(
                            col_processo,
                            ""
                        )
                    )

                if col_empresa:
                    item["detentor"] = texto(
                        linha.get(
                            col_empresa,
                            ""
                        )
                    )

                if col_cnpj:
                    item["cnpj"] = somente_numeros(
                        linha.get(
                            col_cnpj,
                            ""
                        )
                    )

                if col_categoria:
                    item["categoria"] = texto(
                        linha.get(
                            col_categoria,
                            ""
                        )
                    )

                if col_situacao:
                    item["situacao"] = texto(
                        linha.get(
                            col_situacao,
                            ""
                        )
                    )

                if col_vencimento:
                    item["vencimento"] = texto(
                        linha.get(
                            col_vencimento,
                            ""
                        )
                    )

                item = limpar_json(item)

                prefixo = registro[:PREFIXOS_BASE["saneantes"]]

                grupos[prefixo].append(
                    item
                )

                total += 1

        if total < 1000:
            raise RuntimeError(
                "Base de saneantes gerou "
                f"apenas {total} registros."
            )

        validar_reducao(
            "saneantes",
            total
        )

        maior = gravar_fragmentos(
            DADOS / "saneantes",
            grupos
        )

        print(
            "saneantes:", total, "registros |",
            len(grupos), "fragmentos | prefixo",
            PREFIXOS_BASE["saneantes"], "| maior",
            f"{maior / 1024:.0f} KB"
        )

        return metadados_base(
            URL_SANEANTES,
            total,
            len(grupos),
            PREFIXOS_BASE["saneantes"],
            maior
        )

    finally:
        arquivo.unlink(
            missing_ok=True
        )


# ==================================================
# ÍNDICES AUXILIARES DE PRODUTOS
# ==================================================

def gerar_indices_produtos():
    bases = (
        "dispositivos",
        "medicamentos",
        "saneantes"
    )

    processos = defaultdict(
        lambda: defaultdict(set)
    )
    cnpjs = defaultdict(
        lambda: defaultdict(dict)
    )
    autorizacoes = defaultdict(
        lambda: defaultdict(set)
    )

    por_base = {
        nome: {
            "processos": 0,
            "cnpjs": 0
        }
        for nome in bases
    }

    for nome in bases:
        pasta = DADOS / nome

        for caminho in sorted(
            pasta.glob("*.json")
        ):
            with caminho.open(
                "r",
                encoding="utf-8"
            ) as f:
                itens = json.load(f)

            for item in itens:
                registro = somente_numeros(
                    item.get("registro", "")
                )

                if not registro:
                    continue

                referencia = (
                    nome,
                    registro
                )

                processo = somente_numeros(
                    item.get("processo", "")
                )

                if processo:
                    processos[
                        prefixo_processo(
                            processo
                        )
                    ][processo].add(
                        referencia
                    )
                    por_base[nome][
                        "processos"
                    ] += 1

                cnpj = extrair_cnpj_item(
                    item
                )

                if len(cnpj) == 14:
                    resumo = limpar_json({
                        "b": nome,
                        "registro": registro,
                        "produto": item.get(
                            "produto",
                            ""
                        ),
                        "processo": processo,
                        "detentor": item.get(
                            "detentor",
                            ""
                        ),
                        "cnpj": cnpj,
                        "fabricante": item.get(
                            "fabricante",
                            ""
                        ),
                        "pais": item.get(
                            "pais",
                            ""
                        ),
                        "classe": item.get(
                            "classe",
                            ""
                        ),
                        "categoria": item.get(
                            "categoria",
                            ""
                        ),
                        "classe_terapeutica": (
                            item.get(
                                "classe_terapeutica",
                                ""
                            )
                        ),
                        "situacao": item.get(
                            "situacao",
                            ""
                        ),
                        "vencimento": item.get(
                            "vencimento",
                            ""
                        )
                    })
                    chave_resumo = (
                        nome,
                        registro,
                        processo,
                        item.get("produto", "")
                    )
                    cnpjs[
                        cnpj[:PREFIXO_INDICE_CNPJ]
                    ][cnpj][
                        chave_resumo
                    ] = resumo
                    por_base[nome][
                        "cnpjs"
                    ] += 1

    pasta_afe = DADOS / "afe_ae"
    for caminho in sorted(
        pasta_afe.glob("*.json")
    ):
        with caminho.open(
            "r",
            encoding="utf-8"
        ) as f:
            itens = json.load(f)

        for item in itens:
            autorizacao = somente_numeros(
                item.get("autorizacao", "")
            )
            cnpj = somente_numeros(
                item.get("cnpj", "")
            )

            if autorizacao and len(cnpj) == 14:
                autorizacoes[
                    autorizacao[
                        :PREFIXO_INDICE_AUTORIZACAO
                    ]
                ][autorizacao].add(cnpj)

    def preparar(grupos):
        preparados = {}

        for prefixo in sorted(grupos):
            preparados[prefixo] = {
                chave: [
                    {
                        "b": base,
                        "r": registro
                    }
                    for base, registro in sorted(
                        referencias
                    )
                ]
                for chave, referencias in sorted(
                    grupos[prefixo].items()
                )
            }

        return preparados

    processos_prontos = preparar(
        processos
    )

    cnpjs_prontos = {
        prefixo: {
            cnpj: [
                resumo
                for _, resumo in sorted(
                    resumos.items()
                )
            ]
            for cnpj, resumos in sorted(
                grupos.items()
            )
        }
        for prefixo, grupos in sorted(
            cnpjs.items()
        )
    }

    autorizacoes_prontas = {
        prefixo: {
            autorizacao: [
                {"c": cnpj}
                for cnpj in sorted(cnpjs_autorizados)
            ]
            for autorizacao, cnpjs_autorizados in sorted(
                grupos.items()
            )
        }
        for prefixo, grupos in sorted(
            autorizacoes.items()
        )
    }

    gravar_fragmentos(
        DADOS / "indices" / "processos",
        processos_prontos
    )
    gravar_fragmentos(
        DADOS / "indices" / "cnpj_produtos",
        cnpjs_prontos
    )
    gravar_fragmentos(
        DADOS / "indices" / "autorizacoes",
        autorizacoes_prontas
    )

    gerado_em = datetime.now(
        timezone.utc
    ).isoformat()

    return {
        "status": "ok",
        "gerado_em": gerado_em,
        "processos": {
            "status": "ok",
            "fragmentacao": (
                "dígitos 6 a 8 do processo "
                "normalizado"
            ),
            "chaves": sum(
                len(itens)
                for itens in processos_prontos.values()
            ),
            "referencias": sum(
                len(refs)
                for itens in processos_prontos.values()
                for refs in itens.values()
            ),
            "fragmentos": len(
                processos_prontos
            )
        },
        "cnpj_produtos": {
            "status": "ok",
            "prefixo": PREFIXO_INDICE_CNPJ,
            "fragmentacao": (
                "3 primeiros dígitos do CNPJ"
            ),
            "chaves": sum(
                len(itens)
                for itens in cnpjs_prontos.values()
            ),
            "referencias": sum(
                len(refs)
                for itens in cnpjs_prontos.values()
                for refs in itens.values()
            ),
            "fragmentos": len(
                cnpjs_prontos
            )
        },
        "autorizacoes": {
            "status": (
                "ok"
                if autorizacoes_prontas
                else "indisponivel"
            ),
            "prefixo": PREFIXO_INDICE_AUTORIZACAO,
            "observacao": (
                "Índice por número de AFE/AE."
                if autorizacoes_prontas
                else "A fonte aberta não publicou número de autorização reconhecível."
            ),
            "chaves": sum(
                len(itens)
                for itens in autorizacoes_prontas.values()
            ),
            "referencias": sum(
                len(refs)
                for itens in autorizacoes_prontas.values()
                for refs in itens.values()
            ),
            "fragmentos": len(
                autorizacoes_prontas
            )
        },
        "por_base": por_base
    }


# ==================================================
# MANIFEST
# ==================================================

def gerar_manifesto(
    dispositivos,
    afe_ae,
    medicamentos,
    saneantes,
    indices
):

    DADOS.mkdir(
        parents=True,
        exist_ok=True
    )

    manifesto = {
        "versao_esquema": 2,

        "projeto":
        "Base Vigilância Sanitária",

        "gerado_em":
        datetime.now(
            timezone.utc
        ).isoformat(),

        "bases": {
            "dispositivos":
            dispositivos,

            "afe_ae":
            afe_ae,

            "medicamentos":
             medicamentos,

            "saneantes":
            saneantes
        },

        "indices": indices
    }

    with (
        DADOS / "manifest.json"
    ).open(
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            manifesto,
            f,
            ensure_ascii=False,
            indent=2
        )


# ==================================================
# EXECUÇÃO
# ==================================================

if __name__ == "__main__":

    print(
        "=== DISPOSITIVOS ==="
    )

    dispositivos = gerar_dispositivos()

    print(
        "=== AFE / AE ==="
    )

    afe_ae = gerar_afe_ae()

    print(
        "=== MEDICAMENTOS ==="
    )

    medicamentos = gerar_medicamentos()
    print(
    "=== SANEANTES ==="
    )

    saneantes = gerar_saneantes()

    print(
        "=== ÍNDICES AUXILIARES ==="
    )

    indices = gerar_indices_produtos()

    gerar_manifesto(
        dispositivos,
        afe_ae,
        medicamentos,
        saneantes,
        indices
    )

    print(
        "Todas as bases foram "
        "geradas com sucesso."
    )
