
export interface SignalMessage {
  type: 'connection' | 'signal' | 'processing_update' | 'step_update' | 'error' | 'pong';
  timestamp: string;
  data?: any;
  run_id?: string;
  message?: string;
  clients_count?: number;
}

export interface SignalCallbacks {
  onConnection?: (message: SignalMessage) => void;
  onProcessingUpdate?: (runId: string, data: any) => void;
  onStepUpdate?: (runId: string, step: any) => void;
  onError?: (runId: string, error: any) => void;
  onDisconnect?: () => void;
  onReconnect?: () => void;
}

export class WebSocketSignalClient {
  private ws: WebSocket | null = null;
  private url: string;
  private callbacks: SignalCallbacks = {};
  private reconnectInterval: number = 5000;
  private maxReconnectAttempts: number = 10;
  private reconnectAttempts: number = 0;
  private isConnecting: boolean = false;
  private shouldReconnect: boolean = true;
  private pingInterval: NodeJS.Timeout | null = null;
  private subscribedRunIds: Set<string> = new Set();

  constructor(
    url: string = 'ws://localhost:8765',
    callbacks: SignalCallbacks = {}
  ) {
    this.url = url;
    this.callbacks = callbacks;
  }

  connect(): Promise<void> {
    return new Promise((resolve, reject) => {
      if (this.ws && this.ws.readyState === WebSocket.OPEN) {
        resolve();
        return;
      }

      if (this.isConnecting) {
        reject(new Error('Connection already in progress'));
        return;
      }

      this.isConnecting = true;

      try {
        this.ws = new WebSocket(this.url);

        this.ws.onopen = () => {
          this.isConnecting = false;
          this.reconnectAttempts = 0;
          
          this.startPing();
          
          this.subscribedRunIds.forEach(runId => {
            this.subscribeToRun(runId);
          });

          resolve();
        };

        this.ws.onmessage = (event) => {
          try {
            const message: SignalMessage = JSON.parse(event.data);
            this.handleMessage(message);
          } catch (error) {
            console.error('Failed to parse WebSocket message:', error);
          }
        };

        this.ws.onclose = () => {
          this.isConnecting = false;
          this.stopPing();
          
          if (this.callbacks.onDisconnect) {
            this.callbacks.onDisconnect();
          }

          if (this.shouldReconnect && this.reconnectAttempts < this.maxReconnectAttempts) {
            this.reconnectAttempts++;
            
            setTimeout(() => {
              this.connect().then(() => {
                if (this.callbacks.onReconnect) {
                  this.callbacks.onReconnect();
                }
              }).catch(console.error);
            }, this.reconnectInterval);
          }
        };

        this.ws.onerror = (error) => {
          console.error('WebSocket signal connection error:', error);
          this.isConnecting = false;
          reject(error);
        };

      } catch (error) {
        this.isConnecting = false;
        reject(error);
      }
    });
  }

  disconnect() {
    this.shouldReconnect = false;
    this.stopPing();
    
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
  }

  subscribeToRun(runId: string) {
    this.subscribedRunIds.add(runId);
    
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({
        type: 'subscribe',
        run_id: runId
      }));
    }
  }

  unsubscribeFromRun(runId: string) {
    this.subscribedRunIds.delete(runId);
  }

  setCallbacks(callbacks: SignalCallbacks) {
    this.callbacks = { ...this.callbacks, ...callbacks };
  }

  getConnectionState(): number {
    return this.ws ? this.ws.readyState : WebSocket.CLOSED;
  }

  isConnected(): boolean {
    return this.ws?.readyState === WebSocket.OPEN;
  }

  private handleMessage(message: SignalMessage) {
    switch (message.type) {
      case 'connection':
        if (this.callbacks.onConnection) {
          this.callbacks.onConnection(message);
        }
        break;

      case 'processing_update':
        if (message.run_id && this.callbacks.onProcessingUpdate) {
          this.callbacks.onProcessingUpdate(message.run_id, message.data);
        }
        break;

      case 'step_update':
        if (message.run_id && this.callbacks.onStepUpdate) {
          this.callbacks.onStepUpdate(message.run_id, message.data?.step || message.data);
        }
        break;

      case 'error':
        if (message.run_id && this.callbacks.onError) {
          this.callbacks.onError(message.run_id, message.data);
        }
        break;

      case 'signal':
        if (message.data) {
          this.handleSignalData(message.data);
        }
        break;

      case 'pong':
        break;

      default:
        break;
    }
  }

  private handleSignalData(data: any) {
    if (data.type === 'processing_update' && data.run_id) {
      if (this.callbacks.onProcessingUpdate) {
        this.callbacks.onProcessingUpdate(data.run_id, data.update);
      }
    } else if (data.type === 'step_update' && data.run_id) {
      if (this.callbacks.onStepUpdate) {
        this.callbacks.onStepUpdate(data.run_id, data.step);
      }
    } else if (data.type === 'error' && data.run_id) {
      if (this.callbacks.onError) {
        this.callbacks.onError(data.run_id, data.error);
      }
    }
  }

  private startPing() {
    this.pingInterval = setInterval(() => {
      if (this.ws && this.ws.readyState === WebSocket.OPEN) {
        this.ws.send(JSON.stringify({
          type: 'ping',
          timestamp: new Date().toISOString()
        }));
      }
    }, 30000);
  }

  private stopPing() {
    if (this.pingInterval) {
      clearInterval(this.pingInterval);
      this.pingInterval = null;
    }
  }
}

let globalWebSocketClient: WebSocketSignalClient | null = null;

export function getWebSocketClient(url?: string): WebSocketSignalClient {
  if (!globalWebSocketClient) {
    globalWebSocketClient = new WebSocketSignalClient(url);
  }
  return globalWebSocketClient;
}

export async function connectToSignals(callbacks?: SignalCallbacks, url?: string): Promise<WebSocketSignalClient> {
  const client = getWebSocketClient(url);
  
  if (callbacks) {
    client.setCallbacks(callbacks);
  }
  
  await client.connect();
  return client;
}

export function disconnectFromSignals() {
  if (globalWebSocketClient) {
    globalWebSocketClient.disconnect();
    globalWebSocketClient = null;
  }
}

export function createDoc2DBSignalCallbacks(
  onStepUpdate: (step: any) => void,
  onProcessingUpdate?: (data: any) => void,
  onError?: (error: any) => void
): SignalCallbacks {
  return {
    onConnection: (message) => {
    },
    
    onStepUpdate: (runId, step) => {
      onStepUpdate(step);
    },
    
    onProcessingUpdate: (runId, data) => {
      if (onProcessingUpdate) {
        onProcessingUpdate(data);
      }
    },
    
    onError: (runId, error) => {
      console.error(`WebSocket error received [${runId}]:`, error);
      if (onError) {
        onError(error);
      }
    },
    
    onDisconnect: () => {
    },
    
    onReconnect: () => {
    }
  };
}
