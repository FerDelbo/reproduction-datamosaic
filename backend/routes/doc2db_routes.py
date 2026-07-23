"""
Doc2DB processing API routes.
"""
import os
import json
import time
import logging
from datetime import datetime
from flask import Blueprint, request, jsonify, Response
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import HISTORY_DIR, OUTPUT_DIR, UPLOAD_FOLDER
from utils.history_utils import load_history_from_files, delete_history_file, delete_output_directory, save_task_to_history

logger = logging.getLogger(__name__)

doc2db_bp = Blueprint('doc2db', __name__)

doc2db_service = None

def set_doc2db_service(service):
    """Set the Doc2DB service instance."""
    global doc2db_service
    doc2db_service = service


@doc2db_bp.route('/doc2db/history', methods=['GET'])
@doc2db_bp.route('/projects/<project_id>/doc2db/history', methods=['GET'])
def get_doc2db_history(project_id=None):
    """Get Doc2DB processing history."""
    try:
        history = load_history_from_files(HISTORY_DIR)
        history.sort(key=lambda x: x.get("start_time", ""), reverse=True)
        return jsonify(history), 200
    except Exception as e:
        logger.error(f"Failed to get Doc2DB history: {str(e)}")
        return jsonify({"error": "Failed to get processing history"}), 500


@doc2db_bp.route('/doc2db/history/<task_id>/details', methods=['GET'])
@doc2db_bp.route('/projects/<project_id>/doc2db/history/<task_id>/details', methods=['GET'])
def get_doc2db_details(task_id, project_id=None):
    """Get detailed information for a specific processing task."""
    try:
        history_file = os.path.join(HISTORY_DIR, f"{task_id}.json")
        if os.path.exists(history_file):
            with open(history_file, 'r', encoding='utf-8') as f:
                history_data = json.load(f)
            
            result_file = os.path.join(OUTPUT_DIR, task_id, "result.json")
            result_loaded = False
            
            if os.path.exists(result_file):
                logger.info(f"Reading result.json for task {task_id}: {result_file}")
                try:
                    with open(result_file, 'r', encoding='utf-8') as f:
                        result_data = json.load(f)
                    
                    if result_data and isinstance(result_data, dict) and 'tables' in result_data:
                        tables = result_data.get('tables', {})
                        has_valid_data = any(
                            isinstance(table_rows, list) and len(table_rows) > 0 
                            for table_rows in tables.values()
                        )
                        
                        if has_valid_data:
                            history_data['run_id'] = task_id
                            
                            if 'result' not in history_data:
                                history_data['result'] = {}
                            history_data['result']['run_id'] = task_id
                            history_data['result']['result_data'] = result_data
                            
                            if 'result_context' not in history_data:
                                history_data['result_context'] = {}
                            history_data['result_context']['run_id'] = task_id
                            history_data['result_context']['result_data'] = result_data
                            
                            result_loaded = True
                        
                except Exception as e:
                    logger.error(f"Failed to read result.json: {str(e)}")
            
            if not result_loaded:
                snapshot_file = os.path.join(OUTPUT_DIR, task_id, "snapshots.jsonl")
                if os.path.exists(snapshot_file):
                    try:
                        snapshots = []
                        with open(snapshot_file, 'r', encoding='utf-8') as f:
                            for line in f:
                                line = line.strip()
                                if line:
                                    snapshots.append(json.loads(line))
                        
                        if snapshots:
                            formatted_snapshot = doc2db_service._format_snapshot_for_frontend(snapshots)
                            
                            history_data['run_id'] = task_id
                            
                            if 'result_context' not in history_data:
                                history_data['result_context'] = {}
                            history_data['result_context']['run_id'] = task_id
                            history_data['result_context']['snapshot'] = formatted_snapshot
                            
                            if 'result' not in history_data:
                                history_data['result'] = {}
                            history_data['result']['run_id'] = task_id
                            history_data['result']['snapshot'] = formatted_snapshot
                            
                    except Exception as e:
                        logger.error(f"Failed to read snapshot data: {str(e)}")
            from flask import Response
            return Response(
                json.dumps(history_data, ensure_ascii=False, indent=2, sort_keys=False),
                mimetype='application/json'
            ), 200
        
        if doc2db_service:
            progress = doc2db_service.get_task_progress(task_id)
            if progress:
                return jsonify(progress), 200
        
        return jsonify({"error": "Processing task not found"}), 404
        
    except Exception as e:
        logger.error(f"Failed to get processing details: {str(e)}")
        return jsonify({"error": "Failed to get processing details"}), 500


