#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Gera banco legislativo hierarquico a partir dos textos integrais extraidos."""
from __future__ import annotations
import argparse, hashlib, json, re, unicodedata
from datetime import datetime, timezone
from pathlib import Path

BASE=Path(__file__).resolve().parent.parent
TEXTOS=BASE/'textos'; CURADA=BASE/'dados'/'legislacao_curada'; SAIDA=BASE/'dados'/'legislacao_v12'
# Aceita tanto "ANEXO XV - Limites" quanto títulos oficiais em que o nome do
# anexo vem na linha seguinte. O lookahead impede que "ANEXO I" case o início
# de "ANEXO II", "ANEXO III" etc.
RE_ANEXO=re.compile(r"^\s*ANEXO\s+([IVXLCDM]+|\d+[A-Z]?)(?=\s|[-–—:]|$)(?:\s*[-–—:]\s*(.*)|\s+(.*))?$",re.I)
RE_ARTIGO=re.compile(r"^\s*Art\.?\s*(\d+[A-Z]?)\s*[ºo°.]?\s*(.*)$",re.I)
RE_PARAGRAFO=re.compile(r"^\s*§\s*(\d+[A-Z]?)\s*[ºo°.]?\s*(.*)$",re.I)
RE_PU=re.compile(r"^\s*Par[aá]grafo\s+[uú]nico\.?\s*(.*)$",re.I)
RE_INCISO=re.compile(r"^\s*([IVXLCDM]+)\s*[-–—]\s+(.+)$")
RE_ITEM=re.compile(r"^\s*(\d+(?:\.\d+){0,4})\s*[.)-]\s+([A-Za-zÀ-ÿ].+)$")
RE_VALOR_TABELA=re.compile(r"^\s*[<>≤≥~]?\s*\d{1,3}(?:[.\s]\d{3})*(?:,\d+)?\s*(?:kcal|kj|g|mg|µg|mcg|ml|l|%|ui)\b",re.I)
RE_TITULO_TABELA=re.compile(r"^\s*(TABELA|QUADRO)\s+([A-Z0-9IVXLCDM.-]+)\b",re.I)

def slug(s):
 s=unicodedata.normalize('NFKD',s).encode('ascii','ignore').decode('ascii'); return re.sub(r'[^a-zA-Z0-9]+','-',s).strip('-').lower() or 'norma'
def sha256_texto(s): return hashlib.sha256(s.encode()).hexdigest()
def chave(norma,anexo,tipo,numero):
 p=[slug(norma)]; p += ['anexo-'+slug(anexo)] if anexo else []; p += [slug(tipo),slug(str(numero))]; return '::'.join(p)
def novo_no(norma,anexo,tipo,numero,rotulo,texto,ordem,pai=None,meta=None):
 n={'id':chave(norma,anexo,tipo,numero),'norma':norma,'anexo':anexo,'tipo':tipo,'numero':str(numero),'rotulo':rotulo,'texto':texto,'ordem':ordem}
 if pai:n['pai']=pai
 if meta:n.update(meta)
 return n

