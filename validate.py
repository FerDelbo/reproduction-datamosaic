import sys
import json


def carregar_linhas(path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, list):
        return data

    if isinstance(data, dict):
        if len(data) == 1:
            return next(iter(data.values()))
        print(f"[AVISO] '{path}' tem múltiplas tabelas: {list(data.keys())}")
        print("Usando a primeira encontrada. Se quiser outra, ajuste o script.")
        return next(iter(data.values()))

    raise ValueError(f"Formato de JSON não reconhecido em {path}")


def normalizar(v):
    """Torna a comparação tolerante a diferenças de tipo/formatação:
    - None / 'NULL' / 'None' / string vazia viram None
    - números viram float, então '500000.00' == 500000.0 == '500000'
    - o resto vira string em minúsculas, sem espaço nas pontas
    """
    if v is None:
        return None
    s = str(v).strip()
    if s.upper() in ("NULL", "NONE", ""):
        return None
    try:
        return round(float(s), 6)
    except ValueError:
        return s.casefold()


def comparar(gabarito_path, extraido_path, pk_field="RecordID"):
    gabarito_rows = carregar_linhas(gabarito_path)
    extraido_rows = carregar_linhas(extraido_path)

    gabarito = {str(r[pk_field]): r for r in gabarito_rows if pk_field in r}
    extraido = {str(r[pk_field]): r for r in extraido_rows if pk_field in r}

    gt_ids = set(gabarito.keys())
    pred_ids = set(extraido.keys())
    matched_ids = gt_ids & pred_ids
    missing_ids = gt_ids - pred_ids   # devia ter extraído e não extraiu
    extra_ids = pred_ids - gt_ids     # extraiu algo que não está no gabarito (a mais / alucinação)

    row_precision = len(matched_ids) / len(pred_ids) if pred_ids else 0.0
    row_recall = len(matched_ids) / len(gt_ids) if gt_ids else 0.0
    row_f1 = (2 * row_precision * row_recall / (row_precision + row_recall)
              if (row_precision + row_recall) > 0 else 0.0)

    # --- nível célula, só nas linhas que casaram pela PK ---
    todos_campos = set()
    for r in gabarito.values():
        todos_campos.update(r.keys())
    for r in extraido.values():
        todos_campos.update(r.keys())

    total_campos = 0
    campos_corretos = 0
    divergencias = []          # lista de (pk, campo, valor_gabarito, valor_extraido)
    total_por_campo = {c: 0 for c in todos_campos}
    erros_por_campo = {c: 0 for c in todos_campos}

    for pk_val in matched_ids:
        gt_row = gabarito[pk_val]
        pred_row = extraido[pk_val]
        for campo in todos_campos:
            if campo == pk_field:
                continue
            total_campos += 1
            total_por_campo[campo] += 1
            v_gt = normalizar(gt_row.get(campo))      # .get() já cobre "chave ausente = None"
            v_pred = normalizar(pred_row.get(campo))
            if v_gt == v_pred:
                campos_corretos += 1
            else:
                erros_por_campo[campo] += 1
                divergencias.append((pk_val, campo, gt_row.get(campo), pred_row.get(campo)))

    cell_accuracy = campos_corretos / total_campos if total_campos else 0.0

    print(f"\n{'='*70}")
    print(f"Gabarito : {gabarito_path}  ({len(gt_ids)} instância(s))")
    print(f"Extraído : {extraido_path}  ({len(pred_ids)} instância(s))")
    print(f"Chave usada para casar as linhas: '{pk_field}'")
    print(f"{'='*70}")

    print(f"\n--- Nível LINHA (achou a instância certa?) ---")
    print(f"  Precisão: {row_precision:.2%}   Recall: {row_recall:.2%}   F1: {row_f1:.2%}")
    print(f"  Corretas:                 {len(matched_ids)}")
    print(f"  Faltando (não extraiu):   {len(missing_ids)}  {sorted(missing_ids)}")
    print(f"  A mais (fora do gabarito):{len(extra_ids)}  {sorted(extra_ids)}")

    print(f"\n--- Nível CÉLULA (valores dos campos, só nas linhas que casaram) ---")
    print(f"  Acurácia geral: {cell_accuracy:.2%}  ({campos_corretos}/{total_campos} campos)")

    campos_com_erro = [(c, erros_por_campo[c], total_por_campo[c])
                        for c in todos_campos if total_por_campo[c] > 0 and erros_por_campo[c] > 0]
    if campos_com_erro:
        print(f"\n  Campos com divergência:")
        for campo, err, tot in sorted(campos_com_erro, key=lambda x: -x[1]):
            print(f"    {campo:30s} {tot - err}/{tot} corretos  ({err} divergência(s))")

        print(f"\n  Detalhe das divergências:")
        for pk_val, campo, v_gt, v_pred in divergencias:
            print(f"    [{pk_val}] {campo}: gabarito={v_gt!r}  extraído={v_pred!r}")
    else:
        print(f"  Nenhuma divergência de valor nas linhas que casaram — tudo certo.")

    return {
        "row_precision": row_precision,
        "row_recall": row_recall,
        "row_f1": row_f1,
        "cell_accuracy": cell_accuracy,
        "missing_ids": sorted(missing_ids),
        "extra_ids": sorted(extra_ids),
        "divergencias": divergencias,
    }




# if __name__ == "__main__":
#     if len(sys.argv) < 3:
#         print(__doc__)
#         sys.exit(1)
gabarito_path = sys.argv[1]
extraido_path = sys.argv[2]
pk_field = sys.argv[3] if len(sys.argv) > 3 else "RecordID"
comparar(gabarito_path, extraido_path, pk_field)