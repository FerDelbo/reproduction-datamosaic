"""Structure constraint MCP - validate and fix data structure issues (not-null, uniqueness, etc.)"""
from typing import List, Dict, Any, Optional, Set
from .base import MCPVerifier, MCPFixer, BaseMCP, get_table_definition, get_cell_value, is_valid_fix_value
from ...memory import TableSnapshot, Violation, Fix, SuggestedFix, ConstraintType, ViolationSeverity, FixType, TableRow
from ...core.ids import IdGenerator
from datetime import datetime
from types import SimpleNamespace
import json
import re

from llm.main import get_answer


def _dict_to_namespace(data: Any) -> Any:
    """Recursively convert nested dict/list to SimpleNamespace for attribute-style access."""
    if isinstance(data, dict):
        return SimpleNamespace(**{k: _dict_to_namespace(v) for k, v in data.items()})
    if isinstance(data, list):
        return [_dict_to_namespace(item) for item in data]
    return data


def _extract_json_payload(llm_response: str) -> Optional[str]:
    """Extract a JSON string from an LLM response."""
    if not llm_response or not llm_response.strip():
        return None
    
    fenced = re.search(
        r'```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```',
        llm_response, re.DOTALL
    )
    if fenced:
        return fenced.group(1)
    
    obj_match = re.search(r'\{.*\}', llm_response, re.DOTALL)
    if obj_match:
        return obj_match.group(0)
    
    return llm_response.strip()


