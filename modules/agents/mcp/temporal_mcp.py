"""Temporal constraint MCP - validate and fix time-related constraint issues"""
import re
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from .base import MCPVerifier, MCPFixer, BaseMCP, get_table_definition, get_cell_value, is_valid_fix_value
from ...memory import TableSnapshot, Violation, Fix, SuggestedFix, ConstraintType, ViolationSeverity, FixType
from ...core.ids import IdGenerator


class TemporalVerifier(MCPVerifier):
    """Temporal constraint verifier"""
    
    def __init__(self):
        super().__init__("TemporalVerifier.v1")
    
    def get_supported_constraints(self) -> List[str]:
        return [ConstraintType.TEMPORAL.value]
    
    def can_handle(self, constraint_type: str) -> bool:
        return constraint_type == ConstraintType.TEMPORAL.value
    
    def verify(self, snapshot: TableSnapshot, schema: Dict[str, Any], 
               table_name: str, context=None) -> List[Violation]:
        """Verify temporal constraints in the table (cell-level and table-level)"""
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
        
        row_violations = self._verify_row_temporal_constraints(
            snapshot, table_def, table_name
        )
        violations.extend(row_violations)
        
        table_violations = self._verify_table_temporal_constraints(
            snapshot, table_def, table_name
        )
        violations.extend(table_violations)
        
        return violations
    
    def verify_cell(self, table: str, tuple_id: str, attr: str, 
                   value: Any, attr_def: Dict[str, Any], 
                   snapshot: TableSnapshot, context=None) -> List[Violation]:
        """Verify temporal constraints for a single cell"""
        violations = []
        
        if value is None or str(value).strip() == '':
            return violations
        
        format_violations = self._check_temporal_format(
            table, tuple_id, attr, value, attr_def
        )
        violations.extend(format_violations)
        
        range_violations = self._check_temporal_range(
            table, tuple_id, attr, value, attr_def
        )
        violations.extend(range_violations)
        
        return violations
    
    def _verify_row_temporal_constraints(self, snapshot: TableSnapshot, 
                                        table_def: Dict[str, Any], 
                                        table_name: str) -> List[Violation]:
        """Verify in-row temporal constraints"""
        violations = []
        attributes = table_def.get('attributes', [])
        
        for row in snapshot.rows:
            temporal_violations = self._check_temporal_logic_within_row(
                row, attributes, table_name
            )
            violations.extend(temporal_violations)
        
        return violations
    
    def _verify_table_temporal_constraints(self, snapshot: TableSnapshot, 
                                          table_def: Dict[str, Any], 
                                          table_name: str) -> List[Violation]:
        """Verify table-level temporal constraints"""
        violations = []
        
        sequence_violations = self._check_temporal_sequence(
            snapshot, table_def, table_name
        )
        violations.extend(sequence_violations)
        
        return violations
    
    def _check_temporal_format(self, table: str, tuple_id: str, attr: str, 
                              value: Any, attr_def: Dict[str, Any]) -> List[Violation]:
        """Check temporal format validity"""
        violations = []
        
        if not self._is_temporal_field(attr, attr_def):
            return violations
        
        str_value = str(value).strip()
        
        parsed_date = self._parse_date(str_value)
        if parsed_date is None:
            violation_id = IdGenerator.generate_violation_id(
                table, tuple_id, attr, ConstraintType.TEMPORAL.value
            )
            
            suggested_value = self._suggest_date_fix(str_value)
            
            violation = Violation(
                id=violation_id,
                table=table,
                tuple_id=tuple_id,
                attr=attr,
                constraint_type=ConstraintType.TEMPORAL.value,
                description=f"Field {attr} value '{value}' is not a valid time format",
                severity=ViolationSeverity.WARN.value,
                
                suggested_fix=SuggestedFix(value=suggested_value, ),
                detector_id=self.mcp_id,
                timestamp=""
            )
            violations.append(violation)
        
        return violations
    
    def _check_temporal_range(self, table: str, tuple_id: str, attr: str, 
                             value: Any, attr_def: Dict[str, Any]) -> List[Violation]:
        """Check temporal range constraints"""
        violations = []
        
        if not self._is_temporal_field(attr, attr_def):
            return violations
        
        str_value = str(value).strip()
        parsed_date = self._parse_date(str_value)
        
        if parsed_date is None:
            return violations
        
        min_date = attr_def.get('min_date')
        if min_date:
            min_parsed = self._parse_date(str(min_date))
            if min_parsed and parsed_date < min_parsed:
                violation_id = IdGenerator.generate_violation_id(
                    table, tuple_id, attr, ConstraintType.TEMPORAL.value
                )
                
                violation = Violation(
                    id=violation_id,
                    table=table,
                    tuple_id=tuple_id,
                    attr=attr,
                    constraint_type=ConstraintType.TEMPORAL.value,
                    description=f"Field {attr} time {value} is earlier than the minimum time {min_date}",
                    severity=ViolationSeverity.WARN.value,
                    
                    suggested_fix=SuggestedFix(value=str(min_date), ),
                    detector_id=self.mcp_id,
                    timestamp=""
                )
                violations.append(violation)
        
        max_date = attr_def.get('max_date')
        if max_date:
            max_parsed = self._parse_date(str(max_date))
            if max_parsed and parsed_date > max_parsed:
                violation_id = IdGenerator.generate_violation_id(
                    table, tuple_id, attr, ConstraintType.TEMPORAL.value
                )
                
                violation = Violation(
                    id=violation_id,
                    table=table,
                    tuple_id=tuple_id,
                    attr=attr,
                    constraint_type=ConstraintType.TEMPORAL.value,
                    description=f"Field {attr} time {value} is later than the maximum time {max_date}",
                    severity=ViolationSeverity.WARN.value,
                    
                    suggested_fix=SuggestedFix(value=str(max_date), ),
                    detector_id=self.mcp_id,
                    timestamp=""
                )
                violations.append(violation)
        
        if attr_def.get('no_future', False):
            now = datetime.now()
            if parsed_date > now:
                violation_id = IdGenerator.generate_violation_id(
                    table, tuple_id, attr, ConstraintType.TEMPORAL.value
                )
                
                violation = Violation(
                    id=violation_id,
                    table=table,
                    tuple_id=tuple_id,
                    attr=attr,
                    constraint_type=ConstraintType.TEMPORAL.value,
                    description=f"Field {attr} cannot be a future time {value}",
                    severity=ViolationSeverity.WARN.value,
                    
                    suggested_fix=SuggestedFix(value=now.strftime('%Y-%m-%d'), ),
                    detector_id=self.mcp_id,
                    timestamp=""
                )
                violations.append(violation)
        
        return violations
    
    def _check_temporal_logic_within_row(self, row, attributes: List[Dict[str, Any]], 
                                        table_name: str) -> List[Violation]:
        """Check logical relationships between temporal fields within a row"""
        violations = []
        
        temporal_fields = {}
        for attr_def in attributes:
            attr_name = attr_def['name']
            if attr_name in row.cells and self._is_temporal_field(attr_name, attr_def):
                value = row.cells[attr_name].value
                if value:
                    parsed_date = self._parse_date(str(value))
                    if parsed_date:
                        temporal_fields[attr_name] = {
                            'value': value,
                            'parsed': parsed_date,
                            'attr_def': attr_def
                        }
        
        violations.extend(self._check_start_end_logic(row.tuple_id, temporal_fields, table_name))
        violations.extend(self._check_create_update_logic(row.tuple_id, temporal_fields, table_name))
        violations.extend(self._check_order_delivery_logic(row.tuple_id, temporal_fields, table_name))
        
        return violations
    
    def _check_start_end_logic(self, tuple_id: str, temporal_fields: Dict[str, Any], 
                              table_name: str) -> List[Violation]:
        """Check logical relationship between start and end times"""
        violations = []
        
        start_fields = [name for name in temporal_fields.keys() 
                       if 'start' in name.lower() or 'begin' in name.lower()]
        end_fields = [name for name in temporal_fields.keys() 
                     if 'end' in name.lower() or 'finish' in name.lower() or 'complete' in name.lower()]
        
        for start_field in start_fields:
            for end_field in end_fields:
                start_date = temporal_fields[start_field]['parsed']
                end_date = temporal_fields[end_field]['parsed']
                
                if start_date > end_date:
                    violation_id = IdGenerator.generate_violation_id(
                        table_name, tuple_id, end_field, ConstraintType.TEMPORAL.value
                    )
                    
                    violation = Violation(
                        id=violation_id,
                        table=table_name,
                        tuple_id=tuple_id,
                        attr=end_field,
                        constraint_type=ConstraintType.TEMPORAL.value,
                        description=f"End time {end_field} ({temporal_fields[end_field]['value']}) cannot be earlier than start time {start_field} ({temporal_fields[start_field]['value']})",
                        severity=ViolationSeverity.ERROR.value,
                        
                        suggested_fix=SuggestedFix(
                            value=(start_date + timedelta(days=1)).strftime('%Y-%m-%d'), 
                            
                        ),
                        detector_id=self.mcp_id,
                        timestamp=""
                    )
                    violations.append(violation)
        
        return violations
    
    def _check_create_update_logic(self, tuple_id: str, temporal_fields: Dict[str, Any], 
                                  table_name: str) -> List[Violation]:
        """Check logical relationship between create and update times"""
        violations = []
        
        create_fields = [name for name in temporal_fields.keys() 
                        if 'create' in name.lower() or 'add' in name.lower()]
        update_fields = [name for name in temporal_fields.keys() 
                        if 'update' in name.lower() or 'modify' in name.lower()]
        
        for create_field in create_fields:
            for update_field in update_fields:
                create_date = temporal_fields[create_field]['parsed']
                update_date = temporal_fields[update_field]['parsed']
                
                if create_date > update_date:
                    violation_id = IdGenerator.generate_violation_id(
                        table_name, tuple_id, update_field, ConstraintType.TEMPORAL.value
                    )
                    
                    violation = Violation(
                        id=violation_id,
                        table=table_name,
                        tuple_id=tuple_id,
                        attr=update_field,
                        constraint_type=ConstraintType.TEMPORAL.value,
                        description=f"Update time {update_field} ({temporal_fields[update_field]['value']}) cannot be earlier than create time {create_field} ({temporal_fields[create_field]['value']})",
                        severity=ViolationSeverity.ERROR.value,
                        
                        suggested_fix=SuggestedFix(
                            value=create_date.strftime('%Y-%m-%d'), 
                            
                        ),
                        detector_id=self.mcp_id,
                        timestamp=""
                    )
                    violations.append(violation)
        
        return violations
    
    def _check_order_delivery_logic(self, tuple_id: str, temporal_fields: Dict[str, Any], 
                                   table_name: str) -> List[Violation]:
        """Check logical relationship between order and delivery times"""
        violations = []
        
        order_fields = [name for name in temporal_fields.keys() 
                       if 'order' in name.lower()]
        delivery_fields = [name for name in temporal_fields.keys() 
                          if 'delivery' in name.lower() or 'ship' in name.lower()]
        
        for order_field in order_fields:
            for delivery_field in delivery_fields:
                order_date = temporal_fields[order_field]['parsed']
                delivery_date = temporal_fields[delivery_field]['parsed']
                
                if order_date > delivery_date:
                    violation_id = IdGenerator.generate_violation_id(
                        table_name, tuple_id, delivery_field, ConstraintType.TEMPORAL.value
                    )
                    
                    violation = Violation(
                        id=violation_id,
                        table=table_name,
                        tuple_id=tuple_id,
                        attr=delivery_field,
                        constraint_type=ConstraintType.TEMPORAL.value,
                        description=f"Delivery time {delivery_field} ({temporal_fields[delivery_field]['value']}) cannot be earlier than order time {order_field} ({temporal_fields[order_field]['value']})",
                        severity=ViolationSeverity.ERROR.value,
                        
                        suggested_fix=SuggestedFix(
                            value=(order_date + timedelta(days=3)).strftime('%Y-%m-%d'), 
                            
                        ),
                        detector_id=self.mcp_id,
                        timestamp=""
                    )
                    violations.append(violation)
        
        return violations
    
    def _check_temporal_sequence(self, snapshot: TableSnapshot, 
                                table_def: Dict[str, Any], 
                                table_name: str) -> List[Violation]:
        """Check temporal sequence constraints"""
        violations = []
        
        attributes = table_def.get('attributes', [])
        sort_field = None
        
        for attr_def in attributes:
            if (attr_def.get('temporal_sort', False) or 
                'date' in attr_def['name'].lower() or 
                'time' in attr_def['name'].lower()):
                sort_field = attr_def['name']
                break
        
        if not sort_field:
            return violations
        
        dates = []
        for row in snapshot.rows:
            if sort_field in row.cells:
                value = row.cells[sort_field].value
                if value:
                    parsed_date = self._parse_date(str(value))
                    if parsed_date:
                        dates.append({
                            'tuple_id': row.tuple_id,
                            'date': parsed_date,
                            'value': value
                        })
        
        dates.sort(key=lambda x: x['date'])
        for i in range(1, len(dates)):
            prev_date = dates[i-1]['date']
            curr_date = dates[i]['date']
            
            if (curr_date - prev_date).days > 365:
                violation_id = IdGenerator.generate_violation_id(
                    table_name, dates[i]['tuple_id'], sort_field, ConstraintType.TEMPORAL.value
                )
                
                violation = Violation(
                    id=violation_id,
                    table=table_name,
                    tuple_id=dates[i]['tuple_id'],
                    attr=sort_field,
                    constraint_type=ConstraintType.TEMPORAL.value,
                    description=f"Temporal sequence anomaly: {sort_field} value {dates[i]['value']} has too large a gap from the previous record",
                    severity=ViolationSeverity.INFO.value,
                    
                    suggested_fix=None,
                    detector_id=self.mcp_id,
                    timestamp=""
                )
                violations.append(violation)
        
        return violations
    
    def _is_temporal_field(self, attr_name: str, attr_def: Dict[str, Any]) -> bool:
        """Determine whether a field is temporal
        
        Priority:
        1. Rely entirely on the type definition in the schema (recommended)
        2. Use field-name heuristics only when type is undefined (fallback)
        """
        field_type = attr_def.get('type', '').strip()
        
        if field_type:
            field_type_lower = field_type.lower()
            
            if any(t in field_type_lower for t in ['date', 'time', 'timestamp']):
                return True
            
            return False
        
        self.logger.warning(
            f"Field {attr_name} has no type definition; falling back to field-name heuristics (not recommended)"
        )
        
        import re
        
        separated = re.sub(r'(?<!^)(?=[A-Z])', '_', attr_name)
        words = [word.lower() for word in separated.split('_') if word]
        
        temporal_keywords = ['date', 'time', 'created', 'updated', 'start', 'end', 'begin', 'finish', 'at', 'on']
        
        return any(word in temporal_keywords for word in words)
    
    def _parse_date(self, date_str: str) -> Optional[datetime]:
        """Parse a date string"""
        date_formats = [
            '%Y-%m-%d',
            '%Y/%m/%d',
            '%d/%m/%Y',
            '%m/%d/%Y',
            '%Y-%m-%d %H:%M:%S',
            '%Y/%m/%d %H:%M:%S',
            '%Y%m%d',
        ]
        
        for fmt in date_formats:
            try:
                return datetime.strptime(date_str.strip(), fmt)
            except ValueError:
                continue
        
        return None
    
    def _suggest_date_fix(self, date_str: str) -> str:
        """Suggest a date fix value"""
        if re.match(r'\d{4}/\d{2}/\d{2}', date_str):
            return date_str.replace('/', '-')
        elif re.match(r'\d{2}/\d{2}/\d{4}', date_str):
            parts = date_str.split('/')
            return f"20{parts[2]}-{parts[0]}-{parts[1]}"
        elif re.match(r'\d{4}\d{2}\d{2}', date_str):
            return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
        
        return datetime.now().strftime('%Y-%m-%d')


