from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict
import csv
import json
import re
import shutil
import ssl
import tempfile
import time
import unicodedata
import urllib.error
import urllib.request

BASE = Path(__file__).resolve().parent.parent
DADOS = BASE / "dados"
PASTA = DADOS / "afe_ae"
PASTA_ATIVIDADES = DADOS / "afe_ae_atividades"

FONTE = (
    "https://dados.anvisa.gov.br/dados/"
    "CONSULTAS/EMPRESA_FISCALIZACAO_PRODUTO/"
    "TA_CONSULTA_FUNCIONAMENTO_EMPRESA_NACIONAL.CSV"
)
DICIONARIO = (
    "https://dados.anvisa.gov.br/dados/"
    "CONSULTAS/EMPRESA_FISCALIZACAO_PRODUTO/"
    "Documentacao_e_Dicionario_de_Dados_Certificado_AFE.pdf"
)
PREFIXO = 3
TESTES = ("1.40410-4", "7.35065-7", "0086723", "1339472")

CAMPOS_EXPOSTOS = [
    "cnpj",
    "razao_social",
    "nome_fantasia",
    "autorizacao",
    "autorizacao_nova",
    "processo",
    "tipo",
    "autorizacao_especial",
    "situacao",
    "ativo",
    "data_autorizacao",
    "data_publicacao",
    "data_cancelamento",
    "classe",
    "atividade_tipo",
    "atividade",
    "municipio",
    "uf",
    "cep",
    "endereco",
    "bairro",
    "responsavel_tecnico",
    "responsavel_legal",
    "codigo_municipio_ibge",
    "data_carga_fonte",
    "fonte_base",
]
CAMPOS_FRAGMENTO_PRINCIPAL = [
    campo for campo in CAMPOS_EXPOSTOS if campo != "atividade"
]


def digitos(valor):
    return re.sub(r"\D", "", str(valor or ""))


def canon_num(valor):
    d = digitos(valor)
    return (d.lstrip("0") or "0") if d else ""


def txt(valor):
    return re.sub(r"\s+", " ", str(valor or "").strip())


def token(valor):
    s = (
        unicodedata.normalize("NFKD", txt(valor))
        .encode("ascii", "ignore")
        .decode("ascii")
    )
    return s.upper()


def sim_nao(valor):
    t = token(valor)
    if t in {"S", "SIM", "1", "TRUE", "ATIVO", "ATIVA"}:
        return True
    if t in {"N", "NAO", "0", "FALSE", "INATIVO", "INATIVA"}:
        return False
    return None


def data_iso(v):
    if not v:
        return None
    v = str(v).strip().split(" ")[0]
    try:
        return datetime.strptime(v, "%m/%d/%Y").date().isoformat()
    except ValueError:
        return None


def data_iso_contada(linha, campo_fonte, campo_destino, falhas_datas):
    bruto = txt(linha.get(campo_fonte))
    convertido = data_iso(bruto)
    if bruto and convertido is None:
        falhas_datas[campo_destino] += 1
    return convertido


def baixar_csv(url, tentativas=4):
    ultimo = None
    for n in range(1, tentativas + 1):
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 base-vigilancia"},
        )
        contexto_ssl = ssl._create_unverified_context()
        try:
            tmp = Path(
                tempfile.mkstemp(
                    prefix="afe_ae_oficial_",
                    suffix=".csv",
                )[1]
            )
            with urllib.request.urlopen(
                req,
                timeout=180,
                context=contexto_ssl,
            ) as r, tmp.open("wb") as f:
                shutil.copyfileobj(r, f)
            if tmp.stat().st_size < 1_000_000:
                raise RuntimeError("Arquivo AFE/AE oficial pequeno demais.")
            return tmp
        except (
            urllib.error.URLError,
            urllib.error.HTTPError,
            TimeoutError,
            OSError,
        ) as e:
            ultimo = e
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass
            if n < tentativas:
                time.sleep(10 * n)
    raise RuntimeError(
        f"Falha baixando a base oficial AFE/AE: {ultimo!r}"
    )


