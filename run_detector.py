"""
Executa UM detector (verificador MCP) por vez sobre um conjunto de dados e
reporta o que ele detectou. Funciona com schema flat e normalizado.

Dois modos:

  1) Só detectar (dados quaisquer, ex.: saída da extração):
       python run_detector.py --detector type \
           --schema dataset/CommonGovernment/schema.json \
           --data   output/entity_eval/<run>/<caso>/predictions.json

  2) Verificar a detecção (--inject N): parte de um gabarito LIMPO (answer),
     injeta N erros conhecidos do tipo que o detector deveria pegar e mede
     precisão/recall da detecção. Também roda no dado limpo para contar
     falsos alarmes.
       python run_detector.py --detector type --inject 5 \
           --schema dataset/CommonGovernment/schema_commongov_normalized.json \
           --data   dataset/CommonGovernment/answer_normalized.json

Detectores: type, value, structure, format, temporal, reference, logic, aggregation
  (logic e aggregation chamam LLM; exigem --allow-llm e não têm injeção automática)

Use --detector all para rodar todos, um de cada vez, com relatório separado.
Relatórios: output/detection/<timestamp>_<tag>/<detector>.json + report.md
"""
import argparse
import copy
import json
import logging
import random
import re
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Set, Tuple

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from modules.memory import TableSnapshot, TableRow, CellData  # noqa: E402
from modules.agents.mcp.base import get_table_definition  # noqa: E402

DETECTORS = ["type", "value", "structure", "format", "temporal", "reference", "logic", "aggregation"]
LLM_DETECTORS = {"logic", "aggregation"}

log = logging.getLogger("run_detector")


# ---------------------------------------------------------------------------
# Carregamento
# ---------------------------------------------------------------------------
def make_verifier(name: str, allow_llm: bool):
    from modules.agents.mcp import type_mcp, value_mcp, structure_mcp, format_mcp, \
        temporal_mcp, reference_mcp, logic_mcp, aggregation_mcp
    v = {
        "type": type_mcp.TypeVerifier,
        "value": value_mcp.ValueVerifier,
        "structure": structure_mcp.StructureVerifier,
        "format": format_mcp.FormatVerifier,
        "temporal": temporal_mcp.TemporalVerifier,
        "reference": reference_mcp.ReferenceVerifier,
        "logic": logic_mcp.LogicVerifier,
        "aggregation": aggregation_mcp.AggregationVerifier,
    }[name]()
    if hasattr(v, "enable_llm_validation"):
        v.enable_llm_validation = allow_llm
    return v


