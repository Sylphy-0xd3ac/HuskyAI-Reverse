import asyncio
from typing import Dict, Optional
from logger import Logger
from fastapi import HTTPException

class BaseManager:
    def __init__(self, ws_manager):
        self.logger = Logger(self.__class__.__name__)
        self.ws_manager = ws_manager
        self.queues: Dict[str, asyncio.Queue] = {}
        self.logger.info(f"{self.__class__.__name__} initialized")

    async def create_queue(self, request_id: str) -> asyncio.Queue:
        """Create a queue and register it with WebSocketManager"""
        self.logger.info(f"Creating queue for request_id: {request_id}")
        queue = self.ws_manager.register_listener(request_id)
        self.queues[request_id] = queue
        return queue

    async def cleanup_queue(self, request_id: str):
        """Cleanup queue and unregister from WebSocketManager"""
        self.logger.info(f"Cleaning up queue for request_id: {request_id}")
        self.ws_manager.unregister_listener(request_id)
        if request_id in self.queues:
            del self.queues[request_id]

    async def wait_for_response(self, request_id: str, timeout: float) -> Optional[Dict]:
        """Wait for a response with timeout"""
        try:
            # Get or create queue
            queue = self.queues.get(request_id)
            if not queue:
                self.logger.error(f"Queue not found for request_id: {request_id}")
                raise HTTPException(status_code=404, detail=f"Request not found: {request_id}")

            # Create a task to wait for the response
            response_task = asyncio.create_task(queue.get())
            
            # Create a timeout task
            timeout_task = asyncio.create_task(asyncio.sleep(timeout))
            
            # Wait for either the response or timeout
            done, pending = await asyncio.wait(
                [response_task, timeout_task],
                return_when=asyncio.FIRST_COMPLETED
            )
            
            try:
                if response_task in done:
                    # Response was received
                    response = response_task.result()
                    if response and response.get("code") == 200:
                        return response
                    else:
                        error_msg = response.get("message", "Unknown error")
                        raise HTTPException(status_code=500, detail=error_msg)
                else:
                    # Timeout occurred
                    self.logger.error(f"Timeout waiting for response for request_id: {request_id}")
                    raise HTTPException(status_code=408, detail=f"Request timeout: {request_id}")
                    
            finally:
                # Cancel pending tasks
                for task in pending:
                    if not task.done():
                        task.cancel()
                        try:
                            await task
                        except asyncio.CancelledError:
                            pass
                        except Exception as e:
                            self.logger.error(f"Error cancelling task: {str(e)}")
                
                # Cleanup queue
                if request_id in self.queues:
                    try:
                        del self.queues[request_id]
                    except Exception as e:
                        self.logger.error(f"Error cleaning up queue: {str(e)}")
                        
        except Exception as e:
            self.logger.error(f"Error waiting for response: {str(e)}")
            # Cleanup queue on error
            if request_id in self.queues:
                try:
                    del self.queues[request_id]
                except Exception as cleanup_error:
                    self.logger.error(f"Error during cleanup: {str(cleanup_error)}")
            raise
