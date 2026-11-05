#!/usr/bin/env python3
"""
Avaliação ISOLADA da etapa de Entity Extraction do DataMosaic.

Roda apenas o Cold Start do extrator de entidades
(modules/agents/extractor/entity_extractor.py -> EntityExtractor.extract_cold_start,
chamado via BaseExtractor.extract), sem Verifier / Fixer / Orchestrator,
e compara a saída com o gabarito (answer.json).

Métricas (por tabela e agregadas por caso):
  - cell_precision / cell_recall / cell_f1  -> MESMA lógica de test_dataset_evaluate.py
                                              (Doc2DBEvaluator.calculate_cell_metrics),
                                              comparável com o paper.
  - row_precision / row_recall / row_f1     -> nível de instância (linha casada com o
                                              gabarito com similaridade >= --row-threshold).
  - input_tokens / output_tokens / total_tokens / llm_calls / tempo.

Uso:
  # casos no layout padrão dataset/<DB>/<case>/{schema.json, docs/, answer.json}
  python evaluate_entity_extraction.py FinanceDB/case1 LegalDB/case1 --model gpt-4o-mini
  python evaluate_entity_extraction.py all --model gpt-4o-mini

  # casos customizados (docs/gabarito com nomes arbitrários) definidos em JSON
  python evaluate_entity_extraction.py --config eval_cases.json --model gpt-4o-mini

Saídas (em --output-dir, padrão output/entity_eval):
  metrics.csv                 tabela acumulada (uma linha por tabela + linha __ALL__ por caso)
  <run_id>/metrics.md         tabela desta execução em Markdown
  <run_id>/<caso>/predictions.json, comparisons.json
"""
import argparse
import csv
import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

# ---------------------------------------------------------------------------
# Ambiente (.env do pacote llm/) — precisa vir antes dos imports de modules/
# ---------------------------------------------------------------------------
from dotenv import load_dotenv  # noqa: E402

ENV_FILE = ROOT / "llm" / ".env"
if ENV_FILE.exists():
    load_dotenv(ENV_FILE)

import importlib.util  # noqa: E402

if importlib.util.find_spec("llm.main") is None:
    sys.exit("ERRO: pacote llm/ não encontrado (modules/ depende dele). "
             "Restaure com: git checkout -- llm")

