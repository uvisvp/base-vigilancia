#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
import json
from collections import Counter

import atualizar_legislacao_adicional as core
from estruturar_legislacao import estruturar_texto, slug

NORMAS=[
 {'norma_id':'rdc-anvisa-672-2022','norma':'RDC 672-2022','grupo':'rdc-anvisa','rotulo':'RDC Anvisa nº 672/2022',
  'url':'https://anvisalegis.datalegis.net/action/ActionDatalegis.php?acao=abrirTextoAto&cod_menu=8542&cod_modulo=310&link=S&numeroAto=00000672&orgao=RDC%2FDC%2FANVISA%2FMS&seqAto=000&tipo=RDC&valorAno=2022',
  'data_fonte':'2022-03-30','status_vigencia':'vigente','status_fonte':'AnvisaLegis: vigente; art. 12 revoga expressamente a RDC 362/2020',
  'min_chars':7000,'obrig':['RDC Nº 672','insumos farmacêuticos ativos','Art. 12','RDC nº 362']},
 {'norma_id':'rdc-anvisa-497-2021','norma':'RDC 497-2021','grupo':'rdc-anvisa','rotulo':'RDC Anvisa nº 497/2021 — texto consolidado',
  'url':'https://anvisalegis.datalegis.net/action/ActionDatalegis.php?acao=abrirTextoAto&cod_menu=8542&cod_modulo=310&link=S&numeroAto=00000497&orgao=RDC%2FDC%2FANVISA%2FMS&seqAto=000&tipo=RDC&valorAno=2021',
  'data_fonte':'2021-05-20','status_vigencia':'vigente_com_alteracoes','status_fonte':'AnvisaLegis: vigente com alterações; texto consolidado inclui alterações posteriores',
  'min_chars':18000,'obrig':['RDC Nº 497','Certificação de Boas Práticas','Art. 28','Insumos Farmacêuticos Ativos']},
 {'norma_id':'rdc-anvisa-362-2020','norma':'RDC 362-2020','grupo':'rdc-anvisa','rotulo':'RDC Anvisa nº 362/2020 — revogada',
  'url':'https://cvs.saude.sp.gov.br/zip/U_RS-MS-ANVISA-RDC-362_270320.pdf',
  'fonte_normativa_oficial':'https://anvisalegis.datalegis.net/action/ActionDatalegis.php?acao=abrirTextoAto&cod_menu=8542&cod_modulo=310&link=S&numeroAto=00000362&orgao=RDC%2FDC%2FANVISA%2FMS&seqAto=000&tipo=RDC&valorAno=2020',
  'fonte_status':'https://anvisalegis.datalegis.net/action/ActionDatalegis.php?acao=abrirTextoAto&cod_menu=8542&cod_modulo=310&link=S&numeroAto=00000672&orgao=RDC%2FDC%2FANVISA%2FMS&seqAto=000&tipo=RDC&valorAno=2022',
  'nota_fonte_texto':'Espelho do DOU preservado pelo Centro de Vigilância Sanitária/SP; a revogação é comprovada pelo art. 12 da RDC 672/2022.',
  'data_fonte':'2020-03-27','status_vigencia':'revogada_2022-05-02','status_fonte':'RDC 672/2022, art. 12; revogada com a entrada em vigor da RDC 672 em 2/5/2022',
  'min_chars':5000,'obrig':['RDC Nº 362','insumos farmacêuticos ativos','Art. 1']},
]

def main():
 core.NORMAS=NORMAS
 core.garantir_catalogo()
 (core.SAIDA/'normas').mkdir(parents=True,exist_ok=True); core.TEXTOS.mkdir(exist_ok=True)
 mp=core.SAIDA/'manifest.json'; man=json.loads(mp.read_text(encoding='utf-8'))
 rel={'schema':'relatorio-legislacao-ifa-certificacao-v1','gerado_em':core.agora(),'normas':[]}
 for n in NORMAS:
  print('Baixando',n['norma']); r=core.baixar(n['url']); txt,formato=core.extrair_resposta(r); core.validar(n,txt)
  pasta=core.FONTES/n['norma_id']; pasta.mkdir(parents=True,exist_ok=True)
  (pasta/f'texto_bruto.{formato}').write_bytes(r.content)
  tp=core.TEXTOS/f"{n['norma']}--oficial.txt"; tp.write_text(txt,encoding='utf-8')
  meta={'norma':n['norma'],'fonte_oficial':n.get('fonte_normativa_oficial',n['url']),'fonte_texto_utilizada':n['url'],
   'fonte_status':n.get('fonte_status'),'nota_fonte_texto':n.get('nota_fonte_texto'),'url_final':r.url,'consultado_em':core.agora(),
   'data_fonte':n['data_fonte'],'tipo_data_fonte':'data_do_ato; texto consultado em fonte institucional identificada na proveniência',
   'formato_fonte':formato,'sha256_fonte':core.sha_b(r.content),'sha256_texto':core.sha_t(txt),'status_vigencia':n['status_vigencia'],
   'status_fonte':n['status_fonte'],'texto':str(tp.relative_to(core.BASE)),'data_processamento':core.agora(),
   'schema':'proveniencia-legislativa-v1','escopo_validacao':'consulta estruturada; observar status de vigência e alterações'}
  tp.with_suffix('.meta.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding='utf-8')
  doc=estruturar_texto(n['norma'],txt); core.aplicar_meta(doc,meta)
  ids=[x['id'] for x in doc['nos'] if x.get('estrutural',True)]
  rep=[k for k,v in Counter(ids).items() if v>1]
  if rep: raise RuntimeError(f"{n['norma']}: IDs repetidos {rep[:10]}")
  fn=slug(n['norma'])+'.json'; (core.SAIDA/'normas'/fn).write_text(json.dumps(doc,ensure_ascii=False,indent=2),encoding='utf-8')
  man['normas'][n['norma']]={'arquivo':fn,'nos':len(doc['nos']),'sha256_texto':doc['sha256_texto'],'proveniencia':meta}
  rel['normas'].append({'norma':n['norma'],'arquivo':fn,'nos':len(doc['nos']),'chars':len(txt),'status_vigencia':n['status_vigencia']})
 man['gerado_em']=core.agora(); mp.write_text(json.dumps(man,ensure_ascii=False,indent=2),encoding='utf-8')
 rel['total_normas_manifest']=len(man['normas'])
 (core.SAIDA/'relatorio-legislacao-ifa-certificacao.json').write_text(json.dumps(rel,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps(rel,ensure_ascii=False))

if __name__=='__main__': main()
