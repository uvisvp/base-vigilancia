#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import csv, hashlib, io, json, re, sys, time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader

BASE = Path(__file__).resolve().parent.parent
FONTES = BASE / 'fontes'
TEXTOS = BASE / 'textos'
CATALOGO = FONTES / 'normas.csv'
SAIDA = BASE / 'dados' / 'legislacao_v12'
sys.path.insert(0, str(BASE / 'scripts'))
from estruturar_legislacao import estruturar_texto, slug

HEAD = {
    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/pdf,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'pt-BR,pt;q=0.9,en;q=0.7',
    'Accept-Encoding': 'identity',
    'Connection': 'close',
}

NORMAS = [
    {'norma_id':'rdc-anvisa-22-2014','norma':'RDC 22-2014','grupo':'rdc-anvisa','rotulo':'RDC Anvisa nº 22/2014','url':'https://anvisalegis.datalegis.net/action/ActionDatalegis.php?acao=abrirTextoAto&cod_menu=8542&cod_modulo=310&link=S&numeroAto=00000022&orgao=RDC%2FDC%2FANVISA%2FMS&seqAto=000&tipo=RDC&valorAno=2014','data_fonte':'2014-04-29','status_vigencia':'vigente_com_alteracoes','status_fonte':'AnvisaLegis: Vigente com Alterações','min_chars':9000,'obrig':['RDC Nº 22','SNGPC','Art. 1']},
    {'norma_id':'decreto-estadual-sp-69118-2024','norma':'Decreto Estadual SP 69118-2024','grupo':'decreto-estadual-sp','rotulo':'Decreto Estadual SP nº 69.118/2024','url':'https://www.al.sp.gov.br/repositorio/legislacao/decreto/2024/decreto-69118-09.12.2024.html','data_fonte':'2024-12-09','status_vigencia':'sem_revogacao_expressa','status_fonte':'ALESP: sem revogação expressa','min_chars':12000,'obrig':['DECRETO N° 69.118','Segurança Contra Incêndios','Art. 1']},
    {'norma_id':'lei-municipal-sp-13478-2002','norma':'Lei Municipal SP 13478-2002','grupo':'lei-municipal','rotulo':'Lei Municipal SP nº 13.478/2002 — texto consolidado','url':'https://legislacao.prefeitura.sp.gov.br/lei-13478-de-30-de-dezembro-de-2002','data_fonte':'2002-12-30','status_vigencia':'alterada_parcialmente_inconstitucional_parcialmente_revogada','status_fonte':'Prefeitura de São Paulo: ALTERADO, DECLARADO PARCIALMENTE INCONSTITUCIONAL, REVOGADO(A) PARCIALMENTE','min_chars':30000,'obrig':['LEI Nº 13.478','Sistema de Limpeza Urbana','Art. 1']},
    {'norma_id':'lei-federal-10357-2001','norma':'Lei 10357-2001','grupo':'lei-federal','rotulo':'Lei Federal nº 10.357/2001 — texto consolidado','url':'https://www.planalto.gov.br/ccivil_03/leis/leis_2001/l10357.htm','data_fonte':'2001-12-27','status_vigencia':'sem_revogacao_expressa','status_fonte':'Câmara dos Deputados: não consta revogação expressa; texto consolidado obtido no Planalto','min_chars':10000,'obrig':['10.357','produtos químicos','Art. 1']},
    {'norma_id':'lei-estadual-sp-15266-2013','norma':'Lei Estadual SP 15266-2013','grupo':'lei-estadual-sp','rotulo':'Lei Estadual SP nº 15.266/2013 — texto atualizado','url':'https://www.al.sp.gov.br/repositorio/legislacao/lei/2013/lei-15266-26.12.2013.html','data_fonte':'2013-12-26','status_vigencia':'sem_revogacao_expressa_com_alteracoes','status_fonte':'ALESP: sem revogação expressa; há alterações cadastradas','min_chars':25000,'obrig':['LEI N° 15.266','Taxa de Fiscalização','Art. 1']},
    {'norma_id':'rdc-anvisa-359-2020','norma':'RDC 359-2020','grupo':'rdc-anvisa','rotulo':'RDC Anvisa nº 359/2020','url':'https://anvisalegis.datalegis.net/action/ActionDatalegis.php?acao=abrirTextoAto&cod_menu=9431&cod_modulo=310&link=S&numeroAto=00000359&orgao=RDC%2FDC%2FANVISA%2FMS&seqAto=000&tipo=RDC&valorAno=2020','data_fonte':'2020-03-27','status_vigencia':'vigente_com_alteracoes','status_fonte':'AnvisaLegis: Vigente com Alterações','min_chars':25000,'obrig':['RDC Nº 359','Dossiê de Insumo Farmacêutico Ativo','CADIFA','Art. 2']},
    {'norma_id':'rdc-anvisa-361-2020','norma':'RDC 361-2020','grupo':'rdc-anvisa','rotulo':'RDC Anvisa nº 361/2020','url':'https://anvisalegis.datalegis.net/action/ActionDatalegis.php?acao=detalharAto&cod_menu=8542&cod_modulo=310&desItem=&desItemFim=&nomeTitulo=codigos&numeroAto=00000361&orgao=RDC%2FDC%2FANVISA%2FMS&seqAto=000&tipo=RDC&valorAno=2020','data_fonte':'2020-03-27','status_vigencia':'alterador','status_fonte':'AnvisaLegis: Alterador; Anvisa informa vigência do marco regulatório','min_chars':10000,'obrig':['RDC Nº 361','Dossiê de Insumo Farmacêutico Ativo','CBPF','CADIFA']},
    {
        'norma_id':'rdc-anvisa-57-2009',
        'norma':'RDC 57-2009',
        'grupo':'rdc-anvisa',
        'rotulo':'RDC Anvisa nº 57/2009 — revogada',
        'url':'https://portal.crfsp.org.br/113-juridico/legislacao/1804-resolucao-rdc-no-57-de-18-de-novembro-de-2009.html',
        'fonte_normativa_oficial':'https://bvsms.saude.gov.br/bvs/saudelegis/anvisa/2009/rdc0057_17_11_2009.html',
        'fonte_status':'https://www.gov.br/anvisa/pt-br/setorregulado/regularizacao/insumos/registro-de-ifa-rdc-57-2009-revogada',
        'nota_fonte_texto':'Espelho institucional do CRF-SP utilizado para extração técnica do texto completo, inclusive o Regulamento Técnico. A referência normativa oficial permanece BVS/MS; a situação regulatória é conferida na Anvisa.',
        'data_fonte':'2009-11-17',
        'status_vigencia':'revogada_2021-03-01',
        'status_fonte':'Anvisa: revogada pela RDC 359/2020 a partir de 1º de março de 2021; mantida no v12 para análise de registros legados',
        'min_chars':18000,
        'obrig':['RDC nº 57','REGULAMENTO TÉCNICO PARA REGISTRO DE INSUMOS FARMACÊUTICOS ATIVOS','4. DOCUMENTAÇÃO PARA REGISTRO','6. DOCUMENTAÇÃO PARA RENOVAÇÃO DO REGISTRO'],
        'estruturar_alineas':False,
    },
]