def detectar_configuracao(arquivo):
    amostra = arquivo.read_bytes()[:200_000]
    encoding = "latin-1"
    for tentativa in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            amostra.decode(tentativa)
            encoding = tentativa
            break
        except UnicodeDecodeError:
            pass
    texto_amostra = amostra.decode(encoding, errors="replace")
    delimitador = ";"
    try:
        delimitador = csv.Sniffer().sniff(
            texto_amostra,
            delimiters=";,|\t",
        ).delimiter
    except csv.Error:
        pass
    return encoding, delimitador


def carregar_local():
    registros = []
    exato = defaultdict(list)
    proc_cnpj = defaultdict(list)
    aut_cnpj = defaultdict(list)
    cnpj_idx = defaultdict(list)

    for arq in sorted(PASTA.glob("*.json")):
        itens = json.loads(arq.read_text(encoding="utf-8"))
        if not isinstance(itens, list):
            continue
        for item in itens:
            idx = len(registros)
            registros.append(item)
            p = digitos(item.get("processo"))
            a = digitos(item.get("autorizacao"))
            c = digitos(item.get("cnpj"))
            exato[(p, a, c)].append(idx)
            if p and c:
                proc_cnpj[(p, c)].append(idx)
            if a and c:
                aut_cnpj[(a, c)].append(idx)
            if c:
                cnpj_idx[c].append(idx)

    return registros, exato, proc_cnpj, aut_cnpj, cnpj_idx


def candidatos(indices, processo, autorizacao, cnpj):
    exato, proc_cnpj, aut_cnpj, cnpj_idx = indices
    lista = exato.get((processo, autorizacao, cnpj), [])
    if lista:
        return lista, "processo+autorizacao+cnpj"

    if processo and cnpj:
        lista = proc_cnpj.get((processo, cnpj), [])
        if len(lista) == 1:
            return lista, "processo+cnpj"

    if autorizacao and cnpj:
        lista = aut_cnpj.get((autorizacao, cnpj), [])
        if len(lista) == 1:
            return lista, "autorizacao+cnpj"

    if cnpj:
        lista = cnpj_idx.get(cnpj, [])
        if len(lista) == 1:
            return lista, "cnpj_unico"

    return [], ""


def enriquecer_item(item, linha, falhas_datas):
    especial = txt(linha.get("ST_AUTORIZACAO_ESPECIAL"))
    ativo = txt(linha.get("ATIVO"))
    eh_especial = sim_nao(especial)
    esta_ativo = sim_nao(ativo)

    datas = {
        "data_autorizacao": data_iso_contada(
            linha,
            "DT_AUTORIZACAO",
            "data_autorizacao",
            falhas_datas,
        ),
        "data_publicacao": data_iso_contada(
            linha,
            "DT_PUBLICACAO",
            "data_publicacao",
            falhas_datas,
        ),
        "data_cancelamento": data_iso_contada(
            linha,
            "DT_CANCELAMENTO",
            "data_cancelamento",
            falhas_datas,
        ),
        "data_carga_fonte": data_iso_contada(
            linha,
            "DT_CARGA_ETL",
            "data_carga_fonte",
            falhas_datas,
        ),
    }

    valores = {
        "autorizacao_nova": txt(
            linha.get("NU_AUTORIZACAO_NOVO")
        ),
        "autorizacao_especial": especial,
        "ativo": ativo,
        **datas,
        "classe": txt(linha.get("TIPO_PRODUTO")),
        "atividade_tipo": txt(
            linha.get("CO_TIPO_ATIVIDADES")
        ),
        "atividade": txt(linha.get("ATIVIDADES")),
        "nome_fantasia": txt(linha.get("NO_FANTASIA")),
        "municipio": txt(linha.get("CIDADE")),
        "uf": txt(linha.get("UF")),
        "cep": txt(linha.get("NU_CEP")),
        "endereco": txt(linha.get("DS_ENDERECO")),
        "bairro": txt(linha.get("BAIRRO")),
        "responsavel_tecnico": txt(
            linha.get("REPRESENTANTE_TECNICO")
        ),
        "responsavel_legal": txt(
            linha.get("REPRESENTANTE_LEGAL")
        ),
        "codigo_municipio_ibge": txt(
            linha.get("CO_MUNICIPIO_IBGE")
        ),
    }

    if eh_especial is True:
        valores["tipo"] = "AE"
    elif eh_especial is False:
        valores["tipo"] = "AFE"

    if esta_ativo is True:
        valores["situacao"] = "Ativa"
    elif esta_ativo is False:
        valores["situacao"] = "Inativa"

    for campo in datas:
        item.pop(campo, None)

    for campo, valor in valores.items():
        if valor not in ("", None):
            item[campo] = valor

    item["fonte_base"] = "ANVISA_AFE_AE_DADOS_ABERTOS"


