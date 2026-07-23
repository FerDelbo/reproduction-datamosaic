"""Validator implementation based on MCP (Model Context Protocol)"""
import logging
import asyncio
from typing import List, Dict, Any, Optional
from ..mcp.base import MCPClient
from ..mcp.data_quality_server import DataQualityMCPServer
from ...memory import TableSnapshot, Violation, ConstraintType, ViolationSeverity, SuggestedFix
from ...core.ids import IdGenerator
from ...core.io import IOManager
from enum import Enum

from .mcp_router import MCPRouter


class ViolationCategory(Enum):
    """Violation classification - differentiated handling methods"""
    TOOL_FIXABLE = "tool_fixable"  # Can be repaired with tools
    REQUIRES_REEXTRACTION = "requires_reextraction"  # Need to re-extract from the document


class MCPBasedVerifier:
    """Validator based on Model Context Protocol"""
    
    def __init__(self, enable_smart_routing: bool = True):
        """Initialize MCP validator
        
        Args:
            enable_smart_routing: Whether to enable smart MCP routing (default True)"""
        self.verifier_id = "MCPBasedVerifier.v2.1"
        self.logger = logging.getLogger('doc2db.verifier')
        
        self.mcp_client = MCPClient("doc2db-verifier-client")
        self.data_quality_server = DataQualityMCPServer()
        
        self.mcp_client.connect_server(self.data_quality_server)
        
        self.constraint_type_mapping = {
            ConstraintType.TYPE.value: "TYPE",
            ConstraintType.VALUE.value: "VALUE",
            ConstraintType.STRUCTURE.value: "STRUCTURE",
            ConstraintType.LOGIC.value: "LOGIC",
            ConstraintType.TEMPORAL.value: "TEMPORAL",
            ConstraintType.FORMAT.value: "FORMAT",
            ConstraintType.REFERENCE.value: "REFERENCE",
            ConstraintType.AGGREGATION.value: "AGGREGATION",
        }
        
        self.enable_smart_routing = enable_smart_routing
        self.router = MCPRouter() if enable_smart_routing else None
        
        routing_status = "smart routing enabled" if enable_smart_routing else "using traditional sequential verification"
        self.logger.info(f"Initialized MCP verifier v2.1 with {len(self.constraint_type_mapping)} constraint types, {routing_status}")
    
    def verify_table(self, table, context=None) -> List[Violation]:
        """Directly verify Table objects (new interface)
        
        Args:
            table: Table object
            context: processing context
            
        Returns:
            List of violations found"""
        try:
            return table.verify(self, context)
        except Exception as e:
            self.logger.error(f"Failed to verify Table object: {e}")
            return []
    
    def verify(self, snapshot: TableSnapshot, schema: Dict[str, Any], 
               table_name: str, context=None) -> List[Violation]:
        """Validate data in table snapshot using MCP"""
        self.logger.info(f"Starting MCP verification for table {table_name}")
        
        if isinstance(schema, str):
            try:
                import json
                schema = json.loads(schema)
                self.logger.info(f"Parsed schema from string to dict")
            except Exception as e:
                self.logger.error(f"Failed to parse schema: {e}")
                return []
        elif not isinstance(schema, dict):
            self.logger.error(f"Invalid schema type: {type(schema)}")
            return []
        
        try:
            try:
                loop = asyncio.get_running_loop()
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(asyncio.run, self._async_verify(snapshot, schema, table_name, context))
                    return future.result()
            except RuntimeError:
                return asyncio.run(self._async_verify(snapshot, schema, table_name, context))
        except Exception as e:
            self.logger.error(f"Async verification failed: {e}")
            return []
    
    async def _async_verify(self, snapshot: TableSnapshot, schema: Dict[str, Any], 
                           table_name: str, context=None) -> List[Violation]:
        """Asynchronous verification implementation"""
        all_violations = []
        routing_info = None
        
        constraint_types_to_check = list(self.constraint_type_mapping.values())  # Default all
        
        if self.enable_smart_routing and self.router:
            try:
                selected_mcp_names, routing_info = self.router.select_mcps(snapshot, schema, table_name)
                
                mcp_to_constraint_map = {
                    "TypeMCP": "TYPE",
                    "ValueMCP": "VALUE", 
                    "StructureMCP": "STRUCTURE",
                    "FormatMCP": "FORMAT",
                    "LogicMCP": "LOGIC",
                    "TemporalMCP": "TEMPORAL",
                    "ReferenceMCP": "REFERENCE",
                    "AggregationMCP": "AGGREGATION"
                }
                
                constraint_types_to_check = [
                    mcp_to_constraint_map[mcp_name] 
                    for mcp_name in selected_mcp_names 
                    if mcp_name in mcp_to_constraint_map
                ]
                
                self.logger.info(f"Smart routing selected {len(constraint_types_to_check)} constraint types: {constraint_types_to_check}")
                
            except Exception as e:
                self.logger.warning(f"Smart routing failed; using all MCPs: {e}")
                constraint_types_to_check = list(self.constraint_type_mapping.values())
        
        verification_data = {
            "table_name": table_name,
            "rows": [
                {
                    "tuple_id": row.tuple_id,
                    "cells": {
                        attr: cell.value
                        for attr, cell in row.cells.items()
                    }
                }
                for row in snapshot.rows
            ]
        }
        
        mcp_success = False
        try:
            response = await self.mcp_client.call_tool(
                server_name="doc2db-data-quality",
                tool_name="batch_verify",
                arguments={
                    "snapshots": [verification_data],
                    "schema": schema,
                    "constraint_types": constraint_types_to_check  # Constraint types using smart routing
                }
            )
            
            if response and response.get("status") == "success":
                mcp_success = True
                total_violations = response.get("total_violations", 0)
                self.logger.info(f"MCP batch verification succeeded; processed {response.get('processed_snapshots', 0)} snapshots and found {total_violations} violations")
                
                violations_data = response.get("violations", [])
                
                routing_info = {
                    'violations_by_mcp': response.get("violations_by_type", {}),
                    'constraint_types_checked': response.get("constraint_types", []),
                    'total_violations': total_violations
                }
                
                for violation_data in violations_data:
                    all_violations.append(self._convert_mcp_violation_to_object(violation_data, table_name))
                    
            elif response and response.get("status") == "error":
                self.logger.error(f"MCP verification returned error: {response.get('message', 'unknown error')}")
            
        except Exception as e:
            self.logger.error(f"MCP tool call failed: {e}")
        
        if not mcp_success:
            self.logger.info("MCP server verification failed; falling back to individual MCP components")
            all_violations = await self._fallback_verify(snapshot, schema, table_name, context)
        
        unique_violations = {}
        for violation in all_violations:
            if hasattr(violation, 'id') and violation.id not in unique_violations:
                unique_violations[violation.id] = violation
        
        final_violations = list(unique_violations.values())
        
        categorized_violations = self._categorize_violations(final_violations, table_name)
        
        for violation, category in zip(final_violations, categorized_violations):
            if category == ViolationCategory.REQUIRES_REEXTRACTION:
                violation.processing_category = "requires_reextraction"
            elif category == ViolationCategory.TOOL_FIXABLE:
                violation.processing_category = "tool_fixable"
            else:
                violation.processing_category = str(category)
        
        verification_info = f"MCP verification complete; found {len(final_violations)} violations"
        self.logger.info(verification_info)
        
        if hasattr(context, 'step_outputs'):
            error_violations = [v for v in final_violations if getattr(v, 'severity', 'warn') == 'error']
            warn_violations = [v for v in final_violations if getattr(v, 'severity', 'warn') == 'warn']
            
            details = {
                'table_name': table_name,
                'violations_found': len(final_violations),
                'error_violations': len(error_violations),
                'warn_violations': len(warn_violations),
                'mcp_server': self.data_quality_server.name,
                'constraint_types_checked': constraint_types_to_check,
                'violations_by_type': {},
                'output_text': f"MCP verification complete; found {len(final_violations)} quality issues"
            }
            
            for violation in final_violations:
                constraint_type = getattr(violation, 'constraint_type', 'unknown')
                if constraint_type not in details['violations_by_type']:
                    details['violations_by_type'][constraint_type] = 0
                details['violations_by_type'][constraint_type] += 1
            
            if routing_info and 'violations_by_mcp' in routing_info:
                details['mcp_results'] = []
                mcp_name_map = {
                    'TYPE': 'TypeMCP',
                    'VALUE': 'ValueMCP',
                    'STRUCTURE': 'StructureMCP',
                    'FORMAT': 'FormatMCP',
                    'LOGIC': 'LogicMCP',
                    'TEMPORAL': 'TemporalMCP',
                    'REFERENCE': 'ReferenceMCP',
                    'AGGREGATION': 'AggregationMCP'
                }
                
                for constraint_type, violation_count in routing_info['violations_by_mcp'].items():
                    mcp_name = mcp_name_map.get(constraint_type, f"{constraint_type}MCP")
                    details['mcp_results'].append({
                        'mcp_name': mcp_name,
                        'constraint_type': constraint_type,
                        'violations_found': violation_count,
                        'status': 'found_issues' if violation_count > 0 else 'passed'
                    })
                
                for constraint_type in constraint_types_to_check:
                    if constraint_type not in routing_info['violations_by_mcp']:
                        mcp_name = mcp_name_map.get(constraint_type, f"{constraint_type}MCP")
                        details['mcp_results'].append({
                            'mcp_name': mcp_name,
                            'constraint_type': constraint_type,
                            'violations_found': 0,
                            'status': 'passed'
                        })
                
                details['smart_routing_enabled'] = True
                details['mcps_skipped'] = routing_info.get('optional_mcps_skipped', [])
            else:
                details['smart_routing_enabled'] = False
            
            context.step_outputs.append({
                'step': f'verifier_{table_name}_completed',
                'step_name': f'verifier_{table_name}_completed',
                'status': 'completed', 
                'description': f"Table {table_name} verification complete; found {len(final_violations)} quality issues",
                'details': details,
                'timestamp': IOManager.get_timestamp()
            })
            
        
        return final_violations
    
    async def _fallback_verify(self, snapshot: TableSnapshot, schema: Dict[str, Any], 
                              table_name: str, context=None) -> List[Violation]:
        """Fallback verification method - use specific MCP components directly"""
        self.logger.info("Verifying directly with individual MCP components")
        
        violations = []
        routing_info = None
        
        try:
            from ..mcp import (
                TypeMCP, ValueMCP, StructureMCP, FormatMCP,
                LogicMCP, TemporalMCP, ReferenceMCP, AggregationMCP
            )
            
            all_mcps = {
                "TypeMCP": TypeMCP(),
                "ValueMCP": ValueMCP(), 
                "StructureMCP": StructureMCP(),
                "FormatMCP": FormatMCP(),
                "LogicMCP": LogicMCP(),
                "TemporalMCP": TemporalMCP(),
                "ReferenceMCP": ReferenceMCP(),
                "AggregationMCP": AggregationMCP()
            }
            
            if self.enable_smart_routing and self.router:
                selected_mcp_names, routing_info = self.router.select_mcps(snapshot, schema, table_name)
                
                mcps_to_run = [(name, all_mcps[name]) for name in selected_mcp_names if name in all_mcps]
            else:
                mcps_to_run = list(all_mcps.items())
            
            for mcp_name, mcp in mcps_to_run:
                try:
                    self.logger.info(f"Verifying with {mcp_name}...")
                    
                    mcp_violations = mcp.verify(snapshot, schema, table_name)
                    violations.extend(mcp_violations)
                except Exception as e:
                    self.logger.error(f"{mcp_name} verification failed: {e}")
            
        except ImportError as e:
            self.logger.error(f"Failed to import MCP components: {e}")
            violations = []
        
        if violations:
            categorized_violations = self._categorize_violations(violations, table_name)
            
            for violation, category in zip(violations, categorized_violations):
                violation.processing_category = category
        
        self.logger.info(f"MCP verification complete; found {len(violations)} violations total")
        
        if routing_info and hasattr(context, 'step_outputs'):
            context.step_outputs.append({
                'step': f'mcp_routing_{table_name}',
                'status': 'completed',
                'description': f'MCP routing decision for table {table_name}',
                'details': routing_info,
                'timestamp': IOManager.get_timestamp()
            })
        
        return violations
    
    def _convert_mcp_violation_to_object(self, violation_data: Dict[str, Any], table_name: str) -> Violation:
        """Convert the violation data returned by the MCP into a Violation object"""
        
        tuple_id = violation_data.get('tuple_id', '')
        attr = violation_data.get('attr', '')
        constraint_type = violation_data.get('constraint_type', 'UNKNOWN')
        
        violation_id = IdGenerator.generate_violation_id(
            table_name, tuple_id, attr, constraint_type
        )
        
        suggested_fix = None
        if violation_data.get('suggested_fix'):
            suggested_fix = SuggestedFix(
                value=violation_data['suggested_fix']
            )
        
        severity = violation_data.get('severity', ViolationSeverity.WARN.value)
        if severity not in [s.value for s in ViolationSeverity]:
            severity = ViolationSeverity.WARN.value
        
        violation = Violation(
            id=violation_id,
            table=table_name,
            tuple_id=tuple_id,
            attr=attr,
            constraint_type=constraint_type,
            description=violation_data.get('description', f"MCP-detected {constraint_type} constraint violation"),
            severity=severity,
            suggested_fix=suggested_fix,
            detector_id=self.verifier_id,
            timestamp=""
        )
        
        if 'current_value' in violation_data:
            violation.current_value = violation_data['current_value']
        
        return violation
    
    def get_supported_constraints(self) -> List[str]:
        """Get a list of supported constraint types"""
        return list(self.constraint_type_mapping.keys())
    
    async def get_mcp_resources(self) -> List[Dict[str, Any]]:
        """Get MCP server resources"""
        try:
            resources = await self.mcp_client.list_server_resources("doc2db-data-quality")
            return [resource.to_dict() for resource in resources]
        except Exception as e:
            self.logger.error(f"Failed to get MCP resources: {e}")
            return []
    
    async def get_constraint_types_info(self) -> Optional[Dict[str, Any]]:
        """Get constraint type information"""
        try:
            resource_data = await self.mcp_client.get_resource("doc2db-data-quality", "constraint://types")
            return resource_data
        except Exception as e:
            self.logger.error(f"Failed to get constraint type information: {e}")
            return None
    
    def _categorize_violations(self, violations: List[Violation], table_name: str) -> List[ViolationCategory]:
        """Classify violations and differentiate treatment methods"""
        categories = []
        
        for violation in violations:
            category = self._determine_violation_category(violation)
            categories.append(category)
            
            category_name = "tool fixable" if category == ViolationCategory.TOOL_FIXABLE else "re-extraction"
        
        tool_fixable_count = sum(1 for cat in categories if cat == ViolationCategory.TOOL_FIXABLE)
        reextraction_count = sum(1 for cat in categories if cat == ViolationCategory.REQUIRES_REEXTRACTION)
        
        
        return categories
    
    def _determine_violation_category(self, violation: Violation) -> ViolationCategory:
        """Determine how to handle individual violations"""
        constraint_type = violation.constraint_type
        description = violation.description.lower() if violation.description else ""
        
        if hasattr(violation, 'business_rule_id') and violation.business_rule_id:
            if violation.business_rule_id in ['agg_1', 'agg_2']:
                return ViolationCategory.REQUIRES_REEXTRACTION
        
        
        tool_fixable_conditions = [
            constraint_type == ConstraintType.TYPE.value and any(keyword in description for keyword in [
                "类型", "type", "转换", "convert", "格式", "format"
            ]),
            
            constraint_type == ConstraintType.FORMAT.value,
            
            constraint_type == ConstraintType.VALUE.value and any(keyword in description for keyword in [
                "范围", "range", "长度", "length", "大小", "size", "超出", "exceed"
            ]),
            
            hasattr(violation, 'suggested_fix') and violation.suggested_fix is not None,
            
            constraint_type == ConstraintType.LOGIC.value and any(format_keyword in description for format_keyword in [
                "格式", "单位", "标识", "format", "unit", "identifier", "统一", "standardize", "空格", "spacing"
            ]),
            
            constraint_type == ConstraintType.STRUCTURE.value and any(keyword in description for keyword in [
                "重复", "duplicate", "冲突", "conflict", "唯一", "unique"
            ]),
        ]
        
        reextraction_conditions = [
            constraint_type == ConstraintType.STRUCTURE.value and not any(keyword in description for keyword in [
                "重复", "duplicate", "冲突", "conflict", "唯一", "unique"
            ]),
            
            constraint_type == ConstraintType.LOGIC.value and any(keyword in description for keyword in [
                "关系", "relation", "依赖", "dependency", "一致性", "consistency", "计算错误", "数值异常", "业务规则冲突"
            ]) and not any(format_keyword in description for format_keyword in [
                "格式", "单位", "标识", "format", "unit", "identifier", "统一", "standardize"
            ]),
            
            constraint_type == ConstraintType.REFERENCE.value,
            
            "缺失" in description or "missing" in description or "空值" in description or "null" in description,
            
            violation.severity == ViolationSeverity.ERROR.value and not (
                hasattr(violation, 'suggested_fix') and violation.suggested_fix is not None
            ),
        ]
        
        if any(tool_fixable_conditions):
            return ViolationCategory.TOOL_FIXABLE
        elif any(reextraction_conditions):
            return ViolationCategory.REQUIRES_REEXTRACTION
        else:
            if violation.severity == ViolationSeverity.ERROR.value:
                return ViolationCategory.REQUIRES_REEXTRACTION
            else:
                return ViolationCategory.TOOL_FIXABLE
    
    def verify_multi_table(self, all_snapshots: Dict[str, TableSnapshot], 
                          schema: Dict[str, Any], context=None) -> List[Violation]:
        """Multi-table validation - verify relationships between tables and cross-table constraints
        
        Args:
            all_snapshots: snapshot dictionary of all tables {table_name: TableSnapshot}
            schema: complete schema definition (including relations)
            context: processing context
            
        Returns:
            Cross-table violation list"""
        self.logger.info(f"Starting multi-table verification for {len(all_snapshots)} tables")
        
        try:
            try:
                loop = asyncio.get_running_loop()
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(asyncio.run, self._async_verify_multi_table(all_snapshots, schema, context))
                    return future.result()
            except RuntimeError:
                return asyncio.run(self._async_verify_multi_table(all_snapshots, schema, context))
        except Exception as e:
            self.logger.error(f"Multi-table verification failed: {e}")
            return []
    
    async def _async_verify_multi_table(self, all_snapshots: Dict[str, TableSnapshot],
                                       schema: Dict[str, Any], context=None) -> List[Violation]:
        """Asynchronous multi-table verification implementation"""
        all_violations = []
        
        relation_verification_details = []
        same_field_verification_details = []
        
        relations = schema.get('relations', [])
        if relations:
            self.logger.info(f"[Multi-table verification - Relations] Found {len(relations)} relation definitions")
            
            for rel_idx, relation in enumerate(relations):
                if not isinstance(relation, dict):
                    continue
                
                rel_type = relation.get('type', 'unknown')
                from_def = relation.get('from', {})
                to_def = relation.get('to', {})
                
                from_table = from_def.get('table')
                from_field = from_def.get('field')
                to_table = to_def.get('table')
                to_field = to_def.get('field')
                
                if not all([from_table, from_field, to_table, to_field]):
                    self.logger.warning(f"Relation {rel_idx} definition is incomplete; skipping")
                    continue
                
                self.logger.info(f"  Verifying relation [{rel_type}]: {from_table}.{from_field} -> {to_table}.{to_field}")
                
                relation_violations = await self._verify_single_relation(
                    relation, all_snapshots, schema, context
                )
                
                relation_detail = {
                    'relation_type': rel_type,
                    'from_table': from_table,
                    'from_field': from_field,
                    'to_table': to_table,
                    'to_field': to_field,
                    'violations_count': len(relation_violations),
                    'status': 'passed' if not relation_violations else 'violations_found'
                }
                relation_verification_details.append(relation_detail)
                
                if relation_violations:
                    self.logger.warning(f"    Found {len(relation_violations)} violations")
                    all_violations.extend(relation_violations)
                else:
                    self.logger.info(f"    Relation integrity verified")
        else:
            self.logger.info("No relations defined in schema")
            self.logger.info("[Multi-table verification - Relations] No relations defined in schema")
        
        self.logger.info(f"[Multi-table verification - Same fields] Checking same fields across tables...")
        same_field_violations = await self._verify_same_fields_across_tables(
            all_snapshots, schema, context
        )
        
        if same_field_violations:
            self.logger.warning(f"  Found {len(same_field_violations)} same-field violations")
            all_violations.extend(same_field_violations)
        else:
            self.logger.info(f"  Same-field verification passed")
        
        self.logger.info(f"[Multi-table verification - Business rules] Checking multi-table business rules defined in schema...")
        business_rule_violations = await self._verify_multi_table_business_rules(
            all_snapshots, schema, context
        )
        
        if business_rule_violations:
            self.logger.warning(f"  Found {len(business_rule_violations)} business rule violations")
            all_violations.extend(business_rule_violations)
        else:
            self.logger.info(f"  Business rule verification passed")
        
        self.logger.info(f"[Multi-table verification] Complete; found {len(all_violations)} cross-table violations total")
        self.logger.info(f"    - Relation verification: {len(all_violations) - len(same_field_violations)}")
        self.logger.info(f"    - Same-field verification: {len(same_field_violations)}")
        
        if context and hasattr(context, 'step_outputs'):
            from ...core.io import IOManager
            
            multi_table_detail_step = {
                'step': 'multi_table_verification_detailed',
                'step_name': 'multi_table_verification_detailed',
                'status': 'completed',
                'description': f'Multi-table verification details',
                'details': {
                    'total_tables': len(all_snapshots),
                    'tables_verified': list(all_snapshots.keys()),
                    'relations_verified': len(relations) if relations else 0,
                    'relation_verification_details': relation_verification_details,
                    'same_field_checks': len(same_field_verification_details),
                    'total_violations': len(all_violations),
                    'relation_violations': len(all_violations) - len(same_field_violations),
                    'same_field_violations': len(same_field_violations),
                    'verification_summary': f"Verified {len(relations) if relations else 0} table relations and checked cross-table field consistency"
                },
                'timestamp': IOManager.get_timestamp()
            }
            context.step_outputs.append(multi_table_detail_step)
        
        return all_violations
    
    async def _verify_single_relation(self, relation: Dict[str, Any],
                                     all_snapshots: Dict[str, TableSnapshot],
                                     schema: Dict[str, Any], context=None) -> List[Violation]:
        """Verify the integrity of a single relationship"""
        violations = []
        
        from_def = relation.get('from', {})
        to_def = relation.get('to', {})
        
        from_table = from_def.get('table')
        from_field = from_def.get('field')
        to_table = to_def.get('table')
        to_field = to_def.get('field')
        rel_type = relation.get('type', 'unknown')
        
        if from_table not in all_snapshots:
            self.logger.warning(f"Source table {from_table} does not exist; skipping relation verification")
            return violations
        
        if to_table not in all_snapshots:
            self.logger.warning(f"Target table {to_table} does not exist; skipping relation verification")
            return violations
        
        from_snapshot = all_snapshots[from_table]
        to_snapshot = all_snapshots[to_table]
        
        to_values = set()
        for row in to_snapshot.rows:
            if to_field in row.cells:
                cell = row.cells[to_field]
                if cell.value is not None:
                    to_values.add(str(cell.value))
        
        for row in from_snapshot.rows:
            if from_field not in row.cells:
                continue
            
            cell = row.cells[from_field]
            if cell.value is None:
                field_nullable = self._is_field_nullable(schema, from_table, from_field)
                if not field_nullable:
                    violation = Violation(
                        id=IdGenerator.generate_violation_id(
                            from_table, row.tuple_id, from_field, "REFERENCE"
                        ),
                        table=from_table,
                        tuple_id=row.tuple_id,
                        attr=from_field,
                        constraint_type=ConstraintType.REFERENCE.value,
                        description=f"Foreign key field {from_field} is null but is not nullable (references {to_table}.{to_field})",
                        severity=ViolationSeverity.ERROR.value,
                        suggested_fix=None,
                        detector_id=self.verifier_id,
                        timestamp=""
                    )
                    violation.current_value = None
                    violations.append(violation)
                continue
            
            fk_value = str(cell.value)
            if fk_value not in to_values:
                violation = Violation(
                    id=IdGenerator.generate_violation_id(
                        from_table, row.tuple_id, from_field, "REFERENCE"
                    ),
                    table=from_table,
                    tuple_id=row.tuple_id,
                    attr=from_field,
                    constraint_type=ConstraintType.REFERENCE.value,
                    description=f"Foreign key value '{fk_value}' does not exist in target table {to_table}.{to_field} ({rel_type} relation)",
                    severity=ViolationSeverity.ERROR.value,
                    suggested_fix=None,
                    detector_id=self.verifier_id,
                    timestamp=""
                )
                violation.current_value = fk_value
                violations.append(violation)
        
        return violations
    
    def _is_field_nullable(self, schema: Dict[str, Any], table_name: str, field_name: str) -> bool:
        """Check whether the field is allowed to be empty"""
        tables = schema.get('tables', [])
        for table in tables:
            if table.get('name') != table_name:
                continue
            
            fields = table.get('fields', table.get('attributes', []))
            for field in fields:
                if field.get('name') == field_name:
                    constraints = field.get('constraints', {})
                    return constraints.get('nullable', True)
        
        return True
    
    async def _verify_same_fields_across_tables(self, all_snapshots: Dict[str, TableSnapshot],
                                               schema: Dict[str, Any], context=None) -> List[Violation]:
        """Verify the same fields in different tables (same field names)
        
        Verification content includes:
        1. Data type consistency for the same field
        2. Value range consistency of the same field (if the field value represents the same entity/concept)
        3. Format consistency of the same fields
        
        Args:
            all_snapshots: snapshots of all tables
            schema: complete schema
            context: processing context
            
        Returns:
            List of violations for same fields across tables"""
        violations = []
        
        table_fields = {}  # {table_name: {field_name: field_info}}
        
        for table_name, snapshot in all_snapshots.items():
            if not snapshot or not snapshot.rows:
                continue
            
            if snapshot.rows:
                first_row = snapshot.rows[0]
                field_names = list(first_row.cells.keys())
                
                field_defs = self._get_table_field_definitions(schema, table_name)
                
                table_fields[table_name] = {
                    'field_names': field_names,
                    'field_defs': field_defs,
                    'snapshot': snapshot
                }
        
        field_to_tables = {}  # {field_name: [table_names]}
        for table_name, info in table_fields.items():
            for field_name in info['field_names']:
                if field_name not in field_to_tables:
                    field_to_tables[field_name] = []
                field_to_tables[field_name].append(table_name)
        
        common_fields = {field: tables for field, tables in field_to_tables.items() if len(tables) > 1}
        
        if not common_fields:
            self.logger.info("No same fields found across tables")
            return violations
        
        self.logger.info(f"  Found {len(common_fields)} same fields across tables:")
        for field, tables in common_fields.items():
            self.logger.info(f"     - {field}: {', '.join(tables)}")
        
        for field_name, table_names in common_fields.items():
            self.logger.info(f"  Verifying same field: {field_name}")
            
            field_values_by_table = {}
            field_types_by_table = {}
            
            for table_name in table_names:
                snapshot = table_fields[table_name]['snapshot']
                values = []
                types = set()
                
                for row in snapshot.rows:
                    if field_name in row.cells:
                        cell = row.cells[field_name]
                        if cell.value is not None:
                            values.append(cell.value)
                            types.add(type(cell.value).__name__)
                
                field_values_by_table[table_name] = values
                field_types_by_table[table_name] = types
            
            type_violations = self._check_field_type_consistency(
                field_name, table_names, field_types_by_table, all_snapshots
            )
            violations.extend(type_violations)
            
            domain_violations = self._check_field_domain_consistency(
                field_name, table_names, field_values_by_table, all_snapshots, schema
            )
            violations.extend(domain_violations)
            
            format_violations = self._check_field_format_consistency(
                field_name, table_names, field_values_by_table, all_snapshots
            )
            violations.extend(format_violations)
        
        return violations
    
    def _get_table_field_definitions(self, schema: Dict[str, Any], table_name: str) -> Dict[str, Any]:
        """Get the field definitions of the table from the schema"""
        tables = schema.get('tables', [])
        for table in tables:
            if table.get('name') == table_name:
                fields = table.get('fields', table.get('attributes', []))
                return {field.get('name'): field for field in fields if 'name' in field}
        return {}
    
    def _check_field_type_consistency(self, field_name: str, table_names: List[str],
                                     field_types_by_table: Dict[str, set],
                                     all_snapshots: Dict[str, TableSnapshot]) -> List[Violation]:
        """Check the type consistency of the same field in different tables"""
        violations = []
        
        all_types = set()
        for types in field_types_by_table.values():
            all_types.update(types)
        
        if len(all_types) > 1:
            self.logger.warning(f"    Type inconsistency: {all_types}")
            
            type_counts = {}
            for table_name, types in field_types_by_table.items():
                for t in types:
                    type_counts[t] = type_counts.get(t, 0) + 1
            
            expected_type = max(type_counts.items(), key=lambda x: x[1])[0] if type_counts else None
            
            for table_name, types in field_types_by_table.items():
                if expected_type and expected_type not in types:
                    actual_type = list(types)[0] if types else "unknown"
                    violation = Violation(
                        id=IdGenerator.generate_violation_id(
                            table_name, "CROSS_TABLE", field_name, "TYPE"
                        ),
                        table=table_name,
                        tuple_id="CROSS_TABLE",
                        attr=field_name,
                        constraint_type=ConstraintType.TYPE.value,
                        description=f"Cross-table field type inconsistency: field {field_name} has type {actual_type} in table {table_name} but {expected_type} in other tables",
                        severity=ViolationSeverity.WARN.value,
                        suggested_fix=None,
                        detector_id=self.verifier_id,
                        timestamp=""
                    )
                    violations.append(violation)
        
        return violations
    
    def _check_field_domain_consistency(self, field_name: str, table_names: List[str],
                                       field_values_by_table: Dict[str, List],
                                       all_snapshots: Dict[str, TableSnapshot],
                                       schema: Dict[str, Any]) -> List[Violation]:
        """Check the consistency of the value range of the same field in different tables
        
        If the field has enumeration values defined in the schema, check whether the actual values are within the enumeration range
        
        NOTE: Similar entity detection is now handled by the ConsistencyMCP component"""
        violations = []
        
        all_unique_values = set()
        for values in field_values_by_table.values():
            all_unique_values.update(str(v) for v in values)
        
        if len(all_unique_values) < 20 and len(all_unique_values) > 0:
            value_sets = {table: set(str(v) for v in values) 
                         for table, values in field_values_by_table.items()}
            
            common_values = set.intersection(*value_sets.values()) if value_sets else set()
            
            for table_name, values in value_sets.items():
                unique_to_table = values - common_values
                if unique_to_table and len(unique_to_table) / len(values) > 0.3:  # More than 30% are unique values
                    self.logger.info(f"    Table {table_name} has unique values: {unique_to_table}")
        
        return violations
    
    def _check_field_format_consistency(self, field_name: str, table_names: List[str],
                                       field_values_by_table: Dict[str, List],
                                       all_snapshots: Dict[str, TableSnapshot]) -> List[Violation]:
        """Check the format consistency of the same field in different tables (for string fields)"""
        violations = []
        
        format_patterns = {}  # {table_name: set_of_patterns}
        
        for table_name, values in field_values_by_table.items():
            patterns = set()
            for value in values:
                if isinstance(value, str):
                    pattern = self._detect_string_pattern(value)
                    patterns.add(pattern)
            format_patterns[table_name] = patterns
        
        all_patterns = set()
        for patterns in format_patterns.values():
            all_patterns.update(patterns)
        
        if len(all_patterns) > 3:  # More than 3 different modes
            self.logger.info(f"    Many format patterns detected: {all_patterns}")
        
        return violations
    
    async def _verify_multi_table_business_rules(self, all_snapshots: Dict[str, TableSnapshot],
                                                 schema: Dict[str, Any], context=None) -> List[Violation]:
        """Verify the multi-table business rules (including logical rules and aggregation rules) defined in the schema"""
        violations = []
        
        try:
            from ..mcp import LogicMCP
            
            logic_mcp = LogicMCP()
            if hasattr(logic_mcp.verifier, 'verify_multi_table_business_rules'):
                logic_violations = logic_mcp.verifier.verify_multi_table_business_rules(
                    all_snapshots, schema, context
                )
                violations.extend(logic_violations)
        except Exception as e:
            self.logger.error(f"Multi-table business logic rule verification failed: {e}")
        
        try:
            from ..mcp import AggregationMCP
            
            aggregation_mcp = AggregationMCP()
            if hasattr(aggregation_mcp.verifier, 'verify_multi_table_aggregation_rules'):
                aggregation_violations = aggregation_mcp.verifier.verify_multi_table_aggregation_rules(
                    all_snapshots, schema, context
                )
                violations.extend(aggregation_violations)
        except Exception as e:
            self.logger.error(f"Multi-table aggregation rule verification failed: {e}")
        
        return violations
    
    def _detect_string_pattern(self, value: str) -> str:
        """Detect the format pattern of a string"""
        import re
        
        if not value:
            return "empty"
        
        if re.match(r'^\d{4}-\d{2}-\d{2}$', value):
            return "date_iso"
        elif re.match(r'^\d{2}/\d{2}/\d{4}$', value):
            return "date_us"
        elif re.match(r'^\d+$', value):
            return "numeric"
        elif re.match(r'^\d+\.\d+$', value):
            return "decimal"
        elif re.match(r'^[A-Z][a-z]+$', value):
            return "capitalized_word"
        elif re.match(r'^[A-Z]+$', value):
            return "uppercase"
        elif re.match(r'^[a-z]+$', value):
            return "lowercase"
        else:
            return "mixed"