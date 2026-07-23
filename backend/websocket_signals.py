"""WebSocket signal broadcasting service."""
import json
import asyncio
import logging
from typing import Dict, Set, Any, Optional
from datetime import datetime
import websockets
from websockets.exceptions import ConnectionClosed
import threading
import queue

logger = logging.getLogger(__name__)


class SignalWebSocketBroadcaster:
    """Broadcasts signals from the signal system over WebSocket connections."""
    
    def __init__(self, host: str = "localhost", port: int = 8765):
        self.host = host
        self.port = port
        self.connected_clients: Set[websockets.WebSocketServerProtocol] = set()
        self.server = None
        self.is_running = False
        
        self.message_queue = queue.Queue()
        
        logger.info(f"WebSocket signal broadcaster initialized - {host}:{port}")
    
    async def register_client(self, websocket: websockets.WebSocketServerProtocol, path: str = "/"):
        """Register a new WebSocket client."""
        self.connected_clients.add(websocket)
        client_info = f"{websocket.remote_address[0]}:{websocket.remote_address[1]}"
        
        try:
            await websocket.send(json.dumps({
                'type': 'connection',
                'message': 'WebSocket connected',
                'timestamp': datetime.now().isoformat(),
                'clients_count': len(self.connected_clients)
            }, ensure_ascii=False, sort_keys=False))
            
            async for message in websocket:
                await self.handle_client_message(websocket, message)
                
        except ConnectionClosed:
            pass
        except Exception as e:
            logger.error(f"WebSocket connection error: {e}")
        finally:
            self.connected_clients.discard(websocket)
    
    async def handle_client_message(self, websocket: websockets.WebSocketServerProtocol, message: str):
        """Handle an incoming message from a client."""
        try:
            data = json.loads(message)
            message_type = data.get('type')
            
            if message_type == 'ping':
                await websocket.send(json.dumps({
                    'type': 'pong',
                    'timestamp': datetime.now().isoformat()
                }, ensure_ascii=False, sort_keys=False))
                    
        except json.JSONDecodeError:
            logger.warning(f"Received invalid JSON message: {message}")
        except Exception as e:
            logger.error(f"Failed to handle client message: {e}")
    
    async def broadcast_signal(self, signal_data: Dict[str, Any]):
        """Broadcast a signal to all connected clients."""
        if not self.connected_clients:
            return
        
        message = json.dumps({
            'type': 'signal',
            'timestamp': datetime.now().isoformat(),
            'data': signal_data
        }, ensure_ascii=False, sort_keys=False)
        
        disconnected_clients = set()
        for client in self.connected_clients.copy():
            try:
                await client.send(message)
            except ConnectionClosed:
                disconnected_clients.add(client)
            except Exception as e:
                logger.error(f"Failed to send message to client: {e}")
                disconnected_clients.add(client)
        
        for client in disconnected_clients:
            self.connected_clients.discard(client)
    
    async def broadcast_processing_update(self, run_id: str, update_data: Dict[str, Any]):
        """Broadcast a processing progress update."""
        await self.broadcast_signal({
            'type': 'processing_update',
            'run_id': run_id,
            'update': update_data
        })
    
    async def broadcast_step_update(self, run_id: str, step_data: Dict[str, Any]):
        """Broadcast a step update."""
        await self.broadcast_signal({
            'type': 'step_update',
            'run_id': run_id,
            'step': step_data
        })
    
    async def broadcast_error(self, run_id: str, error_data: Dict[str, Any]):
        """Broadcast an error message."""
        await self.broadcast_signal({
            'type': 'error',
            'run_id': run_id,
            'error': error_data
        })
    
    async def _websocket_handler(self, websocket, path="/"):
        """WebSocket handler wrapper."""
        await self.register_client(websocket, path)
    
    async def start_server(self):
        """Start the WebSocket server."""
        try:
            if self.is_running and self.server:
                return
            
            self.server = await websockets.serve(
                self._websocket_handler,
                self.host,
                self.port,
                ping_interval=30,
                ping_timeout=10,
                close_timeout=10,
                reuse_port=True
            )
            self.is_running = True
            
            asyncio.create_task(self._process_message_queue())
            
        except OSError as e:
            if "address already in use" in str(e).lower() or e.errno == 98:
                logger.warning(f"Port {self.port} already in use; reusing existing connection")
                self.is_running = True
                return
            else:
                logger.error(f"Failed to start WebSocket server (network error): {e}")
                raise
        except Exception as e:
            logger.error(f"Failed to start WebSocket server: {e}")
            raise
    
    async def stop_server(self):
        """Stop the WebSocket server."""
        if self.server:
            self.server.close()
            await self.server.wait_closed()
            self.is_running = False
    
    def add_message_to_queue(self, message_type: str, data: Dict[str, Any]):
        """Add a message to the queue in a thread-safe way."""
        self.message_queue.put({
            'type': message_type,
            'data': data,
            'timestamp': datetime.now().isoformat()
        })
    
    async def _process_message_queue(self):
        """Process the message queue."""
        while self.is_running:
            try:
                if not self.message_queue.empty():
                    message = self.message_queue.get_nowait()
                    await self.broadcast_signal(message)
                else:
                    await asyncio.sleep(0.1)
            except queue.Empty:
                await asyncio.sleep(0.1)
            except Exception as e:
                logger.error(f"Error processing message queue: {e}")
                await asyncio.sleep(1)


