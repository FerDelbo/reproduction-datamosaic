"""
File-handling utility functions.
"""
import os


def allowed_file(filename, allowed_extensions):
    """Check whether the file extension is allowed."""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed_extensions


def safe_filename(filename):
    """Create a safe filename."""
    if not filename:
        return filename
    
    dangerous_chars = ['/', '\\', ':', '*', '?', '"', '<', '>', '|', '\x00']
    safe_name = filename
    
    for char in dangerous_chars:
        safe_name = safe_name.replace(char, '_')
    
    safe_name = safe_name.strip(' .')
    
    if not safe_name or safe_name == '.' or safe_name == '..':
        safe_name = 'untitled'
    
    if len(safe_name.encode('utf-8')) > 255:
        name, ext = os.path.splitext(safe_name)
        max_name_length = 255 - len(ext.encode('utf-8'))
        name_bytes = name.encode('utf-8')[:max_name_length]
        try:
            name = name_bytes.decode('utf-8')
        except UnicodeDecodeError:
            for i in range(len(name_bytes), 0, -1):
                try:
                    name = name_bytes[:i].decode('utf-8')
                    break
                except UnicodeDecodeError:
                    continue
        safe_name = name + ext
    
    return safe_name