logging.basicConfig(level=logging.WARNING,
                    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
log = logging.getLogger("entity_eval")
log.setLevel(logging.INFO)

from langchain_core.callbacks import BaseCallbackHandler  # noqa: E402

import modules.agents.extractor.entity_extractor as entity_mod  # noqa: E402
from modules.agents.extractor.base import BaseExtractor  # noqa: E402

# Reaproveita a métrica oficial do repositório
_stdout = sys.stdout
sys.stdout = open(os.devnull, "w")  # silencia o print de aviso do import
try:
    from test_dataset_evaluate import Doc2DBEvaluator  # noqa: E402
finally:
    sys.stdout.close()
    sys.stdout = _stdout

_METRICS = Doc2DBEvaluator.__new__(Doc2DBEvaluator)  # só usamos métodos puros de comparação


# ---------------------------------------------------------------------------
# Contagem de tokens
# ---------------------------------------------------------------------------
class TokenTracker(BaseCallbackHandler):
    """Acumula tokens de TODAS as chamadas LLM da etapa (inclui retries do OutputFixingParser
    e o fallback em Markdown via llm.gpt)."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.input_tokens = 0
        self.output_tokens = 0
        self.calls = 0
        self.calls_without_usage = 0
        self.fallback_calls = 0

    def add(self, inp: int, out: int):
        self.calls += 1
        self.input_tokens += int(inp or 0)
        self.output_tokens += int(out or 0)

    # LangChain (ChatOpenAI)
    def on_llm_end(self, response, **kwargs):
        for gens in response.generations:
            for gen in gens:
                usage = getattr(getattr(gen, "message", None), "usage_metadata", None)
                if usage:
                    self.add(usage.get("input_tokens"), usage.get("output_tokens"))
                    return
        token_usage = (response.llm_output or {}).get("token_usage") or {}
        if token_usage:
            self.add(token_usage.get("prompt_tokens"), token_usage.get("completion_tokens"))
        else:
            self.calls += 1
            self.calls_without_usage += 1

    def snapshot(self) -> Dict[str, int]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.input_tokens + self.output_tokens,
            "llm_calls": self.calls,
            "fallback_calls": self.fallback_calls,
            "calls_without_usage": self.calls_without_usage,
        }


TRACKER = TokenTracker()

# 1) Injeta o callback em todo ChatOpenAI criado pelo EntityExtractor
_OrigChatOpenAI = entity_mod.ChatOpenAI


def _tracked_chat_openai(**kwargs):
    kwargs.setdefault("callbacks", [TRACKER])
    return _OrigChatOpenAI(**kwargs)


entity_mod.ChatOpenAI = _tracked_chat_openai

# 2) Fallback (Markdown) usa llm.gpt -> requests.post; capturamos o 'usage' da resposta
try:
    import llm.gpt as _gpt

    _real_post = _gpt.requests.post

    def _tracked_post(*args, **kwargs):
        resp = _real_post(*args, **kwargs)
        try:
            usage = resp.json().get("usage") or {}
            TRACKER.fallback_calls += 1
            if usage:
                TRACKER.add(usage.get("prompt_tokens"), usage.get("completion_tokens"))
            else:
                TRACKER.calls += 1
                TRACKER.calls_without_usage += 1
        except Exception:
            pass
        return resp

    _gpt.requests = SimpleNamespace(post=_tracked_post)
except Exception as e:  # pragma: no cover
    log.warning(f"Não foi possível instrumentar llm.gpt: {e}")


# ---------------------------------------------------------------------------
# Carregamento de casos
# ---------------------------------------------------------------------------
TEXT_EXT = {".txt", ".md", ".json", ".csv"}


def read_document(path: Path) -> str:
    if path.suffix.lower() in TEXT_EXT:
        return path.read_text(encoding="utf-8", errors="ignore")
    from modules.agents.orchestrator.utils import DocumentUtils
    return DocumentUtils().convert_documents_to_text([str(path)])[0]


def entity_tables(schema: Dict[str, Any]) -> List[str]:
    """Tabelas que o BaseExtractor encaminha para o EntityExtractor (não-relação)."""
    names = []
    for t in schema.get("tables", []):
        ttype = str(t.get("type", "entity")).lower()
        rel_cfg = t.get("relation_extraction", {}) or {}
        if ttype in ("relation", "relationship") or rel_cfg.get("enabled", False):
            continue
        names.append(t["name"])
    return names


def normalize_answer(answer: Any, schema: Dict[str, Any], table_hint: Optional[str]) -> Dict[str, list]:
    if isinstance(answer, dict):
        return answer
    if isinstance(answer, list):
        table = table_hint or schema["tables"][0]["name"]
        return {table: answer}
    raise ValueError("Formato de answer.json não reconhecido")


def apply_filter(rows: list, flt: Optional[Dict[str, Any]]) -> list:
    if not flt:
        return rows
    field, values = flt["field"], {str(v) for v in flt["values"]}
    return [r for r in rows if str(r.get(field)) in values]


def load_standard_case(spec: str) -> Dict[str, Any]:
    case_dir = ROOT / "dataset" / spec
    docs = sorted(p for p in (case_dir / "docs").iterdir() if p.is_file())
    return {
        "name": spec,
        "schema": case_dir / "schema.json",
        "docs": docs,
        "answer": case_dir / "answer.json",
    }


def discover_all_cases() -> List[str]:
    specs = []
    for schema in sorted((ROOT / "dataset").glob("*/*/schema.json")):
        case_dir = schema.parent
        if (case_dir / "answer.json").exists() and (case_dir / "docs").is_dir():
            specs.append(f"{case_dir.parent.name}/{case_dir.name}")
    return specs


def load_config_cases(path: Path) -> List[Dict[str, Any]]:
    cases = json.loads(path.read_text(encoding="utf-8"))
    out = []
    for c in cases:
        out.append({
            "name": c["name"],
            "schema": ROOT / c["schema"],
            "docs": [ROOT / d for d in c["docs"]],
            "answer": ROOT / c["answer"] if c.get("answer") else None,
            "table": c.get("table"),
            "answer_filter": c.get("answer_filter"),
            "tables": c.get("tables"),
        })
    return out


# ---------------------------------------------------------------------------
# Métricas
# ---------------------------------------------------------------------------
def prf(tp: int, n_pred: int, n_gold: int):
    p = tp / n_pred * 100 if n_pred else (100.0 if n_gold == 0 else 0.0)
    r = tp / n_gold * 100 if n_gold else (100.0 if n_pred == 0 else 0.0)
    f = 2 * p * r / (p + r) if (p + r) else 0.0
    return p, r, f


def row_metrics(expected: List[dict], generated: List[dict], threshold: float):
    """Casamento guloso 1-para-1 com a mesma similaridade de linha do avaliador oficial."""
    used = set()
    tp = 0
    for exp_row in expected:
        best_idx, best = None, 0.0
        for i, gen_row in enumerate(generated):
            if i in used:
                continue
            s = _METRICS._calculate_row_similarity(exp_row, gen_row)
            if s > best:
                best, best_idx = s, i
        if best_idx is not None and best >= threshold:
            used.add(best_idx)
            tp += 1
    return tp


def cell_metrics(expected: Dict[str, list], generated: Dict[str, list]) -> Dict[str, Any]:
    if not any(expected.values()):
        # caso sem instâncias no gabarito: qualquer célula gerada é falso positivo
        gen_cells = sum(len(r) for rows in generated.values() for r in rows)
        p, r, f = prf(0, gen_cells, 0)
        return {"cell_precision": p, "cell_recall": r, "cell_f1": f,
                "total_expected_cells": 0, "total_generated_cells": gen_cells,
                "total_correct_cells": 0, "detailed_comparisons": []}
    return _METRICS.calculate_cell_metrics(generated, expected)


# ---------------------------------------------------------------------------
# Execução da etapa de entity extraction
# ---------------------------------------------------------------------------
def merge_documents(texts: List[str], names: List[str]) -> str:
    """Mesmo formato de UnifiedOrchestrator._merge_documents_langchain_style."""
    parts = []
    for i, (content, name) in enumerate(zip(texts, names), 1):
        if content:
            parts.append(f"=== Document {i}: {name} ===\n")
            parts.append(content)
            parts.append(f"\n=== End of Document {i} ===\n\n")
    return "\n".join(parts)


def run_table(extractor: BaseExtractor, schema: dict, table: str, texts: List[str],
              doc_paths: List[Path], model: str, mode: str, fill_nulls: bool) -> Dict[str, Any]:
    if mode == "merged":
        names = [p.name for p in doc_paths]
        text_contents = [merge_documents(texts, names)]
        documents = ["merged_documents"]
    else:
        text_contents = texts
        documents = [str(p) for p in doc_paths]

    context = SimpleNamespace(model=model, documents=documents, step_outputs=[],
                              enable_eae=extractor.enable_eae)
    TRACKER.reset()
    t0 = time.time()
    rows = extractor.extract(
        text_contents=text_contents,
        schema=schema,
        table_name=table,
        nl_prompt="",
        context=context,
        full_schema=schema,
    )
    elapsed = time.time() - t0

    table_def = extractor._get_table_definition(schema, table) or {}
    attr_names = [a["name"] for a in table_def.get("attributes", [])]
    predictions = []
    for row in rows:
        values = {k: c.value for k, c in row.cells.items()}
        if fill_nulls:
            for a in attr_names:
                values.setdefault(a, None)
        predictions.append(values)

    return {"predictions": predictions, "time_s": elapsed, **TRACKER.snapshot()}


def prepare_case(case: Dict[str, Any], args) -> Dict[str, Any]:
    """Carrega schema, documentos e gabarito e decide quais tabelas serão extraídas."""
    schema = json.loads(Path(case["schema"]).read_text(encoding="utf-8"))
    doc_paths = [Path(p) for p in case["docs"]]
    texts = [read_document(p) for p in doc_paths]

    expected: Dict[str, list] = {}
    if case.get("answer"):
        raw = json.loads(Path(case["answer"]).read_text(encoding="utf-8"))
        expected = normalize_answer(raw, schema, case.get("table"))
    if case.get("answer_filter"):
        expected = {t: apply_filter(r, case["answer_filter"]) for t, r in expected.items()}

    tables = case.get("tables") or entity_tables(schema)
    if args.tables:
        tables = [t for t in tables if t in args.tables]

    warnings = []
    schema_tables = {t["name"] for t in schema.get("tables", [])}
    orphan = [t for t in expected if t not in schema_tables]
    if orphan:
        warnings.append(f"gabarito tem tabela(s) {orphan} que não existem no schema "
                        f"-> métricas dessas tabelas serão inválidas (gabarito precisa ser projetado p/ o schema)")
    if expected and not any(expected.get(t) for t in tables):
        warnings.append("nenhuma tabela extraída tem linhas no gabarito -> tudo contará como falso positivo")

    return {"schema": schema, "doc_paths": doc_paths, "texts": texts,
            "expected": expected, "tables": tables, "warnings": warnings}


_ENCODER = None


def count_tokens(text: str) -> int:
    global _ENCODER
    try:
        if _ENCODER is None:
            import tiktoken
            _ENCODER = tiktoken.get_encoding("o200k_base")
        return len(_ENCODER.encode(text))
    except Exception:
        return len(text) // 4


def estimate_input_tokens(prep: Dict[str, Any], extractor: BaseExtractor, mode: str) -> int:
    """Estimativa (sem chamar a API) dos tokens de entrada da 1ª chamada por tabela/documento.
    Reconstrói o prompt do EntityExtractor; retries do OutputFixingParser não estão incluídos."""
    from langchain_core.output_parsers import PydanticOutputParser
    schema = prep["schema"]
    if mode == "merged":
        texts = [merge_documents(prep["texts"], [p.name for p in prep["doc_paths"]])]
    else:
        texts = [t for t in prep["texts"] if t and t.strip()]
    total = 0
    for table in prep["tables"]:
        table_def = extractor._get_table_definition(schema, table)
        list_model = extractor._create_list_model_from_schema({"tables": [table_def]}, table)
        fmt = PydanticOutputParser(pydantic_object=list_model).get_format_instructions() if list_model else ""
        ctx = extractor._build_schema_context(table_def, full_schema=schema)
        overhead = count_tokens(ctx + fmt) + 150  # +150 ~ texto fixo do prompt
        total += sum(overhead + count_tokens(t) for t in texts)
    return total


def evaluate_case(case: Dict[str, Any], extractor: BaseExtractor, args, run_dir: Path,
                  prep: Optional[Dict[str, Any]] = None) -> List[Dict]:
    prep = prep or prepare_case(case, args)
    schema, doc_paths, texts = prep["schema"], prep["doc_paths"], prep["texts"]
    expected, tables = prep["expected"], prep["tables"]
    for w in prep["warnings"]:
        log.warning(f"[{case['name']}] {w}")

    log.info(f"=== Caso {case['name']}: {len(doc_paths)} doc(s), tabelas de entidade: {tables}")

    results, all_gen, all_exp = [], {}, {}
    totals = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0,
              "llm_calls": 0, "fallback_calls": 0, "time_s": 0.0}
    detailed = {}

    for table in tables:
        exp_rows = expected.get(table, [])
        out = run_table(extractor, schema, table, texts, doc_paths,
                        args.model, args.mode, args.fill_nulls)
        gen_rows = out["predictions"]

        cm = cell_metrics({table: exp_rows}, {table: gen_rows})
        tp = row_metrics(exp_rows, gen_rows, args.row_threshold)
        rp, rr, rf = prf(tp, len(gen_rows), len(exp_rows))

        all_gen[table], all_exp[table] = gen_rows, exp_rows
        detailed[table] = cm.get("detailed_comparisons", [])
        for k in totals:
            totals[k] += out[k]

        results.append(build_row(case["name"], table, args, len(doc_paths), exp_rows, gen_rows,
                                 cm, (rp, rr, rf, tp), out))
        log.info(f"  [{table}] cell F1={cm['cell_f1']:.2f}  row F1={rf:.2f}  "
                 f"rows {len(gen_rows)}/{len(exp_rows)}  tokens in={out['input_tokens']} "
                 f"out={out['output_tokens']}  calls={out['llm_calls']}")

    # Agregado do caso (micro, todas as tabelas de entidade juntas)
    if len(tables) > 1:
        cm = cell_metrics(all_exp, all_gen)
        n_gen = sum(len(v) for v in all_gen.values())
        n_exp = sum(len(v) for v in all_exp.values())
        tp = sum(row_metrics(all_exp[t], all_gen[t], args.row_threshold) for t in tables)
        rp, rr, rf = prf(tp, n_gen, n_exp)
        results.append(build_row(case["name"], "__ALL__", args, len(doc_paths),
                                 [None] * n_exp, [None] * n_gen, cm, (rp, rr, rf, tp), totals))

    case_dir = run_dir / case["name"].replace("/", "__")
    case_dir.mkdir(parents=True, exist_ok=True)
    (case_dir / "predictions.json").write_text(
        json.dumps(all_gen, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    (case_dir / "comparisons.json").write_text(
        json.dumps(detailed, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return results


def build_row(case_name, table, args, n_docs, exp_rows, gen_rows, cm, row_m, usage) -> Dict:
    rp, rr, rf, tp = row_m
    return {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "case": case_name,
        "table": table,
        "model": args.model,
        "mode": args.mode,
        "eae": not args.no_eae,
        "n_docs": n_docs,
        "expected_rows": len(exp_rows),
        "extracted_rows": len(gen_rows),
        "matched_rows": tp,
        "row_precision": round(rp, 2),
        "row_recall": round(rr, 2),
        "row_f1": round(rf, 2),
        "expected_cells": cm.get("total_expected_cells", 0),
        "generated_cells": cm.get("total_generated_cells", 0),
        "correct_cells": cm.get("total_correct_cells", 0),
        "cell_precision": round(cm["cell_precision"], 2),
        "cell_recall": round(cm["cell_recall"], 2),
        "cell_f1": round(cm["cell_f1"], 2),
        "input_tokens": usage["input_tokens"],
        "output_tokens": usage["output_tokens"],
        "total_tokens": usage["total_tokens"],
        "llm_calls": usage["llm_calls"],
        "fallback_calls": usage["fallback_calls"],
        "time_s": round(usage["time_s"], 2),
    }


# ---------------------------------------------------------------------------
# Saída
# ---------------------------------------------------------------------------
MD_COLS = ["case", "table", "eae", "expected_rows", "extracted_rows",
           "row_precision", "row_recall", "row_f1",
           "cell_precision", "cell_recall", "cell_f1",
           "input_tokens", "output_tokens", "total_tokens", "llm_calls", "time_s"]


def to_markdown(rows: List[Dict]) -> str:
    lines = ["| " + " | ".join(MD_COLS) + " |", "|" + "---|" * len(MD_COLS)]
    for r in rows:
        lines.append("| " + " | ".join(str(r[c]) for c in MD_COLS) + " |")
    return "\n".join(lines)


def append_csv(path: Path, rows: List[Dict]):
    if not rows:
        return
    fields = list(rows[0].keys())
    if path.exists():
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            old_fields = reader.fieldnames or []
            old_rows = list(reader)
        if old_fields != fields:
            # Cabeçalho antigo (ex.: sem a coluna "eae"): reescreve com a união das colunas.
            # Linhas antigas sem "eae" foram geradas com EAE ativo (era sempre ligado).
            merged = fields + [c for c in old_fields if c not in fields]
            for r in old_rows:
                if not r.get("eae"):
                    r["eae"] = True
            with path.open("w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=merged)
                w.writeheader()
                w.writerows(old_rows)
                w.writerows(rows)
            return
    new = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        if new:
            w.writeheader()
        w.writerows(rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cases", nargs="*", help="Casos no layout padrão (ex.: FinanceDB/case1) ou 'all'")
    ap.add_argument("--config", type=Path, help="JSON com casos customizados (ver eval_cases.json)")
    ap.add_argument("--model", default="gpt-4o-mini")
    ap.add_argument("--mode", choices=["per_doc", "merged"], default="per_doc",
                    help="per_doc: uma chamada por documento (document_mode=single). "
                         "merged: documentos concatenados como no document_mode=multi.")
    ap.add_argument("--tables", nargs="*", help="Restringe a estas tabelas")
    ap.add_argument("--row-threshold", type=float, default=0.5,
                    help="Similaridade mínima p/ considerar uma linha casada (métrica de linha)")
    ap.add_argument("--fill-nulls", action="store_true",
                    help="Inclui campos nulos nas linhas extraídas (o parser do DataMosaic os descarta). "
                         "Útil quando o gabarito tem muitos nulos.")
    ap.add_argument("--output-dir", type=Path, default=ROOT / "output" / "entity_eval")
    ap.add_argument("--no-eae", action="store_true",
                    help="Desativa a estratégia EAE (dica 'scan entities first') no prompt de entidades")
    ap.add_argument("-v", "--verbose", action="store_true", help="Mostra logs do extrator")
    ap.add_argument("--case", nargs="+", metavar="NOME",
                    help="Roda só estes casos (nome exato ou padrão, ex.: 'CommonGovernment/doc1' "
                         "ou 'CommonGovernment/*'). Combine com --list para ver os nomes.")
    ap.add_argument("--list", action="store_true",
                    help="Só lista os casos com estimativa de tokens de entrada (NÃO chama a API)")
    ap.add_argument("--confirm", action="store_true",
                    help="Mostra a estimativa e pede confirmação antes de cada caso")
    ap.add_argument("--budget", type=int, default=None,
                    help="Para a execução quando o total de tokens (entrada+saída) ultrapassar este valor")
    args = ap.parse_args()

    if args.verbose:
        logging.getLogger("doc2db").setLevel(logging.INFO)

    cases: List[Dict[str, Any]] = []
    specs = discover_all_cases() if args.cases == ["all"] else args.cases
    cases += [load_standard_case(s) for s in specs]
    if args.config:
        cases += load_config_cases(args.config)
    if not cases:
        ap.error("Informe ao menos um caso (ex.: FinanceDB/case1, 'all') ou --config")

    if args.case:
        from fnmatch import fnmatch
        cases = [c for c in cases if any(fnmatch(c["name"], pat) for pat in args.case)]
        if not cases:
            ap.error(f"Nenhum caso corresponde a {args.case}. Use --list para ver os nomes.")

    extractor = BaseExtractor(enable_eae=not args.no_eae)
    log.info(f"EAE {'ATIVADO' if extractor.enable_eae else 'DESATIVADO'}")

    if args.list:
        print(f"{'caso':45s} {'docs':>4s} {'tabelas':>7s} {'~tokens entrada':>16s}  avisos")
        grand = 0
        for case in cases:
            prep = prepare_case(case, args)
            est = estimate_input_tokens(prep, extractor, args.mode)
            grand += est
            print(f"{case['name']:45s} {len(prep['doc_paths']):>4d} {len(prep['tables']):>7d} "
                  f"{est:>16,d}  {'; '.join(prep['warnings'])}")
        print(f"{'TOTAL':45s} {'':>4s} {'':>7s} {grand:>16,d}")
        print("\n(estimativa da 1ª chamada por tabela/doc; não inclui tokens de saída nem retries)")
        return

    run_id = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{args.model.replace('/', '-')}_{args.mode}_{'EAE' if not args.no_eae else 'noEAE'}"
    run_dir = args.output_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    all_rows: List[Dict] = []
    used_in = used_out = 0
    for idx, case in enumerate(cases, 1):
        if args.budget is not None and used_in + used_out >= args.budget:
            log.warning(f"Orçamento de {args.budget:,} tokens atingido ({used_in + used_out:,}). "
                        f"Casos restantes não executados: {[c['name'] for c in cases[idx - 1:]]}")
            break
        try:
            prep = prepare_case(case, args)
            if args.confirm:
                est = estimate_input_tokens(prep, extractor, args.mode)
                for w in prep["warnings"]:
                    print(f"  AVISO: {w}")
                ans = input(f"[{idx}/{len(cases)}] {case['name']}: {len(prep['tables'])} tabela(s), "
                            f"~{est:,} tokens de entrada. Rodar? [s/N/q] ").strip().lower()
                if ans == "q":
                    break
                if ans not in ("s", "y", "sim", "yes"):
                    continue
            case_rows = evaluate_case(case, extractor, args, run_dir, prep)
            all_rows += case_rows
            # Persiste após cada caso: se interromper, o que já rodou fica salvo
            append_csv(args.output_dir / "metrics.csv", case_rows)
            c_in = sum(r["input_tokens"] for r in case_rows if r["table"] != "__ALL__")
            c_out = sum(r["output_tokens"] for r in case_rows if r["table"] != "__ALL__")
            used_in, used_out = used_in + c_in, used_out + c_out
            print(f"\n>>> [{idx}/{len(cases)}] {case['name']}: entrada={c_in:,} saída={c_out:,} | "
                  f"acumulado: entrada={used_in:,} saída={used_out:,} total={used_in + used_out:,}\n")
        except KeyboardInterrupt:
            log.warning("Interrompido pelo usuário.")
            break
        except Exception as e:
            log.exception(f"Falha no caso {case['name']}: {e}")

    (run_dir / "metrics.csv").unlink(missing_ok=True)
    append_csv(run_dir / "metrics.csv", all_rows)
    md = to_markdown(all_rows)
    (run_dir / "metrics.md").write_text(md + "\n", encoding="utf-8")

    print("\n" + md)
    print(f"\nTabela acumulada: {args.output_dir / 'metrics.csv'}")
    print(f"Detalhes desta execução: {run_dir}")


if __name__ == "__main__":
    main()
