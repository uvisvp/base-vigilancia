from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict
import csv
import json
import re
import urllib.request
import tempfile
import shutil
import ssl

BASE = Path(__file__).resolve().parent.parent
DADOS = BASE / "dados"

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


def gravar_fragmentos(destino, grupos):
    destino.mkdir(
        parents=True,
        exist_ok=True
    )

    for antigo in destino.glob("*.json"):
        antigo.unlink()

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

                prefixo = registro[:3]

                grupos[prefixo].append(
                    item
                )

                total += 1

        if total < 1000:
            raise RuntimeError(
                "Base de dispositivos "
                "gerou poucos registros."
            )

        gravar_fragmentos(
            DADOS / "dispositivos",
            grupos
        )

        return {
            "fonte": URL_DISPOSITIVOS,
            "registros": total,
            "fragmentos": len(grupos),
            "atualizado_em":
            datetime.now(
                timezone.utc
            ).isoformat()
        }

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
                    "FANTASIA"
                ]
            )

            col_autorizacao = achar_coluna(
                leitor.fieldnames,
                [
                    "NUMERO_AUTORIZACAO",
                    "NUM_AUTORIZACAO",
                    "AUTORIZACAO",
                    "AFE"
                ]
            )

            col_tipo = achar_coluna(
                leitor.fieldnames,
                [
                    "TIPO_AUTORIZACAO",
                    "TIPO_AFE",
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

                prefixo = cnpj[:3]

                grupos[prefixo].append(
                    item
                )

                total += 1

        if total < 1000:
            raise RuntimeError(
                "Base AFE/AE gerou apenas "
                f"{total} registros."
            )

        gravar_fragmentos(
            DADOS / "afe_ae",
            grupos
        )

        return {
            "fonte": URL_AFE_AE,
            "registros": total,
            "fragmentos": len(grupos),
            "atualizado_em":
            datetime.now(
                timezone.utc
            ).isoformat()
        }

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

                prefixo = registro[:3]

                grupos[prefixo].append(
                    item
                )

                total += 1

        if total < 1000:
            raise RuntimeError(
                "Base de medicamentos gerou "
                f"apenas {total} registros."
            )

        gravar_fragmentos(
            DADOS / "medicamentos",
            grupos
        )

        return {
            "fonte": URL_MEDICAMENTOS,
            "registros": total,
            "fragmentos": len(grupos),
            "atualizado_em":
            datetime.now(
                timezone.utc
            ).isoformat()
        }

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
                    "NUMERO_REGISTRO",
                    "REGISTRO",
                    "NUM_REGISTRO",
                    "NUMERO_REGISTRO_PRODUTO"
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

            col_empresa = achar_coluna(
                leitor.fieldnames,
                [
                    "RAZAO_SOCIAL",
                    "EMPRESA",
                    "DETENTOR",
                    "EMPRESA_DETENTORA"
                ]
            )

            col_cnpj = achar_coluna(
                leitor.fieldnames,
                [
                    "CNPJ",
                    "CNPJ_EMPRESA",
                    "CNPJ_DETENTOR"
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
                    "SITUACAO",
                    "STATUS",
                    "SITUACAO_REGISTRO"
                ]
            )

            col_vencimento = achar_coluna(
                leitor.fieldnames,
                [
                    "VALIDADE",
                    "DATA_VENCIMENTO",
                    "VENCIMENTO",
                    "DATA_VENCIMENTO_REGISTRO"
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

                prefixo = registro[:3]

                grupos[prefixo].append(
                    item
                )

                total += 1

        if total < 1000:
            raise RuntimeError(
                "Base de saneantes gerou "
                f"apenas {total} registros."
            )

        gravar_fragmentos(
            DADOS / "saneantes",
            grupos
        )

        return {
            "fonte": URL_SANEANTES,
            "registros": total,
            "fragmentos": len(grupos),
            "atualizado_em":
            datetime.now(
                timezone.utc
            ).isoformat()
        }

    finally:
        arquivo.unlink(
            missing_ok=True
        )
# ==================================================
# MANIFEST
# ==================================================

def gerar_manifesto(
    dispositivos,
    afe_ae,
    medicamentos,
    saneantes
):

    DADOS.mkdir(
        parents=True,
        exist_ok=True
    )

    manifesto = {
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
        }
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
    gerar_manifesto(
    dispositivos,
    afe_ae,
    medicamentos,
    saneantes
)

    print(
        "Todas as bases foram "
        "geradas com sucesso."
    )
