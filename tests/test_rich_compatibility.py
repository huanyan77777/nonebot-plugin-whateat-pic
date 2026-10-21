"""Exercise the real download coroutine with real Rich and mocked HTTP."""
import asyncio
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import httpx
from rich.console import Console
from rich.progress import Progress

from test_fork_regressions import extract


class RichCompatibilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_download_skip_and_failure_progress(self):
        for fail in (False, True):
            with self.subTest(download_failure=fail), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                existing = root / "eat_pic" / "existing.png"
                existing.parent.mkdir()
                existing.write_bytes(b"original")
                requests = []
                output = io.StringIO()
                progress_instances = []

                def respond(request):
                    requests.append(request.url.path)
                    if request.url.path.endswith("download_list.json"):
                        return httpx.Response(200, json={
                            "drink_pic": [{"name": "tea.png"}],
                            "eat_pic": [{"name": "existing.png"}, {"name": "rice.png"}],
                        })
                    return httpx.Response(503 if fail else 200, content=b"test-image")

                client_type = httpx.AsyncClient

                def client():
                    return client_type(transport=httpx.MockTransport(respond))

                def progress_factory(*args, **kwargs):
                    progress = Progress(*args, **kwargs, console=Console(file=output, force_terminal=True, width=100))
                    progress_instances.append(progress)
                    return progress

                progress_factory.get_default_columns = Progress.get_default_columns
                fn = extract("check_on_statup.py", "check_resource", dict(
                    config=SimpleNamespace(whateat_auto_download=True, whatpic_res_path=directory),
                    available_urls=["https://example.test/"], logger=Mock(),
                    httpx=httpx, asyncio=asyncio, json=json, Path=Path, Progress=progress_factory,
                ))
                with patch.object(httpx, "AsyncClient", side_effect=client):
                    await fn()
                self.assertEqual(existing.read_bytes(), b"original")
                self.assertFalse(any(path.endswith("existing.png") for path in requests))
                self.assertEqual(len(requests), 3)
                for relative in ("drink_pic/tea.png", "eat_pic/rice.png"):
                    path = root / relative
                    if fail:
                        self.assertFalse(path.exists())
                    else:
                        self.assertEqual(path.read_bytes(), b"test-image")
                self.assertEqual(progress_instances[0].tasks[0].completed, 3)
                self.assertTrue(progress_instances[0].tasks[0].finished)
                self.assertIn("3/3", output.getvalue())