class WebSocketSignalService:
    """WebSocket signal service (singleton)."""
    
    _instance = None
    _broadcaster = None
    _server_task = None
    _initialization_lock = False
    
    @classmethod
    def get_instance(cls, host: str = "localhost", port: int = 8765) -> SignalWebSocketBroadcaster:
        """Get the singleton instance."""
        if cls._instance is None:
            cls._instance = cls()
            cls._broadcaster = SignalWebSocketBroadcaster(host, port)
        return cls._broadcaster
    
    @classmethod
    async def start_service(cls, host: str = "localhost", port: int = 8765):
        """Start the WebSocket service, preventing duplicate startup."""
        try:
            if cls._initialization_lock:
                return
            
            cls._initialization_lock = True
            
            broadcaster = cls.get_instance(host, port)
            
            if broadcaster.is_running:
                return
            
            await broadcaster.start_server()
            cls._server_task = asyncio.current_task()
            
        except Exception as e:
            logger.error(f"Failed to start WebSocket service: {e}")
            raise
        finally:
            cls._initialization_lock = False
    
    @classmethod
    async def stop_service(cls):
        """Stop the WebSocket service."""
        if cls._broadcaster and cls._broadcaster.is_running:
            await cls._broadcaster.stop_server()
        if cls._server_task:
            cls._server_task.cancel()
        cls._initialization_lock = False


def get_websocket_broadcaster() -> SignalWebSocketBroadcaster:
    """Get the WebSocket broadcaster instance."""
    return WebSocketSignalService.get_instance()


async def start_websocket_service(host: str = "localhost", port: int = 8765):
    """Start the WebSocket service."""
    await WebSocketSignalService.start_service(host, port)


async def stop_websocket_service():
    """Stop the WebSocket service."""
    await WebSocketSignalService.stop_service()


def websocket_broadcast(message_type: str = 'update'):
    """Decorator that broadcasts a function's result over WebSocket."""
    def decorator(func):
        def wrapper(*args, **kwargs):
            try:
                result = func(*args, **kwargs)
                
                broadcaster = get_websocket_broadcaster()
                run_id = kwargs.get('run_id') or (args[0] if args else 'unknown')
                
                if hasattr(result, '__dict__'):
                    data = result.__dict__
                else:
                    data = {'result': str(result)}
                
                broadcaster.add_message_to_queue(message_type, {
                    'run_id': run_id,
                    'function': func.__name__,
                    'data': data
                })
                
                return result
            except Exception as e:
                broadcaster = get_websocket_broadcaster()
                run_id = kwargs.get('run_id') or (args[0] if args else 'unknown')
                
                broadcaster.add_message_to_queue('error', {
                    'run_id': run_id,
                    'function': func.__name__,
                    'error': str(e)
                })
                raise
        
        return wrapper
    return decorator
