"""Cadastro Nacional de Estabelecimentos de Saúde (CNES) do município de São Paulo.

Fonte: base mensal completa do CNES no FTP do DATASUS
(ftp://ftp.datasus.gov.br/cnes/BASE_DE_DADOS_CNES_AAAAMM.ZIP, ~750 MB, publicada
por volta do dia 15 do mês seguinte). A API de dados abertos do Ministério da Saúde
não serve ao app: não permite chamada do navegador (sem CORS), ignora o filtro por
CNPJ e não traz equipamentos, serviços nem licença sanitária.

Publica, só para os municípios de MUNICIPIOS (código IBGE de 6 dígitos):
- cnes/estabelecimentos/<3 primeiros dígitos do CNES>.json: {cnes: estabelecimento}
- cnes/cnpj/<3 primeiros dígitos do CNPJ>.json: {cnpj: [cnes, ...]}, pelo CNPJ
  próprio do estabelecimento
- cnes/mantenedora/<3 primeiros dígitos do CNPJ>.json: {cnpj: [cnes, ...]}, pelo
  CNPJ da mantenedora (a Prefeitura mantém mais de mil unidades: índice à parte,
  para a busca pelo CNPJ próprio não carregar todas)
- cnes/manifest.json e a entrada "cnes" no manifesto principal

Não publica CPF (estabelecimento de pessoa física e diretor clínico) nem dados
de profissionais.
"""
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
import csv
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import urllib.request
import zipfile

BASE = Path(__file__).resolve().parent.parent
DADOS = BASE / "dados"
DESTINO = DADOS / "cnes"
FTP = "ftp://ftp.datasus.gov.br/cnes/"
VERSAO = "2026-10-20-cnes-v1"
MUNICIPIOS = [m.strip() for m in os.environ.get("CNES_MUNICIPIOS", "355030").split(",") if m.strip()]
LIMITE_QUEDA = 0.90

csv.field_size_limit(10_000_000)


def digitos(valor):
    return re.sub(r"\D", "", str(valor or ""))


def texto(valor):
    return re.sub(r"\s+", " ", str(valor or "")).strip()


def gravar_json(caminho, dados, identado=False):
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(
        json.dumps(dados, ensure_ascii=False, indent=2 if identado else None,
                   separators=None if identado else (",", ":")),
        encoding="utf-8",
    )


def limpo(d):
    return {k: v for k, v in d.items() if v not in (None, "", [], {})}


def codigo(valor):
    """Código sem espaços e sem zeros à esquerda ("08" e "8" são o mesmo motivo)."""
    v = texto(valor)
    return v.lstrip("0") or "0" if v.isdigit() else v


def data_br(valor):
    """DD/MM/AAAA para AAAA-MM-DD."""
    m = re.match(r"^(\d{2})/(\d{2})/(\d{4})", texto(valor))
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else ""


def ultimo_arquivo():
    arquivo = os.environ.get("CNES_ZIP", "").strip()
    if arquivo:
        m = re.search(r"(\d{6})", Path(arquivo).name)
        return Path(arquivo), m.group(1) if m else ""
    with urllib.request.urlopen(FTP, timeout=120) as resposta:
        lista = resposta.read().decode("latin-1")
    nomes = sorted(set(re.findall(r"BASE_DE_DADOS_CNES_(\d{6})\.ZIP", lista, re.I)))
    if not nomes:
        raise RuntimeError("Nenhuma BASE_DE_DADOS_CNES_AAAAMM.ZIP no FTP do DATASUS.")
    competencia = nomes[-1]
    destino = Path(tempfile.gettempdir()) / f"BASE_DE_DADOS_CNES_{competencia}.ZIP"
    url = f"{FTP}BASE_DE_DADOS_CNES_{competencia}.ZIP"
    # O FTP do DATASUS derruba conexões longas: curl com retomada (-C -) até o ZIP ficar íntegro.
    for tentativa in range(1, 7):
        if destino.exists() and zipfile.is_zipfile(destino):
            break
        print("Baixando", competencia, "| tentativa", tentativa)
        subprocess.run(["curl", "-sS", "--retry", "3", "--retry-delay", "15", "-C", "-",
                        "-m", "3000", "-o", str(destino), url], check=False)
    if not zipfile.is_zipfile(destino):
        raise RuntimeError(f"Não foi possível baixar {url} completo.")
    print("Arquivo:", destino, round(destino.stat().st_size / 2**20), "MB")
    return destino, competencia


