import asyncio
import sys
import json
import http
import signal
import websockets as Server
from src.logger import logger
from src.recv_handler.message_handler import message_handler
from src.recv_handler.meta_event_handler import meta_event_handler
from src.recv_handler.notice_handler import notice_handler
from src.recv_handler.message_sending import message_send_instance
from src.send_handler.nc_sending import nc_message_sender
from src.config import global_config
from src.mmc_com_layer import mmc_start_com, mmc_stop_com, router
from src.response_pool import put_response, check_timeout_response

message_queue = asyncio.Queue()
server: Server.Server = None


async def message_recv(server_connection: Server.ServerConnection):
    await message_handler.set_server_connection(server_connection)
    asyncio.create_task(notice_handler.set_server_connection(server_connection))
    await nc_message_sender.set_server_connection(server_connection)
    async for raw_message in server_connection:
        logger.debug(f"{raw_message[:1500]}..." if (len(raw_message) > 1500) else raw_message)
        decoded_raw_message: dict = json.loads(raw_message)
        post_type = decoded_raw_message.get("post_type")
        if post_type in ["meta_event", "message", "notice"]:
            await message_queue.put(decoded_raw_message)
        elif post_type is None:
            await put_response(decoded_raw_message)


async def message_process():
    while True:
        message = await message_queue.get()
        post_type = message.get("post_type")
        if post_type == "message":
            await message_handler.handle_raw_message(message)
        elif post_type == "meta_event":
            await meta_event_handler.handle_meta_event(message)
        elif post_type == "notice":
            await notice_handler.handle_notice(message)
        else:
            logger.warning(f"未知的post_type: {post_type}")
        message_queue.task_done()


async def main():
    message_send_instance.maibot_router = router
    _ = await asyncio.gather(napcat_server(), mmc_start_com(), message_process(), check_timeout_response())


def check_napcat_server_token(conn, request):
    token = global_config.napcat_server.token
    if not token or token.strip() == "":
        return None
    auth_header = request.headers.get("Authorization")
    if auth_header != f"Bearer {token}":
        return Server.Response(
            status=http.HTTPStatus.UNAUTHORIZED,
            headers=Server.Headers([("Content-Type", "text/plain")]),
            body=b"Unauthorized\n",
        )
    return None


async def napcat_server():
    global server
    logger.info("正在启动adapter...")
    server = await Server.serve(
        message_recv,
        global_config.napcat_server.host,
        global_config.napcat_server.port,
        max_size=2**26,
        process_request=check_napcat_server_token,
    )
    logger.info(f"Adapter已启动，监听地址: ws://{global_config.napcat_server.host}:{global_config.napcat_server.port}")
    await server.wait_closed()


async def graceful_shutdown(loop: asyncio.AbstractEventLoop, timeout: float = 10.0):
    logger.info("正在关闭adapter...")

    # 主动关闭所有 websocket 连接
    if server and server.is_serving() and server.connections:
        logger.info(f"正在关闭 {len(server.connections)} 个客户端连接...")
        close_tasks = [conn.close() for conn in server.connections]
        await asyncio.gather(*close_tasks, return_exceptions=True)

    # 关闭服务器，停止接受新连接
    if server and server.is_serving():
        logger.info("正在关闭 Websocket 服务器...")
        server.close()
        await server.wait_closed()
        logger.info("Websocket 服务器已关闭")

    # 关闭 aiohttp 客户端
    await mmc_stop_com()
    logger.info("MMC com layer 已停止")

    # 取消所有其他任务
    tasks = [t for t in asyncio.all_tasks(loop=loop) if t is not asyncio.current_task()]
    if tasks:
        logger.info(f"正在取消 {len(tasks)} 个剩余任务...")
        for task in tasks:
            task.cancel()

        await asyncio.gather(*tasks, return_exceptions=True)
        logger.info("所有剩余任务已处理完毕")

    logger.info("Adapter 已成功关闭")


if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    shutdown_event = asyncio.Event()

    def _shutdown_handler(sig: int):
        logger.warning(f"收到信号 {signal.Signals(sig).name}，开始关闭...")
        shutdown_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _shutdown_handler, sig)
        except NotImplementedError:
            pass  # Windows

    try:
        main_task = loop.create_task(main())
        loop.run_until_complete(shutdown_event.wait())
    finally:
        logger.info("开始优雅关闭流程...")

        # 执行新的关机流程
        loop.run_until_complete(graceful_shutdown(loop=loop))

        # 最终关闭循环
        if loop and not loop.is_closed():
            loop.close()
        logger.info("程序已退出")
        sys.exit(0)