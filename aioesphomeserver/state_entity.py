from __future__ import annotations

import json

from aioesphomeserver.basic_entity import BasicEntity


class _StateEntity(BasicEntity):
    async def _publish_state(self) -> None:
        await self.notify_state_change()

    async def state_json(self) -> str:
        return json.dumps(
            {"id": self.json_id, "name": self.name, "state": await self.get_state()}
        )
