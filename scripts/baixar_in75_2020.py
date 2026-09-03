#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Baixa a versão oficial consolidada da IN 75/2020 no AnvisaLegis.

A publicação só prossegue se a fonte contiver todos os Anexos I a XXIII.
Isso evita gerar silenciosamente uma base parcial.
"""
from __future__ import annotations
import re, urllib.request
from html import unescape
from pathlib import Path

BASE=Path(__file__).resolve().parent.parent
OUT=BASE/'textos'/'IN 75-2020--anvisa-legis.txt'
URL='https://anvisalegis.datalegis.net/action/ActionDatalegis.php?acao=abrirTextoAto&tipo=INM&numeroAto=00000075&seqAto=000&valorAno=2020&orgao=DC/ANVISA/MS&codTipo=&desItem=&desItemFim=&cod_menu=9434&cod_modulo=310&pesquisa=true'
ROMANOS=('I','II','III','IV','V','VI','VII','VIII','IX','X','XI','XII','XIII','XIV','XV','XVI','XVII','XVIII','XIX','XX','XXI','XXII','XXIII')

def baixar():
    req=urllib.request.Request(URL,headers={
        'User-Agent':'Mozilla/5.0 base-vigilancia/1.0',
        'Accept':'text/html,application/xhtml+xml'
    })
    with urllib.request.urlopen(req,timeout=120) as r:
        bruto=r.read()
    for enc in ('utf-8','windows-1252','latin-1'):
        try:
            return bruto.decode(enc)
        except UnicodeDecodeError:
            pass
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
        if ln:
            linhas.append(ln)
    return '\n'.join(linhas)+'\n'

def validar(texto):
    faltam=[]
    for r in ROMANOS:
        if not re.search(rf'(?im)^\s*ANEXO\s+{r}\b',texto):
            faltam.append(r)
    if faltam:
        raise RuntimeError('IN 75/2020 incompleta; anexos ausentes: '+', '.join(faltam))
    if not re.search(r'(?i)INSTRU[CÇ][AÃ]O(?:\s+NORMATIVA)?(?:-IN)?\s*(?:N[º°.]*)?\s*75',texto):
        raise RuntimeError('Fonte não reconhecida como IN 75/2020')
    # Travas de conteúdo: pontos importantes espalhados pela norma.
    obrigatorios=(
        'VDR PARA FINS DE ROTULAGEM NUTRICIONAL',
        'TAMANHO DAS PORÇÕES',
        'ROTULAGEM NUTRICIONAL FRONTAL',
        'AÇÚCARES ADICIONADOS',
        'FATORES DE CONVERSÃO',
    )
    normal=texto.upper()
    ausentes=[x for x in obrigatorios if x not in normal]
    if ausentes:
        raise RuntimeError('IN 75/2020 falhou nas travas de conteúdo: '+', '.join(ausentes))

def main():
    texto=limpar(baixar())
    validar(texto)
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(texto,encoding='utf-8')
    print(f'OK: IN 75/2020 integral, Anexos I a XXIII presentes, {len(texto)} caracteres')

if __name__=='__main__':
    main()
