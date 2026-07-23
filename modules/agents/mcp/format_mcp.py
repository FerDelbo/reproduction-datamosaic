"""Format constraint MCP - cell-level format validation and fixing"""
import re
import json
import os
import logging
from typing import List, Dict, Any, Optional
from .base import MCPVerifier, MCPFixer, BaseMCP, get_cell_value, get_table_definition
from ...memory import TableSnapshot, Violation, Fix, SuggestedFix, ConstraintType, ViolationSeverity, FixType
from ...core.ids import IdGenerator


class FormatVerifier(MCPVerifier):
    """Format constraint verifier - cell level"""
    
    def __init__(self, config_path: str = None):
        super().__init__("FormatVerifier.v1")
        self.logger = logging.getLogger('doc2db.mcp.format_verifier')
        
        if config_path is None:
            config_path = os.path.join(
                os.path.dirname(__file__), 
                'config', 
                'format_rules.json'
            )
        
        self.field_format_rules = self._load_config(config_path)
    
    def _load_config(self, config_path: str) -> Dict[str, Any]:
        """Load format rule configuration from a JSON file"""
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
                return config.get('field_format_rules', {})
        except FileNotFoundError:
            self.logger.warning(f"Config file not found: {config_path}; using defaults")
            return {}
        except json.JSONDecodeError as e:
            self.logger.error(f"Failed to parse config file: {e}; using defaults")
            return {}
    
    def get_supported_constraints(self) -> List[str]:
        return [ConstraintType.FORMAT.value]
    
    def can_handle(self, constraint_type: str) -> bool:
        return constraint_type == ConstraintType.FORMAT.value
    
    def verify(self, snapshot: TableSnapshot, schema: Dict[str, Any], 
               table_name: str, context=None) -> List[Violation]:
        """Validate format cell by cell"""
        violations = []
        
        self.logger.info(f"Starting cell-level format validation: {table_name}")
        total_cells_checked = 0
        
        table_def = get_table_definition(schema, table_name)
        attr_dict = {}
        
        if table_def:
            attributes = table_def.get('attributes', [])
            attr_dict = {attr['name']: attr for attr in attributes}
            self.logger.info(f"Loaded {len(attr_dict)} field definitions from schema")
        else:
            self.logger.warning(f"Could not load table {table_name} definition from schema; using config rules only")
        
        for row in snapshot.rows:
            for attr, cell in row.cells.items():
                value = str(cell.value) if cell.value is not None else ""
                
                if not value:
                    continue
                
                schema_pattern = None
                schema_description = None
                
                if attr in attr_dict:
                    attr_def = attr_dict[attr]
                    schema_pattern = attr_def.get('pattern')
                    schema_description = attr_def.get('pattern_description') or attr_def.get('format_description')
                
                if schema_pattern:
                    total_cells_checked += 1
                    
                    if not re.match(schema_pattern, value):
                        violation_id = IdGenerator.generate_violation_id(
                            table_name, row.tuple_id, attr, 
                            ConstraintType.FORMAT.value
                        )
                        
                        description = f"[Format mismatch] Field {attr} does not match schema format"
                        if schema_description:
                            description += f": {schema_description}"
                        description += f", current value: '{value}'"
                        
                        violation = Violation(
                            id=violation_id,
                            table=table_name,
                            tuple_id=row.tuple_id,
                            attr=attr,
                            constraint_type=ConstraintType.FORMAT.value,
                            description=description,
                            severity=ViolationSeverity.WARN.value,
                            suggested_fix=SuggestedFix(
                                value=f"Change to match pattern '{schema_pattern}'"
                            ),
                            detector_id=self.mcp_id,
                            timestamp=""
                        )
                        violations.append(violation)
                        
                        self.logger.debug(f"Format violation detected (schema): {row.tuple_id}.{attr} = '{value}'")
                
                elif attr in self.field_format_rules:
                    total_cells_checked += 1
                    rule = self.field_format_rules[attr]
                    
                    if not re.match(rule['pattern'], value):
                        violation_id = IdGenerator.generate_violation_id(
                            table_name, row.tuple_id, attr, 
                            ConstraintType.FORMAT.value
                        )
                        
                        violation = Violation(
                            id=violation_id,
                            table=table_name,
                            tuple_id=row.tuple_id,
                            attr=attr,
                            constraint_type=ConstraintType.FORMAT.value,
                            description=f"[Format mismatch] Field {attr} does not match standard '{rule['description']}', current value: '{value}'",
                            severity=ViolationSeverity.WARN.value,
                            suggested_fix=SuggestedFix(
                                value=f"Change to standard format, e.g.: {', '.join(rule['standard_examples'][:2])}"
                            ),
                            detector_id=self.mcp_id,
                            timestamp=""
                        )
                        violations.append(violation)
                        
                        self.logger.debug(f"Format violation detected (config): {row.tuple_id}.{attr} = '{value}'")
        
        self.logger.info(f"Format validation complete: checked {total_cells_checked} cells, found {len(violations)} violations")
        return violations
    
    def verify_cell(self, table: str, tuple_id: str, attr: str, 
                   value: Any, attr_def: Dict[str, Any], 
                   snapshot: TableSnapshot, context=None) -> List[Violation]:
        """Verify format for a single cell"""
        violations = []
        value_str = str(value) if value is not None else ""
        
        if not value_str:
            return violations
        
        schema_pattern = attr_def.get('pattern') if attr_def else None
        schema_description = None
        
        if attr_def:
            schema_description = attr_def.get('pattern_description') or attr_def.get('format_description')
        
        if schema_pattern:
            if not re.match(schema_pattern, value_str):
                violation_id = IdGenerator.generate_violation_id(
                    table, tuple_id, attr, ConstraintType.FORMAT.value
                )
                
                description = f"[Format mismatch] Field {attr} does not match schema format"
                if schema_description:
                    description += f": {schema_description}"
                description += f", current value: '{value_str}'"
                
                violation = Violation(
                    id=violation_id,
                    table=table,
                    tuple_id=tuple_id,
                    attr=attr,
                    constraint_type=ConstraintType.FORMAT.value,
                    description=description,
                    severity=ViolationSeverity.WARN.value,
                    suggested_fix=SuggestedFix(
                        value=f"Change to match pattern '{schema_pattern}'"
                    ),
                    detector_id=self.mcp_id,
                    timestamp=""
                )
                violations.append(violation)
        
        elif attr in self.field_format_rules:
            rule = self.field_format_rules[attr]
            
            if not re.match(rule['pattern'], value_str):
                violation_id = IdGenerator.generate_violation_id(
                    table, tuple_id, attr, ConstraintType.FORMAT.value
                )
                
                violation = Violation(
                    id=violation_id,
                    table=table,
                    tuple_id=tuple_id,
                    attr=attr,
                    constraint_type=ConstraintType.FORMAT.value,
                    description=f"[Format mismatch] Field {attr} does not match standard '{rule['description']}', current value: '{value_str}'",
                    severity=ViolationSeverity.WARN.value,
                    suggested_fix=SuggestedFix(
                        value=f"Change to standard format, e.g.: {', '.join(rule['standard_examples'][:2])}"
                    ),
                    detector_id=self.mcp_id,
                    timestamp=""
                )
                violations.append(violation)
        
        return violations


