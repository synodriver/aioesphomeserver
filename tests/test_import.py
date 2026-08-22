def test_package_imports():
    import aioesphomeserver

    assert aioesphomeserver.Device is not None
    assert aioesphomeserver.NativeApiServer is not None
    assert aioesphomeserver.CAMERA_IMAGE_CHUNK_SIZE == 1390


def test_entities_are_defined_in_their_domain_modules():
    from aioesphomeserver.alarm_control_panel import AlarmControlPanelEntity
    from aioesphomeserver.button import ButtonEntity
    from aioesphomeserver.camera import CameraEntity
    from aioesphomeserver.cover import CoverEntity
    from aioesphomeserver.date import DateEntity
    from aioesphomeserver.datetime import DateTimeEntity
    from aioesphomeserver.event import EventEntity
    from aioesphomeserver.fan import FanEntity
    from aioesphomeserver.infrared import InfraredEntity
    from aioesphomeserver.lock import LockEntity
    from aioesphomeserver.media_player import MediaPlayerEntity
    from aioesphomeserver.radio_frequency import RadioFrequencyEntity
    from aioesphomeserver.siren import SirenEntity
    from aioesphomeserver.text import TextEntity
    from aioesphomeserver.text_sensor import TextSensorEntity
    from aioesphomeserver.time import TimeEntity
    from aioesphomeserver.update import UpdateEntity
    from aioesphomeserver.valve import ValveEntity
    from aioesphomeserver.water_heater import WaterHeaterEntity

    entities = (
        AlarmControlPanelEntity,
        ButtonEntity,
        CameraEntity,
        CoverEntity,
        DateEntity,
        DateTimeEntity,
        EventEntity,
        FanEntity,
        InfraredEntity,
        LockEntity,
        MediaPlayerEntity,
        RadioFrequencyEntity,
        SirenEntity,
        TextEntity,
        TextSensorEntity,
        TimeEntity,
        UpdateEntity,
        ValveEntity,
        WaterHeaterEntity,
    )
    for entity_type in entities:
        assert entity_type.__module__ == f"aioesphomeserver.{entity_type.DOMAIN}"
