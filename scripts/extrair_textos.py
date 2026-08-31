#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Extrator de texto de arquivos de legislacao.

Le arquivos PDF e HTML de fontes/ e grava o texto integral em textos/.

Principios:
  - extrai o texto integral, preservando acentuacao e a ordem original;
  - nao resume, nao interpreta, nao reescreve, nao reordena;
  - remove apenas o que claramente nao e conteudo (script, style, nav, menu,
    header, footer, aside, form, botao, iframe);
  - PDF sem camada de texto utilizavel e registrado como FALHA, nunca inventado;
  - gera relatorio com o resultado de cada arquivo.

Uso:
    python scripts/extrair_textos.py
    python scripts/extrair_textos.py --entrada fontes --saida textos
    python scripts/extrair_textos.py --autoteste
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import traceback
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
ENTRADA_PADRAO = BASE / "fontes"
SAIDA_PADRAO = BASE / "textos"
RELATORIO_PADRAO = BASE / "textos" / "relatorio-extracao"

EXT_HTML = {".html", ".htm", ".xhtml"}
EXT_PDF = {".pdf"}

# Um PDF cuja extracao renda menos que isto por pagina provavelmente e digitalizado
# (imagem sem camada de texto). Nesse caso registramos falha em vez de entregar lixo.
MIN_CHARS_POR_PAGINA = 40
MIN_CHARS_TOTAL = 200

TAGS_FORA = [
    "script", "style", "noscript", "template",
    "nav", "header", "footer", "aside", "form",
    "button", "iframe", "svg", "canvas", "map", "object", "embed",
]
# Elementos de navegacao identificados por atributo, nao por tag.
PADRAO_NAV = re.compile(
    r"(^|[\s_-])(nav|navbar|menu|breadcrumb|sidebar|side-bar|rodape|footer|cabecalho|"
    r"header|banner|cookie|skip-link|pagination|paginacao|compartilh|social|"
    r"barra-governo|barra-brasil|acessibilidade-barra|voltar-ao-topo)([\s_-]|$)",
    re.I,
)


# ─────────────────────────────── utilidades ───────────────────────────────
def normalizar(texto: str) -> str:
    """Normaliza espacos e quebras SEM alterar acentos, pontuacao ou ordem."""
    # NFC mantem os acentos compostos corretamente em UTF-8.
    texto = unicodedata.normalize("NFC", texto)
    texto = texto.replace("\u00a0", " ").replace("\u200b", "")
    texto = texto.replace("\r\n", "\n").replace("\r", "\n")
    linhas = [re.sub(r"[ \t]+", " ", ln).strip() for ln in texto.split("\n")]
    saida, vazias = [], 0
    for ln in linhas:
        if ln:
            saida.append(ln)
            vazias = 0
        else:
            vazias += 1
            if vazias == 1:
                saida.append("")
    return "\n".join(saida).strip()


def id_norma(arquivo: Path, entrada: Path) -> str:
    """fontes/<norma_id>/x.html -> <norma_id>; fontes/x.html -> x"""
    rel = arquivo.relative_to(entrada)
    return rel.parts[0] if len(rel.parts) > 1 else rel.stem


def nome_saida(arquivo: Path, entrada: Path) -> str:
    """Espelha o caminho relativo, trocando '/' por '--'. Nomes sempre unicos.

    fontes/lei-5991-1973/texto_bruto.html -> lei-5991-1973--texto_bruto.txt
    fontes/lei-5991-1973.html             -> lei-5991-1973.txt
    """
    rel = arquivo.relative_to(entrada).with_suffix("")
    return "--".join(rel.parts) + ".txt"