def load_data(path: Path, schema: dict) -> Dict[str, List[dict]]:
    """Aceita answer flat (lista), answer normalizado / predictions.json ({tabela: [linhas]})
    ou {"run_info":..., "<tabela>": [...]} (saída do extract.py)."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, list):
        return {schema["tables"][0]["name"]: raw}
    return {k: v for k, v in raw.items() if isinstance(v, list)}


def to_snapshot(table: str, rows: List[dict]) -> TableSnapshot:
    return TableSnapshot(
        run_id="run_detector", table=table, created_at="",
        rows=[TableRow(tuple_id=f"{table}#{i}",
                       cells={k: CellData(value=v, evidences=[]) for k, v in r.items()})
              for i, r in enumerate(rows)])


def attrs_of(schema: dict, table: str) -> List[dict]:
    td = get_table_definition(schema, table) or {}
    return td.get("attributes", [])


# ---------------------------------------------------------------------------
# Execução de um detector
# ---------------------------------------------------------------------------
def run_one(verifier, schema: dict, data: Dict[str, List[dict]]) -> List[dict]:
    snapshots = {t: to_snapshot(t, rows) for t, rows in data.items()}
    context = SimpleNamespace(all_snapshots=snapshots, schema=schema, model="gpt-4o-mini")
    out = []
    for table, snap in snapshots.items():
        if not get_table_definition(schema, table):
            log.warning(f"tabela {table} não existe no schema; ignorada")
            continue
        try:
            violations = verifier.verify(snap, schema, table, context)
        except TypeError:
            violations = verifier.verify(snap, schema, table)
        for v in violations:
            out.append({"table": v.table or table, "tuple_id": v.tuple_id, "attr": v.attr,
                        "constraint_type": v.constraint_type, "severity": v.severity,
                        "description": v.description})
    return out


# ---------------------------------------------------------------------------
# Injeção de erros conhecidos (um tipo por detector)
# ---------------------------------------------------------------------------
NUMERIC = ("INT", "DECIMAL", "FLOAT", "DOUBLE", "NUMERIC", "NUMBER", "REAL")


def _is_numeric(a): return any(t in str(a.get("type", "")).upper() for t in NUMERIC)
def _is_date(a): return any(t in str(a.get("type", "")).upper() for t in ("DATE", "TIME"))
def _filled(v): return v is not None and str(v).strip() not in ("", "NULL", "null")


def candidates(detector: str, schema: dict, data: Dict[str, List[dict]], verifier) -> List[Tuple]:
    """Lista de (tabela, linha, atributo, valor_injetado, células_aceitas)."""
    cands = []
    rels = schema.get("relations", [])
    fk_cols = {(r["from"]["table"], r["from"]["field"]) for r in rels}
    fmt_rules = getattr(verifier, "field_format_rules", {}) or {}
    for table, rows in data.items():
        attrs = attrs_of(schema, table)
        pk = [a["name"] for a in attrs if a.get("primary_key")]
        for i, r in enumerate(rows):
            for a in attrs:
                n, v = a["name"], r.get(a["name"])
                tid = f"{table}#{i}"
                if detector == "type" and _is_numeric(a) and _filled(v):
                    cands.append((table, i, n, "valor_invalido_xyz", {(table, tid, n)}))
                elif detector == "value" and _is_numeric(a) and _filled(v) and n not in pk:
                    cands.append((table, i, n, None, {(table, tid, n)}))
                elif detector == "temporal" and _is_date(a) and _filled(v):
                    cands.append((table, i, n, "data-invalida-99", {(table, tid, n)}))
                elif detector == "format" and (a.get("pattern") or n in fmt_rules) and _filled(v):
                    cands.append((table, i, n, "###formato_quebrado###", {(table, tid, n)}))
                elif detector == "reference" and (table, n) in fk_cols and _filled(v):
                    cands.append((table, i, n, f"FK_INEXISTENTE_{i}", {(table, tid, n)}))
        if detector == "structure" and pk and len(rows) > 1:
            k = pk[0]
            for i in range(1, len(rows)):
                # PK duplicada: a linha i recebe a PK da linha 0; aceita detecção em qualquer uma
                cands.append((table, i, k, rows[0].get(k),
                              {(table, f"{table}#{i}", k), (table, f"{table}#0", k)}))
    return cands


def inject(detector, schema, data, n, seed, verifier):
    cands = candidates(detector, schema, data, verifier)
    if not cands:
        return None, []
    rnd = random.Random(seed)
    # no máximo um erro por célula/linha para não confundir as contagens
    rnd.shuffle(cands)
    chosen, used_rows = [], set()
    for c in cands:
        if (c[0], c[1]) in used_rows:
            continue
        chosen.append(c); used_rows.add((c[0], c[1]))
        if len(chosen) >= n:
            break
    dirty = copy.deepcopy(data)
    errors = []
    for table, i, attr, new, accept in chosen:
        errors.append({"table": table, "tuple_id": f"{table}#{i}", "attr": attr,
                       "original": data[table][i].get(attr), "injected": new,
                       "_accept": accept})
        dirty[table][i][attr] = new
    return dirty, errors


def score(errors: List[dict], violations: List[dict], baseline: Set[Tuple]) -> Dict[str, Any]:
    hit_cells = {(v["table"], v["tuple_id"], v["attr"]) for v in violations}
    accept_all = set().union(*[e["_accept"] for e in errors]) if errors else set()
    for e in errors:
        e["detected"] = bool(e["_accept"] & hit_cells)
    tp = sum(e["detected"] for e in errors)
    # falsos positivos: células sinalizadas que não são erro injetado nem já eram sinalizadas no limpo
    fp_cells = hit_cells - accept_all - baseline
    p = tp / (tp + len(fp_cells)) * 100 if (tp + len(fp_cells)) else 0.0
    r = tp / len(errors) * 100 if errors else 0.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return {"injected": len(errors), "detected": tp, "missed": len(errors) - tp,
            "false_positive_cells": len(fp_cells), "precision": round(p, 2),
            "recall": round(r, 2), "f1": round(f, 2),
            "false_positive_examples": sorted(fp_cells)[:10]}


# ---------------------------------------------------------------------------
def summarize(violations: List[dict]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for v in violations:
        k = f"{v['table']}.{v['attr']}"
        out[k] = out.get(k, 0) + 1
    return dict(sorted(out.items(), key=lambda x: -x[1]))


def run_detector(name, args, schema, data) -> Dict[str, Any]:
    if name in LLM_DETECTORS and not args.allow_llm:
        return {"detector": name, "status": "pulado",
                "reason": "detector usa LLM; rode com --allow-llm"}
    verifier = make_verifier(name, args.allow_llm)
    clean = run_one(verifier, schema, data)
    res = {"detector": name, "status": "ok",
           "clean": {"violations": len(clean), "by_cell": summarize(clean), "items": clean}}
    if args.inject:
        if name in LLM_DETECTORS:
            res["inject"] = {"status": "sem injeção automática para detectores LLM"}
            return res
        dirty, errors = inject(name, schema, data, args.inject, args.seed, verifier)
        if dirty is None:
            res["inject"] = {"status": "nenhuma célula elegível para este detector neste schema "
                                       "(ex.: sem FKs, sem DATE, sem pattern)"}
            return res
        found = run_one(verifier, schema, dirty)
        baseline = {(v["table"], v["tuple_id"], v["attr"]) for v in clean}
        sc = score(errors, found, baseline)
        for e in errors:
            e.pop("_accept")
        res["inject"] = {"status": "ok", **sc, "errors": errors, "violations": found}
    return res


def to_md(results: List[dict], tag: str, args) -> str:
    lines = [f"# Detecção — {tag}", "",
             f"- schema: `{args.schema}`", f"- dados: `{args.data}`",
             f"- injeção: {args.inject or 'não'} (seed {args.seed})", "",
             "| detector | status | violações no dado original | injetados | detectados | perdidos | FP | P | R | F1 |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for r in results:
        if r["status"] != "ok":
            lines.append(f"| {r['detector']} | {r['reason']} | | | | | | | | |"); continue
        inj = r.get("inject", {})
        if inj.get("status") == "ok":
            cols = [inj["injected"], inj["detected"], inj["missed"], inj["false_positive_cells"],
                    inj["precision"], inj["recall"], inj["f1"]]
        else:
            cols = [inj.get("status", "-")] + [""] * 6
        lines.append(f"| {r['detector']} | ok | {r['clean']['violations']} | " +
                     " | ".join(str(c) for c in cols) + " |")
    for r in results:
        if r["status"] != "ok":
            continue
        lines += ["", f"## {r['detector']}"]
        if r["clean"]["by_cell"]:
            lines.append("Violações no dado original (tabela.atributo: qtd): " +
                         ", ".join(f"`{k}`: {v}" for k, v in list(r["clean"]["by_cell"].items())[:15]))
        inj = r.get("inject", {})
        if inj.get("status") == "ok":
            lines += ["", "| tabela | tuple_id | atributo | original | injetado | detectado |", "|---|---|---|---|---|---|"]
            for e in inj["errors"]:
                lines.append(f"| {e['table']} | {e['tuple_id']} | {e['attr']} | {e['original']!r} | "
                             f"{e['injected']!r} | {'SIM' if e['detected'] else 'NÃO'} |")
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--detector", required=True, choices=DETECTORS + ["all"])
    ap.add_argument("--schema", required=True, type=Path)
    ap.add_argument("--data", required=True, type=Path, help="answer flat/normalizado ou predictions.json")
    ap.add_argument("--inject", type=int, default=0, help="nº de erros a injetar para medir a detecção")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--allow-llm", action="store_true", help="permite detectores que chamam LLM")
    ap.add_argument("--tag", help="nome da execução (default: nome do schema)")
    ap.add_argument("--output-dir", type=Path, default=ROOT / "output" / "detection")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(levelname)s %(name)s: %(message)s")
    if not args.verbose:
        logging.getLogger("doc2db").setLevel(logging.ERROR)

    schema = json.loads(args.schema.read_text(encoding="utf-8"))
    data = load_data(args.data, schema)
    tag = args.tag or args.schema.stem
    names = DETECTORS if args.detector == "all" else [args.detector]

    run_dir = args.output_dir / f"{datetime.now():%Y%m%d_%H%M%S}_{tag}"
    run_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for name in names:
        print(f">>> detector: {name}", flush=True)
        r = run_detector(name, args, schema, data)
        results.append(r)
        (run_dir / f"{name}.json").write_text(
            json.dumps(r, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    md = to_md(results, tag, args)
    (run_dir / "report.md").write_text(md, encoding="utf-8")
    print("\n" + md)
    print(f"Relatórios em: {run_dir}")


if __name__ == "__main__":
    main()