@doc2db_bp.route('/doc2db/history/<task_id>/delete', methods=['DELETE'])
@doc2db_bp.route('/projects/<project_id>/doc2db/history/<task_id>/delete', methods=['DELETE'])
def delete_doc2db_record(task_id, project_id=None):
    """Delete a Doc2DB processing record."""
    try:
        task_status = doc2db_service.get_task_status(task_id) if doc2db_service else None
        service_exists = task_status is not None
        
        history_file = os.path.join(HISTORY_DIR, f"{task_id}.json")
        file_exists = os.path.exists(history_file)
        
        output_dir = os.path.join(OUTPUT_DIR, task_id)
        output_exists = os.path.exists(output_dir)
        
        if not service_exists and not file_exists and not output_exists:
            return jsonify({"error": "Processing task not found"}), 404
        
        try:
            from websocket_signals import get_websocket_broadcaster
            broadcaster = get_websocket_broadcaster()
            if broadcaster:
                broadcaster.add_message_to_queue('task_deleted', {
                    'task_id': task_id,
                    'message': 'Task has been deleted',
                    'timestamp': datetime.now().isoformat()
                })
        except Exception as ws_error:
            logger.warning(f"WebSocket notification failed (non-critical): {ws_error}")
        
        if service_exists and doc2db_service:
            doc2db_service.cleanup_task(task_id)
        
        if file_exists:
            delete_history_file(task_id, HISTORY_DIR)
        
        if output_exists:
            delete_output_directory(task_id, OUTPUT_DIR)
        
        return jsonify({"message": "Deleted successfully"}), 200
    except Exception as e:
        logger.error(f"Failed to delete processing record: {str(e)}")
        return jsonify({"error": "Delete failed"}), 500


@doc2db_bp.route('/doc2db/schema/default', methods=['GET'])
@doc2db_bp.route('/projects/<project_id>/doc2db/schema/default', methods=['GET'])
def get_default_schema(project_id=None):
    """Get the default schema."""
    try:
        if not doc2db_service:
            return jsonify({"error": "Doc2DB service unavailable"}), 503
            
        table_name = request.args.get('table_name', 'orders')
        schema = doc2db_service.create_default_schema(table_name)
        return jsonify(schema), 200
    except Exception as e:
        logger.error(f"Failed to get default schema: {e}")
        return jsonify({"error": f"Failed to get default schema: {str(e)}"}), 500


