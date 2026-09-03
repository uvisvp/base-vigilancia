#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Gera base estruturada das listas vigentes da Portaria SVS/MS 344/1998."""
from __future__ import annotations
import hashlib, json, re, urllib.request
from datetime import datetime, timezone
from html import unescape
from pathlib import Path

BASE=Path(__file__).resolve().parent.parent
SAIDA=BASE/'dados'/'controlados_portaria344'
URL_FONTE=('https://anvisalegis.datalegis.net/action/ActionDatalegis.php?acao=abrirTextoAto&codTipo=&cod_menu=1696&cod_modulo=134&desItem=&desItemFim=&numeroAto=00001036&orgao=RDC%2FDC%2FANVISA%2FMS&pesquisa=true&seqAto=000&tipo=RDC&valorAno=2026')
NORMA_FONTE='RDC Anvisa 1.036/2026'; NORMA_BASE='Portaria SVS/MS 344/1998 - Anexo I'
RE_TAG=re.compile(r'<[^>]+>')
RE_LISTA_SIMPLES=re.compile(r'^LISTA\s*[-–—]\s*(A1|A2|A3|B1|B2|C1|C2|C3|C5|D1|D2|E)\s*$',re.I)
RE_LISTA_F=re.compile(r'^LISTA\s*[-–—]?\s*(F[1-4])(?:\s*[-–—:]\s*(.+))?\s*$',re.I)
RE_LISTA_F_PAI=re.compile(r'^LISTA\s*[-–—]\s*F\s*$',re.I)
RE_SUBSTANCIA=re.compile(r'^(\d+)\.\s*(\S.*)$')
RE_NUMERO_SO=re.compile(r'^(\d+)\.\s*$')
RE_ADENDO=re.compile(r'^ADENDO\s*:?\s*$',re.I)
RE_ITEM_ADENDO=re.compile(r'^(\d+(?:\.\d+)*)\)??\.?\s+(.+)$')
RE_VALOR_UNIDADE=re.compile(r'^\d+(?:[.,]\d+)?\s*(?:kcal|kj|g|mg|mcg|µg|ug|ml|l|ui|%)\b',re.I)
RE_SUBITEM_NUMERICO=re.compile(r'^\d+\.\d+(?:\.|\s|$)')
LISTAS_ESPERADAS={'A1','A2','A3','B1','B2','C1','C2','C3','C5','D1','D2','E','F1','F2','F3','F4'}

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

def id_registro(lista,tipo,numero):return f'portaria-344-1998::anexo-i::lista-{lista.lower()}::{tipo}::{numero.lower()}'
def nova_lista(listas,codigo,titulo=''):
 listas.setdefault(codigo,{'id':f'portaria-344-1998::anexo-i::lista-{codigo.lower()}','lista':codigo,'titulo':titulo.strip(),'substancias':[],'adendos':[]})
 if titulo.strip() and not listas[codigo]['titulo']:listas[codigo]['titulo']=titulo.strip()

def nome_valido(nome):
 n=nome.strip().lstrip('|').strip()
 if not n:return False
 if RE_VALOR_UNIDADE.match(n) or RE_SUBITEM_NUMERICO.match(n):return False
 if n.lower() in {'ou','substância','substancias','substâncias','nº','n°','numero','número'}:return False
 return True

def adicionar_substancia(listas,lista,numero,nome):
 nome=nome.strip().lstrip('|').strip()
 if '|' in nome:nome=nome.split('|',1)[0].strip()
 if not nome_valido(nome):return False
 listas[lista]['substancias'].append({'id':id_registro(lista,'substancia',numero),'lista':lista,'tipo':'substancia','numero':numero,'nome':nome})
 return True

def parsear(linhas):
 listas={}; atual=None; modo_adendo=False; titulo_pendente=[]; pendente_f=None
 for linha in linhas:
  if RE_LISTA_F_PAI.match(linha):atual=None;modo_adendo=False;titulo_pendente=[];pendente_f=None;continue
  mf=RE_LISTA_F.match(linha)
  if mf:
   atual=mf.group(1).upper();nova_lista(listas,atual,(mf.group(2) or '').strip());modo_adendo=False;titulo_pendente=[];pendente_f=None;continue
  m=RE_LISTA_SIMPLES.match(linha)
  if m:
   atual=m.group(1).upper();nova_lista(listas,atual);modo_adendo=False;titulo_pendente=[];pendente_f=None;continue
  if not atual:continue
  if RE_ADENDO.match(linha):modo_adendo=True;pendente_f=None;continue
  if modo_adendo:
   ma=RE_ITEM_ADENDO.match(linha)
   if ma:
    numero,texto=ma.group(1),ma.group(2).strip();listas[atual]['adendos'].append({'id':id_registro(atual,'adendo',numero),'lista':atual,'tipo':'adendo','numero':numero,'texto':texto})
   elif listas[atual]['adendos']:listas[atual]['adendos'][-1]['texto']+=' '+linha
   continue
  # Nas tabelas F, o HTML oficial pode separar as células: "1." / "2F-VIMINOL" / "ou" / nome químico.
  if atual.startswith('F'):
   mn=RE_NUMERO_SO.match(linha)
   if mn:
    pendente_f=mn.group(1);continue
   if pendente_f is not None:
    if adicionar_substancia(listas,atual,pendente_f,linha):
     pendente_f=None;continue
    # cabeçalhos/células auxiliares não devem consumir o número pendente
    if linha.lower() in {'ou','a) substâncias','a) substancias','substâncias','substancias'}:continue
  ms=RE_SUBSTANCIA.match(linha)
  if ms:
   numero,nome=ms.group(1),ms.group(2).strip()
   if adicionar_substancia(listas,atual,numero,nome):continue
  if not listas[atual]['substancias'] and not modo_adendo and linha.startswith('(') and linha.endswith(')'):
   if titulo_pendente and not listas[atual]['titulo']:listas[atual]['titulo']=' '.join(titulo_pendente)
   continue
  if not listas[atual]['substancias'] and not modo_adendo and not linha.upper().startswith(('MINISTERIO','AGENCIA','LISTA ')):
   titulo_pendente.append(linha)
   if not listas[atual]['titulo']:listas[atual]['titulo']=' '.join(titulo_pendente)
 return listas

