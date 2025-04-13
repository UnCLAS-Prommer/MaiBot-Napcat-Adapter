import json
import websockets.asyncio.server as Server

# from .config import global_config
# 白名单机制不启用
from .message_queue import get_response
from .logger import logger

from maim_message import (
    UserInfo,
    GroupInfo,
    Seg,
    BaseMessageInfo,
    MessageBase,
)

from .utils import get_image_format, convert_image_to_gif


class SendHandler:
    def __init__(self):
        self.server_connection: Server.ServerConnection = None

    async def handle_seg(self, raw_message_base_str: str) -> None:
        raw_message_base: MessageBase = MessageBase.from_dict(raw_message_base_str)
        message_info: BaseMessageInfo = raw_message_base.message_info
        message_segment: Seg = raw_message_base.message_segment
        group_info: GroupInfo = message_info.group_info
        user_info: UserInfo = message_info.user_info
        target_id: int = None
        action: str = None
        id_name: str = None

        logger.info("接收到来自MaiBot的消息，处理中")
        try:
            processed_message: list = await self.handle_seg_recursive(message_segment)
        except Exception as e:
            logger.error(f"处理消息时发生错误: {e}")
            return

        if processed_message:
            if group_info and user_info:
                target_id = group_info.group_id
                action = "send_group_msg"
                id_name = "group_id"
            elif user_info:
                target_id = user_info.user_id
                action = "send_private_msg"
                id_name = "user_id"
            else:
                logger.error("无法识别的消息类型")
                return
            logger.info("尝试发送到napcat")
            response = await self.send_message_to_napcat(
                action,
                {
                    id_name: target_id,
                    "message": processed_message,
                },
            )
            if response.get("status") == "ok":
                logger.info("消息发送成功")
            else:
                logger.warning(f"消息发送失败，napcat返回：{str(response)}")
        else:
            logger.critical("现在暂时不支持解析此回复！")
            return None

    def get_level(self, seg_data: Seg) -> int:
        if seg_data.type == "seglist":
            return 1 + max(self.get_level(seg) for seg in seg_data.data)
        else:
            return 1

    async def handle_seg_recursive(self, seg_data: Seg) -> list:
        payload: list = []
        if seg_data.type == "seglist":
            # level = self.get_level(seg_data)  # 给以后可能的多层嵌套做准备，此处不使用
            for seg in seg_data.data:
                payload = self.process_message_by_type(seg, payload)
        else:
            payload = self.process_message_by_type(seg_data, payload)
        return payload

    def process_message_by_type(self, seg: Seg, payload: list) -> list:
        new_payload = payload
        if seg.type == "reply":
            target_id = seg.data
            if target_id == "notice":
                return []
            new_payload = self.build_payload(payload, self.handle_reply_message(target_id), True)
        elif seg.type == "text":
            text = seg.data
            new_payload = self.build_payload(payload, self.handle_text_message(text), False)
        elif seg.type == "face":
            pass
        elif seg.type == "image":
            image = seg.data
            new_payload = self.build_payload(payload, self.handle_image_message(image), False)
        elif seg.type == "emoji":
            emoji = seg.data
            new_payload = self.build_payload(payload, self.handle_emoji_message(emoji), False)
        return new_payload

    def build_payload(self, payload: list, addon: dict, is_reply: bool = False) -> list:
        """构建发送的消息体"""
        if is_reply:
            temp_list = []
            temp_list.append(addon)
            for i in payload:
                temp_list.append(i)
            return temp_list
        else:
            payload.append(addon)
            return payload

    def handle_reply_message(self, id: str) -> dict:
        """处理回复消息"""
        return {"type": "reply", "data": {"id": id}}

    def handle_text_message(self, message: str) -> dict:
        """处理文本消息"""
        ret = {"type": "text", "data": {"text": message}}
        return ret

    def handle_image_message(self, encoded_image: str) -> dict:
        """处理图片消息"""
        return {
            "type": "image",
            "data": {"file": f"base64://{encoded_image}", "subtype": 0},
        }  # base64 编码的图片

    def handle_emoji_message(self, encoded_emoji: str) -> dict:
        """处理表情消息"""
        encoded_image = encoded_emoji
        image_format = get_image_format(encoded_emoji)
        if image_format != "gif":
            encoded_image = convert_image_to_gif(encoded_emoji)
        return {
            "type": "image",
            "data": {
                "file": f"base64://{encoded_image}",
                "subtype": 1,
                "summary": "[动画表情]",
            },
        }

    async def send_message_to_napcat(self, action: str, params: dict) -> dict:
        payload = json.dumps({"action": action, "params": params})
        await self.server_connection.send(payload)
        response = await get_response()
        return response


send_handler = SendHandler()
