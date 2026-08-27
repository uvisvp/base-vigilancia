from pathlib import Path
from collections import defaultdict
from datetime import datetime, timezone
import json
import re
import shutil
import tempfile

BASE = Path(__file__).resolve().parent.parent
DADOS = BASE / "dados"
INDICES = DADOS / "indices"

BASES_PROCESSO = ("dispositivos", "medicamentos", "saneantes")
BASES_CNPJ = ("medicamentos", "saneantes")


def digits(value):
    return re.sub(r"\D", "", str(value or ""))


def process_shard(processo):
    numero = digits(processo)
    return numero[5:8] if len(numero) >= 8 else numero[:3]


def carregar_json(path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def gravar_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(
            data,
            f,
            ensure_ascii=False,
            separators=(",", ":")
        )


def contar_referencias_existentes(path):
    if not path.exists():
        return 0

    total = 0

    for arquivo in path.glob("*.json"):
        data = carregar_json(arquivo)

        if isinstance(data, dict):
            total += sum(
                len(v)
                for v in data.values()
                if isinstance(v, list)
            )

    return total


def validar_reducao(nome, novo, antigo):
    if novo < 1000:
        raise RuntimeError(
            f"Índice {nome} gerou apenas {novo} referências."
        )

    if antigo and novo < antigo * 0.90:
        queda = (1 - novo / antigo) * 100

        raise RuntimeError(
            f"Índice {nome} caiu {queda:.1f}% "
            f"({antigo} -> {novo}). "
            "Atualização cancelada para proteger "
            "a base publicada."
        )


def iterar_base(nome):
    pasta = DADOS / nome

    if not pasta.exists():
        raise RuntimeError(
            f"Base ausente: {pasta}"
        )

    arquivos = sorted(
        pasta.glob("*.json")
    )

    if not arquivos:
        raise RuntimeError(
            f"Base sem fragmentos: {pasta}"
        )

    for arquivo in arquivos:
        data = carregar_json(arquivo)

        if not isinstance(data, list):
            raise RuntimeError(
                f"Fragmento inválido: {arquivo}"
            )

        for item in data:
            if isinstance(item, dict):
                yield item


def cnpj_do_item(item, base):
    cnpj = digits(
        item.get("cnpj")
    )

    if len(cnpj) == 14:
        return cnpj

    if base == "medicamentos":
        # Na base de medicamentos o CNPJ
        # aparece no início do campo detentor.
        encontrado = re.match(
            r"\s*(\d{14})(?:\D|$)",
            str(item.get("detentor", ""))
        )

        if encontrado:
            return encontrado.group(1)

    return ""


def gerar_indices():
    processos = defaultdict(
        lambda: defaultdict(list)
    )

    cnpjs = defaultdict(
        lambda: defaultdict(list)
    )

    total_processo = 0
    total_cnpj = 0

    por_base_processo = defaultdict(int)
    por_base_cnpj = defaultdict(int)

    for base in BASES_PROCESSO:

        for item in iterar_base(base):

            registro = digits(
                item.get("registro")
            )

            processo = digits(
                item.get("processo")
            )

            # -------------------------
            # ÍNDICE POR PROCESSO
            # -------------------------

            if registro and processo:

                shard = process_shard(
                    processo
                )

                processos[
                    shard
                ][
                    processo
                ].append(
                    {
                        "b": base,
                        "r": registro
                    }
                )

                total_processo += 1

                por_base_processo[
                    base
                ] += 1

            # -------------------------
            # ÍNDICE POR CNPJ
            # -------------------------

            if (
                base in BASES_CNPJ
                and registro
            ):

                cnpj = cnpj_do_item(
                    item,
                    base
                )

                if len(cnpj) == 14:

                    produto = dict(
                        item
                    )

                    produto[
                        "b"
                    ] = base

                    produto[
                        "cnpj"
                    ] = cnpj

                    cnpjs[
                        cnpj[:3]
                    ][
                        cnpj
                    ].append(
                        produto
                    )

                    total_cnpj += 1

                    por_base_cnpj[
                        base
                    ] += 1

    # -------------------------
    # PROTEÇÃO CONTRA QUEDA
    # -------------------------

    antigo_processo = (
        contar_referencias_existentes(
            INDICES / "processos"
        )
    )

    antigo_cnpj = (
        contar_referencias_existentes(
            INDICES / "cnpj_produtos"
        )
    )

    validar_reducao(
        "processos",
        total_processo,
        antigo_processo
    )

    validar_reducao(
        "CNPJ de produtos",
        total_cnpj,
        antigo_cnpj
    )

    # -------------------------
    # GRAVAÇÃO TEMPORÁRIA
    # -------------------------

    temporario = Path(
        tempfile.mkdtemp(
            prefix="indices_",
            dir=DADOS
        )
    )

    try:

        pasta_processos = (
            temporario / "processos"
        )

        pasta_cnpj = (
            temporario / "cnpj_produtos"
        )

        for shard, mapa in (
            processos.items()
        ):

            gravar_json(
                pasta_processos
                / f"{shard}.json",
                dict(mapa)
            )

        for shard, mapa in (
            cnpjs.items()
        ):

            gravar_json(
                pasta_cnpj
                / f"{shard}.json",
                dict(mapa)
            )

        if INDICES.exists():
            shutil.rmtree(
                INDICES
            )

        temporario.rename(
            INDICES
        )

    except Exception:

        shutil.rmtree(
            temporario,
            ignore_errors=True
        )

        raise

    # -------------------------
    # ATUALIZA MANIFEST
    # -------------------------

    manifesto_path = (
        DADOS / "manifest.json"
    )

    if manifesto_path.exists():
        manifesto = carregar_json(
            manifesto_path
        )
    else:
        manifesto = {}

    manifesto[
        "indices"
    ] = {

        "status": "ok",

        "gerado_em":
            datetime.now(
                timezone.utc
            ).isoformat(),

        "processos": {

            "referencias":
                total_processo,

            "fragmentos":
                len(processos),

            "por_base":
                dict(
                    sorted(
                        por_base_processo.items()
                    )
                ),

            "shard":
                "digitos 6 a 8 do processo"
        },

        "cnpj_produtos": {

            "referencias":
                total_cnpj,

            "fragmentos":
                len(cnpjs),

            "por_base":
                dict(
                    sorted(
                        por_base_cnpj.items()
                    )
                ),

            "bases":
                list(BASES_CNPJ),

            "observacao":
                (
                    "Dispositivos não entram: "
                    "a fonte atual não fornece "
                    "CNPJ confiável."
                )
        }
    }

    gravar_json(
        manifesto_path,
        manifesto
    )

    print(
        "Índice de processos:",
        total_processo,
        "referências em",
        len(processos),
        "fragmentos"
    )

    print(
        "Índice de CNPJ:",
        total_cnpj,
        "referências em",
        len(cnpjs),
        "fragmentos"
    )

    print(
        "Índices gerados com sucesso."
    )


if __name__ == "__main__":
    gerar_indices()