def agora(): return datetime.now(timezone.utc).isoformat()
def sha_b(b): return hashlib.sha256(b).hexdigest()
def sha_t(s): return hashlib.sha256(s.encode()).hexdigest()


def baixar(url):
    err = None
    for i in range(4):
        try:
            r = requests.get(url, headers=HEAD, timeout=(20,120), allow_redirects=True)
            r.raise_for_status()
            if len(r.content) < 500:
                raise RuntimeError('resposta curta')
            return r
        except Exception as e:
            err = e
            if i < 3:
                time.sleep(min(2**i, 8))
    raise RuntimeError(f'Falha ao baixar {url}: {err}')


def limpar_linhas(txt):
    linhas = []
    for ln in txt.splitlines():
        ln = re.sub(r'\s+', ' ', ln).strip()
        if not ln:
            continue
        if ln in {'Voltar','Imprimir','Compartilhar:','Redefinir Cookies'}:
            continue
        ln = re.sub(r'^Artigo\s+(\d+(?:-[A-Z]|[A-Z])?)\s*[º°o]?\s*[-–—]?', r'Art. \1 ', ln, flags=re.I)
        linhas.append(ln)
    return '\n'.join(linhas).strip()


def extrair_html(body):
    soup = BeautifulSoup(body, 'html.parser')
    for x in soup(['script','style','noscript','nav','footer']):
        x.decompose()
    return limpar_linhas(soup.get_text('\n'))


def extrair_pdf(body):
    reader = PdfReader(io.BytesIO(body))
    return limpar_linhas('\n'.join((p.extract_text() or '') for p in reader.pages))


def extrair_resposta(r):
    ctype = (r.headers.get('content-type') or '').lower()
    if r.url.lower().endswith('.pdf') or 'application/pdf' in ctype or r.content[:4] == b'%PDF':
        return extrair_pdf(r.content), 'pdf'
    return extrair_html(r.content), 'html'


def validar(n, txt):
    if len(txt) < n['min_chars']:
        raise RuntimeError(f"{n['norma']}: texto curto ({len(txt)})")
    falt = [x for x in n['obrig'] if x.casefold() not in txt.casefold()]
    if falt:
        raise RuntimeError(f"{n['norma']}: faltam marcadores {falt}")


