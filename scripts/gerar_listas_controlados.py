#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Gera a base operacional das listas mais aplicáveis da Portaria SVS/MS 344/1998.

Escopo deliberado: A1, A2, A3, B1, B2 e C1, C2, C3, C4, C5.
As demais listas são reconhecidas apenas como limites de seção e não são publicadas.
"""
from __future__ import annotations
import hashlib, json, re, unicodedata, urllib.request
from datetime import datetime, timezone
from html import unescape
from pathlib import Path

BASE=Path(__file__).resolve().parent.parent
SAIDA=BASE/'dados'/'controlados_portaria344'
URL_FONTE=('https://anvisalegis.datalegis.net/action/ActionDatalegis.php?acao=abrirTextoAto&codTipo=&cod_menu=1696&cod_modulo=134&desItem=&desItemFim=&numeroAto=00001036&orgao=RDC%2FDC%2FANVISA%2FMS&pesquisa=true&seqAto=000&tipo=RDC&valorAno=2026')
NORMA_FONTE='RDC Anvisa 1.036/2026'; NORMA_BASE='Portaria SVS/MS 344/1998 - Anexo I'
LISTAS_ESCOPO=('A1','A2','A3','B1','B2','C1','C2','C3','C4','C5')
LISTAS_ESPERADAS=set(LISTAS_ESCOPO)
RE_TAG=re.compile(r'<[^>]+>')
# Reconhece QUALQUER cabeçalho de lista para encerrar corretamente a anterior,
# mas só abre/coleta as dez listas do escopo operacional.
RE_QUALQUER_LISTA=re.compile(r'^LISTA\s*[-–—]?\s*([A-F](?:\d)?)\b(?:\s*[-–—:]\s*(.*))?$',re.I)
RE_SUBSTANCIA=re.compile(r'^(\d+)\.\s*(\S.*)$')
RE_ADENDO=re.compile(r'^ADENDO\s*:?\s*$',re.I)
RE_ITEM_ADENDO=re.compile(r'^(\d+(?:\.\d+)*)\)??\.?\s+(.+)$')
RE_VALOR_UNIDADE=re.compile(r'^\d+(?:[.,]\d+)?\s*(?:kcal|kj|g|mg|mcg|µg|ug|ml|l|ui|%)\b',re.I)
RE_SUBITEM_NUMERICO=re.compile(r'^\d+\.\d+(?:\.|\s|$)')

def baixar():
 req=urllib.request.Request(URL_FONTE,headers={'User-Agent':'base-vigilancia/1.0'})
 with urllib.request.urlopen(req,timeout=120) as r:
  bruto=r.read(); meta={'data_fonte':r.headers.get('Last-Modified') or r.headers.get('Date') or 'nao informada','etag':r.headers.get('ETag')}
 for enc in ('utf-8','windows-1252','latin-1'):
  try:return bruto.decode(enc),meta
  except UnicodeDecodeError:pass
 return bruto.decode('utf-8',errors='replace'),meta

def html_para_linhas(html):
 x=re.sub(r'</?(?:p|div|li|tr|td|th|br|h\d)\b[^>]*>','\n',html,flags=re.I)
 x=unescape(RE_TAG.sub(' ',x)).replace('\xa0',' ')
 return [re.sub(r'\s+',' ',ln).strip() for ln in x.splitlines() if re.sub(r'\s+',' ',ln).strip()]

def slug(s):
 s=unicodedata.normalize('NFKD',s).encode('ascii','ignore').decode('ascii').lower()
 return re.sub(r'[^a-z0-9]+','-',s).strip('-')[:80] or 'sem-nome'

def id_registro(lista,tipo,numero,nome=None):
 base=f'portaria-344-1998::anexo-i::lista-{lista.lower()}::{tipo}::{numero.lower()}'
 return base if not nome else base+'::'+slug(nome)

def nova_lista(listas,codigo,titulo=''):
 listas.setdefault(codigo,{'id':f'portaria-344-1998::anexo-i::lista-{codigo.lower()}','lista':codigo,'titulo':titulo.strip(),'substancias':[],'adendos':[]})

def nome_valido(nome):
 n=nome.strip().lstrip('|').strip()
 return bool(n) and not RE_VALOR_UNIDADE.match(n) and not RE_SUBITEM_NUMERICO.match(n) and n.lower() not in {'ou','substância','substancias','substâncias','nº','n°','numero','número'}

def adicionar_substancia(listas,lista,numero,nome):
 nome=nome.strip().lstrip('|').strip()
 if '|' in nome:nome=nome.split('|',1)[0].strip()
 if not nome_valido(nome):return False
 listas[lista]['substancias'].append({'id':id_registro(lista,'substancia',numero,nome),'lista':lista,'tipo':'substancia','numero':numero,'nome':nome})
 return True

def parsear(linhas):
 listas={}; atual=None; modo_adendo=False; titulo=[]
 for linha in linhas:
  mh=RE_QUALQUER_LISTA.match(linha)
  if mh:
   codigo=mh.group(1).upper(); atual=codigo if codigo in LISTAS_ESPERADAS else None
   modo_adendo=False; titulo=[]
   if atual:nova_lista(listas,atual,(mh.group(2) or '').strip())
   continue
  if not atual:continue
  if RE_ADENDO.match(linha):modo_adendo=True;continue
  if modo_adendo:
   ma=RE_ITEM_ADENDO.match(linha)
   if ma:
    numero,texto=ma.group(1),ma.group(2).strip();listas[atual]['adendos'].append({'id':id_registro(atual,'adendo',numero,texto),'lista':atual,'tipo':'adendo','numero':numero,'texto':texto})
   elif listas[atual]['adendos']:listas[atual]['adendos'][-1]['texto']+=' '+linha
   continue
  ms=RE_SUBSTANCIA.match(linha)
  if ms and adicionar_substancia(listas,atual,ms.group(1),ms.group(2).strip()):continue
  if not listas[atual]['substancias'] and not linha.upper().startswith(('MINISTERIO','AGENCIA','LISTA ')):
   titulo.append(linha)
   if not listas[atual]['titulo']:listas[atual]['titulo']=' '.join(titulo)
 return listas

def validar(listas):
 faltantes=sorted(LISTAS_ESPERADAS-set(listas));extras=sorted(set(listas)-LISTAS_ESPERADAS)
 if faltantes:raise RuntimeError('Listas ausentes na fonte: '+', '.join(faltantes))
 if extras:raise RuntimeError('Listas fora do escopo: '+', '.join(extras))
 ids=[]; total=0
 for codigo in LISTAS_ESCOPO:
  obj=listas[codigo]
  if not obj['substancias']:raise RuntimeError(f'Lista {codigo} sem substancias extraidas')
  total+=len(obj['substancias']);ids += [x['id'] for x in obj['substancias']]+[x['id'] for x in obj['adendos']]
 if len(ids)!=len(set(ids)):
  vistos=set();rep=[]
  for x in ids:
   if x in vistos and x not in rep:rep.append(x)
   vistos.add(x)
  raise RuntimeError('IDs duplicados: '+', '.join(rep[:20]))
 if total<200:raise RuntimeError(f'Extracao suspeita: apenas {total} substancias no escopo')

def gerar():
 html,meta=baixar();listas=parsear(html_para_linhas(html));validar(listas);SAIDA.mkdir(parents=True,exist_ok=True);gerado_em=datetime.now(timezone.utc).isoformat()
 payload={'schema':'controlados-portaria344-v2','escopo':'operacional','listas_incluidas':list(LISTAS_ESCOPO),'norma_base':NORMA_BASE,'norma_fonte':NORMA_FONTE,'fonte_oficial':URL_FONTE,'gerado_em':gerado_em,'listas':[listas[k] for k in LISTAS_ESCOPO]}
 serial=json.dumps(payload,ensure_ascii=False,separators=(',',':'));(SAIDA/'listas.json').write_text(serial,encoding='utf-8')
 ts=sum(len(x['substancias']) for x in listas.values());ta=sum(len(x['adendos']) for x in listas.values())
 manifest={'schema':payload['schema'],'status':'ok','escopo':'operacional','listas_incluidas':list(LISTAS_ESCOPO),'norma_base':NORMA_BASE,'norma_fonte':NORMA_FONTE,'fonte_oficial':URL_FONTE,'data_fonte':meta['data_fonte'],'gerado_em':gerado_em,'listas':len(listas),'substancias':ts,'adendos':ta,'sha256':hashlib.sha256(serial.encode()).hexdigest()}
 if meta.get('etag'):manifest['etag_fonte']=meta['etag']
 (SAIDA/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8');print(f'OK: {len(listas)} listas operacionais, {ts} substancias, {ta} adendos');return manifest

def autoteste():
 amostra=[]
 for cod in LISTAS_ESCOPO:amostra += [f'LISTA - {cod}',f'1. SUBSTANCIA {cod}']
 amostra += ['LISTA - D1','1. NAO DEVE ENTRAR','LISTA F1 - SUBSTANCIAS ENTORPECENTES','1. TAMBEM NAO DEVE ENTRAR']
 d=parsear(amostra)
 assert set(d)==LISTAS_ESPERADAS
 assert all(len(d[c]['substancias'])==1 for c in LISTAS_ESCOPO)
 assert all('NAO DEVE ENTRAR' not in x['nome'] for c in d for x in d[c]['substancias'])
 ids=[x['id'] for c in d for x in d[c]['substancias']]
 assert len(ids)==len(set(ids))
 assert not nome_valido('3.500 kcal') and not nome_valido('600 mg') and not nome_valido('1.1. texto')
 print('AUTOTESTE OK')
if __name__=='__main__':
 import sys
 autoteste() if '--autoteste' in sys.argv else gerar()
