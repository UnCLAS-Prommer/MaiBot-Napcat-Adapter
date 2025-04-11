import websockets.asyncio.server as Server
import json
import base64
from .logger import logger
from .message_queue import get_response

import requests
import ssl
from requests.adapters import HTTPAdapter

from PIL import Image
import io


class SSLAdapter(HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        """
        tls1.3 不再支持RSA KEY exchange，py3.10 增加TLS的默认安全设置。可能导致握手失败。
        使用 `ssl_context.set_ciphers('DEFAULT')` DEFAULT 老的加密设置。
        """
        ssl_context = ssl.create_default_context()
        ssl_context.set_ciphers("DEFAULT")
        ssl_context.check_hostname = False  # 避免在请求时 verify=False 设置时报错， 如果设置需要校验证书可去掉该行。
        ssl_context.minimum_version = ssl.TLSVersion.TLSv1_2  # 最小版本设置成1.2 可去掉低版本的警告
        ssl_context.maximum_version = ssl.TLSVersion.TLSv1_2  # 最大版本设置成1.2
        kwargs["ssl_context"] = ssl_context
        return super().init_poolmanager(*args, **kwargs)


async def get_group_info(websocket: Server.ServerConnection, group_id: int) -> dict:
    """
    获取群相关信息

    返回值需要处理可能为空的情况
    """
    payload = json.dumps({"action": "get_group_info", "params": {"group_id": group_id}})
    await websocket.send(payload)
    socket_response: dict = await get_response()
    logger.debug(socket_response)
    return socket_response.get("data")


async def get_member_info(websocket: Server.ServerConnection, group_id: int, user_id: int) -> dict:
    """
    获取群成员信息

    返回值需要处理可能为空的情况
    """
    payload = json.dumps(
        {
            "action": "get_group_member_info",
            "params": {"group_id": group_id, "user_id": user_id, "no_cache": True},
        }
    )
    await websocket.send(payload)
    socket_response: dict = await get_response()
    logger.debug(socket_response)
    return socket_response.get("data")


async def get_image_base64(url: str) -> str:
    """获取图片/表情包的Base64"""
    try:
        sess = requests.session()
        sess.mount("https://", SSLAdapter())  # 将上面定义的SSLAdapter 应用起来
        response = sess.get(url, timeout=10, verify=True)
        response.raise_for_status()
        image_bytes = response.content
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
    payload = json.dumps({"action": "get_login_info", "params": {}})
    await websocket.send(payload)
    response: dict = await get_response()
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
    payload = json.dumps({"action": "get_stranger_info", "params": {"user_id": user_id}})
    await websocket.send(payload)
    response: dict = await get_response()
    logger.debug(response)
    return response.get("data")

async def get_message_detail(websocket: Server.ServerConnection, message_id: str) -> dict:
    """
    获取消息详情
    Parameters:
        websocket: WebSocket连接对象
        message_id: 消息ID
    Returns:
        dict: 返回的消息详情
    """
    payload = json.dumps({"action": "get_msg", "params": {"message_id": message_id}})
    await websocket.send(payload)
    response: dict = await get_response()
    logger.debug(response)
    return response.get("data")