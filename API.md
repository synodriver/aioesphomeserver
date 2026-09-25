# Native API 与蓝牙代理

项目提供 ESPHome Native API 服务，默认端口为 `6053`，支持明文和固定 PSK 的 Noise 加密。明文协议帧使用 ESPHome 的 protobuf 定义：`0x00` 前导、payload 长度 varuint、消息类型 varuint、protobuf payload。

## 服务端生命周期

```python
from aioesphomeserver import Device, SwitchEntity

device = Device(name="demo", friendly_name="Demo")
device.add_entity(SwitchEntity(name="Relay"))
await device.run(api_port=6053, web_port=8080)
```

`name` 是 ESPHome 节点名，同时用于 mDNS hostname、`HelloResponse.name` 和
`DeviceInfoResponse.name`；建议只使用小写字母、数字、连字符或下划线。界面显示名称应放在
`friendly_name`。如果不需要 HTTP Web Server，可传入 `web_port=None`，避免非必要的端口冲突。

`esphome_version` 可在 `Device(...)` 构造时传入，默认值为 `0.0.1`。该值会同时写入
`DeviceInfoResponse.esphome_version` 和 mDNS TXT `version` 字段，供 Home Assistant 设备信息和诊断使用。

`project_name` 是可选字段；如果设置，必须使用 ESPHome/Home Assistant 兼容的
`vendor.project` 格式，例如 `aioesphomeserver.example`。Home Assistant 在设备注册阶段会把
非空 `project_name` 按点号拆分来推导厂商和型号，缺少点号的值可能导致注册流程中断，表现为设备可连接但实体和蓝牙代理不注册。本库会在
`DeviceInfoResponse` 和 mDNS 中忽略不含点号的 `project_name`，示例也统一使用 dotted 格式。

### Home Assistant 能发现但无法添加

Home Assistant 的 zeroconf 流程先从 `_esphomelib._tcp.local.` 读取 IP、端口、MAC 和节点名；
确认添加后再通过 TCP 连接该端口，等待 `HelloResponse` 和 `DeviceInfoResponse`。因此“可以发现”
只证明 mDNS 可达，并不证明 Native API TCP 可达。请依次检查：

- HA 主机能否连接运行示例的主机 `6053/tcp`；Windows 防火墙需要允许 Python 入站连接；
- 运行日志中是否出现 `Starting on 0.0.0.0:6053`，以及 6053 是否被其他进程占用；
- 节点名是否一致。不要把带空格的显示名称直接当作节点名；
- 示例不需要 Web 功能时使用 `web_port=None`，防止 8080 冲突影响进程启动。

Windows 上可以允许 Python 在专用网络接收入站连接，或用管理员 PowerShell 按实际端口添加规则：

```powershell
New-NetFirewallRule `
  -DisplayName "aioesphomeserver ESPHome API" `
  -Direction Inbound `
  -Profile Private `
  -Protocol TCP `
  -LocalPort 6053 `
  -Action Allow
```

若启用了 Web Server，还需按实际配置放行对应端口（默认 `8080/tcp`）。不要在没有明确网络隔离方案时把这些端口开放到公用网络。mDNS 可发现只代表 UDP 发现链路正常，不能替代从 HA 主机到 `6053/tcp` 的连通性测试。

## Noise 加密

`Device.encryption_key` 接受 base64 编码的 32 字节 ESPHome API 密钥，也接受原始 32 字节 `bytes`：

```python
device = Device(
    name="encrypted-demo",
    friendly_name="Encrypted Demo",
    encryption_key="AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8=",
)
await device.run(api_port=6053, web_port=None)
```

配置密钥后，mDNS 会发布 `api_encryption=Noise_NNpsk0_25519_ChaChaPoly_SHA256`，Native API 只接受使用同一密钥的 Noise 连接；Home Assistant 添加设备时需要填写相同密钥。未配置密钥时继续使用明文协议。

