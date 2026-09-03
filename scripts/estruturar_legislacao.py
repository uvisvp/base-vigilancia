#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Gera banco legislativo hierárquico a partir dos textos integrais extraídos."""
from __future__ import annotations
import argparse, hashlib, json, re, unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

BASE=Path(__file__).resolve().parent.parent
TEXTOS=BASE/'textos'; CURADA=BASE/'dados'/'legislacao_curada'; SAIDA=BASE/'dados'/'legislacao_v12'
RE_ANEXO=re.compile(r"^\s*ANEXO\s+([IVXLCDM]+|\d+[A-Z]?)(?=\s|[-–—:]|$)(?:\s*[-–—:]\s*(.*)|\s+(.*))?$",re.I)
RE_ARTIGO=re.compile(r"^\s*Art\.?\s*(\d+[A-Z]?)\s*[ºo°.]?\s*(.*)$",re.I)
RE_PARAGRAFO=re.compile(r"^\s*§\s*(\d+[A-Z]?)\s*[ºo°.]?\s*(.*)$",re.I)
RE_PU=re.compile(r"^\s*Par[aá]grafo\s+[uú]nico\.?\s*(.*)$",re.I)
RE_INCISO=re.compile(r"^\s*([IVXLCDM]+)\s*[-–—]\s+(.+)$")
RE_ITEM=re.compile(r"^\s*(\d+(?:\.\d+){0,4})\s*[.)-]\s+([A-Za-zÀ-ÿ].+)$")
RE_VALOR_TABELA=re.compile(r"^\s*[<>≤≥~]?\s*\d{1,3}(?:[.\s]\d{3})*(?:,\d+)?\s*(?:kcal|kj|g|mg|µg|mcg|ml|l|%|ui)\b",re.I)
RE_TITULO_TABELA=re.compile(r"^\s*(TABELA|QUADRO)\s+([A-Z0-9IVXLCDM.-]+)\b",re.I)
MARCADOR_TABELA_INICIO='[[TABELA_INICIO]]'; MARCADOR_TABELA_FIM='[[TABELA_FIM]]'

def slug(s):
    s=unicodedata.normalize('NFKD',str(s)).encode('ascii','ignore').decode('ascii')
    return re.sub(r'[^a-zA-Z0-9]+','-',s).strip('-').lower() or 'norma'

def sha256_texto(s): return hashlib.sha256(s.encode()).hexdigest()

def chave(norma,anexo,tipo,numero):
    p=[slug(norma)]
    if anexo:p.append('anexo-'+slug(anexo))
    p += [slug(tipo),slug(numero)]
    return '::'.join(p)

def id_hierarquico(norma,anexo,tipo,numero,pai=None):
    if pai and tipo in {'paragrafo','inciso','item'}:
        return f'{pai}::{slug(tipo)}::{slug(numero)}'
    return chave(norma,anexo,tipo,numero)

def novo_no(norma,anexo,tipo,numero,rotulo,texto,ordem,pai=None,meta=None,id_forcado=None):
    n={'id':id_forcado or id_hierarquico(norma,anexo,tipo,str(numero),pai),'norma':norma,'anexo':anexo,'tipo':tipo,'numero':str(numero),'rotulo':rotulo,'texto':texto,'ordem':ordem}
    if pai:n['pai']=pai
    if meta:n.update(meta)
    return n

def resolver_norma(documentos,norma):
    if norma in documentos:return norma
    alvo=slug(norma); candidatos=[k for k in documentos if slug(k)==alvo]
    if len(candidatos)==1:return candidatos[0]
    if len(candidatos)>1:raise RuntimeError(f'Norma ambígua {norma}: {candidatos}')
    return norma

def validar_destinos(documentos):
    vistos={}
    for norma in documentos:
        destino=f'{slug(norma)}.json'
        if destino in vistos and vistos[destino]!=norma:
            raise RuntimeError(f'Colisão de arquivo: {vistos[destino]} e {norma} -> {destino}')
        vistos[destino]=norma
    return vistos

def preencher_titulos_anexos(nos):
    for raiz in [n for n in nos if n.get('tipo')=='anexo' and not n.get('texto')]:
        seguintes=[n for n in nos if n.get('anexo')==raiz.get('anexo') and n.get('ordem',0)>raiz.get('ordem',0)]
        if not seguintes:continue
        primeiro=min(seguintes,key=lambda n:n.get('ordem',0))
        if primeiro.get('tipo')=='bloco' and primeiro.get('texto'):
            raiz['texto']=primeiro['texto']; raiz['titulo_origem']='linha_seguinte'; primeiro['papel']='titulo_anexo'

