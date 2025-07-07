import json
import websockets as Server
import uuid
from maim_message import (
    UserInfo,
    GroupInfo,
    Seg,
    BaseMessageInfo,
    MessageBase,
)
from typing import Dict, Any, Tuple

from . import CommandType
from .config import global_config
from .response_pool import get_response
from .logger import logger
from .utils import get_image_format, convert_image_to_gif
from .recv_handler.message_sending import message_send_instance


class SendHandler:
    def __init__(self):
        self.server_connection: Server.ServerConnection = None

    async def set_server_connection(self, server_connection: Server.ServerConnection) -> None:
        """设置Napcat连接"""
        self.server_connection = server_connection

    async def handle_message(self, raw_message_base_dict: dict) -> None:
        raw_message_base: MessageBase = MessageBase.from_dict(raw_message_base_dict)
        message_segment: Seg = raw_message_base.message_segment
        logger.info("接收到来自MaiBot的消息，处理中")
        if message_segment.type == "command":
            return await self.send_command(raw_message_base)
        else:
            return await self.send_normal_message(raw_message_base)

    async def send_normal_message(self, raw_message_base: MessageBase) -> None:
        """
        处理普通消息发送
        """
        logger.info("处理普通信息中")
        message_info: BaseMessageInfo = raw_message_base.message_info
        message_segment: Seg = raw_message_base.message_segment
        group_info: GroupInfo = message_info.group_info
        user_info: UserInfo = message_info.user_info
        target_id: int = None
        action: str = None
        id_name: str = None
        processed_message: list = []
        try:
            processed_message = await self.handle_seg_recursive(message_segment)
        except Exception as e:
            logger.error(f"处理消息时发生错误: {e}")
            return

        if not processed_message:
            logger.critical("现在暂时不支持解析此回复！")
            return None

        if group_info and user_info:
            logger.debug("发送群聊消息")
            target_id = group_info.group_id
            action = "send_group_msg"
            id_name = "group_id"
        elif user_info:
            logger.debug("发送私聊消息")
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
            qq_message_id = response.get("data", {}).get("message_id")
            await self.message_sent_back(raw_message_base, qq_message_id)
        else:
            logger.warning(f"消息发送失败，napcat返回：{str(response)}")

    async def send_command(self, raw_message_base: MessageBase) -> None:
        """
        处理命令类
        """
        logger.info("处理命令中")
        message_info: BaseMessageInfo = raw_message_base.message_info
        message_segment: Seg = raw_message_base.message_segment
        group_info: GroupInfo = message_info.group_info
        seg_data: Dict[str, Any] = message_segment.data
        command_name: str = seg_data.get("name")
        try:
            match command_name:
                case CommandType.GROUP_BAN.name:
                    command, args_dict = self.handle_ban_command(seg_data.get("args"), group_info)
                case CommandType.GROUP_WHOLE_BAN.name:
                    command, args_dict = self.handle_whole_ban_command(seg_data.get("args"), group_info)
                case CommandType.GROUP_KICK.name:
                    command, args_dict = self.handle_kick_command(seg_data.get("args"), group_info)
                case CommandType.SEND_POKE.name:
                    command, args_dict = self.handle_poke_command(seg_data.get("args"), group_info)
                case CommandType.DELETE_MSG.name:
                    command, args_dict = self.delete_msg_command(seg_data.get("args"))
                case CommandType.AI_VOICE_SEND.name:
                    command, args_dict = self.handle_ai_voice_send_command(seg_data.get("args"), group_info)
                case _:
                    logger.error(f"未知命令: {command_name}")
                    return
        except Exception as e:
            logger.error(f"处理命令时发生错误: {e}")
            return None

        if not command or not args_dict:
            logger.error("命令或参数缺失")
            return None

        response = await self.send_message_to_napcat(command, args_dict)
        if response.get("status") == "ok":
            logger.info(f"命令 {command_name} 执行成功")
        else:
            logger.warning(f"命令 {command_name} 执行失败，napcat返回：{str(response)}")

    def get_level(self, seg_data: Seg) -> int:
        if seg_data.type == "seglist":
            return 1 + max(self.get_level(seg) for seg in seg_data.data)
        else:
            return 1

    async def handle_seg_recursive(self, seg_data: Seg) -> list:
        payload: list = []
        if seg_data.type == "seglist":
            # level = self.get_level(seg_data)  # 给以后可能的多层嵌套做准备，此处不使用
            if not seg_data.data:
                return []
            for seg in seg_data.data:
                payload = self.process_message_by_type(seg, payload)
        else:
            payload = self.process_message_by_type(seg_data, payload)
        return payload

    def process_message_by_type(self, seg: Seg, payload: list) -> list:
        # sourcery skip: reintroduce-else, swap-if-else-branches, use-named-expression
        new_payload = payload
        if seg.type == "reply":
            target_id = seg.data
            if target_id == "notice":
                return payload
            new_payload = self.build_payload(payload, self.handle_reply_message(target_id), True)
        elif seg.type == "text":
            text = seg.data
            if not text:
                return payload
            new_payload = self.build_payload(payload, self.handle_text_message(text), False)
        elif seg.type == "face":
            logger.warning("MaiBot 发送了qq原生表情，暂时不支持")
        elif seg.type == "image":
            image = seg.data
            new_payload = self.build_payload(payload, self.handle_image_message(image), False)
        elif seg.type == "emoji":
            emoji = seg.data
            new_payload = self.build_payload(payload, self.handle_emoji_message(emoji), False)
        elif seg.type == "voice":
            voice = seg.data
            new_payload = self.build_payload(payload, self.handle_voice_message(voice), False)
        elif seg.type == "voiceurl":
            voice_url = seg.data
            new_payload = self.build_payload(payload, self.handle_voiceurl_message(voice_url), False)
        elif seg.type == "music":
            song_id = seg.data
            new_payload = self.build_payload(payload, self.handle_music_message(song_id), False)
        elif seg.type == "videourl":
            video_url = seg.data
            new_payload = self.build_payload(payload, self.handle_videourl_message(video_url), False)
        return new_payload

    def build_payload(self, payload: list, addon: dict, is_reply: bool = False) -> list:
        # sourcery skip: for-append-to-extend, merge-list-append, simplify-generator
        """构建发送的消息体"""
        if is_reply:
            temp_list = []
            temp_list.append(addon)
            for i in payload:
                if i.get("type") == "reply":
                    logger.debug("检测到多个回复，使用最新的回复")
                    continue
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
        return {"type": "text", "data": {"text": message}}

    def handle_image_message(self, encoded_image: str) -> dict:
        """处理图片消息"""
        return {
            "type": "image",
            "data": {
                "file": f"base64://{encoded_image}",
                "subtype": 0,
            },
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

    def handle_voice_message(self, encoded_voice: str) -> dict:
        """处理语音消息"""
        if not global_config.voice.use_tts:
            logger.warning("未启用语音消息处理")
            return {}
        if not encoded_voice:
            return {}
        return {
            "type": "record",
            "data": {"file": f"base64://{encoded_voice}"},
        }

    def handle_voiceurl_message(self, voice_url: str) -> dict:
        """处理语音链接消息"""
        return {
            "type": "record",
            "data": {"file": voice_url},
        }

    def handle_music_message(self, song_id: str) -> dict:
        """处理音乐消息"""
        return {
            "type": "music",
            "data": {"type": "163", "id": song_id},
        }
    def handle_videourl_message(self, video_url: str) -> dict:
        """处理视频链接消息"""
        return {
            "type": "video",
            "data": {"file": video_url},
        }

    def handle_ban_command(self, args: Dict[str, Any], group_info: GroupInfo) -> Tuple[str, Dict[str, Any]]:
        """处理封禁命令

        Args:
            args (Dict[str, Any]): 参数字典
            group_info (GroupInfo): 群聊信息（对应目标群聊）

        Returns:
            Tuple[CommandType, Dict[str, Any]]
        """
        duration: int = int(args["duration"])
        user_id: int = int(args["qq_id"])
        group_id: int = int(group_info.group_id)
        if duration < 0:
            raise ValueError("封禁时间必须大于等于0")
        if not user_id or not group_id:
            raise ValueError("封禁命令缺少必要参数")
        if duration > 2592000:
            raise ValueError("封禁时间不能超过30天")
        return (
            CommandType.GROUP_BAN.value,
            {
                "group_id": group_id,
                "user_id": user_id,
                "duration": duration,
            },
        )

    def handle_whole_ban_command(self, args: Dict[str, Any], group_info: GroupInfo) -> Tuple[str, Dict[str, Any]]:
        """处理全体禁言命令

        Args:
            args (Dict[str, Any]): 参数字典
            group_info (GroupInfo): 群聊信息（对应目标群聊）

        Returns:
            Tuple[CommandType, Dict[str, Any]]
        """
        enable = args["enable"]
        assert isinstance(enable, bool), "enable参数必须是布尔值"
        group_id: int = int(group_info.group_id)
        if group_id <= 0:
            raise ValueError("群组ID无效")
        return (
            CommandType.GROUP_WHOLE_BAN.value,
            {
                "group_id": group_id,
                "enable": enable,
            },
        )

    def handle_kick_command(self, args: Dict[str, Any], group_info: GroupInfo) -> Tuple[str, Dict[str, Any]]:
        """处理群成员踢出命令

        Args:
            args (Dict[str, Any]): 参数字典
            group_info (GroupInfo): 群聊信息（对应目标群聊）

        Returns:
            Tuple[CommandType, Dict[str, Any]]
        """
        user_id: int = int(args["qq_id"])
        group_id: int = int(group_info.group_id)
        if group_id <= 0:
            raise ValueError("群组ID无效")
        if user_id <= 0:
            raise ValueError("用户ID无效")
        return (
            CommandType.GROUP_KICK.value,
            {
                "group_id": group_id,
                "user_id": user_id,
                "reject_add_request": False,  # 不拒绝加群请求
            },
        )

    def handle_poke_command(self, args: Dict[str, Any], group_info: GroupInfo) -> Tuple[str, Dict[str, Any]]:
        """处理戳一戳命令

        Args:
            args (Dict[str, Any]): 参数字典
            group_info (GroupInfo): 群聊信息（对应目标群聊）

        Returns:
            Tuple[CommandType, Dict[str, Any]]
        """
        user_id: int = int(args["qq_id"])
        if group_info is None:
            group_id = None
        else:
            group_id: int = int(group_info.group_id)
            if group_id <= 0:
                raise ValueError("群组ID无效")
        if user_id <= 0:
            raise ValueError("用户ID无效")
        return (
            CommandType.SEND_POKE.value,
            {
                "group_id": group_id,
                "user_id": user_id,
            },
        )

    def delete_msg_command(self, args: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
        """处理撤回消息命令

        Args:
            args (Dict[str, Any]): 参数字典

        Returns:
            Tuple[CommandType, Dict[str, Any]]
        """
        try:
            message_id = int(args["message_id"])
            if message_id <= 0:
                raise ValueError("消息ID无效")
        except KeyError:
            raise ValueError("缺少必需参数: message_id") from None
        except (ValueError, TypeError) as e:
            raise ValueError(f"消息ID无效: {args['message_id']} - {str(e)}") from None

        return (
            CommandType.DELETE_MSG.value,
            {
                "message_id": message_id,
            },
        )

    def handle_ai_voice_send_command(self, args: Dict[str, Any], group_info: GroupInfo) -> Tuple[str, Dict[str, Any]]:
        """
        处理AI语音发送命令的逻辑。
        并返回 NapCat 兼容的 (action, params) 元组。
        """
        if not group_info or not group_info.group_id:
            raise ValueError("AI语音发送命令必须在群聊上下文中使用")
        if not args:
            raise ValueError("AI语音发送命令缺少参数")

        group_id: int = int(group_info.group_id)
        character_id = args.get("character")
        text_content = args.get("text")

        if not character_id or not text_content:
            raise ValueError(f"AI语音发送命令参数不完整: character='{character_id}', text='{text_content}'")

        return (
            CommandType.AI_VOICE_SEND.value,
            {
                "group_id": group_id,
                "text": text_content,
                "character": character_id,
            },
        )

    async def send_message_to_napcat(self, action: str, params: dict) -> dict:
        request_uuid = str(uuid.uuid4())
        payload = json.dumps({"action": action, "params": params, "echo": request_uuid})
        await self.server_connection.send(payload)
        try:
            response = await get_response(request_uuid)
        except TimeoutError:
            logger.error("发送消息超时，未收到响应")
            return {"status": "error", "message": "timeout"}
        except Exception as e:
            logger.error(f"发送消息失败: {e}")
            return {"status": "error", "message": str(e)}
        return response

    async def message_sent_back(self, message_base: MessageBase, qq_message_id: str) -> None:
        # 修改 additional_config，添加 echo 字段
        if message_base.message_info.additional_config is None:
            message_base.message_info.additional_config = {}

        message_base.message_info.additional_config["echo"] = True

        # 获取原始的 mmc_message_id
        mmc_message_id = message_base.message_info.message_id

        # 修改 message_segment 为 notify 类型
        message_base.message_segment = Seg(
            type="notify", data={"sub_type": "echo", "echo": mmc_message_id, "actual_id": qq_message_id}
        )
        await message_send_instance.message_send(message_base)
        logger.debug("已回送消息ID")
        return


send_handler = SendHandler()