def garantir_catalogo():
    with CATALOGO.open(encoding='utf-8', newline='') as f:
        rows = list(csv.DictReader(f))
        fields = list(rows[0]) if rows else ['norma_id','grupo','baixar','url','rotulo','observacao']
    por_id = {r['norma_id']: r for r in rows}
    mudou = False
    for n in NORMAS:
        url_catalogo = n.get('fonte_normativa_oficial', n['url'])
        observacao = n.get('nota_fonte_texto','')
        if n['norma_id'] not in por_id:
            novo = {'norma_id':n['norma_id'],'grupo':n['grupo'],'baixar':'sim','url':url_catalogo,'rotulo':n['rotulo'],'observacao':observacao}
            rows.append(novo); por_id[n['norma_id']] = novo; mudou = True
        else:
            r = por_id[n['norma_id']]
            if r.get('url') != url_catalogo or r.get('rotulo') != n['rotulo'] or r.get('observacao','') != observacao:
                r.update(url=url_catalogo, rotulo=n['rotulo'], observacao=observacao)
                mudou = True
    if mudou:
        with CATALOGO.open('w', encoding='utf-8', newline='') as f:
            w = csv.DictWriter(f, fieldnames=fields, lineterminator='\n')
            w.writeheader(); w.writerows(rows)
    return mudou


def normalizar_rt_rdc57(doc):
    if doc.get('norma') != 'RDC 57-2009':
        return doc
    root = 'rdc-57-2009::regulamento-tecnico'
    old_parent = 'rdc-57-2009::artigo::6'
    nos = list(doc.get('nos', []))
    marcador = next((n for n in nos if n.get('tipo') == 'bloco' and str(n.get('texto','')).strip().upper() == 'ANEXO'), None)
    if not marcador:
        raise RuntimeError('RDC 57-2009: marcador ANEXO sem número não localizado')
    ordem_inicio = int(marcador.get('ordem', 0))
    titulo = next((n for n in nos if int(n.get('ordem',0)) > ordem_inicio and str(n.get('texto','')).strip().upper().startswith('REGULAMENTO TÉCNICO PARA REGISTRO DE INSUMOS FARMACÊUTICOS ATIVOS')), None)
    if not titulo:
        raise RuntimeError('RDC 57-2009: título do Regulamento Técnico não localizado')
    remover = {marcador.get('id'), titulo.get('id')}
    nos = [n for n in nos if n.get('id') not in remover]
    for no in nos:
        if int(no.get('ordem',0)) <= ordem_inicio:
            continue
        nid = str(no.get('id') or '')
        pai = str(no.get('pai') or '')
        if nid.startswith(old_parent + '::'):
            no['id'] = root + nid[len(old_parent):]
        if pai == old_parent or pai.startswith(old_parent + '::'):
            no['pai'] = root + pai[len(old_parent):]
    nos.append({
        'id':root,'norma':'RDC 57-2009','anexo':None,'tipo':'regulamento_tecnico','numero':'geral',
        'rotulo':'Regulamento Técnico','texto':str(titulo.get('texto') or '').strip(),'ordem':ordem_inicio,
        'origem_estrutura':'anexo_sem_numero'
    })
    nos.sort(key=lambda n:(int(n.get('ordem',0)), str(n.get('id',''))))
    doc['nos'] = nos
    ids = [n['id'] for n in nos if n.get('estrutural', True)]
    rep = sorted({x for x in ids if ids.count(x) > 1})
    if rep:
        raise RuntimeError(f'RDC 57-2009: IDs duplicados após normalização: {rep[:10]}')
    exigidos = [root + '::item::4-1', root + '::item::6-6']
    falt = [x for x in exigidos if not any(n.get('id') == x for n in nos)]
    if falt:
        raise RuntimeError(f'RDC 57-2009: itens estruturais não encontrados: {falt}')
    doc.setdefault('validacao', {})['regulamento_tecnico'] = {
        'id': root,
        'itens_confirmados': exigidos,
        'vinculo_artigo_6_remanescente': sum(1 for n in nos if int(n.get('ordem',0)) > ordem_inicio and (str(n.get('id','')).startswith(old_parent+'::') or str(n.get('pai','')).startswith(old_parent+'::'))),
    }
    if doc['validacao']['regulamento_tecnico']['vinculo_artigo_6_remanescente']:
        raise RuntimeError('RDC 57-2009: dispositivos do Regulamento Técnico ainda vinculados ao Art. 6')
    return doc


