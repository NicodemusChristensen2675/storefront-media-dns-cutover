from dataclasses import replace

import pytest

from media_cutover import CutoverRequest, change_media_target


class RecordingDns:
    def __init__(self):
        self.writes = []

    def zone_id(self, domain):
        assert domain == "shop.example"
        return "zone-42"

    def set_target(self, zone_id, hostname, target, ttl):
        self.writes.append((zone_id, hostname, target, ttl))


def test_delivery_gate_and_rollback():
    client = RecordingDns()
    ready = CutoverRequest("shop.example", "media.shop.example", "new.cdn.example",
                           "old.cdn.example", True, True, True, 60)
    with pytest.raises(ValueError, match="creator delivery"):
        change_media_target(client, replace(ready, creator_delivery_ready=False))
    assert client.writes == []

    assert change_media_target(client, ready)["target"] == "new.cdn.example"
    assert change_media_target(client, ready, rollback=True)["target"] == "old.cdn.example"
    assert client.writes == [
        ("zone-42", "media.shop.example", "new.cdn.example", 60),
        ("zone-42", "media.shop.example", "old.cdn.example", 60),
    ]
