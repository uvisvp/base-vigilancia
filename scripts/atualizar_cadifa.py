#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Publica banco CADIFA a partir do painel oficial da Anvisa.

O painel é descoberto exclusivamente a partir de páginas oficiais da Anvisa.
A entidade e os campos são identificados pelo modelo do Power BI; alterações
incompatíveis fazem o workflow falhar em vez de publicar dados incorretos.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import hashlib, json, re, unicodedata

from diagnosticar_ifa_regularidade import (
    CADIFA_FONTES, abrir, descobrir_powerbi_cadifa, diagnosticar_painel,
    pontuar_cadifa, headers_powerbi
)

SAIDA=Path("dados/ifa_regularidade")


def norm(v):
    return unicodedata.normalize("NFKD",str(v or "")).encode("ascii","ignore").decode().lower()


def score_entidade(ent):
    s=norm(ent.get("entidade"))+" "+" ".join(norm(x) for x in ent.get("campos",[]))
    p=0
    for termo,peso in (("cadifa",8),("detentor",5),("insumo",4),("ifa",4),("revis",4),("carta",3),("valid",3),("situac",2),("status",2)):
        if termo in s:p+=peso
    if "notifica" in s or "pos-registro" in s:p-=8
    return p


def mapear_campos(campos):
    mapa={}
    regras={
        "detentor":["detentor"],
        "ifa":["insumo farmac","ifa","insumo"],
        "numero_cadifa":["numero cadifa","n cadifa","cadifa","numero da carta","carta"],
        "revisao":["ultima revis","revisao","revis"],
        "situacao":["situacao","status","valida","validade"],
    }
    usados=set()
    for destino,termos in regras.items():
        for c in campos:
            nc=norm(c)
            if c in usados: continue
            if any(t in nc for t in termos):
                mapa[destino]=c; usados.add(c); break
    return mapa


def payload(model_id,entidade,campos):
    selects=[]
    for c in campos:
        selects.append({"Column":{"Expression":{"SourceRef":{"Source":"c"}},"Property":c},"Name":f"{entidade}.{c}"})
    q={"Version":2,"From":[{"Name":"c","Entity":entidade,"Type":0}],"Select":selects}
    return {"version":"1.0.0","queries":[{"Query":{"Commands":[{"SemanticQueryDataShapeCommand":{"Query":q,"Binding":{"Primary":{"Groupings":[{"Projections":list(range(len(campos)))}]},"DataReduction":{"DataVolume":6,"Primary":{"Window":{"Count":100000}}},"Version":1},"ExecutionMetricsKind":1}}]},"CacheKey":""}],"cancelQueries":[],"modelId":model_id}


def inv(v):
    if isinstance(v,list):return {i:x for i,x in enumerate(v)}
    if not isinstance(v,dict):return {}
    o={}
    for k,x in v.items():
        if isinstance(x,int):o[x]=k
        else:
            try:o[int(k)]=x
            except:pass
    return o


def decodificar(resp,campos):
    saida=[]
    for resultado in resp.get("results",[]):
        for ds in resultado.get("result",{}).get("data",{}).get("dsr",{}).get("DS",[]):
            dics={n:inv(v) for n,v in ds.get("ValueDicts",{}).items()}
            for bloco in ds.get("PH",[]):
                for matriz in bloco.values():
                    if not isinstance(matriz,list):continue
                    esquema=[]; anterior=[None]*len(campos)
                    for linha in matriz:
                        if not isinstance(linha,dict):continue
                        if linha.get("S"):esquema=linha["S"]
                        cel=list(linha.get("C",[])); rep=int(linha.get("R",0) or 0); nul=int(linha.get("Ø",0) or 0); cur=0; vals=[]
                        for i in range(len(campos)):
                            mask=1<<i
                            if rep&mask:val=anterior[i]
                            elif nul&mask:val=None
                            elif cur<len(cel):val=cel[cur];cur+=1
                            else:val=None
                            if i<len(esquema):
                                dn=esquema[i].get("DN")
                                if dn and isinstance(val,int):val=dics.get(dn,{}).get(val,val)
                            vals.append(val)
                        anterior=vals
                        if any(v not in (None,"") for v in vals):saida.append(dict(zip(campos,vals)))
    return saida


