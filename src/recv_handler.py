from .logger import logger
from .config import global_config
from .qq_emoji_list import qq_face
import time
import asyncio
import json
import websockets as Server
from typing import List, Tuple, Optional, Dict, Any
import uuid

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
    get_message_detail,
    read_bot_id,
    update_bot_id,
)
from .response_pool import get_response


class RecvHandler:
    maibot_router: Router = None

    def __init__(self):
        self.server_connection: Server.ServerConnection = None
        self.interval = global_config.napcat_server.heartbeat_interval
        self._interval_checking = False
        self.bot_id_list: Dict[int, bool] = {}

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
                if not self._interval_checking:
                    asyncio.create_task(self.check_heartbeat())
                self.last_heart_beat = time.time()
                self.interval = message.get("interval") / 1000
            else:
                self_id = message.get("self_id")
                logger.warning(f"Bot {self_id} Napcat 端异常！")

    async def check_heartbeat(self, id: int) -> None:
        self._interval_checking = True
        while True:
            now_time = time.time()
            if now_time - self.last_heart_beat > self.interval * 2:
                logger.error(f"Bot {id} 连接已断开，被下线，或者Napcat卡死！")
                break
            else:
                logger.debug("心跳正常")
            await asyncio.sleep(self.interval)

    async def check_allow_to_chat(self, user_id: int, group_id: Optional[int] = None) -> bool:
        # sourcery skip: hoist-statement-from-if, merge-else-if-into-elif
        """
        检查是否允许聊天
        Parameters:
            user_id: int: 用户ID
            group_id: int: 群ID
        Returns:
            bool: 是否允许聊天
        """
        user_id = str(user_id)
        logger.debug(f"群聊id: {group_id}, 用户id: {user_id}")
        if global_config.chat.ban_qq_bot and group_id:
            logger.debug("开始判断是否为机器人")
            if not self.bot_id_list:
                self.bot_id_list = read_bot_id()
            if user_id in self.bot_id_list:
                if self.bot_id_list[user_id]:
                    logger.warning("QQ官方机器人消息拦截已启用，消息被丢弃")
                    return False
            else:
                member_info = await get_member_info(self.server_connection, group_id, user_id)
                if member_info:
                    is_bot = member_info.get("is_robot")
                    if is_bot is None:
                        logger.warning("无法获取用户是否为机器人，默认为不是但是不进行更新")
                    else:
                        if is_bot:
                            logger.warning("QQ官方机器人消息拦截已启用，消息被丢弃，新机器人加入拦截名单")
                            self.bot_id_list[user_id] = True
                            update_bot_id(self.bot_id_list)
                            return False
                        else:
                            self.bot_id_list[user_id] = False
                            update_bot_id(self.bot_id_list)
        user_id = int(user_id)
        logger.debug("开始检查聊天白名单/黑名单")
        if group_id:
            if global_config.chat.group_list_type == "whitelist" and group_id not in global_config.chat.group_list:
                logger.warning("群聊不在聊天白名单中，消息被丢弃")
                return False
            elif global_config.chat.group_list_type == "blacklist" and group_id in global_config.chat.group_list:
                logger.warning("群聊在聊天黑名单中，消息被丢弃")
                return False
        else:
            if global_config.chat.private_list_type == "whitelist" and user_id not in global_config.chat.private_list:
                logger.warning("私聊不在聊天白名单中，消息被丢弃")
                return False
            elif global_config.chat.private_list_type == "blacklist" and user_id in global_config.chat.private_list:
                logger.warning("私聊在聊天黑名单中，消息被丢弃")
                return False
        if user_id in global_config.chat.ban_user_id:
            logger.warning("用户在全局黑名单中，消息被丢弃")
            return False
        return True

    async def handle_raw_message(self, raw_message: dict) -> None:
        # sourcery skip: low-code-quality, remove-unreachable-code
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
        format_info: FormatInfo = FormatInfo(
            content_format=["text", "image", "emoji"],
            accept_format=["text", "image", "emoji", "reply", "voice", "command"],
        )  # 格式化信息
        if message_type == MessageType.private:
            sub_type = raw_message.get("sub_type")
            if sub_type == MessageType.Private.friend:
                sender_info: dict = raw_message.get("sender")

                if not await self.check_allow_to_chat(sender_info.get("user_id"), None):
                    return None

                # 发送者用户信息
                user_info: UserInfo = UserInfo(
                    platform=global_config.maibot_server.platform_name,
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
                nickname = fetched_member_info.get("nickname") if fetched_member_info else None
                # 发送者用户信息
                user_info: UserInfo = UserInfo(
                    platform=global_config.maibot_server.platform_name,
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
                    platform=global_config.maibot_server.platform_name,
                    group_id=raw_message.get("group_id"),
                    group_name=group_name,
                )

            else:
                logger.warning(f"私聊消息类型 {sub_type} 不支持")
                return None
        elif message_type == MessageType.group:
            sub_type = raw_message.get("sub_type")
            if sub_type == MessageType.Group.normal:
                sender_info: dict = raw_message.get("sender")

                if not await self.check_allow_to_chat(sender_info.get("user_id"), raw_message.get("group_id")):
                    return None

                # 发送者用户信息
                user_info: UserInfo = UserInfo(
                    platform=global_config.maibot_server.platform_name,
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
                    platform=global_config.maibot_server.platform_name,
                    group_id=raw_message.get("group_id"),
                    group_name=group_name,
                )

            else:
                logger.warning(f"群聊消息类型 {sub_type} 不支持")
                return None

        additional_config: dict = {}
        if global_config.voice.use_tts:
            additional_config["allow_tts"] = True

        # 消息信息
        message_info: BaseMessageInfo = BaseMessageInfo(
            platform=global_config.maibot_server.platform_name,
            message_id=message_id,
            time=message_time,
            user_info=user_info,
            group_info=group_info,
            template_info=template_info,
            format_info=format_info,
            additional_config=additional_config,
        )

        # 处理实际信息
        if not raw_message.get("message"):
            logger.warning("原始消息内容为空")
            return None

        # 获取Seg列表
        seg_message: List[Seg] = await self.handle_real_message(raw_message)
        if not seg_message:
            logger.warning("处理后消息内容为空")
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

    async def handle_real_message(self, raw_message: dict, in_reply: bool = False) -> List[Seg] | None:
        # sourcery skip: low-code-quality
        """
        处理实际消息
        Parameters:
            real_message: dict: 实际消息
        Returns:
            seg_message: list[Seg]: 处理后的消息段列表
        """
        real_message: list = raw_message.get("message")
        if not real_message:
            return None
        seg_message: List[Seg] = []
        for sub_message in real_message:
            sub_message: dict
            sub_message_type = sub_message.get("type")
            match sub_message_type:
                case RealMessageType.text:
                    ret_seg = await self.handle_text_message(sub_message)
                    if ret_seg:
                        seg_message.append(ret_seg)
                    else:
                        logger.warning("text处理失败")
                case RealMessageType.face:
                    ret_seg = await self.handle_face_message(sub_message)
                    if ret_seg:
                        seg_message.append(ret_seg)
                    else:
                        logger.warning("face处理失败或不支持")
                case RealMessageType.reply:
                    if not in_reply:
                        ret_seg = await self.handle_reply_message(sub_message)
                        if ret_seg:
                            seg_message += ret_seg
                        else:
                            logger.warning("reply处理失败")
                case RealMessageType.image:
                    ret_seg = await self.handle_image_message(sub_message)
                    if ret_seg:
                        seg_message.append(ret_seg)
                    else:
                        logger.warning("image处理失败")
                case RealMessageType.record:
                    logger.warning("不支持语音解析")
                case RealMessageType.video:
                    logger.warning("不支持视频解析")
                case RealMessageType.at:
                    ret_seg = await self.handle_at_message(
                        sub_message,
                        raw_message.get("self_id"),
                        raw_message.get("group_id"),
                    )
                    if ret_seg:
                        seg_message.append(ret_seg)
                    else:
                        logger.warning("at处理失败")
                case RealMessageType.rps:
                    logger.warning("暂时不支持猜拳魔法表情解析")
                case RealMessageType.dice:
                    logger.warning("暂时不支持骰子表情解析")
                case RealMessageType.shake:
                    # 预计等价于戳一戳
                    logger.warning("暂时不支持窗口抖动解析")
                case RealMessageType.share:
                    logger.warning("暂时不支持链接解析")
                case RealMessageType.forward:
                    messages = await self.get_forward_message(sub_message)
                    if not messages:
                        logger.warning("转发消息内容为空或获取失败")
                        return None
                    ret_seg = await self.handle_forward_message(messages)
                    if ret_seg:
                        seg_message.append(ret_seg)
                    else:
                        logger.warning("转发消息处理失败")
                case RealMessageType.node:
                    logger.warning("不支持转发消息节点解析")
                case _:
                    logger.warning(f"未知消息类型: {sub_message_type}")
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
        return Seg(type="text", data=plain_text)

    async def handle_face_message(self, raw_message: dict) -> Seg | None:
        """
        处理表情消息
        Parameters:
            raw_message: dict: 原始消息
        Returns:
            seg_data: Seg: 处理后的消息段
        """
        message_data: dict = raw_message.get("data")
        face_raw_id: str = str(message_data.get("id"))
        if face_raw_id in qq_face:
            face_content: str = qq_face.get(face_raw_id)
            return Seg(type="text", data=face_content)
        else:
            logger.warning(f"不支持的表情：{face_raw_id}")
            return None

    async def handle_image_message(self, raw_message: dict) -> Seg | None:
        """
        处理图片消息与表情包消息
        Parameters:
            raw_message: dict: 原始消息
        Returns:
            seg_data: Seg: 处理后的消息段
        """
        message_data: dict = raw_message.get("data")
        image_sub_type = message_data.get("sub_type")
        try:
            image_base64 = await get_image_base64(message_data.get("url"))
        except Exception as e:
            logger.error(f"图片消息处理失败: {str(e)}")
            return None
        if image_sub_type == 0:
            """这部分认为是图片"""
            return Seg(type="image", data=image_base64)
        elif image_sub_type == 1:
            """这部分认为是表情包"""
            return Seg(type="emoji", data=image_base64)
        else:
            logger.warning(f"不支持的图片子类型：{image_sub_type}")
            return None

    async def handle_at_message(self, raw_message: dict, self_id: int, group_id: int) -> Seg | None:
        # sourcery skip: use-named-expression
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
                logger.debug("机器人被at")
                self_info: dict = await get_self_info(self.server_connection)
                if self_info:
                    return Seg(type="text", data=f"@<{self_info.get('nickname')}:{self_info.get('user_id')}>")
                else:
                    return None
            else:
                member_info: dict = await get_member_info(self.server_connection, group_id=group_id, user_id=qq_id)
                if member_info:
                    return Seg(type="text", data=f"@<{member_info.get('nickname')}:{member_info.get('user_id')}>")
                else:
                    return None

    async def get_forward_message(self, raw_message: dict) -> Dict[str, Any] | None:
        forward_message_data: Dict = raw_message.get("data")
        if not forward_message_data:
            logger.warning("转发消息内容为空")
            return None
        forward_message_id = forward_message_data.get("id")
        request_uuid = str(uuid.uuid4())
        payload = json.dumps(
            {
                "action": "get_forward_msg",
                "params": {"message_id": forward_message_id},
                "echo": request_uuid,
            }
        )
        try:
            await self.server_connection.send(payload)
            response: dict = await get_response(request_uuid)
        except TimeoutError:
            logger.error("获取转发消息超时")
            return None
        except Exception as e:
            logger.error(f"获取转发消息失败: {str(e)}")
            return None
        logger.debug(
            f"转发消息原始格式：{json.dumps(response)[:80]}..."
            if len(json.dumps(response)) > 80
            else json.dumps(response)
        )
        response_data: Dict = response.get("data")
        if not response_data:
            logger.warning("转发消息内容为空或获取失败")
            return None
        return response_data.get("messages")

    async def handle_reply_message(self, raw_message: dict) -> List[Seg] | None:
        # sourcery skip: move-assign-in-block, use-named-expression
        """
        处理回复消息

        """
        raw_message_data: dict = raw_message.get("data")
        message_id: int = None
        if raw_message_data:
            message_id = raw_message_data.get("id")
        else:
            return None
        message_detail: dict = await get_message_detail(self.server_connection, message_id)
        if not message_detail:
            logger.warning("获取被引用的消息详情失败")
            return None
        reply_message = await self.handle_real_message(message_detail, in_reply=True)
        if reply_message is None:
            reply_message = "(获取发言内容失败)"
        sender_info: dict = message_detail.get("sender")
        sender_nickname: str = sender_info.get("nickname")
        sender_id: str = sender_info.get("user_id")
        seg_message: List[Seg] = []
        if not sender_nickname:
            logger.warning("无法获取被引用的人的昵称，返回默认值")
            seg_message.append(Seg(type="text", data="[回复 未知用户："))
        else:
            seg_message.append(Seg(type="text", data=f"[回复<{sender_nickname}:{sender_id}>："))
        seg_message += reply_message
        seg_message.append(Seg(type="text", data="]，说："))
        return seg_message

    async def handle_notice(self, raw_message: dict) -> None:
        notice_type = raw_message.get("notice_type")
        # message_time: int = raw_message.get("time")
        message_time: float = time.time()  # 应可乐要求，现在是float了

        group_id = raw_message.get("group_id")
        user_id = raw_message.get("user_id")

        if not await self.check_allow_to_chat(user_id, group_id):
            logger.warning("notice消息被丢弃")
            return None

        handled_message: Seg = None

        match notice_type:
            case NoticeType.friend_recall:
                logger.info("好友撤回一条消息")
                logger.info(f"撤回消息ID：{raw_message.get('message_id')}, 撤回时间：{raw_message.get('time')}")
                logger.warning("暂时不支持撤回消息处理")
            case NoticeType.group_recall:
                logger.info("群内用户撤回一条消息")
                logger.info(f"撤回消息ID：{raw_message.get('message_id')}, 撤回时间：{raw_message.get('time')}")
                logger.warning("暂时不支持撤回消息处理")
            case NoticeType.notify:
                sub_type = raw_message.get("sub_type")
                match sub_type:
                    case NoticeType.Notify.poke:
                        if global_config.chat.enable_poke:
                            handled_message: Seg = await self.handle_poke_notify(raw_message)
                        else:
                            logger.warning("戳一戳消息被禁用，取消戳一戳处理")
                    case _:
                        logger.warning(f"不支持的notify类型: {notice_type}.{sub_type}")
            case _:
                logger.warning(f"不支持的notice类型: {notice_type}")
                return None
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
            platform=global_config.maibot_server.platform_name,
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
            else:
                logger.warning("无法获取戳一戳消息所在群的名称")
            group_info = GroupInfo(
                platform=global_config.maibot_server.platform_name,
                group_id=group_id,
                group_name=group_name,
            )

        message_info: BaseMessageInfo = BaseMessageInfo(
            platform=global_config.maibot_server.platform_name,
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

    async def handle_poke_notify(self, raw_message: dict) -> Seg | None:
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
            target_name = self_info.get("nickname")
        else:
            return None
        try:
            first_txt = raw_info[2].get("txt", "戳了戳")
            second_txt = raw_info[4].get("txt", "")
        except Exception as e:
            logger.warning(f"解析戳一戳消息失败: {str(e)}，将使用默认文本")
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
            data=f"{first_txt}{target_name}{second_txt}（这是QQ的一个功能，用于提及某人，但没那么明显）",
        )
        return seg_data

    async def handle_forward_message(self, message_list: list) -> Seg | None:
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
            logger.trace("图片数量小于5，开始解析图片为base64")
            return await self._recursive_parse_image_seg(handled_message, True)
        elif image_count > 0:
            logger.trace("图片数量大于等于5，开始解析图片为占位符")
            # 处理图片数量大于等于5的情况，此时解析图片为占位符
            return await self._recursive_parse_image_seg(handled_message, False)
        else:
            # 处理没有图片的情况，此时直接返回
            logger.trace("没有图片，直接返回")
            return handled_message

    async def _recursive_parse_image_seg(self, seg_data: Seg, to_image: bool) -> Seg:
        # sourcery skip: merge-else-if-into-elif
        if to_image:
            if seg_data.type == "seglist":
                new_seg_list = []
                for i_seg in seg_data.data:
                    parsed_seg = await self._recursive_parse_image_seg(i_seg, to_image)
                    new_seg_list.append(parsed_seg)
                return Seg(type="seglist", data=new_seg_list)
            elif seg_data.type == "image":
                image_url = seg_data.data
                try:
                    encoded_image = await get_image_base64(image_url)
                except Exception as e:
                    logger.error(f"图片处理失败: {str(e)}")
                    return Seg(type="text", data="[图片]")
                return Seg(type="image", data=encoded_image)
            elif seg_data.type == "emoji":
                image_url = seg_data.data
                try:
                    encoded_image = await get_image_base64(image_url)
                except Exception as e:
                    logger.error(f"图片处理失败: {str(e)}")
                    return Seg(type="text", data="[表情包]")
                return Seg(type="emoji", data=encoded_image)
            else:
                logger.trace(f"不处理类型: {seg_data.type}")
                return seg_data
        else:
            if seg_data.type == "seglist":
                new_seg_list = []
                for i_seg in seg_data.data:
                    parsed_seg = await self._recursive_parse_image_seg(i_seg, to_image)
                    new_seg_list.append(parsed_seg)
                return Seg(type="seglist", data=new_seg_list)
            elif seg_data.type == "image":
                return Seg(type="text", data="[图片]")
            elif seg_data.type == "emoji":
                return Seg(type="text", data="[动画表情]")
            else:
                logger.trace(f"不处理类型: {seg_data.type}")
                return seg_data

    async def _handle_forward_message(self, message_list: list, layer: int) -> Tuple[Seg, int] | Tuple[None, int]:
        # sourcery skip: low-code-quality
        """
        递归处理实际转发消息
        Parameters:
            message_list: list: 转发消息列表，首层对应messages字段，后面对应content字段
            layer: int: 当前层级
        Returns:
            seg_data: Seg: 处理后的消息段
            image_count: int: 图片数量
        """
        seg_list: List[Seg] = []
        image_count = 0
        if message_list is None:
            return None, 0
        for sub_message in message_list:
            sub_message: dict
            sender_info: dict = sub_message.get("sender")
            user_nickname: str = sender_info.get("nickname", "QQ用户")
            user_nickname_str = f"【{user_nickname}】:"
            break_seg = Seg(type="text", data="\n")
            message_of_sub_message_list: List[Dict[str, Any]] = sub_message.get("message")
            if not message_of_sub_message_list:
                logger.warning("转发消息内容为空")
                continue
            message_of_sub_message = message_of_sub_message_list[0]
            if message_of_sub_message.get("type") == RealMessageType.forward:
                if layer >= 3:
                    full_seg_data = Seg(
                        type="text",
                        data=("--" * layer) + f"【{user_nickname}】:【转发消息】\n",
                    )
                else:
                    sub_message_data = message_of_sub_message.get("data")
                    if not sub_message_data:
                        continue
                    contents = sub_message_data.get("content")
                    seg_data, count = await self._handle_forward_message(contents, layer + 1)
                    image_count += count
                    head_tip = Seg(
                        type="text",
                        data=("--" * layer) + f"【{user_nickname}】: 合并转发消息内容：\n",
                    )
                    full_seg_data = Seg(type="seglist", data=[head_tip, seg_data])
                seg_list.append(full_seg_data)
            elif message_of_sub_message.get("type") == RealMessageType.text:
                sub_message_data = message_of_sub_message.get("data")
                if not sub_message_data:
                    continue
                text_message = sub_message_data.get("text")
                seg_data = Seg(type="text", data=text_message)
                data_list: List[Any] = []
                if layer > 0:
                    data_list = [
                        Seg(type="text", data=("--" * layer) + user_nickname_str),
                        seg_data,
                        break_seg,
                    ]
                else:
                    data_list = [
                        Seg(type="text", data=user_nickname_str),
                        seg_data,
                        break_seg,
                    ]
                seg_list.append(Seg(type="seglist", data=data_list))
            elif message_of_sub_message.get("type") == RealMessageType.image:
                image_count += 1
                image_data = message_of_sub_message.get("data")
                sub_type = image_data.get("sub_type")
                image_url = image_data.get("url")
                data_list: List[Any] = []
                if sub_type == 0:
                    seg_data = Seg(type="image", data=image_url)
                else:
                    seg_data = Seg(type="emoji", data=image_url)
                if layer > 0:
                    data_list = [
                        Seg(type="text", data=("--" * layer) + user_nickname_str),
                        seg_data,
                        break_seg,
                    ]
                else:
                    data_list = [
                        Seg(type="text", data=user_nickname_str),
                        seg_data,
                        break_seg,
                    ]
                full_seg_data = Seg(type="seglist", data=data_list)
                seg_list.append(full_seg_data)
        return Seg(type="seglist", data=seg_list), image_count

    async def message_process(self, message_base: MessageBase) -> None:
        try:
            send_status = await self.maibot_router.send_message(message_base)
            if not send_status:
                raise RuntimeError("发送消息失败，可能是路由未正确配置或连接异常")
        except Exception as e:
            logger.error(f"发送消息失败: {str(e)}")
            logger.error("请检查与MaiBot之间的连接")
            return None


recv_handler = RecvHandler()