def resumo_teste(registros):
    saida = []
    campos = (
        "cnpj",
        "razao_social",
        "nome_fantasia",
        "autorizacao",
        "autorizacao_nova",
        "processo",
        "tipo",
        "autorizacao_especial",
        "situacao",
        "ativo",
        "data_autorizacao",
        "data_publicacao",
        "data_cancelamento",
        "data_carga_fonte",
        "classe",
        "atividade",
        "municipio",
        "uf",
    )

    for entrada in TESTES:
        alvo = canon_num(entrada)
        encontrados = []
        for item in registros:
            ids = {
                canon_num(item.get("autorizacao")),
                canon_num(item.get("autorizacao_nova")),
            }
            ids.discard("")
            if alvo in ids:
                encontrados.append(
                    {
                        campo: item.get(campo)
                        for campo in campos
                        if item.get(campo) not in ("", None)
                    }
                )
        saida.append(
            {
                "entrada": entrada,
                "encontrados": encontrados,
            }
        )
    return saida


def contar(registros, campo):
    return sum(
        1
        for item in registros
        if item.get(campo) not in ("", None, [], {})
    )


def chave_atividade(item):
    return "|".join(
        (
            digitos(item.get("cnpj")),
            digitos(item.get("autorizacao")),
            digitos(item.get("processo")),
        )
    )