当前实现是启动时固定 PSK，不处理 `NoiseEncryptionSetKeyRequest`，也不把自己声明为可在线配网（`api_encryption_provisionable=false`）。修改密钥后必须同步更新 Home Assistant 中的配置。密钥不应写入日志或提交到公开仓库。

服务端响应 API 版本 `1.18`，支持握手、认证（当前无密码）、设备信息、设备能力、实体枚举、状态订阅、日志订阅、Ping/Pong、断开和已有实体命令。库会响应 `DeviceCapabilitiesRequest`（149）并返回 `DeviceCapabilitiesResponse`（150）；蓝牙、语音、Z-Wave 和串口能力同时写入旧版 `DeviceInfoResponse` 字段，兼容旧客户端。协议基准为 `aioesphomeapi 46.5.0`，此版本已包含官方设备能力 protobuf 类。

Native API 单帧 payload 最大为 `65535` 字节，varuint 最多 4 字节；服务端默认接受最多 6 个并发客户端，并要求明文客户端在 60 秒内发送首个消息。超过限制或发送错误前导的连接会被关闭，入站日志只记录 protobuf 消息类型，不记录参数和二进制 payload。

当前实体覆盖：`BinarySensorEntity`、`SensorEntity`、`TextSensorEntity`、`SwitchEntity`、`LightEntity`、`NumberEntity`、`SelectEntity`、`TextEntity`、`ButtonEntity`、`ClimateEntity`、`CoverEntity`、`FanEntity`、`LockEntity`、`MediaPlayerEntity`、`SirenEntity`、`ValveEntity`、`WaterHeaterEntity`、`AlarmControlPanelEntity`、`DateEntity`、`DateTimeEntity`、`TimeEntity`、`UpdateEntity`、`EventEntity`、`CameraEntity`、`InfraredEntity` 和 `RadioFrequencyEntity`。这些类均提供对应的 ESPHome discovery protobuf；带命令的实体还提供状态更新和异步用户钩子。

### 实体模块

实体实现按 ESPHome domain 放在同名模块中，推荐从对应模块导入：

```python
from aioesphomeserver.camera import CameraEntity
from aioesphomeserver.lock import LockEntity
from aioesphomeserver.sensor import SensorEntity
```

这种布局让协议定义、状态字段和命令处理在同一个 domain 边界内，便于按实体类型维护和扩展；共享的状态发布逻辑位于内部模块 `aioesphomeserver.state_entity`。新版不再提供旧的
`aioesphomeserver.additional_entities` 模块，应用应直接使用各自的 domain 模块。摄像头分片常量
`CAMERA_IMAGE_CHUNK_SIZE` 现在归属 `aioesphomeserver.camera`，并继续从包根导出。

`examples/entity_showcase.py` 提供一个不依赖硬件的完整实体目录示例：同一个 `Device` 注册全部
实体 domain，并通过异步任务周期性推送 Sensor、Binary Sensor、Text Sensor 和 Event 状态。其中
Camera 继承专项示例的 `ExampleCamera`，可实际返回 JPEG 快照并推送定时帧流；Bluetooth Proxy 和
Voice Assistant 等需要独立后端的功能仍分别见对应专项示例。

所有接收 Home Assistant 控制请求的实体都暴露异步 `on_command()`，应用可覆写它执行真实设备操作。Button 还保留语义更明确的 `on_press()`，Camera 保留 `on_request()`，Infrared/RF 保留 `on_transmit()`；它们默认由 `on_command()` 转发，既能统一覆写，也兼容专用钩子。Sensor、Binary Sensor、Text Sensor 和 Event 在 ESPHome 协议中没有 HA 到设备的命令消息，因此不需要 `on_command()`。

## 外部数据和自定义命令

`SensorEntity.set_state()` 可用于定期发布 HTTP、数据库、串口或其他外部数据源的值。`NumberEntity` 和 `SelectEntity` 收到 Home Assistant 命令时会调用异步 `on_command(value)`；应用可继承实体，在钩子中执行外部操作，并在操作成功后调用 `set_state(value)` 将最终状态回推给 Home Assistant。