def estruturar_texto(norma,texto):
    linhas=[x.strip() for x in texto.splitlines() if x.strip()]
    nos=[]; anexo=None; artigo_id=paragrafo_id=inciso_id=None; em_tabela=False; tabela=None
    contadores_tabela={}; ocorrencias_artigo=Counter()
    for ordem,linha in enumerate(linhas,1):
        m=RE_ANEXO.match(linha)
        if m:
            anexo=m.group(1).upper(); titulo=((m.group(2) or m.group(3) or '')).strip(); nid=chave(norma,anexo,'anexo',anexo)
            nos.append({'id':nid,'norma':norma,'anexo':anexo,'tipo':'anexo','numero':anexo,'rotulo':f'Anexo {anexo}','texto':titulo,'ordem':ordem})
            artigo_id=paragrafo_id=inciso_id=None; em_tabela=False; tabela=None; continue
        if linha==MARCADOR_TABELA_INICIO:
            if anexo:
                contadores_tabela[anexo]=contadores_tabela.get(anexo,0)+1; tabela=f'html-{contadores_tabela[anexo]}'
                nos.append(novo_no(norma,anexo,'tabela',tabela,f'Tabela {contadores_tabela[anexo]} do Anexo {anexo}','',ordem,pai=chave(norma,anexo,'anexo',anexo),meta={'origem_estrutura':'html_oficial'})); em_tabela=True
            continue
        if linha==MARCADOR_TABELA_FIM:
            em_tabela=False; tabela=None; continue
        if em_tabela:
            nos.append(novo_no(norma,anexo,'linha_tabela',f'linha-{ordem}','Célula de tabela',linha,ordem,pai=chave(norma,anexo,'tabela',tabela),meta={'estrutural':False,'origem_estrutura':'html_oficial'})); continue
        m=RE_ARTIGO.match(linha)
        if m:
            numero=m.group(1).upper(); ocorrencias_artigo[(anexo,numero)]+=1; ocorr=ocorrencias_artigo[(anexo,numero)]
            base=chave(norma,anexo,'artigo',numero); nid=base if ocorr==1 else f'{base}::ocorrencia-{ocorr}'
            meta={'ocorrencia':ocorr}
            if ocorr>1:meta['artigo_repetido_na_fonte']=True
            n=novo_no(norma,anexo,'artigo',numero,f'Art. {numero}',linha,ordem,meta=meta,id_forcado=nid); nos.append(n)
            artigo_id=n['id']; paragrafo_id=inciso_id=None; tabela=None; continue
        m=RE_TITULO_TABELA.match(linha)
        if m:
            tabela=m.group(2); em_tabela=True; nos.append(novo_no(norma,anexo,'tabela',tabela,f'Tabela {tabela}',linha,ordem,pai=chave(norma,anexo,'anexo',anexo) if anexo else None,meta={'origem_estrutura':'texto'})); continue
        m=RE_PU.match(linha)
        if m:
            n=novo_no(norma,anexo,'paragrafo','unico','Parágrafo único',linha,ordem,pai=artigo_id); nos.append(n); paragrafo_id=n['id']; inciso_id=None; continue
        m=RE_PARAGRAFO.match(linha)
        if m:
            numero=m.group(1); n=novo_no(norma,anexo,'paragrafo',numero,f'§ {numero}º',linha,ordem,pai=artigo_id); nos.append(n); paragrafo_id=n['id']; inciso_id=None; continue
        m=RE_INCISO.match(linha)
        if m and artigo_id:
            numero=m.group(1).upper(); n=novo_no(norma,anexo,'inciso',numero,f'Inciso {numero}',linha,ordem,pai=paragrafo_id or artigo_id); nos.append(n); inciso_id=n['id']; continue
        if RE_VALOR_TABELA.match(linha):
            nos.append(novo_no(norma,anexo,'linha_tabela',f'linha-{ordem}','Linha de tabela',linha,ordem,pai=chave(norma,anexo,'anexo',anexo) if anexo else None,meta={'estrutural':False,'motivo':'valor_tabelar_sem_marcacao'})); continue
        m=RE_ITEM.match(linha)
        if m and (anexo or artigo_id):
            numero=m.group(1)
            if re.fullmatch(r'\d{1,3}\.\d{3}',numero) and not artigo_id:
                nos.append(novo_no(norma,anexo,'linha_tabela',f'linha-{ordem}','Linha de tabela',linha,ordem,pai=chave(norma,anexo,'anexo',anexo) if anexo else None,meta={'estrutural':False,'motivo':'numero_tabela'})); continue
            nos.append(novo_no(norma,anexo,'item',numero,f'Item {numero}',linha,ordem,pai=inciso_id or paragrafo_id or artigo_id or (chave(norma,anexo,'anexo',anexo) if anexo else None))); continue
        nos.append(novo_no(norma,anexo,'bloco',f'b{ordem}','Texto',linha,ordem,pai=inciso_id or paragrafo_id or artigo_id or (chave(norma,anexo,'anexo',anexo) if anexo else None),meta={'estrutural':False}))
    preencher_titulos_anexos(nos)
    ids=[n['id'] for n in nos if n.get('estrutural',True)]; repetidos=sorted({x for x in ids if ids.count(x)>1})
    artigos_rep={f'{a or "sem-anexo"}:{num}':q for (a,num),q in ocorrencias_artigo.items() if q>1}
    return {'schema':'legislacao-hierarquica-v12','norma':norma,'sha256_texto':sha256_texto(texto),'nos':nos,'validacao':{'ids_estruturais_repetidos':repetidos,'artigos_repetidos_na_fonte':artigos_rep}}