class Base:
    def __init__(self, caminho):
        self.zip = zipfile.ZipFile(caminho)
        self.nomes = self.zip.namelist()

    def membro(self, tabela):
        padrao = re.compile(rf"^(.*/)?{re.escape(tabela)}\d*\.csv$", re.I)
        return next((n for n in self.nomes if padrao.match(n)), None)

    def linhas(self, tabela):
        nome = self.membro(tabela)
        if not nome:
            print("AVISO: tabela ausente na base:", tabela)
            return
        with self.zip.open(nome) as bruto:
            leitor = csv.reader(io.TextIOWrapper(bruto, encoding="latin-1", newline=""), delimiter=";")
            cabecalho = [re.sub(r"^TO_CHAR\((?:A\.)?(\w+),.*$", r"\1", c) for c in next(leitor)]
            for linha in leitor:
                yield dict(zip(cabecalho, linha))

    def descricoes(self, tabela, n=1):
        """Tabela de apoio: as n primeiras colunas (códigos) -> primeira coluna DS_/NO_.

        Pela posição, porque os nomes variam entre a tabela de apoio e a de uso
        (CO_MOTIVO_DESAB x CO_MOTIVO_DESATIVACAO, CO_SERVICO x CO_SERVICO_ESPECIALIZADO)."""
        mapa, amostra = {}, None
        for linha in self.linhas(tabela) or []:
            colunas = list(linha)
            coluna = next((c for c in colunas[n:] if c.startswith(("DS_", "NO_"))), None)
            if coluna:
                mapa[tuple(codigo(linha[c]) for c in colunas[:n])] = texto(linha[coluna])
                amostra = amostra or (colunas[:n], coluna, list(mapa.items())[:3])
        print("Tabela de apoio", tabela, len(mapa), "códigos", amostra or "")
        return mapa


