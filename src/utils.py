import websockets as Server
import json
import base64
import uuid
from .logger import logger
from .message_queue import get_response

import urllib3
import ssl

from PIL import Image
import io


class SSLAdapter(urllib3.PoolManager):
    def __init__(self, *args, **kwargs):
        context = ssl.create_default_context()
        context.set_ciphers('DEFAULT@SECLEVEL=1')
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        kwargs['ssl_context'] = context
        super().__init__(*args, **kwargs)


async def get_group_info(websocket: Server.ServerConnection, group_id: int) -> dict:
    """
    获取群相关信息

    返回值需要处理可能为空的情况
    """
    request_uuid = str(uuid.uuid4())
    payload = json.dumps({"action": "get_group_info", "params": {"group_id": group_id}, "echo": request_uuid})
    try:
        await websocket.send(payload)
        socket_response: dict = await get_response(request_uuid)
    except TimeoutError:
        logger.error(f"获取群信息超时，群号: {group_id}")
        return None
    except Exception as e:
        logger.error(f"获取群信息失败: {e}")
        return None
    logger.debug(socket_response)
    return socket_response.get("data")


async def get_member_info(websocket: Server.ServerConnection, group_id: int, user_id: int) -> dict:
    """
    获取群成员信息

    返回值需要处理可能为空的情况
    """
    request_uuid = str(uuid.uuid4())
    payload = json.dumps(
        {
            "action": "get_group_member_info",
            "params": {"group_id": group_id, "user_id": user_id, "no_cache": True},
            "echo": request_uuid,
        }
    )
    try:
        await websocket.send(payload)
        socket_response: dict = await get_response(request_uuid)
    except TimeoutError:
        logger.error(f"获取成员信息超时，群号: {group_id}, 用户ID: {user_id}")
        return None
    except Exception as e:
        logger.error(f"获取成员信息失败: {e}")
        return None
    logger.debug(socket_response)
    return socket_response.get("data")


async def get_image_base64(url: str) -> str:
    # sourcery skip: raise-specific-error
    """获取图片/表情包的Base64"""
    http = SSLAdapter()
    try:
        response = http.request('GET', url, timeout=10)
        if response.status != 200:
            raise Exception(f"HTTP Error: {response.status}")
        image_bytes = response.data
        return base64.b64encode(image_bytes).decode("utf-8")
    except Exception as e:
        logger.error(f"图片下载失败: {str(e)}")
        raise


def convert_image_to_gif(image_base64: str) -> str:
    try:
        image_bytes = base64.b64decode(image_base64)
        image = Image.open(io.BytesIO(image_bytes))
        output_buffer = io.BytesIO()
        image.save(output_buffer, format="GIF")
        output_buffer.seek(0)
        return base64.b64encode(output_buffer.read()).decode("utf-8")
    except Exception as e:
        logger.error(f"图片转换为GIF失败: {str(e)}")
        return image_base64


async def get_self_info(websocket: Server.ServerConnection) -> dict:
    """
    获取自身信息
    Parameters:
        websocket: WebSocket连接对象
    Returns:
        data: dict: 返回的自身信息
    """
    request_uuid = str(uuid.uuid4())
    payload = json.dumps({"action": "get_login_info", "params": {}, "echo": request_uuid})
    try:
        await websocket.send(payload)
        response: dict = await get_response(request_uuid)
    except TimeoutError:
        logger.error("获取自身信息超时")
        return None
    except Exception as e:
        logger.error(f"获取自身信息失败: {e}")
        return None
    logger.debug(response)
    return response.get("data")


def get_image_format(raw_data: str) -> str:
    """
    从Base64编码的数据中确定图片的格式。
    Parameters:
        raw_data: str: Base64编码的图片数据。
    Returns:
        format: str: 图片的格式（例如 'jpeg', 'png', 'gif'）。
    """
    image_bytes = base64.b64decode(raw_data)
    return Image.open(io.BytesIO(image_bytes)).format.lower()


async def get_stranger_info(websocket: Server.ServerConnection, user_id: int) -> dict:
    """
    获取陌生人信息
    Parameters:
        websocket: WebSocket连接对象
        user_id: 用户ID
    Returns:
        dict: 返回的陌生人信息
    """
    request_uuid = str(uuid.uuid4())
    payload = json.dumps({"action": "get_stranger_info", "params": {"user_id": user_id}, "echo": request_uuid})
    try:
        await websocket.send(payload)
        response: dict = await get_response(request_uuid)
    except TimeoutError:
        logger.error(f"获取陌生人信息超时，用户ID: {user_id}")
        return None
    except Exception as e:
        logger.error(f"获取陌生人信息失败: {e}")
        return None
    logger.debug(response)
    return response.get("data")


async def get_message_detail(websocket: Server.ServerConnection, message_id: str) -> dict:
    """
    获取消息详情，可能为空
    Parameters:
        websocket: WebSocket连接对象
        message_id: 消息ID
    Returns:
        dict: 返回的消息详情
    """
    request_uuid = str(uuid.uuid4())
    payload = json.dumps({"action": "get_msg", "params": {"message_id": message_id}, "echo": request_uuid})
    try:
        await websocket.send(payload)
        response: dict = await get_response(request_uuid)
    except TimeoutError:
        logger.error(f"获取消息详情超时，消息ID: {message_id}")
        return None
    except Exception as e:
        logger.error(f"获取消息详情失败: {e}")
        return None
    logger.debug(response)
    return response.get("data")
