from maim_message import Router, RouteConfig, TargetConfig
from .config import global_config
from .logger import logger
from .send_handler import send_handler

route_config = RouteConfig(
    route_config={
        global_config.platform: TargetConfig(
            url=f"ws://{global_config.mai_host}:{global_config.mai_port}/ws",
            token=None,
        )
    }
)
router = Router(route_config)


async def mmc_start_com():
    logger.info("正在连接MaiBot")
    router.register_class_handler(send_handler.handle_message)
    await router.run()


async def mmc_stop_com():
    await router.stop()
