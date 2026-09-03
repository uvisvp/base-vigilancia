#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Diagnóstico passivo do painel público e-SISBI / SISBI-POA (MAPA)."""
from __future__ import annotations
import hashlib, json, re, ssl, sys
import urllib.parse, urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
SAIDA = BASE / "diagnosticos" / "mapa_sisbi"
PAINEL = "https://mapa-indicadores.agricultura.gov.br/publico/extensions/DSN_ESISBI_2/DSN_ESISBI_2.html"
UA = "Mozilla/5.0 (compatible; BaseVigilancia/1.0; +https://github.com/uvisvp/base-vigilancia)"
TERMOS = ("gestão dos produtos", "gestao dos produtos", "produto", "excel", "xlsx", "xls", "csv", "export", "download", "qlik", "esisbi", "sisbi", "sgsi")

def agora(): return datetime.now(timezone.utc).isoformat()
def sha256(data): return hashlib.sha256(data).hexdigest()
def salvar(nome, obj):
    SAIDA.mkdir(parents=True, exist_ok=True)
    (SAIDA / nome).write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")

def get(url, timeout=45):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout, context=ssl.create_default_context()) as r:
        return r.read(), {k.lower(): v for k, v in r.headers.items()}, int(getattr(r, "status", 200))

def texto(data, headers):
    ct = headers.get("content-type", "")
    m = re.search(r"charset=([^ ;]+)", ct, re.I)
    encs = ([m.group(1).strip('"\'')] if m else []) + ["utf-8-sig", "utf-8", "latin-1"]
    for enc in encs:
        try: return data.decode(enc)
        except Exception: pass
    return data.decode("utf-8", errors="replace")

def assets(html):
    out = set()
    for pattern in [r'<script[^>]+src=["\']([^"\']+)["\']', r'<link[^>]+href=["\']([^"\']+)["\']']:
        for v in re.findall(pattern, html, re.I):
            if not v.startswith(("data:", "javascript:", "#")):
                out.add(urllib.parse.urljoin(PAINEL, v))
    return sorted(out)

def urls(text, base):
    out = set(re.findall(r'https?://[^\s"\'<>\)]+', text, re.I))
    for v in re.findall(r'["\']([^"\']+\.(?:xlsx?|csv|json|js)(?:\?[^"\']*)?)["\']', text, re.I):
        out.add(urllib.parse.urljoin(base, v))
    return sorted(u.rstrip(".,;") for u in out)

def score(url):
    u = url.lower(); pesos = {".xlsx":10, ".xls":9, ".csv":8, "excel":7, "export":6, "download":5, "produto":4, "esisbi":3, "sisbi":3, "qlik":2}
    return sum(p for t, p in pesos.items() if t in u)

def trechos(t, limite=60):
    linhas = t.splitlines(); out = []
    for i, linha in enumerate(linhas):
        if any(x in linha.lower() for x in TERMOS):
            out.append({"linha_aprox": i + 1, "trecho": "\n".join(linhas[max(0, i-1):i+2])[:1800]})
            if len(out) >= limite: break
    return out

def main():
    SAIDA.mkdir(parents=True, exist_ok=True)
    resumo = {"status":"iniciado", "orgao":"Ministério da Agricultura e Pecuária — MAPA", "sistema":"e-SISBI / SISBI-POA", "painel":PAINEL, "executado_em":agora(), "observacao":"Somente recursos públicos; sem contorno de autenticação, CAPTCHA ou controles de acesso."}
    try: data, h, st = get(PAINEL)
    except Exception as e:
        resumo.update(status="erro", erro=f"{type(e).__name__}: {e}"); salvar("resumo.json", resumo); return 1
    html = texto(data, h); aa = assets(html)
    resumo.update(status="painel_acessivel", http_status=st, content_type=h.get("content-type"), last_modified=h.get("last-modified"), etag=h.get("etag"), tamanho_bytes=len(data), sha256_html=sha256(data), quantidade_assets=len(aa), contem_gestao_produtos=("gestão dos produtos" in html.lower() or "gestao dos produtos" in html.lower()), contem_produtos=("produtos" in html.lower()), contem_qlik=("qlik" in html.lower()))
    inv=[]; cand=[]; amostras=[{"origem":PAINEL, "trechos":trechos(html)}]
    for u in urls(html, PAINEL):
        if score(u): cand.append({"url":u, "origem":"html_principal", "pontuacao":score(u)})
    for u in aa:
        item={"url":u}; path=urllib.parse.urlparse(u).path.lower()
        if not path.endswith((".js", ".json", ".html", ".htm", ".css", ".txt")):
            item.update(inspecionado=False, motivo="asset não textual"); inv.append(item); continue
        try:
            d, hh, ss = get(u); item.update(inspecionado=True, http_status=ss, content_type=hh.get("content-type"), tamanho_bytes=len(d), sha256=sha256(d))
            if len(d) > 8_000_000:
                item.update(analisado=False, motivo="asset maior que 8 MB"); inv.append(item); continue
            tt=texto(d, hh); item.update(analisado=True, contem_qlik=("qlik" in tt.lower()), contem_export=("export" in tt.lower()), contem_excel=any(x in tt.lower() for x in ("excel", ".xlsx", ".xls")), contem_csv=(".csv" in tt.lower()), contem_produto=("produto" in tt.lower()))
            if any(item.get(k) for k in ("contem_qlik", "contem_export", "contem_excel", "contem_csv", "contem_produto")):
                amostras.append({"origem":u, "trechos":trechos(tt)})
            for x in urls(tt, u):
                if score(x): cand.append({"url":x, "origem":u, "pontuacao":score(x)})
        except Exception as e: item.update(inspecionado=False, erro=f"{type(e).__name__}: {e}")
        inv.append(item)
    dedup={}
    for c in cand:
        if c["url"] not in dedup or c["pontuacao"] > dedup[c["url"]]["pontuacao"]: dedup[c["url"]]=c
    finais=sorted(dedup.values(), key=lambda x:(-x["pontuacao"], x["url"]))
    resumo["assets_inspecionados"] = sum(1 for x in inv if x.get("inspecionado")); resumo["candidatos_exportacao"] = len(finais)
    if finais: resumo["status"]="diagnostico_concluido_com_candidatos"
    else:
        resumo["status"]="diagnostico_concluido_sem_url_estatica"
        resumo["conclusao_preliminar"]="Nenhuma URL estática de Excel/CSV foi identificada. A exportação pode ser dinâmica; nenhum contorno de sessão ou autenticação foi tentado."
    salvar("assets.json", inv); salvar("candidatos_exportacao.json", finais); salvar("amostra_textual.json", amostras); salvar("resumo.json", resumo)
    print(json.dumps(resumo, ensure_ascii=False, indent=2)); return 0

if __name__ == "__main__": raise SystemExit(main())
