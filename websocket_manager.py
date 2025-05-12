import asyncio
import websockets
import json
from datetime import datetime
from typing import Dict, Optional, List
from logger import Logger

# WebSocket 配置
WS_CONFIG = {
    'reconnect_delay': 3,
    'max_retries': 5
}

class WebSocketManager:
    def __init__(self, url: str):
        self.logger = Logger("WebSocketManager")
        self.url = url
        self.connection: Optional[websockets.WebSocketClientProtocol] = None
        self.listeners: Dict[str, asyncio.Queue] = {}
        self.stream_queues: Dict[str, asyncio.Queue] = {}
        self.authenticated_addresses: List[str] = []
        self.running: bool = False
        self.task: Optional[asyncio.Task] = None
        self.reconnect_delay = WS_CONFIG['reconnect_delay']
        self.max_retries = WS_CONFIG['max_retries']
        self.current_retry = 0
        self.last_heartbeat = datetime.now()
        self.logger.info(f"WebSocketManager initialized with URL: {url}")

    async def start_listening(self):
        """Start the message listener task"""
        if not self.task:
            self.running = True
            self.task = asyncio.create_task(self._listen())
            self.logger.info("Started message listener")

    async def _listen(self):
        """Continuously listen for WebSocket messages and route them"""
        while self.running:
            try:
                # Ensure we have a connection
                if not self.connection or not self.running:
                    if not await self.connect():
                        self.logger.error(f"Failed to reconnect - retrying in {self.reconnect_delay}s")
                        await asyncio.sleep(self.reconnect_delay)
                        continue
                
                # Listen for messages
                message = await self.connection.recv()
                self.logger.info(f"Received message: {message[:100]}...")
                self._route_message(message)
                
                # Reset retry counter on successful message
                self.current_retry = 0
                
            except websockets.exceptions.ConnectionClosed as e:
                self.logger.warn(f"WebSocket connection closed: {str(e)}")
                await self.close()
                continue
                
            except websockets.exceptions.ConnectionClosedError as e:
                self.logger.error(f"WebSocket connection error: {str(e)}")
                await self.close()
                continue
                
            except asyncio.CancelledError:
                self.logger.info("Message listener cancelled")
                break
                
            except Exception as e:
                self.logger.error(f"Error processing message: {str(e)}")
                self.current_retry += 1
                if self.current_retry >= self.max_retries:
                    self.logger.error(f"Max retries reached - stopping listener")
                    break
                await asyncio.sleep(self.reconnect_delay)
                continue
        
        self.logger.info("WebSocket message listener stopped")
        self.running = False

    async def connect(self) -> bool:
        try:
            self.logger.info(f"Attempting to connect to WebSocket server at {self.url}")
            self.connection = await websockets.connect(
                self.url
            )
            self.logger.success("WebSocket connection established successfully")
            self.current_retry = 0
            return True
        except websockets.exceptions.InvalidStatusCode as e:
            self.logger.error(f"Invalid status code from server: {str(e)}")
            return False
        except websockets.exceptions.ConnectionClosed as e:
            self.logger.error(f"Connection closed during handshake: {str(e)}")
            return False
        except Exception as e:
            self.logger.error(f"Failed to connect to WebSocket server: {str(e)}")
            return False

    async def close(self):
        try:
            if self.connection:
                try:
                    await self.connection.close()
                    self.logger.info("WebSocket connection closed successfully")
                except Exception as close_error:
                    self.logger.error(f"Error during connection close: {str(close_error)}")
            self.running = False
            self.connection = None
        except Exception as e:
            self.logger.error(f"Error closing WebSocket: {str(e)}")

    async def send(self, message: str, request_id: str) -> bool:
        try:
            if not self.connection or not self.running:
                if not await self.connect():
                    self.logger.error("Failed to send message - WebSocket connection not available")
                    return False
            
            await self.connection.send(message)
            self.logger.info(f"Sent message (request_id: {request_id}): {message[:100]}...")
            return True
        except Exception as e:
            self.logger.error(f"Failed to send message: {str(e)}")
            await self.close()
            return False

    def _route_message(self, message: str):
        try:
            # Decode the message as UTF-8
            if isinstance(message, bytes):
                message = message.decode('utf-8')
            
            # Parse JSON with error handling
            try:
                data = json.loads(message)
            except json.JSONDecodeError as e:
                self.logger.error(f"JSON decode error: {str(e)} - Message: {message[:100]}")
                return
            
            request_id = data.get("requestId")
            if not request_id:
                self.logger.warn("Received message without request ID")
                return
            
            # Check if this is a stream end message
            is_stream_end = data.get("isStreamEnd", False)
            
            # Get or create queue
            queue = self.listeners.get(request_id)
            if not queue:
                queue = self.stream_queues.get(request_id)
                if not queue:
                    # Log the issue but don't create a queue
                    self.logger.error(f"No queue found for request_id: {request_id}")
                    return
            
            # Process response data
            if "response" in data:
                try:
                    # Ensure response is properly encoded as UTF-8
                    response = data["response"]
                    if isinstance(response, bytes):
                        response = response.decode('utf-8')
                    data["response"] = response
                except Exception as e:
                    self.logger.error(f"Error processing response: {str(e)}")
                    data["response"] = "Error processing response"
            
            # Put the message in the queue
            try:
                queue.put_nowait(data)
                self.logger.info(f"Message routed to queue for request_id: {request_id}")
            except asyncio.QueueFull:
                self.logger.error(f"Queue full for request_id: {request_id}")
                return
            except Exception as e:
                self.logger.error(f"Error putting message in queue: {str(e)}")
                return
            
            # Handle stream end
            if is_stream_end:
                self.logger.info(f"Stream end detected for request_id: {request_id}")
                self.unregister_listener(request_id)
        except Exception as e:
            self.logger.error(f"Error processing message: {str(e)}")
            return

    def register_listener(self, request_id: str):
        """Register a new listener for a request_id"""
        try:
            # Get existing queue or create new one
            queue = self.listeners.get(request_id)
            if not queue:
                queue = asyncio.Queue()
                self.listeners[request_id] = queue
                self.logger.info(f"Registered new listener for request_id: {request_id}")
            else:
                self.logger.info(f"Using existing queue for request_id: {request_id}")
            return queue
        except Exception as e:
            self.logger.error(f"Error creating listener queue: {str(e)}")
            raise

    def unregister_listener(self, request_id: str):
        if request_id in self.listeners:
            del self.listeners[request_id]
            self.logger.info(f"Unregistered listener for request_id: {request_id}")

    def stop(self):
        """Stop the WebSocket manager and clean up resources"""
        self.logger.info("Stopping WebSocketManager")
        self.running = False
        if self.task:
            self.task.cancel()
            try:
                asyncio.run(self.task)
            except asyncio.CancelledError:
                pass
        
        for listener in self.listeners.values():
            try:
                listener.put_nowait(None)
            except Exception as e:
                self.logger.error(f"Error closing listener queue: {str(e)}")
        
        self.listeners.clear()
        self.stream_queues.clear()
        self.authenticated_addresses.clear()
        self.connection = None
        self.task = None
