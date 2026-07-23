"""
Settings management API routes.
"""
import os
import sys
import logging
from flask import Blueprint, request, jsonify

logger = logging.getLogger(__name__)

settings_bp = Blueprint('settings', __name__)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LLM_DIR = os.path.join(PROJECT_ROOT, 'llm')
LLM_ENV_PATH = os.path.join(LLM_DIR, '.env')


@settings_bp.route('/settings', methods=['GET', 'POST'])
def handle_settings():
    """Get or update model settings."""
    
    if request.method == 'GET':
        try:
            if PROJECT_ROOT not in sys.path:
                sys.path.append(PROJECT_ROOT)
            
            try:
                from llm.global_config import get_model
                current_model = get_model()
            except ImportError:
                current_model = 'gpt-4o'  # default model
            
            env_path = LLM_ENV_PATH
            env_settings = {}
            if os.path.exists(env_path):
                with open(env_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if line and '=' in line and not line.startswith('#'):
                            key, value = line.split('=', 1)
                            env_settings[key.strip()] = value.strip()
            
            settings = {
                'model': current_model,
                'api_key_configured': bool(env_settings.get('API_KEY')),
                'api_url': env_settings.get('API_URL', '')
            }
            
            logger.info("Retrieved model settings (API key configured: %s)", settings['api_key_configured'])
            return jsonify(settings)
        except Exception as e:
            logger.error(f"Error reading settings: {str(e)}")
            return jsonify({'error': str(e)}), 500
    
    elif request.method == 'POST':
        try:
            data = request.json
            
            if 'model' in data:
                if PROJECT_ROOT not in sys.path:
                    sys.path.append(PROJECT_ROOT)
                
                try:
                    from llm.global_config import set_model
                    set_model(data['model'])
                    logger.info(f"Model setting updated to: {data['model']}")
                except ImportError:
                    logger.warning("Could not import the global_config module")
            
            if 'api_key' in data or 'api_url' in data:
                env_path = LLM_ENV_PATH
                env_content = {}
                
                if os.path.exists(env_path):
                    with open(env_path, 'r', encoding='utf-8') as f:
                        for line in f:
                            line = line.strip()
                            if line and '=' in line and not line.startswith('#'):
                                key, value = line.split('=', 1)
                                env_content[key.strip()] = value.strip()
                
                if data.get('api_key'):
                    env_content["API_KEY"] = data['api_key']
                if 'api_url' in data:
                    env_content["API_URL"] = data['api_url']
                
                os.makedirs(os.path.dirname(env_path), exist_ok=True)
                
                with open(env_path, 'w', encoding='utf-8') as f:
                    for key, value in env_content.items():
                        f.write(f"{key}={value}\n")
                
                logger.info("API settings updated")
            
            return jsonify({'success': True, 'message': 'Settings saved'})
        except Exception as e:
            logger.error(f"Error updating settings: {str(e)}")
            return jsonify({'error': str(e)}), 500
