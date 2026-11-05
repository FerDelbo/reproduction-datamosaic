import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logging.getLogger("llm.gpt").setLevel(logging.DEBUG)
logging.getLogger("doc2db.extractor").setLevel(logging.DEBUG)

import sys, os, json, ast, argparse
from types import SimpleNamespace
from modules.agents.extractor.base import BaseExtractor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# schema
with open("/home/fernando/Área de Trabalho/DataMosaic/dataset/CommonGovernment/schema.json", "r", encoding="utf-8") as f:
# with open("/home/fernando/Área de Trabalho/DataMosaic/dataset/StudentDB/case1/schema.json", "r", encoding="utf-8") as f:
    schema = json.load(f)

# document
document1 =  open("./dataset/CommonGovernment/docs/doc1.txt", encoding="utf-8").read()
document2 =  open("./dataset/CommonGovernment/docs/doc2.txt", encoding="utf-8").read()
document3 =  open("./dataset/CommonGovernment/docs/d3.txt", encoding="utf-8").read()

# grounth true doc1 4 instancias, doc2 duas instancias com nulos e doc3 sem instanicas

parser = argparse.ArgumentParser()
parser.add_argument("--no-eae", action="store_true", help="Desativa a estratégia EAE na extração de entidades")
args = parser.parse_args()
USE_EAE = not args.no_eae

context = SimpleNamespace(model="gpt-4o-mini", enable_eae=USE_EAE)  # troque pro modelo que você configurou no .env

extractor = BaseExtractor(enable_eae=USE_EAE)

rows = extractor.extract(
    text_contents=[document1, document2, document3],
    # text_contents=[document2],
    schema=schema,          # pode ser o schema completo (múltiplas tabelas)
    table_name="CommonGovernment",       # nome exato da tabela-alvo dentro de schema["tables"]
    nl_prompt="",            # instrução adicional em linguagem natural, opcional
    context=context,
    full_schema=schema,      # opcional: dá contexto de FKs/outras tabelas pro prompt
)

import json
from datetime import datetime

print(f"\n{len(rows)} linha(s) extraída(s):\n")

resultado = []
for row in rows:
    valores = {campo: cell.value for campo, cell in row.cells.items()}
    print(f"  tuple_id={row.tuple_id}  {valores}")
    resultado.append(valores)

saida = {
    "run_info": {
        "model": context.model,
        "eae_enabled": USE_EAE,
        "timestamp": datetime.now().isoformat(),
        "num_rows": len(resultado),
    },
    "CommonGovernment": resultado,
}

eae_tag = "EAE" if USE_EAE else "noEAE"
nome_arquivo = f"./output/extraidoDOC4_{context.model.replace('/', '-')}_{eae_tag}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
with open(nome_arquivo, "w", encoding="utf-8") as f:
    json.dump(saida, f, indent=2, ensure_ascii=False)

print(f"\nSalvo em: {nome_arquivo}")