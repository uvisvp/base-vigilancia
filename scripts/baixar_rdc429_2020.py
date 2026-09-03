#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Baixa a versão oficial consolidada da RDC 429/2020 no AnvisaLegis.

Preserva as fronteiras das tabelas HTML para o estruturador legislativo e
interrompe a atualização se a fonte deixar de apresentar elementos essenciais.
"""
from __future__ import annotations
import re, urllib.request
from html import unescape
from pathlib import Path

BASE=Path(__file__).resolve().parent.parent
OUT=BASE/'textos'/'RDC 429-2020--anvisa-legis.txt'
URL='https://anvisalegis.datalegis.net/action/ActionDatalegis.php?acao=abrirTextoAto&cod_menu=9434&cod_modulo=310&numeroAto=00000429&orgao=RDC%2FDC%2FANVISA%2FMS&seqAto=000&tipo=RDC&valorAno=2020'
MARCADOR_TABELA_INICIO='[[TABELA_INICIO]]'
MARCADOR_TABELA_FIM='[[TABELA_FIM]]'
LIXO_INTERFACE={
    '-->','NORMAS REGULATÓRIAS DA ANVISA','Busca de Normas','Voltar','COPIAR LINK',
    'CRIAR TAGS','IMPRIMIR','PDF','VER NOTAS DE ALTERAÇÃO','FECHAR NOTAS DE ALTERAÇÃO',
    '+','|','-','Ver mais detalhes','Carregando...'
}

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
    x=re.sub(r'(?is)<table\b[^>]*>',f'\n{MARCADOR_TABELA_INICIO}\n',x)
    x=re.sub(r'(?is)</table\s*>',f'\n{MARCADOR_TABELA_FIM}\n',x)
    x=re.sub(r'(?i)<br\s*/?>','\n',x)
    x=re.sub(r'(?i)</(?:p|div|li|tr|td|th|h[1-6])>','\n',x)
    x=re.sub(r'<[^>]+>',' ',x)
    x=unescape(x).replace('\xa0',' ')
    linhas=[]
    for ln in x.splitlines():
        ln=re.sub(r'[ \t]+',' ',ln).strip()
        if ln and ln not in LIXO_INTERFACE:
            linhas.append(ln)
    return '\n'.join(linhas)+'\n'

def validar(texto):
    normal=texto.upper()
    if not re.search(r'(?i)\bRDC\b\s*(?:N[º°.]*)?\s*429\b',texto):
        raise RuntimeError('Fonte não reconhecida como RDC 429/2020: número da RDC ausente')
    if not re.search(r'(?i)(?:DE\s+8\s+DE\s+OUTUBRO\s+DE\s+2020|RDC\s*(?:N[º°.]*)?\s*429[^\n]{0,120}2020)',texto):
        raise RuntimeError('Fonte não reconhecida como RDC 429/2020: referência temporal ausente')
    obrigatorios=(
        'ROTULAGEM NUTRICIONAL DOS ALIMENTOS EMBALADOS',
        'AÇÚCARES ADICIONADOS',
        'TABELA DE INFORMAÇÃO NUTRICIONAL',
        'ROTULAGEM NUTRICIONAL FRONTAL',
        'ALEGAÇÕES NUTRICIONAIS',
    )
    ausentes=[x for x in obrigatorios if x not in normal]
    if ausentes:
        raise RuntimeError('RDC 429/2020 falhou nas travas de conteúdo: '+', '.join(ausentes))
    if not re.search(r'(?im)^\s*Art\.?\s*50-A\b',texto):
        raise RuntimeError('RDC 429/2020 consolidada sem Art. 50-A; possível alteração estrutural da fonte')
    artigos=[int(x) for x in re.findall(r'(?im)^\s*Art\.?\s*(\d+)\s*[ºo°.]?',texto)]
    if not artigos or 1 not in artigos:
        raise RuntimeError('RDC 429/2020 sem Art. 1º reconhecível')
    if max(artigos)<51:
        raise RuntimeError(f'RDC 429/2020 aparentemente incompleta; maior artigo reconhecido: {max(artigos)}')
    aberturas=texto.count(MARCADOR_TABELA_INICIO)
    fechamentos=texto.count(MARCADOR_TABELA_FIM)
    if aberturas!=fechamentos:
        raise RuntimeError(f'HTML oficial com tabelas desbalanceadas: {aberturas} início(s), {fechamentos} fim(ns)')
    return len(set(artigos)), max(artigos), aberturas

def main():
    texto=limpar(baixar())
    qtd_artigos,maior,tabelas=validar(texto)
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(texto,encoding='utf-8')
    print(f'OK: RDC 429/2020 oficial preservada, {len(texto)} caracteres, {qtd_artigos} artigos numerados, maior Art. {maior}, Art. 50-A presente, {tabelas} tabela(s) HTML')

if __name__=='__main__':
    main()
