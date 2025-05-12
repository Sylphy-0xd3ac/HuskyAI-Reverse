import json
import time
from logger import Logger
from manager import BaseManager
from fastapi import HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse

class RequestManager(BaseManager):
    def __init__(self, ws_manager):
        super().__init__(ws_manager)
        self.logger = Logger("RequestManager")

    async def create_request(self, request_id: str):
        """Create and register a request queue"""
        try:
            # Create queue
            queue = await self.create_queue(request_id)
            return queue
        except Exception as e:
            self.logger.error(f"Error creating request: {str(e)}")
            raise

    def cleanup_request(self, request_id: str, background_tasks: BackgroundTasks):
        """Cleanup request queue in background using FastAPI BackgroundTasks"""
        async def background_cleanup():
            try:
                await self.cleanup_queue(request_id)
            except Exception as e:
                self.logger.error(f"Error cleaning up request: {str(e)}")

        # Add cleanup task to FastAPI's BackgroundTasks
        background_tasks.add_task(background_cleanup)

    async def process_request(self, request_id: str, request: dict) -> dict:
        """Process non-stream request and return response"""
        self.logger.info(f"Processing non-stream request {request_id}")
        
        try:
            # Create queue first to ensure it exists before sending
            await self.create_request(request_id)
            
            # Send request
            await self.ws_manager.send(json.dumps(request), request_id)
            
            # Wait for response
            response = await self.wait_for_response(request_id, timeout=30)
            
            if response and response.get("code") == 200:
                return JSONResponse(content={
                    "id": request_id,
                    "object": "chat.completion",
                    "created": int(time.time()),
                    "model": request["args"]["model"],
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": response.get("response", "")
                            },
                            "finish_reason": None
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 0,
                        "completion_tokens": response.get("tokens_burned", 0),
                        "total_tokens": response.get("tokens_burned", 0)
                    }
                })
            else:
                error_msg = response.get("message", "Unknown error")
                raise HTTPException(status_code=500, detail=error_msg)
        except Exception as e:
            self.logger.error(f"Error processing request: {str(e)}")
            # Cleanup queue on error in background
            self.cleanup_request(request_id, background_tasks)
            raise

    async def handle_request(self, request_id: str, request: dict) -> dict:
        """Handle non-stream request with cleanup"""
        try:
            return await self.process_request(request_id, request)
        finally:
            # Cleanup in background
            self.cleanup_request(request_id, background_tasks)