class StructureVerifier(MCPVerifier):
    """Structure constraint verifier"""
    
    def __init__(self):
        super().__init__("StructureVerifier.v1")
    
    def get_supported_constraints(self) -> List[str]:
        return [
            ConstraintType.STRUCTURE.value,


        ]
    
    def can_handle(self, constraint_type: str) -> bool:
        return constraint_type in self.get_supported_constraints()
    
    def verify(self, snapshot: TableSnapshot, schema: Dict[str, Any], 
               table_name: str, context=None) -> List[Violation]:
        """Verify structure constraints in the table"""
        violations = []
        table_def = get_table_definition(schema, table_name)
        
        if not table_def:
            return violations
        
        attributes = table_def.get('attributes', [])
        attr_dict = {attr['name']: attr for attr in attributes}
        
        for row in snapshot.rows:
            for attr_name, cell_data in row.cells.items():
                if attr_name not in attr_dict:
                    continue
                
                attr_def = attr_dict[attr_name]
                value = cell_data.value
                
                cell_violations = self.verify_cell(
                    snapshot.table, row.tuple_id, attr_name, 
                    value, attr_def, snapshot, context
                )
                violations.extend(cell_violations)
        
        table_violations = self._verify_table_constraints(
            snapshot, attr_dict, table_name
        )
        violations.extend(table_violations)
        
        return violations
    
    def verify_cell(self, table: str, tuple_id: str, attr: str, 
                   value: Any, attr_def: Dict[str, Any], 
                   snapshot: TableSnapshot, context=None) -> List[Violation]:
        """Verify structure constraints for a single cell"""
        violations = []
        
        not_null_violations = self._check_not_null_constraint(
            table, tuple_id, attr, value, attr_def
        )
        violations.extend(not_null_violations)
        
        required_violations = self._check_required_constraint(
            table, tuple_id, attr, value, attr_def
        )
        violations.extend(required_violations)
        
        return violations
    
    def _check_not_null_constraint(self, table: str, tuple_id: str, attr: str, 
                                  value: Any, attr_def: Dict[str, Any]) -> List[Violation]:
        """Check not-null constraints"""
        violations = []
        
        if attr_def.get('not_null', False) or attr_def.get('required', False):
            if self._is_empty_value(value):
                violation_id = IdGenerator.generate_violation_id(
                    table, tuple_id, attr, ConstraintType.STRUCTURE.value
                )
                
                default_value = self._suggest_default_value(attr, attr_def)
                
                violation = Violation(
                    id=violation_id,
                    table=table,
                    tuple_id=tuple_id,
                    attr=attr,
                    constraint_type=ConstraintType.STRUCTURE.value,
                    description=f"Field {attr} has a missing value (empty/null), violating structure constraint",
                    severity=ViolationSeverity.ERROR.value,
                    
                    suggested_fix=SuggestedFix(value=default_value, ),
                    detector_id=self.mcp_id,
                    timestamp=""
                )
                violations.append(violation)
        
        return violations
    
    def _check_required_constraint(self, table: str, tuple_id: str, attr: str, 
                                  value: Any, attr_def: Dict[str, Any]) -> List[Violation]:
        """Check required-field constraints"""
        violations = []
        
        if attr_def.get('required', False) and not attr_def.get('not_null', False):
            if self._is_empty_value(value):
                violation_id = IdGenerator.generate_violation_id(
                    table, tuple_id, attr, ConstraintType.STRUCTURE.value
                )
                
                default_value = self._suggest_default_value(attr, attr_def)
                
                violation = Violation(
                    id=violation_id,
                    table=table,
                    tuple_id=tuple_id,
                    attr=attr,
                    constraint_type=ConstraintType.STRUCTURE.value,
                    description=f"Field {attr} has a missing value (empty/null) and is required",
                    severity=ViolationSeverity.WARN.value,
                    
                    suggested_fix=SuggestedFix(value=default_value, ),
                    detector_id=self.mcp_id,
                    timestamp=""
                )
                violations.append(violation)
        
        return violations
    
    def _verify_table_constraints(self, snapshot: TableSnapshot, 
                                 attr_dict: Dict[str, Dict[str, Any]], 
                                 table_name: str) -> List[Violation]:
        """Verify table-level structure constraints"""
        violations = []
        
        unique_violations = self._check_unique_constraints(
            snapshot, attr_dict, table_name
        )
        violations.extend(unique_violations)
        
        pk_violations = self._check_primary_key_constraints(
            snapshot, attr_dict, table_name
        )
        violations.extend(pk_violations)
        
        return violations
    
    def _check_unique_constraints(self, snapshot: TableSnapshot, 
                                 attr_dict: Dict[str, Dict[str, Any]], 
                                 table_name: str) -> List[Violation]:
        """Check uniqueness constraints"""
        violations = []
        
        unique_attrs = [
            attr_name for attr_name, attr_def in attr_dict.items()
            if attr_def.get('unique', False)
        ]
        
        for attr_name in unique_attrs:
            value_to_tuples = {}
            
            for row in snapshot.rows:
                if attr_name in row.cells:
                    value = row.cells[attr_name].value
                    if not self._is_empty_value(value):
                        str_value = str(value)
                        if str_value not in value_to_tuples:
                            value_to_tuples[str_value] = []
                        value_to_tuples[str_value].append(row.tuple_id)
            
            for value, tuple_ids in value_to_tuples.items():
                if len(tuple_ids) > 1:
                    for tuple_id in tuple_ids:
                        violation_id = IdGenerator.generate_violation_id(
                            table_name, tuple_id, attr_name, ConstraintType.STRUCTURE.value
                        )
                        
                        other_tuples = [tid for tid in tuple_ids if tid != tuple_id]
                        
                        violation = Violation(
                            id=violation_id,
                            table=table_name,
                            tuple_id=tuple_id,
                            attr=attr_name,
                            constraint_type=ConstraintType.STRUCTURE.value,
                            description=f"Field {attr_name} value '{value}' is duplicated in rows: {', '.join(other_tuples)}",
                            severity=ViolationSeverity.ERROR.value,
                            
                            suggested_fix=None,  # Uniqueness violations usually require manual handling
                            detector_id=self.mcp_id,
                            timestamp=""
                        )
                        violations.append(violation)
        
        return violations
    
    def _check_primary_key_constraints(self, snapshot: TableSnapshot, 
                                      attr_dict: Dict[str, Dict[str, Any]], 
                                      table_name: str) -> List[Violation]:
        """Check primary key constraints"""
        violations = []
        
        pk_attrs = [
            attr_name for attr_name, attr_def in attr_dict.items()
            if attr_def.get('primary_key', False)
        ]
        
        if not pk_attrs:
            return violations
        
        pk_values = {}
        
        for row in snapshot.rows:
            pk_value_parts = []
            has_null = False
            
            for pk_attr in pk_attrs:
                if pk_attr in row.cells:
                    value = row.cells[pk_attr].value
                    if self._is_empty_value(value):
                        has_null = True
                        break
                    pk_value_parts.append(str(value))
                else:
                    has_null = True
                    break
            
            if has_null:
                for pk_attr in pk_attrs:
                    if pk_attr in row.cells:
                        value = row.cells[pk_attr].value
                        if self._is_empty_value(value):
                            violation_id = IdGenerator.generate_violation_id(
                                table_name, row.tuple_id, pk_attr, ConstraintType.STRUCTURE.value
                            )
                            
                            violation = Violation(
                                id=violation_id,
                                table=table_name,
                                tuple_id=row.tuple_id,
                                attr=pk_attr,
                                constraint_type=ConstraintType.STRUCTURE.value,
                                description=f"Primary key field {pk_attr} cannot be empty",
                                severity=ViolationSeverity.ERROR.value,
                                
                                suggested_fix=None,
                                detector_id=self.mcp_id,
                                timestamp=""
                            )
                            violations.append(violation)
            else:
                pk_value = '|'.join(pk_value_parts)
                if pk_value in pk_values:
                    for pk_attr in pk_attrs:
                        violation_id = IdGenerator.generate_violation_id(
                            table_name, row.tuple_id, pk_attr, ConstraintType.STRUCTURE.value
                        )
                        
                        violation = Violation(
                            id=violation_id,
                            table=table_name,
                            tuple_id=row.tuple_id,
                            attr=pk_attr,
                            constraint_type=ConstraintType.STRUCTURE.value,
                            description=f"Duplicate primary key value, conflicts with row {pk_values[pk_value]}",
                            severity=ViolationSeverity.ERROR.value,
                            
                            suggested_fix=None,
                            detector_id=self.mcp_id,
                            timestamp=""
                        )
                        violations.append(violation)
                else:
                    pk_values[pk_value] = row.tuple_id
        
        return violations
    
    def _is_empty_value(self, value: Any) -> bool:
        """Check whether a value is empty"""
        if value is None:
            return True
        if isinstance(value, str) and value.strip() == '':
            return True
        return False
    
    def _suggest_default_value(self, attr: str, attr_def: Dict[str, Any]) -> str:
        """Suggest a default value"""
        attr_type = attr_def.get('type', 'string').lower()
        attr_name = attr.lower()
        
        if 'status' in attr_name:
            return 'Pending'
        elif 'date' in attr_name or 'time' in attr_name:
            return datetime.now().strftime('%Y-%m-%d')
        elif 'amount' in attr_name or 'price' in attr_name or 'cost' in attr_name:
            return '0.00'
        elif 'quantity' in attr_name or 'count' in attr_name:
            return '1'
        elif 'name' in attr_name:
            return 'Unnamed'
        elif 'description' in attr_name or 'remark' in attr_name:
            return 'N/A'
        
        if attr_type in ['integer', 'int', 'number']:
            return '0'
        elif attr_type in ['float', 'decimal']:
            return '0.0'
        elif attr_type in ['boolean', 'bool']:
            return 'false'
        elif attr_type in ['date']:
            return datetime.now().strftime('%Y-%m-%d')
        elif attr_type in ['datetime', 'timestamp']:
            return datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        else:
            return ''


