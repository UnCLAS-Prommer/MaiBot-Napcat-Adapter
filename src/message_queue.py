import queue
import asyncio

recv_queue = queue.Queue()

async def get_response():
    while recv_queue.empty():
        await asyncio.sleep(0.5)
    return recv_queue.get()
