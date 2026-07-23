"""Aggregation constraint MCP - validate and fix aggregation-related issues"""
import json
import re
import os
import logging
from typing import List, Dict, Any, Optional
from .base import MCPVerifier, MCPFixer, BaseMCP, get_table_definition, get_cell_value, is_valid_fix_value
from ...memory import TableSnapshot, Violation, Fix, SuggestedFix, ConstraintType, ViolationSeverity, FixType
from ...core.ids import IdGenerator

import sys
sys.path.append(os.path.join(os.path.dirname(__file__), '../../../..'))
from llm.main import get_answer


class AggregationVerifier(MCPVerifier):
    """Aggregation constraint verifier"""
    
    def __init__(self, config_path: str = None):
        super().__init__("AggregationVerifier.v1")
        self.enable_llm_validation = True
        
        if config_path is None:
            config_path = os.path.join(
                os.path.dirname(__file__), 
                'config', 
                'aggregation_rules.json'
            )
        
        self.config = self._load_config(config_path)
        self.aggregation_keywords = self.config.get('aggregation_keywords', {})
        self.calculation_types = self.config.get('calculation_types', {})
    
    def _load_config(self, config_path: str) -> Dict[str, Any]:
        """Load aggregation rule configuration from a JSON file"""
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            self.logger.warning(f"Config file not found: {config_path}; using defaults")
            return {}
        except json.JSONDecodeError as e:
            self.logger.error(f"Failed to parse config file: {e}; using defaults")
            return {}
    
    def get_supported_constraints(self) -> List[str]:
        return [ConstraintType.AGGREGATION.value]
    
    def can_handle(self, constraint_type: str) -> bool:
        return constraint_type == ConstraintType.AGGREGATION.value
    
    def verify(self, snapshot: TableSnapshot, schema: Dict[str, Any], 
               table_name: str, context=None) -> List[Violation]:
        """Verify aggregation constraints in the table"""
        violations = []
        
        algo_violations = self._verify_algorithmic_aggregation(
            snapshot, schema, table_name, context
        )
        violations.extend(algo_violations)
        
        schema_rule_violations = self._verify_schema_aggregation_rules(
            snapshot, schema, table_name, context
        )
        violations.extend(schema_rule_violations)
        
        if self.enable_llm_validation:
            llm_violations = self._llm_validate_aggregation(
                snapshot, schema, table_name, context
            )
            violations.extend(llm_violations)
        
        return violations
    
    def verify_cell(self, table: str, tuple_id: str, attr: str, 
                   value: Any, attr_def: Dict[str, Any], 
                   snapshot: TableSnapshot, context=None) -> List[Violation]:
        """Verify aggregation constraints for a single cell"""
        violations = []
        
        if attr_def.get('calculated', False):
            calc_violations = self._verify_calculated_field(
                table, tuple_id, attr, value, attr_def, snapshot
            )
            violations.extend(calc_violations)
        
        return violations
    
    def _verify_algorithmic_aggregation(self, snapshot: TableSnapshot, 
                                       schema: Dict[str, Any], 
                                       table_name: str, context=None) -> List[Violation]:
        """Verify algorithmically detectable aggregation constraints"""
        violations = []
        table_def = get_table_definition(schema, table_name)
        
        if not table_def:
            return violations
        
        attributes = table_def.get('attributes', [])
        
        for row in snapshot.rows:
            for attr_def in attributes:
                attr_name = attr_def['name']
                if attr_name in row.cells and attr_def.get('calculated', False):
                    value = row.cells[attr_name].value
                    
                    calc_violations = self._verify_calculated_field(
                        snapshot.table, row.tuple_id, attr_name, 
                        value, attr_def, snapshot
                    )
                    violations.extend(calc_violations)
        
        table_violations = self._verify_table_aggregation(
            snapshot, table_def, table_name
        )
        violations.extend(table_violations)
        
        return violations
    
    def _verify_calculated_field(self, table: str, tuple_id: str, attr: str, 
                                value: Any, attr_def: Dict[str, Any], 
                                snapshot: TableSnapshot) -> List[Violation]:
        """Verify calculated fields"""
        violations = []
        
        calculation = attr_def.get('calculation')
        if not calculation:
            return violations
        
        target_row = None
        for row in snapshot.rows:
            if row.tuple_id == tuple_id:
                target_row = row
                break
        
        if not target_row:
            return violations
        
        expected_value = self._calculate_expected_value(calculation, target_row)
        
        if expected_value is not None and value is not None:
            try:
                actual_value = float(str(value).replace(',', ''))
                expected_float = float(expected_value)
                
                tolerance = 0.01
                if abs(actual_value - expected_float) > tolerance:
                    violation_id = IdGenerator.generate_violation_id(
                        table, tuple_id, attr, ConstraintType.AGGREGATION.value
                    )
                    
                    violation = Violation(
                        id=violation_id,
                        table=table,
                        tuple_id=tuple_id,
                        attr=attr,
                        constraint_type=ConstraintType.AGGREGATION.value,
                        description=f"Calculated field {attr} value {value} is incorrect; expected {expected_value}",
                        severity=ViolationSeverity.ERROR.value,
                        
                        suggested_fix=SuggestedFix(value=str(expected_value), ),
                        detector_id=self.mcp_id,
                        timestamp=""
                    )
                    violations.append(violation)
                    
            except (ValueError, TypeError):
                pass
        
        return violations
    
    def _calculate_expected_value(self, calculation: Dict[str, Any], row) -> Optional[float]:
        """Calculate the expected value"""
        calc_type = calculation.get('type')
        
        if calc_type == 'sum':
            fields = calculation.get('fields', [])
            total = 0
            for field in fields:
                if field in row.cells:
                    try:
                        value = row.cells[field].value
                        if value is not None:
                            total += float(str(value).replace(',', ''))
                    except (ValueError, TypeError):
                        return None
            return total
        
        elif calc_type == 'multiply':
            fields = calculation.get('fields', [])
            if len(fields) < 2:
                return None
            
            result = 1
            for field in fields:
                if field in row.cells:
                    try:
                        value = row.cells[field].value
                        if value is not None:
                            result *= float(str(value).replace(',', ''))
                        else:
                            return None
                    except (ValueError, TypeError):
                        return None
                else:
                    return None
            return result
        
        elif calc_type == 'percentage':
            numerator_field = calculation.get('numerator')
            denominator_field = calculation.get('denominator')
            
            if not numerator_field or not denominator_field:
                return None
            
            try:
                numerator = row.cells.get(numerator_field)
                denominator = row.cells.get(denominator_field)
                
                if numerator and denominator:
                    num_val = float(str(numerator.value).replace(',', ''))
                    den_val = float(str(denominator.value).replace(',', ''))
                    
                    if den_val != 0:
                        return (num_val / den_val) * 100
                    
            except (ValueError, TypeError, AttributeError):
                return None
        
        return None
    
    def _verify_table_aggregation(self, snapshot: TableSnapshot, 
                                 table_def: Dict[str, Any], 
                                 table_name: str) -> List[Violation]:
        """Verify table-level aggregation constraints"""
        violations = []
        
        total_violations = self._check_total_fields(snapshot, table_def, table_name)
        violations.extend(total_violations)
        
        avg_violations = self._check_average_fields(snapshot, table_def, table_name)
        violations.extend(avg_violations)
        
        return violations
    
    def _check_total_fields(self, snapshot: TableSnapshot, 
                           table_def: Dict[str, Any], 
                           table_name: str) -> List[Violation]:
        """Check total fields"""
        violations = []
        
        total_keywords = self.aggregation_keywords.get('total', ['总计', 'total', '合计', 'sum'])
        
        total_rows = []
        for row in snapshot.rows:
            for attr, cell in row.cells.items():
                value = str(cell.value).lower()
                if any(keyword in value for keyword in total_keywords):
                    total_rows.append(row)
                    break
        
        if not total_rows:
            return violations
        
        for total_row in total_rows:
            for attr, cell in total_row.cells.items():
                try:
                    total_value = float(str(cell.value).replace(',', ''))
                    
                    calculated_total = 0
                    count = 0
                    
                    for row in snapshot.rows:
                        if row.tuple_id != total_row.tuple_id and attr in row.cells:
                            try:
                                value = row.cells[attr].value
                                if value is not None:
                                    num_value = float(str(value).replace(',', ''))
                                    calculated_total += num_value
                                    count += 1
                            except (ValueError, TypeError):
                                continue
                    
                    if count > 0 and abs(total_value - calculated_total) > 0.01:
                        violation_id = IdGenerator.generate_violation_id(
                            table_name, total_row.tuple_id, attr, ConstraintType.AGGREGATION.value
                        )
                        
                        violation = Violation(
                            id=violation_id,
                            table=table_name,
                            tuple_id=total_row.tuple_id,
                            attr=attr,
                            constraint_type=ConstraintType.AGGREGATION.value,
                            description=f"Total field {attr} value {total_value} is incorrect; calculated value is {calculated_total}",
                            severity=ViolationSeverity.ERROR.value,
                            
                            suggested_fix=SuggestedFix(value=str(calculated_total), ),
                            detector_id=self.mcp_id,
                            timestamp=""
                        )
                        violations.append(violation)
                        
                except (ValueError, TypeError):
                    continue
        
        return violations
    
    def _check_average_fields(self, snapshot: TableSnapshot, 
                             table_def: Dict[str, Any], 
                             table_name: str) -> List[Violation]:
        """Check average fields"""
        violations = []
        
        avg_keywords = self.aggregation_keywords.get('average', ['平均', 'average', 'avg', '均值'])
        
        avg_rows = []
        for row in snapshot.rows:
            for attr, cell in row.cells.items():
                value = str(cell.value).lower()
                if any(keyword in value for keyword in avg_keywords):
                    avg_rows.append(row)
                    break
        
        if not avg_rows:
            return violations
        
        for avg_row in avg_rows:
            for attr, cell in avg_row.cells.items():
                try:
                    avg_value = float(str(cell.value).replace(',', ''))
                    
                    total = 0
                    count = 0
                    
                    for row in snapshot.rows:
                        if row.tuple_id != avg_row.tuple_id and attr in row.cells:
                            try:
                                value = row.cells[attr].value
                                if value is not None:
                                    num_value = float(str(value).replace(',', ''))
                                    total += num_value
                                    count += 1
                            except (ValueError, TypeError):
                                continue
                    
                    if count > 0:
                        calculated_avg = total / count
                        if abs(avg_value - calculated_avg) > 0.01:
                            violation_id = IdGenerator.generate_violation_id(
                                table_name, avg_row.tuple_id, attr, ConstraintType.AGGREGATION.value
                            )
                            
                            violation = Violation(
                                id=violation_id,
                                table=table_name,
                                tuple_id=avg_row.tuple_id,
                                attr=attr,
                                constraint_type=ConstraintType.AGGREGATION.value,
                                description=f"Average field {attr} value {avg_value} is incorrect; calculated value is {calculated_avg:.2f}",
                                severity=ViolationSeverity.ERROR.value,
                                
                                suggested_fix=SuggestedFix(value=f"{calculated_avg:.2f}", ),
                                detector_id=self.mcp_id,
                                timestamp=""
                            )
                            violations.append(violation)
                            
                except (ValueError, TypeError):
                    continue
        
        return violations
    
    def _verify_schema_aggregation_rules(self, snapshot: TableSnapshot,
                                         schema: Dict[str, Any],
                                         table_name: str, context=None) -> List[Violation]:
        """Verify aggregation rules defined in the schema"""
        violations = []
        
        rules = schema.get('rules', [])
        if not rules:
            return violations
        
        self.logger.info(f"[AggregationVerifier] Checking aggregation rules in schema...")
        
        for rule in rules:
            if not rule.get('enabled', True):
                continue
            
            rule_type = rule.get('type', '')
            if rule_type != 'AGGREGATION':
                continue
            
            rule_id = rule.get('id', '')
            rule_name = rule.get('name', '')
            rule_tables = rule.get('tables', [])
            
            if table_name not in rule_tables:
                continue
            
            self.logger.debug(f"  Validating aggregation rule {rule_id} ({rule_name})")
            
            rule_scope = rule.get('scope', 'single_table')
            
            if rule_scope == 'single_table':
                rule_violations = self._verify_single_table_aggregation_rule(
                    rule, snapshot, schema, table_name, context
                )
                violations.extend(rule_violations)
            elif rule_scope == 'multi_table':
                self.logger.debug(f"    Rule {rule_id} requires multi-table validation; skipping single-table phase")
        
        if violations:
            self.logger.info(f"  Found {len(violations)} aggregation rule violations")
        
        return violations
    
    def _verify_single_table_aggregation_rule(self, rule: Dict[str, Any],
                                             snapshot: TableSnapshot,
                                             schema: Dict[str, Any],
                                             table_name: str, context=None) -> List[Violation]:
        """Verify single-table aggregation rules (e.g., agg_2: course capacity limit)"""
        violations = []
        
        rule_id = rule.get('id', '')
        rule_description = rule.get('description', '')
        validation_logic = rule.get('validation_logic', {})
        severity = rule.get('severity', 'ERROR')
        
        aggregation_type = validation_logic.get('aggregation_type', '')
        group_by = validation_logic.get('group_by', '')
        max_value = validation_logic.get('max_value')
        
        if not group_by or max_value is None:
            self.logger.warning(f"Rule {rule_id} is missing required validation parameters")
            return violations
        
        group_counts = {}
        for row in snapshot.rows:
            if group_by in row.cells:
                group_key = row.cells[group_by].value
                if group_key:
                    if group_key not in group_counts:
                        group_counts[group_key] = []
                    group_counts[group_key].append(row.tuple_id)
        
        for group_key, tuple_ids in group_counts.items():
            if aggregation_type == 'count':
                actual_count = len(tuple_ids)
                if actual_count > max_value:
                    violation_id = IdGenerator.generate_violation_id(
                        table_name, 'AGGREGATION_' + str(group_key), group_by, ConstraintType.AGGREGATION.value
                    )
                    
                    violation = Violation(
                        id=violation_id,
                        table=table_name,
                        tuple_id='AGGREGATION_' + str(group_key),
                        attr=group_by,
                        constraint_type=ConstraintType.AGGREGATION.value,
                        description=f"[{rule_id}] {rule_description} - {group_by}={group_key} exceeds limit: actual {actual_count}, max {max_value}",
                        severity=severity,
                        suggested_fix=None,
                        detector_id=self.mcp_id,
                        timestamp=""
                    )
                    violation.current_value = f"count={actual_count}"
                    violation.business_rule_id = rule_id
                    violation.affected_tuple_ids = tuple_ids  # Record all affected tuple_ids
                    violations.append(violation)
        
        return violations
    
    def verify_multi_table_aggregation_rules(self, all_snapshots: Dict[str, TableSnapshot],
                                            schema: Dict[str, Any],
                                            context=None) -> List[Violation]:
        """Verify multi-table aggregation rules (e.g., agg_1: student credit limit)"""
        violations = []
        
        rules = schema.get('rules', [])
        if not rules:
            return violations
        
        self.logger.info(f"[AggregationVerifier] Checking multi-table aggregation rules...")
        
        for rule in rules:
            if not rule.get('enabled', True):
                continue
            
            rule_type = rule.get('type', '')
            if rule_type != 'AGGREGATION':
                continue
            
            rule_scope = rule.get('scope', 'single_table')
            if rule_scope != 'multi_table':
                continue
            
            rule_id = rule.get('id', '')
            rule_name = rule.get('name', '')
            
            self.logger.debug(f"  Validating multi-table aggregation rule {rule_id} ({rule_name})")
            
            if rule_id == 'agg_1':
                rule_violations = self._verify_student_credit_limit(
                    rule, all_snapshots, schema, context
                )
                violations.extend(rule_violations)
        
        if violations:
            self.logger.info(f"  Multi-table aggregation rules found {len(violations)} violations")
        
        return violations
    
    def _verify_student_credit_limit(self, rule: Dict[str, Any],
                                    all_snapshots: Dict[str, TableSnapshot],
                                    schema: Dict[str, Any],
                                    context=None) -> List[Violation]:
        """Verify agg_1: student course credit limit"""
        violations = []
        
        rule_id = rule.get('id', '')
        rule_description = rule.get('description', '')
        severity = rule.get('severity', 'ERROR')
        validation_logic = rule.get('validation_logic', {})
        
        max_credits = validation_logic.get('max_value', 12)
        
        course_offering_snapshot = all_snapshots.get('CourseOffering')
        course_snapshot = all_snapshots.get('Course')
        
        if not course_offering_snapshot or not course_snapshot:
            self.logger.debug(f"  CourseOffering or Course table not found; skipping agg_1 validation")
            return violations
        
        course_credits = {}
        for row in course_snapshot.rows:
            course_id = row.cells.get('ID')
            credit = row.cells.get('Credit')
            if course_id and credit:
                course_credits[str(course_id.value)] = credit.value
        
        student_credits = {}
        student_courses = {}  # Track each student's enrolled courses for detailed reporting
        
        for row in course_offering_snapshot.rows:
            student_id = row.cells.get('StudentID')
            course_id = row.cells.get('CourseID')
            
            if student_id and course_id:
                student_id_str = str(student_id.value)
                course_id_str = str(course_id.value)
                
                if course_id_str in course_credits:
                    credit = course_credits[course_id_str]
                    try:
                        credit_value = float(str(credit).replace(',', ''))
                        
                        if student_id_str not in student_credits:
                            student_credits[student_id_str] = 0
                            student_courses[student_id_str] = []
                        
                        student_credits[student_id_str] += credit_value
                        student_courses[student_id_str].append((course_id_str, credit_value, row.tuple_id))
                    except (ValueError, TypeError):
                        continue
        
        for student_id, total_credits in student_credits.items():
            if total_credits > max_credits:
                violation_id = IdGenerator.generate_violation_id(
                    'CourseOffering', 'STUDENT_' + student_id, 'StudentID', ConstraintType.AGGREGATION.value
                )
                
                affected_tuple_ids = [tid for _, _, tid in student_courses[student_id]]
                
                violation = Violation(
                    id=violation_id,
                    table='CourseOffering',
                    tuple_id='STUDENT_' + student_id,
                    attr='StudentID',
                    constraint_type=ConstraintType.AGGREGATION.value,
                    description=f"[{rule_id}] {rule_description} - student {student_id} total credits exceed limit: actual {total_credits}, max {max_credits}",
                    severity=severity,
                    suggested_fix=None,
                    detector_id=self.mcp_id,
                    timestamp=""
                )
                violation.current_value = f"total_credits={total_credits}"
                violation.business_rule_id = rule_id
                violation.affected_tuple_ids = affected_tuple_ids
                violations.append(violation)
        
        return violations
    
    def _llm_validate_aggregation(self, snapshot: TableSnapshot, 
                                 schema: Dict[str, Any], 
                                 table_name: str, context=None) -> List[Violation]:
        """Use LLM to validate complex aggregation logic"""
        violations = []
        
        try:
            aggregation_context = self._build_aggregation_context(
                snapshot, schema, table_name
            )
            
            system_prompt = """You are a professional data aggregation validation expert skilled at finding errors in aggregation calculations."""
            
            prompt = f"""
Analyze aggregation calculation issues in the table data below.

{aggregation_context}

Validation focus:
1. Whether total rows are calculated correctly
2. Whether averages are accurate
3. Whether percentage calculations are reasonable
4. Logical consistency of summary data
5. Correctness of grouped aggregations
6. Formula validation for calculated fields

Return issues in this format:
{{
  "violations": [
    {{
      "tuple_id": "row ID",
      "attr": "field name",
      "problem_type": "aggregation",
      "description": "issue description",
      "severity": "error/warn/info",
      "suggested_fix": "concrete fix value (if any)"
    }}
  ]
}}

Important:
- suggested_fix must be a concrete data value (number, date, etc.), not descriptive text
- If no concrete fix can be determined, set suggested_fix to null or an empty string
- Do not use prompt-like text such as "please check" or "suggested change" in suggested_fix
- suggested_fix should be a value that can directly replace the original

Examples:
Correct: "suggested_fix": "12345.67"
Correct: "suggested_fix": "2024-03-15"
Correct: "suggested_fix": null
Incorrect: "suggested_fix": "Confirm whether data should be deduplicated or whether multiple records are intentional."
Incorrect: "suggested_fix": "Suggested change to correct format"

If no issues are found, return an empty array.
"""
            
            model = context.model if context and hasattr(context, 'model') else "gpt-4o"
            llm_response = get_answer(prompt, system_prompt=system_prompt, model=model)
            
            llm_violations = self._parse_llm_aggregation_response(llm_response, table_name)
            violations.extend(llm_violations)
            
        except Exception as e:
            self.logger.error(f"LLM aggregation validation failed: {e}")
        
        return violations
    
    def _build_aggregation_context(self, snapshot: TableSnapshot, 
                                  schema: Dict[str, Any], 
                                  table_name: str) -> str:
        """Build aggregation validation context"""
        context_parts = []
        
        context_parts.append(f"=== Table info ===")
        context_parts.append(f"Table: {table_name}")
        context_parts.append(f"Total rows: {len(snapshot.rows)}")
        
        table_def = get_table_definition(schema, table_name)
        if table_def:
            attributes = table_def.get('attributes', [])
            context_parts.append(f"\nField definitions:")
            for attr in attributes:
                field_info = f"- {attr['name']}"
                if 'type' in attr:
                    field_info += f" ({attr['type']})"
                if attr.get('calculated'):
                    field_info += " [calculated field]"
                if 'description' in attr:
                    field_info += f": {attr['description']}"
                context_parts.append(field_info)
        
        context_parts.append(f"\n=== Data content ===")
        for i, row in enumerate(snapshot.rows):
            row_data = []
            for attr, cell in row.cells.items():
                value = cell.value
                row_data.append(f"{attr}: {value}")
            
            context_parts.append(f"Row {i+1} [{row.tuple_id}]: {', '.join(row_data)}")
        
        return "\n".join(context_parts)
    
    def _parse_llm_aggregation_response(self, llm_response: str, table_name: str) -> List[Violation]:
        """Parse LLM aggregation validation response"""
        violations = []
        
        try:
            if not llm_response or not llm_response.strip():
                return violations
            
            json_match = re.search(r'```json\s*(\{.*?\})\s*```', llm_response, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
            else:
                json_str = llm_response.strip()
            
            if not json_str:
                return violations
            
            data = json.loads(json_str)
            llm_violations = data.get('violations', [])
            
            for viol_data in llm_violations:
                violation_id = IdGenerator.generate_violation_id(
                    table_name, 
                    viol_data.get('tuple_id', ''),
                    viol_data.get('attr', ''),
                    ConstraintType.AGGREGATION.value
                )
                
                suggested_fix = None
                if viol_data.get('suggested_fix'):
                    suggested_fix = SuggestedFix(
                        value=viol_data['suggested_fix'],

                    )
                
                violation = Violation(
                    id=violation_id,
                    table=table_name,
                    tuple_id=viol_data.get('tuple_id', ''),
                    attr=viol_data.get('attr', ''),
                    constraint_type=ConstraintType.AGGREGATION.value,
                    description=f"[Aggregation validation] {viol_data.get('description', 'aggregation calculation issue')}",
                    severity=viol_data.get('severity', 'warn'),

                    suggested_fix=suggested_fix,
                    detector_id=self.mcp_id,
                    timestamp=""
                )
                violations.append(violation)
                
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            self.logger.error(f"Failed to parse LLM aggregation validation response: {e}")
        
        return violations


class AggregationFixer(MCPFixer):
    """Aggregation constraint fixer"""
    
    def __init__(self, config_path: str = None):
        super().__init__("AggregationFixer.v1")
        
        if config_path is None:
            config_path = os.path.join(
                os.path.dirname(__file__), 
                'config', 
                'aggregation_rules.json'
            )
        
        self.config = self._load_config(config_path)
        self.field_fix_rules = self.config.get('field_fix_rules', {})
    
    def _load_config(self, config_path: str) -> Dict[str, Any]:
        """Load aggregation rule configuration from a JSON file"""
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            self.logger.warning(f"Config file not found: {config_path}; using defaults")
            return {}
        except json.JSONDecodeError as e:
            self.logger.error(f"Failed to parse config file: {e}; using defaults")
            return {}
    
    def get_supported_constraints(self) -> List[str]:
        return [ConstraintType.AGGREGATION.value]
    
    def can_handle(self, constraint_type: str) -> bool:
        return constraint_type == ConstraintType.AGGREGATION.value
    
    def can_fix(self, violation: Violation) -> bool:
        return violation.constraint_type == ConstraintType.AGGREGATION.value
    
    def get_supported_fix_types(self) -> List[str]:
        return [
            FixType.CALCULATION_FIX.value,
            FixType.AGGREGATION_FIX.value
        ]
    
    def fix(self, violation: Violation, snapshot: TableSnapshot, 
            context=None) -> List[Fix]:
        """Fix aggregation constraint violations"""
        if not self.can_fix(violation):
            return []
        
        fixes = []
        old_value = get_cell_value(violation, snapshot)
        
        if not old_value:
            return fixes
        
        new_value = None
        
        if violation.suggested_fix and violation.suggested_fix.value:
            suggested_value = violation.suggested_fix.value
            if is_valid_fix_value(suggested_value):
                new_value = suggested_value
            else:
                self.logger.warning(f"Suggested fix value '{suggested_value}' looks like prompt text rather than a data value; ignoring and attempting auto-generated fix")
                new_value = self._generate_aggregation_fix(violation, old_value, snapshot)
        else:
            new_value = self._generate_aggregation_fix(violation, old_value, snapshot)
        
        if new_value and new_value != old_value:
            fix_id = IdGenerator.generate_fix_id(
                violation.table, violation.tuple_id, violation.attr,
                FixType.AGGREGATION_FIX.value, old_value
            )
            
            fix = Fix(
                id=fix_id,
                table=violation.table,
                tuple_id=violation.tuple_id,
                attr=violation.attr,
                old=old_value,
                new=new_value,
                fix_type=FixType.AGGREGATION_FIX.value,
                applied_by=self.mcp_id,
                timestamp=""
            )
            fixes.append(fix)
            self.logger.info("Aggregation fix applied to attribute %s", violation.attr)
        
        return fixes
    
    def _generate_aggregation_fix(self, violation: Violation, old_value: str, 
                                 snapshot: TableSnapshot) -> Optional[str]:
        """Automatically generate fixes for aggregation issues"""
        try:
            attr = violation.attr
            
            if attr not in self.field_fix_rules:
                return None
            
            field_rule = self.field_fix_rules[attr]
            fix_type = field_rule.get('type')
            
            if fix_type == 'amount_unit':
                return self._fix_amount_unit_consistency(old_value, snapshot, attr, field_rule)
            elif fix_type == 'quarter_format':
                return self._fix_quarter_format_consistency(old_value, snapshot, attr, field_rule)
            
            return None
            
        except Exception as e:
            self.logger.error(f"Failed to generate aggregation fix: {e}")
            return None
    
    def _fix_amount_unit_consistency(self, old_value: str, snapshot: TableSnapshot, 
                                   attr: str, field_rule: Dict[str, Any]) -> Optional[str]:
        """Fix tax amount unit consistency issues"""
        target_format = field_rule.get('target_format', '亿元')
        conversion_rules = field_rule.get('conversion_rules', [])
        
        for rule in conversion_rules:
            pattern = rule['pattern']
            action = rule['action']
            
            match = re.match(pattern, old_value)
            if match:
                number = match.group(1)
                
                if action == 'remove_space_add_yuan':
                    return f"{number}亿元"
                elif action == 'replace_renminbi_with_yuan':
                    return f"{number}亿元"
                elif action == 'add_yuan':
                    return f"{number}亿元"
                elif action == 'add_yi_yuan':
                    return f"{number}亿元"
        
        return None
    
    def _fix_quarter_format_consistency(self, old_value: str, snapshot: TableSnapshot, 
                                      attr: str, field_rule: Dict[str, Any]) -> Optional[str]:
        """Fix quarter format consistency issues"""
        mapping = field_rule.get('mapping', {})
        standard_values = field_rule.get('standard_values', [])
        
        if old_value.lower() in mapping:
            return mapping[old_value.lower()]
        
        for quarter in standard_values:
            if quarter in old_value:
                return quarter
        
        return None


class AggregationMCP(BaseMCP):
    """Aggregation constraint MCP"""
    
    def __init__(self):
        verifier = AggregationVerifier()
        fixer = AggregationFixer()
        super().__init__("AggregationMCP.v1", verifier, fixer)
