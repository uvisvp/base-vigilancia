from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.gerar_banco_in211 import parse_html
html = """
<h2>ANEXO III</h2>
<p>01.1.1 Leite fluido</p>
<table>
<tr><th>Função</th><th>INS</th><th>Aditivos</th><th>Limite máximo (mg/kg ou mg/L)</th><th>Nota</th></tr>
<tr><td>Estabilizante</td><td>331(i)</td><td>di-hidrogenocitrato de sódio</td><td>1000</td><td>Somente para leite UHT.</td></tr>
<tr><td></td><td>331(ii)</td><td>Citrato dissódico monohidrogênio</td><td>1000</td><td>Somente para leite UHT.</td></tr>
</table>
<h2>ANEXO IV</h2>
<p>14.1.1 Exemplo</p>
<table>
<tr><th>Função</th><th>INS</th><th>Coadjuvantes</th><th>Limite máximo</th><th>Nota</th></tr>
<tr><td>Agente de filtração</td><td>558</td><td>Bentonita</td><td>quantum satis</td><td>Condição exemplo.</td></tr>
</table>
"""
r=parse_html(html)
assert len(r)==3, r
assert r[0]["categoria_codigo"]=="01.1.1"
assert r[1]["funcao"]=="Estabilizante"
assert r[2]["anexo"]=="IV" and r[2]["quantum_satis"] is True
print("OK - parser fixture:", len(r), "linhas")