def gravar_fragmentos(registros):
    grupos = defaultdict(list)
    atividades = defaultdict(dict)

    for item in registros:
        cnpj = digitos(item.get("cnpj"))
        if len(cnpj) != 14:
            continue

        prefixo = cnpj[:PREFIXO]
        atividade = item.pop("atividade", None)

        if atividade not in ("", None):
            chave = chave_atividade(item)
            existente = atividades[prefixo].get(chave)
            if existente is not None and existente != atividade:
                raise RuntimeError(
                    "Conflito no fragmento de atividade para "
                    f"{chave}."
                )
            atividades[prefixo][chave] = atividade

        grupos[prefixo].append(item)

    PASTA.mkdir(parents=True, exist_ok=True)
    PASTA_ATIVIDADES.mkdir(parents=True, exist_ok=True)

    for antigo in PASTA.glob("*.json"):
        antigo.unlink()
    for antigo in PASTA_ATIVIDADES.glob("*.json"):
        antigo.unlink()

    maior_principal = 0
    for prefixo, itens in grupos.items():
        caminho = PASTA / f"{prefixo}.json"
        caminho.write_text(
            json.dumps(
                itens,
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )
        maior_principal = max(
            maior_principal,
            caminho.stat().st_size,
        )

    maior_atividade = 0
    for prefixo, itens in atividades.items():
        caminho = PASTA_ATIVIDADES / f"{prefixo}.json"
        caminho.write_text(
            json.dumps(
                itens,
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )
        maior_atividade = max(
            maior_atividade,
            caminho.stat().st_size,
        )

    return {
        "fragmentos_principais": len(grupos),
        "fragmentos_atividade": len(atividades),
        "maior_fragmento_principal": maior_principal,
        "maior_fragmento_atividade": maior_atividade,
    }


def main():
    (
        registros,
        exato,
        proc_cnpj,
        aut_cnpj,
        cnpj_idx,
    ) = carregar_local()
    if not registros:
        raise RuntimeError("Base afe_ae local ausente.")

    arquivo = baixar_csv(FONTE)
    enriquecidos = set()
    metodos = defaultdict(int)
    falhas_datas = defaultdict(int)
    linhas_fonte = 0
    sem_vinculo = 0
    ambiguos = 0
    campos_observados = []

    try:
        encoding, delimitador = detectar_configuracao(arquivo)
        with arquivo.open(
            "r",
            encoding=encoding,
            errors="replace",
            newline="",
        ) as f:
            leitor = csv.DictReader(
                f,
                delimiter=delimitador,
            )
            if not leitor.fieldnames:
                raise RuntimeError(
                    "CSV oficial AFE/AE sem cabeçalho."
                )
            campos_observados = list(leitor.fieldnames)

            obrigatorios = {
                "NU_CNPJ",
                "NU_AUTORIZACAO",
                "NU_PROCESSO",
                "ATIVO",
                "ST_AUTORIZACAO_ESPECIAL",
                "DT_PUBLICACAO",
            }
            faltantes = sorted(
                obrigatorios.difference(
                    campos_observados
                )
            )
            if faltantes:
                raise RuntimeError(
                    "Base oficial AFE/AE perdeu campos obrigatórios: "
                    + ", ".join(faltantes)
                )

            indices = (
                exato,
                proc_cnpj,
                aut_cnpj,
                cnpj_idx,
            )

            for linha in leitor:
                linhas_fonte += 1
                p = digitos(linha.get("NU_PROCESSO"))
                a = digitos(linha.get("NU_AUTORIZACAO"))
                c = digitos(linha.get("NU_CNPJ"))
                if len(c) != 14:
                    continue

                lista, metodo = candidatos(
                    indices,
                    p,
                    a,
                    c,
                )
                if not lista:
                    sem_vinculo += 1
                    continue

                if (
                    metodo
                    != "processo+autorizacao+cnpj"
                    and len(lista) != 1
                ):
                    ambiguos += 1
                    continue

                metodos[metodo] += len(lista)
                for idx in lista:
                    enriquecer_item(
                        registros[idx],
                        linha,
                        falhas_datas,
                    )
                    enriquecidos.add(idx)
    finally:
        arquivo.unlink(missing_ok=True)

    cobertura = {
        "total_autorizacoes": len(registros),
        "vinculos_enriquecidos": len(enriquecidos),
        "sem_vinculo_enriquecimento": (
            len(registros) - len(enriquecidos)
        ),
        "com_tipo": contar(registros, "tipo"),
        "com_situacao": contar(
            registros,
            "situacao",
        ),
        "com_data_autorizacao": contar(
            registros,
            "data_autorizacao",
        ),
        "com_data_publicacao": contar(
            registros,
            "data_publicacao",
        ),
        "com_data_cancelamento": contar(
            registros,
            "data_cancelamento",
        ),
        "com_data_carga_fonte": contar(
            registros,
            "data_carga_fonte",
        ),
        "com_atividade": contar(
            registros,
            "atividade",
        ),
        "com_classe": contar(
            registros,
            "classe",
        ),
        "com_autorizacao_nova": contar(
            registros,
            "autorizacao_nova",
        ),
        "afe": sum(
            1
            for item in registros
            if item.get("tipo") == "AFE"
        ),
        "ae": sum(
            1
            for item in registros
            if item.get("tipo") == "AE"
        ),
        "ativas": sum(
            1
            for item in registros
            if item.get("situacao") == "Ativa"
        ),
        "inativas": sum(
            1
            for item in registros
            if item.get("situacao") == "Inativa"
        ),
    }

    casos = resumo_teste(registros)
    (
        DADOS / "afe_ae_casos_teste.json"
    ).write_text(
        json.dumps(
            casos,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    fragmentacao = gravar_fragmentos(registros)

    falhas_datas_completas = {
        campo: falhas_datas.get(campo, 0)
        for campo in (
            "data_autorizacao",
            "data_publicacao",
            "data_cancelamento",
            "data_carga_fonte",
        )
    }
    total_falhas_datas = sum(
        falhas_datas_completas.values()
    )

    agora = datetime.now(timezone.utc).isoformat()
    schema = {
        "versao": 3,
        "gerado_em": agora,
        "fonte_primaria": FONTE,
        "fonte_enriquecimento": FONTE,
        "dicionario_oficial": DICIONARIO,
        "campos_fonte_observados": campos_observados,
        "campos_expostos": CAMPOS_EXPOSTOS,
        "campos_fragmento_principal": (
            CAMPOS_FRAGMENTO_PRINCIPAL
        ),
        "fragmento_atividade": {
            "pasta": "afe_ae_atividades",
            "campo": "atividade",
            "fragmentacao": (
                "3 primeiros dígitos do CNPJ"
            ),
            "chave": "cnpj|autorizacao|processo",
        },
        "datas": {
            "formato_saida": "YYYY-MM-DD",
            "formato_origem_aceito": "MM/DD/YYYY",
            "campos": [
                "data_autorizacao",
                "data_publicacao",
                "data_cancelamento",
                "data_carga_fonte",
            ],
            "falhas_normalizacao": (
                falhas_datas_completas
            ),
            "total_falhas_normalizacao": (
                total_falhas_datas
            ),
        },
        "mapeamento": {
            "tipo": {
                "origem": (
                    "ST_AUTORIZACAO_ESPECIAL"
                ),
                "regra": (
                    "S/Sim = AE; N/Não = AFE, "
                    "conforme dicionário oficial."
                ),
            },
            "situacao": {
                "origem": "ATIVO",
                "regra": (
                    "Sim = Ativa; Não = Inativa, "
                    "conforme dicionário oficial."
                ),
            },
            "data_autorizacao": {
                "origem": "DT_AUTORIZACAO",
                "saida": "ISO 8601 (YYYY-MM-DD)",
            },
            "data_publicacao": {
                "origem": "DT_PUBLICACAO",
                "saida": "ISO 8601 (YYYY-MM-DD)",
            },
            "data_cancelamento": {
                "origem": "DT_CANCELAMENTO",
                "saida": "ISO 8601 (YYYY-MM-DD)",
            },
            "data_carga_fonte": {
                "origem": "DT_CARGA_ETL",
                "saida": "ISO 8601 (YYYY-MM-DD)",
            },
            "autorizacao_nova": {
                "origem": "NU_AUTORIZACAO_NOVO",
            },
            "classe": {
                "origem": "TIPO_PRODUTO",
            },
            "atividade": {
                "origem": "ATIVIDADES",
                "armazenamento": (
                    "fragmento separado "
                    "afe_ae_atividades"
                ),
            },
        },
        "campos_nao_disponiveis_nesta_fonte": [
            "resolucao",
            "ato_publicacao",
            "motivo_situacao_inativa",
            "historico_de_eventos",
        ],
        "regra": (
            "Nenhum tipo AFE/AE, situação ou publicação é "
            "inferido pelo formato do número. O tipo decorre "
            "exclusivamente de ST_AUTORIZACAO_ESPECIAL e a "
            "situação exclusivamente de ATIVO, ambos "
            "documentados pela Anvisa."
        ),
        "linhas_fonte": linhas_fonte,
        "registros_locais": len(registros),
        "vinculos_enriquecidos": len(enriquecidos),
        "linhas_fonte_sem_vinculo": sem_vinculo,
        "vinculos_ambiguos_descartados": ambiguos,
        "metodos_vinculo": dict(
            sorted(metodos.items())
        ),
        "cobertura": cobertura,
        "fragmentacao": fragmentacao,
        "casos_teste": "afe_ae_casos_teste.json",
    }

    (
        DADOS / "afe_ae_schema.json"
    ).write_text(
        json.dumps(
            schema,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    manifest_path = DADOS / "manifest.json"
    manifest = json.loads(
        manifest_path.read_text(encoding="utf-8")
    )
    manifest["versao_esquema"] = 3

    b = (
        manifest.setdefault("bases", {})
        .setdefault("afe_ae", {})
    )
    b["fonte_enriquecimento"] = FONTE
    b["dicionario_oficial"] = DICIONARIO
    b["enriquecimento_gerado_em"] = agora
    b["vinculos_enriquecidos"] = len(
        enriquecidos
    )
    b["schema"] = "afe_ae_schema.json"
    b["casos_teste"] = "afe_ae_casos_teste.json"
    b["campos_expostos"] = CAMPOS_EXPOSTOS
    b["campos_fragmento_principal"] = (
        CAMPOS_FRAGMENTO_PRINCIPAL
    )
    b["fragmento_atividade"] = {
        "pasta": "afe_ae_atividades",
        "campo": "atividade",
        "prefixo": PREFIXO,
        "fragmentacao": (
            "3 primeiros dígitos do CNPJ"
        ),
        "chave": "cnpj|autorizacao|processo",
        **fragmentacao,
    }
    b["campos_enriquecimento"] = [
        "autorizacao_nova",
        "tipo",
        "situacao",
        "data_autorizacao",
        "data_publicacao",
        "data_cancelamento",
        "data_carga_fonte",
        "classe",
        "atividade_tipo",
        "atividade",
        "nome_fantasia",
        "municipio",
        "uf",
        "cep",
        "endereco",
        "bairro",
        "responsavel_tecnico",
        "responsavel_legal",
        "codigo_municipio_ibge",
        "fonte_base",
    ]
    b["datas_iso"] = {
        "formato": "YYYY-MM-DD",
        "campos": [
            "data_autorizacao",
            "data_publicacao",
            "data_cancelamento",
            "data_carga_fonte",
        ],
        "falhas_normalizacao": (
            falhas_datas_completas
        ),
        "total_falhas_normalizacao": (
            total_falhas_datas
        ),
    }
    b["campos_indisponiveis"] = [
        "resolucao",
        "ato_publicacao",
        "historico_de_eventos",
    ]
    b["cobertura_enriquecimento"] = cobertura
    b["regra_enriquecimento"] = (
        "Sem inferência pelo número: tipo e situação vêm "
        "de campos oficiais documentados da própria base "
        "aberta da Anvisa."
    )
    b["maior_fragmento"] = (
        fragmentacao["maior_fragmento_principal"]
    )

    manifest_path.write_text(
        json.dumps(
            manifest,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(
        "AFE/AE enriquecida a partir da base aberta oficial."
    )
    print("Linhas fonte:", linhas_fonte)
    print(
        "Registros locais:",
        len(registros),
    )
    print(
        "Vínculos enriquecidos:",
        len(enriquecidos),
    )
    print(
        "Falhas normalização datas:",
        json.dumps(
            falhas_datas_completas,
            ensure_ascii=False,
        ),
    )
    print(
        "Total falhas normalização datas:",
        total_falhas_datas,
    )
    print(
        "Fragmentação:",
        json.dumps(
            fragmentacao,
            ensure_ascii=False,
        ),
    )
    print(
        "Cobertura:",
        json.dumps(
            cobertura,
            ensure_ascii=False,
        ),
    )
    print(
        "Casos de teste:",
        json.dumps(
            casos,
            ensure_ascii=False,
        ),
    )


if __name__ == "__main__":
    main()