class FormatFixer(MCPFixer):
    """Format constraint fixer - cell level"""
    
    def __init__(self, config_path: str = None):
        super().__init__("FormatFixer.v1")
        self.logger = logging.getLogger('doc2db.mcp.format_fixer')
        
        if config_path is None:
            config_path = os.path.join(
                os.path.dirname(__file__), 
                'config', 
                'format_rules.json'
            )
        
        self.format_config = self._load_config(config_path)
        
        self.format_normalizers = {}
        for field_name in self.format_config.keys():
            if field_name == '季度':
                self.format_normalizers[field_name] = self._normalize_quarter
            elif field_name == '税额':
                self.format_normalizers[field_name] = self._normalize_amount
    
    def _load_config(self, config_path: str) -> Dict[str, Any]:
        """Load format rule configuration from a JSON file"""
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
                return config.get('field_format_rules', {})
        except FileNotFoundError:
            self.logger.warning(f"Config file not found: {config_path}; using defaults")
            return {}
        except json.JSONDecodeError as e:
            self.logger.error(f"Failed to parse config file: {e}; using defaults")
            return {}
    
    def get_supported_constraints(self) -> List[str]:
        return [ConstraintType.FORMAT.value]
    
    def can_handle(self, constraint_type: str) -> bool:
        return constraint_type == ConstraintType.FORMAT.value
    
    def can_fix(self, violation: Violation) -> bool:
        return (violation.constraint_type == ConstraintType.FORMAT.value and
                violation.attr in self.format_normalizers)
    
    def get_supported_fix_types(self) -> List[str]:
        return [FixType.FORMAT_FIX.value]
    
    def fix(self, violation: Violation, snapshot: TableSnapshot, 
            context=None) -> List[Fix]:
        """Fix format violations"""
        if not self.can_fix(violation):
            return []
        
        fixes = []
        
        try:
            old_value = get_cell_value(violation, snapshot)
            
            self.logger.info(f"FormatFixer: attempting fix for {violation.tuple_id}.{violation.attr}")
            
            if old_value is None:
                self.logger.warning(f"Could not get cell value: {violation.tuple_id}.{violation.attr}")
                return []
            
            normalizer = self.format_normalizers[violation.attr]
            new_value = normalizer(str(old_value))
            
            
            if new_value and new_value != old_value:
                fix_id = IdGenerator.generate_fix_id(
                    violation.table, violation.tuple_id, violation.attr,
                    FixType.FORMAT_FIX.value, old_value
                )
                
                fix = Fix(
                    id=fix_id,
                    table=violation.table,
                    tuple_id=violation.tuple_id,
                    attr=violation.attr,
                    old=old_value,
                    new=new_value,
                    fix_type=FixType.FORMAT_FIX.value,
                    applied_by=self.mcp_id,
                    timestamp="",
                    fix_success=True
                )
                
                fixes.append(fix)
                self.logger.info("Format fix applied to attribute %s", violation.attr)
                
        except Exception as e:
            self.logger.error(f"Format fix failed: {e}")
        
        return fixes
    
    def fix_batch(self, violations: List[Violation], snapshot: TableSnapshot, 
                  context=None) -> List[Fix]:
        """Batch-fix format violations with unified repair support"""
        all_fixes = []
        
        unified_fixes = self._apply_unified_fixes(violations, snapshot)
        all_fixes.extend(unified_fixes)
        
        fixed_violations = {f"{fix.attr}_{fix.tuple_id}" for fix in unified_fixes}
        
        remaining_violations = [
            v for v in violations 
            if f"{v.attr}_{v.tuple_id}" not in fixed_violations
        ]
        
        for violation in remaining_violations:
            fixes = self.fix(violation, snapshot, context)
            all_fixes.extend(fixes)
        
        self.logger.info(f"Batch format fix complete, generated {len(all_fixes)} fixes")
        return all_fixes
    
    def _apply_unified_fixes(self, violations: List[Violation], 
                            snapshot: TableSnapshot) -> List[Fix]:
        """Apply unified fix rules"""
        unified_fixes = []
        
        try:
            violations_by_attr = {}
            for violation in violations:
                attr = getattr(violation, 'attr', '')
                if attr:
                    if attr not in violations_by_attr:
                        violations_by_attr[attr] = []
                    violations_by_attr[attr].append(violation)
            
            for attr, attr_violations in violations_by_attr.items():
                if attr == '季度':
                    attr_fixes = self._unify_quarter_format(attr_violations, snapshot)
                    unified_fixes.extend(attr_fixes)
                elif attr == '税额':
                    attr_fixes = self._unify_amount_format(attr_violations, snapshot)
                    unified_fixes.extend(attr_fixes)
                
        except Exception as e:
            self.logger.error(f"Unified fix processing failed: {e}")
        
        return unified_fixes
    
    def _unify_quarter_format(self, violations: List[Violation], 
                             snapshot: TableSnapshot) -> List[Fix]:
        """Unify quarter format"""
        fixes = []
        
        try:
            if '季度' not in self.format_config:
                return fixes
            
            config = self.format_config['季度']
            quarter_map = config.get('mapping', {})
            standard_values = config.get('standard_values', [])
            
            processed_tuples = set()
            
            for row in snapshot.rows:
                if '季度' in row.cells:
                    current_value = str(row.cells['季度'].value).strip()
                    new_value = None
                    
                    if current_value.lower() in quarter_map:
                        new_value = quarter_map[current_value.lower()]
                    else:
                        for quarter in standard_values:
                            if quarter in current_value:
                                new_value = quarter
                                break
                    
                    if new_value and new_value != current_value and row.tuple_id not in processed_tuples:
                        fix_id = IdGenerator.generate_fix_id(
                            snapshot.table, row.tuple_id, '季度',
                            FixType.FORMAT_FIX.value, current_value
                        )
                        
                        fix = Fix(
                            id=fix_id,
                            table=snapshot.table,
                            tuple_id=row.tuple_id,
                            attr='季度',
                            old=current_value,
                            new=new_value,
                            fix_type=FixType.FORMAT_FIX.value,
                            applied_by=f"{self.mcp_id}_unified",
                            timestamp="",
                            fix_success=True
                        )
                        fixes.append(fix)
                        processed_tuples.add(row.tuple_id)
                        
        except Exception as e:
            self.logger.error(f"Unified quarter format fix failed: {e}")
        
        return fixes
    
    def _unify_amount_format(self, violations: List[Violation], 
                            snapshot: TableSnapshot) -> List[Fix]:
        """Unify tax amount format"""
        fixes = []
        
        try:
            if '税额' not in self.format_config:
                return fixes
            
            config = self.format_config['税额']
            conversion_rules = config.get('conversion_rules', [])
            
            processed_tuples = set()
            
            for row in snapshot.rows:
                if '税额' in row.cells:
                    current_value = str(row.cells['税额'].value).strip()
                    new_value = None
                    
                    for rule in conversion_rules:
                        pattern = rule['pattern']
                        template = rule['template']
                        
                        match = re.match(pattern, current_value)
                        if match:
                            new_value = template.format(*match.groups())
                            break
                    
                    if new_value and new_value != current_value and row.tuple_id not in processed_tuples:
                        fix_id = IdGenerator.generate_fix_id(
                            snapshot.table, row.tuple_id, '税额',
                            FixType.FORMAT_FIX.value, current_value
                        )
                        
                        fix = Fix(
                            id=fix_id,
                            table=snapshot.table,
                            tuple_id=row.tuple_id,
                            attr='税额',
                            old=current_value,
                            new=new_value,
                            fix_type=FixType.FORMAT_FIX.value,
                            applied_by=f"{self.mcp_id}_unified",
                            timestamp="",
                            fix_success=True
                        )
                        fixes.append(fix)
                        processed_tuples.add(row.tuple_id)
                        
        except Exception as e:
            self.logger.error(f"Unified tax amount format fix failed: {e}")
        
        return fixes
    
    def _normalize_quarter(self, value: str) -> Optional[str]:
        """Normalize quarter format to full Chinese name"""
        if not value or '季度' not in self.format_config:
            return None
        
        value = str(value).strip()
        value_lower = value.lower()
        
        config = self.format_config['季度']
        quarter_map = config.get('mapping', {})
        standard_values = config.get('standard_values', [])
        
        if value_lower in quarter_map:
            return quarter_map[value_lower]
        
        for quarter in standard_values:
            if quarter in value:
                return quarter
        
        return None
    
    def _normalize_amount(self, value: str) -> Optional[str]:
        """Normalize amount format and ensure a unit is present"""
        if not value or '税额' not in self.format_config:
            return None
        
        value = str(value).strip()
        
        config = self.format_config['税额']
        standard_pattern = config.get('standard_pattern', '')
        conversion_rules = config.get('conversion_rules', [])
        
        if re.match(standard_pattern, value):
            return value
        
        for rule in conversion_rules:
            pattern = rule['pattern']
            template = rule['template']
            
            match = re.match(pattern, value)
            if match:
                return template.format(*match.groups())
        
        return None


class FormatMCP(BaseMCP):
    """Format constraint MCP"""
    
    def __init__(self):
        verifier = FormatVerifier()
        fixer = FormatFixer()
        super().__init__("FormatMCP.v1", verifier, fixer)
