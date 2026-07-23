"""
History-record utility functions.
"""
import os
import json
import time
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def resolve_display_table_name(table_name: str = '', schema=None) -> str:
    """Build a display name for history lists."""
    if table_name and str(table_name).strip():
        return str(table_name).strip()

    parsed_schema = schema
    if isinstance(parsed_schema, str) and parsed_schema.strip():
        try:
            parsed_schema = json.loads(parsed_schema)
        except json.JSONDecodeError:
            parsed_schema = None

    if isinstance(parsed_schema, dict):
        tables = parsed_schema.get('tables') or []
        names = [
            table.get('name', '').strip()
            for table in tables
            if isinstance(table, dict) and table.get('name', '').strip()
        ]
        if len(names) == 1:
            return names[0]
        if len(names) > 1:
            return '_'.join(names)
        legacy_name = parsed_schema.get('table_name')
        if legacy_name and str(legacy_name).strip():
            return str(legacy_name).strip()

    return 'unknown'


def save_task_to_history(task_id, status_data, history_dir):
    """Save task status to a history file."""
    try:
        history_file = os.path.join(history_dir, f"{task_id}.json")
        with open(history_file, 'w', encoding='utf-8') as f:
            json.dump(status_data, f, ensure_ascii=False, indent=2)
        logger.info(f"Saved task {task_id} to history")
    except Exception as e:
        logger.error(f"Failed to save task history: {str(e)}")


def load_history_from_files(history_dir):
    """Load history records from files."""
    try:
        history = []
        if not os.path.exists(history_dir):
            return history
            
        for filename in os.listdir(history_dir):
            if filename.endswith('.json'):
                filepath = os.path.join(history_dir, filename)
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        status_data = json.load(f)
                    
                    result = status_data.get('result') or {}
                    summary = result.get('summary') or {}
                    request = status_data.get('request') or {}
                    display_table_name = resolve_display_table_name(
                        summary.get('table_name') or status_data.get('table_name', ''),
                        request.get('schema')
                    )
                    
                    history_item = {
                        "id": filename.replace('.json', ''),
                        "title": f"Doc2DB processing - {display_table_name}",
                        "status": status_data.get('status', 'unknown'),
                        "start_time": _format_time_safe(status_data.get('start_time')),
                        "end_time": _format_time_safe(status_data.get('end_time')),
                        "total_rows": summary.get('total_rows', 0),
                        "table_name": display_table_name,
                        "schema": request.get('schema', ''),
                        "violations_count": summary.get('violations_found', 0),
                        "fixes_count": summary.get('fixes_applied', 0)
                    }
                    history.append(history_item)
                except Exception as e:
                    logger.error(f"Failed to read history file {filename}: {str(e)}")
                    continue
        
        history.sort(key=lambda x: x.get("start_time", ""), reverse=True)
        return history
    except Exception as e:
        logger.error(f"Failed to load history records: {str(e)}")
        return []


def delete_history_file(task_id, history_dir):
    """Delete a history-record file."""
    try:
        history_file = os.path.join(history_dir, f"{task_id}.json")
        if os.path.exists(history_file):
            os.remove(history_file)
            logger.info(f"Deleted history file for task {task_id}")
            return True
        else:
            logger.warning(f"History file not found: {task_id}")
            return False
    except Exception as e:
        logger.error(f"Failed to delete history file: {str(e)}")
        return False


def delete_output_directory(task_id, output_dir):
    """Delete the task_id folder in the output directory."""
    try:
        output_dir_path = os.path.join(output_dir, task_id)
        if os.path.exists(output_dir_path) and os.path.isdir(output_dir_path):
            import shutil
            shutil.rmtree(output_dir_path)
            logger.info(f"Deleted output directory for task {task_id}")
            return True
        else:
            logger.warning(f"Output directory not found: {task_id}")
            return False
    except Exception as e:
        logger.error(f"Failed to delete output directory: {str(e)}")
        return False


def _format_time_safe(time_value):
    """Normalize a time field, accepting both string and numeric formats."""
    if not time_value:
        return None
    try:
        if isinstance(time_value, str):
            if '.' in time_value:
                time_value = time_value.split('.')[0]
            if not time_value.endswith('Z'):
                time_value = time_value + 'Z'
            return time_value
        else:
            return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.localtime(time_value))
    except:
        return None