def estruturar_texto(norma,texto):
 linhas=[x.strip() for x in texto.splitlines() if x.strip()]; nos=[]; anexo=None; artigo_id=paragrafo_id=inciso_id=None; em_tabela=False; tabela=None
 for ordem,linha in enumerate(linhas,1):
  # Limites estruturais têm precedência absoluta sobre estado de tabela.
  m=RE_ANEXO.match(linha)
  if m:
   anexo=m.group(1).upper(); titulo=((m.group(2) or m.group(3) or '')).strip(); nid=chave(norma,anexo,'anexo',anexo)
   nos.append({'id':nid,'norma':norma,'anexo':anexo,'tipo':'anexo','numero':anexo,'rotulo':f'Anexo {anexo}','texto':titulo,'ordem':ordem})
   artigo_id=paragrafo_id=inciso_id=None; em_tabela=False; tabela=None; continue
  m=RE_ARTIGO.match(linha)
  if m:
   numero=m.group(1); n=novo_no(norma,anexo,'artigo',numero,f'Art. {numero}',linha,ordem); nos.append(n); artigo_id=n['id']; paragrafo_id=inciso_id=None; em_tabela=False; tabela=None; continue
  m=RE_TITULO_TABELA.match(linha)
  if m:
   tabela=m.group(2); em_tabela=True; nos.append(novo_no(norma,anexo,'tabela',tabela,f'Tabela {tabela}',linha,ordem,pai=chave(norma,anexo,'anexo',anexo) if anexo else None)); continue
  m=RE_PU.match(linha)
  if m:
   em_tabela=False; tabela=None; n=novo_no(norma,anexo,'paragrafo','unico','Parágrafo único',linha,ordem,pai=artigo_id); nos.append(n); paragrafo_id=n['id']; inciso_id=None; continue
  m=RE_PARAGRAFO.match(linha)
  if m:
   em_tabela=False; tabela=None; numero=m.group(1); n=novo_no(norma,anexo,'paragrafo',numero,f'§ {numero}º',linha,ordem,pai=artigo_id); nos.append(n); paragrafo_id=n['id']; inciso_id=None; continue
  m=RE_INCISO.match(linha)
  if m and artigo_id:
   em_tabela=False; tabela=None; numero=m.group(1).upper(); n=novo_no(norma,anexo,'inciso',numero,f'Inciso {numero}',linha,ordem,pai=paragrafo_id or artigo_id); nos.append(n); inciso_id=n['id']; continue
  if em_tabela or RE_VALOR_TABELA.match(linha):
   nos.append(novo_no(norma,anexo,'linha_tabela',f'linha-{ordem}','Linha de tabela',linha,ordem,pai=(chave(norma,anexo,'tabela',tabela) if tabela else (chave(norma,anexo,'anexo',anexo) if anexo else None)),meta={'estrutural':False})); continue
  m=RE_ITEM.match(linha)
  if m and (anexo or artigo_id):
   numero=m.group(1)
   if re.fullmatch(r'\d{1,3}\.\d{3}',numero) and not artigo_id:
    nos.append(novo_no(norma,anexo,'linha_tabela',f'linha-{ordem}','Linha de tabela',linha,ordem,pai=chave(norma,anexo,'anexo',anexo) if anexo else None,meta={'estrutural':False,'motivo':'numero_tabela'})); continue
   nos.append(novo_no(norma,anexo,'item',numero,f'Item {numero}',linha,ordem,pai=inciso_id or paragrafo_id or artigo_id or (chave(norma,anexo,'anexo',anexo) if anexo else None))); continue
  nos.append(novo_no(norma,anexo,'bloco',f'b{ordem}','Texto',linha,ordem,pai=inciso_id or paragrafo_id or artigo_id or (chave(norma,anexo,'anexo',anexo) if anexo else None),meta={'estrutural':False}))
 ids=[n['id'] for n in nos if n.get('estrutural',True)]; repetidos=sorted({x for x in ids if ids.count(x)>1})
 return {'schema':'legislacao-hierarquica-v12','norma':norma,'sha256_texto':sha256_texto(texto),'nos':nos,'validacao':{'ids_estruturais_repetidos':repetidos}}

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
 for r in carregar_curados():
  norma=r['norma']; doc=documentos.setdefault(norma,{'schema':'legislacao-hierarquica-v12','norma':norma,'sha256_texto':None,'nos':[],'validacao':{'ids_estruturais_repetidos':[]}}); doc['nos']=[n for n in doc['nos'] if n['id']!=r['id']]; doc['nos'].append(r); manifest['curados']+=1
 for norma,doc in sorted(documentos.items()):
  ids=[n['id'] for n in doc['nos'] if n.get('estrutural',True)]; rep=sorted({x for x in ids if ids.count(x)>1}); doc['validacao']['ids_estruturais_repetidos']=rep
  if rep:raise RuntimeError(f'{norma}: IDs estruturais duplicados: {rep[:10]}')
  destino=normas_dir/f'{slug(norma)}.json'; destino.write_text(json.dumps(doc,ensure_ascii=False,separators=(',',':')),encoding='utf-8'); manifest['normas'][norma]={'arquivo':destino.name,'nos':len(doc['nos']),'sha256_texto':doc.get('sha256_texto')}
 (saida/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8'); print(f"OK: {len(documentos)} norma(s); {manifest['curados']} registro(s) curado(s)."); return manifest

def autoteste():
 amostra='''INSTRUÇÃO NORMATIVA\nANEXO I\nValores diários de referência\nANEXO II Tabela de referência\nTABELA 1\n2.000 kcal Carboidratos 300 g\n300 mg Colesterol\nArt. 17. Aplicam-se as disposições.\nANEXO XV - Limites\n15. Açúcares adicionados\nANEXO XVI Exceções\n15. Bebidas alcoólicas.\nANEXO XXIII: fatores de conversão\n'''
 d=estruturar_texto('IN 75/2020',amostra); ids=[n['id'] for n in d['nos']]; anexos={n['anexo'] for n in d['nos'] if n['tipo']=='anexo'}
 assert anexos=={'I','II','XV','XVI','XXIII'},anexos; assert not any('item::2-000' in x for x in ids); assert len([x for x in ids if 'artigo::17' in x])==1; assert len(ids)==len(set(ids)); print('AUTOTESTE OK')
def main():
 p=argparse.ArgumentParser(); p.add_argument('--autoteste',action='store_true'); p.add_argument('--textos',default=str(TEXTOS)); p.add_argument('--saida',default=str(SAIDA)); a=p.parse_args(); autoteste() if a.autoteste else processar(a.textos,a.saida)
if __name__=='__main__':main()