def validar(listas):
 faltantes=sorted(LISTAS_ESPERADAS-set(listas));extras=sorted(set(listas)-LISTAS_ESPERADAS)
 if faltantes:raise RuntimeError('Listas ausentes na fonte: '+', '.join(faltantes))
 if extras:raise RuntimeError('Listas inesperadas na extracao: '+', '.join(extras))
 ids=[];total=0
 for codigo,obj in listas.items():
  if not obj['substancias']:raise RuntimeError(f'Lista {codigo} sem substancias extraidas')
  total+=len(obj['substancias']);ids += [x['id'] for x in obj['substancias']]+[x['id'] for x in obj['adendos']]
 repetidos=sorted({x for x in ids if ids.count(x)>1})
 if repetidos:raise RuntimeError('IDs duplicados: '+', '.join(repetidos[:20]))
 if total<300:raise RuntimeError(f'Extracao suspeita: apenas {total} substancias')

def gerar():
 html,meta=baixar();listas=parsear(html_para_linhas(html));validar(listas);SAIDA.mkdir(parents=True,exist_ok=True);gerado_em=datetime.now(timezone.utc).isoformat()
 payload={'schema':'controlados-portaria344-v1','norma_base':NORMA_BASE,'norma_fonte':NORMA_FONTE,'fonte_oficial':URL_FONTE,'gerado_em':gerado_em,'listas':[listas[k] for k in sorted(listas)]}
 serial=json.dumps(payload,ensure_ascii=False,separators=(',',':'));(SAIDA/'listas.json').write_text(serial,encoding='utf-8')
 ts=sum(len(x['substancias']) for x in listas.values());ta=sum(len(x['adendos']) for x in listas.values())
 manifest={'schema':payload['schema'],'status':'ok','norma_base':NORMA_BASE,'norma_fonte':NORMA_FONTE,'fonte_oficial':URL_FONTE,'data_fonte':meta['data_fonte'],'gerado_em':gerado_em,'listas':len(listas),'substancias':ts,'adendos':ta,'sha256':hashlib.sha256(serial.encode()).hexdigest()}
 if meta.get('etag'):manifest['etag_fonte']=meta['etag']
 (SAIDA/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8');print(f'OK: {len(listas)} listas, {ts} substancias, {ta} adendos');return manifest

def autoteste():
 amostra=['LISTA - A1','LISTA DAS SUBSTANCIAS ENTORPECENTES','1. Acetilmetadol','2.Morfina','ADENDO:','1) ficam tambem sob controle:','1.1. os sais e isomeros','LISTA - B2','1.Aminorex','LISTA - D1','1.1-boc-4-AP','LISTA - F','LISTA F1 - SUBSTANCIAS ENTORPECENTES','1.','2F-VIMINOL','ou','nome quimico','2. | DIMETOCAINA | exemplo','LISTA F2 - SUBSTANCIAS PSICOTROPICAS','a) SUBSTANCIAS','1.','(+) - LISERGIDA','ou','LSD','LISTA F3 - PRECURSORAS','1. | EXEMPLO F3','LISTA F4 - OUTRAS','1. | FENIBUT']
 d=parsear(amostra)
 assert d['A1']['substancias'][0]['nome']=='Acetilmetadol'
 assert d['B2']['substancias'][0]['nome']=='Aminorex'
 assert d['D1']['substancias'][0]['nome']=='1-boc-4-AP'
 assert d['F1']['substancias'][0]['nome']=='2F-VIMINOL' and d['F1']['substancias'][1]['nome']=='DIMETOCAINA'
 assert d['F2']['substancias'][0]['nome']=='(+) - LISERGIDA'
 assert not nome_valido('3.500 kcal') and not nome_valido('600 mg') and not nome_valido('1.1. texto')
 print('AUTOTESTE OK')
if __name__=='__main__':
 import sys
 autoteste() if '--autoteste' in sys.argv else gerar()
