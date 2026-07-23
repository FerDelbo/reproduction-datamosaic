"""Logic constraint MCP - use LLM to validate and fix business logic issues"""
import json
import re
import os
from pathlib import Path
from typing import List, Dict, Any, Optional
from .base import MCPVerifier, MCPFixer, BaseMCP, get_table_definition, get_cell_value
from ...memory import TableSnapshot, Violation, Fix, SuggestedFix, ConstraintType, ViolationSeverity, FixType
from ...core.ids import IdGenerator

from llm.main import get_answer


def _extract_json_payload(llm_response: str) -> Optional[str]:
    """Extract a JSON string from an LLM response (supports ```json``` fences and bare JSON)."""
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
    
    arr_match = re.search(r'\[.*\]', llm_response, re.DOTALL)
    if arr_match:
        return arr_match.group(0)
    
    return llm_response.strip()


class BusinessLogicRulesLoader:
    """Business logic rules loader - load rules from a JSON config file"""
    
    def __init__(self, config_path: Optional[str] = None):
        """
        Initialize the rules loader
        
        Args:
            config_path: Config file path; defaults to config/business_logic_rules.json
        """
        self.logger = __import__('logging').getLogger('doc2db.logic_rules')
        
        if config_path is None:
            project_root = Path(__file__).parent.parent.parent.parent
            config_path = project_root / "config" / "business_logic_rules.json"
        
        self.config_path = Path(config_path)
        self.rules = []
        self.default_prompt = "General business table; verify logical consistency of the data"
        
        self._load_rules()
    
    def _load_rules(self):
        """Load business logic rules"""
        try:
            if not self.config_path.exists():
                self.logger.warning(f"Business logic rules config file not found: {self.config_path}")
                return
            
            with open(self.config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            self.rules = config.get('rules', [])
            self.default_prompt = config.get('default_prompt', self.default_prompt)
            
        except Exception as e:
            self.logger.error(f"Failed to load business logic rules: {e}")
    
    def get_applicable_prompts(self, table_name: str, field_names: List[str]) -> List[str]:
        """
        Get applicable validation prompts
        
        Args:
            table_name: Table name
            field_names: List of field names
            
        Returns:
            List of applicable validation prompts
        """
        applicable_prompts = []
        
        table_name_lower = table_name.lower()
        field_names_lower = [f.lower() for f in field_names]
        
        for rule in self.rules:
            if not rule.get('enabled', True):
                continue
            
            triggers = rule.get('triggers', {})
            table_keywords = triggers.get('table_name_keywords', [])
            field_keywords = triggers.get('field_name_keywords', [])
            
            table_matched = any(
                keyword.lower() in table_name_lower 
                for keyword in table_keywords
            )
            
            field_matched = any(
                any(keyword.lower() in field_name for keyword in field_keywords)
                for field_name in field_names_lower
            )
            
            if table_matched or field_matched:
                prompts = rule.get('validation_prompts', [])
                applicable_prompts.extend(prompts)
                self.logger.debug(f"Rule '{rule['name']}' triggered (table match: {table_matched}, field match: {field_matched})")
        
        return applicable_prompts


class LogicVerifier(MCPVerifier):
    """Logic constraint verifier - use LLM for business logic validation"""
    
    def __init__(self):
        super().__init__("LogicVerifier.v1")
        self.enable_llm_validation = True
        
        self.rules_loader = BusinessLogicRulesLoader()
    
    def get_supported_constraints(self) -> List[str]:
        return [ConstraintType.LOGIC.value]
    
    def can_handle(self, constraint_type: str) -> bool:
        return constraint_type == ConstraintType.LOGIC.value
    
    def verify(self, snapshot: TableSnapshot, schema: Dict[str, Any], 
               table_name: str, context=None) -> List[Violation]:
        """Verify logic constraints in the table (table-level and cell-level)"""
        violations = []
        
        if not self.enable_llm_validation:
            return violations
        
        table_def = get_table_definition(schema, table_name)
        if table_def:
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
        
        schema_rule_violations = self._verify_schema_business_rules(
            snapshot, schema, table_name, context
        )
        violations.extend(schema_rule_violations)
        
        llm_violations = self._llm_validate_business_logic(
            snapshot, schema, table_name, context
        )
        violations.extend(llm_violations)
        
        return violations
    
    def verify_cell(self, table: str, tuple_id: str, attr: str, 
                   value: Any, attr_def: Dict[str, Any], 
                   snapshot: TableSnapshot, context=None) -> List[Violation]:
        """Verify logic constraints for a single cell (fast rule-based check)"""
        violations = []
        
        business_rules = attr_def.get('business_rules', [])
        for rule in business_rules:
            if not self._check_business_rule(value, rule):
                violation_id = IdGenerator.generate_violation_id(
                    table, tuple_id, attr, ConstraintType.LOGIC.value
                )
                
                violation = Violation(
                    id=violation_id,
                    table=table,
                    tuple_id=tuple_id,
                    attr=attr,
                    constraint_type=ConstraintType.LOGIC.value,
                    description=f"[Business rule] Field {attr} violates business rule: {rule.get('description', 'unknown rule')}",
                    severity=ViolationSeverity.WARN.value,
                    suggested_fix=None,
                    detector_id=self.mcp_id,
                    timestamp=""
                )
                violations.append(violation)
        
        return violations
    
    def _check_business_rule(self, value: Any, rule: Dict[str, Any]) -> bool:
        """Check business rules"""
        rule_type = rule.get('type', '')
        
        if rule_type == 'pattern':
            pattern = rule.get('pattern', '')
            return re.match(pattern, str(value)) is not None
        
        elif rule_type == 'range':
            try:
                num_value = float(str(value).replace(',', ''))
                min_val = rule.get('min')
                max_val = rule.get('max')
                if min_val is not None and num_value < min_val:
                    return False
                if max_val is not None and num_value > max_val:
                    return False
            except ValueError:
                return False
        
        return True
    
    def _verify_schema_business_rules(self, snapshot: TableSnapshot,
                                      schema: Dict[str, Any],
                                      table_name: str, context=None) -> List[Violation]:
        """Verify business rules defined in the schema"""
        violations = []
        
        business_rules = schema.get('rules', [])
        if not business_rules:
            return violations
        
        self.logger.info(f"[LogicVerifier] Checking {len(business_rules)} business rules in schema...")
        
        for rule in business_rules:
            if not rule.get('enabled', True):
                continue
            
            rule_id = rule.get('id', '')
            rule_name = rule.get('name', '')
            rule_scope = rule.get('scope', 'single_table')
            rule_tables = rule.get('tables', [])
            
            if table_name not in rule_tables:
                continue
            
            self.logger.debug(f"  Validating rule {rule_id} ({rule_name}) - scope: {rule_scope}")
            
            if rule_scope == 'single_table':
                rule_violations = self._verify_single_table_rule(
                    rule, snapshot, schema, table_name, context
                )
                violations.extend(rule_violations)
            elif rule_scope == 'multi_table':
                self.logger.debug(f"    Rule {rule_id} requires multi-table validation; skipping single-table phase")
        
        if violations:
            self.logger.info(f"  Found {len(violations)} business rule violations")
        
        return violations
    
    def _verify_single_table_rule(self, rule: Dict[str, Any],
                                  snapshot: TableSnapshot,
                                  schema: Dict[str, Any],
                                  table_name: str, context=None) -> List[Violation]:
        """Verify single-table business rules"""
        violations = []
        
        rule_id = rule.get('id', '')
        rule_name = rule.get('name', '')
        rule_description = rule.get('description', '')
        validation_logic = rule.get('validation_logic', {})
        
        check_method = validation_logic.get('check_method', '')
        
        if check_method == 'formula':
            violations = self._verify_formula_rule(
                rule, snapshot, schema, table_name, context
            )
        elif check_method == 'llm_validation':
            violations = self._verify_llm_rule(
                rule, snapshot, schema, table_name, context
            )
        else:
            self.logger.warning(f"Unknown validation method: {check_method}")
        
        return violations
    
    def _verify_formula_rule(self, rule: Dict[str, Any],
                            snapshot: TableSnapshot,
                            schema: Dict[str, Any],
                            table_name: str, context=None) -> List[Violation]:
        """Verify formula-based business rules (e.g., phi_2: cash_sanity_bound)"""
        violations = []
        
        rule_id = rule.get('id', '')
        rule_name = rule.get('name', '')
        rule_description = rule.get('description', '')
        validation_logic = rule.get('validation_logic', {})
        severity = rule.get('severity', 'WARN')
        
        formula = validation_logic.get('formula', '')
        required_fields = validation_logic.get('fields', [])
        
        if not formula or not required_fields:
            self.logger.warning(f"Rule {rule_id} is missing formula or field definitions")
            return violations
        
        for row in snapshot.rows:
            field_values = {}
            missing_fields = []
            
            for field in required_fields:
                if field in row.cells:
                    value = row.cells[field].value
                    if value is not None:
                        try:
                            field_values[field] = float(str(value).replace(',', ''))
                        except (ValueError, TypeError):
                            field_values[field] = value
                    else:
                        missing_fields.append(field)
                else:
                    missing_fields.append(field)
            
            if missing_fields:
                continue
            
            try:
                if rule_id == 'phi_2':
                    ending_cash = None
                    beginning_cash = None
                    
                    for field_name, value in row.cells.items():
                        field_lower = field_name.lower()
                        if 'ending' in field_lower or '期末' in field_name or 'end' in field_lower:
                            if 'cash' in field_lower or '现金' in field_name:
                                ending_cash = value.value
                        elif 'beginning' in field_lower or '期初' in field_name or 'begin' in field_lower:
                            if 'cash' in field_lower or '现金' in field_name:
                                beginning_cash = value.value
                    
                    if ending_cash is not None and beginning_cash is not None:
                        try:
                            ending = float(str(ending_cash).replace(',', ''))
                            beginning = float(str(beginning_cash).replace(',', ''))
                            
                            if beginning != 0 and abs(ending / beginning) >= 10:
                                violation_id = IdGenerator.generate_violation_id(
                                    table_name, row.tuple_id, 'cash_flow', ConstraintType.LOGIC.value
                                )
                                
                                violation = Violation(
                                    id=violation_id,
                                    table=table_name,
                                    tuple_id=row.tuple_id,
                                    attr='cash_flow',
                                    constraint_type=ConstraintType.LOGIC.value,
                                    description=f"[{rule_id}] {rule_description} - ending/beginning cash ratio too large: {ending/beginning:.2f}",
                                    severity=severity,
                                    suggested_fix=None,
                                    detector_id=self.mcp_id,
                                    timestamp=""
                                )
                                violation.current_value = f"ratio={ending/beginning:.2f}"
                                violation.business_rule_id = rule_id
                                violations.append(violation)
                        except (ValueError, TypeError, ZeroDivisionError):
                            pass
            
            except Exception as e:
                self.logger.error(f"Failed to evaluate formula rule {rule_id}: {e}")
        
        return violations
    
    def _verify_llm_rule(self, rule: Dict[str, Any],
                        snapshot: TableSnapshot,
                        schema: Dict[str, Any],
                        table_name: str, context=None) -> List[Violation]:
        """Use LLM to validate complex business rules"""
        violations = []
        
        rule_id = rule.get('id', '')
        rule_description = rule.get('description', '')
        validation_logic = rule.get('validation_logic', {})
        severity = rule.get('severity', 'WARN')
        
        try:
            field_definitions = self._build_field_definitions(schema, table_name)
            data_sample = self._build_data_sample(snapshot)
            
            rule_context = f"""
Business rule validation:
- Rule ID: {rule_id}
- Rule description: {rule_description}
- Constraint: {validation_logic.get('constraint', '')}

Verify whether the data satisfies this business rule.
"""
            
            model = context.model if context and hasattr(context, 'model') else "gpt-4o"
            
            self.logger.info(f"[LogicVerifier] Validating rule {rule_id} with LLM...")
            llm_violations_data = self._call_validate_business_logic(
                table_name=table_name,
                field_definitions=field_definitions,
                data_sample=data_sample,
                business_context=rule_context,
                model=model,
            )
            
            llm_violations = self._convert_llm_violations(llm_violations_data, table_name)
            for violation in llm_violations:
                violation.business_rule_id = rule_id
            
            violations.extend(llm_violations)
            
        except Exception as e:
            self.logger.error(f"LLM validation failed for rule {rule_id}: {e}")
        
        return violations
    
    def verify_multi_table_business_rules(self, all_snapshots: Dict[str, TableSnapshot],
                                         schema: Dict[str, Any],
                                         context=None) -> List[Violation]:
        """Verify multi-table business rules (e.g., phi_1 mutual investment ban, phi_3 recursive investment)"""
        violations = []
        
        business_rules = schema.get('rules', [])
        if not business_rules:
            return violations
        
        self.logger.info(f"[LogicVerifier] Checking multi-table business rules...")
        
        for rule in business_rules:
            if not rule.get('enabled', True):
                continue
            
            rule_id = rule.get('id', '')
            rule_name = rule.get('name', '')
            rule_scope = rule.get('scope', 'single_table')
            
            if rule_scope != 'multi_table':
                continue
            
            self.logger.debug(f"  Validating multi-table rule {rule_id} ({rule_name})")
            
            if rule_id == 'phi_1':
                rule_violations = self._verify_no_mutual_investment(
                    rule, all_snapshots, schema, context
                )
                violations.extend(rule_violations)
            
            elif rule_id == 'phi_3':
                rule_violations = self._verify_recursive_investment(
                    rule, all_snapshots, schema, context
                )
                violations.extend(rule_violations)
        
        if violations:
            self.logger.info(f"  Multi-table rules found {len(violations)} violations")
        
        return violations
    
    def _verify_no_mutual_investment(self, rule: Dict[str, Any],
                                     all_snapshots: Dict[str, TableSnapshot],
                                     schema: Dict[str, Any],
                                     context=None) -> List[Violation]:
        """Verify phi_1: mutual investment prohibition rule"""
        violations = []
        
        rule_id = rule.get('id', '')
        rule_description = rule.get('description', '')
        severity = rule.get('severity', 'ERROR')
        
        investment_table_names = ['company_report', '公司_报告']
        investment_snapshot = None
        investment_table_name = None
        
        for tname in investment_table_names:
            if tname in all_snapshots:
                investment_snapshot = all_snapshots[tname]
                investment_table_name = tname
                break
        
        if not investment_snapshot:
            self.logger.debug(f"  Investment relationship table not found; skipping phi_1 validation")
            return violations
        
        investments = {}
        for row in investment_snapshot.rows:
            cells = row.cells
            
            investor = None
            investee = None
            
            for field_name in cells.keys():
                if 'company' in field_name.lower() or '公司' in field_name:
                    if investor is None:
                        investor = cells[field_name].value
                    elif investee is None:
                        investee = cells[field_name].value
            
            if investor and investee:
                if investor not in investments:
                    investments[investor] = set()
                investments[investor].add(investee)
        
        checked_pairs = set()
        for investor, investees in investments.items():
            for investee in investees:
                pair = tuple(sorted([investor, investee]))
                if pair in checked_pairs:
                    continue
                checked_pairs.add(pair)
                
                if investee in investments and investor in investments[investee]:
                    violation_id = IdGenerator.generate_violation_id(
                        investment_table_name, 'MULTI_TABLE', 'mutual_investment', ConstraintType.LOGIC.value
                    )
                    
                    violation = Violation(
                        id=violation_id,
                        table=investment_table_name,
                        tuple_id='MULTI_TABLE',
                        attr='mutual_investment',
                        constraint_type=ConstraintType.LOGIC.value,
                        description=f"[{rule_id}] {rule_description} - mutual investment found: {investor} ⇄ {investee}",
                        severity=severity,
                        suggested_fix=None,
                        detector_id=self.mcp_id,
                        timestamp=""
                    )
                    violation.current_value = f"{investor} ⇄ {investee}"
                    violation.business_rule_id = rule_id
                    violations.append(violation)
        
        return violations
    
    def _verify_recursive_investment(self, rule: Dict[str, Any],
                                    all_snapshots: Dict[str, TableSnapshot],
                                    schema: Dict[str, Any],
                                    context=None) -> List[Violation]:
        """Verify phi_3: recursive investment rule (transitive closure)"""
        violations = []
        
        rule_id = rule.get('id', '')
        rule_description = rule.get('description', '')
        severity = rule.get('severity', 'WARN')
        
        investment_table_names = ['company_report', '公司_报告']
        investment_snapshot = None
        investment_table_name = None
        
        for tname in investment_table_names:
            if tname in all_snapshots:
                investment_snapshot = all_snapshots[tname]
                investment_table_name = tname
                break
        
        if not investment_snapshot:
            return violations
        
        investments = {}
        for row in investment_snapshot.rows:
            cells = row.cells
            
            investor = None
            investee = None
            
            for field_name in cells.keys():
                if 'company' in field_name.lower() or '公司' in field_name:
                    if investor is None:
                        investor = cells[field_name].value
                    elif investee is None:
                        investee = cells[field_name].value
            
            if investor and investee:
                if investor not in investments:
                    investments[investor] = set()
                investments[investor].add(investee)
        
        all_companies = set(investments.keys())
        for investee_set in investments.values():
            all_companies.update(investee_set)
        
        for a in all_companies:
            if a not in investments:
                continue
            
            for b in investments[a]:
                if b not in investments:
                    continue
                
                for c in investments[b]:
                    if c != a and (a not in investments or c not in investments[a]):
                        violation_id = IdGenerator.generate_violation_id(
                            investment_table_name, 'MULTI_TABLE', 'transitive_investment', ConstraintType.LOGIC.value
                        )
                        
                        violation = Violation(
                            id=violation_id,
                            table=investment_table_name,
                            tuple_id='MULTI_TABLE',
                            attr='transitive_investment',
                            constraint_type=ConstraintType.LOGIC.value,
                            description=f"[{rule_id}] {rule_description} - missing transitive investment: {a}→{b}→{c}, but {a}→{c} not recorded",
                            severity=severity,
                            suggested_fix=SuggestedFix(value=f"Add investment relationship: {a} → {c}"),
                            detector_id=self.mcp_id,
                            timestamp=""
                        )
                        violation.current_value = f"{a}→{b}→{c}"
                        violation.business_rule_id = rule_id
                        violations.append(violation)
        
        return violations
    
    def _llm_validate_business_logic(self, snapshot: TableSnapshot, 
                                    schema: Dict[str, Any], 
                                    table_name: str, context=None) -> List[Violation]:
        """Use LLM for business logic validation"""
        violations = []
        
        try:
            field_definitions = self._build_field_definitions(schema, table_name)
            data_sample = self._build_data_sample(snapshot)
            business_context = self._infer_business_context(table_name, snapshot)
            
            model = context.model if context and hasattr(context, 'model') else "gpt-4o"
            
            self.logger.info(f"[LogicVerifier] Calling LLM for business logic validation (model={model})...")
            llm_violations_data = self._call_validate_business_logic(
                table_name=table_name,
                field_definitions=field_definitions,
                data_sample=data_sample,
                business_context=business_context,
                model=model,
            )
            
            llm_violations = self._convert_llm_violations(llm_violations_data, table_name)
            violations.extend(llm_violations)
            
        except Exception as e:
            self.logger.error(f"LLM business logic validation failed: {e}")
        
        return violations
    
    def _call_validate_business_logic(self, table_name: str, field_definitions: str,
                                       data_sample: str, business_context: str,
                                       model: str) -> List[Dict[str, Any]]:
        """Call LLM directly for business logic validation and return a list of violation dicts."""
        system_prompt = (
            "You are a data quality and business logic validation expert. "
            "Output strictly in the specified JSON format with no extra explanation or Markdown fences."
        )
        
        user_prompt = f"""Based on the business context and data below, analyze whether any business logic issues exist.

=== Table info ===
Table: {table_name}

Field definitions:
{field_definitions}

=== Data content ===
{data_sample}

=== Business context ===
{business_context}

Validation focus:
1. Business rule consistency - verify data follows common business rules
2. Inter-field logic - verify relationships between related fields are reasonable
3. Value plausibility - verify values fall within reasonable business ranges
4. State transition logic - verify status values follow business workflows
5. Calculation logic - verify calculated fields are correct
6. Business constraints - verify no business constraints are violated

Important: for suggested_fix:
- Must be a concrete data value that can directly replace the original (number, date, text, etc.)
- Do not use descriptive text (e.g. "please check", "suggested change")
- Set to null if a concrete fix value cannot be determined

Output format (JSON only, no other content):
{{
  "violations": [
    {{
      "tuple_id": "row ID",
      "attr": "field name",
      "problem_type": "issue type",
      "description": "issue description",
      "severity": "error | warn | info",
      "suggested_fix": "concrete fix value or null"
    }}
  ]
}}

If no issues are found, return {{"violations": []}}.
"""
        
        try:
            llm_response = get_answer(user_prompt, system_prompt=system_prompt, model=model)
        except Exception as e:
            self.logger.error(f"LLM call failed: {e}")
            return []
        
        return self._parse_violations_response(llm_response)
    
    @staticmethod
    def _parse_violations_response(llm_response: str) -> List[Dict[str, Any]]:
        """Parse the violation list from an LLM response."""
        json_str = _extract_json_payload(llm_response)
        if not json_str:
            return []
        
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            return []
        
        if isinstance(data, dict):
            items = data.get('violations', [])
        elif isinstance(data, list):
            items = data
        else:
            return []
        
        return [item for item in items if isinstance(item, dict)]
    
    def _convert_llm_violations(self, llm_violations: List[Dict[str, Any]], 
                                 table_name: str) -> List[Violation]:
        """Convert LLM violation dicts into system Violation objects."""
        violations = []
        
        for item in llm_violations:
            try:
                tuple_id = str(item.get('tuple_id', '')).strip('[]')
                attr = item.get('attr', '')
                description = item.get('description', 'business logic issue')
                severity = item.get('severity') or 'warn'
                suggested_fix_value = item.get('suggested_fix')
                
                if not attr:
                    continue
                
                violation_id = IdGenerator.generate_violation_id(
                    table_name,
                    tuple_id,
                    attr,
                    ConstraintType.LOGIC.value
                )
                
                suggested_fix = None
                if suggested_fix_value is not None and str(suggested_fix_value).strip():
                    suggested_fix = SuggestedFix(value=str(suggested_fix_value))
                
                violation = Violation(
                    id=violation_id,
                    table=table_name,
                    tuple_id=tuple_id,
                    attr=attr,
                    constraint_type=ConstraintType.LOGIC.value,
                    description=f"[Business logic] {description}",
                    severity=severity,
                    suggested_fix=suggested_fix,
                    detector_id=self.mcp_id,
                    timestamp=""
                )
                violations.append(violation)
                
            except Exception as ve:
                self.logger.error(f"Error converting violation item: {ve}")
                continue
        
        return violations
    
    def _build_field_definitions(self, schema: Dict[str, Any], table_name: str) -> str:
        """Build field definition string"""
        table_def = get_table_definition(schema, table_name)
        if not table_def:
            return ""
        
        attributes = table_def.get('attributes', [])
        field_lines = []
        
        for attr in attributes:
            field_info = f"- {attr['name']}"
            if 'type' in attr:
                field_info += f" ({attr['type']})"
            if 'description' in attr:
                field_info += f": {attr['description']}"
            
            constraints = []
            if attr.get('required'):
                constraints.append("required")
            if 'domain' in attr:
                constraints.append(f"allowed values: {attr['domain']}")
            if 'min' in attr or 'max' in attr:
                range_info = []
                if 'min' in attr:
                    range_info.append(f"min: {attr['min']}")
                if 'max' in attr:
                    range_info.append(f"max: {attr['max']}")
                constraints.append(f"range: {', '.join(range_info)}")
            
            if constraints:
                field_info += f" [constraints: {' | '.join(constraints)}]"
            
            field_lines.append(field_info)
        
        return "\n".join(field_lines)
    
    def _build_data_sample(self, snapshot: TableSnapshot) -> str:
        """Build data sample string"""
        sample_lines = [f"Total rows: {len(snapshot.rows)}"]
        
        max_rows = min(10, len(snapshot.rows))
        for i, row in enumerate(snapshot.rows[:max_rows]):
            row_data = []
            for attr, cell in row.cells.items():
                value = cell.value
                row_data.append(f"{attr}: {value}")
            
            sample_lines.append(f"Row {i+1} [{row.tuple_id}]: {', '.join(row_data)}")
        
        if len(snapshot.rows) > max_rows:
            sample_lines.append(f"... {len(snapshot.rows) - max_rows} more rows")
        
        return "\n".join(sample_lines)
    
    def _build_logic_validation_context(self, snapshot: TableSnapshot, 
                                       schema: Dict[str, Any], 
                                       table_name: str) -> str:
        """Build business logic validation context"""
        context_parts = []
        
        context_parts.append(f"=== Table info ===")
        context_parts.append(f"Table: {table_name}")
        
        table_def = get_table_definition(schema, table_name)
        if table_def:
            attributes = table_def.get('attributes', [])
            context_parts.append(f"\nField definitions:")
            for attr in attributes:
                field_info = f"- {attr['name']}"
                if 'type' in attr:
                    field_info += f" ({attr['type']})"
                if 'description' in attr:
                    field_info += f": {attr['description']}"
                
                constraints = []
                if attr.get('required'):
                    constraints.append("required")
                if 'domain' in attr:
                    constraints.append(f"allowed values: {attr['domain']}")
                if 'min' in attr or 'max' in attr:
                    range_info = []
                    if 'min' in attr:
                        range_info.append(f"min: {attr['min']}")
                    if 'max' in attr:
                        range_info.append(f"max: {attr['max']}")
                    constraints.append(f"range: {', '.join(range_info)}")
                
                if constraints:
                    field_info += f" [constraints: {' | '.join(constraints)}]"
                
                context_parts.append(field_info)
        
        context_parts.append(f"\n=== Data content ===")
        context_parts.append(f"Total rows: {len(snapshot.rows)}")
        
        max_rows = min(10, len(snapshot.rows))
        for i, row in enumerate(snapshot.rows[:max_rows]):
            row_data = []
            for attr, cell in row.cells.items():
                value = cell.value
                row_data.append(f"{attr}: {value}")
            
            context_parts.append(f"Row {i+1} [{row.tuple_id}]: {', '.join(row_data)}")
        
        if len(snapshot.rows) > max_rows:
            context_parts.append(f"... {len(snapshot.rows) - max_rows} more rows")
        
        context_parts.append(f"\n=== Business context ===")
        business_context = self._infer_business_context(table_name, snapshot)
        context_parts.append(business_context)
        
        return "\n".join(context_parts)
    
    def _infer_business_context(self, table_name: str, snapshot: TableSnapshot) -> str:
        """Infer business scenario context using rules from the config file"""
        field_names = []
        if len(snapshot.rows) > 0:
            field_names = list(snapshot.rows[0].cells.keys())
        
        applicable_prompts = self.rules_loader.get_applicable_prompts(table_name, field_names)
        
        if not applicable_prompts:
            applicable_prompts = [self.rules_loader.default_prompt]
        
        return "\n".join([f"- {prompt}" for prompt in applicable_prompts])
    
    def _parse_llm_logic_response(self, llm_response: str, table_name: str) -> List[Violation]:
        """Parse LLM business logic validation response"""
        violations = []
        
        try:
            if not llm_response or not llm_response.strip():
                self.logger.warning("LLM returned empty response")
                return violations
            
            json_str = None
            
            json_match = re.search(r'```json\s*(\{.*?\}|\[.*?\])\s*```', llm_response, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
            else:
                json_match = re.search(r'```\s*(\{.*?\}|\[.*?\])\s*```', llm_response, re.DOTALL)
                if json_match:
                    json_str = json_match.group(1)
                else:
                    json_match = re.search(r'\{.*?"violations".*?\}', llm_response, re.DOTALL)
                    if json_match:
                        json_str = json_match.group(0)
                    else:
                        json_match = re.search(r'\[\s*\]', llm_response)
                        if json_match:
                            json_str = json_match.group(0)
                        else:
                            json_str = llm_response.strip()
            
            if not json_str or not json_str.strip():
                self.logger.warning("Could not extract valid JSON content")
                return violations
            
            data = json.loads(json_str)
            
            if isinstance(data, dict):
                llm_violations = data.get('violations', [])
            elif isinstance(data, list):
                llm_violations = data
            else:
                self.logger.warning(f"Unsupported JSON parse result format: {type(data)}")
                return violations
            
            if not isinstance(llm_violations, list):
                self.logger.warning(f"violations data is not a list: {type(llm_violations)}")
                return violations
            
            for i, viol_data in enumerate(llm_violations):
                try:
                    if not isinstance(viol_data, dict):
                        self.logger.warning(f"Violation item {i} is not a dict: {type(viol_data)}")
                        continue
                    
                    tuple_id_raw = viol_data.get('tuple_id', '')
                    tuple_id = tuple_id_raw.strip('[]')
                    
                    violation_id = IdGenerator.generate_violation_id(
                        table_name, 
                        tuple_id,
                        viol_data.get('attr', ''),
                        ConstraintType.LOGIC.value
                    )
                    
                    suggested_fix = None
                    if viol_data.get('suggested_fix'):
                        suggested_fix = SuggestedFix(
                            value=viol_data['suggested_fix']
                        )
                    
                    violation = Violation(
                        id=violation_id,
                        table=table_name,
                        tuple_id=tuple_id,  # Use cleaned tuple_id
                        attr=viol_data.get('attr', ''),
                        constraint_type=ConstraintType.LOGIC.value,
                        description=f"[Business logic] {viol_data.get('description', 'business logic issue')}",
                        severity=viol_data.get('severity', 'warn'),
                        suggested_fix=suggested_fix,
                        detector_id=self.mcp_id,
                        timestamp=""
                    )
                    violations.append(violation)
                    
                except Exception as ve:
                    self.logger.error(f"Error processing violation item {i}: {ve}")
                    continue
                
        except json.JSONDecodeError as e:
            self.logger.error(f"JSON parsing failed: {e}")
            response_length = len(json_str) if 'json_str' in locals() else len(llm_response)
            self.logger.error("Unable to parse LLM response (length=%d)", response_length)
            
            if 'json_str' in locals() and json_str:
                try:
                    fixed_violations = self._attempt_json_repair(json_str, llm_response, table_name)
                    violations.extend(fixed_violations)
                except Exception as repair_error:
                    self.logger.error(f"JSON repair failed: {repair_error}")
            
        except (KeyError, ValueError, TypeError) as e:
            self.logger.error(f"Failed to parse LLM business logic validation response: {e}")
        except Exception as e:
            self.logger.error(f"Unknown error: {e}")
        
        return violations
    
    def _attempt_json_repair(self, json_str: str, original_response: str, table_name: str = "tax") -> List[Violation]:
        """Attempt to repair corrupted JSON and parse violations"""
        violations = []
        
        try:
            if json_str.startswith('{') and not json_str.endswith('}'):
                violations_pattern = r'"violations"\s*:\s*\[(.*?)\]'
                match = re.search(violations_pattern, original_response, re.DOTALL)
                if match:
                    violations_content = match.group(1)
                    repaired_json = f'{{"violations": [{violations_content}]}}'
                    self.logger.info("Attempting to repair incomplete JSON object")
                    data = json.loads(repaired_json)
                    return self._process_violations_data(data.get('violations', []), table_name)
            
            violations_items = re.findall(r'\{[^}]*"tuple_id"[^}]*\}', original_response, re.DOTALL)
            if violations_items:
                for item_str in violations_items:
                    try:
                        item_data = json.loads(item_str)
                        violation = self._create_violation_from_data(item_data, table_name)
                        if violation:
                            violations.append(violation)
                    except:
                        continue
            
            return violations
            
        except Exception as e:
            self.logger.error(f"JSON repair attempt failed: {e}")
            return []
    
    def _process_violations_data(self, violations_data: List[Dict], table_name: str) -> List[Violation]:
        """Process violations data and convert to Violation objects"""
        violations = []
        for i, viol_data in enumerate(violations_data):
            try:
                violation = self._create_violation_from_data(viol_data, table_name)
                if violation:
                    violations.append(violation)
            except Exception as ve:
                self.logger.error(f"Error processing violation item {i}: {ve}")
                continue
        return violations
    
    def _create_violation_from_data(self, viol_data: Dict, table_name: str) -> Optional[Violation]:
        """Create a Violation object from data"""
        try:
            tuple_id_raw = viol_data.get('tuple_id', '')
            tuple_id = tuple_id_raw.strip('[]')  # Remove square brackets
            attr = viol_data.get('attr', '')
            description = viol_data.get('description', '')
            
            if not tuple_id or not attr:
                return None
            
            suggested_fix_text = viol_data.get('suggested_fix', '')
            suggested_fix = SuggestedFix(
                value=suggested_fix_text
            ) if suggested_fix_text else None
            
            violation = Violation(
                id=IdGenerator.generate_violation_id(
                    table_name, tuple_id, attr, ConstraintType.LOGIC.value
                ),
                table=table_name,
                tuple_id=tuple_id,
                attr=attr,
                constraint_type=ConstraintType.LOGIC.value,
                description=description,
                severity=ViolationSeverity.WARN.value,  # Default to warning
                suggested_fix=suggested_fix,
                detector_id=self.verifier_id,
                timestamp=""
            )
            
            return violation
            
        except Exception as e:
            self.logger.error(f"Failed to create Violation object: {e}")
            return None


class LogicFixer(MCPFixer):
    """Logic constraint fixer - use LLM for business logic fixes"""
    
    def __init__(self):
        super().__init__("LogicFixer.v1")
        self.enable_llm_fixing = True
        
        self.format_standards = {
            '季度': '第一季度',  # Use full Chinese name format consistently
            '税额': '亿元'       # Use hundred-million yuan unit consistently
        }
        self.applied_fixes_memory = {}  # Track applied fixes to avoid repeated repairs
        
        self.rules_loader = BusinessLogicRulesLoader()
    
    def get_supported_constraints(self) -> List[str]:
        return [ConstraintType.LOGIC.value]
    
    def can_handle(self, constraint_type: str) -> bool:
        return constraint_type == ConstraintType.LOGIC.value
    
    def can_fix(self, violation: Violation) -> bool:
        return (violation.constraint_type == ConstraintType.LOGIC.value and 
                self.enable_llm_fixing)
    
    def get_supported_fix_types(self) -> List[str]:
        return [
            FixType.LOGIC_FIX.value,
            FixType.BUSINESS_RULE_FIX.value,
            FixType.CALCULATION_FIX.value
        ]
    
    def fix(self, violation: Violation, snapshot: TableSnapshot, 
            context=None) -> List[Fix]:
        """Fix logic constraint violations"""
        if not self.can_fix(violation):
            return []
        
        fixes = []
        
        violation_key = f"{violation.attr}_{violation.tuple_id}"
        if violation_key in self.applied_fixes_memory:
            return []
        
        
        standard_fix = self._apply_standard_format(violation, snapshot)
        if standard_fix:
            fixes.append(standard_fix)
            self.applied_fixes_memory[violation_key] = standard_fix.new
        else:
            llm_fixes = self._llm_fix_logic_violation(violation, snapshot, context)
            fixes.extend(llm_fixes)
            for fix in llm_fixes:
                fix_key = f"{fix.attr}_{fix.tuple_id}"
                self.applied_fixes_memory[fix_key] = fix.new
        
        return fixes
    
    def _apply_standard_format(self, violation: Violation, snapshot: TableSnapshot) -> Optional[Fix]:
        """Apply predefined standard format fixes"""
        try:
            old_value = get_cell_value(violation, snapshot)
            if not old_value:
                return None
            
            attr_name = violation.attr
            new_value = None
            
            if attr_name == '季度':
                new_value = self._standardize_quarter_format(old_value)
            
            elif attr_name == '税额':
                new_value = self._standardize_amount_format(old_value)
            
            if new_value and new_value != old_value:
                fix_id = IdGenerator.generate_fix_id(
                    violation.table, violation.tuple_id, violation.attr,
                    FixType.LOGIC_FIX.value, old_value
                )
                
                fix = Fix(
                    id=fix_id,
                    table=violation.table,
                    tuple_id=violation.tuple_id,
                    attr=violation.attr,
                    old=old_value,
                    new=new_value,
                    fix_type=FixType.LOGIC_FIX.value,
                    applied_by=f"{self.mcp_id}_standard",
                    timestamp=""
                )
                
                return fix
                
        except Exception as e:
            self.logger.error(f"Standard format fix failed: {e}")
        
        return None
    
    def _standardize_quarter_format(self, value: str) -> Optional[str]:
        """Normalize quarter format to full Chinese name"""
        if not value:
            return None
        
        value = str(value).strip()
        value_lower = value.lower()
        
        if value_lower in ['q1', 'quarter 1', '1q', '一季度']:
            return '第一季度'
        elif value_lower in ['q2', 'quarter 2', '2q', '二季度']:
            return '第二季度'
        elif value_lower in ['q3', 'quarter 3', '3q', '三季度']:
            return '第三季度'
        elif value_lower in ['q4', 'quarter 4', '4q', '四季度']:
            return '第四季度'
        elif '第一季度' in value:
            return '第一季度'
        elif '第二季度' in value:
            return '第二季度'
        elif '第三季度' in value:
            return '第三季度'
        elif '第四季度' in value:
            return '第四季度'
        
        return None
    
    def _standardize_amount_format(self, value: str) -> Optional[str]:
        """Normalize amount format and ensure a unit is present"""
        if not value:
            return None
        
        value = str(value).strip()
        
        import re
        
        if re.match(r'^\d+(\.\d+)?\s+亿$', value):
            return value.replace(' ', '') + '元'
        
        if value.endswith('亿人民币'):
            return value.replace('亿人民币', '亿元')
        
        if value.endswith('亿') and not value.endswith('亿元'):
            return value + '元'
        
        if re.match(r'^\d+(\.\d+)?$', value):
            return value + '亿元'
        
        if re.match(r'^\d+(\.\d+)?亿.+', value) and not value.endswith('亿元'):
            number_match = re.match(r'^(\d+(?:\.\d+)?)亿', value)
            if number_match:
                number_part = number_match.group(1)
                return f"{number_part}亿元"
        
        return None
    
    def _build_fix_consistency_rules(self, violation: Violation, snapshot: TableSnapshot) -> str:
        """
        Dynamically build fix rules for the current table and fields
        Include only relevant rules to avoid unnecessary prompts
        """
        field_names = []
        if len(snapshot.rows) > 0:
            field_names = list(snapshot.rows[0].cells.keys())
        
        applicable_prompts = self.rules_loader.get_applicable_prompts(
            violation.table, 
            field_names
        )
        
        if applicable_prompts:
            rules_text = "Data normalization rules (for this table only):\n"
            
            for prompt in applicable_prompts:
                rules_text += f"- {prompt}\n"
            
            return rules_text
        else:
            return "Data normalization rules:\n- Maintain data consistency and accuracy\n"
    
    def _llm_fix_logic_violation(self, violation: Violation, snapshot: TableSnapshot, 
                                context=None) -> List[Fix]:
        """Use LLM to fix business logic violations"""
        fixes = []
        
        try:
            old_value = get_cell_value(violation, snapshot)
            
            target_row_data = self._get_target_row_data(violation, snapshot)
            reference_samples = self._get_reference_samples(violation, snapshot)
            
            consistency_rules = self._build_fix_consistency_rules(violation, snapshot)
            
            universal_constraints = """
**Important constraints**:
1. When fixing, use **only information explicitly present in the document**
2. **Do not derive, calculate, or invent any values** (e.g. do not compute age from birth date or infer values from other fields)
3. **Do not** add information from common knowledge or external sources (addresses, postal codes, phone numbers, etc.)
4. If the document has no explicit value for a field, **keep it null**; do not attempt a fix
5. For location and similar fields, use only what the document explicitly states
6. Do not speculate; if uncertain, do not fix
7. **When the current value is null and the document provides no explicit value, new_value must be null**
"""
            
            consistency_rules += "\n" + universal_constraints
            
            model = context.model if context and hasattr(context, 'model') else "gpt-4o"
            
            self.logger.info(f"[LogicFixer] Calling LLM to fix field {violation.attr} (model={model})...")
            llm_fix_data = self._call_fix_business_logic(
                table_name=violation.table,
                field_name=violation.attr,
                problem_description=violation.description,
                current_value=str(old_value),
                target_row_data=target_row_data,
                reference_samples=reference_samples,
                consistency_rules=consistency_rules,
                model=model,
            )
            
            llm_fix = self._convert_llm_fix(llm_fix_data, violation, old_value, context)
            if llm_fix:
                fixes.append(llm_fix)
                
        except Exception as e:
            self.logger.error(f"LLM business logic fix failed: {e}")
        
        return fixes
    
    def _call_fix_business_logic(self, table_name: str, field_name: str,
                                  problem_description: str, current_value: str,
                                  target_row_data: str, reference_samples: str,
                                  consistency_rules: str, model: str) -> Dict[str, Any]:
        """Call LLM to generate a business logic fix plan and return a dict."""
        system_prompt = (
            "You are a data repair expert. "
            "Output strictly in the specified JSON format with no extra explanation or Markdown fences."
        )
        
        user_prompt = f"""Provide an appropriate fix for the following business logic issue.

{consistency_rules}

Violation details:
- Table: {table_name}
- Field: {field_name}
- Problem: {problem_description}
- Current value: {current_value}

Target row data:
{target_row_data}

Reference samples:
{reference_samples}

Fix principles:
1. Strictly follow the data normalization rules above
2. Preserve correct business semantics
3. **Do not derive, calculate, or invent any values**
4. **Use only values explicitly present in the document**
5. Ensure the fixed format matches normalization rules
6. **If the document has no explicit value for this field, return null; do not attempt a fix**
7. **Do not infer values from other fields (e.g. do not compute age from birth date)**

If no explicit fix value can be found in the document, set new_value to null.

Output format (JSON only, no other content):
{{
  "new_value": "fixed value, or null if unfixable",
  "fix_type": "logic_fix | business_rule_fix | calculation_fix",
  "reasoning": "fix rationale"
}}
"""
        
        try:
            llm_response = get_answer(user_prompt, system_prompt=system_prompt, model=model)
        except Exception as e:
            self.logger.error(f"LLM call failed: {e}")
            return {}
        
        return self._parse_fix_response(llm_response)
    
    @staticmethod
    def _parse_fix_response(llm_response: str) -> Dict[str, Any]:
        """Parse the fix plan dict from an LLM response."""
        json_str = _extract_json_payload(llm_response)
        if not json_str:
            return {}
        
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            return {}
        
        if isinstance(data, dict):
            return data
        return {}
    
    def _get_target_row_data(self, violation: Violation, snapshot: TableSnapshot) -> str:
        """Get complete data for the target row"""
        target_row = None
        for row in snapshot.rows:
            if row.tuple_id == violation.tuple_id:
                target_row = row
                break
        
        if not target_row:
            return ""
        
        row_parts = []
        for attr, cell in target_row.cells.items():
            value = cell.value
            row_parts.append(f"{attr}: {value}")
        
        return "\n".join(row_parts)
    
    def _get_reference_samples(self, violation: Violation, snapshot: TableSnapshot) -> str:
        """Get reference data samples"""
        other_rows = [row for row in snapshot.rows[:5] if row.tuple_id != violation.tuple_id]
        if not other_rows:
            return ""
        
        sample_parts = []
        for i, row in enumerate(other_rows):
            row_data = []
            for attr, cell in row.cells.items():
                value = cell.value
                row_data.append(f"{attr}: {value}")
            sample_parts.append(f"Sample {i+1}: {', '.join(row_data)}")
        
        return "\n".join(sample_parts)
    
    def _mark_unfixable(self, violation: Violation, context):
        """Mark a violation as unfixable"""
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
            
            if memory_manager and run_id:
                import asyncio
                
                try:
                    loop = asyncio.get_running_loop()
                    asyncio.create_task(
                        memory_manager.mark_violation_unfixable(violation.id, run_id)
                    )
                    self.logger.debug(f"Marked violation {violation.id} as unfixable (async)")
                except RuntimeError:
                    asyncio.run(memory_manager.mark_violation_unfixable(violation.id, run_id))
                    self.logger.debug(f"Marked violation {violation.id} as unfixable")
            else:
                self.logger.debug(f"Cannot mark violation {violation.id} as unfixable: context missing memory_manager or run_id")
        except Exception as e:
            self.logger.error(f"Failed to mark violation {violation.id} as unfixable: {e}")
            import traceback
            traceback.print_exc()
    
    def _convert_llm_fix(self, llm_fix: Dict[str, Any], violation: Violation, 
                         old_value: Any, context=None) -> Optional[Fix]:
        """Convert LLM fix dicts into system Fix objects."""
        try:
            raw_new_value = llm_fix.get('new_value') if llm_fix else None
            reasoning = llm_fix.get('reasoning', '') if llm_fix else ''
            
            new_value = None if raw_new_value is None else str(raw_new_value).strip()
            if not new_value or new_value.lower() == 'null':
                self.logger.info(f"Cannot fix this issue: {violation.id} (reason: {reasoning})")
                self._mark_unfixable(violation, context)
                return None
            
            fix_type_map = {
                'logic_fix': FixType.LOGIC_FIX.value,
                'business_rule_fix': FixType.BUSINESS_RULE_FIX.value,
                'calculation_fix': FixType.CALCULATION_FIX.value,
            }
            
            raw_fix_type = (llm_fix.get('fix_type') or '').lower() if llm_fix else ''
            fix_type = fix_type_map.get(raw_fix_type, FixType.LOGIC_FIX.value)
            
            fix_id = IdGenerator.generate_fix_id(
                violation.table, violation.tuple_id, violation.attr,
                fix_type, old_value
            )
            
            fix = Fix(
                id=fix_id,
                table=violation.table,
                tuple_id=violation.tuple_id,
                attr=violation.attr,
                old=old_value,
                new=new_value,
                fix_type=fix_type,
                applied_by=f"{self.mcp_id}_llm",
                timestamp=""
            )
            
            return fix
            
        except Exception as e:
            self.logger.error(f"Failed to convert LLM fix response: {e}")
            return None
    
    def _build_logic_fix_context(self, violation: Violation, snapshot: TableSnapshot) -> str:
        """Build business logic fix context"""
        context_parts = []
        
        target_row = None
        for row in snapshot.rows:
            if row.tuple_id == violation.tuple_id:
                target_row = row
                break
        
        if target_row:
            context_parts.append("Target row data:")
            for attr, cell in target_row.cells.items():
                value = cell.value
                context_parts.append(f"  {attr}: {value}")
        
        other_rows = [row for row in snapshot.rows[:5] if row.tuple_id != violation.tuple_id]
        if other_rows:
            context_parts.append("\nReference data samples:")
            for i, row in enumerate(other_rows):
                row_data = []
                for attr, cell in row.cells.items():
                    value = cell.value
                    row_data.append(f"{attr}: {value}")
                context_parts.append(f"  Sample {i+1}: {', '.join(row_data)}")
        
        return "\n".join(context_parts)
    
    def _parse_llm_logic_fix_response(self, llm_response: str, violation: Violation, 
                                     old_value: Any) -> Optional[Fix]:
        """Parse LLM business logic fix response"""
        try:
            if not llm_response or not llm_response.strip():
                self.logger.warning("LLM returned empty fix response")
                return None
            
            json_str = None
            
            json_match = re.search(r'```json\s*(\{.*?\}|\[.*?\])\s*```', llm_response, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
            else:
                json_match = re.search(r'```\s*(\{.*?\}|\[.*?\])\s*```', llm_response, re.DOTALL)
                if json_match:
                    json_str = json_match.group(1)
                else:
                    json_match = re.search(r'\{.*?"fix".*?\}', llm_response, re.DOTALL)
                    if json_match:
                        json_str = json_match.group(0)
                    else:
                        json_str = llm_response.strip()
            
            if not json_str or not json_str.strip():
                self.logger.warning("Could not extract valid fix JSON content")
                return None
            
            data = json.loads(json_str)
            
            if not isinstance(data, dict):
                self.logger.warning(f"Fix JSON parse result is not a dict: {type(data)}")
                return None
                
            fix_data = data.get('fix')
            
            if fix_data is None:
                self.logger.info("LLM indicates this issue cannot be fixed")
                return None
            
            if not isinstance(fix_data, dict):
                self.logger.warning(f"fix field is not a dict: {type(fix_data)}")
                return None
            
            new_value = fix_data.get('new_value')
            if new_value is None:
                self.logger.warning("Fix data missing new_value field")
                return None
            
            fix_type_map = {
                'logic_fix': FixType.LOGIC_FIX.value,
                'business_rule_fix': FixType.BUSINESS_RULE_FIX.value,
                'calculation_fix': FixType.CALCULATION_FIX.value,
            }
            
            fix_type = fix_type_map.get(
                fix_data.get('fix_type', '').lower(), 
                FixType.LOGIC_FIX.value
            )
            
            fix_id = IdGenerator.generate_fix_id(
                violation.table, violation.tuple_id, violation.attr,
                fix_type, old_value
            )
            
            fix = Fix(
                id=fix_id,
                table=violation.table,
                tuple_id=violation.tuple_id,
                attr=violation.attr,
                old=old_value,
                new=new_value,
                fix_type=fix_type,
                applied_by=f"{self.mcp_id}_llm",
                timestamp=""
            )
            
            return fix
            
        except json.JSONDecodeError as e:
            self.logger.error(f"Fix JSON parsing failed: {e}")
            response_length = len(json_str) if 'json_str' in locals() else len(llm_response)
            self.logger.error("Unable to parse LLM response (length=%d)", response_length)
            return None
        except (KeyError, ValueError, TypeError) as e:
            self.logger.error(f"Failed to parse LLM business logic fix response: {e}")
            return None
        except Exception as e:
            self.logger.error(f"Unknown error while parsing fix response: {e}")
            return None
    
    def fix_batch(self, violations: List[Violation], snapshot: TableSnapshot, 
                  context=None) -> List[Fix]:
        """
        Batch-fix logic constraint violations
        
        Strategy:
        1. Apply standard format fixes first (no LLM)
        2. Batch-process violations that require LLM
        """
        all_fixes = []
        
        standard_violations = []
        need_llm_violations = []
        
        for violation in violations:
            if not self.can_fix(violation):
                continue
            
            violation_key = f"{violation.attr}_{violation.tuple_id}"
            if violation_key in self.applied_fixes_memory:
                continue
            
            attr_name = violation.attr
            if attr_name in self.format_standards:
                standard_violations.append(violation)
            else:
                need_llm_violations.append(violation)
        
        for violation in standard_violations:
            standard_fix = self._apply_standard_format(violation, snapshot)
            if standard_fix:
                all_fixes.append(standard_fix)
                violation_key = f"{violation.attr}_{violation.tuple_id}"
                self.applied_fixes_memory[violation_key] = standard_fix.new
        
        if need_llm_violations:
            llm_fixes = self._batch_fix_with_llm(need_llm_violations, snapshot, context)
            all_fixes.extend(llm_fixes)
            for fix in llm_fixes:
                fix_key = f"{fix.attr}_{fix.tuple_id}"
                self.applied_fixes_memory[fix_key] = fix.new
        
        if all_fixes:
            self.logger.info(f"LogicFixer: batch-fixed {len(violations)} violations, generated {len(all_fixes)} fixes")
        
        return all_fixes
    
    def _batch_fix_with_llm(self, violations: List[Violation], 
                           snapshot: TableSnapshot, context=None) -> List[Fix]:
        """
        Batch-fix business logic violations with LLM
        
        Core optimization: merge all violations into one prompt so the LLM returns all fixes at once
        """
        if not violations:
            return []
        
        fixes = []
        table_name = violations[0].table
        
        violations_info = []
        for i, violation in enumerate(violations):
            old_value = get_cell_value(violation, snapshot)
            target_row_data = self._get_target_row_data(violation, snapshot)
            
            violations_info.append(f"""
[Violation {i+1}]
- violation_id: {violation.id}
- tuple_id: {violation.tuple_id}
- field: {violation.attr}
- problem: {violation.description}
- current_value: {old_value}
- row_data:
{target_row_data}
""")
        
        reference_samples = self._get_reference_samples(violations[0], snapshot)
        consistency_rules = self._build_fix_consistency_rules(violations[0], snapshot)
        
        universal_constraints = """
**Important constraints**:
1. When fixing, use **only information explicitly present in the document**
2. **Do not derive, calculate, or invent any values**
3. **Do not** add information from common knowledge or external sources
4. If the document has no explicit value for a field, **keep it null**
5. **When the current value is null and the document provides no explicit value, new_value must be null**
"""
        
        user_prompt = f"""Task: batch-fix business logic violations in table [{table_name}]

[Violations to fix] {len(violations)} total
{''.join(violations_info)}

[Reference samples]
{reference_samples}

[Consistency rules]
{consistency_rules}
{universal_constraints}

[Output format] Return strictly in this JSON format:
```json
{{
  "fixes": [
    {{
      "violation_id": "v-xxx",
      "tuple_id": "...",
      "field": "...",
      "new_value": "...",  // null if unfixable
      "reasoning": "fix reason or reason it cannot be fixed",
      "can_fix": true  // or false
    }}
  ]
}}
```

Analyze all violations and output all fix suggestions at once.
"""
        
        system_prompt = """You are a data quality expert specializing in fixing business logic violations.
Your task is to analyze ALL violations and provide fixes for each one based ONLY on explicitly provided information in the documents.
Output in strict JSON format."""
        
        try:
            model = context.model if context and hasattr(context, 'model') else "gpt-4o"
            
            self.logger.info(f"[LogicFixer] Batch fixing {len(violations)} violations (model={model})...")
            
            from llm.main import get_answer
            llm_response = get_answer(user_prompt, system_prompt=system_prompt, model=model)
            
            fixes = self._parse_batch_llm_response(llm_response, violations, snapshot, context)
            
            self.logger.info(f"[LogicFixer] Batch fix complete, generated {len(fixes)} fixes")
            
        except Exception as e:
            self.logger.error(f"[LogicFixer] Batch LLM fix failed: {e}")
            self.logger.info("Falling back to one-by-one fix mode...")
            for violation in violations:
                try:
                    individual_fixes = self._llm_fix_logic_violation(violation, snapshot, context)
                    fixes.extend(individual_fixes)
                except Exception as ve:
                    self.logger.error(f"Failed to fix violation {violation.id}: {ve}")
        
        return fixes
    
    def _parse_batch_llm_response(self, llm_response: str, violations: List[Violation],
                                  snapshot: TableSnapshot, context) -> List[Fix]:
        """Parse batch LLM response"""
        fixes = []
        
        try:
            json_str = None
            json_match = re.search(r'```json\s*(\{.*?\})\s*```', llm_response, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
            else:
                json_match = re.search(r'```\s*(\{.*?\})\s*```', llm_response, re.DOTALL)
                if json_match:
                    json_str = json_match.group(1)
                else:
                    json_match = re.search(r'\{.*?"fixes".*?\}', llm_response, re.DOTALL)
                    if json_match:
                        json_str = json_match.group(0)
            
            if not json_str:
                self.logger.warning("Could not extract JSON from LLM response")
                return fixes
            
            data = json.loads(json_str)
            fixes_data = data.get('fixes', [])
            
            violation_map = {v.id: v for v in violations}
            
            for fix_data in fixes_data:
                try:
                    violation_id = fix_data.get('violation_id')
                    if not violation_id or violation_id not in violation_map:
                        self.logger.warning(f"Invalid violation_id: {violation_id}")
                        continue
                    
                    violation = violation_map[violation_id]
                    can_fix = fix_data.get('can_fix', True)
                    new_value = fix_data.get('new_value')
                    reasoning = fix_data.get('reasoning', '')
                    
                    if not can_fix or new_value is None or str(new_value).strip() == "":
                        self.logger.info(f"Cannot fix this issue: {violation_id} (reason: {reasoning})")
                        self._mark_unfixable(violation, context)
                        continue
                    
                    old_value = get_cell_value(violation, snapshot)
                    
                    fix = Fix(
                        id=IdGenerator.generate_fix_id(
                            violation.table, 
                            violation.tuple_id, 
                            violation.attr,
                            FixType.LOGIC_FIX.value, 
                            old_value
                        ),
                        table=violation.table,
                        tuple_id=violation.tuple_id,
                        attr=violation.attr,
                        old=old_value,
                        new=new_value,
                        fix_type=FixType.LOGIC_FIX.value,
                        applied_by=f"{self.mcp_id}_batch_llm",
                        timestamp=""
                    )
                    fixes.append(fix)
                    
                except Exception as e:
                    self.logger.error(f"Failed to process fix data: {e}")
                    continue
            
        except json.JSONDecodeError as e:
            self.logger.error(f"JSON parsing failed: {e}")
        except Exception as e:
            self.logger.error(f"Failed to parse batch LLM response: {e}")
        
        return fixes


class LogicMCP(BaseMCP):
    """Logic constraint MCP"""
    
    def __init__(self):
        verifier = LogicVerifier()
        fixer = LogicFixer()
        super().__init__("LogicMCP.v1", verifier, fixer)
