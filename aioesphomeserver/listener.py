from typing import Any

from .basic_entity import BasicEntity


class EntityListener(BasicEntity):
    def __init__(self, *args: Any, entity_id: str | None = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.entity_id = entity_id

    async def can_handle(self, key: str, message: object) -> bool:
        if key == "log":
            return False

        if self.device is None or self.entity_id is None:
            return False
        entity = self.device.get_entity(self.entity_id)
        return entity is not None and getattr(message, "key", None) == entity.key
