"""
File management API routes.
"""
import os
import logging
from flask import Blueprint, request, jsonify
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import UPLOAD_FOLDER, ALLOWED_EXTENSIONS, OUTPUT_DIR
from utils.file_utils import allowed_file, safe_filename

logger = logging.getLogger(__name__)

file_bp = Blueprint('file', __name__)


@file_bp.route('/files', methods=['GET'])
@file_bp.route('/projects/<project_id>/files', methods=['GET'])
def list_files(project_id=None):
    """Get the list of files."""
    files = []
    
    if os.path.exists(UPLOAD_FOLDER):
        for filename in os.listdir(UPLOAD_FOLDER):
            if allowed_file(filename, ALLOWED_EXTENSIONS):
                filepath = os.path.join(UPLOAD_FOLDER, filename)
                files.append({
                    "filename": filename,
                    "filepath": filepath,
                    "size": os.path.getsize(filepath)
                })
    
    return jsonify({"files": files}), 200


@file_bp.route('/upload', methods=['POST'])
def upload_file():
    """Upload a single file."""
    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400
    
    file = request.files['file']
    
    if file.filename == '':
        return jsonify({"error": "No file selected"}), 400
    
    if file and allowed_file(file.filename, ALLOWED_EXTENSIONS):
        filename = safe_filename(file.filename)
        filepath = os.path.join(UPLOAD_FOLDER, filename)
        
        if os.path.exists(filepath):
            return jsonify({
                "status": "exists",
                "message": f"File '{filename}' already exists",
                "filename": filename,
                "filepath": filepath
            }), 409
        
        file.save(filepath)
        return jsonify({
            "status": "success",
            "message": "File uploaded successfully",
            "filename": filename,
            "filepath": filepath
        }), 200
    else:
        return jsonify({"error": "File type not allowed"}), 400


@file_bp.route('/upload/batch', methods=['POST'])
@file_bp.route('/projects/<project_id>/upload/batch', methods=['POST'])
def upload_batch_files(project_id=None):
    """Upload files in batch."""
    uploaded_files = []
    failed_files = []
    existing_files = []
    
    files = request.files.getlist('files')
    if not files or all(file.filename == '' for file in files):
        return jsonify({"error": "No files selected"}), 400
    
    for file in files:
        if file.filename == '':
            continue
            
        if file and allowed_file(file.filename, ALLOWED_EXTENSIONS):
            original_filename = file.filename
            
            if '/' in original_filename or '\\' in original_filename:
                base_filename = os.path.basename(original_filename)
                filename = safe_filename(base_filename)
            else:
                filename = safe_filename(original_filename)
                
            filepath = os.path.join(UPLOAD_FOLDER, filename)
            
            if os.path.exists(filepath):
                name, ext = os.path.splitext(filename)
                counter = 1
                
                while os.path.exists(filepath):
                    new_filename = f"{name}_{counter}{ext}"
                    filepath = os.path.join(UPLOAD_FOLDER, new_filename)
                    counter += 1
                
                filename = new_filename
            
            try:
                file.save(filepath)
                uploaded_files.append({
                    "filename": filename,
                    "original_filename": original_filename,
                    "filepath": filepath,
                    "size": os.path.getsize(filepath)
                })
            except Exception as e:
                logger.error(f"Failed to save file {filename}: {str(e)}")
                failed_files.append({
                    "filename": original_filename,
                    "error": str(e)
                })
        else:
            failed_files.append({
                "filename": file.filename,
                "error": "File type not allowed"
            })
    
    response_data = {
        "status": "completed",
        "uploaded": uploaded_files,
        "failed": failed_files,
        "existing": existing_files,
        "summary": {
            "total": len(files),
            "uploaded_count": len(uploaded_files),
            "failed_count": len(failed_files),
            "existing_count": len(existing_files)
        }
    }
    
    if uploaded_files and not failed_files:
        response_data["status"] = "success"
        response_data["message"] = f"Successfully uploaded {len(uploaded_files)} files"
    elif uploaded_files:
        response_data["status"] = "partial"
        response_data["message"] = f"Uploaded {len(uploaded_files)} files, {len(failed_files)} failed"
    else:
        response_data["status"] = "error"
        response_data["message"] = "No files were uploaded successfully"
        return jsonify(response_data), 400
    
    return jsonify(response_data), 200


