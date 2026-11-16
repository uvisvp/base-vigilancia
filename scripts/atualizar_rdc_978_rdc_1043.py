#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Incorpora à RDC Anvisa nº 978/2025 (EAC) as alterações da RDC Anvisa nº 1.043, de 01/10/2026
(DOU de 05/10/2026, republicada em 15/10/2026): art. 5º, XLIV, XLV e XLV-A; art. 25 (caput; parágrafo
único revogado); art. 43; art. 44, parágrafo único; art. 50 e parágrafo único; art. 51, §§ 1º a 3º;
art. 53, parágrafo único; art. 122, §§ 4º a 6º.

A redação nova de cada dispositivo é lida do texto consolidado da RDC 978 no AnvisaLegis e conferida
com o texto da própria RDC 1.043 no AnvisaLegis: só entra o que as duas páginas trazem igual. O texto
publicado (textos/RDC 978-2025--oficial.txt) é alterado só nesses dispositivos, para os identificadores
dos demais não mudarem; depois o estruturador do v12 regrava a norma.

Uso: python3 scripts/atualizar_rdc_978_rdc_1043.py
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE / "scripts"))
from estruturar_legislacao import processar  # noqa: E402

TXT = BASE / "textos" / "RDC 978-2025--oficial.txt"
META = TXT.with_suffix(".meta.json")
LEGIS = "https://anvisalegis.datalegis.net/action/ActionDatalegis.php?acao=abrirTextoAto&link=S&orgao=RDC%2FDC%2FANVISA%2FMS&seqAto=000&tipo=RDC&cod_modulo=310"
URL_978 = LEGIS + "&cod_menu=8542&numeroAto=00000978&valorAno=2025"
URL_1043 = LEGIS + "&cod_menu=9428&numeroAto=00001043&valorAno=2026"
NOTA = "Resolução da Diretoria Colegiada Anvisa nº 1.043, de 01/10/2026, republicada no DOU nº 195, de 15/10/2026"
HEAD = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/128 Safari/537.36",
        "Accept": "text/html,*/*;q=0.8", "Accept-Language": "pt-BR,pt;q=0.9", "Accept-Encoding": "identity", "Connection": "close"}


def baixar(url: str) -> bytes:
    erro = None
    for i in range(4):
        try:
            r = requests.get(url, headers=HEAD, timeout=(20, 120))
            r.raise_for_status()
            if len(r.content) < 500:
                raise RuntimeError("resposta curta")
            return r.content
        except Exception as exc:  # noqa: BLE001
            erro = exc
            time.sleep(min(2 ** i, 8))
    raise RuntimeError(f"Falha ao baixar {url}: {erro}")


def linhas(html: bytes) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    for x in soup(["script", "style", "noscript", "nav", "footer"]):
        x.decompose()
    return [re.sub(r"\s+", " ", ln).strip() for ln in soup.get_text("\n").splitlines() if ln.strip()]


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("“", '"').replace("”", '"')).strip().casefold()


def apos(ls: list[str], ancora: str, prefixo: str, ate: str | None = None) -> int:
    """índice da primeira linha que começa com `prefixo` depois da linha que começa com `ancora` (antes de `ate`)"""
    i = next(k for k, ln in enumerate(ls) if ln.startswith(ancora))
    for k in range(i if prefixo == ancora else i + 1, len(ls)):
        if ate and k > i and ls[k].startswith(ate):
            break
        if ls[k].startswith(prefixo):
            return k
    raise RuntimeError(f"{prefixo!r} não encontrado depois de {ancora!r}")


# (âncora, prefixo, fim do trecho, operação) — operação: troca | insere_depois:<prefixo da linha anterior>
ALVOS = [
    ("Art. 5º", "XLIV - ", "Art. 6º", "troca"),
    ("Art. 5º", "XLV - ", "Art. 6º", "troca"),
    ("Art. 5º", "XLV-A - ", "Art. 6º", "insere_depois:XLV - "),
    ("Art. 25.", "Art. 25.", None, "troca"),
    ("Art. 43.", "Art. 43.", None, "troca"),
    ("Art. 44.", "Parágrafo único.", "Art. 45.", "troca"),
    ("Art. 50.", "Art. 50.", None, "troca"),
    ("Art. 50.", "Parágrafo único.", "Art. 51.", "troca"),
    ("Art. 51.", "§ 1º", "Art. 52.", "troca"),
    ("Art. 51.", "§ 2º", "Art. 52.", "troca"),
    ("Art. 51.", "§ 3º", "Art. 52.", "troca"),
    ("Art. 53.", "Parágrafo único.", "Art. 54.", "troca"),
    ("Art. 122.", "§ 4º", "Art. 123.", "insere_depois:§ 3º"),
    ("Art. 122.", "§ 5º", "Art. 123.", "insere_depois:§ 4º"),
    ("Art. 122.", "§ 6º", "Art. 123.", "insere_depois:§ 5º"),
]
INCISOS_122 = ["I - ", "II - ", "III - "]