def carregar_curados():
    itens=[]
    if not CURADA.exists():return itens
    for arq in sorted(CURADA.glob('*.json')):
        obj=json.loads(arq.read_text(encoding='utf-8')); regs=obj if isinstance(obj,list) else obj.get('registros',[])
        for r in regs:
            obrig={'norma','anexo','tipo','numero','texto','fonte_oficial'}; faltam=sorted(obrig-set(r))
            if faltam:raise RuntimeError(f"{arq.name}: registro curado sem {', '.join(faltam)}")
            r=dict(r); r['id']=chave(r['norma'],r.get('anexo'),r['tipo'],str(r['numero'])); r['curado']=True; r['arquivo_curado']=arq.name; itens.append(r)
    return itens

def processar(textos=TEXTOS,saida=SAIDA):
    textos,saida=Path(textos),Path(saida); normas_dir=saida/'normas'; normas_dir.mkdir(parents=True,exist_ok=True)
    manifest={'schema':'legislacao-hierarquica-v12','gerado_em':datetime.now(timezone.utc).isoformat(),'normas':{},'curados':0}; documentos={}
    for arq in sorted(textos.glob('*.txt')):
        norma=arq.stem.split('--',1)[0]; documentos[norma]=estruturar_texto(norma,arq.read_text(encoding='utf-8'))
    for r0 in carregar_curados():
        norma=resolver_norma(documentos,r0['norma']); r=dict(r0)
        if norma!=r['norma']:
            r['norma']=norma; r['id']=chave(norma,r.get('anexo'),r['tipo'],str(r['numero']))
        doc=documentos.setdefault(norma,{'schema':'legislacao-hierarquica-v12','norma':norma,'sha256_texto':None,'nos':[],'validacao':{'ids_estruturais_repetidos':[],'artigos_repetidos_na_fonte':{}}})
        doc['nos']=[n for n in doc['nos'] if n['id']!=r['id']]; doc['nos'].append(r); manifest['curados']+=1
    validar_destinos(documentos)
    for norma,doc in sorted(documentos.items()):
        ids=[n['id'] for n in doc['nos'] if n.get('estrutural',True)]; rep=sorted({x for x in ids if ids.count(x)>1}); doc['validacao']['ids_estruturais_repetidos']=rep
        if rep:raise RuntimeError(f'{norma}: IDs estruturais duplicados: {rep[:10]}')
        destino=normas_dir/f'{slug(norma)}.json'; destino.write_text(json.dumps(doc,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
        manifest['normas'][norma]={'arquivo':destino.name,'nos':len(doc['nos']),'sha256_texto':doc.get('sha256_texto')}
    (saida/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print(f"OK: {len(documentos)} norma(s); {manifest['curados']} registro(s) curado(s)."); return manifest

def autoteste():
    amostra='''Art. 1º Regra.\nI - primeiro.\nArt. 2º Outra regra.\nI - outro inciso I.\n§ 1º Parágrafo.\nI - inciso do parágrafo.\nArt. 2º Redação adicional.\nANEXO II\nVDR oficial\n[[TABELA_INICIO]]\nArt. 99 célula, não dispositivo\n[[TABELA_FIM]]\n'''
    d=estruturar_texto('Norma teste',amostra); ids=[n['id'] for n in d['nos'] if n.get('estrutural',True)]
    assert len(ids)==len(set(ids)),ids
    assert len([n for n in d['nos'] if n['tipo']=='artigo' and n['numero']=='2'])==2
    assert d['validacao']['artigos_repetidos_na_fonte']=={'sem-anexo:2':2}
    incisos=[n for n in d['nos'] if n['tipo']=='inciso']; assert len({n['id'] for n in incisos})==len(incisos)
    assert not any(n['tipo']=='artigo' and n['numero']=='99' for n in d['nos'])
    docs={'IN 75-2020':d}; assert resolver_norma(docs,'IN 75/2020')=='IN 75-2020'; assert validar_destinos(docs)=={'in-75-2020.json':'IN 75-2020'}
    try:validar_destinos({'IN 75-2020':d,'IN 75/2020':d})
    except RuntimeError:pass
    else:raise AssertionError('Colisão de arquivo não detectada')
    print('AUTOTESTE OK')

def main():
    p=argparse.ArgumentParser(); p.add_argument('--autoteste',action='store_true'); p.add_argument('--textos',default=str(TEXTOS)); p.add_argument('--saida',default=str(SAIDA)); a=p.parse_args()
    autoteste() if a.autoteste else processar(a.textos,a.saida)
if __name__=='__main__':main()
