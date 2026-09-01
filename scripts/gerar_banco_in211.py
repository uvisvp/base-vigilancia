#!/usr/bin/env python3
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timezone
import hashlib, json, re, unicodedata, requests
from bs4 import BeautifulSoup

BASE = Path(__file__).resolve().parent.parent
OUT = BASE / "dados" / "alimentos" / "in211"
OUT.mkdir(parents=True, exist_ok=True)

URL = ("https://anvisalegis.datalegis.net/action/ActionDatalegis.php?"
       "acao=abrirTextoAto&cod_menu=1686&cod_modulo=135&link=S&"
       "numeroAto=00000211&orgao=DC%2FANVISA%2FMS&seqAto=000&tipo=INM&valorAno=2023")

PARSER_VERSION = "1.0.0"
MIN_TOTAL = 15000
MAX_DROP = 0.20

def txt(x):
    return re.sub(r"\s+", " ", (x or "").strip())

def norm(x):
    s = unicodedata.normalize("NFD", str(x or ""))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()

def digits_ins(x):
    # Preserva sufixos como 331(i) / 160a(i) para exibição e gera chave estável.
    s = txt(x).lower().replace(" ", "")
    return re.sub(r"[^0-9a-z()]+", "", s)

def ins_prefix(x):
    n = re.sub(r"\D", "", x or "")
    return (n[:2] if len(n) >= 2 else (n or "sem"))

def cat_top(codigo):
    m = re.match(r"^(\d{2})", codigo or "")
    return m.group(1) if m else "sem"

def atomizar_celula(td):
    return txt(" ".join(td.stripped_strings))

def is_cat_line(s):
    return bool(re.match(r"^\d{2}(?:\.\d+)+\s+\S", txt(s)))

def parse_categoria(s):
    s = txt(s)
    m = re.match(r"^(\d{2}(?:\.\d+)+)\s+(.*)$", s)
    return (m.group(1), m.group(2)) if m else (None, None)

def detectar_anexo(s):
    u = norm(s)
    if "anexo iii" in u: return "III"
    if "anexo iv" in u: return "IV"
    return None

def achar_colunas(headers):
    m = {norm(h): i for i,h in enumerate(headers)}
    def pick(*terms):
        for term in terms:
            nt = norm(term)
            for k,i in m.items():
                if nt in k: return i
        return None
    return {
        "funcao": pick("função", "funcao"),
        "ins": pick("ins"),
        "nome": pick("aditivos", "aditivo", "coadjuvantes", "coadjuvante", "substância", "substancia"),
        "limite": pick("limite máximo", "limite maximo", "limite"),
        "nota": pick("nota", "condições de uso", "condicoes de uso", "observação", "observacao"),
    }

def parse_html(html):
    soup = BeautifulSoup(html, "html.parser")
    anexo = None
    categoria_codigo = categoria_nome = ""
    resultados = []
    seq = 0

    # Varre os elementos na ordem em que aparecem para carregar o contexto da categoria.
    for el in soup.find_all(["p","div","h1","h2","h3","h4","h5","table"]):
        if el.name != "table":
            s = txt(" ".join(el.stripped_strings))
            if not s: continue
            a = detectar_anexo(s)
            if a: anexo = a
            if is_cat_line(s):
                cc,cn = parse_categoria(s)
                if cc:
                    categoria_codigo, categoria_nome = cc, cn
            continue

        rows = el.find_all("tr")
        if not rows: continue
        matrix = [[atomizar_celula(td) for td in tr.find_all(["th","td"])] for tr in rows]
        matrix = [r for r in matrix if any(r)]
        if len(matrix) < 2: continue

        # Procura uma linha de cabeçalho plausível nas primeiras 3 linhas.
        hi = None
        cols = None
        for i,row in enumerate(matrix[:3]):
            nrow = " | ".join(norm(x) for x in row)
            if "ins" in nrow and ("limite" in nrow or "aditivo" in nrow or "coadjuvante" in nrow):
                hi = i; cols = achar_colunas(row); break
        if hi is None or cols is None: continue
        if cols["nome"] is None: continue

        last_funcao = ""
        for row in matrix[hi+1:]:
            def get(k):
                idx = cols.get(k)
                return txt(row[idx]) if idx is not None and idx < len(row) else ""
            funcao = get("funcao") or last_funcao
            if funcao: last_funcao = funcao
            ins = get("ins")
            nome = get("nome")
            limite = get("limite")
            nota = get("nota")
            if not nome: continue
            # Elimina repetições do próprio cabeçalho no corpo.
            if norm(nome) in {"aditivo","aditivos","coadjuvante","coadjuvantes","substancia"}: continue
            seq += 1
            qs = bool(re.search(r"quantum\s+satis|\bqs\b", limite, re.I))
            resultados.append({
                "id": seq,
                "anexo": anexo or "",
                "tipo": "aditivo" if (anexo == "III") else ("coadjuvante" if anexo == "IV" else ""),
                "categoria_codigo": categoria_codigo,
                "categoria": categoria_nome,
                "funcao": funcao,
                "ins": ins,
                "ins_chave": digits_ins(ins),
                "nome": nome,
                "limite": limite,
                "quantum_satis": qs,
                "nota": nota,
            })
    return resultados

