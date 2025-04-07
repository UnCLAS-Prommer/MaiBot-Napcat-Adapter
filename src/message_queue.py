import asyncio

recv_queue = asyncio.Queue()
message_queue = asyncio.Queue()

async def get_response():
    response = await recv_queue.get()
    recv_queue.task_done()
    return response