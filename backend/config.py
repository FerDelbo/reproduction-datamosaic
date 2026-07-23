"""
Application configuration.
"""
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
HISTORY_DIR = os.path.join(BASE_DIR, 'history')
OUTPUT_DIR = os.path.join(BASE_DIR, 'output')

CORS_ORIGINS = [
    "http://localhost:3000", "http://127.0.0.1:3000",
    "http://localhost:3001", "http://127.0.0.1:3001"
]

ALLOWED_EXTENSIONS = {'pdf', 'txt', 'md', 'csv', 'xlsx', 'xls', 'docx', 'doc', 'json', 'jsonl'}

WEBSOCKET_HOST = "localhost"
WEBSOCKET_PORT = 8765

PROJECT_VERSION = "1.0.0"
PROJECT_NAME = "Doc2DB - document-to-database API service"

API_ENDPOINTS = [
    "GET /api/health - health check",
    "GET /api/files - list files", 
    "POST /api/upload - upload a single file",
    "POST /api/upload/batch - upload files in batch",
    "POST /api/files/delete - delete a file",
    "GET /api/files/content - get file content",
    "POST /api/doc2db/process - start a Doc2DB processing task",
    "GET /api/doc2db/status/<task_id> - get processing status",
    "GET /api/doc2db/result/<task_id> - get processing result",
    "GET /api/doc2db/schema/default - get default schema",
    "GET /api/doc2db/history - get Doc2DB processing history"
]
