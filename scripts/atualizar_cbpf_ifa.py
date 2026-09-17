#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Extrai o painel oficial de Certificados de Boas Práticas da Anvisa.

Publica um banco destinado ao cruzamento regulatório de IFA. O banco preserva
os campos oficiais do painel e marca registros cujo TIPO/ESCOPO indicam IFA,
sem emitir conclusão automática de regularidade sanitária.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, urlunparse
import gzip, hashlib, json, re, ssl, urllib.request, uuid

PAGINA = "https://app.powerbi.com/view?r=eyJrIjoiNTU3MDE4OTgtYzc5NS00NGRhLWI0ODMtOWUzN2E2Njc5MzdlIiwidCI6ImI2N2FmMjNmLWMzZjMtNGQzNS04MGM3LWI3MDg1ZjVlZGQ4MSJ9"
FONTE = "https://www.gov.br/anvisa/pt-br/setorregulado/certificados-de-boas-praticas"
ENTIDADE = "Consulta1"
CAMPOS = [
    "CNPJ", "SOLICITANTE DO CERTIFICADO", "ESTABELECIMENTO CERTIFICADO",
    "ENDEREÇO", "PAIS", "ESTADO", "TIPO", "ESCOPO", "RESOLUÇÃO",
    "DATA DE PUBLICAÇÃO", "DATA DE VALIDADE", "CHECK 1", "HOJE", "INÍCIO"
]
SAIDA = Path("dados/ifa_regularidade")


def abrir_bytes(url, headers=None, body=None):
    req = urllib.request.Request(url, data=body, headers=headers or {"User-Agent":"Mozilla/5.0 base-vigilancia"})
    with urllib.request.urlopen(req, timeout=240, context=ssl._create_unverified_context()) as r:
        b = r.read()
        if "gzip" in r.headers.get("Content-Encoding", "").lower(): b = gzip.decompress(b)
        return b, r.status, dict(r.headers.items())


def abrir_texto(url, headers=None):
    b,s,h=abrir_bytes(url,headers); return b.decode("utf-8",errors="replace"),s,h


def localizar_json(html,nome):
    p=rf"var\s+{re.escape(nome)}\s*=\s*"
    m=re.search(p+r"JSON\.parse\('((?:\\.|[^'])*)'\)",html,re.S)
    if m:
        bruto=m.group(1); dec=json.loads('"'+bruto.replace('"','\\"').replace('\\"','\"')+'"'); return json.loads(dec)
    m=re.search(p,html,re.S)
    if m: return json.JSONDecoder().raw_decode(html[m.end():].lstrip())[0]
    raise RuntimeError(f"Variável {nome} não localizada")


def api_cluster(uri):
    p=urlparse(uri); partes=(p.hostname or "").split("."); partes[0]=partes[0].replace("-redirect","").replace("global-","")+"-api"
    return urlunparse((p.scheme or "https",".".join(partes),"","","","")).rstrip("/")


def headers_pbi(key,json_post=False):
    h={"Accept":"application/json","ActivityId":str(uuid.uuid4()),"RequestId":str(uuid.uuid4()),"X-PowerBI-ResourceKey":key,"Origin":"https://app.powerbi.com","Referer":PAGINA,"User-Agent":"Mozilla/5.0 base-vigilancia"}
    if json_post: h["Content-Type"]="application/json;charset=UTF-8"
    return h


def payload(model_id):
    selects=[]
    for c in CAMPOS:
        selects.append({"Column":{"Expression":{"SourceRef":{"Source":"c"}},"Property":c},"Name":f"{ENTIDADE}.{c}"})
    query={"Version":2,"From":[{"Name":"c","Entity":ENTIDADE,"Type":0}],"Select":selects}
    return {"version":"1.0.0","queries":[{"Query":{"Commands":[{"SemanticQueryDataShapeCommand":{"Query":query,"Binding":{"Primary":{"Groupings":[{"Projections":list(range(len(CAMPOS)))}]},"DataReduction":{"DataVolume":6,"Primary":{"Window":{"Count":100000}}},"Version":1},"ExecutionMetricsKind":1}}]},"CacheKey":""}],"cancelQueries":[],"modelId":model_id}


def inv(v):
    if isinstance(v,list): return {i:x for i,x in enumerate(v)}
    if not isinstance(v,dict): return {}
    out={}
    for k,x in v.items():
        if isinstance(x,int): out[x]=k
        else:
            try: out[int(k)]=x
            except: pass
    return out


def datasets(resp):
    out=[]
    for r in resp.get("results",[]): out += r.get("result",{}).get("data",{}).get("dsr",{}).get("DS",[])
    return out


