#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Inclui no banco hierárquico (legislacao_v12) as normas municipais de academias e
piscinas usadas pelo roteiro "Academias e piscinas" (app Roteiros), pedido de
16/10/2026:
  - Portaria SMS nº 1.101/2015 (regulamento técnico: lutas, ginástica, musculação,
    natação, saunas) — texto do PDF do Catálogo de Legislação Municipal enviado
    pela equipe; itens do Anexo como nós "item" (ex.: ...::item::6-2-4);
  - Lei 11.383/1993 (academias; redação vigente dada pelas Leis 15.527/2012 e
    15.681/2013), Lei 15.681/2013, Lei 17.105/2019 (sistema hidráulico de
    piscinas), Lei 13.993/2005 (profundidade nas bordas), Lei 16.059/2014
    (salva-vidas ou guardião), Lei 13.945/2005 (desfibrilador) — texto do site
    legislacao.prefeitura.sp.gov.br.
Texto consolidado: quando a página traz redações sucessivas do mesmo artigo,
fica só a última (a vigente); a anotação “(Redação dada pela Lei …)” vai para
o campo "alteracao". Não reprocessa as demais normas do banco.
Uso: python scripts/incluir_normas_academia_piscina.py"""
from __future__ import annotations
import hashlib, json, re, unicodedata
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
TEXTOS = BASE / 'textos'; SAIDA = BASE / 'dados' / 'legislacao_v12'
AGORA = datetime.now(timezone.utc).isoformat()
SITE = 'https://legislacao.prefeitura.sp.gov.br/leis/'
NORMAS = [
  ('Portaria SMS SP 1101-2015', 'portaria', 'https://legislacao.prefeitura.sp.gov.br/', '2015-06-19',
   'PDF do Catálogo de Legislação Municipal (legislacao.prefeitura.sp.gov.br) enviado pela equipe em 16/10/2026', 'vigente'),
  ('Lei Municipal SP 11383-1993', 'lei', SITE + 'lei-11383-de-28-de-junho-de-1993', '1993-06-28', None, 'vigente_com_alteracoes'),
  ('Lei Municipal SP 15681-2013', 'lei', SITE + 'lei-15681-de-04-de-janeiro-de-2013', '2013-01-04', None, 'vigente'),
  ('Lei Municipal SP 17105-2019', 'lei', SITE + 'lei-17105-de-3-de-junho-de-2019', '2019-06-03', None, 'vigente'),
  ('Lei Municipal SP 13993-2005', 'lei', SITE + 'lei-13993-de-10-de-junho-de-2005', '2005-06-10', None, 'vigente'),
  ('Lei Municipal SP 16059-2014', 'lei', SITE + 'lei-16059-de-13-de-agosto-de-2014', '2014-08-13', None, 'vigente'),
  ('Lei Municipal SP 13945-2005', 'lei', SITE + 'lei-13945-de-07-de-janeiro-de-2005', '2005-01-07', None, 'vigente_com_alteracoes'),
]

def slug(s):
    s = unicodedata.normalize('NFKD', str(s)).encode('ascii', 'ignore').decode('ascii')
    return re.sub(r'[^a-zA-Z0-9]+', '-', s).strip('-').lower()
def sha(s): return hashlib.sha256(s.encode()).hexdigest()
RE_ALT = re.compile(r'\s*\((Reda[çc][ãa]o dada|Inclu[íi]d[oa]|Acrescid[oa]|Revogad[oa])[^)]*\)\s*$', re.I)
def tira_alt(t):
    m = RE_ALT.search(t)
    return (t[:m.start()].rstrip(), m.group(0).strip(' ()')) if m else (t, None)

RE_ART = re.compile(r'^Art\.?\s*(\d+)\s*[ºo°]?\.?\s*(?:-?\s*([A-Z])\s*(?=[-–]))?\s*[-–.]?\s*(.*)$')
RE_PAR = re.compile(r'^§\s*(\d+)\s*[ºo°]?\.?\s*(.*)$')
RE_PU = re.compile(r'^Par[áa]grafo\s+[úu]nico\.?\s*[-–]?\s*(.*)$', re.I)
RE_INC = re.compile(r'^([IVXLC]+)\s*[-–]\s*(.*)$')
RE_ALI = re.compile(r'^([a-z])\)\s*(.*)$')
RE_ANEXO = re.compile(r'^ANEXO\s+([IVX]+)\s*$')
RE_FIM = re.compile(r'^(Câmara Municipal de São Paulo|PREFEITURA DO MUNICÍPIO|Publicada na|O Presidente|Este texto não substitui)', re.I)

def limpa(texto):
    texto = texto.replace('\ufb01', 'fi').replace('\ufb02', 'fl').replace('\x00', '')
    ls = texto.split('\n')
    # menu do site antes do cabeçalho real: começa na última linha “LEI Nº …” antes do Art. 1
    a1 = next((i for i, l in enumerate(ls) if re.match(r'^\s*Art\.?\s*1\s*[ºo°]', l)), len(ls))
    cab = [i for i, l in enumerate(ls[:a1]) if re.match(r'^\s*LEI N[ºo°]', l.strip(), re.I)]
    return '\n'.join(ls[cab[-1]:] if cab else ls)

def lei(norma, texto, status):
    texto = limpa(texto)
    ns = slug(norma); arts = {}; ordem_art = []; atual = None; anexo = None; anexos = {}; fim = False; quote = False; pre = []
    for bruta in texto.split('\n'):
        l = bruta.strip()
        if not l: continue
        m = RE_ANEXO.match(l)
        if m: anexo = m.group(1); anexos[anexo] = []; fim = True; continue
        if anexo: anexos[anexo].append(l); continue
        if RE_FIM.match(l): fim = True; continue
        if fim: continue
        if quote:                       # citação de outra lei (lei alteradora): continua no artigo
            atual['texto'] += '\n' + l
            if l.endswith('”') or l.endswith('"'): quote = False
            continue
        if l.startswith('“') or l.startswith('"'):
            if atual is None: pre.append(l); continue
            atual['texto'] += '\n' + l; quote = not (l.endswith('”') or l.endswith('"')); continue
        m = RE_ART.match(l)
        if m:
            num = m.group(1) + ('-' + m.group(2).lower() if m.group(2) else '')
            t, alt = tira_alt(l)
            atual = {'num': num, 'texto': t, 'alt': alt, 'filhos': []}
            if num not in arts: ordem_art.append(num)
            arts[num] = atual          # redação posterior substitui a anterior
            continue
        if atual is None: pre.append(l); continue
        for tipo, rx in (('paragrafo', RE_PAR), ('paragrafo', RE_PU), ('inciso', RE_INC), ('alinea', RE_ALI)):
            m = rx.match(l)
            if m:
                t, alt = tira_alt(l)
                n = 'unico' if rx is RE_PU else m.group(1)
                atual['filhos'].append({'tipo': tipo, 'num': n, 'texto': t, 'alt': alt}); break
        else:
            t, alt = tira_alt(l)
            alvo = atual['filhos'][-1] if atual['filhos'] else atual
            alvo['texto'] += '\n' + t
            if alt: alvo['alt'] = alt
    nos = []; o = 0
    def no(**k):
        nonlocal o; o += 1
        d = {'id': k['id'], 'norma': norma, 'anexo': k.get('anexo'), 'tipo': k['tipo'], 'numero': k['numero'], 'rotulo': k['rotulo'],
             'texto': k['texto'], 'ordem': o, 'status_vigencia': status}
        if k.get('pai'): d['pai'] = k['pai']
        if k.get('alt'): d['alteracao'] = k['alt']
        nos.append(d)
    if pre: no(id=f'{ns}::ementa::1', tipo='ementa', numero='1', rotulo='Ementa e preâmbulo', texto='\n'.join(pre))
    for num in ordem_art:
        a = arts[num]; aid = f'{ns}::artigo::{num}'; rot = 'Art. ' + num.replace('-', '-').upper()
        no(id=aid, tipo='artigo', numero=num, rotulo=rot, texto=a['texto'], alt=a['alt'])
        ultimo_inc = None
        for f in a['filhos']:
            if f['tipo'] == 'alinea' and ultimo_inc: pai = ultimo_inc
            else: pai = aid
            fid = f'{pai}::{f["tipo"]}::{f["num"].lower()}'
            r = {'paragrafo': ('Parágrafo único' if f['num'] == 'unico' else f'§ {f["num"]}º') + f' do art. {num.upper()}',
                 'inciso': f'Inciso {f["num"]}', 'alinea': f'Alínea {f["num"]}'}[f['tipo']]
            no(id=fid, tipo=f['tipo'], numero=f['num'], rotulo=r, texto=f['texto'], pai=pai, alt=f['alt'])
            if f['tipo'] == 'inciso': ultimo_inc = fid
    for an, ls in anexos.items():
        no(id=f'{ns}::anexo-{an.lower()}::bloco::1', anexo=an, tipo='bloco', numero='1', rotulo=f'Anexo {an}', texto='\n'.join(ls))
    return nos

def portaria(norma, texto, status):
    texto = texto.replace('\ufb01', 'fi').replace('\ufb02', 'fl')
    ns = slug(norma)
    ruido = re.compile(r'^(PORTARIA SECRETARIA MUNICIPAL DA SAÚDE - SMS Nº 1\.101|DE 19 DE JUNHO DE 2015|Este texto não substitui)', re.I)
    ementa = 'Aprova Regulamento Técnico estabelecendo'
    novo = re.compile(r'^(Art\.\s*\d|\d+(?:\.\d+)*\.\s|[IVX]+\.\s|ANEXO$|Regulamento técnico sobre|[A-ZÁÉÍÓÚ][\wÀ-ÿ ()\-/]{2,70}:\s)')
    linhas = []; pula = 0
    for l in (x.strip() for x in texto.replace('\x00', '').split('\n')):
        if not l or ruido.match(l): continue
        if l.startswith(ementa) and linhas and 'ANEXO' not in linhas[-1] and any('Art. 5' in x for x in linhas): pula = 4; continue
        if pula: pula -= 1; continue
        if not linhas or novo.match(l): linhas.append(l)
        else: linhas[-1] += ' ' + l
    nos = []; o = 0; item = None; itens = set()
    def no(**k):
        nonlocal o; o += 1
        d = {'id': k['id'], 'norma': norma, 'anexo': k.get('anexo'), 'tipo': k['tipo'], 'numero': k['numero'], 'rotulo': k['rotulo'],
             'texto': re.sub(r'\s+', ' ', k['texto']).replace('   ', ' – ').strip(), 'ordem': o, 'status_vigencia': status}
        if k.get('pai'): d['pai'] = k['pai']
        nos.append(d); return d
    pre = []
    for l in linhas:
        m = re.match(r'^Art\.\s*(\d+)\s*[ºo°]?\s*[-–]?\s*(.*)$', l)
        if m and item is None:
            no(id=f'{ns}::artigo::{m.group(1)}', tipo='artigo', numero=m.group(1), rotulo=f'Art. {m.group(1)}', texto=l); continue
        m = re.match(r'^(\d+(?:\.\d+)*)\.\s+(.*)$', l)
        if m:
            num = m.group(1); partes = num.split('.')
            pai = f'{ns}::item::{"-".join(partes[:-1])}' if len(partes) > 1 and '-'.join(partes[:-1]) in itens else None
            item = no(id=f'{ns}::item::{num.replace(".", "-")}', anexo='Regulamento técnico', tipo='item', numero=num,
                      rotulo=f'Item {num}', texto=f'{num}. {m.group(2)}', pai=pai)
            itens.add(num.replace('.', '-')); continue
        m = re.match(r'^([IVX]+)\.\s+(.*)$', l)
        if m and item:
            no(id=f'{item["id"]}::inciso::{m.group(1).lower()}', anexo='Regulamento técnico', tipo='inciso', numero=m.group(1),
               rotulo=f'Inciso {m.group(1)}', texto=l, pai=item['id']); continue
        if item: item['texto'] += '\n' + l
        else: pre.append(l)
    if pre: nos.insert(0, {'id': f'{ns}::ementa::1', 'norma': norma, 'anexo': None, 'tipo': 'ementa', 'numero': '1', 'rotulo': 'Preâmbulo',
                           'texto': '\n'.join(pre), 'ordem': 0, 'status_vigencia': status})
    return nos

def main():
    man_p = SAIDA / 'manifest.json'; man = json.loads(man_p.read_text(encoding='utf-8'))
    for norma, tipo, url, data, nota, status in NORMAS:
        tf = TEXTOS / f'{norma}--oficial.txt'; texto = tf.read_text(encoding='utf-8')
        nos = (portaria if tipo == 'portaria' else lei)(norma, texto, status)
        ids = [n['id'] for n in nos]; rep = sorted({i for i in ids if ids.count(i) > 1})
        alts = sorted({n['alteracao'] for n in nos if n.get('alteracao')})
        prov = {'norma': norma, 'fonte_oficial': url, 'fonte_texto_utilizada': url if not nota else nota, 'nota_fonte_texto': nota,
                'consultado_em': AGORA, 'data_fonte': data, 'tipo_data_fonte': 'data_do_ato; texto consolidado do Catálogo de Legislação Municipal',
                'formato_fonte': 'pdf' if nota else 'html', 'sha256_texto': sha(texto), 'alteracoes_encontradas': alts,
                'status_vigencia': status, 'texto': f'textos\\{tf.name}', 'data_processamento': AGORA, 'schema': 'proveniencia-legislativa-v1',
                'escopo_validacao': 'dispositivos vinculados ao roteiro de academias e piscinas (app Roteiros); demais usos exigem revisão própria'}
        (TEXTOS / f'{norma}--oficial.meta.json').write_text(json.dumps(prov, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        arq = slug(norma) + '.json'
        doc = {'schema': 'legislacao-hierarquica-v12', 'norma': norma, 'sha256_texto': sha(texto), 'nos': nos,
               'validacao': {'ids_estruturais_repetidos': rep, 'artigos_repetidos_na_fonte': {}}, 'proveniencia': prov}
        (SAIDA / 'normas' / arq).write_text(json.dumps(doc, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
        man['normas'][norma] = {'arquivo': arq, 'nos': len(nos), 'sha256_texto': sha(texto), 'proveniencia': prov}
        print(f'{norma}: {len(nos)} nós, repetidos {len(rep)} -> {arq}')
    man['gerado_em'] = AGORA
    man_p.write_text(json.dumps(man, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

if __name__ == '__main__': main()
