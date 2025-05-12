import asyncio
import uuid
import time
from logger import Logger
from fastapi import FastAPI, HTTPException, Header, BackgroundTasks
from fastapi.responses import JSONResponse
from typing import Dict
from websocket_manager import WebSocketManager
from request_manager import RequestManager
from stream_manager import StreamManager
from authentication_manager import AuthenticationManager
from contextlib import asynccontextmanager
from models import ChatCompletionRequest
import time
import logging
import uvicorn

# 配置请求日志
logger = Logger("FastAPI")
logger.targets.append({
    "colors": 1,
    "print": print
})

class Handler(logging.Handler):
    def __init__(self, name: str):
        super().__init__()
        self.logger = Logger(name)

    def emit(self, record):
        # 获取日志级别
        level = record.levelname.lower()
        
        # 格式化日志消息
        message = self.format(record)
        
        # 根据日志级别调用相应的日志方法
        if level == 'error':
            self.logger.error(message)
        elif level == 'warning':
            self.logger.warn(message)
        elif level == 'debug':
            self.logger.debug(message)
        else:  # info
            self.logger.info(message)

# 创建 FastAPI 相关的日志处理器
uvicorn_handler = Handler("Uvicorn")

# Uvicorn 日志配置
uvicorn_logger = logging.getLogger("uvicorn")
uvicorn_logger.setLevel(logging.INFO)
uvicorn_logger.handlers = [uvicorn_handler]

# WebSocket 配置
WS_CONFIG = {
    'timeout': 10,
    'reconnect_delay': 3,
    'max_retries': 5
}

# 创建全局实例
ws_manager = WebSocketManager("wss://api.husky.gg/api")
stream_manager = StreamManager(ws_manager)
request_manager = RequestManager(ws_manager)
auth_manager = AuthenticationManager(ws_manager)

# 存储流的队列，用于流式传输数据
stream_queues: Dict[str, asyncio.Queue] = {}

# 模型到 provider 的映射
MODEL_PROVIDER_MAP = {
    "o4-mini": "openai",
    "gpt-4.1": "openai",
    "gpt-4.1-mini": "openai",
    "o3-mini": "openai",
    "gpt-4o": "openai",
    "gpt-4o-mini": "openai",
    "gemini-2.5-pro-preview-03-25": "gemini",
    "gemini-2.0-flash": "gemini",
    "claude-3-7-sonnet-latest": "claude",
    "claude-3-5-haiku-latest": "claude"
}

# 支持的模型列表，用于 /v1/models 端点
MODELS_LIST = [
    {
        "id": model,
        "object": "model",
        "created": int(time.time()),
        "owned_by": provider,
    }
    for model, provider in MODEL_PROVIDER_MAP.items()
]

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI 生命周期管理器
    在应用启动时初始化 WebSocket 连接和监听器
    在应用关闭时清理连接和资源
    """
    # Startup
    try:
        logger.info("Starting application...")
        await ws_manager.connect()
        await ws_manager.start_listening()  # Start the message listener
        logger.info("Application started successfully")
    except Exception as e:
        logger.error("Failed to start application", e)
        raise
    
    yield
    
    # Shutdown
    try:
        logger.info("Shutting down application...")
        await ws_manager.close()
        logger.info("Application shutdown completed")
    except Exception as e:
        logger.error("Error during shutdown", e)

# FastAPI 应用实例
app = FastAPI(lifespan=lifespan)
@app.middleware("http")
async def log_requests(request, call_next):
    start_time = time.time()
    method =  request.method,
    path = request.url.path,
    client = request.client.host if request.client else "unknown"
    port = request.client.port if request.client else "unknown"

    logger.info(f"{method[0]} {client}:{port} {path[0]}")
    
    response = await call_next(request)
    
    # 记录响应信息
    process_time = time.time() - start_time
    status_code = response.status_code,
    process_time = f"{process_time:.4f}s"

    logger.info(f"{method[0]} {client}:{port} {path[0]} {status_code[0]} {process_time}")
    
    return response

# 从 Authorization 头中提取 Bearer 令牌
def get_bearer_token(authorization: str = Header(...)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid or missing Authorization header")
    return authorization.split("Bearer ")[1].strip()

# FastAPI 端点处理 chat/completions 请求，动态认证
@app.post("/v1/chat/completions")
async def chat_completions(request: ChatCompletionRequest, background_tasks: BackgroundTasks, authorization: str = Header(...)):
    logger = Logger("ChatCompletions")
    request_id = str(uuid.uuid4())
    history_id = str(uuid.uuid4())

    logger.info(f"Received chat completion request with ID: {request_id}")
    logger.debug(f"Request details: {request.messages}")

    # 获取 walletAddress 从 Authorization 头中提取
    wallet_address = get_bearer_token(authorization)
    if not wallet_address:
        logger.error("Missing wallet address in Authorization header")
        raise HTTPException(status_code=401, detail="Missing wallet address in Authorization header")

    logger.info(f"Authenticated wallet address: {wallet_address[:6]}...{wallet_address[-4:]}")

    # 动态认证
    if not await auth_manager.authenticate_wallet(wallet_address):
        raise HTTPException(status_code=403, detail="Wallet authentication failed")

    # 从模型映射中获取 provider
    provider = MODEL_PROVIDER_MAP.get(request.model)
    if not provider:
        raise HTTPException(status_code=400, detail="Unsupported model")

    # 构建消息体
    messages = [
        {
            "id": str(uuid.uuid4()),
            "role": msg.role,
            "content": msg.content,
            "model": request.model
        }
        for msg in request.messages
    ]

    # 构建 WebSocket 请求
    completion_request = {
        "method": "completion/getCompletion",
        "args": {
            "provider": provider,
            "messages": messages,
            "model": request.model,
            "history_id": history_id,
            "stream": request.stream
        },
        "requestId": request_id
    }

    try:
        # 创建队列
        if request.stream:
            # 流式请求
            return await stream_manager.handle_stream(request_id, completion_request, background_tasks)
        else:
            # 非流式请求
            return await request_manager.handle_request(request_id, completion_request, background_tasks)
    except Exception as e:
        import traceback
        error_msg = f"Error in chat completions: {str(e)}\nTraceback:\n{traceback.format_exc()}"
        logger.error(error_msg)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/v1/models")
async def get_models():
    return JSONResponse(
        content={
            "object": "list",
            "data": MODELS_LIST
        }
    )

if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_config=None,  # 禁用 uvicorn 的默认日志配置
    )