def sha_obj(o):return hashlib.sha256(json.dumps(o,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()


def main():
    SAIDA.mkdir(parents=True,exist_ok=True)
    urls,desc_meta=descobrir_powerbi_cadifa()
    candidatos=[]
    for url in urls:
        try:
            d=diagnosticar_painel("cadifa",url,CADIFA_FONTES[0]); d["pontuacao_cadifa"]=pontuar_cadifa(d); candidatos.append(d)
        except Exception as e: print("Candidato ignorado:",url,type(e).__name__,e)
    if not candidatos: raise RuntimeError("Painel CADIFA não localizado a partir das páginas oficiais da Anvisa")
    candidatos.sort(key=lambda x:x.get("pontuacao_cadifa",0),reverse=True); diag=candidatos[0]
    if diag.get("pontuacao_cadifa",0)<5: raise RuntimeError("Nenhum painel encontrado pôde ser identificado com segurança como CADIFA")
    ents=sorted(diag["entidades"],key=score_entidade,reverse=True)
    if not ents or score_entidade(ents[0])<8: raise RuntimeError("Entidade CADIFA não identificada com segurança no modelo")
    ent=ents[0]; entidade=ent["entidade"]; campos=ent["campos"]
    mapa=mapear_campos(campos)
    if not mapa.get("detentor") or not mapa.get("ifa"): raise RuntimeError(f"Campos essenciais CADIFA ausentes: mapa={mapa}; campos={campos}")
    model_id=diag["modelos"][0]["id"]
    body=json.dumps(payload(model_id,entidade,campos),ensure_ascii=False,separators=(",",":")).encode()
    raw,status,_=abrir(f"{diag['api']}/public/reports/querydata?synchronous=true",headers_powerbi(diag['resource_key'],diag['pagina_powerbi'])|{"Content-Type":"application/json;charset=UTF-8"}) if False else (None,None,None)
    # abrir() é textual; usa urllib aqui para POST mantendo os cabeçalhos do painel.
    import ssl, urllib.request, gzip
    h=headers_powerbi(diag['resource_key'],diag['pagina_powerbi']); h["Content-Type"]="application/json;charset=UTF-8"
    req=urllib.request.Request(f"{diag['api']}/public/reports/querydata?synchronous=true",data=body,headers=h)
    with urllib.request.urlopen(req,timeout=240,context=ssl._create_unverified_context()) as r:
        rb=r.read(); status=r.status
        if "gzip" in r.headers.get("Content-Encoding","").lower():rb=gzip.decompress(rb)
    registros=decodificar(json.loads(rb.decode("utf-8",errors="replace")),campos)
    if not registros: raise RuntimeError("Painel CADIFA retornou zero registros")
    gerado=datetime.now(timezone.utc).isoformat()
    banco={"schema":"cadifa-v1","gerado_em":gerado,"fonte_oficial":CADIFA_FONTES[0],"pagina_oficial_cadifa":CADIFA_FONTES[1],"painel_oficial":diag["pagina_powerbi"],"observacao":"Banco público de CADIFAs para cruzamento regulatório. CADIFA não substitui certificado de análise e não comprova, isoladamente, a conformidade de um lote específico.","entidade_origem":entidade,"campos_origem":campos,"mapa_campos":mapa,"total":len(registros),"registros":registros}
    banco["sha256_conteudo"]=sha_obj(registros)
    (SAIDA/"cadifa.json").write_text(json.dumps(banco,ensure_ascii=False,indent=2),encoding="utf-8")
    mf=SAIDA/"manifest.json"; manifest={"schema":"ifa-regularidade-manifest-v1","gerado_em":gerado,"fontes":{}}
    if mf.exists():
        try:manifest=json.loads(mf.read_text(encoding="utf-8"))
        except:pass
    manifest["schema"]="ifa-regularidade-manifest-v1"; manifest["gerado_em"]=gerado; manifest.setdefault("fontes",{})["cadifa"]={"arquivo":"cadifa.json","fonte_oficial":CADIFA_FONTES[0],"painel_oficial":diag["pagina_powerbi"],"total":len(registros),"sha256":banco["sha256_conteudo"],"mapa_campos":mapa,"status_querydata":status}
    mf.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
    (SAIDA/"cadifa-descoberta.json").write_text(json.dumps({"gerado_em":gerado,"painel_escolhido":diag["pagina_powerbi"],"pontuacao":diag["pontuacao_cadifa"],"entidade":entidade,"campos":campos,"mapa_campos":mapa,"descoberta":desc_meta},ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"painel":diag["pagina_powerbi"],"entidade":entidade,"total":len(registros),"mapa_campos":mapa},ensure_ascii=False,indent=2))

if __name__=="__main__":main()