# ─────────────────────────────── HTML ───────────────────────────────
def extrair_html(caminho: Path) -> tuple[str, dict]:
    from bs4 import BeautifulSoup

    bruto = caminho.read_bytes()
    sopa = None
    codificacao = None
    for cod in ("utf-8", "windows-1252", "iso-8859-1"):
        try:
            sopa = BeautifulSoup(bruto.decode(cod), "html.parser")
            codificacao = cod
            break
        except UnicodeDecodeError:
            continue
    if sopa is None:
        sopa = BeautifulSoup(bruto.decode("utf-8", errors="replace"), "html.parser")
        codificacao = "utf-8 (com substituicoes)"

    removidos = 0
    for tag in sopa.find_all(TAGS_FORA):
        tag.decompose()
        removidos += 1
    for tag in sopa.find_all(attrs={"role": re.compile(
            r"^(navigation|banner|contentinfo|search|menu|menubar|complementary)$", re.I)}):
        tag.decompose()
        removidos += 1
    for tag in sopa.find_all(True):
        # Ao decompor um elemento pai, o BeautifulSoup invalida os atributos
        # dos filhos que ja estavam na lista de iteracao. Ignore esses filhos
        # para que blocos de navegacao aninhados nao interrompam a extracao.
        if getattr(tag, "attrs", None) is None:
            continue
        alvo = " ".join(filter(None, [
            " ".join(tag.get("class", [])) if isinstance(tag.get("class"), list) else (tag.get("class") or ""),
            tag.get("id") or "",
        ]))
        if alvo and PADRAO_NAV.search(alvo):
            tag.decompose()
            removidos += 1

    # separator="\n" preserva a ordem do documento e a separacao entre blocos.
    texto = normalizar(sopa.get_text(separator="\n"))
    return texto, {"codificacao": codificacao, "elementos_removidos": removidos}


# ─────────────────────────────── PDF ───────────────────────────────
def extrair_pdf(caminho: Path) -> tuple[str, dict]:
    from pypdf import PdfReader

    leitor = PdfReader(str(caminho))
    if getattr(leitor, "is_encrypted", False):
        try:
            leitor.decrypt("")
        except Exception:
            raise RuntimeError("PDF protegido por senha")

    partes, vazias = [], 0
    for i, pagina in enumerate(leitor.pages, 1):
        try:
            t = pagina.extract_text() or ""
        except Exception as e:
            t = ""
            print(f"      aviso: falha na pagina {i}: {e}", file=sys.stderr)
        if not t.strip():
            vazias += 1
        partes.append(t)

    texto = normalizar("\n".join(partes))
    n_pag = len(leitor.pages)
    meta = {"paginas": n_pag, "paginas_sem_texto": vazias,
            "chars_por_pagina": round(len(texto) / n_pag, 1) if n_pag else 0}

    if len(texto) < MIN_CHARS_TOTAL or (n_pag and len(texto) / n_pag < MIN_CHARS_POR_PAGINA):
        raise RuntimeError(
            f"PDF sem camada de texto utilizavel "
            f"({len(texto)} caracteres em {n_pag} pagina(s); "
            f"{vazias} pagina(s) sem texto). Provavel PDF digitalizado — requer OCR. "
            f"Nenhum texto foi gravado."
        )
    return texto, meta


# ─────────────────────────────── varredura ───────────────────────────────
def coletar(entrada: Path) -> list[Path]:
    exts = EXT_HTML | EXT_PDF
    return sorted(p for p in entrada.rglob("*")
                  if p.is_file() and p.suffix.lower() in exts)


