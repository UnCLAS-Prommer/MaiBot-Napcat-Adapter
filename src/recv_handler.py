from .logger import logger
from .config import global_config
import time
import asyncio
import json
import websockets.asyncio.server as Server
from typing import List, Tuple

from . import MetaEventType, RealMessageType, MessageType, NoticeType
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

from .utils import (
    get_group_info,
    get_member_info,
    get_image_base64,
    get_self_info,
    get_stranger_info,
)
from .message_queue import get_response


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

        Parameters:
            raw_message: dict: 原始消息
        """
        message_type: str = raw_message.get("message_type")
        message_id: int = raw_message.get("message_id")
        # message_time: int = raw_message.get("time")
        message_time: float = time.time()  # 应可乐要求，现在是float了

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
                fetched_group_info: dict = await get_group_info(self.server_connection, raw_message.get("group_id"))
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
                fetched_group_info = await get_group_info(self.server_connection, raw_message.get("group_id"))
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

        logger.info("发送到Maibot处理信息")
        await self.message_process(message_base)

    async def handle_real_message(self, raw_message: dict) -> List[Seg]:
        """
        处理实际消息
        Parameters:
            real_message: dict: 实际消息
        Returns:
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
                    logger.warning("暂时不支持骰子表情解析")
                    pass
                case RealMessageType.shake:
                    # 预计等价于戳一戳
                    logger.warning("暂时不支持窗口抖动解析")
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
                    # response = await self.server_connection.recv()
                    response: dict = await get_response()
                    logger.debug(
                        f"转发消息原始格式：{json.dumps(response)[:80]}..."
                        if len(json.dumps(response)) > 80
                        else json.dumps(response)
                    )
                    messages = response.get("data").get("messages")
                    ret_seg = await self.handle_forward_message(messages)
                    if ret_seg:
                        seg_message.append(ret_seg)
                case RealMessageType.node:
                    logger.warning("不支持转发消息节点解析")
                    pass
        return seg_message

    async def handle_text_message(self, raw_message: dict) -> Seg:
        """
        处理纯文本信息
        Parameters:
            raw_message: dict: 原始消息
        Returns:
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
        Parameters:
            raw_message: dict: 原始消息
        Returns:
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

    async def handle_at_message(self, raw_message: dict, self_id: int, group_id: int) -> Seg:
        """
        处理at消息
        Parameters:
            raw_message: dict: 原始消息
            self_id: int: 机器人QQ号
            group_id: int: 群号
        Returns:
            seg_data: Seg: 处理后的消息段
        """
        message_data: dict = raw_message.get("data")
        if message_data:
            qq_id = message_data.get("qq")
            if str(self_id) == str(qq_id):
                self_info: dict = await get_self_info(self.server_connection)
                if self_info:
                    return Seg(type=RealMessageType.text, data=f"@{self_info.get('nickname')}")
                else:
                    return None
            else:
                member_info: dict = await get_member_info(self.server_connection, group_id=group_id, user_id=self_id)
                if member_info:
                    return Seg(
                        type=RealMessageType.text,
                        data=f"@{member_info.get('nickname')}",
                    )
                else:
                    return None

    async def handle_notice(self, raw_message: dict) -> None:
        notice_type = raw_message.get("notice_type")
        # message_time: int = raw_message.get("time")
        message_time: float = time.time()  # 应可乐要求，现在是float了

        group_id = raw_message.get("group_id")
        user_id = raw_message.get("user_id")
        handled_message: Seg = None

        match notice_type:
            case NoticeType.friend_recall:
                logger.info("好友撤回一条消息")
                logger.info(f"撤回消息ID：{raw_message.get('message_id')}, 撤回时间：{raw_message.get('time')}")
                logger.warning("暂时不支持撤回消息处理")
                pass
            case NoticeType.group_recall:
                logger.info("群内用户撤回一条消息")
                logger.info(f"撤回消息ID：{raw_message.get('message_id')}, 撤回时间：{raw_message.get('time')}")
                logger.warning("暂时不支持撤回消息处理")
                pass
            case NoticeType.notify:
                sub_type = raw_message.get("sub_type")
                match sub_type:
                    case NoticeType.Notify.poke:
                        handled_message: Seg = await self.handle_poke_notify(raw_message)
        if not handled_message:
            logger.warning("notice处理失败或不支持")
            return None

        source_name: str = None
        source_cardname: str = None
        if group_id:
            member_info: dict = await get_member_info(self.server_connection, group_id, user_id)
            if member_info:
                source_name = member_info.get("nickname")
                source_cardname = member_info.get("card")
            else:
                logger.warning("无法获取戳一戳消息发送者的昵称，消息可能会无效")
                source_name = "QQ用户"
        else:
            stranger_info = await get_stranger_info(self.server_connection, user_id)
            if stranger_info:
                source_name = stranger_info.get("nickname")
            else:
                logger.warning("无法获取戳一戳消息发送者的昵称，消息可能会无效")
                source_name = "QQ用户"

        user_info: UserInfo = UserInfo(
            platform=global_config.platform,
            user_id=user_id,
            user_nickname=source_name,
            user_cardname=source_cardname,
        )

        group_info: GroupInfo = None
        if group_id:
            fetched_group_info = await get_group_info(self.server_connection, group_id)
            group_name: str = None
            if fetched_group_info:
                group_name = fetched_group_info.get("group_name")
            group_info = GroupInfo(
                platform=global_config.platform,
                group_id=group_id,
                group_name=group_name,
            )

        message_info: BaseMessageInfo = BaseMessageInfo(
            platform=global_config.platform,
            message_id="notice",
            time=message_time,
            user_info=user_info,
            group_info=group_info,
            template_info=None,
            format_info=None,
        )

        message_base: MessageBase = MessageBase(
            message_info=message_info,
            message_segment=handled_message,
            raw_message=json.dumps(raw_message),
        )

        logger.info("发送到Maibot处理通知信息")
        await self.message_process(message_base)

    async def handle_poke_notify(self, raw_message: dict) -> Seg:
        self_info: dict = await get_self_info(self.server_connection)
        if not self_info:
            logger.error("自身信息获取失败")
            return None
        self_id = raw_message.get("self_id")
        target_id = raw_message.get("target_id")
        target_name: str = None
        raw_info: list = raw_message.get("raw_info")
        # 计算Seg
        if self_id == target_id:
            if self_info:
                target_name = self_info.get("nickname")
            else:
                logger.warning("无法获取bot的昵称，戳一戳消息可能无效")
                target_name = "你"
        try:
            first_txt = raw_info[2].get("text", "戳了戳")
            second_txt = raw_info[4].get("text", "")
        except Exception as e:
            logger.warning(f"解析戳一戳消息失败，使用默认文本：{str(e)}")
            first_txt = "戳了戳"
            second_txt = ""
        """
        # 不启用戳其他人的处理
        else:
            # 由于Napcat不支持获取昵称，所以需要单独获取
            group_id = raw_message.get("group_id")
            fetched_member_info: dict = await get_member_info(
                self.server_connection, group_id, target_id
            )
            if fetched_member_info:
                target_name = fetched_member_info.get("nickname")
        """
        seg_data: Seg = Seg(
            type="text",
            data=f"{first_txt}{target_name}{second_txt}（这是一个类似摸摸头的友善行为，不是恶意行为，请不要作出攻击发言）",
        )
        return seg_data

    async def handle_forward_message(self, message_list: list) -> Seg:
        """
        递归处理转发消息，并按照动态方式确定图片处理方式
        Parameters:
            message_list: list: 转发消息列表
        """
        handled_message, image_count = await self._handle_forward_message(message_list, 0)
        handled_message: Seg
        image_count: int
        if not handled_message:
            return None
        if image_count < 5 and image_count > 0:
            # 处理图片数量小于5的情况，此时解析图片为base64
            parsed_handled_message = await self._recursive_parse_image_seg(handled_message, True)
            return parsed_handled_message
        elif image_count > 0:
            # 处理图片数量大于等于5的情况，此时解析图片为占位符
            parsed_handled_message = await self._recursive_parse_image_seg(handled_message, False)
            return parsed_handled_message
        else:
            # 处理没有图片的情况，此时直接返回
            return handled_message

    async def _recursive_parse_image_seg(self, seg_data: Seg, to_image: bool) -> Seg:
        if to_image:
            if seg_data.type == "seglist":
                new_seg_list = []
                for i_seg in seg_data.data:
                    parsed_seg = await self._recursive_parse_image_seg(i_seg, to_image)
                    new_seg_list.append(parsed_seg)
                return Seg(type="seglist", data=new_seg_list)
            elif seg_data.type == "image":
                image_url = seg_data.data
                encoded_image = await get_image_base64(image_url)
                return Seg(type="image", data=encoded_image)
            elif seg_data.type == "emoji":
                image_url = seg_data.data
                encoded_image = await get_image_base64(image_url)
                return Seg(type="emoji", data=encoded_image)
            else:
                return seg_data
        else:
            if seg_data.type == "seglist":
                new_seg_list = []
                for i_seg in seg_data.data:
                    parsed_seg = await self._recursive_parse_image_seg(i_seg, to_image)
                    new_seg_list.append(parsed_seg)
                return Seg(type="seglist", data=new_seg_list)
            elif seg_data.type == "image":
                image_url = seg_data.data
                return Seg(type="text", data="【图片】")
            elif seg_data.type == "emoji":
                image_url = seg_data.data
                return Seg(type="text", data="【动画表情】")
            else:
                return seg_data

    async def _handle_forward_message(self, message_list: list, layer: int) -> Tuple[Seg, int]:
        """
        递归处理实际转发消息
        Parameters:
            message_list: list: 转发消息列表，首层对应messages字段，后面对应content字段
            layer: int: 当前层级
        Returns:
            seg_data: Seg: 处理后的消息段
            image_count: int: 图片数量
        """
        seg_list = []
        image_count = 0
        if message_list is None or len(message_list) == 0:
            return None, 0
        for sub_message in message_list:
            sub_message: dict
            sender_info: dict = sub_message.get("sender")
            user_nickname: str = sender_info.get("nickname", "QQ用户")
            user_nickname_str = f"【{user_nickname}】:"
            break_seg = Seg(type="text", data="\n")
            message_of_sub_message: dict = sub_message.get("message")[0]
            if message_of_sub_message.get("type") == RealMessageType.forward:
                if layer >= 3:
                    full_seg_data = (
                        Seg(
                            type="text",
                            data=("--" * layer) + f"【{user_nickname}】:【转发消息】\n",
                        ),
                        0,
                    )
                else:
                    contents = message_of_sub_message.get("data").get("content")
                    seg_data, count = await self._handle_forward_message(contents, layer + 1)
                    image_count += count
                    head_tip = Seg(
                        type="text",
                        data=("--" * layer) + f"【{user_nickname}】: 合并转发消息内容：\n",
                    )
                    full_seg_data = Seg(type="seglist", data=[head_tip, seg_data])
                seg_list.append(full_seg_data)
            elif message_of_sub_message.get("type") == RealMessageType.text:
                text_message = message_of_sub_message.get("data").get("text")
                seg_data = Seg(type="text", data=text_message)
                if layer > 0:
                    seg_list.append(
                        Seg(
                            type="seglist",
                            data=[
                                Seg(type="text", data=("--" * layer) + user_nickname_str),
                                seg_data,
                                break_seg,
                            ],
                        )
                    )
                else:
                    seg_list.append(
                        Seg(
                            type="seglist",
                            data=[
                                Seg(type="text", data=user_nickname_str),
                                seg_data,
                                break_seg,
                            ],
                        )
                    )
            elif message_of_sub_message.get("type") == RealMessageType.image:
                image_count += 1
                image_data = message_of_sub_message.get("data")
                sub_type = image_data.get("sub_type")
                image_url = image_data.get("url")
                if sub_type == 0:
                    seg_data = Seg(type="image", data=image_url)
                else:
                    seg_data = Seg(type="emoji", data=image_url)
                if layer > 0:
                    full_seg_data = Seg(
                        type="seglist",
                        data=[
                            Seg(type="text", data=("--" * layer) + user_nickname_str),
                            seg_data,
                            break_seg,
                        ],
                    )
                else:
                    full_seg_data = Seg(
                        type="seglist",
                        data=[
                            Seg(type="text", data=user_nickname_str),
                            seg_data,
                            break_seg,
                        ],
                    )
                seg_list.append(full_seg_data)
        return Seg(type="seglist", data=seg_list), image_count

    async def message_process(self, message_base: MessageBase) -> None:
        await self.maibot_router.send_message(message_base)


recv_handler = RecvHandler()
