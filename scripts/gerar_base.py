# Base Vigilância Sanitária
# Atualização automática de dados públicos da Anvisa

from pathlib import Path
from datetime import datetime, timezone
import json

BASE = Path(__file__).resolve().parent.parent
DADOS = BASE / "dados"

# Bases que serão integradas ao aplicativo.
# As URLs oficiais serão confirmadas e adicionadas individualmente.
FONTES = {
    "dispositivos": {
        "url": "",
        "descricao": "Dispositivos médicos / produtos para saúde",
    },
    "medicamentos": {
        "url": "",
        "descricao": "Medicamentos regularizados",
    },
    "cosmeticos": {
        "url": "",
        "descricao": "Cosméticos, produtos de higiene e perfumes",
    },
    "saneantes": {
        "url": "",
        "descricao": "Produtos saneantes",
    },
    "suplementos": {
        "url": "",
        "descricao": "Suplementos alimentares regularizados/notificados",
    },
    "alimentos": {
        "url": "",
        "descricao": "Alimentos sujeitos a regularização nacional",
    },
    "afe_ae": {
        "url": "",
        "descricao": "Empresas com AFE / AE",
    },
}

def criar_manifesto():
    DADOS.mkdir(parents=True, exist_ok=True)

    manifesto = {
        "projeto": "Base Vigilância Sanitária",
        "gerado_em": datetime.now(timezone.utc).isoformat(),
        "fontes": {},
    }

    for nome, config in FONTES.items():
        manifesto["fontes"][nome] = {
            "descricao": config["descricao"],
            "configurada": bool(config["url"]),
            "url": config["url"],
        }

    destino = DADOS / "manifest.json"

    with destino.open("w", encoding="utf-8") as arquivo:
        json.dump(
            manifesto,
            arquivo,
            ensure_ascii=False,
            indent=2
        )

    print(f"Manifesto criado: {destino}")


if __name__ == "__main__":
    criar_manifesto()