完整组合示例见 `examples/external_data_entities.py`，其中一个 Device 同时包含定时更新的 Sensor、可设置目标值的 Number 和可选择工作模式的 Select。

## Camera

`CameraEntity` 使用 ESPHome 的 `CameraImageRequest` 和 `CameraImageResponse`。继承实体并覆写
异步 `on_request(single, stream)`：`single=True` 时调用 `send_image(jpeg_bytes)` 返回一张快照，
`stream=True` 时启动应用自己的采集循环并重复调用 `send_image()` 推送 JPEG 帧。`send_image()` 会
自动按 ESPHome 的 1390 字节单包上限分片，非最后一块的 `done` 始终为 `False`，最后一块沿用
传入的 `done`（默认 `True`）。

`examples/camera.py` 提供一个不依赖摄像头硬件的完整示例。它用内置 JPEG 验证协议和生命周期；实际
接入时只需把 `capture_frame()` 替换为返回完整 JPEG 的 CameraX、OpenCV、V4L2 或其他后端调用。
示例还在 `stop()` 中取消视频推送任务，并在每次流请求约 5 秒后自动停止，避免设备关闭或客户端
停止请求后遗留后台任务。

## 用户自定义服务（`api.actions`）

ESPHome YAML 的 `api: actions:` 在本库中对应 `Device.add_service()`。服务会在 Native API
的实体列表中以 `ListEntitiesServicesResponse` 暴露给 Home Assistant，HA 调用时通过
`ExecuteServiceRequest` 执行注册的 Python 函数：

```python
from aioesphomeserver import Device, ServiceArgument, SupportsResponseType

def set_scene(scene: str, brightness: float) -> None:
    print(scene, brightness)

async def notify(message: str) -> None:
    await send_notification(message)

device.add_service(
    "set_scene",
    set_scene,
    description="Select a scene and set its brightness.",
    arguments={
        "scene": ServiceArgument(str, "Scene name", "evening"),
        "brightness": ServiceArgument(float, "Brightness from 0 to 1", "0.6"),
    },
)
device.add_service("notify", notify, arguments={"message": str})
```

`arguments` 的声明顺序决定回调的位置参数顺序。支持 `bool`、`int`、`float`、`str` 和
`list[bool]`、`list[int]`、`list[float]`、`list[str]`；也可以直接使用 `ServiceArgType`
枚举。`description` 写入 `ListEntitiesServicesResponse.description`；参数使用
`ServiceArgument(type, description, example)` 时，后两个字符串写入
`ListEntitiesServicesArgument.description` 和 `.example`。只传类型的旧用法继续有效，
对应元数据为空字符串。回调可以是同步函数或异步函数，异步函数会被等待；执行期间 Native API 仍可处理
Ping 和其他请求。参数数量不匹配或未知服务 key 会被忽略。

默认服务不返回结果，对应 ESPHome 的 `supports_response: none`。需要返回数据时使用
`SupportsResponseType.OPTIONAL`、`ONLY` 或 `STATUS`：OPTIONAL 仅当 HA 请求响应时返回，ONLY
始终返回，STATUS 只返回成功/失败状态。回调返回值必须是 JSON object（Python `dict`/`Mapping`）；
返回 `bytes` 时内容也必须能解析为 JSON object。列表、字符串、数字、非法 JSON bytes 和其他非对象
值会返回失败响应，因为 Home Assistant 会按 object 解析服务结果。抛出异常或响应校验失败会返回失败
和错误文本，不会关闭连接。例如：

```python
async def echo(value: str) -> dict[str, str]:
    return {"echo": value}

device.add_service(
    "echo",
    echo,
    arguments={"value": str},
    supports_response=SupportsResponseType.OPTIONAL,
)
```

完整示例见 `examples/custom_services.py`，官方客户端调用方式是
`await client.execute_service(service, {"value": "hello"}, return_response=True)`。

## 调用 Home Assistant 服务

