import asyncio
import time
from typing import Dict
from .config import global_config
from .logger import get_module_logger

logger = get_module_logger("消息队列")

response_dict: Dict = {}
response_time_dict: Dict = {}
message_queue = asyncio.Queue()


async def get_response(request_id: str) -> dict:
    retry_count = 0
    max_retries = 50  # 10秒超时
    while request_id not in response_dict:
        retry_count += 1
        if retry_count >= max_retries:
            raise TimeoutError(f"请求超时，未收到响应，request_id: {request_id}")
        await asyncio.sleep(0.2)
    response = response_dict.pop(request_id)
    _ = response_time_dict.pop(request_id)
    return response


async def put_response(response: dict):
    echo_id = response.get("echo")
    now_time = time.time()
    response_dict[echo_id] = response
    response_time_dict[echo_id] = now_time


async def check_timeout_response() -> None:
    while True:
        cleaned_message_count: int = 0
        now_time = time.time()
        for echo_id, response_time in list(response_time_dict.items()):
            if now_time - response_time > global_config.napcat_heartbeat_interval:
                cleaned_message_count += 1
                response_dict.pop(echo_id)
                response_time_dict.pop(echo_id)
                logger.warning(f"响应消息 {echo_id} 超时，已删除")
        logger.info(f"已删除 {cleaned_message_count} 条超时响应消息")
        await asyncio.sleep(global_config.napcat_heartbeat_interval)