def main() -> int:
    b978, b1043 = baixar(URL_978), baixar(URL_1043)
    cons, alt = linhas(b978), linhas(b1043)
    alt_n = norm(" ".join(alt))
    if "1.043" not in " ".join(alt) or "978" not in " ".join(alt):
        raise RuntimeError("página da RDC 1.043 não reconhecida")
    txt = TXT.read_text(encoding="utf-8").splitlines()
    feitos = []

    def confere(novo: str, rot: str):
        corpo = re.sub(r"^(Art\. \d+\.|Parágrafo único\.|§ \dº|[IVXL]+(?:-A)? -)\s*", "", novo)
        if norm(corpo) not in alt_n:
            raise RuntimeError(f"{rot}: redação do consolidado não confere com a RDC 1.043: {novo[:90]}")

    for ancora, pref, ate, op in ALVOS:
        novo = cons[apos(cons, ancora, pref, ate)]
        confere(novo, f"{ancora} {pref}")
        if op == "troca":
            k = apos(txt, ancora, pref, ate)
            if txt[k] != novo:
                txt[k] = novo
                feitos.append(f"{ancora} {pref}".strip())
        else:
            try:
                apos(txt, ancora, pref, ate)  # já inserido
            except (RuntimeError, StopIteration):
                k = apos(txt, ancora, op.split(":", 1)[1], ate)
                txt.insert(k + 1, novo)
                feitos.append(f"{ancora} {pref} (incluído)")
    # incisos do § 6º do art. 122
    k6c, k6 = apos(cons, "Art. 122.", "§ 6º", "Art. 123."), apos(txt, "Art. 122.", "§ 6º", "Art. 123.")
    fim = next(k for k in range(k6c, len(cons)) if cons[k].startswith("Art. 123."))
    novos = []
    for p in INCISOS_122:
        ln = next(cons[k] for k in range(k6c + 1, fim) if cons[k].startswith(p))
        confere(ln, "Art. 122, § 6º, " + p)
        novos.append(ln)
    if txt[k6 + 1:k6 + 1 + len(novos)] != novos:
        if txt[k6 + 1].startswith("I - "):
            raise RuntimeError("incisos do § 6º do art. 122 diferentes dos esperados")
        txt[k6 + 1:k6 + 1] = novos
        feitos.append("Art. 122, § 6º, I a III (incluídos)")
    # parágrafo único do art. 25: revogado (o consolidado traz só a nota)
    k25 = apos(txt, "Art. 25.", "Parágrafo único.", "Art. 26.")
    if "revogado o parágrafo único do art. 25" not in alt_n:
        raise RuntimeError("revogação do parágrafo único do art. 25 não encontrada na RDC 1.043")
    rev = f"Parágrafo único. (Revogado pela {NOTA})"
    if txt[k25] != rev:
        txt[k25] = rev
        feitos.append("Art. 25, parágrafo único (revogado)")

    if not feitos:
        print("RDC 978/2025 já está com as alterações da RDC 1.043/2026.")
        return 0
    texto = "\n".join(txt)
    # o arquivo publicado usa CRLF e termina com quebra de linha: mantém, para o diff mostrar só o que mudou
    crlf = b"\r\n" in TXT.read_bytes()
    with TXT.open("w", encoding="utf-8", newline="\r\n" if crlf else "\n") as f:
        f.write(texto + "\n")
    meta = json.loads(META.read_text(encoding="utf-8"))
    agora = datetime.now(timezone.utc).isoformat()
    notas = meta.get("alteracoes_encontradas", [])
    for n in (f"(Redação dada pela {NOTA})", f"(Incluído pela {NOTA})", f"(Revogado pela {NOTA})"):
        if n not in notas:
            notas.append(n)
    meta.update(consultado_em=agora, data_processamento=agora, alteracoes_encontradas=notas,
                sha256_fonte=hashlib.sha256(b978).hexdigest(), sha256_texto=hashlib.sha256(texto.strip().encode("utf-8")).hexdigest(),
                fonte_alteracao=URL_1043,
                nota_fonte_texto="Texto consolidado do AnvisaLegis; dispositivos alterados pela RDC 1.043/2026 conferidos com o texto da própria RDC 1.043 no AnvisaLegis.")
    META.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    processar()
    print("RDC 978/2025 atualizada:", "; ".join(feitos))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