def processar(entrada: Path, saida: Path, relatorio: Path) -> dict:
    entrada, saida, relatorio = Path(entrada), Path(saida), Path(relatorio)
    inicio = datetime.now(timezone.utc)

    if not entrada.exists():
        print(f"Pasta de entrada nao encontrada: {entrada}")
        print("Crie a pasta e coloque nela os arquivos .pdf, .html ou .htm.")
        entrada.mkdir(parents=True, exist_ok=True)

    arquivos = coletar(entrada)
    print(f"Entrada : {entrada}")
    print(f"Saida   : {saida}")
    print(f"Arquivos encontrados: {len(arquivos)}\n")

    saida.mkdir(parents=True, exist_ok=True)
    relatorio.parent.mkdir(parents=True, exist_ok=True)

    sucesso, falha = [], []
    for arq in arquivos:
        rel = arq.relative_to(entrada).as_posix()
        nid = id_norma(arq, entrada)
        ext = arq.suffix.lower()
        print(f"  {rel}")
        try:
            if ext in EXT_PDF:
                texto, meta = extrair_pdf(arq)
                origem = "pdf"
            else:
                texto, meta = extrair_html(arq)
                origem = "html"

            if not texto.strip():
                raise RuntimeError("extracao resultou em texto vazio")

            destino = saida / nome_saida(arq, entrada)
            destino.write_text(texto, encoding="utf-8")
            reg = {"arquivo": rel, "norma_id": nid, "origem": origem,
                   "saida": destino.relative_to(saida).as_posix(),
                   "caracteres": len(texto), "linhas": texto.count("\n") + 1,
                   "bytes_entrada": arq.stat().st_size, **meta}
            sucesso.append(reg)
            print(f"      OK  -> {destino.name}  ({len(texto):,} caracteres)".replace(",", "."))
        except Exception as e:
            reg = {"arquivo": rel, "norma_id": nid, "origem": ext.lstrip("."),
                   "erro": str(e), "tipo_erro": type(e).__name__,
                   "bytes_entrada": arq.stat().st_size if arq.exists() else 0}
            falha.append(reg)
            print(f"      FALHA: {e}")
            if not isinstance(e, RuntimeError):
                traceback.print_exc(file=sys.stderr)

    fim = datetime.now(timezone.utc)
    res = {
        "gerado_em": fim.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "duracao_s": round((fim - inicio).total_seconds(), 2),
        "entrada": str(entrada.relative_to(BASE)) if entrada.is_relative_to(BASE) else str(entrada),
        "total": len(arquivos), "sucesso": len(sucesso), "falha": len(falha),
        "extraidos": sucesso, "falhas": falha,
    }

    relatorio.with_suffix(".json").write_text(
        json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")

    linhas = [
        "# Relatorio de extracao de textos", "",
        f"- Gerado em: {res['gerado_em']}",
        f"- Duracao: {res['duracao_s']} s",
        f"- Arquivos encontrados: {res['total']}",
        f"- Extraidos com sucesso: {res['sucesso']}",
        f"- Falharam: {res['falha']}", "",
    ]
    if sucesso:
        linhas += ["## Extraidos com sucesso", "",
                   "| Arquivo | Origem | Saida | Caracteres |",
                   "|---|---|---|---|"]
        linhas += [f"| {r['arquivo']} | {r['origem']} | {r['saida']} | {r['caracteres']} |"
                   for r in sucesso]
        linhas.append("")
    if falha:
        linhas += ["## Falharam", "",
                   "| Arquivo | Origem | Motivo |", "|---|---|---|"]
        linhas += [f"| {r['arquivo']} | {r['origem']} | {r['erro']} |" for r in falha]
        linhas.append("")
    if not arquivos:
        linhas += ["Nenhum arquivo .pdf, .html ou .htm foi encontrado na pasta de entrada.", ""]
    relatorio.with_suffix(".md").write_text("\n".join(linhas), encoding="utf-8")

    print(f"\nResumo: {res['sucesso']} extraido(s), {res['falha']} falha(s), "
          f"de {res['total']} arquivo(s).")
    print(f"Relatorio: {relatorio.with_suffix('.md')}")
    return res


# ─────────────────────────────── autoteste ───────────────────────────────
def autoteste() -> int:
    """Gera arquivos sinteticos e verifica o extrator. Nao usa rede."""
    import tempfile

    print("== AUTOTESTE ==\n")
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        ent, sai = tmp / "fontes", tmp / "textos"

        d = ent / "norma-exemplo-1-2000"
        d.mkdir(parents=True)
        (d / "texto_bruto.html").write_text(
            "<html><head><title>t</title><style>a{}</style>"
            "<script>var x=1;</script></head><body>"
            "<nav>Menu Principal</nav><div class='breadcrumb'>"
            "<span>Inicio</span> &gt; <a href='/leis'>Leis</a></div>"
            "<h1>LEI N\u00ba 1, DE 1\u00ba DE JANEIRO DE 2000.</h1>"
            "<p>Art. 1\u00ba Fica institu\u00eddo o regime de fiscaliza\u00e7\u00e3o sanit\u00e1ria.</p>"
            "<p>Par\u00e1grafo \u00fanico. A a\u00e7\u00e3o \u00e9 permanente.</p>"
            "<footer>Rodap\u00e9 do site</footer></body></html>", encoding="utf-8")

        d2 = ent / "norma-sem-texto-2-2001"
        d2.mkdir(parents=True)
        d2.joinpath("digitalizada.pdf").write_bytes(_pdf_minimo(com_texto=False))

        d3 = ent / "norma-pdf-3-2002"
        d3.mkdir(parents=True)
        d3.joinpath("texto.pdf").write_bytes(_pdf_minimo(com_texto=True))

        res = processar(ent, sai, tmp / "rel")

        falhou = []
        txt = (sai / "norma-exemplo-1-2000--texto_bruto.txt").read_text(encoding="utf-8")
        for termo in ("fiscaliza\u00e7\u00e3o sanit\u00e1ria", "institu\u00eddo",
                      "Par\u00e1grafo \u00fanico", "LEI N\u00ba 1"):
            if termo not in txt:
                falhou.append(f"HTML: acentuacao/conteudo perdido: {termo!r}")
        for lixo in ("Menu Principal", "var x=1", "Rodap\u00e9 do site", "Inicio > Leis"):
            if lixo in txt:
                falhou.append(f"HTML: elemento de navegacao nao removido: {lixo!r}")
        if txt.index("Art. 1") > txt.index("Par\u00e1grafo \u00fanico"):
            falhou.append("HTML: ordem original do conteudo nao preservada")

        ids_falha = {f["norma_id"] for f in res["falhas"]}
        if "norma-sem-texto-2-2001" not in ids_falha:
            falhou.append("PDF sem camada de texto deveria ter sido registrado como falha")
        if (sai / "norma-sem-texto-2-2001--digitalizada.txt").exists():
            falhou.append("PDF sem texto nao pode gerar arquivo .txt")

        print()
        if falhou:
            for f in falhou:
                print(f"  FALHOU: {f}")
            return 1
        print("  Todas as verificacoes passaram.")
        return 0


def _pdf_minimo(com_texto: bool) -> bytes:
    """PDF valido minimo, com ou sem camada de texto. Sem dependencias."""
    if com_texto:
        conteudo = (b"BT /F1 12 Tf 50 700 Td (Art. 1 Texto de teste do extrator.) Tj ET\n"
                    b"BT /F1 12 Tf 50 680 Td (Paragrafo unico. Segunda linha do teste.) Tj ET\n"
                    b"BT /F1 12 Tf 50 660 Td (Terceira linha para passar do limite minimo de caracteres.) Tj ET\n"
                    b"BT /F1 12 Tf 50 640 Td (Quarta linha do documento de teste para o extrator de normas.) Tj ET\n"
                    b"BT /F1 12 Tf 50 620 Td (Quinta linha do documento de teste para o extrator de normas.) Tj ET\n")
    else:
        conteudo = b"0.5 0.5 0.5 rg 50 50 500 700 re f\n"

    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(conteudo)).encode() + b" >>\nstream\n" + conteudo + b"endstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    saida = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, o in enumerate(objs, 1):
        offsets.append(len(saida))
        saida += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    inicio_xref = len(saida)
    saida += f"xref\n0 {len(objs) + 1}\n".encode() + b"0000000000 65535 f \n"
    for off in offsets:
        saida += f"{off:010d} 00000 n \n".encode()
    saida += (f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n"
              f"{inicio_xref}\n%%EOF\n").encode()
    return bytes(saida)


def main() -> int:
    ap = argparse.ArgumentParser(description="Extrai texto integral de PDF e HTML de legislacao.")
    ap.add_argument("--entrada", default=str(ENTRADA_PADRAO))
    ap.add_argument("--saida", default=str(SAIDA_PADRAO))
    ap.add_argument("--relatorio", default=str(RELATORIO_PADRAO))
    ap.add_argument("--autoteste", action="store_true",
                    help="roda verificacao interna com arquivos sinteticos, sem rede")
    ap.add_argument("--falhar-se-houver-erro", action="store_true",
                    help="encerra com codigo 1 se algum arquivo falhar")
    a = ap.parse_args()

    if a.autoteste:
        return autoteste()

    res = processar(Path(a.entrada), Path(a.saida), Path(a.relatorio))
    if a.falhar_se_houver_erro and res["falha"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
