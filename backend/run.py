import asyncio
import selectors
import sys

import uvicorn


async def serve():
    config = uvicorn.Config(
        "app.main:app",
        host="127.0.0.1",
        port=8001,
        reload=False,
        loop="asyncio",
    )
    server = uvicorn.Server(config)
    await server.serve()


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.run(
            serve(),
            loop_factory=lambda: asyncio.SelectorEventLoop(
                selectors.SelectSelector()
            ),
        )
    else:
        asyncio.run(serve())