@doc2db_bp.route('/doc2db/process', methods=['POST'])
@doc2db_bp.route('/projects/<project_id>/doc2db/process', methods=['POST'])
def start_doc2db_processing(project_id=None):
    """Start Doc2DB processing."""
    try:
        if not doc2db_service:
            return jsonify({"error": "Doc2DB service unavailable"}), 503
            
        data = request.get_json()
        if not data:
            return jsonify({"error": "No request data provided"}), 400
        
        file_paths = data.get('files', [])
        schema = data.get('schema')
        schema_original = data.get('schema', '')
        table_name = data.get('table_name', 'orders')
        nl_prompt = data.get('nl_prompt', '')
        user_query = data.get('user_query', '')
        input_mode = data.get('input_mode', 'schema')
        schema_mode = data.get('schema_mode', 'form')
        model = data.get('model', 'gpt-4o')
        processing_mode = data.get('processing_mode', 'auto')
        max_concurrent_tables = data.get('max_concurrent_tables', 3)
        document_mode = data.get('document_mode', 'single')
        
        if not file_paths:
            return jsonify({"error": "No files provided"}), 400
        
        if not schema and input_mode != 'instruction':
            return jsonify({"error": "No schema provided"}), 400
        
        full_file_paths = []
        for file_path in file_paths:
            if not os.path.isabs(file_path):
                full_path = os.path.join(UPLOAD_FOLDER, file_path)
            else:
                full_path = file_path
                
            if not os.path.exists(full_path):
                return jsonify({"error": f"File not found: {file_path}"}), 400
            
            full_file_paths.append(full_path)
        
        request_data = {
            'files': file_paths,
            'schema': schema_original,
            'table_name': table_name,
            'nl_prompt': nl_prompt,
            'input_mode': input_mode,
            'schema_mode': schema_mode,
            'model': model,
            'user_query': user_query,
            'processing_mode': processing_mode,
            'max_concurrent_tables': max_concurrent_tables,
            'document_mode': document_mode
        }
        
        task_id = doc2db_service.start_processing_async(
            documents=full_file_paths,
            schema=schema,
            table_name=table_name,
            nl_prompt=nl_prompt,
            user_query=user_query,
            model=model,
            request_data=request_data,
            processing_mode=processing_mode,
            max_concurrent_tables=max_concurrent_tables,
            document_mode=document_mode
        )
        
        return jsonify({
            "task_id": task_id,
            "status": "started",
            "message": "Processing started"
        }), 200
        
    except Exception as e:
        logger.error(f"Failed to start Doc2DB processing: {e}")
        return jsonify({"error": f"Failed to start processing: {str(e)}"}), 500


@doc2db_bp.route('/doc2db/status/<task_id>', methods=['GET'])
@doc2db_bp.route('/projects/<project_id>/doc2db/status/<task_id>', methods=['GET'])
def get_doc2db_status(task_id, project_id=None):
    """Get Doc2DB processing status."""
    try:
        if not doc2db_service:
            return jsonify({"error": "Doc2DB service unavailable"}), 503
            
        progress = doc2db_service.get_task_progress(task_id)
        
        if progress is None:
            logger.debug(f"Task not found: {task_id} (may have been deleted)")
            return jsonify({"error": "Task not found"}), 404
        
        return jsonify(progress), 200
        
    except Exception as e:
        logger.error(f"Failed to get Doc2DB status: {e}")
        return jsonify({"error": f"Failed to get status: {str(e)}"}), 500


