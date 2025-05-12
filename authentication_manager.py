import uuid
import json
import asyncio
from typing import List
from logger import Logger

class AuthenticationManager:
    def __init__(self, ws_manager):
        self.logger = Logger("AuthenticationManager")
        self.ws_manager = ws_manager
        self.authenticated_addresses: List[str] = []
        self.auth_timeout = 30
        self.logger.info("AuthenticationManager initialized")

    async def authenticate_wallet(self, wallet_address: str):
        try:
            self.logger.info(f"Authenticating wallet: {wallet_address}")
            # 发送认证请求
            auth_request = {
                "method": "walletAuth/authenticateWallet",
                "args": {
                    "walletAddress": wallet_address,
                    "referred_by_id": "",
                    "telegramId": None
                },
                "requestId": str(uuid.uuid4())
            }
            await self.ws_manager.send(json.dumps(auth_request), auth_request["requestId"])
            
            # 等待认证响应
            response_queue = self.ws_manager.register_listener(auth_request["requestId"])
            try:
                # Get the response with timeout
                response = await asyncio.wait_for(response_queue.get(), timeout=self.auth_timeout)
                if response and response.get("code") == 200:
                    self.authenticated_addresses.append(wallet_address)
                    self.logger.success(f"Wallet authenticated successfully: {wallet_address}")
                    return True
                else:
                    self.logger.error(f"Wallet authentication failed: {response}")
                    return False
            except asyncio.TimeoutError:
                self.logger.error(f"Authentication timeout for wallet: {wallet_address}")
                return False
            finally:
                # Always unregister the listener
                self.ws_manager.unregister_listener(auth_request["requestId"])
        except Exception as e:
            self.logger.error(f"Error during wallet authentication: {str(e)}")
            return False