class StructureFixer(MCPFixer):
    """Structure constraint fixer - use LLM to intelligently fix primary key conflicts and structure issues"""
    
    def __init__(self):
        super().__init__("StructureFixer.v2")  # Version bumped to v2 to indicate LLM support
        self.enable_llm_fixing = True  # Enable LLM fixing
    
    def _is_empty_value(self, value: Any) -> bool:
        """Check whether a value is empty"""
        if value is None:
            return True
        if isinstance(value, str) and value.strip() == '':
            return True
        return False
    
    def get_supported_constraints(self) -> List[str]:
        return [
            ConstraintType.STRUCTURE.value,
        ]
    
    def can_handle(self, constraint_type: str) -> bool:
        return constraint_type in self.get_supported_constraints()
    
    def can_fix(self, violation: Violation) -> bool:
        """
        Can now fix all structural violations, including primary key conflicts and uniqueness violations
        via LLM analysis and merging of duplicate records
        """
        if violation.constraint_type != ConstraintType.STRUCTURE.value:
            return False
        
        if self.enable_llm_fixing:
            return True
        
        return 'unique' not in violation.description.lower() and 'duplicate' not in violation.description.lower()
    
    def get_supported_fix_types(self) -> List[str]:
        return [
            FixType.DEFAULT_VALUE.value,
            FixType.STRUCTURE_FIX.value
        ]
    
    def fix(self, violation: Violation, snapshot: TableSnapshot, 
            context=None) -> List[Fix]:
        """
        Fix a single violation (backward compatible)
        For complex issues like primary key conflicts, prefer fix_batch for batch fixing
        """
        if not self.can_fix(violation):
            return []
        
        fixes = []
        
        if 'missing value' in violation.description.lower() or 'empty/null' in violation.description.lower():
            if violation.suggested_fix and violation.suggested_fix.value:
                suggested_value = violation.suggested_fix.value
                if is_valid_fix_value(suggested_value):
                    new_value = suggested_value
                else:
                    self.logger.warning(f"Suggested fix value '{suggested_value}' looks like prompt text rather than a data value; skipping fix")
                    return fixes
                
                fix_id = IdGenerator.generate_fix_id(
                    violation.table, violation.tuple_id, violation.attr,
                    FixType.DEFAULT_VALUE.value, None
                )
                
                fix = Fix(
                    id=fix_id,
                    table=violation.table,
                    tuple_id=violation.tuple_id,
                    attr=violation.attr,
                    old=None,
                    new=new_value,
                    fix_type=FixType.DEFAULT_VALUE.value,
                    applied_by=self.mcp_id,
                    timestamp="",
                )
                fixes.append(fix)
        
        return fixes
    
    def fix_batch(self, violations: List[Violation], snapshot: TableSnapshot, 
                  context=None) -> List[Fix]:
        """
        Batch-fix structural violations - use LLM to handle primary key conflicts and duplicate records
        
        This method will:
        1. Analyze all structural violations
        2. Identify duplicate record groups
        3. Use LLM to decide how to merge/delete/update records
        4. Generate fix operations
        """
        if not violations or not self.enable_llm_fixing:
            all_fixes = []
            for violation in violations:
                fixes = self.fix(violation, snapshot, context)
                all_fixes.extend(fixes)
            return all_fixes
        
        
        try:
            primary_key_violations = [
                v for v in violations 
                if 'primary key' in v.description.lower() and ('duplicate' in v.description.lower() or 'conflict' in v.description.lower())
            ]
            other_violations = [v for v in violations if v not in primary_key_violations]
            
            
            all_fixes = []
            
            if primary_key_violations:
                llm_fixes = self._llm_fix_structure_violations(
                    primary_key_violations, snapshot, context
                )
                all_fixes.extend(llm_fixes)
            
            for violation in other_violations:
                simple_fixes = self.fix(violation, snapshot, context)
                all_fixes.extend(simple_fixes)
            
            
            return all_fixes
            
        except Exception as e:
            self.logger.error(f"LLM batch fix failed: {e}")
            import traceback
            traceback.print_exc()
            
            all_fixes = []
            for violation in violations:
                fixes = self.fix(violation, snapshot, context)
                all_fixes.extend(fixes)
            return all_fixes
    
    def _llm_fix_structure_violations(self, violations: List[Violation], 
                                     snapshot: TableSnapshot, 
                                     context=None) -> List[Fix]:
        """Use LLM to fix structural violations (mainly primary key conflicts and duplicate records)"""
        fixes = []
        
        try:
            self.logger.info(f"[StructureFixer] Fixing {len(violations)} structure violations, table={snapshot.table}, rows={len(snapshot.rows) if snapshot.rows else 0}")
            
            schema_def = self._build_schema_definition(snapshot, context)
            
            violations_info = self._build_violations_info(violations)
            
            table_snapshot_str = self._build_table_snapshot(snapshot)
            
            duplicate_groups = self._identify_duplicate_groups(violations, snapshot)
            
            model = context.model if context and hasattr(context, 'model') else "gpt-4o"
            
            structure_fix = self._call_fix_structure_violations(
                table_name=snapshot.table,
                schema_definition=schema_def,
                violations_info=violations_info,
                table_snapshot=table_snapshot_str,
                duplicate_groups=duplicate_groups,
                model=model,
            )
            
            fixes = self._convert_structure_fix_to_fixes(
                structure_fix, violations, snapshot, context
            )
            
            ops_count = len(structure_fix.operations) if structure_fix.operations else 0
            if len(fixes) > 0:
                self.logger.info(f"[StructureFixer] Generated {len(fixes)} fixes")
            else:
                self.logger.warning(f"[StructureFixer] No fixes generated (operations={ops_count})")
            
            return fixes
            
        except Exception as e:
            self.logger.error(f"LLM structure fix failed: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    def _call_fix_structure_violations(self, table_name: str, schema_definition: str,
                                        violations_info: str, table_snapshot: str,
                                        duplicate_groups: str, model: str) -> SimpleNamespace:
        """Call LLM to generate a structural fix plan; returns SimpleNamespace (operations / merged_records / summary)."""
        system_prompt = (
            "You are a data quality expert specializing in structural table issues. "
            "Output strictly in the specified JSON format with no extra explanation or Markdown fences."
        )
        
        user_prompt = f"""Analyze structural issues in the table below and provide a fix plan.

## Table definition
Table: {table_name}
Schema:
{schema_definition}

## Detected violations
{violations_info}

## Current table data (full snapshot)
{table_snapshot}

## Duplicate record groups
{duplicate_groups}

## Fix principles

### 1. Primary key conflicts
- **Smart merge**: if duplicate rows are highly similar or identical, merge into one record
- **Keep the most complete row**: retain the row with the fullest, most accurate information
- **Remove redundant rows**: mark duplicate rows for deletion

### 2. Null filling
- If a field is empty but can be inferred from other rows, suggest a fill value
- Do not invent data; use only information already in the table
- Keep null when a value cannot be inferred

### 3. Noise cleanup
- Identify and clean obvious noise (format errors, illegal characters, etc.)
- Normalize data formats

## Important constraints
1. All fixes must be based on existing table data; do not add information
2. For primary key conflicts, prefer merge over simple deletion
3. Preserve data integrity and accuracy
4. If unsure how to fix, explain in reason and set operation_type to "keep"

Output format (JSON only, no other content):
{{
  "operations": [
    {{
      "operation_type": "merge | delete | update | keep",
      "tuple_id": "affected row ID",
      "reason": "operation rationale",
      "changes": "for update/merge, describe field changes as field: old -> new; otherwise null"
    }}
  ],
  "merged_records": [
    {{
      "tuple_id": "retained row ID after merge",
      "merged_from": ["original row IDs merged in"],
      "final_data": "final merged data (JSON string)"
    }}
  ],
  "summary": "summary of the fix plan"
}}
"""
        
        empty_fix = SimpleNamespace(operations=[], merged_records=[], summary="")
        
        try:
            llm_response = get_answer(user_prompt, system_prompt=system_prompt, model=model)
        except Exception as e:
            self.logger.error(f"LLM call failed: {e}")
            return empty_fix
        
        json_str = _extract_json_payload(llm_response)
        if not json_str:
            return empty_fix
        
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            self.logger.error(f"Failed to parse structure fix JSON: {e}")
            return empty_fix
        
        if not isinstance(data, dict):
            return empty_fix
        
        data.setdefault('operations', [])
        data.setdefault('merged_records', [])
        data.setdefault('summary', '')
        
        return _dict_to_namespace(data)
    
    def _build_schema_definition(self, snapshot: TableSnapshot, context=None) -> str:
        """Build schema definition string"""
        if not context or not hasattr(context, 'schema'):
            return f"Table: {snapshot.table}"
        
        schema = context.schema
        table_def = get_table_definition(schema, snapshot.table)
        
        if not table_def:
            return f"Table: {snapshot.table}"
        
        lines = [f"Table: {snapshot.table}"]
        lines.append("\nField definitions:")
        
        attributes = table_def.get('attributes', [])
        for attr in attributes:
            attr_name = attr.get('name')
            attr_type = attr.get('type', 'string')
            is_pk = attr.get('primary_key', False)
            is_unique = attr.get('unique', False)
            is_required = attr.get('required', False) or attr.get('not_null', False)
            
            flags = []
            if is_pk:
                flags.append('primary key')
            if is_unique:
                flags.append('unique')
            if is_required:
                flags.append('required')
            
            flag_str = f" ({', '.join(flags)})" if flags else ""
            lines.append(f"  - {attr_name}: {attr_type}{flag_str}")
        
        return "\n".join(lines)
    
    def _build_violations_info(self, violations: List[Violation]) -> str:
        """Build violation info string"""
        lines = []
        for i, v in enumerate(violations, 1):
            lines.append(f"{i}. Row ID: {v.tuple_id}")
            lines.append(f"   Field: {v.attr}")
            lines.append(f"   Issue: {v.description}")
            lines.append(f"   Severity: {v.severity}")
            lines.append("")
        
        return "\n".join(lines)
    
    def _build_table_snapshot(self, snapshot: TableSnapshot) -> str:
        """Build table snapshot string (for LLM analysis)"""
        lines = []
        
        if snapshot.rows:
            headers = list(snapshot.rows[0].cells.keys())
            lines.append("| " + " | ".join(headers) + " | Row ID |")
            lines.append("| " + " | ".join(["---"] * (len(headers) + 1)) + " |")
            
            for row in snapshot.rows:
                values = []
                for h in headers:
                    cell = row.cells.get(h)
                    value = str(cell.value) if cell else "NULL"
                    values.append(value)
                values.append(row.tuple_id)
                lines.append("| " + " | ".join(values) + " |")
        
        return "\n".join(lines)
    
    def _identify_duplicate_groups(self, violations: List[Violation], 
                                   snapshot: TableSnapshot) -> str:
        """Identify duplicate record groups"""
        duplicate_map = {}  # key: primary key value, value: [tuple_ids]
        
        for v in violations:
            if 'primary key' in v.description.lower() and 'conflict' in v.description.lower():
                import re
                match = re.search(r'conflicts with row\s+(t-[^\s]+)', v.description)
                if match:
                    conflicting_tuple = match.group(1)
                    
                    pk_value = self._get_primary_key_value(v.tuple_id, snapshot)
                    
                    if pk_value not in duplicate_map:
                        duplicate_map[pk_value] = []
                    
                    if v.tuple_id not in duplicate_map[pk_value]:
                        duplicate_map[pk_value].append(v.tuple_id)
                    if conflicting_tuple not in duplicate_map[pk_value]:
                        duplicate_map[pk_value].append(conflicting_tuple)
        
        lines = []
        for pk_value, tuple_ids in duplicate_map.items():
            lines.append(f"Primary key value: {pk_value}")
            lines.append(f"Duplicate row IDs: {', '.join(tuple_ids)}")
            lines.append(f"Duplicate count: {len(tuple_ids)}")
            
            for tuple_id in tuple_ids:
                row = self._get_row_by_tuple_id(tuple_id, snapshot)
                if row:
                    row_data = {k: str(v.value) for k, v in row.cells.items()}
                    lines.append(f"  - {tuple_id}: {json.dumps(row_data, ensure_ascii=False)}")
            
            lines.append("")
        
        return "\n".join(lines) if lines else "No duplicate record groups"
    
    def _get_primary_key_field(self, snapshot: TableSnapshot, context=None) -> Optional[str]:
        """Get primary key field name"""
        schema = None
        
        if context:
            if isinstance(context, dict):
                schema = context.get('schema')
                if not schema and 'processing_context' in context:
                    processing_context = context['processing_context']
                    if hasattr(processing_context, 'schema'):
                        schema = processing_context.schema
            else:
                if hasattr(context, 'schema'):
                    schema = context.schema
        
        if not schema and hasattr(snapshot, 'schema'):
            schema = snapshot.schema
        
        if not schema:
            return None
        
        if isinstance(schema, dict):
            if 'tables' in schema:
                table_def = get_table_definition(schema, snapshot.table)
                if table_def:
                    attributes = table_def.get('attributes', [])
                    for attr in attributes:
                        if isinstance(attr, dict):
                            constraints = attr.get('constraints', {})
                            if constraints.get('primary_key', False):
                                return attr.get('name')
            else:
                attributes = schema.get('attributes', [])
                for attr in attributes:
                    if isinstance(attr, dict):
                        constraints = attr.get('constraints', {})
                        if constraints.get('primary_key', False):
                            return attr.get('name')
        
        return None
    
    def _get_primary_key_value(self, tuple_id: str, snapshot: TableSnapshot) -> str:
        """Get primary key value"""
        row = self._get_row_by_tuple_id(tuple_id, snapshot)
        if not row:
            return "unknown"
        
        first_cell = list(row.cells.values())[0] if row.cells else None
        return str(first_cell.value) if first_cell else "unknown"
    
    def _get_row_by_tuple_id(self, tuple_id: str, snapshot: TableSnapshot) -> Optional[TableRow]:
        """Get row by tuple_id"""
        for row in snapshot.rows:
            if row.tuple_id == tuple_id:
                return row
        return None
    
    def _mark_violations_unfixable(self, violations: List[Violation], context):
        """Mark violation list as unfixable"""
        try:
            memory_manager = None
            run_id = None
            
            if context:
                if isinstance(context, dict):
                    memory_manager = context.get('memory_manager')
                    run_id = context.get('run_id')
                else:
                    memory_manager = getattr(context, 'memory_manager', None)
                    run_id = getattr(context, 'run_id', None)
            
            if memory_manager and run_id and violations:
                import asyncio
                for violation in violations:
                    try:
                        try:
                            loop = asyncio.get_running_loop()
                            asyncio.create_task(
                                memory_manager.mark_violation_unfixable(violation.id, run_id)
                            )
                        except RuntimeError:
                            asyncio.run(memory_manager.mark_violation_unfixable(violation.id, run_id))
                        self.logger.info(f"Marked violation {violation.id} as unfixable (safety check rejected)")
                    except Exception as mark_error:
                        self.logger.error(f"Failed to mark violation unfixable: {mark_error}")
            else:
                self.logger.debug(f"Cannot mark violations unfixable: context missing memory_manager or run_id")
        except Exception as e:
            self.logger.error(f"Failed to mark violations unfixable: {e}")
    
    def _are_rows_identical(self, row1: TableRow, row2: TableRow) -> bool:
        """Check whether two rows are identical"""
        if not row1 or not row2:
            return False
        
        all_fields = set(row1.cells.keys()) | set(row2.cells.keys())
        
        for field in all_fields:
            val1 = row1.cells.get(field)
            val2 = row2.cells.get(field)
            
            v1 = val1.value if val1 and hasattr(val1, 'value') else (val1 if val1 else None)
            v2 = val2.value if val2 and hasattr(val2, 'value') else (val2 if val2 else None)
            
            v1_str = str(v1).strip() if v1 is not None else ""
            v2_str = str(v2).strip() if v2 is not None else ""
            
            if v1_str != v2_str:
                return False
        
        return True
    
    def _is_row_subset_of(self, subset_row: TableRow, superset_row: TableRow) -> bool:
        """Check whether subset_row is a subset of superset_row
        
        Subset definition: all non-empty field values in subset_row exist and match in superset_row
        """
        if not subset_row or not superset_row:
            return False
        
        for field, cell in subset_row.cells.items():
            val = cell.value if hasattr(cell, 'value') else cell
            if val is None or (isinstance(val, str) and val.strip() == ""):
                continue
            
            superset_cell = superset_row.cells.get(field)
            if not superset_cell:
                return False
            
            superset_val = superset_cell.value if hasattr(superset_cell, 'value') else superset_cell
            
            val_str = str(val).strip() if val is not None else ""
            superset_val_str = str(superset_val).strip() if superset_val is not None else ""
            
            if val_str != superset_val_str:
                return False
        
        return True
    
    def _can_safely_delete_row(self, row_to_delete: TableRow, snapshot: TableSnapshot, 
                               violations: List[Violation], context=None) -> tuple[bool, str]:
        """Check whether a row can be safely deleted
        
        Deletion is allowed only when:
        1. Another row is identical to the row being deleted
        2. The row being deleted is a subset of another row (the other row has more information)
        
        Returns:
            (can_delete: bool, reason: str)
        """
        if not row_to_delete:
            return False, "Row does not exist"
        
        pk_field = self._get_primary_key_field(snapshot, context)
        if not pk_field:
            return False, "Cannot determine primary key field; conservative policy: deletion not allowed"
        
        delete_pk_cell = row_to_delete.cells.get(pk_field)
        if not delete_pk_cell:
            return False, "Row to delete has no primary key value"
        
        delete_pk_value = delete_pk_cell.value if hasattr(delete_pk_cell, 'value') else delete_pk_cell
        
        conflicting_rows = []
        for row in snapshot.rows:
            if row.tuple_id == row_to_delete.tuple_id:
                continue  # Skip self
            
            row_pk_cell = row.cells.get(pk_field)
            if not row_pk_cell:
                continue
            
            row_pk_value = row_pk_cell.value if hasattr(row_pk_cell, 'value') else row_pk_cell
            
            if str(row_pk_value).strip() == str(delete_pk_value).strip():
                conflicting_rows.append(row)
        
        if not conflicting_rows:
            return False, f"No other row with the same primary key value ({delete_pk_value}); deletion not allowed"
        
        for conflicting_row in conflicting_rows:
            if self._are_rows_identical(row_to_delete, conflicting_row):
                self.logger.info(f"[Safe delete check] Row {row_to_delete.tuple_id} is identical to row {conflicting_row.tuple_id}; deletion allowed")
                return True, f"Identical to row {conflicting_row.tuple_id}"
            
            if self._is_row_subset_of(row_to_delete, conflicting_row):
                self.logger.info(f"[Safe delete check] Row {row_to_delete.tuple_id} is a subset of row {conflicting_row.tuple_id}; deletion allowed")
                return True, f"Subset of row {conflicting_row.tuple_id}"
        
        for conflicting_row in conflicting_rows:
            if self._is_row_subset_of(conflicting_row, row_to_delete):
                self.logger.warning(f"[Safe delete check] Row {conflicting_row.tuple_id} is a subset of row {row_to_delete.tuple_id}; delete the conflicting row instead")
                return False, f"Conflicting row {conflicting_row.tuple_id} is a subset of the row to delete; delete the conflicting row instead"
        
        conflicting_tuple_ids = [r.tuple_id for r in conflicting_rows]
        self.logger.warning(f"[Safe delete check] Row {row_to_delete.tuple_id} is neither identical to nor a subset of conflicting rows {conflicting_tuple_ids}; deletion not allowed")
        return False, f"Neither identical to nor a subset of conflicting rows {conflicting_tuple_ids}"
    
    def _convert_structure_fix_to_fixes(self, structure_fix: Any, 
                                       violations: List[Violation],
                                       snapshot: TableSnapshot, 
                                       context=None) -> List[Fix]:
        """Convert LLM StructureFix to a list of Fix objects"""
        fixes = []
        
        deletion_count = sum(1 for op in structure_fix.operations or [] if op.operation_type == "delete")
        total_rows = len(snapshot.rows) if snapshot.rows else 0
        
        if deletion_count >= total_rows and total_rows > 0:
            self.logger.error(f"[StructureFixer SAFETY CHECK] Attempting to delete all {total_rows} rows!")
            self.logger.error(f"[StructureFixer SAFETY CHECK] Likely incorrect LLM decision; refusing to execute")
            self.logger.error(f"[StructureFixer SAFETY CHECK] Delete operations: {deletion_count}/{total_rows}")
            
            self.logger.error(f"[StructureFixer SAFETY CHECK] Violation list:")
            for i, v in enumerate(violations, 1):
                self.logger.error(f"      {i}. {v.tuple_id} - {v.attr}: {v.description}")
            
            self.logger.error(f"[StructureFixer SAFETY CHECK] LLM operations:")
            for i, op in enumerate(structure_fix.operations or [], 1):
                self.logger.error(f"      {i}. {op.operation_type} - {op.tuple_id}: {op.reason}")
            
            self.logger.error(f"[StructureFixer SAFETY CHECK] Refusing all delete operations to prevent data loss")
            
            self._mark_violations_unfixable(violations, context)
            
            return []  # Do not perform any deletions
        
        for operation in structure_fix.operations:
            try:
                if operation.operation_type == "delete":
                    row_to_delete = self._get_row_by_tuple_id(operation.tuple_id, snapshot)
                    if not row_to_delete:
                        self.logger.warning(f"[Delete operation] Row {operation.tuple_id} does not exist; skipping delete")
                        continue
                    
                    can_delete, reason = self._can_safely_delete_row(
                        row_to_delete, snapshot, violations, context
                    )
                    
                    if not can_delete:
                        self.logger.warning(
                            f"[Safe delete check] Rejected deletion of row {operation.tuple_id}: {reason}"
                        )
                        self.logger.warning(
                            f"   LLM delete reason: {operation.reason if hasattr(operation, 'reason') else 'N/A'}"
                        )
                        continue
                    else:
                        self.logger.info(
                            f"[Safe delete check] Allowed deletion of row {operation.tuple_id}: {reason}"
                        )
                    
                    row = row_to_delete  # Use the already fetched row
                    if row:
                        pk_field = self._get_primary_key_field(snapshot, context)
                        if pk_field and pk_field in row.cells:
                            old_cell = row.cells.get(pk_field)
                            old_value = old_cell.value if old_cell else None
                            
                            fix_id = IdGenerator.generate_fix_id(
                                snapshot.table, operation.tuple_id, pk_field,
                                FixType.STRUCTURE_FIX.value, old_value
                            )
                            
                            fix = Fix(
                                id=fix_id,
                                table=snapshot.table,
                                tuple_id=operation.tuple_id,
                                attr=pk_field,
                                old=old_value,
                                new="__DELETED__",  # Special value marking deletion
                                fix_type=FixType.STRUCTURE_FIX.value,
                                applied_by=self.mcp_id,
                                timestamp=datetime.now().isoformat(),
                                fix_success=True,
                                failure_reason=operation.reason
                            )
                            fixes.append(fix)
                        else:
                            if row.cells:
                                first_field = list(row.cells.keys())[0]
                                old_cell = row.cells.get(first_field)
                                old_value = old_cell.value if old_cell else None
                                
                                fix_id = IdGenerator.generate_fix_id(
                                    snapshot.table, operation.tuple_id, first_field,
                                    FixType.STRUCTURE_FIX.value, old_value
                                )
                                
                                fix = Fix(
                                    id=fix_id,
                                    table=snapshot.table,
                                    tuple_id=operation.tuple_id,
                                    attr=first_field,
                                    old=old_value,
                                    new="__DELETED__",
                                    fix_type=FixType.STRUCTURE_FIX.value,
                                    applied_by=self.mcp_id,
                                    timestamp=datetime.now().isoformat(),
                                    fix_success=True,
                                    failure_reason=operation.reason
                                )
                                fixes.append(fix)
                    
                elif operation.operation_type == "update":
                    if operation.changes:
                        update_fixes = self._parse_and_create_updates(
                            operation.tuple_id, operation.changes, 
                            snapshot, operation.reason
                        )
                        fixes.extend(update_fixes)
                
                elif operation.operation_type == "merge":
                    merged_record = next(
                        (mr for mr in structure_fix.merged_records 
                         if operation.tuple_id in mr.merged_from or mr.tuple_id == operation.tuple_id),
                        None
                    )
                    if merged_record:
                        merge_fixes = self._create_merge_fixes(
                            merged_record, snapshot, operation.reason
                    )
                    fixes.extend(merge_fixes)
                
                elif operation.operation_type == "keep":
                    continue
                
            except Exception as e:
                self.logger.error(f"Failed to convert fix operation: {e}")
        
        return fixes
    
    def _parse_and_create_updates(self, tuple_id: str, changes: str, 
                                  snapshot: TableSnapshot, reason: str) -> List[Fix]:
        """Parse changes string and create Fix objects"""
        fixes = []
        
        import re
        pattern = r'(\w+):\s*([^-]+?)\s*->\s*([^,]+)'
        matches = re.findall(pattern, changes)
        
        for field_name, old_value, new_value in matches:
            field_name = field_name.strip()
            old_value = old_value.strip()
            new_value = new_value.strip()
            
            fix_id = IdGenerator.generate_fix_id(
                snapshot.table, tuple_id, field_name,
                FixType.STRUCTURE_FIX.value, old_value
            )
            
            fix = Fix(
                id=fix_id,
                table=snapshot.table,
                tuple_id=tuple_id,
                attr=field_name,
                old=old_value if old_value != "NULL" else None,
                new=new_value if new_value != "NULL" else None,
                fix_type=FixType.STRUCTURE_FIX.value,
                applied_by=self.mcp_id,
                timestamp=datetime.now().isoformat(),
                )
            fixes.append(fix)
        
        return fixes
    
    def _create_merge_fixes(self, merged_record, snapshot: TableSnapshot, 
                           reason: str) -> List[Fix]:
        """Create Fix objects for merge operations"""
        fixes = []
        
        try:
            final_data = json.loads(merged_record.final_data)
            
            target_tuple_id = merged_record.tuple_id
            target_row = self._get_row_by_tuple_id(target_tuple_id, snapshot)
            
            if target_row:
                for field_name, new_value in final_data.items():
                    old_cell = target_row.cells.get(field_name)
                    old_value = old_cell.value if old_cell else None
                    
                    if self._is_empty_value(old_value):
                        continue
                    
                    if str(old_value) != str(new_value):
                        fix_id = IdGenerator.generate_fix_id(
                            snapshot.table, target_tuple_id, field_name,
                            FixType.STRUCTURE_FIX.value, old_value
                        )
                        
                        fix = Fix(
                            id=fix_id,
                            table=snapshot.table,
                            tuple_id=target_tuple_id,
                            attr=field_name,
                            old=old_value,
                            new=new_value,
                            fix_type=FixType.STRUCTURE_FIX.value,
                            applied_by=self.mcp_id,
                            timestamp=datetime.now().isoformat(),
                        )
                        fixes.append(fix)
            
        except Exception as e:
            self.logger.error(f"Failed to create merge Fix: {e}")
        
        return fixes


class StructureMCP(BaseMCP):
    """Structure constraint MCP"""
    
    def __init__(self):
        verifier = StructureVerifier()
        fixer = StructureFixer()
        super().__init__("StructureMCP.v1", verifier, fixer)