def carregar(base):
    tipos = base.descricoes("tbTipoUnidade")
    turnos = base.descricoes("tbTurnoAtendimento")
    naturezas = base.descricoes("tbNaturezaJuridica")
    motivos = base.descricoes("tbMotivoDesativacao")
    orgaos = base.descricoes("tbOrgaoEmissor")
    estab = {}
    diagnostico = defaultdict(Counter)
    for x in base.linhas("tbEstabelecimento"):
        unidade = texto(x.get("CO_UNIDADE"))
        if unidade[:6] not in MUNICIPIOS:
            continue
        cnes = texto(x.get("CO_CNES")).zfill(7)
        for campo in ("TP_LIC_SANI", "TP_ORGAO_EXPEDIDOR", "TP_GESTAO", "CO_MOTIVO_DESAB", "TP_PFPJ"):
            diagnostico[campo][texto(x.get(campo))] += 1
        motivo = texto(x.get("CO_MOTIVO_DESAB"))
        cnpj = digitos(x.get("NU_CNPJ"))
        estab[unidade] = limpo({
            "cnes": cnes,
            "razao_social": texto(x.get("NO_RAZAO_SOCIAL")),
            "nome_fantasia": texto(x.get("NO_FANTASIA")),
            "cnpj": cnpj if len(cnpj) == 14 else "",
            "cnpj_mantenedora": digitos(x.get("NU_CNPJ_MANTENEDORA")),
            "pessoa": {"1": "física", "3": "jurídica"}.get(texto(x.get("TP_PFPJ")), ""),
            "tipo_unidade": tipos.get((codigo(x.get("TP_UNIDADE")),), texto(x.get("TP_UNIDADE"))),
            "logradouro": texto(x.get("NO_LOGRADOURO")),
            "numero": texto(x.get("NU_ENDERECO")),
            "complemento": texto(x.get("NO_COMPLEMENTO")),
            "bairro": texto(x.get("NO_BAIRRO")),
            "cep": digitos(x.get("CO_CEP")),
            "codigo_municipio": unidade[:6],
            "telefone": texto(x.get("NU_TELEFONE")),
            "email": texto(x.get("NO_EMAIL")).lower(),
            "natureza_juridica": naturezas.get((codigo(x.get("CO_NATUREZA_JUR")),), texto(x.get("CO_NATUREZA_JUR"))),
            "gestao": {"M": "municipal", "E": "estadual", "D": "dupla", "S": "sem gestão"}.get(texto(x.get("TP_GESTAO")), texto(x.get("TP_GESTAO"))),
            "turno": turnos.get((codigo(x.get("CO_TURNO_ATENDIMENTO")),), ""),
            "licenca_sanitaria": limpo({
                "numero": texto(x.get("NU_ALVARA")),
                "data_expedicao": data_br(x.get("DT_EXPEDICAO")),
                "validade": data_br(x.get("DT_VAL_LIC_SANI")),
                "orgao_expedidor": orgaos.get((codigo(x.get("TP_ORGAO_EXPEDIDOR")),), "") if texto(x.get("TP_ORGAO_EXPEDIDOR")) else "",
                "codigo_orgao_expedidor": texto(x.get("TP_ORGAO_EXPEDIDOR")),
                "codigo_tipo": texto(x.get("TP_LIC_SANI")),
            }),
            "registro_diretor_clinico": texto(x.get("REG_DIRETORCLN")),
            "situacao": ("desativado — " + motivos.get((codigo(motivo),), "motivo " + motivo).lower()) if motivo else "ativo",
            "data_atualizacao": data_br(x.get("DT_ATUALIZACAO")),
        })
    print("Estabelecimentos nos municípios", MUNICIPIOS, ":", len(estab))
    for campo, contagem in diagnostico.items():
        print("Valores de", campo, dict(contagem.most_common(12)))

    equipamentos = base.descricoes("tbEquipamento", 2)
    tipos_equip = base.descricoes("tbTipoEquipamento")
    for x in base.linhas("rlEstabEquipamento") or []:
        alvo = estab.get(texto(x.get("CO_UNIDADE")))
        if not alvo:
            continue
        chave = (codigo(x.get("CO_EQUIPAMENTO")), codigo(x.get("CO_TIPO_EQUIPAMENTO")))
        alvo.setdefault("equipamentos", []).append(limpo({
            "equipamento": equipamentos.get(chave, "código " + chave[0]),
            "tipo": tipos_equip.get((chave[1],), ""),
            "existentes": int(digitos(x.get("QT_EXISTENTE")) or 0),
            "em_uso": int(digitos(x.get("QT_USO")) or 0),
            "sus": texto(x.get("TP_SUS")) == "1",
        }))

    servicos = base.descricoes("tbServicoEspecializado")
    classes = base.descricoes("tbClassificacaoServico", 2)
    for x in base.linhas("rlEstabServClass") or []:
        alvo = estab.get(texto(x.get("CO_UNIDADE")))
        if not alvo or texto(x.get("ST_ATIVO_SN")).upper() == "N":
            continue
        servico, classe = codigo(x.get("CO_SERVICO")), codigo(x.get("CO_CLASSIFICACAO"))
        nome = " — ".join(filter(None, [servicos.get((servico,), "serviço " + servico), classes.get((servico, classe), "")]))
        lista = alvo.setdefault("servicos", [])
        if nome not in lista:
            lista.append(nome)
    return estab


