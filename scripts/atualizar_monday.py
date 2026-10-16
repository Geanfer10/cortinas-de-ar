"""
Busca o quadro "Cortinas de Ar – Limpeza" no Monday e grava:
  - data/latest.json    -> situação atual de cada cortina
  - data/historico.json -> registro das limpezas detectadas + foto diária da conformidade
                           (alimenta os gráficos executivos do painel)
  - data/fotos/         -> fotos de Antes e Depois anexadas no Monday (cópia reduzida em JPG).
                           As fotos ficam fixas: nunca são apagadas daqui. Se a célula do Monday
                           for limpa, o painel continua mostrando a última foto; quando uma foto
                           nova é anexada, ela passa a ser a exibida e a anterior fica no histórico.
Roda no GitHub Actions. O token vem do secret MONDAY_API_TOKEN (nunca é impresso no log).
Pillow (+ pillow-heif para fotos de iPhone) é opcional: se estiver instalado, as fotos são
reduzidas para JPG de até 1600 px; sem ele, o arquivo é salvo como veio.
"""
import json
import os
import sys
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

BOARD_ID = 18435679675
API_URL = "https://api.monday.com/v2"
PERIODICIDADE_PADRAO = 60  # bimestral

# IDs das colunas do quadro (se criar/renomear colunas no Monday, ajuste aqui)
COL = {
    "equipamento": "text_mm85nb75",
    "local": "text_mm8515b5",
    "situacao": "color_mm85ne9c",
    "periodicidade": "numeric_mm857ejg",
    "ultima": "date_mm856a3h",
    "proxima": "formula_mm856pk3",
    "responsavel": "text_mm85w8hs",
    "os": "text_mm85vyeq",
    "observacoes": "long_text_mm85myen",
    "foto_antes": "file_mm86n9y3",
    "foto_depois": "file_mm86y32t",
}

QUERY = """
query ($board: [ID!], $cols: [String!], $cursor: String) {
  boards(ids: $board) {
    name
    items_page(limit: 200, cursor: $cursor) {
      cursor
      items {
        id
        name
        column_values(ids: $cols) {
          id
          text
          ... on FormulaValue { display_value }
          ... on FileValue {
            files { ... on FileAssetValue { asset_id name created_at asset { public_url file_extension } } }
          }
        }
      }
    }
  }
}
"""

BRT = timezone(timedelta(hours=-3))
PASTA = Path(__file__).resolve().parent.parent / "data"
SAIDA = PASTA / "latest.json"
HISTORICO = PASTA / "historico.json"
ALERTA_DIAS = 10          # mesma regra do painel: "a vencer" com 10 dias ou menos
MAX_FOTOS = 400           # guarda ~13 meses de fotos diárias
PASTA_IMG = PASTA / "fotos"
LADO_MAX = 1600           # px, maior lado da foto salva
EXT_IMG = {"jpg", "jpeg", "png", "webp", "heic", "heif", "gif", "bmp"}


