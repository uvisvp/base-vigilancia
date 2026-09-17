#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import csv, hashlib, json, re, sys, time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import requests
from bs4 import BeautifulSoup

BASE=Path(__file__).resolve().parent.parent
FONTES=BASE/'fontes'; TEXTOS=BASE/'textos'; CATALOGO=FONTES/'normas.csv'; SAIDA=BASE/'dados'/'legislacao_v12'
sys.path.insert(0,str(BASE/'scripts'))
from estruturar_legislacao import estruturar_texto, slug

HEAD={'User-Agent':'Mozilla/5.0 base-vigilancia/1.0','Accept-Language':'pt-BR,pt;q=0.9'}
NORMAS=[
 {'norma_id':'rdc-anvisa-22-2014','norma':'RDC 22-2014','grupo':'rdc-anvisa','rotulo':'RDC Anvisa nº 22/2014','url':'https://anvisalegis.datalegis.net/action/ActionDatalegis.php?acao=abrirTextoAto&cod_menu=8542&cod_modulo=310&link=S&numeroAto=00000022&orgao=RDC%2FDC%2FANVISA%2FMS&seqAto=000&tipo=RDC&valorAno=2014','data_fonte':'2014-04-29','status_vigencia':'vigente_com_alteracoes','status_fonte':'AnvisaLegis: Vigente com Alterações','min_chars':9000,'obrig':['RDC Nº 22','SNGPC','Art. 1']},
 {'norma_id':'decreto-estadual-sp-69118-2024','norma':'Decreto Estadual SP 69118-2024','grupo':'decreto-estadual-sp','rotulo':'Decreto Estadual SP nº 69.118/2024','url':'https://www.al.sp.gov.br/repositorio/legislacao/decreto/2024/decreto-69118-09.12.2024.html','data_fonte':'2024-12-09','status_vigencia':'sem_revogacao_expressa','status_fonte':'ALESP: sem revogação expressa','min_chars':12000,'obrig':['DECRETO N° 69.118','Segurança Contra Incêndios','Art. 1']},
 {'norma_id':'lei-municipal-sp-13478-2002','norma':'Lei Municipal SP 13478-2002','grupo':'lei-municipal','rotulo':'Lei Municipal SP nº 13.478/2002 — texto consolidado','url':'https://legislacao.prefeitura.sp.gov.br/lei-13478-de-30-de-dezembro-de-2002','data_fonte':'2002-12-30','status_vigencia':'alterada_parcialmente_inconstitucional_parcialmente_revogada','status_fonte':'Prefeitura de São Paulo: ALTERADO, DECLARADO PARCIALMENTE INCONSTITUCIONAL, REVOGADO(A) PARCIALMENTE','min_chars':30000,'obrig':['LEI Nº 13.478','Sistema de Limpeza Urbana','Art. 1']},
 {'norma_id':'lei-federal-10357-2001','norma':'Lei 10357-2001','grupo':'lei-federal','rotulo':'Lei Federal nº 10.357/2001 — texto consolidado','url':'https://www.planalto.gov.br/ccivil_03/leis/leis_2001/l10357.htm','data_fonte':'2001-12-27','status_vigencia':'sem_revogacao_expressa','status_fonte':'Câmara dos Deputados: não consta revogação expressa; texto consolidado obtido no Planalto','min_chars':10000,'obrig':['10.357','produtos químicos','Art. 1']},
 {'norma_id':'lei-estadual-sp-15266-2013','norma':'Lei Estadual SP 15266-2013','grupo':'lei-estadual-sp','rotulo':'Lei Estadual SP nº 15.266/2013 — texto atualizado','url':'https://www.al.sp.gov.br/repositorio/legislacao/lei/2013/lei-15266-26.12.2013.html','data_fonte':'2013-12-26','status_vigencia':'sem_revogacao_expressa_com_alteracoes','status_fonte':'ALESP: sem revogação expressa; há alterações cadastradas','min_chars':25000,'obrig':['LEI N° 15.266','Taxa de Fiscalização','Art. 1']},
]

def agora(): return datetime.now(timezone.utc).isoformat()
def sha_b(b): return hashlib.sha256(b).hexdigest()
def sha_t(s): return hashlib.sha256(s.encode()).hexdigest()

def baixar(url):
    err=None
    for i in range(3):
        try:
            r=requests.get(url,headers=HEAD,timeout=90); r.raise_for_status()
            if len(r.content)<500: raise RuntimeError('resposta curta')
            return r
        except Exception as e:
            err=e; time.sleep(2**i)
    raise RuntimeError(f'Falha ao baixar {url}: {err}')

def extrair_html(body):
    soup=BeautifulSoup(body,'html.parser')
    for x in soup(['script','style','noscript','nav','footer']): x.decompose()
    txt=soup.get_text('\n')
    linhas=[]
    for ln in txt.splitlines():
        ln=re.sub(r'\s+',' ',ln).strip()
        if not ln: continue
        if ln in {'Voltar','Imprimir','Compartilhar:','Redefinir Cookies'}: continue
        ln=re.sub(r'^Artigo\s+(\d+(?:-[A-Z]|[A-Z])?)\s*[º°o]?\s*[-–—]?',r'Art. \1 ',ln,flags=re.I)
        linhas.append(ln)
    return '\n'.join(linhas).strip()

