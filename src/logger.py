from loguru import logger
from .config import global_config
import sys
# import builtins

logger.remove()
logger.add(
    sys.stderr,
    level=global_config.debug_level,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
)


# def handle_output(message: str):
#     if "连接失败" in message:
#         logger.error(message)
#     elif "收到无效的" in message:
#         logger.warning(message)
#     elif "检测到平台" in message:
#         logger.warning(message)
#     else:
#         logger.info(message)


# builtins.print = handle_output