def chamar_api(token, variaveis):
    corpo = json.dumps({"query": QUERY, "variables": variaveis}).encode("utf-8")
    req = urllib.request.Request(
        API_URL,
        data=corpo,
        headers={
            "Authorization": token,
            "Content-Type": "application/json",
            "API-Version": "2025-04",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        dados = json.loads(resp.read().decode("utf-8"))
    if "errors" in dados:
        raise RuntimeError(f"Erro da API do Monday: {dados['errors']}")
    return dados["data"]


def para_data(txt):
    try:
        return date.fromisoformat((txt or "").strip()[:10])
    except ValueError:
        return None


def baixar_foto(coluna, tag, lado):
    """Salva a foto mais recente da coluna em data/fotos e devolve {arquivo, nome, enviada_em}."""
    arquivos = [f for f in (coluna or {}).get("files") or [] if f and f.get("asset")]
    arquivos = [f for f in arquivos if (f["asset"].get("file_extension") or "").lower().lstrip(".") in EXT_IMG]
    if not arquivos:
        return None
    f = max(arquivos, key=lambda x: x.get("created_at") or "")
    destino = PASTA_IMG / f"{tag}_{lado}_{f['asset_id']}.jpg"
    rel = f"data/fotos/{destino.name}"
    info = {"arquivo": rel, "nome": f.get("name") or "", "enviada_em": (f.get("created_at") or "")[:19]}
    if destino.exists():
        return info
    try:
        with urllib.request.urlopen(f["asset"]["public_url"], timeout=120) as resp:
            bruto = resp.read()
    except Exception as e:  # uma foto com problema não derruba a atualização
        print(f"Aviso: não foi possível baixar a foto {lado} de {tag}: {e}")
        return None
    PASTA_IMG.mkdir(parents=True, exist_ok=True)
    try:
        from io import BytesIO
        from PIL import Image, ImageOps
        try:
            import pillow_heif
            pillow_heif.register_heif_opener()
        except ImportError:
            pass
        img = ImageOps.exif_transpose(Image.open(BytesIO(bruto))).convert("RGB")
        img.thumbnail((LADO_MAX, LADO_MAX))
        img.save(destino, "JPEG", quality=82, optimize=True)
    except Exception:
        destino.write_bytes(bruto)  # sem Pillow: guarda o original
    print(f"Foto {lado} de {tag} salva ({destino.name})")
    return info


def main():
    token = os.environ.get("MONDAY_API_TOKEN", "").strip()
    if not token:
        sys.exit("Secret MONDAY_API_TOKEN não configurado no repositório.")

    itens, cursor, nome_quadro = [], None, ""
    while True:
        dados = chamar_api(token, {"board": [str(BOARD_ID)], "cols": list(COL.values()), "cursor": cursor})
        quadro = dados["boards"][0]
        nome_quadro = quadro["name"]
        pagina = quadro["items_page"]
        itens.extend(pagina["items"])
        cursor = pagina.get("cursor")
        if not cursor:
            break

    # fotos atuais (para manter a última quando a célula do Monday estiver vazia)
    anteriores = {}
    if SAIDA.exists():
        try:
            anteriores = {c["tag"]: c for c in json.loads(SAIDA.read_text(encoding="utf-8")).get("cortinas", [])}
        except ValueError:
            pass

    def foto(coluna, tag, lado):
        nova = baixar_foto(coluna, tag, lado)
        if nova:
            return nova
        velha = (anteriores.get(tag) or {}).get(f"foto_{lado}")
        if velha and (PASTA.parent / velha["arquivo"]).exists():
            return velha
        return None

    cortinas = []
    for it in itens:
        v = {c["id"]: c for c in it["column_values"]}
        txt = lambda chave: (v.get(COL[chave], {}).get("text") or "").strip()

        try:
            periodo = int(float(txt("periodicidade"))) or PERIODICIDADE_PADRAO
        except ValueError:
            periodo = PERIODICIDADE_PADRAO

        ultima = para_data(txt("ultima"))
        proxima = para_data(v.get(COL["proxima"], {}).get("display_value"))
        if ultima and not proxima:  # garante a próxima mesmo se a fórmula vier vazia
            proxima = ultima + timedelta(days=periodo)

        cortinas.append({
            "item_id": it["id"],
            "tag": it["name"].strip(),
            "equipamento": txt("equipamento") or "Cortina de Ar",
            "local": txt("local"),
            "situacao": txt("situacao") or "Operando",
            "periodicidade": periodo,
            "ultima_limpeza": ultima.isoformat() if ultima else None,
            "proxima_limpeza": proxima.isoformat() if proxima else None,
            "responsavel": txt("responsavel"),
            "os": txt("os"),
            "observacoes": txt("observacoes"),
            "foto_antes": foto(v.get(COL["foto_antes"]), it["name"].strip(), "antes"),
            "foto_depois": foto(v.get(COL["foto_depois"]), it["name"].strip(), "depois"),
        })

    cortinas.sort(key=lambda c: c["tag"])

    saida = {
        "gerado_em": datetime.now(BRT).isoformat(timespec="seconds"),
        "quadro": nome_quadro,
        "board_id": BOARD_ID,
        "board_url": f"https://messigean18s-team.monday.com/boards/{BOARD_ID}",
        "periodicidade_padrao": PERIODICIDADE_PADRAO,
        "total": len(cortinas),
        "cortinas": cortinas,
    }

    PASTA.mkdir(parents=True, exist_ok=True)
    SAIDA.write_text(json.dumps(saida, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    atualizar_historico(cortinas)
    print(f"OK: {len(cortinas)} cortinas gravadas em data/latest.json")


def estado(c, hoje):
    if c["situacao"] != "Operando":
        return "fora"
    if not c["ultima_limpeza"]:
        return "sem_registro"
    falta = (date.fromisoformat(c["proxima_limpeza"]) - hoje).days
    if falta < 0:
        return "vencida"
    if falta <= ALERTA_DIAS:
        return "a_vencer"
    return "em_dia"


def atualizar_historico(cortinas):
    hist = {"limpezas": [], "fotos": []}
    if HISTORICO.exists():
        try:
            hist.update(json.loads(HISTORICO.read_text(encoding="utf-8")))
        except ValueError:
            pass

    agora = datetime.now(BRT)
    hoje = agora.date()

    # 1) cada data de "Última Limpeza" nova vira um registro de limpeza realizada.
    #    Registro que foi desfeito no Monday (data apagada ou trocada por uma anterior,
    #    ou cortina excluída do quadro) sai do histórico: não conta como limpeza feita.
    atual = {c["tag"]: c["ultima_limpeza"] for c in cortinas}
    hist["limpezas"] = [
        l for l in hist["limpezas"]
        if l["tag"] in atual and atual[l["tag"]] and atual[l["tag"]] >= l["data"]
    ]
    ja = {(l["tag"], l["data"]) for l in hist["limpezas"]}
    for c in cortinas:
        if c["ultima_limpeza"] and (c["tag"], c["ultima_limpeza"]) not in ja:
            hist["limpezas"].append({
                "tag": c["tag"], "local": c["local"], "data": c["ultima_limpeza"],
                "registrado_em": agora.isoformat(timespec="seconds"),
            })
    hist["limpezas"].sort(key=lambda l: (l["data"], l["tag"]))

    # 1b) cada foto nova de antes/depois fica registrada (nada é apagado)
    hist.setdefault("registro_fotos", [])
    ja_fotos = {r["arquivo"] for r in hist["registro_fotos"]}
    for c in cortinas:
        for lado in ("antes", "depois"):
            f = c.get(f"foto_{lado}")
            if f and f["arquivo"] not in ja_fotos:
                hist["registro_fotos"].append({
                    "tag": c["tag"], "lado": lado, "arquivo": f["arquivo"],
                    "enviada_em": f.get("enviada_em", ""), "ultima_limpeza": c["ultima_limpeza"],
                })
    hist["registro_fotos"].sort(key=lambda r: (r["enviada_em"], r["tag"], r["lado"]))

    # 2) uma foto por dia da conformidade (a do dia é sobrescrita a cada execução)
    cont = {"em_dia": 0, "a_vencer": 0, "vencida": 0, "sem_registro": 0, "fora": 0}
    for c in cortinas:
        cont[estado(c, hoje)] += 1
    operando = len(cortinas) - cont["fora"]
    feitas_mes = sum(1 for c in cortinas if c["ultima_limpeza"]
                     and c["ultima_limpeza"][:7] == hoje.isoformat()[:7] and c["ultima_limpeza"] <= hoje.isoformat())
    foto = {
        "data": hoje.isoformat(), "total": len(cortinas), "operando": operando, **cont,
        "realizadas_mes": feitas_mes,
        # conformidade = cortinas limpas no mês / TODAS as cortinas do quadro
        "conformidade": round(feitas_mes / len(cortinas) * 100, 1) if cortinas else None,
    }
    hist["fotos"] = [f for f in hist["fotos"] if f["data"] != foto["data"]] + [foto]
    hist["fotos"] = sorted(hist["fotos"], key=lambda f: f["data"])[-MAX_FOTOS:]

    HISTORICO.write_text(json.dumps(hist, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