def decodificar(resp):
    saida=[]
    for ds in datasets(resp):
        dics={n:inv(v) for n,v in ds.get("ValueDicts",{}).items()}
        for bloco in ds.get("PH",[]):
            for matriz in bloco.values():
                if not isinstance(matriz,list): continue
                esquema=[]; anterior=[None]*len(CAMPOS)
                for linha in matriz:
                    if not isinstance(linha,dict): continue
                    if linha.get("S"): esquema=linha["S"]
                    cel=list(linha.get("C",[])); rep=int(linha.get("R",0) or 0); nul=int(linha.get("Ø",0) or 0); cur=0; vals=[]
                    for i in range(len(CAMPOS)):
                        mask=1<<i
                        if rep & mask: val=anterior[i]
                        elif nul & mask: val=None
                        elif cur < len(cel): val=cel[cur]; cur+=1
                        else: val=None
                        if i < len(esquema):
                            dn=esquema[i].get("DN")
                            if dn and isinstance(val,int): val=dics.get(dn,{}).get(val,val)
                        vals.append(val)
                    anterior=vals
                    if any(v not in (None,"") for v in vals): saida.append(dict(zip(CAMPOS,vals)))
    return saida


def texto(v): return str(v or "").strip()

def norm(v):
    import unicodedata
    return unicodedata.normalize("NFKD",texto(v)).encode("ascii","ignore").decode().upper()


def e_ifa(r):
    s=norm(r.get("TIPO"))+" "+norm(r.get("ESCOPO"))
    return "INSUMO" in s or "IFA" in s or "FARMACEUTIC" in s


def sha_obj(obj):
    b=json.dumps(obj,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode(); return hashlib.sha256(b).hexdigest()


def main():
    SAIDA.mkdir(parents=True,exist_ok=True)
    html,_,_=abrir_texto(PAGINA)
    desc=localizar_json(html,"resourceDescriptor"); cluster=localizar_json(html,"clusterAssignmentRecord"); key=desc["k"]; api=api_cluster(cluster["FixedClusterUri"])
    modelos=json.loads(abrir_texto(f"{api}/public/reports/{key}/modelsAndExploration?preferReadOnlySession=true",headers_pbi(key))[0])
    model_id=modelos["models"][0]["id"]
    body=json.dumps(payload(model_id),ensure_ascii=False,separators=(",",":")).encode()
    raw,status,_=abrir_bytes(f"{api}/public/reports/querydata?synchronous=true",headers_pbi(key,True),body)
    resp=json.loads(raw.decode("utf-8",errors="replace")); todos=decodificar(resp)
    registros=[]
    for r in todos:
        rr={k:r.get(k) for k in CAMPOS}; rr["escopo_ifa"] = e_ifa(rr); registros.append(rr)
    ifas=[r for r in registros if r["escopo_ifa"]]
    if not registros: raise RuntimeError("Painel CBPF retornou zero registros")
    if not ifas: raise RuntimeError("Nenhum registro do painel foi identificado como IFA por TIPO/ESCOPO; revisar classificador antes de publicar")
    gerado=datetime.now(timezone.utc).isoformat()
    banco={"schema":"cbpf-ifa-v1","gerado_em":gerado,"fonte_oficial":FONTE,"painel_oficial":PAGINA,"observacao":"Banco para cruzamento regulatório. A presença de certificado não constitui, isoladamente, conclusão de regularidade do IFA ou de lote específico.","campos_origem":CAMPOS,"total_painel":len(registros),"total_ifa":len(ifas),"registros":ifas}
    banco["sha256_conteudo"]=sha_obj(ifas)
    (SAIDA/"cbpf_ifa.json").write_text(json.dumps(banco,ensure_ascii=False,indent=2),encoding="utf-8")
    resumo={"schema":"ifa-regularidade-manifest-v1","gerado_em":gerado,"fontes":{"cbpf_ifa":{"arquivo":"cbpf_ifa.json","fonte_oficial":FONTE,"painel_oficial":PAGINA,"total":len(ifas),"sha256":banco["sha256_conteudo"],"status_querydata":status}}}
    mf=SAIDA/"manifest.json"
    if mf.exists():
        try:
            antigo=json.loads(mf.read_text(encoding="utf-8")); resumo["fontes"]={**antigo.get("fontes",{}),**resumo["fontes"]}
        except: pass
    mf.write_text(json.dumps(resumo,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"total_painel":len(registros),"total_ifa":len(ifas),"arquivo":str(SAIDA/"cbpf_ifa.json")},ensure_ascii=False,indent=2))

if __name__=="__main__": main()
