import os
import sys
import tomli
import shutil
from .logger import logger
from typing import Optional


class Config:
    platform: str = "qq"
    nickname: Optional[str] = None
    server_host: str = "localhost"
    server_port: int = 8095
    napcat_heartbeat_interval: int = 30

    def __init__(self):
        self._get_config_path()

    def _get_config_path(self):
        current_file_path = os.path.abspath(__file__)
        src_path = os.path.dirname(current_file_path)
        self.root_path = os.path.join(src_path, "..")
        self.config_path = os.path.join(self.root_path, "config.toml")

    def load_config(self):
        include_configs = ["Nickname", "Napcat_Server", "MaiBot_Server", "Debug"]
        if os.path.exists(self.config_path):
            with open(self.config_path, "rb") as f:
                try:
                    raw_config = tomli.load(f)
                except tomli.TOMLDecodeError as e:
                    logger.critical(f"配置文件bot_config.toml填写有误，请检查第{e.lineno}行第{e.colno}处：{e.msg}")
                    sys.exit(1)
            for key in include_configs:
                if key not in raw_config:
                    logger.error(f"配置文件中缺少必需的字段: '{key}'")
                    sys.exit(1)
            self.nickname = raw_config["Nickname"].get("nickname")
            self.server_host = raw_config["Napcat_Server"].get("host", "localhost")
            self.server_port = raw_config["Napcat_Server"].get("port", 8095)
            self.platform = raw_config["MaiBot_Server"].get("platform_name")
            if not self.platform:
                logger.critical("请在配置文件中指定平台")
                sys.exit(1)
            self.napcat_heartbeat_interval = raw_config["Napcat_Server"].get("heartbeat", 30)
            self.mai_host = raw_config["MaiBot_Server"].get("host", "localhost")
            self.mai_port = raw_config["MaiBot_Server"].get("port", 8000)
            self.debug_level = raw_config["Debug"].get("level", "INFO")
        else:
            logger.error("配置文件不存在！")
            logger.info("正在创建配置文件...")
            shutil.copy(
                os.path.join(self.root_path, "template", "template_config.toml"),
                os.path.join(self.root_path, "config.toml"),
            )
            logger.info("配置文件创建成功，请修改配置文件后重启程序。")
            sys.exit(1)


global_config = Config()
global_config.load_config()
