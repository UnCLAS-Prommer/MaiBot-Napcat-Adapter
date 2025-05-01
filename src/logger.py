from loguru import logger
from typing import Optional, Union, List, Tuple
import sys
import os
from types import ModuleType
from pathlib import Path
from .config import global_config

# 保存原生处理器ID
default_handler_id = None
for handler_id in logger._core.handlers:
    default_handler_id = handler_id
    break

# 移除默认处理器
if default_handler_id is not None:
    logger.remove(default_handler_id)

# 类型别名
LoguruLogger = logger.__class__

# 全局注册表：记录模块与处理器ID的映射
_handler_registry: dict[str, List[int]] = {}
_custom_style_handlers: dict[Tuple[str, str], List[int]] = {}  # 记录自定义样式处理器ID

# 获取日志存储根地址
current_file_path = Path(__file__).resolve()
LOG_ROOT = "logs"

# LOG_LEVEL = global_config.get("Debug", {}).get("level", "INFO").upper()
# print(global_config.debug_level)

DEFAULT_CONFIG = {
        # 日志级别配置
        "console_level": global_config.debug_level,
        "file_level": "DEBUG",
        # 格式配置
        "console_format": (
            "<white>{time:YYYY-MM-DD HH:mm:ss}</white> | <level>{level: <8}</level> | <cyan>{extra[module]: <15}</cyan> | <level>{message}</level>"
        ),
        "file_format": "{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {extra[module]: <15} | {message}",
        "log_dir": LOG_ROOT,
        "rotation": "00:00",
        "retention": "3 days",
        "compression": "zip",
    }

def is_registered_module(record: dict) -> bool:
    """检查是否为已注册的模块"""
    return record["extra"].get("module") in _handler_registry


def is_unregistered_module(record: dict) -> bool:
    """检查是否为未注册的模块"""
    return not is_registered_module(record)


def log_patcher(record: dict) -> None:
    """自动填充未设置模块名的日志记录，保留原生模块名称"""
    if "module" not in record["extra"]:
        # 尝试从name中提取模块名
        module_name = record.get("name", "")
        if module_name == "":
            module_name = "root"
        record["extra"]["module"] = module_name
class LogConfig:
    """日志配置类"""

    def __init__(self, **kwargs):
        self.config = DEFAULT_CONFIG.copy()
        self.config.update(kwargs)

    def to_dict(self) -> dict:
        return self.config.copy()

    def update(self, **kwargs):
        self.config.update(kwargs)


def get_module_logger(
    module: Union[str, ModuleType],
    *,
    console_level: Optional[str] = None,
    file_level: Optional[str] = None,
    extra_handlers: Optional[List[dict]] = None,
    config: Optional[LogConfig] = None,
) -> LoguruLogger:
    module_name = module if isinstance(module, str) else module.__name__
    current_config = config.config if config else DEFAULT_CONFIG

    # 清理旧处理器
    if module_name in _handler_registry:
        for handler_id in _handler_registry[module_name]:
            logger.remove(handler_id)
        del _handler_registry[module_name]

    handler_ids = []

    # 控制台处理器
    console_id = logger.add(
        sink=sys.stderr,
        level=os.getenv("CONSOLE_LOG_LEVEL", console_level or current_config["console_level"]),
        format=current_config["console_format"],
        filter=lambda record: record["extra"].get("module") == module_name and "custom_style" not in record["extra"],
        enqueue=True,
    )
    handler_ids.append(console_id)

    # 文件处理器
    log_dir = Path("logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "{time:YYYY-MM-DD}.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)

    file_id = logger.add(
        sink=str(log_file),
        level=os.getenv("FILE_LOG_LEVEL", file_level or current_config["file_level"]),
        format=current_config["file_format"],
        rotation=current_config["rotation"],
        retention=current_config["retention"],
        compression=current_config["compression"],
        encoding="utf-8",
        filter=lambda record: record["extra"].get("module") == module_name and "custom_style" not in record["extra"],
        enqueue=True,
    )
    handler_ids.append(file_id)

    # 额外处理器
    if extra_handlers:
        for handler in extra_handlers:
            handler_id = logger.add(**handler)
            handler_ids.append(handler_id)

    # 更新注册表
    _handler_registry[module_name] = handler_ids

    return logger.bind(module=module_name)

