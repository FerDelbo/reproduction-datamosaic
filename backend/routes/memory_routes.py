"""
Memory API routes.
"""
import logging
import json
from flask import Blueprint, request, jsonify, Response

logger = logging.getLogger(__name__)

memory_bp = Blueprint('memory', __name__)


@memory_bp.route('/memory/snapshots/<run_id>', methods=['GET'])
def get_memory_snapshots(run_id):
    """Get snapshot data for a given run ID."""
    try:
        table_name = request.args.get('table_name')
        
        from modules.agents.orchestrator import create_signal_driven_orchestrator
        orchestrator = create_signal_driven_orchestrator()
        
        snapshots_data = orchestrator.get_memory_snapshots(run_id, table_name)
        
        json_str = json.dumps(snapshots_data, ensure_ascii=False, sort_keys=False)
        return Response(json_str, mimetype='application/json')
    except Exception as e:
        logger.error(f"Failed to get memory snapshots: {str(e)}")
        return jsonify({'error': str(e)}), 500


@memory_bp.route('/memory/violations/<run_id>', methods=['GET'])
def get_memory_violations(run_id):
    """Get violation data for a given run ID."""
    try:
        table_name = request.args.get('table_name')
        
        from modules.agents.orchestrator import create_signal_driven_orchestrator
        orchestrator = create_signal_driven_orchestrator()
        
        violations_data = orchestrator.get_memory_violations(run_id, table_name)
        
        json_str = json.dumps(violations_data, ensure_ascii=False, sort_keys=False)
        return Response(json_str, mimetype='application/json')
    except Exception as e:
        logger.error(f"Failed to get memory violations: {str(e)}")
        return jsonify({'error': str(e)}), 500


@memory_bp.route('/memory/fixes/<run_id>', methods=['GET'])
def get_memory_fixes(run_id):
    """Get fix data for a given run ID."""
    try:
        table_name = request.args.get('table_name')
        
        from modules.agents.orchestrator import create_signal_driven_orchestrator
        orchestrator = create_signal_driven_orchestrator()
        
        fixes_data = orchestrator.get_memory_fixes(run_id, table_name)
        
        json_str = json.dumps(fixes_data, ensure_ascii=False, sort_keys=False)
        return Response(json_str, mimetype='application/json')
    except Exception as e:
        logger.error(f"Failed to get memory fixes: {str(e)}")
        return jsonify({'error': str(e)}), 500


@memory_bp.route('/memory/summary/<run_id>', methods=['GET'])
def get_memory_summary(run_id):
    """Get summary data for a given run ID."""
    try:
        from modules.agents.orchestrator import create_signal_driven_orchestrator
        orchestrator = create_signal_driven_orchestrator()
        
        summary_data = orchestrator.get_memory_summary(run_id)
        
        json_str = json.dumps(summary_data, ensure_ascii=False, sort_keys=False)
        return Response(json_str, mimetype='application/json')
    except Exception as e:
        logger.error(f"Failed to get memory summary: {str(e)}")
        return jsonify({'error': str(e)}), 500
