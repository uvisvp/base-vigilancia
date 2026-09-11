from pathlib import Path
import csv, re, ssl, urllib.request, tempfile

FONTES={
 'dispositivos':'https://dados.anvisa.gov.br/dados/TA_PRODUTO_SAUDE_SITE.csv',
 'medicamentos':'https://dados.anvisa.gov.br/dados/DADOS_ABERTOS_MEDICAMENTOS.csv',
 'saneantes':'https://dados.anvisa.gov.br/dados/CONSULTAS/PRODUTOS/TA_CONSULTA_SANEANTES.CSV',
 'cosmeticos':'https://dados.anvisa.gov.br/dados/CONSULTAS/PRODUTOS/TA_CONSULTA_COSMETICOS.CSV',
 'alimentos':'https://dados.anvisa.gov.br/dados/CONSULTAS/PRODUTOS/TA_CONSULTA_ALIMENTOS.CSV',
}
ALVO='25351239002201018'

def norm(s): return re.sub(r'[^A-Z0-9]','',str(s or '').upper())
def nums(s): return re.sub(r'\D','',str(s or ''))
def achar(cols,*nomes):
 m={norm(c):c for c in cols if c}
 for n in nomes:
  if norm(n) in m:return m[norm(n)]
 return None

def baixar(url):
 p=Path(tempfile.mkstemp(suffix='.csv')[1])
 req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0 base-vigilancia-diagnostico'})
 ctx=ssl._create_unverified_context()
 with urllib.request.urlopen(req,timeout=240,context=ctx) as r,p.open('wb') as f:
  while True:
   b=r.read(1024*1024)
   if not b:break
   f.write(b)
 return p

def cfg(p):
 b=p.read_bytes()[:200000]
 enc='latin-1'
 for e in ('utf-8-sig','utf-8','latin-1','cp1252'):
  try:b.decode(e);enc=e;break
  except UnicodeDecodeError:pass
 s=b.decode(enc,errors='replace')
 try:d=csv.Sniffer().sniff(s,delimiters=';,|\t').delimiter
 except csv.Error:d=';'
 return enc,d

for nome,url in FONTES.items():
 print('\n===',nome,'===')
 p=baixar(url)
 try:
  enc,d=cfg(p)
  with p.open(encoding=enc,errors='replace',newline='') as f:
   rd=csv.DictReader(f,delimiter=d); cols=rd.fieldnames or []
   cp=achar(cols,'NU_PROCESSO','NUMERO_PROCESSO','PROCESSO_ANVISA','PROCESSO')
   cr=achar(cols,'NU_REGISTRO_PRODUTO','NUMERO_REGISTRO_PRODUTO','NUMERO_REGISTRO_CADASTRO','NUMERO_REGISTRO','NU_REGISTRO','REGISTRO_PRODUTO','REGISTRO')
   prod=achar(cols,'NO_PRODUTO','NOME_PRODUTO','PRODUTO','NOME_COMERCIAL')
   print('processo=',cp,'registro=',cr,'produto=',prod)
   total=comproc=semreg=0; alvo=[]
   for row in rd:
    total+=1; proc=nums(row.get(cp,'')) if cp else ''; reg=nums(row.get(cr,'')) if cr else ''
    if proc:
     comproc+=1
     if not reg:semreg+=1
     if nome=='saneantes' and proc==ALVO:alvo.append({k:row.get(k,'') for k in cols})
   print('linhas=',total,'com_processo=',comproc,'processo_sem_registro=',semreg)
   if nome=='saneantes':
    print('ALVO_ENCONTRADO=',len(alvo))
    for x in alvo[:10]:print('ALVO_ROW=',x)
 finally:p.unlink(missing_ok=True)
