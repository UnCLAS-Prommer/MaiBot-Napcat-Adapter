from .logger import logger
from .config import global_config
import time
import asyncio
import json
import websockets.asyncio.server as Server
from typing import List

from . import MetaEventType, RealMessageType, MessageType
from maim_message import (
    UserInfo,
    GroupInfo,
    Seg,
    BaseMessageInfo,
    MessageBase,
    TemplateInfo,
    FormatInfo,
    Router,
)

from .utils import get_group_info, get_member_info, get_image_base64, get_self_info


class RecvHandler:
    maibot_router: Router = None

    def __init__(self):
        self.server_connection: Server.ServerConnection = None
        self.interval = global_config.napcat_heartbeat_interval

    async def handle_meta_event(self, message: dict) -> None:
        event_type = message.get("meta_event_type")
        if event_type == MetaEventType.lifecycle:
            sub_type = message.get("sub_type")
            if sub_type == MetaEventType.Lifecycle.connect:
                self_id = message.get("self_id")
                self.last_heart_beat = time.time()
                logger.info(f"Bot {self_id} 连接成功")
                asyncio.create_task(self.check_heartbeat(self_id))
        elif event_type == MetaEventType.heartbeat:
            if message["status"].get("online") and message["status"].get("good"):
                self.last_heart_beat = time.time()
                self.interval = message.get("interval") / 1000
            else:
                self_id = message.get("self_id")
                logger.warning(f"Bot {self_id} Napcat 端异常！")

    async def check_heartbeat(self, id: int) -> None:
        while True:
            now_time = time.time()
            if now_time - self.last_heart_beat > self.interval + 3:
                logger.warning(f"Bot {id} 连接已断开")
                break
            else:
                logger.debug("心跳正常")
            await asyncio.sleep(self.interval)

    async def handle_raw_message(self, raw_message: dict) -> None:
        """
        从Napcat接受的原始消息处理

        参数:
            raw_message: dict: 原始消息
        返回值:
            None
        """
        message_type: str = raw_message.get("message_type")
        message_id: int = raw_message.get("message_id")
        message_time: int = raw_message.get("time")

        template_info: TemplateInfo = None  # 模板信息，暂时为空，等待启用
        format_info: FormatInfo = None  # 格式化信息，暂时为空，等待启用

        if message_type == MessageType.private:
            sub_type = raw_message.get("sub_type")
            if sub_type == MessageType.Private.friend:
                sender_info: dict = raw_message.get("sender")

                # 发送者用户信息
                user_info: UserInfo = UserInfo(
                    platform=global_config.platform,
                    user_id=sender_info.get("user_id"),
                    user_nickname=sender_info.get("nickname"),
                    user_cardname=sender_info.get("card"),
                )

                # 不存在群信息
                group_info: GroupInfo = None
            elif sub_type == MessageType.Private.group:
                """
                本部分暂时不做支持，先放着
                """
                logger.warning("群临时消息类型不支持")
                return None

                sender_info: dict = raw_message.get("sender")

                # 由于临时会话中，Napcat默认不发送成员昵称，所以需要单独获取
                fetched_member_info: dict = await get_member_info(
                    self.server_connection,
                    raw_message.get("group_id"),
                    sender_info.get("user_id"),
                )
                nickname: str = None
                if fetched_member_info:
                    nickname = fetched_member_info.get("nickname")

                # 发送者用户信息
                user_info: UserInfo = UserInfo(
                    platform=global_config.platform,
                    user_id=sender_info.get("user_id"),
                    user_nickname=nickname,
                    user_cardname=None,
                )

                # -------------------这里需要群信息吗？-------------------

                # 获取群聊相关信息，在此单独处理group_name，因为默认发送的消息中没有
                fetched_group_info: dict = get_group_info(
                    self.server_connection, raw_message.get("group_id")
                )
                group_name = ""
                if fetched_group_info.get("group_name"):
                    group_name = fetched_group_info.get("group_name")

                group_info: GroupInfo = GroupInfo(
                    platform=global_config.platform,
                    group_id=raw_message.get("group_id"),
                    group_name=group_name,
                )

            else:
                logger.warning("私聊消息类型不支持")
                return None
        elif message_type == MessageType.group:
            sub_type = raw_message.get("sub_type")
            if sub_type == MessageType.Group.normal:
                sender_info: dict = raw_message.get("sender")

                # 发送者用户信息
                user_info: UserInfo = UserInfo(
                    platform=global_config.platform,
                    user_id=sender_info.get("user_id"),
                    user_nickname=sender_info.get("nickname"),
                    user_cardname=sender_info.get("card"),
                )

                # 获取群聊相关信息，在此单独处理group_name，因为默认发送的消息中没有
                fetched_group_info = await get_group_info(
                    self.server_connection, raw_message.get("group_id")
                )
                group_name: str = None
                if fetched_group_info:
                    group_name = fetched_group_info.get("group_name")

                group_info: GroupInfo = GroupInfo(
                    platform=global_config.platform,
                    group_id=raw_message.get("group_id"),
                    group_name=group_name,
                )

            else:
                logger.warning("群聊消息类型不支持")
                return None

        # 消息信息
        message_info: BaseMessageInfo = BaseMessageInfo(
            platform=global_config.platform,
            message_id=message_id,
            time=message_time,
            user_info=user_info,
            group_info=group_info,
            template_info=template_info,
            format_info=format_info,
        )

        # 处理实际信息
        if not raw_message.get("message"):
            logger.warning("消息内容为空")
            return None

        # 获取Seg列表
        seg_message: List[Seg] = await self.handle_real_message(raw_message)
        if not seg_message:
            logger.warning("消息内容为空")
            return None
        submit_seg: Seg = Seg(
            type="seglist",
            data=seg_message,
        )
        # MessageBase创建
        message_base: MessageBase = MessageBase(
            message_info=message_info,
            message_segment=submit_seg,
            raw_message=raw_message.get("raw_message"),
        )
        # 不启用发送消息
        await self.message_process(message_base)

        logger.debug("我处理！")

    async def handle_real_message(self, raw_message: dict) -> List[Seg]:
        """
        处理实际消息

        参数:
            real_message: dict: 实际消息
        返回值:
            seg_message: list[Seg]: 处理后的消息段列表
        """
        real_message: list = raw_message.get("message")
        if len(real_message) == 0:
            return None
        seg_message: List[Seg] = []
        for sub_message in real_message:
            sub_message: dict
            sub_message_type = sub_message.get("type")
            match sub_message_type:
                case RealMessageType.text:
                    ret_seg = await self.handle_text_message(sub_message)
                    seg_message.append(ret_seg)
                case RealMessageType.face:
                    pass
                case RealMessageType.image:
                    ret_seg = await self.handle_image_message(sub_message)
                    if ret_seg:
                        seg_message.append(ret_seg)
                case RealMessageType.record:
                    logger.warning("不支持语音解析")
                    pass
                case RealMessageType.video:
                    logger.warning("不支持视频解析")
                    pass
                case RealMessageType.at:
                    ret_seg = await self.handle_at_message(
                        sub_message,
                        raw_message.get("self_id"),
                        raw_message.get("group_id"),
                    )
                    if ret_seg:
                        seg_message.append(ret_seg)
                case RealMessageType.rps:
                    logger.warning("暂时不支持猜拳魔法表情解析")
                    pass
                case RealMessageType.dice:
                    logger.warning("暂时不支持筛子表情解析")
                    pass
                case RealMessageType.shake:
                    # 预计等价于戳一戳
                    logger.warning("暂时不支持窗口抖动解析")
                    pass
                case RealMessageType.poke:
                    logger.warning("暂时不支持戳一戳解析")
                    pass
                case RealMessageType.share:
                    logger.warning("链接分享？啊？你搞我啊？")
                    pass
                case RealMessageType.reply:
                    logger.warning("暂时不支持回复解析")
                    pass
                case RealMessageType.forward:
                    forward_message_id = sub_message.get("data").get("id")
                    payload = json.dumps(
                        {
                            "action": "get_forward_msg",
                            "params": {"message_id": forward_message_id},
                        }
                    )
                    await self.server_connection.send(payload)
                    response = await self.server_connection.recv()
                    logger.critical(response)
                    logger.critical(json.loads(response))
                case RealMessageType.node:
                    logger.warning("不支持转发消息节点解析")
                    pass
        return seg_message

    async def handle_text_message(self, raw_message: dict) -> Seg:
        """
        处理纯文本信息

        参数:
            raw_message: dict: 原始消息
        返回值:
            seg_data: Seg: 处理后的消息段
        """
        message_data: dict = raw_message.get("data")
        plain_text: str = message_data.get("text")
        seg_data = Seg(type=RealMessageType.text, data=plain_text)
        return seg_data

    async def handle_face_message(self) -> None:
        """
        处理表情消息

        支持未完成
        """
        pass

    async def handle_image_message(self, raw_message: dict) -> Seg:
        """
        处理图片消息与表情包消息

        参数:
            raw_message: dict: 原始消息
        返回值:
            seg_data: Seg: 处理后的消息段
        """
        message_data: dict = raw_message.get("data")
        image_base64 = await get_image_base64(message_data.get("url"))
        image_sub_type = message_data.get("sub_type")
        if not image_base64:
            return None
        if image_sub_type == 0:
            """这部分认为是图片"""
            seg_data = Seg(type="image", data=image_base64)
            return seg_data
        else:
            """这部分认为是表情包"""
            seg_data = Seg(type="emoji", data=image_base64)
            return seg_data

    async def handle_at_message(
        self, raw_message: dict, self_id: int, group_id: int
    ) -> Seg:
        """
        处理at消息
        """
        message_data: dict = raw_message.get("data")
        if message_data:
            qq_id = message_data.get("qq")
            if str(self_id) == str(qq_id):
                self_info: dict = get_self_info()
                if self_info:
                    return Seg(type="text", data=f"@{self_info.get('nickname')} ")
                else:
                    return None
            else:
                member_info: dict = get_member_info(
                    self.server_connection, group_id=group_id, user_id=self_id
                )
                if member_info:
                    return Seg(type="text", data=f"@{member_info.get('nickname')} ")
                else:
                    return None

    async def handle_poke_message(self) -> None:
        pass

    async def message_process(self, message_base: MessageBase) -> None:
        await self.maibot_router.send_message(message_base)


recv_handler = RecvHandler()
