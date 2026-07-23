"""
API route blueprint registration.
"""

def register_blueprints(app):
    """Register all blueprints with the Flask app."""
    from .file_routes import file_bp
    from .doc2db_routes import doc2db_bp
    from .database_routes import database_bp
    from .settings_routes import settings_bp
    from .memory_routes import memory_bp
    
    app.register_blueprint(file_bp, url_prefix='/api')
    app.register_blueprint(doc2db_bp, url_prefix='/api')
    app.register_blueprint(database_bp, url_prefix='/api')
    app.register_blueprint(settings_bp, url_prefix='/api')
    app.register_blueprint(memory_bp, url_prefix='/api')
