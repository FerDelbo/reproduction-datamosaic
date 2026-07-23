"""
Database management API routes.
"""
import os
import json
import sqlite3
import pandas as pd
import uuid
import logging
from datetime import datetime
from flask import Blueprint, request, jsonify, send_file
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import BASE_DIR

logger = logging.getLogger(__name__)

database_bp = Blueprint('database', __name__)


def get_project_path(project_id):
    """Get the project path."""
    if project_id:
        return os.path.join(BASE_DIR, 'projects', project_id)
    return BASE_DIR


def get_database_file_path(project_id, database_id):
    """Get the database file path."""
    project_path = get_project_path(project_id)
    return os.path.join(project_path, 'databases', f'{database_id}.db')


def load_database_metadata(project_id):
    """Load database metadata."""
    project_path = get_project_path(project_id)
    metadata_path = os.path.join(project_path, 'databases', 'metadata.json')
    
    if os.path.exists(metadata_path):
        try:
            with open(metadata_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load database metadata: {str(e)}")
    
    return {}


def save_database_metadata(project_id, metadata):
    """Save database metadata."""
    project_path = get_project_path(project_id)
    databases_dir = os.path.join(project_path, 'databases')
    os.makedirs(databases_dir, exist_ok=True)
    
    metadata_path = os.path.join(databases_dir, 'metadata.json')
    
    try:
        with open(metadata_path, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Failed to save database metadata: {str(e)}")
        raise


@database_bp.route('/databases', methods=['GET'])
@database_bp.route('/projects/<project_id>/databases', methods=['GET'])
def get_databases(project_id=None):
    """Get the list of databases."""
    try:
        metadata = load_database_metadata(project_id)
        databases = []
        
        for db_id, db_info in metadata.items():
            db_path = get_database_file_path(project_id, db_id)
            
            tables = []
            if os.path.exists(db_path):
                try:
                    conn = sqlite3.connect(db_path)
                    cursor = conn.cursor()
                    
                    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
                    table_names = cursor.fetchall()
                    
                    for (table_name,) in table_names:
                        cursor.execute(f"SELECT COUNT(*) FROM `{table_name}`")
                        row_count = cursor.fetchone()[0]
                        
                        tables.append({
                            'name': table_name,
                            'row_count': row_count
                        })
                    
                    conn.close()
                except Exception as e:
                    logger.error(f"Failed to get database table info: {str(e)}")
            
            databases.append({
                'id': db_id,
                'name': db_info.get('name', db_id),
                'display_name': db_info.get('display_name', db_info.get('name', db_id)),
                'description': db_info.get('description', ''),
                'created_at': db_info.get('created_at', ''),
                'last_modified': db_info.get('last_modified', ''),
                'tables': tables
            })
        
        return jsonify({"databases": databases}), 200
    except Exception as e:
        logger.error(f"Failed to get database list: {str(e)}")
        return jsonify({"error": "Failed to get database list"}), 500


@database_bp.route('/projects/<project_id>/databases', methods=['POST'])
def create_database(project_id):
    """Create a new database."""
    try:
        data = request.json
        name = data.get('name', '').strip()
        display_name = data.get('display_name', name).strip()
        description = data.get('description', '').strip()
        
        if not name:
            return jsonify({'error': 'Database name cannot be empty'}), 400
        
        database_id = str(uuid.uuid4())
        
        db_path = get_database_file_path(project_id, database_id)
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        
        conn = sqlite3.connect(db_path)
        conn.close()
        
        metadata = load_database_metadata(project_id)
        metadata[database_id] = {
            'name': name,
            'display_name': display_name,
            'description': description,
            'created_at': datetime.now().isoformat(),
            'last_modified': datetime.now().isoformat()
        }
        save_database_metadata(project_id, metadata)
        
        logger.info(f"Database created successfully: {name} (ID: {database_id})")
        
        return jsonify({
            'success': True,
            'database': {
                'id': database_id,
                'name': name,
                'display_name': display_name,
                'description': description,
                'created_at': metadata[database_id]['created_at'],
                'last_modified': metadata[database_id]['last_modified'],
                'tables': []
            }
        }), 201
        
    except Exception as e:
        logger.error(f"Failed to create database: {str(e)}")
        return jsonify({'error': str(e)}), 500


@database_bp.route('/projects/<project_id>/databases/<database_id>/tables', methods=['GET'])
def get_database_tables(project_id, database_id):
    """Get the list of tables in a database."""
    try:
        db_path = get_database_file_path(project_id, database_id)
        if not os.path.exists(db_path):
            return jsonify({'error': 'Database not found'}), 404
        
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
        table_names = [row[0] for row in cursor.fetchall()]
        
        tables = []
        for table_name in table_names:
            cursor.execute(f"PRAGMA table_info({table_name})")
            columns_info = cursor.fetchall()
            columns = []
            for col_info in columns_info:
                columns.append({
                    'name': col_info[1],
                    'type': col_info[2],
                    'not_null': bool(col_info[3]),
                    'primary_key': bool(col_info[5])
                })
            
            cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
            row_count = cursor.fetchone()[0]
            
            tables.append({
                'name': table_name,
                'columns': columns,
                'row_count': row_count
            })
        
        conn.close()
        
        return jsonify({'tables': tables})
    
    except Exception as e:
        logger.error(f"Failed to get table list: {str(e)}")
        return jsonify({'error': str(e)}), 500


@database_bp.route('/projects/<project_id>/databases/<database_id>/tables/<table_name>/data', methods=['GET'])
def get_table_data(project_id, database_id, table_name):
    """Get table data."""
    try:
        page = int(request.args.get('page', 1))
        page_size = int(request.args.get('page_size', 25))
        
        db_path = get_database_file_path(project_id, database_id)
        if not os.path.exists(db_path):
            return jsonify({'error': 'Database not found'}), 404
        
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,))
        if not cursor.fetchone():
            conn.close()
            return jsonify({'error': 'Table not found'}), 404
        
        cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
        total_count = cursor.fetchone()[0]
        
        cursor.execute(f"PRAGMA table_info({table_name})")
        columns_info = cursor.fetchall()
        columns = [{'name': col_info[1], 'type': col_info[2]} for col_info in columns_info]
        
        offset = (page - 1) * page_size
        cursor.execute(f"SELECT * FROM {table_name} LIMIT ? OFFSET ?", (page_size, offset))
        rows = cursor.fetchall()
        
        data = []
        for row in rows:
            row_dict = {}
            for i, col in enumerate(columns):
                row_dict[col['name']] = row[i]
            data.append(row_dict)
        
        conn.close()
        
        total_pages = (total_count + page_size - 1) // page_size
        
        return jsonify({
            'data': data,
            'columns': columns,
            'pagination': {
                'page': page,
                'page_size': page_size,
                'total_count': total_count,
                'total_pages': total_pages
            }
        })
    
    except Exception as e:
        logger.error(f"Failed to get table data: {str(e)}")
        return jsonify({'error': str(e)}), 500


