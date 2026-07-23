"""
Doc2DB - document-to-database API service.
Main application file: only app initialization and startup logic.
"""
import os
import sys
import json
import time
import logging
from flask import Flask, jsonify
from flask_cors import CORS
from pathlib import Path

from config import (
    BASE_DIR, UPLOAD_FOLDER, HISTORY_DIR, OUTPUT_DIR, 
    CORS_ORIGINS, PROJECT_VERSION, PROJECT_NAME, API_ENDPOINTS,
    WEBSOCKET_HOST, WEBSOCKET_PORT
)
from utils.websocket_utils import start_websocket_service
from routes import register_blueprints
from routes.doc2db_routes import set_doc2db_service

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from modules.services import Doc2DBService

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['JSON_SORT_KEYS'] = False

CORS(app, 
     origins=CORS_ORIGINS,  
     supports_credentials=True,
     allow_headers=["Content-Type", "Authorization"],
     methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"]
)

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(HISTORY_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

doc2db_service = Doc2DBService(output_dir=OUTPUT_DIR)
doc2db_service.history_dir = Path(HISTORY_DIR)
set_doc2db_service(doc2db_service)

websocket_thread = start_websocket_service(host=WEBSOCKET_HOST, port=WEBSOCKET_PORT)
register_blueprints(app)

@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check."""
    return jsonify({
        "status": "healthy",
        "timestamp": time.time()
    })


@app.route('/', methods=['GET'])
def home():
    """Home page."""
    return jsonify({
        "message": PROJECT_NAME,
        "version": PROJECT_VERSION,
        "endpoints": API_ENDPOINTS
    })


if __name__ == '__main__':
    logger.info(f"Starting Flask app...")
    logger.info(f"Upload folder: {app.config['UPLOAD_FOLDER']}")
    logger.info(f"History folder: {HISTORY_DIR}")
    logger.info(f"Output folder: {OUTPUT_DIR}")
    
    # Development features are opt-in and the server binds to loopback by default.
    debug = os.environ.get('FLASK_DEBUG', '0') == '1'
    use_reloader = os.environ.get('FLASK_AUTO_RELOAD', '0') == '1'
    host = os.environ.get('HOST', '127.0.0.1')
    port = int(os.environ.get('PORT', '5000'))
    
    app.run(
        debug=debug,
        host=host,
        port=port,
        use_reloader=use_reloader
    )
    
    if not use_reloader:
        logger.info("Auto-reload is disabled. Set FLASK_AUTO_RELOAD=1 to enable.")