@doc2db_bp.route('/doc2db/stream/<task_id>', methods=['GET'])
@doc2db_bp.route('/projects/<project_id>/doc2db/stream/<task_id>', methods=['GET'])
def stream_doc2db_status(task_id, project_id=None):
    """Stream Doc2DB processing status via SSE."""
    def generate():
        try:
            if not doc2db_service:
                yield f"event: error\ndata: {json.dumps({'error': 'Doc2DB service unavailable'}, ensure_ascii=False, sort_keys=False)}\n\n"
                return
                
            progress_queue = doc2db_service.task_queues.get(task_id)
            
            if progress_queue is None:
                logger.error(f"Task queue not found: {task_id}")
                yield f"event: error\ndata: {json.dumps({'error': 'Task not found'}, ensure_ascii=False, sort_keys=False)}\n\n"
                return
            
            yield f"event: start\ndata: {json.dumps({'message': 'Started streaming task status', 'task_id': task_id}, ensure_ascii=False, sort_keys=False)}\n\n"
            
            import time
            from collections import deque
            buffer_pool = deque()
            buffer_interval = 0.5
            last_send_time = time.time()
            buffer_counter = 0
            
            next_send_time = time.time() + buffer_interval
            task_completed = False
            
            while not task_completed:
                try:
                    current_time = time.time()
                    
                    while current_time < next_send_time:
                        remaining_time = next_send_time - current_time
                        try:
                            message = progress_queue.get(timeout=min(remaining_time, 0.1))
                            buffer_pool.append(message)
                            
                            if message.get('type') == 'final_status':
                                task_completed = True
                                break
                                
                        except:
                            pass
                        
                        current_time = time.time()
                    
                    if buffer_pool:
                        buffer_counter += 1
                        batch_messages = list(buffer_pool)
                        buffer_pool.clear()
                        
                        for i, message in enumerate(batch_messages):
                            message_type = message.get('type', 'update')
                            step_name = message.get('step', 'N/A')
                            
                            if message_type == 'step_completed':
                                step_data = {
                                    'step': message.get('step'),
                                    'description': message.get('description', ''),
                                    'status': message.get('status', 'completed'),
                                    'timestamp': message.get('timestamp'),
                                    'details': message.get('details', {})
                                }
                                
                                yield f"event: step\ndata: {json.dumps(step_data, ensure_ascii=False, sort_keys=False)}\n\n"
                                
                                if i < len(batch_messages) - 1:
                                    time.sleep(0.2)
                                
                            elif message_type == 'final_status':
                                final_data = {
                                    'status': message.get('status'),
                                    'result': message.get('result'),
                                    'final_stats': message.get('final_stats', {})
                                }
                                yield f"event: complete\ndata: {json.dumps(final_data, ensure_ascii=False, sort_keys=False)}\n\n"
                                task_completed = True
                                
                                if i < len(batch_messages) - 1:
                                    time.sleep(0.2)
                                
                            else:
                                message_data = {
                                    'type': message_type,
                                    'content': message
                                }
                                yield f"event: message\ndata: {json.dumps(message_data, ensure_ascii=False, sort_keys=False)}\n\n"
                                
                                if i < len(batch_messages) - 1:
                                    time.sleep(0.2)
                        
                        if task_completed:
                            break
                        
                        next_send_time = time.time() + buffer_interval
                        
                    else:
                        next_send_time = time.time() + buffer_interval
                    
                    if task_id in doc2db_service.running_tasks:
                        task_status = doc2db_service.running_tasks[task_id].get('status')
                        if task_status in ['completed', 'failed'] and not buffer_pool and progress_queue.empty():
                            task_completed = True
                    
                except Exception as inner_e:
                    logger.error(f"Inner loop error: {str(inner_e)}")
                    time.sleep(0.5)
            
            yield f"event: end\ndata: {json.dumps({'message': 'Streaming ended'}, ensure_ascii=False, sort_keys=False)}\n\n"
            
        except Exception as e:
            logger.error(f"Streaming status output error: {str(e)}")
            error_data = {'error': f'Streaming output error: {str(e)}'}
            yield f"event: error\ndata: {json.dumps(error_data, ensure_ascii=False, sort_keys=False)}\n\n"
    
    response = Response(generate(), mimetype='text/event-stream')
    response.headers.update({
        'Cache-Control': 'no-cache, no-store, must-revalidate',
        'Pragma': 'no-cache',
        'Expires': '0',
        'Connection': 'keep-alive',
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Methods': 'GET',
        'Access-Control-Allow-Headers': 'Cache-Control',
        'X-Accel-Buffering': 'no',
        'Content-Encoding': 'identity'
    })
    
    return response


@doc2db_bp.route('/doc2db/result/<task_id>', methods=['GET'])
@doc2db_bp.route('/projects/<project_id>/doc2db/result/<task_id>', methods=['GET'])
def get_doc2db_result(task_id, project_id=None):
    """Get the Doc2DB processing result."""
    try:
        if not doc2db_service:
            return jsonify({"error": "Doc2DB service unavailable"}), 503
            
        task_status = doc2db_service.get_task_status(task_id)
        
        if task_status is None:
            return jsonify({"error": "Task not found"}), 404
        
        if task_status["status"] != "completed":
            return jsonify({
                "error": "Task not yet completed",
                "status": task_status["status"]
            }), 400
        
        progress = doc2db_service.get_task_progress(task_id)
        
        if progress and 'result' in progress:
            return jsonify(progress['result']), 200
        else:
            return jsonify({"error": "Result unavailable"}), 500
        
    except Exception as e:
        logger.error(f"Failed to get Doc2DB result: {e}")
        return jsonify({"error": f"Failed to get result: {str(e)}"}), 500