def aplicar_meta(doc, meta, estruturar_alineas=True):
    doc['proveniencia'] = meta
    for no in doc['nos']:
        no['status_vigencia'] = meta['status_vigencia']
        t = no.get('texto','')
        if re.search(r'\b(revogado|revogada)\b', t, re.I):
            no['status_dispositivo'] = 'possivel_revogacao_textual'
        m = re.match(r'^([a-z])\)\s+', t) if no.get('tipo') == 'bloco' else None
        if estruturar_alineas and m and no.get('pai'):
            no.update(tipo='alinea', numero=m.group(1), rotulo=f"Alínea {m.group(1)}", estrutural=True, id=no['pai']+'::alinea::'+m.group(1))
    counts = Counter(x['id'] for x in doc['nos'])
    occ = Counter()
    for no in doc['nos']:
        if counts[no['id']] > 1:
            old = no['id']; occ[old] += 1
            no['id'] = old + f"::ocorrencia-{occ[old]}"
            no['ambiguidade_na_fonte'] = True


def main():
    cat = garantir_catalogo()
    (SAIDA/'normas').mkdir(parents=True, exist_ok=True)
    TEXTOS.mkdir(exist_ok=True)
    man_path = SAIDA/'manifest.json'
    man = json.loads(man_path.read_text(encoding='utf-8')) if man_path.exists() else {'schema':'legislacao-hierarquica-v12','normas':{}}
    rel = {'schema':'relatorio-legislacao-adicional-v1','gerado_em':agora(),'catalogo_atualizado':cat,'normas':[]}
    for n in NORMAS:
        print('Baixando', n['norma'])
        r = baixar(n['url'])
        txt, tipo_fonte = extrair_resposta(r)
        validar(n, txt)
        pasta = FONTES/n['norma_id']; pasta.mkdir(parents=True, exist_ok=True)
        (pasta/f'texto_bruto.{tipo_fonte}').write_bytes(r.content)
        txtp = TEXTOS/f"{n['norma']}--oficial.txt"
        txtp.write_text(txt, encoding='utf-8')
        meta = {
            'norma':n['norma'],
            'fonte_oficial':n.get('fonte_normativa_oficial', n['url']),
            'fonte_texto_utilizada':n['url'],
            'fonte_status':n.get('fonte_status'),
            'nota_fonte_texto':n.get('nota_fonte_texto'),
            'url_final':r.url,
            'consultado_em':agora(),
            'data_fonte':n['data_fonte'],
            'tipo_data_fonte':'data_do_ato; texto consultado em fonte institucional identificada na proveniência',
            'formato_fonte':tipo_fonte,
            'sha256_fonte':sha_b(r.content),
            'sha256_texto':sha_t(txt),
            'status_vigencia':n['status_vigencia'],
            'status_fonte':n['status_fonte'],
            'texto':str(txtp.relative_to(BASE)),
            'data_processamento':agora(),
            'schema':'proveniencia-legislativa-v1',
            'estruturar_alineas':n.get('estruturar_alineas', True),
            'escopo_validacao':'texto estruturado para consulta; alterações/revogações específicas seguem as marcações e fontes oficiais identificadas na proveniência',
        }
        txtp.with_suffix('.meta.json').write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8')
        doc = estruturar_texto(n['norma'], txt)
        if n['norma'] == 'RDC 57-2009':
            doc = normalizar_rt_rdc57(doc)
        aplicar_meta(doc, meta, estruturar_alineas=n.get('estruturar_alineas', True))
        ids = [x['id'] for x in doc['nos'] if x.get('estrutural', True)]
        if len(ids) != len(set(ids)):
            raise RuntimeError(f"{n['norma']}: IDs estruturais repetidos")
        fn = slug(n['norma']) + '.json'
        (SAIDA/'normas'/fn).write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding='utf-8')
        entrada = {'arquivo':fn,'nos':len(doc['nos']),'sha256_texto':doc['sha256_texto'],'proveniencia':meta}
        if n['norma'] == 'RDC 57-2009':
            entrada['regulamento_tecnico'] = doc['validacao']['regulamento_tecnico']
        man['normas'][n['norma']] = entrada
        rel['normas'].append({'norma':n['norma'],'arquivo':fn,'nos':len(doc['nos']),'chars':len(txt),'status_vigencia':n['status_vigencia'],'status_fonte':n['status_fonte'],'fonte_oficial':meta['fonte_oficial'],'fonte_texto_utilizada':n['url'],'formato_fonte':tipo_fonte})
    man['gerado_em'] = agora()
    man_path.write_text(json.dumps(man, ensure_ascii=False, indent=2), encoding='utf-8')
    rel['total_normas_manifest'] = len(man['normas'])
    (SAIDA/'relatorio-legislacao-adicional.json').write_text(json.dumps(rel, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(rel, ensure_ascii=False))


if __name__ == '__main__':
    main()
