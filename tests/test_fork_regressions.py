"""Isolated regressions: no bot startup, real chat traffic or user resources."""
import ast
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import aiofiles
import httpx

ROOT = Path(__file__).resolve().parents[1] / "nonebot_plugin_whateat_pic"


def extract(filename, name, namespace):
    tree = ast.parse((ROOT / filename).read_text(encoding="utf-8"))
    node = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == name)
    node.decorator_list = []
    module = ast.Module(body=[node], type_ignores=[])
    exec(compile(module, str(ROOT / filename), "exec"), namespace)
    return namespace[name]


class RegressionTests(unittest.IsolatedAsyncioTestCase):
    def image(self, **kwargs):
        values = dict(raw=None, raw_bytes=None, path=None, url=None, id=None)
        values.update(kwargs)
        return SimpleNamespace(**values)

    def fetcher(self):
        return extract("matcher.py", "fetch_image_bytes", dict(
            Event=object, Bot=object, Image=object, aiofiles=aiofiles,
            httpx=httpx, logger=Mock()))

    async def test_raw_image(self):
        self.assertEqual(await self.fetcher()(None, None, {}, self.image(raw=True, raw_bytes=b"png")), b"png")

    async def test_local_image(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "image.png"
            path.write_bytes(b"local image")
            self.assertEqual(await self.fetcher()(None, None, {}, self.image(path=path)), b"local image")
            self.assertIsNone(await self.fetcher()(None, None, {}, self.image(path=path.parent / "missing")))

    async def test_onebot_image(self):
        bot = SimpleNamespace(adapter=SimpleNamespace(get_name=lambda: "OneBot V11"),
                              call_api=AsyncMock(return_value={"url": "https://example.test/image"}))
        client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b"remote image")))
        with patch.object(httpx, "AsyncClient", return_value=client):
            self.assertEqual(await self.fetcher()(None, bot, {}, self.image(id="file-id")), b"remote image")
        bot.call_api.assert_awaited_once_with("get_image", file="file-id")

    async def test_resolution_failure(self):
        bot = SimpleNamespace(adapter=SimpleNamespace(get_name=lambda: "OneBot V11"),
                              call_api=AsyncMock(side_effect=RuntimeError("unavailable")))
        self.assertIsNone(await self.fetcher()(None, bot, {}, self.image(id="file-id")))

    async def test_download_disabled_or_empty_sources(self):
        for enabled, urls in [(False, ["https://example.test/"]), (True, [])]:
            fn = extract("check_on_statup.py", "check_resource", dict(
                config=SimpleNamespace(whateat_auto_download=enabled),
                available_urls=urls, logger=Mock(), httpx=httpx))
            with patch.object(httpx, "AsyncClient", side_effect=AssertionError("unexpected network")):
                await fn()

    async def test_upstream_async_send_preserves_persona(self):
        class Message:
            def __init__(self, text):
                self.text, self.images = text, []
            def append(self, image):
                self.images.append(image)
            async def finish(self):
                sent.append(self)

        for kind, phrase in [("eat", "觉得该吃"), ("drink", "想着该喝")]:
            sent = []
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "dish.png"
                path.write_bytes(b"dish")
                fn = extract("matcher.py", f"handle_{kind}_pic", dict(
                    Event=object, TIME=0, USER_DATA={},
                    check_ismax=lambda event, data: (False, data),
                    check_iscd=lambda time: (False, 0, time),
                    random_pic=lambda category: (path, "测试菜品"),
                    BOT_NAME="杜若汀", UniMessage=Message, Text=str,
                    Image=lambda **kwargs: kwargs, aiofiles=aiofiles))
                await fn(None)
            self.assertIn("杜若汀" + phrase, sent[0].text)
            self.assertEqual(sent[0].images, [{"raw": b"dish"}])
