#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Baixa a versão oficial da IN 75/2020 e prepara o texto integral para o banco legislativo.

A fonte é AnvisaLegis. O script exige a presença dos Anexos I a XX para impedir
publicação silenciosa de uma extração incompleta.
"""
from __future__ import annotations
import re, urllib.request
from html import unescape
from pathlib import Path

BASE=Path(__file__).resolve().parent.parent
OUT=BASE/'textos'/'IN 75-2020--anvisa-legis.txt'
URL='https://anvisalegis.datalegis.net/action/ActionDatalegis.php?acao=abrirTextoAto&tipo=INM&numeroAto=00000075&seqAto=000&valorAno=2020&orgao=DC/ANVISA/MS&cod_modulo=310'
ROMANOS=('I','II','III','IV','V','VI','VII','VIII','IX','X','XI','XII','XIII','XIV','XV','XVI','XVII','XVIII','XIX','XX')

def baixar():
    req=urllib.request.Request(URL,headers={'User-Agent':'base-vigilancia/1.0'})
    with urllib.request.urlopen(req,timeout=120) as r: bruto=r.read()
    for enc in ('utf-8','windows-1252','latin-1'):
        try: return bruto.decode(enc)
        except UnicodeDecodeError: pass
    return bruto.decode('utf-8',errors='replace')

def limpar(html):
    x=re.sub(r'(?is)<(script|style).*?>.*?</\1>',' ',html)
    x=re.sub(r'(?i)<br\s*/?>','\n',x)
    x=re.sub(r'(?i)</(?:p|div|li|tr|td|th|h[1-6])>','\n',x)
    x=re.sub(r'<[^>]+>',' ',x)
    x=unescape(x).replace('\xa0',' ')
    linhas=[]
    for ln in x.splitlines():
        ln=re.sub(r'[ \t]+',' ',ln).strip()
        if ln: linhas.append(ln)
    return '\n'.join(linhas)+'\n'

def validar(texto):
    faltam=[]
    for r in ROMANOS:
        if not re.search(rf'(?im)^\s*ANEXO\s+{r}\b',texto): faltam.append(r)
    if faltam: raise RuntimeError('IN 75/2020 incompleta; anexos ausentes: '+', '.join(faltam))
    if not re.search(r'(?i)INSTRU[CÇ][AÃ]O NORMATIVA',texto):
        raise RuntimeError('Fonte não reconhecida como Instrução Normativa')

def main():
    texto=limpar(baixar()); validar(texto)
    OUT.parent.mkdir(parents=True,exist_ok=True); OUT.write_text(texto,encoding='utf-8')
    print(f'OK: IN 75/2020 integral, Anexos I a XX presentes, {len(texto)} caracteres')
if __name__=='__main__': main()
