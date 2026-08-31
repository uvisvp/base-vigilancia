from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from threading import Lock
from urllib.parse import urlencode
import gzip
import hashlib
import json
import os
import re
import shutil
import tempfile
import time
import urllib.error
import urllib.request


BASE = Path(__file__).resolve().parent.parent
DADOS = BASE / "dados"
PASTA_BASE = DADOS / "produtos_irregulares"
MANIFESTO = DADOS / "manifest.json"

PASTAS_INDICES = {
    "cnpj": DADOS / "indices" / "irregulares_cnpj",
    "registro": DADOS / "indices" / "irregulares_registro",
    "lote": DADOS / "indices" / "irregulares_lote",
}

API = (
    "https://api-gateway.prd.apps.anvisa.gov.br/"
    "consultas-externas-api/api/v1"
)
TOKEN_URL = (
    "https://acesso.prd.apps.anvisa.gov.br/auth/"
    "realms/externo/protocol/openid-connect/token"
)
FONTE = "https://api.anvisa.gov.br/consultas-externas/dossie-doc"

VERSAO = "2026-08-31-produtos-irregulares-v2"
TIPOS_PRODUTO = "6,2,15,1,8,12,3"
ITENS_POR_PAGINA = 300
MAX_TRABALHADORES = 3
LIMITE_QUEDA = 0.90
LIMITE_DETALHES = 0.90


class ErroAPI(RuntimeError):
    def __init__(self, mensagem, status=0):
        super().__init__(mensagem)
        self.status = status


def agora_iso():
    return datetime.now(timezone.utc).isoformat()


def somente_numeros(valor):
    return re.sub(r"\D", "", str(valor or ""))


def normalizar_chave(valor):
    texto = limpar_texto(valor).casefold()
    texto = (
        texto.replace("á", "a")
        .replace("à", "a")
        .replace("â", "a")
        .replace("ã", "a")
        .replace("ä", "a")
        .replace("é", "e")
        .replace("è", "e")
        .replace("ê", "e")
        .replace("ë", "e")
        .replace("í", "i")
        .replace("ì", "i")
        .replace("î", "i")
        .replace("ï", "i")
        .replace("ó", "o")
        .replace("ò", "o")
        .replace("ô", "o")
        .replace("õ", "o")
        .replace("ö", "o")
        .replace("ú", "u")
        .replace("ù", "u")
        .replace("û", "u")
        .replace("ü", "u")
        .replace("ç", "c")
    )
    return re.sub(r"[^a-z0-9]", "", texto)


def limpar_texto(valor):
    if valor is None:
        return ""
    texto = str(valor)
    substituicoes = {
        "N¿o": "Não",
        "n¿o": "não",
        "NÃ£o": "Não",
        "nÃ£o": "não",
        "Ã§": "ç",
        "Ã£": "ã",
        "Ã¡": "á",
        "Ã©": "é",
        "Ãª": "ê",
        "Ã­": "í",
        "Ã³": "ó",
        "Ãµ": "õ",
        "Ãº": "ú",
    }
    for errado, certo in substituicoes.items():
        texto = texto.replace(errado, certo)
    texto = unescape(texto)
    texto = re.sub(r"<br\s*/?>", " ", texto, flags=re.IGNORECASE)
    texto = re.sub(r"<[^>]+>", " ", texto)
    return re.sub(r"\s+", " ", texto).strip()


def data_iso(valor):
    if valor in (None, ""):
        return ""
    try:
        numero = float(valor)
        if numero > 10_000_000_000:
            numero /= 1000
        return datetime.fromtimestamp(
            numero,
            tz=timezone.utc,
        ).isoformat()
    except (TypeError, ValueError, OSError, OverflowError):
        return limpar_texto(valor)


def limpar_json(valor):
    if isinstance(valor, dict):
        resultado = {}
        for chave, item in valor.items():
            limpo = limpar_json(item)
            if limpo not in (None, "", [], {}):
                resultado[chave] = limpo
        return resultado
    if isinstance(valor, list):
        return [
            item_limpo
            for item in valor
            if (item_limpo := limpar_json(item))
            not in (None, "", [], {})
        ]
    if isinstance(valor, str):
        return limpar_texto(valor)
    return valor