@database_bp.route('/projects/<project_id>/databases/<database_id>/export', methods=['GET'])
def export_database(project_id, database_id):
    """Export a database file."""
    try:
        db_path = get_database_file_path(project_id, database_id)
        if not os.path.exists(db_path):
            return jsonify({'error': 'Database not found'}), 404
        
        metadata = load_database_metadata(project_id)
        db_name = metadata.get(database_id, {}).get('name', database_id)
        
        return send_file(
            db_path,
            as_attachment=True,
            download_name=f"{db_name}.db",
            mimetype='application/octet-stream'
        )
    
    except Exception as e:
        logger.error(f"Failed to export database: {str(e)}")
        return jsonify({'error': str(e)}), 500


@database_bp.route('/projects/<project_id>/databases/<database_id>', methods=['DELETE'])
def delete_database(project_id, database_id):
    """Delete a database."""
    try:
        db_path = get_database_file_path(project_id, database_id)
        
        if os.path.exists(db_path):
            os.remove(db_path)
        
        metadata = load_database_metadata(project_id)
        if database_id in metadata:
            del metadata[database_id]
            save_database_metadata(project_id, metadata)
        
        logger.info(f"Deleted database: {database_id}")
        return jsonify({'success': True, 'message': 'Database deleted successfully'})
    
    except Exception as e:
        logger.error(f"Failed to delete database: {str(e)}")
        return jsonify({'error': str(e)}), 500


@database_bp.route('/projects/<project_id>/databases/<database_id>/tables', methods=['POST'])
def create_table_from_data(project_id, database_id):
    """Create a database table from tabular data."""
    try:
        data = request.json
        table_name = data.get('table_name', '').strip()
        table_data = data.get('table_data', [])
        merge_mode = data.get('merge_mode', 'create_new')  # 'create_new' or 'append'
        
        if not table_name or not table_data:
            return jsonify({'error': 'Table name and data cannot be empty'}), 400
        
        db_path = get_database_file_path(project_id, database_id)
        if not os.path.exists(db_path):
            return jsonify({'error': 'Database not found'}), 404
        
        df = pd.DataFrame(table_data)
        
        conn = sqlite3.connect(db_path)
        
        if merge_mode == 'append':
            df.to_sql(table_name, conn, if_exists='append', index=False)
        else:
            df.to_sql(table_name, conn, if_exists='replace', index=False)
        
        conn.close()
        
        metadata = load_database_metadata(project_id)
        if database_id in metadata:
            metadata[database_id]['last_modified'] = datetime.now().isoformat()
            save_database_metadata(project_id, metadata)
        
        logger.info(f"Created/updated table {table_name} in database {database_id}")
        
        return jsonify({
            'success': True,
            'message': f'Table {table_name} {"updated" if merge_mode == "append" else "created"} successfully',
            'table_name': table_name,
            'row_count': len(table_data)
        })
    
    except Exception as e:
        logger.error(f"Failed to create table: {str(e)}")
        return jsonify({'error': str(e)}), 500
