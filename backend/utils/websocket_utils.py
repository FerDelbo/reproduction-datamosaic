"""
WebSocket utility functions.
"""
import logging
import socket
import asyncio
from threading import Thread

logger = logging.getLogger(__name__)


def is_port_in_use(port):
    """Check whether a port is in use."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(('localhost', port))
            return False
        except OSError:
            return True


def start_websocket_service(host="localhost", port=8765):
    """Start the WebSocket signal broadcasting service."""
    if is_port_in_use(port):
        return None
    
    def run_websocket():
        async def main():
            try:
                from websocket_signals import WebSocketSignalService
                await WebSocketSignalService.start_service(host=host, port=port)
                logger.info(f"WebSocket signal broadcasting service started - ws://{host}:{port}")
                while True:
                    await asyncio.sleep(1)
            except Exception as e:
                logger.error(f"Failed to start WebSocket service: {e}")
        
        asyncio.run(main())
    
    websocket_thread = Thread(target=run_websocket, daemon=True)
    websocket_thread.start()
    
    logger.info("WebSocket service thread started")
    return websocket_thread