def publicar(estab, competencia):
    por_cnes = defaultdict(dict)
    por_cnpj, por_mant = defaultdict(lambda: defaultdict(list)), defaultdict(lambda: defaultdict(list))
    for item in estab.values():
        por_cnes[item["cnes"][:3]][item["cnes"]] = item
        for chave, indice in ((item.get("cnpj"), por_cnpj), (item.get("cnpj_mantenedora"), por_mant)):
            if chave and len(chave) == 14 and item["cnes"] not in indice[chave[:3]][chave]:
                indice[chave[:3]][chave].append(item["cnes"])
    temporario = Path(tempfile.mkdtemp(prefix=".cnes_", dir=DADOS))
    try:
        for shard, mapa in por_cnes.items():
            gravar_json(temporario / "estabelecimentos" / f"{shard}.json", dict(sorted(mapa.items())))
        for pasta, indice in (("cnpj", por_cnpj), ("mantenedora", por_mant)):
            for shard, mapa in indice.items():
                gravar_json(temporario / pasta / f"{shard}.json", {k: sorted(v) for k, v in sorted(mapa.items())})
        meta = {
            "status": "ok",
            "fonte": f"{FTP}BASE_DE_DADOS_CNES_{competencia}.ZIP",
            "tipo_fonte": "Base mensal do CNES (DATASUS/Ministério da Saúde)",
            "competencia": f"{competencia[4:]}/{competencia[:4]}" if len(competencia) == 6 else competencia,
            "gerado_em": datetime.now(timezone.utc).isoformat(),
            "versao_gerador": VERSAO,
            "municipios": MUNICIPIOS,
            "registros": len(estab),
            "ativos": sum(1 for x in estab.values() if x.get("situacao") == "ativo"),
            "com_cnpj": sum(1 for x in estab.values() if x.get("cnpj")),
            "com_equipamentos": sum(1 for x in estab.values() if x.get("equipamentos")),
            "com_licenca_sanitaria": sum(1 for x in estab.values() if (x.get("licenca_sanitaria") or {}).get("numero")),
            "fragmentos_estabelecimentos": len(por_cnes),
            "fragmentos_cnpj": len(por_cnpj),
            "fragmentos_mantenedora": len(por_mant),
            "chave": "CNES (7 dígitos)",
            "fragmentacao": "3 primeiros dígitos do CNES; índices por CNPJ próprio (cnpj/) e da mantenedora (mantenedora/), 3 primeiros dígitos",
            "limitacao": "Cadastro declarado pelo estabelecimento e pelo gestor; pode estar desatualizado. "
                         "Não prova funcionamento regular. Sem CPF e sem dados de profissionais.",
        }
        gravar_json(temporario / "manifest.json", meta, identado=True)
        if DESTINO.exists():
            shutil.rmtree(DESTINO)
        temporario.rename(DESTINO)
    except Exception:
        shutil.rmtree(temporario, ignore_errors=True)
        raise
    manifesto_path = DADOS / "manifest.json"
    manifesto = json.loads(manifesto_path.read_text(encoding="utf-8"))
    manifesto.setdefault("bases", {})["cnes"] = dict(meta, arquivo_manifesto="cnes/manifest.json")
    gravar_json(manifesto_path, manifesto)
    return meta


def main():
    print("Versão do gerador:", VERSAO)
    anterior = DESTINO / "manifest.json"
    anteriores = json.loads(anterior.read_text(encoding="utf-8")).get("registros", 0) if anterior.exists() else 0
    caminho, competencia = ultimo_arquivo()
    base = Base(caminho)
    print("Competência:", competencia, "| tabelas na base:", len(base.nomes))
    print("Tabelas de apoio:", sorted(n for n in base.nomes if re.match(r"^tb", n, re.I) and base.zip.getinfo(n).file_size < 2_000_000))
    estab = carregar(base)
    if anteriores and len(estab) < anteriores * LIMITE_QUEDA:
        raise RuntimeError(f"O CNES caiu de {anteriores} para {len(estab)} estabelecimentos. Publicação cancelada.")
    if len(estab) < 100:
        raise RuntimeError(f"Somente {len(estab)} estabelecimentos; publicação cancelada.")
    meta = publicar(estab, competencia)
    print(json.dumps(meta, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