@file_bp.route('/files/delete', methods=['POST'])
@file_bp.route('/projects/<project_id>/files/delete', methods=['POST'])
def delete_file(project_id=None):
    """Delete a file."""
    data = request.json
    
    if not data or 'filepath' not in data:
        return jsonify({"error": "No filepath provided"}), 400
    
    filepath = data['filepath']
    
    try:
        if not os.path.abspath(filepath).startswith(os.path.abspath(UPLOAD_FOLDER)):
            return jsonify({"error": "File path not allowed"}), 403
            
        if os.path.exists(filepath) and os.path.isfile(filepath):
            os.remove(filepath)
            return jsonify({"message": "File deleted successfully"}), 200
        else:
            return jsonify({"error": "File not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@file_bp.route('/files/content', methods=['GET'])
@file_bp.route('/projects/<project_id>/files/content', methods=['GET'])
def get_file_content(project_id=None):
    """Get file content."""
    filepath = request.args.get('filepath')
    
    if not filepath:
        return jsonify({"error": "No filepath provided"}), 400
    
    try:
        abs_filepath = os.path.abspath(filepath)
        allowed_dirs = [
            os.path.abspath(UPLOAD_FOLDER),
            os.path.abspath(OUTPUT_DIR)
        ]
        
        if not any(abs_filepath.startswith(allowed_dir) for allowed_dir in allowed_dirs):
            logger.warning(f"File access denied: {filepath}, allowed directories: {allowed_dirs}")
            return jsonify({"error": "File path not allowed"}), 403
        
        if not os.path.exists(filepath) or not os.path.isfile(filepath):
            return jsonify({"error": "File not found"}), 404
        
        filename = os.path.basename(filepath)
        if not allowed_file(filename, ALLOWED_EXTENSIONS):
            return jsonify({"error": "File type not supported"}), 400
        
        file_extension = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
        
        if file_extension in ['txt', 'md', 'csv', 'json', 'jsonl']:
            try:
                encodings = ['utf-8', 'gbk', 'gb2312', 'latin-1']
                content = None
                used_encoding = None
                
                for encoding in encodings:
                    try:
                        with open(filepath, 'r', encoding=encoding) as f:
                            content = f.read()
                        used_encoding = encoding
                        break
                    except UnicodeDecodeError:
                        continue
                
                if content is None:
                    return jsonify({"error": "Unable to decode file"}), 500
                
                return jsonify({
                    "content": content,
                    "filename": filename,
                    "file_type": file_extension,
                    "encoding": used_encoding
                }), 200
                
            except Exception as e:
                logger.error(f"Failed to read text file: {filepath}, error: {str(e)}")
                return jsonify({"error": f"Failed to read text file: {str(e)}"}), 500
        
        elif file_extension == 'pdf':
            return jsonify({
                "content": "[PDF file content] - please open this file with a dedicated PDF reader",
                "filename": filename,
                "file_type": file_extension
            }), 200
        
        elif file_extension in ['xlsx', 'xls']:
            try:
                import pandas as pd
                df = pd.read_excel(filepath)
                csv_content = df.to_csv(index=False)
                
                return jsonify({
                    "content": csv_content,
                    "filename": filename,
                    "file_type": "csv"
                }), 200
                
            except Exception as e:
                return jsonify({"error": f"Failed to read Excel file: {str(e)}"}), 500
        
        elif file_extension in ['docx', 'doc']:
            return jsonify({
                "content": "[Word document content] - please open this file with Word or a compatible application",
                "filename": filename,
                "file_type": file_extension
            }), 200
        
        else:
            return jsonify({"error": f"Unsupported file type: {file_extension}"}), 400
    
    except Exception as e:
        return jsonify({"error": f"Failed to read file: {str(e)}"}), 500