def gravar_json(caminho, dados, identado=False):
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(
        json.dumps(
            dados,
            ensure_ascii=False,
            indent=2 if identado else None,
            separators=None if identado else (",", ":"),
            sort_keys=not identado,
        ),
        encoding="utf-8",
    )
    return caminho.stat().st_size


def hash_resumo(resumo):
    corpo = json.dumps(
        resumo,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(corpo).hexdigest()


def processo_do_item(item):
    processo = item.get("processo") or {}
    if isinstance(processo, dict):
        processo = processo.get("numero")
    return somente_numeros(processo)


def fragmento_processo(processo):
    numero = somente_numeros(processo)
    return numero[5:8] if len(numero) >= 8 else numero[:3]


class ClienteAnvisa:
    def __init__(self):
        self.client_id = os.environ.get("ANVISA_CLIENT_ID", "").strip()
        self.client_secret = os.environ.get(
            "ANVISA_CLIENT_SECRET",
            "",
        ).strip()
        if not self.client_id or not self.client_secret:
            raise RuntimeError(
                "Configure ANVISA_CLIENT_ID e ANVISA_CLIENT_SECRET "
                "nos Secrets do GitHub Actions."
            )
        self._token = ""
        self._expira_em = 0.0
        self._lock = Lock()

    def token(self, forcar=False):
        with self._lock:
            if (
                not forcar
                and self._token
                and time.monotonic() < self._expira_em - 120
            ):
                return self._token

            corpo = urlencode({
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            }).encode("utf-8")
            pedido = urllib.request.Request(
                TOKEN_URL,
                data=corpo,
                headers={
                    "Accept": "application/json",
                    "Content-Type": (
                        "application/x-www-form-urlencoded"
                    ),
                    "User-Agent": "Base-Vigilancia/1.0",
                },
                method="POST",
            )
            try:
                with urllib.request.urlopen(
                    pedido,
                    timeout=180,
                ) as resposta:
                    dados = json.loads(
                        resposta.read().decode("utf-8")
                    )
            except urllib.error.HTTPError as erro:
                texto = erro.read().decode(
                    "utf-8",
                    errors="replace",
                )
                raise ErroAPI(
                    "Falha ao obter token: "
                    f"HTTP {erro.code}; {texto[:300]}",
                    erro.code,
                ) from erro

            token = dados.get("access_token")
            if not token:
                raise ErroAPI(
                    "A Anvisa não devolveu access_token."
                )
            validade = int(dados.get("expires_in") or 1500)
            self._token = token
            self._expira_em = time.monotonic() + validade
            print(
                "Token temporário renovado; validade:",
                validade,
                "segundos.",
            )
            return token

    def json(self, url, metodo="GET", dados=None, tentativas=6):
        ultimo = None
        renovou_apos_401 = False

        for tentativa in range(1, tentativas + 1):
            corpo = None
            headers = {
                "Accept": "application/json",
                "Accept-Encoding": "gzip",
                "Authorization": f"Bearer {self.token()}",
                "User-Agent": "Base-Vigilancia/1.0",
            }
            if dados is not None:
                corpo = json.dumps(
                    dados,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode("utf-8")
                headers["Content-Type"] = (
                    "application/json;charset=UTF-8"
                )

            pedido = urllib.request.Request(
                url,
                data=corpo,
                headers=headers,
                method=metodo,
            )
            try:
                with urllib.request.urlopen(
                    pedido,
                    timeout=180,
                ) as resposta:
                    conteudo = resposta.read()
                    if "gzip" in resposta.headers.get(
                        "Content-Encoding",
                        "",
                    ).lower():
                        conteudo = gzip.decompress(conteudo)
                    return json.loads(
                        conteudo.decode("utf-8")
                    )
            except urllib.error.HTTPError as erro:
                texto = erro.read()
                if "gzip" in erro.headers.get(
                    "Content-Encoding",
                    "",
                ).lower():
                    try:
                        texto = gzip.decompress(texto)
                    except OSError:
                        pass
                previa = texto.decode(
                    "utf-8",
                    errors="replace",
                )[:300]

                if erro.code == 401 and not renovou_apos_401:
                    self.token(forcar=True)
                    renovou_apos_401 = True
                    continue
                if erro.code == 404:
                    raise ErroAPI(
                        f"Recurso não encontrado: {url}",
                        404,
                    ) from erro
                if erro.code not in (
                    408,
                    429,
                    500,
                    502,
                    503,
                    504,
                ):
                    raise ErroAPI(
                        f"HTTP {erro.code}: {previa}",
                        erro.code,
                    ) from erro
                ultimo = ErroAPI(
                    f"HTTP temporário {erro.code}: {previa}",
                    erro.code,
                )
            except (
                urllib.error.URLError,
                TimeoutError,
                OSError,
                json.JSONDecodeError,
            ) as erro:
                ultimo = erro

            if tentativa < tentativas:
                espera = min(60, 4 * (2 ** (tentativa - 1)))
                time.sleep(espera)

        raise ErroAPI(
            "Falha após novas tentativas: " + repr(ultimo),
            getattr(ultimo, "status", 0),
        )


def consultar_resumos(cliente):
    resumos = {}
    ids_dossie = set()
    total_elementos = 0
    paginas_consultadas = 0

    def pontuacao_resumo(item):
        try:
            atualizado = int(item.get("dataAtualizacao") or 0)
        except (TypeError, ValueError):
            atualizado = 0
        try:
            id_dossie = int(item.get("idDossie") or 0)
        except (TypeError, ValueError):
            id_dossie = 0
        return atualizado, id_dossie

    def executar_passagem(tipo_assunto, ordem):
        nonlocal total_elementos, paginas_consultadas

        pagina = 1
        total_paginas = None
        total_tipo = None
        ids_antes = len(ids_dossie)

        while total_paginas is None or pagina <= total_paginas:
            resposta = cliente.json(
                f"{API}/dossie/",
                metodo="POST",
                dados={
                    # O contrato OpenAPI atual usa size e column.
                    # count é mantido por compatibilidade com a
                    # documentação antiga do mesmo endpoint.
                    "sorting": {"processo": ordem},
                    "column": "processo",
                    "order": ordem,
                    "page": pagina,
                    "size": ITENS_POR_PAGINA,
                    "count": ITENS_POR_PAGINA,
                    "filter": {
                        "tipoAssunto": tipo_assunto,
                        "tiposProduto": TIPOS_PRODUTO,
                    },
                },
            )
            if not isinstance(resposta, dict):
                raise RuntimeError(
                    "A busca de dossiês não devolveu um objeto JSON."
                )

            conteudo = resposta.get("content") or []
            if not isinstance(conteudo, list):
                raise RuntimeError(
                    "A busca de dossiês não devolveu content em lista."
                )

            total_paginas = int(resposta.get("totalPages") or 0)
            informado = int(resposta.get("totalElements") or 0)
            if total_tipo is None:
                total_tipo = informado
                total_elementos += informado
            elif informado != total_tipo:
                raise RuntimeError(
                    "A quantidade da fonte mudou durante a paginação "
                    f"do assunto {tipo_assunto}: "
                    f"{total_tipo} -> {informado}."
                )

            numero_resposta = int(resposta.get("number") or 0)
            if numero_resposta != pagina - 1:
                raise RuntimeError(
                    "A API devolveu uma página diferente da solicitada: "
                    f"solicitada {pagina}, recebida "
                    f"{numero_resposta + 1}."
                )

            for item in conteudo:
                if not isinstance(item, dict):
                    continue

                id_dossie = item.get("idDossie")
                if id_dossie not in (None, ""):
                    ids_dossie.add(str(id_dossie))

                processo = processo_do_item(item)
                if not processo:
                    continue

                anterior = resumos.get(processo)
                if (
                    anterior is None
                    or pontuacao_resumo(item)
                    > pontuacao_resumo(anterior)
                ):
                    resumos[processo] = item

            paginas_consultadas += 1
            print(
                "Assunto",
                tipo_assunto,
                "| ordem",
                ordem,
                "| página",
                pagina,
                "de",
                total_paginas,
                "| IDs únicos:",
                len(ids_dossie),
                "| processos únicos:",
                len(resumos),
            )
            if resposta.get("last") is True:
                break
            pagina += 1

        ids_novos = len(ids_dossie) - ids_antes
        return int(total_tipo or 0), ids_novos

    # 2 = produtos irregulares; 3 = produtos falsificados.
    # As consultas separadas evitam a paginação instável observada
    # quando o filtro 1 ("todos") é usado.
    totais_tipos = []
    for tipo_assunto in ("2", "3"):
        total_tipo, ids_novos = executar_passagem(
            tipo_assunto,
            "ASC",
        )
        totais_tipos.append((tipo_assunto, total_tipo))

        # Segunda passagem, em ordem inversa, somente se a primeira
        # não cobriu praticamente todos os IDs informados pela fonte.
        if total_tipo and ids_novos < total_tipo * 0.98:
            print(
                "Cobertura incompleta no assunto",
                tipo_assunto,
                f"({ids_novos}/{total_tipo}).",
                "Repetindo em ordem inversa.",
            )
            executar_passagem(tipo_assunto, "DESC")

    if total_elementos < 1000:
        raise RuntimeError(
            "A API informou apenas "
            f"{total_elementos} dossiês. Publicação cancelada."
        )

    quantidade_unica = len(ids_dossie) if ids_dossie else len(resumos)
    if quantidade_unica < total_elementos * 0.98:
        raise RuntimeError(
            "Foram recuperados apenas "
            f"{quantidade_unica} IDs únicos de "
            f"{total_elementos} dossiês informados pela fonte."
        )
    if len(resumos) < 1000:
        raise RuntimeError(
            "Foram recuperados apenas "
            f"{len(resumos)} processos únicos."
        )

    print(
        "Cobertura final:",
        quantidade_unica,
        "IDs únicos de",
        total_elementos,
        "| processos únicos:",
        len(resumos),
        "| por assunto:",
        totais_tipos,
    )
    return resumos, total_elementos, paginas_consultadas

def carregar_existentes():
    registros = {}
    if not PASTA_BASE.exists():
        return registros

    for arquivo in sorted(PASTA_BASE.glob("*.json")):
        if arquivo.name in ("manifest.json", "catalogo.json"):
            continue
        try:
            dados = json.loads(arquivo.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as erro:
            raise RuntimeError(
                f"Fragmento publicado inválido: {arquivo}"
            ) from erro
        if not isinstance(dados, dict):
            raise RuntimeError(
                f"Fragmento publicado não é mapa: {arquivo}"
            )
        for processo, item in dados.items():
            if isinstance(item, dict):
                registros[somente_numeros(processo)] = item
    return registros


def mapear_empresa(valor):
    if not isinstance(valor, dict):
        return {}
    return limpar_json({
        "cnpj": somente_numeros(valor.get("cnpj")),
        "razao_social": valor.get("razaoSocial"),
        "endereco": valor.get("endereco"),
        "municipio": valor.get("cidade"),
        "uf": valor.get("uf"),
        "pais": valor.get("pais"),
    })


def mapear_assunto(valor):
    if not isinstance(valor, dict):
        return {}
    return limpar_json({
        "codigo": valor.get("codigo"),
        "descricao": valor.get("descricao"),
    })


def mapear_produtos(valor):
    if not isinstance(valor, list):
        return []
    produtos = []
    for item in valor:
        if not isinstance(item, dict):
            continue
        produtos.append(limpar_json({
            "registro": somente_numeros(item.get("registro")),
            "produto": item.get("produto"),
            "lotes": item.get("lotes"),
            "data_lote_inicial": data_iso(
                item.get("dataLoteInicial")
            ),
            "data_fabricacao": data_iso(
                item.get("dataFabricacao")
            ),
            "processo_produto": somente_numeros(
                item.get("processoProduto")
            ),
        }))
    return [item for item in produtos if item]


def mapear_status_acoes(valor):
    if not isinstance(valor, list):
        return []
    saida = []
    for item in valor:
        if not isinstance(item, dict):
            continue
        detalhes = []
        for detalhe in item.get("detalhes") or []:
            if isinstance(detalhe, dict):
                detalhes.append(limpar_json({
                    "acao": detalhe.get("acao"),
                    "atividade": detalhe.get("atividade"),
                    "expediente": detalhe.get("expediente"),
                    "motivo_suspensao": detalhe.get(
                        "motivoSuspensao"
                    ),
                }))
        saida.append(limpar_json({
            "status": item.get("statusAcao"),
            "descricao": item.get("descricaoAcoes"),
            "detalhes": detalhes,
        }))
    return [item for item in saida if item]


def mapear_medidas(valor):
    if not isinstance(valor, list):
        return []
    medidas = []
    for item in valor:
        if not isinstance(item, dict):
            continue
        medidas.append(limpar_json({
            "expediente": item.get("expediente"),
            "acoes_atividades": item.get("acoesAtividades") or [],
            "status_acoes": mapear_status_acoes(
                item.get("statusAcoesMedidaCautelars")
            ),
            "situacao_medida": item.get("situacaoMedidaCautelar"),
            "situacao_documento": item.get("situacaoDocumento"),
            "numero_dou": item.get("numeroDOU"),
            "data_publicacao": data_iso(item.get("dataPublicacao")),
            "numero_resolucao": item.get("numeroResolucao"),
            "data_resolucao": data_iso(item.get("dataResolucao")),
            "assunto": mapear_assunto(item.get("assunto")),
            "motivacao": item.get("motivacao"),
        }))
    return [item for item in medidas if item]


def resumo_basico(processo, resumo, gerado_em, status):
    tipo = resumo.get("tipoProduto") or {}
    risco = resumo.get("risco") or {}
    return limpar_json({
        "processo": processo,
        "id_dossie": resumo.get("idDossie"),
        "empresa": mapear_empresa(resumo.get("empresa")),
        "laboratorio": mapear_empresa(resumo.get("laboratorio")),
        "tipo_produto": tipo.get("descricao"),
        "codigo_tipo_produto": tipo.get("codigo"),
        "risco": risco.get("descricao"),
        "codigo_risco": risco.get("codigo"),
        "produto_resumo": resumo.get("produtosConcatenados"),
        "acoes_resumo": resumo.get("acoesAtividadesConcatenaos"),
        "total_medidas": resumo.get("totalMedidasCautelares"),
        "data_ultima_medida": data_iso(
            resumo.get("dataUltimaMedidaCautelar")
        ),
        "data_atualizacao": data_iso(resumo.get("dataAtualizacao")),
        "detalhe_status": status,
        "presente_na_fonte": True,
        "consultado_em": gerado_em,
    })


def mapear_detalhe(processo, resumo, detalhe, gerado_em):
    base = resumo_basico(
        processo,
        resumo,
        gerado_em,
        "ok",
    )
    tipo = detalhe.get("tipoProduto") or {}
    risco = detalhe.get("risco") or {}
    base.update(limpar_json({
        "id_dossie": detalhe.get("idDossie") or base.get("id_dossie"),
        "empresa": mapear_empresa(detalhe.get("empresa"))
        or base.get("empresa"),
        "laboratorio": mapear_empresa(detalhe.get("laboratorio"))
        or base.get("laboratorio"),
        "tipo_produto": tipo.get("descricao")
        or base.get("tipo_produto"),
        "codigo_tipo_produto": tipo.get("codigo")
        or base.get("codigo_tipo_produto"),
        "risco": risco.get("descricao") or base.get("risco"),
        "codigo_risco": risco.get("codigo")
        or base.get("codigo_risco"),
        "produtos": mapear_produtos(detalhe.get("produtos")),
        "infracao": detalhe.get("infracao"),
        "situacao_investigacao": detalhe.get("situacaoInvestigacao"),
        "prova_processual_apensa": detalhe.get(
            "provaProcessualApensa"
        ),
        "assunto": mapear_assunto(detalhe.get("assunto")),
        "medidas": mapear_medidas(detalhe.get("medidasCautelares")),
    }))
    base["controle"] = {
        "resumo_hash": hash_resumo(resumo),
        "data_atualizacao_ms": resumo.get("dataAtualizacao"),
    }
    return limpar_json(base)


def forcar_detalhes():
    return os.environ.get(
        "PRODUTOS_IRREGULARES_FORCAR_DETALHES",
        "",
    ).strip().casefold() in ("1", "true", "sim", "yes")


def atualizar_registros(cliente, resumos, existentes, gerado_em):
    registros = {}
    pendentes = []
    reutilizados = 0
    for processo, resumo in sorted(resumos.items()):
        anterior = existentes.get(processo)
        hash_atual = hash_resumo(resumo)
        hash_anterior = (
            (anterior or {}).get("controle", {}).get("resumo_hash")
        )
        if (
            anterior
            and not forcar_detalhes()
            and hash_anterior == hash_atual
            and anterior.get("detalhe_status") == "ok"
        ):
            item = dict(anterior)
            item["presente_na_fonte"] = True
            registros[processo] = item
            reutilizados += 1
        else:
            pendentes.append((processo, resumo, anterior))

    print(
        "Detalhes reutilizados:",
        reutilizados,
        "| detalhes a consultar:",
        len(pendentes),
    )

    erros = []

    def consultar(tarefa):
        processo, resumo, anterior = tarefa
        try:
            detalhe = cliente.json(f"{API}/dossie/{processo}")
            if not isinstance(detalhe, dict):
                raise ErroAPI("Detalhe não é objeto JSON.")
            return (
                processo,
                mapear_detalhe(
                    processo,
                    resumo,
                    detalhe,
                    gerado_em,
                ),
                "",
            )
        except ErroAPI as erro:
            if anterior:
                item = dict(anterior)
                item["presente_na_fonte"] = True
                item["detalhe_status"] = "desatualizado"
                item["erro_atualizacao"] = str(erro)[:300]
            else:
                status = (
                    "nao_encontrado"
                    if erro.status == 404
                    else "erro_temporario"
                )
                item = resumo_basico(
                    processo,
                    resumo,
                    gerado_em,
                    status,
                )
                item["erro_atualizacao"] = str(erro)[:300]
            return processo, item, str(erro)

    with ThreadPoolExecutor(
        max_workers=MAX_TRABALHADORES
    ) as executor:
        futuros = [executor.submit(consultar, item) for item in pendentes]
        for numero, futuro in enumerate(as_completed(futuros), start=1):
            processo, item, erro = futuro.result()
            registros[processo] = item
            if erro:
                erros.append({"processo": processo, "erro": erro[:300]})
            if numero % 50 == 0 or numero == len(pendentes):
                print(
                    "Detalhes processados:",
                    numero,
                    "de",
                    len(pendentes),
                    "| erros:",
                    len(erros),
                )

    ausentes = 0
    for processo, anterior in existentes.items():
        if processo in resumos:
            continue
        item = dict(anterior)
        item["presente_na_fonte"] = False
        item.setdefault("ausente_desde", gerado_em)
        registros[processo] = item
        ausentes += 1

    return registros, reutilizados, len(pendentes), erros, ausentes


def chaves_lote(valor):
    texto = limpar_texto(valor)
    if not texto:
        return set()
    candidatos = {normalizar_chave(texto)}
    for parte in re.split(r"[,;\n\s]+", texto):
        chave = normalizar_chave(parte)
        if len(chave) >= 3:
            candidatos.add(chave)
    ignorar = {
        "todos",
        "todas",
        "lote",
        "lotes",
        "todososlotes",
        "naoinformado",
    }
    return {
        item
        for item in candidatos
        if len(item) >= 3 and item not in ignorar
    }


def nomes_produtos(item):
    nomes = []
    for produto in item.get("produtos") or []:
        nome = limpar_texto(produto.get("produto"))
        if nome and nome not in nomes:
            nomes.append(nome)
    resumo = limpar_texto(item.get("produto_resumo"))
    if resumo and resumo not in nomes:
        nomes.append(resumo)
    return nomes


def construir_publicacao(registros, gerado_em):
    fragmentos = {}
    indice_cnpj = {}
    indice_registro = {}
    indice_lote = {}
    catalogo = []

    for processo, item in sorted(registros.items()):
        fragmentos.setdefault(
            fragmento_processo(processo),
            {},
        )[processo] = item

        empresa = item.get("empresa") or {}
        cnpj = somente_numeros(empresa.get("cnpj"))
        if len(cnpj) == 14:
            indice_cnpj.setdefault(cnpj[:3], {}).setdefault(
                cnpj,
                [],
            ).append(processo)

        lotes_item = []
        registros_item = []
        for produto in item.get("produtos") or []:
            registro = somente_numeros(produto.get("registro"))
            if registro:
                registros_item.append(registro)
                indice_registro.setdefault(
                    registro[:3],
                    {},
                ).setdefault(registro, []).append(processo)

            lote_original = limpar_texto(produto.get("lotes"))
            if lote_original:
                lotes_item.append(lote_original)
            for lote in chaves_lote(lote_original):
                indice_lote.setdefault(lote[:2], {}).setdefault(
                    lote,
                    [],
                ).append(processo)

        catalogo.append(limpar_json({
            "processo": processo,
            "tipo_produto": item.get("tipo_produto"),
            "risco": item.get("risco"),
            "cnpj": cnpj,
            "empresa": empresa.get("razao_social"),
            "produtos": nomes_produtos(item),
            "registros": sorted(set(registros_item)),
            "lotes": sorted(set(lotes_item)),
            "acoes": item.get("acoes_resumo"),
            "data_ultima_medida": item.get("data_ultima_medida"),
            "presente_na_fonte": item.get("presente_na_fonte"),
        }))

    for indice in (indice_cnpj, indice_registro, indice_lote):
        for mapa in indice.values():
            for chave, referencias in mapa.items():
                mapa[chave] = sorted(set(referencias))

    return {
        "fragmentos": fragmentos,
        "cnpj": indice_cnpj,
        "registro": indice_registro,
        "lote": indice_lote,
        "catalogo": {
            "gerado_em": gerado_em,
            "registros": catalogo,
        },
    }


def publicar(registros, publicacao, metadados):
    temporario = Path(
        tempfile.mkdtemp(prefix=".irregulares_", dir=DADOS)
    )
    try:
        pasta_base = temporario / "produtos_irregulares"
        maiores = {
            "base": 0,
            "cnpj": 0,
            "registro": 0,
            "lote": 0,
        }

        for shard, mapa in sorted(publicacao["fragmentos"].items()):
            tamanho = gravar_json(pasta_base / f"{shard}.json", mapa)
            maiores["base"] = max(maiores["base"], tamanho)

        gravar_json(
            pasta_base / "catalogo.json",
            publicacao["catalogo"],
        )
        gravar_json(
            pasta_base / "manifest.json",
            metadados,
            identado=True,
        )

        estagios_indices = {}
        for nome in ("cnpj", "registro", "lote"):
            pasta = temporario / f"irregulares_{nome}"
            estagios_indices[nome] = pasta
            for shard, mapa in sorted(publicacao[nome].items()):
                tamanho = gravar_json(pasta / f"{shard}.json", mapa)
                maiores[nome] = max(maiores[nome], tamanho)

        alvos = [(pasta_base, PASTA_BASE)] + [
            (estagios_indices[nome], PASTAS_INDICES[nome])
            for nome in ("cnpj", "registro", "lote")
        ]
        for origem, destino in alvos:
            destino.parent.mkdir(parents=True, exist_ok=True)
            if destino.exists():
                shutil.rmtree(destino)
            origem.rename(destino)

        return maiores
    finally:
        shutil.rmtree(temporario, ignore_errors=True)


def atualizar_manifesto(metadados, publicacao, maiores):
    if MANIFESTO.exists():
        manifesto = json.loads(MANIFESTO.read_text(encoding="utf-8"))
    else:
        manifesto = {
            "versao_esquema": 2,
            "projeto": "Base Vigilância Sanitária",
            "bases": {},
            "indices": {},
        }
    if not isinstance(manifesto, dict):
        raise RuntimeError("Manifesto principal inválido.")

    manifesto["gerado_em"] = metadados["gerado_em"]
    bases = manifesto.setdefault("bases", {})
    indices = manifesto.setdefault("indices", {})
    base_meta = dict(metadados)
    base_meta.update({
        "maior_fragmento": maiores["base"],
        "catalogo": "produtos_irregulares/catalogo.json",
    })
    bases["produtos_irregulares"] = base_meta
    indices["produtos_irregulares"] = {
        "status": "ok",
        "processo": {
            "formato": "mapa processo para dossiê",
            "fragmentos": len(publicacao["fragmentos"]),
            "fragmentacao": "dígitos 6 a 8 do processo",
        },
        "cnpj": {
            "chaves": sum(len(x) for x in publicacao["cnpj"].values()),
            "fragmentos": len(publicacao["cnpj"]),
            "prefixo": 3,
            "maior_fragmento": maiores["cnpj"],
        },
        "registro": {
            "chaves": sum(
                len(x) for x in publicacao["registro"].values()
            ),
            "fragmentos": len(publicacao["registro"]),
            "prefixo": 3,
            "maior_fragmento": maiores["registro"],
        },
        "lote": {
            "chaves": sum(len(x) for x in publicacao["lote"].values()),
            "fragmentos": len(publicacao["lote"]),
            "prefixo": 2,
            "normalizacao": "somente caracteres alfanuméricos",
            "maior_fragmento": maiores["lote"],
        },
    }
    gravar_json(MANIFESTO, manifesto, identado=True)


def main():
    print("Versão do gerador:", VERSAO)
    gerado_em = agora_iso()
    cliente = ClienteAnvisa()
    existentes = carregar_existentes()
    print("Dossiês publicados anteriormente:", len(existentes))

    resumos, total_fonte, paginas = consultar_resumos(cliente)
    presentes_anteriores = sum(
        1
        for item in existentes.values()
        if item.get("presente_na_fonte", True)
    )
    if (
        presentes_anteriores
        and len(resumos) < presentes_anteriores * LIMITE_QUEDA
    ):
        raise RuntimeError(
            "A fonte caiu de "
            f"{presentes_anteriores} para {len(resumos)} dossiês. "
            "Publicação cancelada para proteger a base."
        )

    registros, reutilizados, consultados, erros, ausentes = (
        atualizar_registros(
            cliente,
            resumos,
            existentes,
            gerado_em,
        )
    )
    detalhes_ok = sum(
        1
        for processo in resumos
        if registros.get(processo, {}).get("detalhe_status") == "ok"
    )
    if detalhes_ok < len(resumos) * LIMITE_DETALHES:
        raise RuntimeError(
            "Somente "
            f"{detalhes_ok} de {len(resumos)} dossiês possuem "
            "detalhe válido. Publicação cancelada."
        )

    publicacao = construir_publicacao(registros, gerado_em)
    metadados = {
        "status": "ok",
        "fonte": FONTE,
        "tipo_fonte": "API autenticada da Anvisa",
        "gerado_em": gerado_em,
        "atualizado_em": gerado_em,
        "versao_gerador": VERSAO,
        "registros": len(registros),
        "presentes_na_fonte": len(resumos),
        "ausentes_na_fonte": ausentes,
        "detalhes_validos": detalhes_ok,
        "detalhes_reutilizados": reutilizados,
        "detalhes_consultados": consultados,
        "erros_detalhe": len(erros),
        "total_informado_fonte": total_fonte,
        "paginas_consultadas": paginas,
        "fragmentos": len(publicacao["fragmentos"]),
        "chave": "processo",
        "fragmentacao": "dígitos 6 a 8 do processo normalizado",
        "campos_excluidos": [
            "resolução CBPF",
            "validade de certificado CBPF",
            "HTML bruto da motivação",
        ],
    }
    maiores = publicar(registros, publicacao, metadados)
    atualizar_manifesto(metadados, publicacao, maiores)

    print("Produtos irregulares gerados com sucesso.")
    print("Registros:", len(registros))
    print("Presentes na fonte:", len(resumos))
    print("Detalhes válidos:", detalhes_ok)
    print("Detalhes reutilizados:", reutilizados)
    print("Detalhes consultados:", consultados)
    print("Erros de detalhe:", len(erros))
    print("Fragmentos:", len(publicacao["fragmentos"]))
    print("Maior fragmento:", round(maiores["base"] / 1024), "KB")


if __name__ == "__main__":
    main()