def validar(n,txt):
    if len(txt)<n['min_chars']: raise RuntimeError(f"{n['norma']}: texto curto ({len(txt)})")
    falt=[x for x in n['obrig'] if x.casefold() not in txt.casefold()]
    if falt: raise RuntimeError(f"{n['norma']}: faltam marcadores {falt}")

def garantir_catalogo():
    with CATALOGO.open(encoding='utf-8',newline='') as f:
        rows=list(csv.DictReader(f)); fields=list(rows[0]) if rows else ['norma_id','grupo','baixar','url','rotulo','observacao']
    ids={r['norma_id'] for r in rows}
    mudou=False
    for n in NORMAS:
        if n['norma_id'] not in ids:
            rows.append({'norma_id':n['norma_id'],'grupo':n['grupo'],'baixar':'sim','url':n['url'],'rotulo':n['rotulo'],'observacao':''}); mudou=True
    if mudou:
        with CATALOGO.open('w',encoding='utf-8',newline='') as f:
            w=csv.DictWriter(f,fieldnames=fields,lineterminator='\n'); w.writeheader(); w.writerows(rows)
    return mudou

def aplicar_meta(doc,meta):
    doc['proveniencia']=meta
    for no in doc['nos']:
        no['status_vigencia']=meta['status_vigencia']
        t=no.get('texto','')
        if re.search(r'\b(revogado|revogada)\b',t,re.I): no['status_dispositivo']='possivel_revogacao_textual'
        m=re.match(r'^([a-z])\)\s+',t) if no.get('tipo')=='bloco' else None
        if m and no.get('pai'):
            no.update(tipo='alinea',numero=m.group(1),rotulo=f"Alínea {m.group(1)}",estrutural=True,id=no['pai']+'::alinea::'+m.group(1))
    counts=Counter(x['id'] for x in doc['nos']); occ=Counter()
    for no in doc['nos']:
        if counts[no['id']]>1:
            old=no['id']; occ[old]+=1; no['id']=old+f"::ocorrencia-{occ[old]}"; no['ambiguidade_na_fonte']=True

def main():
    cat=garantir_catalogo(); (SAIDA/'normas').mkdir(parents=True,exist_ok=True); TEXTOS.mkdir(exist_ok=True)
    man_path=SAIDA/'manifest.json'; man=json.loads(man_path.read_text(encoding='utf-8')) if man_path.exists() else {'schema':'legislacao-hierarquica-v12','normas':{}}
    rel={'schema':'relatorio-legislacao-adicional-v1','gerado_em':agora(),'catalogo_atualizado':cat,'normas':[]}
    for n in NORMAS:
        print('Baixando',n['norma']); r=baixar(n['url']); txt=extrair_html(r.content); validar(n,txt)
        pasta=FONTES/n['norma_id']; pasta.mkdir(parents=True,exist_ok=True); (pasta/'texto_bruto.html').write_bytes(r.content)
        txtp=TEXTOS/f"{n['norma']}--oficial.txt"; txtp.write_text(txt,encoding='utf-8')
        meta={'norma':n['norma'],'fonte_oficial':n['url'],'url_final':r.url,'consultado_em':agora(),'data_fonte':n['data_fonte'],'tipo_data_fonte':'data_do_ato; texto oficial consultado em fonte institucional','sha256_fonte':sha_b(r.content),'sha256_texto':sha_t(txt),'status_vigencia':n['status_vigencia'],'status_fonte':n['status_fonte'],'texto':str(txtp.relative_to(BASE)),'data_processamento':agora(),'schema':'proveniencia-legislativa-v1','estruturar_alineas':True,'escopo_validacao':'texto oficial estruturado para consulta; alterações/revogações específicas seguem as marcações da fonte oficial'}
        txtp.with_suffix('.meta.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding='utf-8')
        doc=estruturar_texto(n['norma'],txt); aplicar_meta(doc,meta)
        ids=[x['id'] for x in doc['nos'] if x.get('estrutural',True)]
        if len(ids)!=len(set(ids)): raise RuntimeError(f"{n['norma']}: IDs estruturais repetidos")
        fn=slug(n['norma'])+'.json'; (SAIDA/'normas'/fn).write_text(json.dumps(doc,ensure_ascii=False,indent=2),encoding='utf-8')
        man['normas'][n['norma']]={'arquivo':fn,'nos':len(doc['nos']),'sha256_texto':doc['sha256_texto'],'proveniencia':meta}
        rel['normas'].append({'norma':n['norma'],'arquivo':fn,'nos':len(doc['nos']),'chars':len(txt),'status_vigencia':n['status_vigencia'],'status_fonte':n['status_fonte'],'fonte':n['url']})
    man['gerado_em']=agora(); man_path.write_text(json.dumps(man,ensure_ascii=False,indent=2),encoding='utf-8')
    rel['total_normas_manifest']=len(man['normas']); (SAIDA/'relatorio-legislacao-adicional.json').write_text(json.dumps(rel,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(rel,ensure_ascii=False))

if __name__=='__main__': main()