ESPHome `api:` 下的 `homeassistant_services: true` 对应本库的
`Device.call_homeassistant_service()` 和 `Device.fire_homeassistant_event()`。Home Assistant
客户端连接后需要先发送 `SubscribeHomeassistantServicesRequest`；官方客户端可调用
`client.subscribe_service_calls(callback)` 完成订阅。订阅后，设备可以调用 HASS 服务或触发事件：

```python
await device.call_homeassistant_service(
    "light.turn_on",
    data={"entity_id": "light.living_room", "brightness": "127"},
    data_template={"transition": "{{ transition_seconds }}"},
    variables={"transition_seconds": "2"},
)

await device.fire_homeassistant_event(
    "esphome.aioesphomeserver_button_pressed",
    data={"source": "front_button"},
)
```

Home Assistant 只接受 `esphome.*` 域下的设备事件；其他域名会被 ESPHome 集成记录为错误并丢弃。
因此自定义事件名应使用 `esphome.` 前缀，例如 `esphome.aioesphomeserver_button_pressed`。

`data`、`data_template` 和 `variables` 对应 ESPHome Native API 的三个
`HomeassistantServiceMap` 列表，键和值都必须是字符串。一次调用会发送给所有已订阅的客户端；没有
订阅者时，无响应调用会记录警告并丢弃，等待响应的调用会抛出 `RuntimeError`。

需要 Home Assistant 返回结果时设置 `wait_for_response=True`。方法会等待
`HomeassistantActionResponse` 并返回官方 protobuf 对象；`response_template` 会原样发送给 Home
Assistant，等待默认超时为 30 秒，可通过 `timeout` 调整：

```python
response = await device.call_homeassistant_service(
    "conversation.process",
    data={"text": "What time is it?"},
    wait_for_response=True,
    response_template="{{ response }}",
)
if response is not None and response.success:
    print(response.response_data)
```

完整示例见 `examples/homeassistant_actions.py`。它使用 Button 回调调用
`persistent_notification.create`，并定时触发一个 Home Assistant 事件。该能力是设备主动向 HASS
发送请求，与 `Device.add_service()` 注册由 HASS 调用的设备服务方向相反。

## 蓝牙代理

`BluetoothProxy` 只定义异步后端接口，不直接依赖蓝牙库。应用继承它并实现扫描、连接、GATT 读写及通知方法；基类负责把后端结果打包成 ESPHome protobuf。

```python
class MyProxy(BluetoothProxy):
    async def connect(self, address, address_type, use_cache): ...
    async def get_services(self, address): ...
    async def read_characteristic(self, address, handle): ...
    async def write_characteristic(self, address, handle, data, response): ...
    async def set_notify(self, address, handle, enable, callback): ...
```

覆盖接口包括：LE 广播订阅、扫描模式、连接/断开、配对/取消配对、清除缓存、服务发现、特征和描述符读写、通知、连接参数和连接槽状态。发生后端错误时抛出 `BluetoothProxyError(error=...)`，协议会返回 `BluetoothGATTErrorResponse` 或对应操作的错误字段。

`examples/bleak_proxy.py` 是可替换后端的 Bleak 实现示例。Home Assistant 只有在 `DeviceInfoResponse` 中看到非零 `bluetooth_proxy_feature_flags` 后才会注册远程扫描器；随后会订阅连接槽、scanner state 和 BLE 广播。示例声明 `FEATURE_STATE_AND_MODE`，因此 HA 蓝牙页面会显示扫描模式选项。Linux 下示例为被动扫描传递与 Home Assistant 相同的 BlueZ `or_patterns`；如果目标系统不支持 Advertisement Monitor，则自动回退为主动扫描，并把实际模式报告给 HA。

Bleak 回调提供的是已经解析并合并的名称、UUID、service data 和 manufacturer data，不提供 BlueZ 收到的原始 HCI ADV/SCAN_RSP 字节。当前 ESPHome 蓝牙代理始终声明 `RAW_ADVERTISEMENTS`，且新协议路径使用 `BluetoothLERawAdvertisementsResponse`（消息 93），因此 Bleak 示例也声明该能力；当后端未提供 `BluetoothAdvertisement.raw_data` 时，库会从解析字段重构一个合法 ADV payload。能像 Android `ScanRecord.bytes` 或 ESPHome tracker 那样取得真实广播字节的后端，应优先把真实字节写入 `raw_data`。Ava 仓库也明确说明蓝牙代理实现仅存在于 release build、没有开源；其公开源码只能核对 protobuf 和消息 ID，不能作为可移植的 Android 蓝牙后端。

