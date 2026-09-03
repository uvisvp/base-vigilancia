#!/usr/bin/env python3
"""
Índice por categoria de aditivos alimentares — etapa derivada do pipeline.

RODA DENTRO DO REPOSITÓRIO, depois da etapa que gera
`dados/aditivos_alimentares/`. Não baixa nada da Anvisa: lê os fragmentos que
a etapa anterior já escreveu e apenas reagrupa.

Por que existe
--------------
A fragmentação publicada é pelo NOME DO ADITIVO: 75 fragmentos, 12,6 MB.
Resolve "aditivo -> categorias" com um fetch. Não resolve
"categoria -> aditivos permitidos", que é a pergunta que o inspetor faz
diante de um rótulo, e que exigiria baixar os 75 fragmentos.

Por que é etapa de pipeline e não um commit manual
--------------------------------------------------
Se o índice for gerado à mão e commitado uma vez, ele descola dos fragmentos
na primeira atualização e passa a mentir sem avisar: o manifesto informaria a
data da base, e o índice seria de outra geração. Aqui ele carrega a assinatura
da origem (`gerado_em` e `data_fonte` da base de aditivos) e o aplicativo
compara — se não bater, avisa em vez de responder.

Saída
-----
  dados/aditivos_alimentares/por_categoria/<cod>.json
  dados/aditivos_alimentares/por_categoria/manifest.json
  + entrada `aditivos_por_categoria` no dados/manifest.json

Verificação
-----------
Ao final, reconstrói as relações a partir do índice e compara com a origem
como multiconjunto. Se divergir, o script falha com código 1 e não publica —
índice derivado que perde ou inventa linha é pior do que índice nenhum.
"""
import json, os, sys, glob, collections, argparse

CAMPOS = [
    ('funcao', 'f'),
    ('limite_mg_kg', 'lm'),
    ('limite_g_100g', 'lg'),
    ('restricao_uso', 'r'),
    ('aplicacao_limites', 'ap'),
    ('explicacao_limite', 'ex'),
    ('regulamento_pos_consolidacao', 'rg'),
    ('regulamento_original', 'ro'),
    ('observacoes', 'ob'),
    ('aditivo', 'ad'),
]
VERSAO_ESQUEMA = 1


def carrega_fragmentos(origem):
    regs = []
    for p in sorted(glob.glob(os.path.join(origem, '*.json'))):
        if os.path.basename(p) in ('catalogo.json', 'categorias.json', 'manifest.json'):
            continue
        with open(p, encoding='utf-8') as f:
            d = json.load(f)
        if isinstance(d, list):
            regs += d
    return regs


def gera(dados_dir):
    origem = os.path.join(dados_dir, 'aditivos_alimentares')
    destino = os.path.join(origem, 'por_categoria')
    if not os.path.isdir(origem):
        sys.exit('etapa anterior não rodou: ' + origem + ' não existe')

    regs = carrega_fragmentos(origem)
    if not regs:
        sys.exit('nenhuma relação lida em ' + origem)

    with open(os.path.join(origem, 'categorias.json'), encoding='utf-8') as f:
        cats = {c['categoria']: c for c in json.load(f)['itens']}

    # assinatura da origem, para o aplicativo detectar índice defasado
    manifesto_geral = {}
    cam_man = os.path.join(dados_dir, 'manifest.json')
    if os.path.exists(cam_man):
        with open(cam_man, encoding='utf-8') as f:
            manifesto_geral = json.load(f)
    base_origem = (manifesto_geral.get('bases') or {}).get('aditivos_alimentares') or {}

    os.makedirs(destino, exist_ok=True)
    for antigo in glob.glob(os.path.join(destino, '*.json')):
        os.remove(antigo)     # regenera do zero: categoria que sumiu não pode ficar

    porcat = collections.defaultdict(list)
    for r in regs:
        porcat[r['numero_categoria']].append(r)

    manifesto = {
        'versao_esquema': VERSAO_ESQUEMA,
        'derivado_de': 'aditivos_alimentares',
        'origem_gerado_em': base_origem.get('gerado_em'),
        'origem_data_fonte': base_origem.get('data_fonte'),
        'origem_registros': base_origem.get('registros'),
        'relacoes': len(regs),
        'campos': {alias: nome for nome, alias in CAMPOS},
        'categorias': {},
        'nota': 'Reagrupamento dos fragmentos por aditivo. Nenhum texto foi alterado; '
                'os campos textuais viram dicionário local e a linha guarda o índice.'
    }

    total = 0
    for cod, lista in sorted(porcat.items()):
        dic = {alias: [] for _, alias in CAMPOS}
        pos = {alias: {} for _, alias in CAMPOS}

        def idx(alias, valor):
            valor = valor if valor is not None else ''
            if valor not in pos[alias]:
                pos[alias][valor] = len(dic[alias])
                dic[alias].append(valor)
            return pos[alias][valor]

        linhas = []
        for r in lista:
            linhas.append([r['ins'], 1 if r.get('possui_restricao') == 'Sim' else 0]
                          + [idx(alias, r.get(nome, '')) for nome, alias in CAMPOS])

        linhas.sort(key=lambda L: (dic['f'][L[2]],
                                   int(''.join(ch for ch in L[0] if ch.isdigit()) or 0)))

        c = cats.get(cod, {})
        saida = {
            'categoria': cod,
            'nome': c.get('nome_categoria', ''),
            'descricao': c.get('descricao_categoria', ''),
            'codex': c.get('categoria_codex', ''),
            'regulamentos': c.get('regulamentos', ''),
            'alimentos': c.get('alimentos', ''),
            'origem_gerado_em': manifesto['origem_gerado_em'],
            'colunas': ['ins', 'restrito'] + [alias for _, alias in CAMPOS],
            'dic': dic,
            'linhas': linhas,
        }
        txt = json.dumps(saida, ensure_ascii=False, separators=(',', ':'))
        with open(os.path.join(destino, cod + '.json'), 'w', encoding='utf-8') as f:
            f.write(txt)
        manifesto['categorias'][cod] = {'n': len(linhas), 'bytes': len(txt.encode())}
        total += len(txt.encode())

    # categorias sem nenhum aditivo entram com n=0: o aplicativo precisa saber
    # que a categoria existe e não tem aditivo, e não que o arquivo faltou
    for cod in sorted(cats):
        manifesto['categorias'].setdefault(cod, {'n': 0, 'bytes': 0})

    with open(os.path.join(destino, 'manifest.json'), 'w', encoding='utf-8') as f:
        json.dump(manifesto, f, ensure_ascii=False, separators=(',', ':'))

    return regs, destino, manifesto, total


