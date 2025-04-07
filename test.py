import asyncio
import queue

message = queue.Queue()

async def test():
    await asyncio.sleep(5)
    message.put("123")

async def test2():
    while message.empty():
        await asyncio.sleep(0.5)
        print("等回复")
    print(message.get())

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(asyncio.gather(test(), test2()))