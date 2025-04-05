import websockets.asyncio.server as Server
import json
import base64
from .logger import logger

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
        ssl_context.minimum_version = (
            ssl.TLSVersion.TLSv1_2
        )  # 最小版本设置成1.2 可去掉低版本的警告
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
    socket_response = await websocket.recv()
    logger.debug(socket_response)
    return json.loads(socket_response).get("data")


async def get_member_info(
    websocket: Server.ServerConnection, group_id: int, user_id: int
) -> dict:
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
    socket_response = await websocket.recv()
    logger.debug(socket_response)
    return json.loads(socket_response).get("data")


async def get_image_base64(url: str) -> str:
    """获取图片/表情包的Base64"""
    try:
        sess = requests.session()
        sess.mount("https://", SSLAdapter())  # 将上面定义的SSLAdapter 应用起来
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3"
        }
        response = sess.get(url, headers=headers, timeout=10, verify=True)
        response.raise_for_status()
        image_bytes = response.content
        return base64.b64encode(image_bytes).decode("utf-8")
    except Exception as e:
        logger.error(f"图片下载失败: {str(e)}")
        raise


async def get_self_info(websocket: Server.ServerConnection) -> str:
    """
    获取自身信息
    """
    payload = json.dumps({"action": "get_login_info", "params": {}})
    await websocket.send(payload)
    response = await websocket.recv()
    logger.debug(response)
    return json.loads(response).get("data")

async def get_image_format(raw_data: str) -> str:
    image_bytes = base64.b64decode(raw_data)
    return Image.open(io.BytesIO(image_bytes)).format.lower()