在 Orange Pi、树莓派等 Linux 主机上，若要真正使用被动扫描，需要 BlueZ >= 5.56、启动 `bluetoothd --experimental`，以及 Linux kernel >= 5.10。没有这些条件时保持主动扫描即可；不要只修改 feature flags 伪装成支持被动扫描。示例默认使用 `hci0`，并从 `/sys/class/bluetooth/hci0/address` 读取真实适配器 MAC；读取不到时才基于主机标识和 adapter 名派生稳定且唯一的本地管理地址，ESPHome 设备 MAC 也使用独立标签派生，避免多台机器共用示例常量。库会把蓝牙 MAC 规范为大写，非法格式会在启动时直接报错，避免 HA 以两个不同的 scanner source 建立或查找适配器。

复制示例部署多个代理时，每个代理的设备 `mac_address` 和 `bluetooth_mac_address` 都必须唯一且保持不变。修改已有代理的蓝牙 MAC 后，重新加载 ESPHome 集成；HA 会按 ESPHome 配置条目迁移对应的蓝牙适配器条目。这个示例直接使用本机真实蓝牙适配器，并非无硬件模拟器；没有可用适配器时只能添加 ESPHome 设备，不能提供扫描网关。ESPHome wire protocol 使用 48 位 BLE MAC，macOS Bleak 通常只提供 UUID，因此此示例当前不支持 macOS 作为代理后端。

## Voice Assistant

`VoiceAssistant` 实现 ESPHome 设备侧协议。Home Assistant 先发送 `SubscribeVoiceAssistantRequest`；设备随后以 `VoiceAssistantRequest` 发起 Assist 会话，使用 `VoiceAssistantAudio` 上传 API 音频。Home Assistant 使用同一音频消息回传扬声器数据，并通过事件、计时器、播报和配置消息控制设备。

| 方向 | protobuf | 用途 |
| --- | --- | --- |
| HA -> 设备 | `SubscribeVoiceAssistantRequest`（89） | 独占订阅与 API 音频模式 |
| 设备 -> HA，HA 应答 | `VoiceAssistantRequest`（90）/ `VoiceAssistantResponse`（91） | 启动或停止 Assist pipeline；应答选择 API（端口 0）或 UDP 音频 |
| 双向 | `VoiceAssistantAudio`（106） | 麦克风/扬声器 PCM 流，支持第二声道和结束标记 |
| HA -> 设备 | `VoiceAssistantEventResponse`（92） | STT、Intent、TTS 和错误事件 |
| HA -> 设备 | `VoiceAssistantTimerEventResponse`（115） | 计时器生命周期 |
| HA -> 设备，设备应答 | `VoiceAssistantAnnounceRequest`（119）/ `VoiceAssistantAnnounceFinished`（120） | 媒体播报 |
| HA -> 设备，设备应答 | `VoiceAssistantConfigurationRequest`（121）/ `VoiceAssistantConfigurationResponse`（122） | 唤醒词能力与当前配置 |
| HA -> 设备 | `VoiceAssistantSetConfiguration`（123） | 激活唤醒词 |

```python
from aioesphomeserver import Device, VoiceAssistant

class MyVoiceAssistant(VoiceAssistant):
    async def on_audio(self, data, data2, end):
        await my_speaker.write_pcm(data)

voice = MyVoiceAssistant(speaker=True)
device = Device(name="Voice device", voice_assistant=voice)

# 在应用的麦克风任务中：
await voice.start(use_vad=True)
await voice.send_audio(pcm_chunk)
await voice.finish_audio()
```

