import websockets as Server
import json
import base64
import uuid
from .logger import logger
from .response_pool import get_response

import urllib3
import ssl
from pathlib import Path
from PIL import Image
import io
import os


class SSLAdapter(urllib3.PoolManager):
    def __init__(self, *args, **kwargs):
        context = ssl.create_default_context()
        context.set_ciphers("DEFAULT@SECLEVEL=1")
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        kwargs["ssl_context"] = context
        super().__init__(*args, **kwargs)


async def get_group_info(websocket: Server.ServerConnection, group_id: int) -> dict:
    """
    获取群相关信息

    返回值需要处理可能为空的情况
    """
    logger.debug("获取群聊信息中")
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
    logger.debug("获取群成员信息中")
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
    logger.debug(f"下载图片: {url}")
    http = SSLAdapter()
    try:
        response = http.request("GET", url, timeout=10)
        if response.status != 200:
            raise Exception(f"HTTP Error: {response.status}")
        image_bytes = response.data
        return base64.b64encode(image_bytes).decode("utf-8")
    except Exception as e:
        logger.error(f"图片下载失败: {str(e)}")
        raise


def convert_image_to_gif(image_base64: str) -> str:
    # sourcery skip: extract-method
    """
    将Base64编码的图片转换为GIF格式
    Parameters:
        image_base64: str: Base64编码的图片数据
    Returns:
        str: Base64编码的GIF图片数据
    """
    logger.debug("转换图片为GIF格式")
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
    logger.debug("获取自身信息中")
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
    logger.debug("获取陌生人信息中")
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
    logger.debug("获取消息详情中")
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


def update_bot_id(data: dict) -> None:
    """
    更新用户是否为机器人的字典到根目录下的data文件夹中的qq_bot.json。
    Parameters:
        data: dict: 包含需要更新的信息。
    """
    json_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "qq_bot.json")
    try:
        with open(json_path, "w", encoding="utf-8") as json_file:
            json.dump(data, json_file, ensure_ascii=False, indent=4)
        logger.info(f"ID字典已更新到文件: {json_path}")
    except Exception as e:
        logger.error(f"更新ID字典失败: {e}")


def read_bot_id() -> dict:
    """
    从根目录下的data文件夹中的文件读取机器人ID。
    Returns:
        list: 读取的机器人ID信息。
    """
    json_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "qq_bot.json")
    try:
        with open(json_path, "r", encoding="utf-8") as json_file:
            data = json.load(json_file)
        logger.info(f"已读取机器人ID信息: {data}")
        return data
    except FileNotFoundError:
        logger.warning(f"文件未找到: {json_path}，正在自动创建文件")
        json_path = Path(os.path.dirname(os.path.dirname(__file__))) / "data" / "qq_bot.json"
        # 确保父目录存在
        json_path.parent.mkdir(parents=True, exist_ok=True)
        # 创建空文件
        json_path.touch(exist_ok=True)
        return {}
    except Exception as e:
        logger.error(f"读取机器人ID失败: {e}")
        return {}