def verifica(regs, destino):
    """Reconstrói as relações a partir do índice. Divergiu, não publica."""
    rec = []
    for p in glob.glob(os.path.join(destino, '*.json')):
        if os.path.basename(p) == 'manifest.json':
            continue
        with open(p, encoding='utf-8') as f:
            d = json.load(f)
        pos = {c: i for i, c in enumerate(d['colunas'])}
        for L in d['linhas']:
            r = {'numero_categoria': d['categoria'], 'ins': L[pos['ins']],
                 'possui_restricao': 'Sim' if L[pos['restrito']] else 'Não'}
            for nome, alias in CAMPOS:
                r[nome] = d['dic'][alias][L[pos[alias]]]
            rec.append(r)

    def chave(r):
        return tuple(sorted((k, (v if v is not None else ''))
                            for k, v in r.items() if k != 'categoria_alimento'))

    a = collections.Counter(chave(r) for r in regs)
    b = collections.Counter(chave(r) for r in rec)
    if a != b:
        so_a, so_b = a - b, b - a
        print('VERIFICAÇÃO FALHOU', file=sys.stderr)
        print('  só na origem: %d | só no índice: %d'
              % (sum(so_a.values()), sum(so_b.values())), file=sys.stderr)
        for k in list(so_a)[:3]:
            print('  ORIGEM', dict(k), file=sys.stderr)
        for k in list(so_b)[:3]:
            print('  ÍNDICE', dict(k), file=sys.stderr)
        return False
    return True


def registra_no_manifesto(dados_dir, manifesto, total):
    cam = os.path.join(dados_dir, 'manifest.json')
    if not os.path.exists(cam):
        return
    with open(cam, encoding='utf-8') as f:
        m = json.load(f)
    m.setdefault('bases', {})
    base = (m['bases'].get('aditivos_alimentares') or {})
    m['bases']['aditivos_por_categoria'] = {
        'status': 'ok',
        'tipo_fonte': 'derivado de aditivos_alimentares',
        'fonte': base.get('fonte'),
        'data_fonte': base.get('data_fonte'),
        'gerado_em': base.get('gerado_em'),
        'registros': manifesto['relacoes'],
        'fragmentos': sum(1 for v in manifesto['categorias'].values() if v['n']),
        'chave': 'código da categoria da IN 211/2023',
        'fragmentacao': 'um arquivo por categoria',
        'bytes': total,
        'observacao': 'Reagrupamento sem perda. A data de fonte é a da base de origem, '
                      'não a deste reagrupamento.'
    }
    with open(cam, 'w', encoding='utf-8') as f:
        json.dump(m, f, ensure_ascii=False, indent=1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dados', default='dados', help='diretório dados/ do repositório')
    a = ap.parse_args()

    regs, destino, manifesto, total = gera(a.dados)
    if not verifica(regs, destino):
        sys.exit(1)
    registra_no_manifesto(a.dados, manifesto, total)

    com = sum(1 for v in manifesto['categorias'].values() if v['n'])
    tam = sorted(v['bytes'] for v in manifesto['categorias'].values() if v['bytes'])
    print('por_categoria: %d categorias com aditivo, %d sem'
          % (com, len(manifesto['categorias']) - com))
    print('  %d relações reagrupadas · verificação sem perda: ok' % manifesto['relacoes'])
    print('  %.2f MB no total · mediana %d KB · maior %d KB'
          % (total / 1e6, tam[len(tam) // 2] / 1024, tam[-1] / 1024))
    print('  assinatura da origem: gerado_em=%s' % manifesto['origem_gerado_em'])


if __name__ == '__main__':
    main()