class TemporalFixer(MCPFixer):
    """Temporal constraint fixer"""
    
    def __init__(self):
        super().__init__("TemporalFixer.v1")
    
    def get_supported_constraints(self) -> List[str]:
        return [ConstraintType.TEMPORAL.value]
    
    def can_handle(self, constraint_type: str) -> bool:
        return constraint_type == ConstraintType.TEMPORAL.value
    
    def can_fix(self, violation: Violation) -> bool:
        if 'Temporal sequence anomaly' in violation.description:
            return False
        return violation.constraint_type == ConstraintType.TEMPORAL.value
    
    def get_supported_fix_types(self) -> List[str]:
        return [
            FixType.TEMPORAL_FIX.value,
            FixType.FORMAT_NORMALIZE.value,
            FixType.RANGE_CLAMP.value
        ]
    
    def fix(self, violation: Violation, snapshot: TableSnapshot, 
            context=None) -> List[Fix]:
        """Fix temporal constraint violations"""
        if not self.can_fix(violation):
            return []
        
        fixes = []
        old_value = get_cell_value(violation, snapshot)
        
        if not old_value:
            return fixes
        
        if violation.suggested_fix and violation.suggested_fix.value:
            suggested_value = violation.suggested_fix.value
            if is_valid_fix_value(suggested_value):
                new_value = suggested_value
            else:
                self.logger.warning(f"Suggested fix value '{suggested_value}' looks like prompt text rather than a data value; skipping fix")
                return fixes
            
            fix_type = self._determine_fix_type(violation.description)
            
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
                applied_by=self.mcp_id,
                timestamp="",

            )
            fixes.append(fix)
        
        return fixes
    
    def _determine_fix_type(self, description: str) -> str:
        """Determine fix type"""
        if 'format' in description:
            return FixType.FORMAT_NORMALIZE.value
        elif 'earlier than' in description or 'later than' in description:
            return FixType.RANGE_CLAMP.value
        else:
            return FixType.TEMPORAL_FIX.value


class TemporalMCP(BaseMCP):
    """Temporal constraint MCP"""
    
    def __init__(self):
        verifier = TemporalVerifier()
        fixer = TemporalFixer()
        super().__init__("TemporalMCP.v1", verifier, fixer)
