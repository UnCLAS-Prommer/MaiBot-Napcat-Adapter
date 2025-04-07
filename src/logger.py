from loguru import logger
import builtins


def handle_output(message: str):
    if "连接失败" in message:
        logger.error(message)
    elif "收到无效的" in message:
        logger.warning(message)
    elif "检测到平台" in message:
        logger.warning(message)
    else:
        logger.info(message)


# builtins.print = handle_output
