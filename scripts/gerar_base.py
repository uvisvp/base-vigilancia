from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict
import csv
import json
import re
import urllib.request
import ssl
import tempfile
import shutil

BASE = Path(__file__).resolve().parent.parent
DADOS = BASE / "dados"

URL_DISPOSITIVOS = "https://dados.anvisa.gov.br/dados/TA_PRODUTO_SAUDE_SITE.csv"


def somente_numeros(valor):
    return re.sub(r"\D", "", str(valor or ""))


def texto(valor):
    return re.sub(r"\s+", " ", str(valor or "").strip())


def achar_coluna(cabecalho, possibilidades):
    mapa = {
        re.sub(r"[^A-Z0-9]", "", c.upper()): c
        for c in cabecalho
        if c
    }

    for nome in possibilidades:
        chave = re.sub(r"[^A-Z0-9]", "", nome.upper())
        if chave in mapa:
            return mapa[chave]

    return None


def baixar_csv():
    print("Baixando base de dispositivos médicos da Anvisa...")

    temporario = Path(
        tempfile.mkstemp(
            prefix="anvisa_dispositivos_",
            suffix=".csv"
        )[1]
    )

    requisicao = urllib.request.Request(
        URL_DISPOSITIVOS,
        headers={
            "User-Agent": "Mozilla/5.0 base-vigilancia"
        }
    )

        contexto_ssl = ssl._create_unverified_context()

    with urllib.request.urlopen(
        requisicao,
        timeout=180,
        context=contexto_ssl
    ) as resposta, temporario.open("wb") as arquivo:

    print(
        "Arquivo baixado:",
        temporario.stat().st_size,
        "bytes"
    )

    if temporario.stat().st_size < 100000:
        raise RuntimeError(
            "A base baixada é pequena demais. "
            "Atualização cancelada por segurança."
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

    return encoding, delimitador


def gerar_dispositivos():
    arquivo = baixar_csv()

    try:
        encoding, delimitador = detectar_configuracao(
            arquivo
        )

        destino = DADOS / "dispositivos"
        destino.mkdir(
            parents=True,
            exist_ok=True
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
                    "O CSV não possui cabeçalho."
                )

            print(
                "Colunas encontradas:",
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

            if not col_registro or not col_produto:
                raise RuntimeError(
                    "Não foi possível localizar "
                    "as colunas essenciais de "
                    "registro e produto."
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

                if col_detentor:
                    item["detentor"] = texto(
                        linha.get(
                            col_detentor,
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

                prefixo = registro[:3]

                grupos[prefixo].append(
                    item
                )

                total += 1

        if total < 1000:
            raise RuntimeError(
                f"Apenas {total} registros foram "
                "processados. Atualização cancelada."
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

        return {
            "fonte": URL_DISPOSITIVOS,
            "registros": total,
            "fragmentos": len(grupos),
            "atualizado_em": datetime.now(
                timezone.utc
            ).isoformat()
        }

    finally:
        arquivo.unlink(
            missing_ok=True
        )


def gerar_manifesto(resultado):
    DADOS.mkdir(
        parents=True,
        exist_ok=True
    )

    manifesto = {
        "projeto": "Base Vigilância Sanitária",
        "gerado_em": datetime.now(
            timezone.utc
        ).isoformat(),
        "bases": {
            "dispositivos": resultado
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


if __name__ == "__main__":
    resultado = gerar_dispositivos()
    gerar_manifesto(resultado)

    print(
        "Base de dispositivos gerada com sucesso."
    )
