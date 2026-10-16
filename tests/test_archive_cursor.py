"""Archive cursor boundaries and batched lookup."""

import pytest


async def test_archive_cursor_reads_and_lookup_batches(app):
    from src.plugins.message_archive import db as archive
    from src.storage import get_db
    db = get_db()
    def seed(conn):
        conn.executemany("""INSERT INTO message_archive
            (session_type,session_id,message_id,event_time,self_id,user_id,sender_name,message_cq,plain_text)
            VALUES(?,?,?,?,?,?,?,?,?)""", [
                ("group", "g", i, i, "bot", f"u{i % 2}", "name", "", "" if i == 2 else str(i))
                for i in range(1, 1102)
            ] + [("private", "g", 5000, 1, "bot", "u", "name", "", "private")])
        return [row[0] for row in conn.execute("SELECT id FROM message_archive WHERE session_type='group' ORDER BY id")]
    ids = await db.transaction(seed)
    assert await archive.get_group_max_id("g") == ids[-1]
    assert await archive.get_group_max_id("missing") == 0
    assert await archive.get_group_first_id_since("g", 3) == ids[2]
    assert await archive.get_group_first_id_since("g", 5000) is None
    rows = await archive.fetch_group_texts_after_id("g", ids[0], until_id=ids[3], limit=1)
    assert [r.id for r in rows] == [ids[2]]
    assert rows[0].self_id == "bot"
    assert rows[0].user_id == "u1"
    assert await archive.fetch_group_texts_after_id("g", ids[3], until_id=ids[3], limit=10) == []
    with pytest.raises(ValueError):
        await archive.fetch_group_texts_after_id("g", 0, limit=0)
    found = await archive.fetch_texts_by_ids([*ids, ids[0], -1])
    assert set(found) == set(ids)
    assert found[ids[1]].plain_text == ""
    assert await archive.fetch_texts_by_ids([]) == {}