`start()` 只有收到无错误的 `VoiceAssistantResponse` 后才允许 `send_audio()`。空音频块会被拒绝；启用 `multi_channel_audio=True` 后，每个音频消息必须同时包含两个非空声道，与 ESPHome 官方的双声道发送规则一致。`is_streaming_audio` 表示麦克风流是否仍可发送，`is_pipeline_active` 则会持续到 `RUN_END` 或显式 `stop()`。

只做播报、不采集麦克风的设备可使用 `VoiceAssistant(output_only=True)`。此模式与 Linux Voice Assistant 一样声明 `API_AUDIO | ANNOUNCE`，但不声明完整 `VOICE_ASSISTANT` 能力，也不允许调用 `start()`。`on_announcement()` 可等待实际播放结束再返回；它在独立任务中运行，不会在播放期间阻塞 Native API 心跳和其他消息。

完整后端接入示例见 `examples/voice_assistant.py`。库不指定音频采集、播放、媒体 URL 下载或唤醒词引擎，应用在对应的异步钩子中接入自己的实现。

## Serial Proxy 与 Z-Wave Proxy

`Device(serial_proxies=[...], zwave_proxy=...)` 在 `DeviceInfoResponse` 和 `DeviceCapabilitiesResponse` 中发布对应能力。串口端口按列表顺序编号，从 0 开始。两个代理都由应用子类接入硬件，本库负责 Native API 消息编解码、独占订阅、权限检查、操作回执及断线清理。`aioesphomeapi>=46.5.0` 的官方客户端可直接使用 `serial_proxy_*` 和 `zwave_proxy_*` 方法。

```python
from aioesphomeapi.model import SerialProxyStatus
from aioesphomeserver import Device, SerialProxy, ZWaveProxy

class MySerialPort(SerialProxy):
    async def on_configure(self, request):
        await uart.configure(request.baudrate, request.parity, request.stop_bits)

    async def on_write(self, data: bytes):
        await uart.write(data)

    async def on_flush(self):
        await uart.drain()
        return SerialProxyStatus.OK

    # 从 UART 读到数据时调用 await self.publish_data(data)

class MyZWaveController(ZWaveProxy):
    async def on_frame(self, data: bytes):
        await controller.write(data)

    # 从控制器读到帧时调用 await self.publish_frame(frame)

device = Device(
    name="gateway",
    serial_proxies=[MySerialPort("UART 1")],
    zwave_proxy=MyZWaveController(home_id=0x12345678),
)
```

串口后端还可覆盖 `on_subscribe()`、`on_unsubscribe()`、`on_set_modem_pins()`、`on_get_modem_pins()`、`on_set_mode()`；不支持的操作默认返回 `NOT_SUPPORTED`。主动调用 `publish_identity()` 会更新已订阅客户端的串口身份。Z-Wave 后端调用 `publish_home_id()` 报告 Home ID 变化。未订阅的客户端不能写串口或 Z-Wave 帧，也不能配置串口；第二个订阅者收到 `PORT_IN_USE` 或 `IN_USE`。红外/RF 发送命令结束后，服务端会向发起方发送 `InfraredRFTransmitCompleteResponse`，使新版客户端能按实际完成时间发送下一帧。

真实串口接入见 `examples/serialx_proxy.py`，Z-Wave Serial API 控制器接入见
`examples/zwave_serialx_proxy.py`。两者都使用 `serialx` 异步端口，需要 Python 3.12 环境和本机串口设备；本库将其列为可选的 `serial` 依赖组。示例命令：

```powershell
D:\conda\envs\hass\python.exe -m examples.serialx_proxy COM3
D:\conda\envs\hass\python.exe -m examples.zwave_serialx_proxy COM4
```

Linux 上将 `COM3`、`COM4` 替换为实际设备路径。串口示例收到客户端配置后重开串口以应用波特率、校验位、停止位、数据位和硬件流控；Z-Wave 示例按 Serial API 帧边界转发，并查询 Home ID。无硬件测试使用模拟 `serialx` 端口，不验证目标串口或控制器的实际行为。
