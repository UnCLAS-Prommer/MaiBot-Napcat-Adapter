import asyncio
import sys
import json
import websockets as Server
from src.logger import logger
from src.recv_handler import recv_handler
from src.send_handler import send_handler
from src.config import global_config
from src.mmc_com_layer import mmc_start_com, mmc_stop_com, router
from src.message_queue import message_queue, put_response, check_timeout_response


async def message_recv(server_connection: Server.ServerConnection):
    recv_handler.server_connection = server_connection
    send_handler.server_connection = server_connection
    async for raw_message in server_connection:
        logger.debug(f"{raw_message[:100]}..." if len(raw_message) > 100 else raw_message)
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
            await recv_handler.handle_raw_message(message)
        elif post_type == "meta_event":
            await recv_handler.handle_meta_event(message)
        elif post_type == "notice":
            await recv_handler.handle_notice(message)
        else:
            logger.warning(f"未知的post_type: {post_type}")
        message_queue.task_done()
        await asyncio.sleep(0.05)


async def main():
    recv_handler.maibot_router = router
    _ = await asyncio.gather(napcat_server(), mmc_start_com(), message_process(), check_timeout_response())


async def napcat_server():
    logger.info("正在启动adapter...")
    async with Server.serve(message_recv, global_config.server_host, global_config.server_port) as server:
        logger.info(f"Adapter已启动，监听地址: ws://{global_config.server_host}:{global_config.server_port}")
        await server.serve_forever()


async def graceful_shutdown():
    try:
        logger.info("正在关闭adapter...")
        await mmc_stop_com()
        tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    except Exception as e:
        logger.error(f"Adapter关闭中出现错误: {e}")


if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        logger.warning("收到中断信号，正在优雅关闭...")
        loop.run_until_complete(graceful_shutdown())
    except Exception as e:
        logger.exception(f"主程序异常: {str(e)}")
        sys.exit(1)
    finally:
        if loop and not loop.is_closed():
            loop.close()
        sys.exit(0)
