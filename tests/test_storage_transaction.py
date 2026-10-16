"""SQLite transaction atomicity and cancellation serialization."""

import asyncio
import threading

import pytest


async def test_transaction_commit_and_rollback(tmp_path):
    from src.storage.sqlite_manager import SQLiteManager
    manager = SQLiteManager(tmp_path / "atomic.sqlite")
    manager.ensure_schema(["CREATE TABLE item(value INTEGER)"])
    try:
        def commit(conn):
            conn.execute("INSERT INTO item VALUES(1)")
            conn.execute("INSERT INTO item VALUES(2)")
            return "done"
        assert await manager.transaction(commit) == "done"
        def rollback(conn):
            conn.execute("INSERT INTO item VALUES(3)")
            raise ValueError("rollback")
        with pytest.raises(ValueError, match="rollback"):
            await manager.transaction(rollback)
        assert [r[0] for r in await manager.fetch_all("SELECT value FROM item")] == [1, 2]
    finally:
        await manager.close()


@pytest.mark.parametrize("worker_fails", [False, True])
async def test_repeated_cancellation_retains_connection_until_worker_finishes(tmp_path, worker_fails):
    from src.storage.sqlite_manager import SQLiteManager
    manager = SQLiteManager(tmp_path / "cancel.sqlite")
    manager.ensure_schema(["CREATE TABLE item(value INTEGER)"])
    loop = asyncio.get_running_loop()
    started = asyncio.Event()
    release = threading.Event()
    def operation(conn):
        conn.execute("INSERT INTO item VALUES(1)")
        loop.call_soon_threadsafe(started.set)
        if not release.wait(5):
            raise TimeoutError("test release was not signaled")
        if worker_fails:
            raise ValueError("worker failed")
    task = asyncio.create_task(manager.transaction(operation))
    await asyncio.wait_for(started.wait(), 2)
    try:
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        reader = asyncio.create_task(manager.fetch_all("SELECT value FROM item"))
        await asyncio.sleep(0)
        assert not reader.done()
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        rows = await asyncio.wait_for(reader, 2)
        assert [r[0] for r in rows] == ([] if worker_fails else [1])
    finally:
        release.set()
        await manager.close()