def carregar_manifest_anterior():
    p = OUT / "manifest.json"
    if not p.exists(): return {}
    try: return json.loads(p.read_text(encoding="utf-8"))
    except Exception: return {}

def validar(rows, prev):
    if len(rows) < MIN_TOTAL:
        raise RuntimeError(f"Extração gerou apenas {len(rows)} autorizações; mínimo de segurança={MIN_TOTAL}.")
    iii = sum(1 for r in rows if r["anexo"] == "III")
    iv = sum(1 for r in rows if r["anexo"] == "IV")
    if not iii or not iv:
        raise RuntimeError(f"Anexos incompletos: III={iii}, IV={iv}")
    old = int(prev.get("total", 0) or 0)
    if old and len(rows) < old * (1-MAX_DROP):
        raise RuntimeError(f"Queda anormal: anterior={old}, novo={len(rows)}")
    return iii, iv

def dump(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix+".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, separators=(",",":")), encoding="utf-8")
    tmp.replace(path)

def gerar_indices(rows):
    by_ins = defaultdict(list)
    by_cat = defaultdict(list)
    nomes = {}
    funcoes = set()
    for r in rows:
        if r["ins_chave"]:
            by_ins[ins_prefix(r["ins_chave"])].append(r)
        by_cat[cat_top(r["categoria_codigo"])].append(r)
        chave_nome = norm(r["nome"])
        if chave_nome:
            item = nomes.setdefault(chave_nome, {"nome":r["nome"],"ins":set(),"tipo":set(),"anexos":set()})
            if r["ins"]: item["ins"].add(r["ins"])
            if r["tipo"]: item["tipo"].add(r["tipo"])
            if r["anexo"]: item["anexos"].add(r["anexo"])
        if r["funcao"]: funcoes.add(r["funcao"])

    for prefixo,items in by_ins.items():
        dump(OUT/"ins"/f"{prefixo}.json", items)
    for top,items in by_cat.items():
        dump(OUT/"categoria"/f"{top}.json", items)

    idx = []
    for chave,item in sorted(nomes.items()):
        idx.append({
            "k": chave,
            "nome": item["nome"],
            "ins": sorted(item["ins"]),
            "tipo": sorted(item["tipo"]),
            "anexos": sorted(item["anexos"]),
        })
    dump(OUT/"indice_nomes.json", idx)
    dump(OUT/"funcoes.json", sorted(funcoes))
    return len(by_ins), len(by_cat), len(idx), len(funcoes)

def main():
    headers = {"User-Agent":"Mozilla/5.0 base-vigilancia/IN211"}
    r = requests.get(URL, headers=headers, timeout=180)
    r.raise_for_status()
    r.encoding = r.apparent_encoding or "utf-8"
    raw = r.text
    rows = parse_html(raw)
    prev = carregar_manifest_anterior()
    iii,iv = validar(rows, prev)
    n_ins,n_cat,n_nomes,n_funcoes = gerar_indices(rows)

    sha = hashlib.sha256(raw.encode("utf-8","replace")).hexdigest()
    manifest = {
        "base":"IN Anvisa nº 211/2023 — Anexos III e IV",
        "parser_version":PARSER_VERSION,
        "gerado_em":datetime.now(timezone.utc).isoformat(),
        "fonte_url":URL,
        "fonte_last_modified":r.headers.get("Last-Modified"),
        "fonte_date":r.headers.get("Date"),
        "fonte_etag":r.headers.get("ETag"),
        "fonte_sha256":sha,
        "total":len(rows),
        "anexo_iii":iii,
        "anexo_iv":iv,
        "fragmentos_ins":n_ins,
        "fragmentos_categoria":n_cat,
        "nomes_unicos":n_nomes,
        "funcoes_unicas":n_funcoes,
        "regra_validacao":{"min_total":MIN_TOTAL,"max_drop":MAX_DROP},
        "campos":["anexo","tipo","categoria_codigo","categoria","funcao","ins","ins_chave","nome","limite","quantum_satis","nota"],
        "observacao":"Resultado automatizado a partir do texto consolidado oficial; falhas de extração abortam a publicação."
    }
    dump(OUT/"manifest.json", manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
