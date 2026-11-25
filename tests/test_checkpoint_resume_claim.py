import asyncio
from types import SimpleNamespace

import pytest
from starlette.requests import Request

from ethan.interface.routers import resume


@pytest.mark.parametrize("failure", [RuntimeError("blob unavailable"), asyncio.CancelledError()])
def test_resume_preparation_failure_releases_claim(monkeypatch, failure):
    class Store:
        status = "interrupted"
        async def load(self, sid):
            return SimpleNamespace(messages=[SimpleNamespace(id=7)], mode="")
        async def update_message_status(self, row, status, expected=None):
            assert row == 7
            if expected and self.status != expected:
                return False
            self.status = status
            return True
        async def load_intermediate_blob(self, row):
            raise failure
    store = Store()
    async def get_store():
        return store
    monkeypatch.setattr(resume, "get_session_store", get_store)
    async def run():
        request = Request({"type": "http", "client": ("127.0.0.1", 1), "headers": []})
        with pytest.raises(type(failure)):
            await resume.resume_from_message("s", 7, request, model=None, user_id="u")
        assert store.status == "interrupted"
    asyncio.run(run())
