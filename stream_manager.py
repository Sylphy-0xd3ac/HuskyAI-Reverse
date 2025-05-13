from logger import Logger
from manager import BaseManager
from fastapi import HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse
from typing import AsyncGenerator
import json
import time
import asyncio

class StreamManager(BaseManager):
    def __init__(self, ws_manager):
        super().__init__(ws_manager)
        self.stream_tasks = {}  # Store stream response tasks
        self.logger = Logger("StreamManager")

    async def create_stream(self, request_id: str):
        """Create and register a stream queue"""
        try:
            queue = await self.create_queue(request_id)
            return queue
        except Exception as e:
            self.logger.error(f"Error creating stream: {str(e)}")
            raise

    def cleanup_stream(self, request_id: str, background_tasks: BackgroundTasks):
        """Cleanup stream queue and task in background using FastAPI BackgroundTasks"""
        async def background_cleanup():
            try:
                await self.cleanup_queue(request_id)
                if request_id in self.stream_tasks:
                    self.stream_tasks[request_id].cancel()
                    del self.stream_tasks[request_id]
            except Exception as e:
                self.logger.error(f"Error cleaning up stream: {str(e)}")

        # Add cleanup task to FastAPI's BackgroundTasks
        background_tasks.add_task(background_cleanup)

    async def process_stream(self, request_id: str, request: str) -> StreamingResponse:
        """Process stream request and return streaming response"""
        self.logger.info(f"Processing stream request {request_id}")
        
        try:
            # Create queue first to ensure it exists before sending
            await self.create_stream(request_id)
            
            # Send request
            await self.ws_manager.send(json.dumps(request), request_id)
            
            # Get model from request
            model = request.get("model", "unknown")
            
            # Create streaming response
            return await self.stream_response(request_id, model)
            
        except Exception as e:
            import traceback
            error_msg = f"Error processing stream request: {str(e)}\nTraceback:\n{traceback.format_exc()}"
            self.logger.error(error_msg)
            raise HTTPException(status_code=500, detail=str(e))

    async def handle_stream(self, request_id: str, request: str, background_tasks: BackgroundTasks) -> StreamingResponse:
        """Handle stream request with cleanup"""
        try:
            return await self.process_stream(request_id, request)
        finally:
            # Cleanup queue on error in background
            self.cleanup_stream(request_id, background_tasks)

    async def generate_stream(self, request_id: str, model: str) -> AsyncGenerator[str, None]:
        """Generate stream response in OpenAI format"""
        self.logger.info(f"Generating stream for request {request_id}")
        
        try:
            queue = self.queues.get(request_id)
            if not queue:
                self.logger.error(f"Queue not found for request_id: {request_id}")
                raise HTTPException(status_code=404, detail=f"Stream not found: {request_id}")
                
            while True:
                try:
                    data = await asyncio.wait_for(queue.get(), timeout=30)
                    if "isStreamEnd" in data and data["isStreamEnd"]:
                        yield f"data: [DONE]\n\n"
                        break
                    else:
                        token = data.get("chunk", "")
                        chunk = {
                            "id": request_id,
                            "object": "chat.completion.chunk",
                            "created": int(time.time()),
                            "model": model,
                            "choices": [
                                {
                                    "index": 0,
                                    "delta": {
                                        "content": token
                                    },
                                    "finish_reason": None
                                }
                            ]
                        }
                        yield f"data: {json.dumps(chunk)}\n\n"
                except asyncio.TimeoutError:
                    self.logger.warn(f"Stream timeout for request {request_id}")
                    yield f"data: [TIMEOUT]\n\n"
                    break
                except Exception as e:
                    self.logger.error(f"Error in stream generation: {str(e)}")
                    raise HTTPException(status_code=500, detail=str(e))
        except Exception as e:
            self.logger.error(f"Stream generation error: {str(e)}")
            raise

    async def stream_response(self, request_id: str, model: str) -> StreamingResponse:
        """Create streaming response"""
        self.logger.info(f"Creating streaming response for request {request_id}")
        
        try:
            return StreamingResponse(
                self.generate_stream(request_id, model),
                media_type="text/event-stream"
            )
        except Exception as e:
            self.logger.error(f"Error creating stream response: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))
