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

## 设备主动连接 outgoing_connection

`OutgoingConnection` 对应 ESPHome 的 `api.outgoing_connection`：设备主动连接 HA，随后仍作为
Noise responder 和 Native API 设备端处理消息。实体、服务、状态订阅、语音和各代理复用原来的连接实现。

```python
from aioesphomeserver import Device, OutgoingConnection, SwitchEntity

device = Device(
    name="outgoing-demo", mac_address="02:00:00:00:10:54",
    encryption_key="<HA 中该设备已有的 Noise 密钥>",
    outgoing_connection=OutgoingConnection(host="192.168.1.10", port=6054, delay=60),
)
device.add_entity(SwitchEntity(name="Relay"))
await device.run(api_port=6053, web_port=None)
```

| 配置 | 默认值 | 含义 |
| --- | --- | --- |
| `host` | `None` | 固定 IPv4/IPv6 地址；省略时从最后一个经 Noise 验证、声明回连目标的客户端学习 |
| `port` | `6054` | HA 的监听端口，固定地址和学习地址均使用此端口 |
| `delay` | `60.0` | 启动或最后一个回连目标断开后的等待秒数，允许 `0` |

必须配置非全零的 32 字节 `encryption_key`，否则 `Device(...)` 立即报错。`host` 接受 IP 字面量，
不接受域名；Python 实现也允许带 scope ID 的 IPv6 地址，学习到的链路本地 IPv6 会保留接口编号。
`has_deep_sleep=True` 时对齐 ESPHome，启动立即尝试，正常断线后等待 5 秒再拨号。
连接失败或握手失败使用 5 至 300 秒指数退避并附加 ±20% 随机抖动，TCP 连接超时 10 秒。

HA 必须支持该功能并监听对应端口，而且已有该设备的 MAC 与密钥配置。主动连接不能代替首次添加设备。
省略 `host` 时，必须先让 HA 成功连入一次：HA 的 `HelloRequest.outgoing_connection_target=True`
仅在验证密钥后被接受。学习的是远端 IP，绝不使用其临时源端口。固定 `host` 不会被学习结果覆盖。
存在任意已声明目标的连接时暂停拨号；已建立的主动连接即使没有收到目标标志，也不会触发重复拨号。
经密钥验证且声明回连目标的入站连接会取消尚未完成的拨号，移交前重新检查连接数、目标连接和密钥。

能力字段 `DeviceInfoResponse.api_outgoing_connection_supported` 随配置自动设置。
保留原有 `Device(api_outgoing_connection_supported=True)` 参数，等价于无固定地址的
`outgoing_connection=OutgoingConnection()`，同样需要有效密钥。
默认不启用主动连接；未启用时忽略 Hello 中的回连声明，正常返回 HelloResponse，兼容新版 HA。
旧版客户端无需发送这个标志，也能照常访问所有实体。

`NativeApiServer.outgoing_host` 返回固定地址或已学习地址。学习地址只在当前服务实例中保存，
同一个实例 `stop()` / `run()` 后仍保留；跨进程持久化由应用保存并在下次构造配置时传回 `host`。
本地 API 监听仍启动，入站和主动连接共享 `max_connections`、加密和消息处理，不增加依赖。
`stop()`、取消 `run()` 都会取消等待/拨号并释放会话。
单条主动会话的异常或后端内部任务取消不会停止入站监听或永久结束拨号循环；
后端断线清理按原顺序执行，一个后端失败后仍尝试其余后端的清理。
停止、重启或取消 `run()` 在断线清理期间产生的取消会延后到其余后端清理完成后传播，
保留最初的取消异常，避免串口或 Z-Wave 残留旧 owner。后端内部再次取消不会覆盖已有的连接取消。
拨号完成与取消同时发生时，也会关闭未移交的连接并取回关闭结果。
可运行示例见 [examples/outgoing_connection.py](examples/outgoing_connection.py)，上游对照与测试见
[AUDIT_OUTGOING_CONNECTION.md](AUDIT_OUTGOING_CONNECTION.md)。

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

当前实现是启动时固定 PSK；收到 `NoiseEncryptionSetKeyRequest` 会明确返回 `success=false`，并声明 `api_encryption_provisionable=false`。修改密钥后必须同步更新 Home Assistant 中的配置。密钥不应写入日志或提交到公开仓库。

服务端响应 API 版本 `1.19`，支持握手、认证（当前无密码）、设备信息、设备能力、实体枚举、状态订阅、日志订阅、Ping/Pong、断开和已有实体命令。库会响应 `DeviceCapabilitiesRequest`（149）并返回 `DeviceCapabilitiesResponse`（150）；蓝牙、语音、Z-Wave 和串口能力同时写入旧版 `DeviceInfoResponse` 字段，兼容旧客户端。协议基准为 Python 3.12 环境的 `aioesphomeapi 46.28.0`。

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

### 灯光颜色模式

`LightEntity.color_modes` 使用 `aioesphomeapi.ColorMode`，例如：

```python
from aioesphomeapi import ColorMode
from aioesphomeserver import LightEntity

light = LightEntity(
    name="Desk light",
    color_modes=(ColorMode.RGB, ColorMode.COLOR_TEMPERATURE),
)
```

序列至少包含一个模式。旧版 `LightColorCapability` 表示单项能力位，不应直接写入
`supported_color_modes`；现在会明确拒绝这类枚举，包括与 `ColorMode` 数值重叠的成员。
已有调用方应将能力组合改为对应的模式，例如 RGBW 使用 `ColorMode.RGB_WHITE`，
仅调光使用 `ColorMode.BRIGHTNESS`。默认模式为 `ColorMode.ON_OFF`。

### Web Server 关闭

`WebServer` 向每个 `/events` 连接独立推送状态、日志和空闲心跳。没有订阅者时不会积压事件。
调用 `await web_server.stop()` 后还应等待 `run()` 任务退出；停止或取消该任务会结束活跃的
SSE 连接并清理 HTTP runner。设备重启服务时可再次调用同一实例的 `run()`。

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

普通 `start()` 在收到无错误的 `VoiceAssistantResponse` 后才允许 `send_audio()`；协商了唤醒词音频且提供检测元数据时，可在请求发出后立即发送缓冲音频，见下文。空音频块会被拒绝；启用 `multi_channel_audio=True` 后，每个音频消息必须同时包含两个非空声道，与 ESPHome 官方的双声道发送规则一致。`is_streaming_audio` 表示麦克风流是否仍可发送，`is_pipeline_active` 则会持续到 `RUN_END`、唤醒词拒绝或显式 `stop()`。

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

订阅过程开始前会预占串口。`on_subscribe()` 失败或被取消时，库会调用 `on_unsubscribe()`
清理可能已打开的后端，再释放 owner；因此关闭钩子应能处理端口尚未完全打开的情况。

真实串口接入见 `examples/serialx_proxy.py`，Z-Wave Serial API 控制器接入见
`examples/zwave_serialx_proxy.py`。两者都使用 `serialx` 异步端口，需要 Python 3.12 环境和本机串口设备；本库将其列为可选的 `serial` 依赖组。示例命令：

```powershell
D:\conda\envs\hass\python.exe -m examples.serialx_proxy COM3
D:\conda\envs\hass\python.exe -m examples.zwave_serialx_proxy COM4
```

Linux 上将 `COM3`、`COM4` 替换为实际设备路径。串口示例收到客户端配置后重开串口以应用波特率、校验位、停止位、数据位和硬件流控；Z-Wave 示例按 Serial API 帧边界转发，并查询 Home ID。无硬件测试使用模拟 `serialx` 端口，不验证目标串口或控制器的实际行为。

## 46.6.0 协议字段

所有实体发现消息可通过 `device_id` 关联 `Device(devices=[DeviceInfo(...)], areas=[AreaInfo(...)])` 中的子设备和区域。`Device(area=...)` 设置主区域；仅未设置 `area` 时才以 `suggested_area` 构造区域信息。实体可设置 `disabled_by_default`；Switch、Climate、Water Heater 可设置 `missing_state`。Climate 支持自定义风速和预设、温度单位及功能标志；Light 可设置 `min_mireds`、`max_mireds`。

`await device.subscribe_homeassistant_state("sensor.example", attribute="", once=False)` 注册 Home Assistant 状态订阅。注册可早于客户端连接，后续客户端订阅时仍会收到请求。响应作为 `homeassistant_state` 事件发送给设备实体，内容为完整的 `HomeAssistantStateResponse`；`once=True` 在收到首个匹配响应后移除。`await device.request_time()` 向已连接客户端发送 `GetTimeRequest`，收到的完整 `GetTimeResponse`（包括 `parsed_timezone` 和 DST 规则）作为 `time_response` 事件传给实体。示例见 `examples/homeassistant_state_time.py`。

`CameraImageRequest` 是不带实体 key 的全局请求，Camera 实体通过 `on_request(single, stream)` 响应。旧版 Cover 开/关/停命令仍可使用，现代位置字段优先。设备主动连接见上文 `outgoing_connection`；在线 Noise 配网尚未实现。当前 46.28.0 协议共 191 个消息类型、913 个字段，全部消息及字段的引用入口见 [协议清单](tools/proto_46_28_inventory.md)，本轮变化及验证见 [AUDIT_46_28.md](AUDIT_46_28.md)；46.23.0 的升级历史见 [AUDIT_46_23.md](AUDIT_46_23.md)。

## 46.23.0 新能力

### 设备向导

`Device(wizard=OnboardingWizard(pages))` 启用 `wizard.configured`，并响应
`DeviceWizardRequest`（156）/`DeviceWizardResponse`（157）。`pages` 使用官方模型
`WizardPage`、`WizardEntityField`、`WizardInputField`、`WizardEntityFilter`，支持标题、说明、
本机实体、子设备 ID、单选/多选输入和实体过滤器；翻译占位符原样发送。
向导编码为版本 1 JSON 的单个 zstd frame，构造时检查客户端 1 MiB 解压限制；完整 protobuf
响应最多 65515 字节，为 Noise 元数据和认证标签预留 20 字节，明文连接使用同一上限。

```python
from aioesphomeserver import OnboardingWizard, WizardPage

key = OnboardingWizard.input_key("selected_calendars")
wizard = OnboardingWizard([WizardPage.from_dict({
    "title": "选择日历",
    "inputs": [{"key": key, "multiple": True, "max_length": 1023,
                "entity_filters": [{"domain": ["calendar"]}]}],
})])
device = Device(name="wizard-demo", wizard=wizard)
```

`WizardInputSetRequest`（158）的 key 是输入 ESPHome id 的 FNV-1 hash，与实体发现 key 不同。
库忽略未知 key 和非法输入；每个实体 ID 要包含 `.`，UTF-8 长度不超过 255 字节。
多选使用逗号分隔，去除每个 ID 两侧空白，按规范化后的字节长度检查 `max_length`（默认 255，
上限 4095），任一项为空或非法则忽略整个请求。服务端不校验 HA 实体是否存在或是否满足 UI 过滤器。

选择值可通过只读快照 `wizard.selections` 获取，只存 RAM，不做持久化；客户端应在每次重连后、
订阅 HA 状态前重发。继承并覆写 `async on_input(key, entity_ids: tuple[str, ...])` 接入应用，
仅在规范化后的选择变化时调用，回调成功后才记录选择；失败或取消后可重试同一选择。
同一输入 key 的回调互斥执行。连接内向导输入、配对令牌、崩溃报告请求及随后到达的 HA 状态订阅
按接收顺序在后台处理，慢回调不会阻塞 Ping；断开时取消未完成回调并丢弃排队请求。
如果连接仍在运行而后端等待的内部任务被取消，服务端会关闭该连接并清理队列，
客户端重连后应重发配置，避免后续订阅使用未完成的配置。
最多允许 64 个待处理请求，超限断开连接。默认是独立输入存储；HA platform 的状态订阅与旧绑定的替换
由应用回调负责，不会仅因配置了过滤器就自动创建 HA 实体订阅。

### Sendspin 配对令牌

`Device(sendspin=SendspinProvider(...))` 发布 `sendspin.feature_flags` 和 `client_id`。
`client_id` 为 Sendspin 静态公钥的 43 字符 base64url 标识，后端未启动时可为空。
默认声明 `SendspinFeature.PAIRING_TOKEN`；继承并覆写
`async on_pairing_token() -> aioesphomeapi.model.SendspinPairingTokenResponse`：

```python
from aioesphomeapi.model import SendspinPairingTokenResponse, SendspinPairingTokenStatus
from aioesphomeserver import SendspinProvider

class MySendspin(SendspinProvider):
    async def on_pairing_token(self) -> SendspinPairingTokenResponse:
        return SendspinPairingTokenResponse.from_dict({
            "status": SendspinPairingTokenStatus.NOT_READY,
        })
```

库处理请求（159）与响应（160），支持 `NOT_READY`、`OK`、`ENCRYPTION_REQUIRED`、
`DISABLED`、`FAILED` 全部状态。仅设备已配置 PSK 且当前连接实际使用 Noise 时才调用后端；
明文连接返回 `ENCRYPTION_REQUIRED`。仅 `OK` 状态携带 token，其余状态强制清空；后端异常返回
`FAILED`，不记录异常文本，防止异常中包含令牌。令牌是长期秘密，应用也不要打印或记录。
基类默认 `NOT_READY`；本库提供协议后端接口，不包含 Sendspin 音频客户端实现。

### YAML 导出

```python
from aioesphomeserver import StoredYaml

device = Device(
    name="yaml-demo",
    encryption_key="AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8=",
    stored_yaml=StoredYaml({
        "device.yaml": "esphome:\n  name: yaml-demo\n",
        "packages/sensors.yaml": "sensor: []\n",
    }),
)
```

`StoredYaml(files, allow_unencrypted=False, chunk_size=1024)` 显式接收相对路径到文本或 bytes 的映射。
只导出给定文件，不扫描磁盘，也不自动脱敏；请自行筛选内容。路径禁止绝对路径和 `..`。
默认要求 `Device.encryption_key`；确有需要可显式传 `allow_unencrypted=True`。

`store_yaml.supported` 为真时响应 `GetYamlRequest`（161）。文件按 EHY1 envelope 编码后 zstd
压缩，通过 `GetYamlResponse`（162）分片传输：只有首块设置压缩总字节数 `total_size`，
只有末块 `done=True`。EHY1 格式为 magic `EHY1`、小端 uint32 文件数量；每个文件依次为
小端 uint16 路径 UTF-8 字节数、路径、小端 uint32 内容字节数、内容。
每连接独立传输，传输中重复请求忽略，写入遵循 backpressure，断线取消，不阻塞 Ping。
46.23.0 官方客户端尚无 `get_yaml()` 高层方法，示例使用连接的消息收集接口。

完整服务端及官方客户端示例：

```powershell
D:\conda\envs\hass\python.exe -m examples.device_setup
# 另一个终端：
D:\conda\envs\hass\python.exe -m examples.check_device_setup_client
```

### 现有功能的新字段

| 类型 | 使用方式 |
| --- | --- |
| 服务参数 | `ServiceArgument(type, description="", example="", optional=False, default_value="")`。默认值始终为字符串，如 `"true"`、`"0.6"`；空串表示无默认值。两字段仅为发现元数据，wire 调用仍须传入每个位置参数，服务端不自动补值。见 `examples/custom_services.py`。 |
| Cover | `CoverEntity(..., supports_tilt=True, supports_stop_tilt=True, supports_toggle=True)` 发布新能力。`stop_tilt` 调用可覆写的 `on_stop_tilt()`，保持倾角不变；默认钩子无硬件动作，接入电机时须覆写。`toggle` 调用 `on_toggle()`，默认在运动中停止，静止且关闭时打开，其余位置关闭；硬件可覆写控制逻辑。见 `examples/entity_showcase.py`。 |
| 子设备 | `DeviceInfo(relation=DeviceRelation.CHILD)` 表示同一物理设备的子设备；默认 `VIA` 为独立设备经本机中转。直接保留官方 protobuf 字段。见 `examples/entity_showcase.py`。 |
| 媒体格式 | `MediaPlayerSupportedFormat(..., bitrate=192)`，单位 kbps，0 表示无偏好；通过 `MediaPlayerEntity(supported_formats=...)` 传入。见 `examples/entity_showcase.py`。 |
| USB 描述 | `UsbDeviceDescriptor(interface_class=..., port_number=...)` 通过 `SerialProxyIdentity.usb` 保留。`examples/serialx_proxy.py` 接受显式 `identity=`，仅在取得真实 USB 描述时设置 `source=USB`；默认 `NONE`，不再使用上游标为保留的 `CONFIGURED` 值。 |

## 46.28.0 新能力

### 崩溃报告

`Device(crash_report=CrashReportStore(report))` 发布当前报告的能力标志，并响应
`CrashReportRequest`（163）/`CrashReportResponse`（164）。官方客户端调用
`await client.crash_report()`，调用前应检查
`(await client.device_capabilities()).crash_report.flags & CrashReportFlag.PRESENT`。

```python
from aioesphomeserver import (
    CrashReason, CrashReportCore, CrashReportFlag, CrashReportResponse,
    CrashReportStore, Device,
)

store = CrashReportStore(CrashReportResponse(
    flags=int(CrashReportFlag.PRESENT | CrashReportFlag.BUILD_MATCHES),
    reason=CrashReason.ABORT, pc=0x40001234, build_time=1794000000,
    crashed_core=0,
    cores=[CrashReportCore(core=0, backtrace=[0x40001234, 0x40005678])],
))
device = Device(name="diagnostic-device", crash_report=store)
```

报告使用官方 protobuf，完整保留 `flags`、`reason`、`pc`、`cause`、`fault_address`、
`build_time`、`crashed_core` 和每个 `cores` 的 `core`、`backtrace`。
标志包括 `PRESENT`、`BUILD_MATCHES`、`CAUSE`、`FAULT_ADDRESS`；后端按实际诊断设置。
`CrashReportStore()` 表示已接入但当前无报告，收到请求返回空响应；未接入时不应请求该能力。

报告在内存中保存，`set_report(response)` 可替换，调用时复制消息，完整 protobuf 不得超过
65515 字节。多客户端读取互斥，只有一个客户端可取得同一份报告；响应发送成功后清除，
失败、取消或连接停止时保留。发送期间存入的新报告不会被旧发送清除。报告清除后能力标志
变为 0，已读取的客户端能力快照不会自动更新，需重新请求。

应用自行提供诊断数据或持久化加载；库不安装 Python 异常捕获器，不把 Python traceback
伪装成固件 PC 地址。示例 `python -m examples.crash_report` 提供一份明确标注为模拟的记录，
可用 `python -m examples.check_device_setup_client` 验证读取和清除。

### 唤醒词音频

`VoiceAssistant(wake_word_audio=True)` 声明 `VoiceAssistantFeature.WAKE_WORD_AUDIO`
（位 7），也写入旧版设备信息能力字段。`output_only=True` 不允许开启该功能。
官方客户端通过 `subscribe_voice_assistant(..., wake_word_audio=True)` 请求订阅位 8，
必须提供 `handle_audio`；其 `handle_start` 会接收第五个
`VoiceAssistantWakeWordAudio | None` 参数。未请求时仍使用四参数回调。

只有本机声明支持且当前客户端请求后，`voice.is_wake_word_audio_requested` 才为真。
应用调用 `start(wake_word=VoiceAssistantWakeWordAudio.from_dict({...}))` 传入检测元数据：

| 模型字段 | 发送的 VoiceAssistantRequest 字段 |
| --- | --- |
| `wake_word_id` | `wake_word_id`（6） |
| `audio_bytes` | `wake_word_audio_bytes`（7） |
| `probability` | `wake_word_probability`（8） |
| `probability_cutoff` | `wake_word_probability_cutoff`（9） |
| `audio_bytes2` | `wake_word_audio_bytes2`（10） |

ID 非空、字节数为 uint32、概率和阈值为有限的 [0, 1] 数值；非双声道设备不能声明第二声道
缓冲字节数。两个字节数表示后续音频流开头属于唤醒词的部分，不包含之后的命令语音。
库只转发元数据和应用送入的音频，不实现采集或检测算法，也不根据概率自动作出验证结论。

**必须在等待启动回执期间发送缓冲音频**，HA 才能进行验证。典型调用顺序：

```python
import asyncio
from aioesphomeserver import VoiceAssistantWakeWordAudio

detection = VoiceAssistantWakeWordAudio.from_dict({
    "wake_word_id": "okay_nabu", "audio_bytes": len(buffered_pcm),
    "probability": 0.9, "probability_cutoff": 0.7,
})
start_task = asyncio.create_task(voice.start(
    wake_word_phrase="Okay Nabu", wake_word=detection,
))
try:
    await voice.wait_until_streaming_audio(timeout=10)
    # 分小块发送缓冲 PCM，然后继续实时数据；双声道每块都要提供 data2。
    for offset in range(0, len(buffered_pcm), 1024):
        await voice.send_audio(buffered_pcm[offset:offset + 1024])
    port = await start_task
    # 继续通过 send_audio 发送实时音频；应用在采集任务中处理。
finally:
    start_task.cancel()
    await asyncio.gather(start_task, return_exceptions=True)
```

`wait_until_streaming_audio()` 在请求发送后允许提前发流；启动响应仍通过 `start_task` 返回。
未协商该功能时，检测元数据被省略，恢复等待启动响应的旧行为；应用应检查协商状态，避免
把缓冲唤醒词音频混入普通命令流。`send_audio()` 仍要求 API 音频端口 0；提前流不接受 UDP 回执。

`VOICE_ASSISTANT_WAKE_WORD_REJECTED`（13）经 `on_event()` 传给应用，并停止流及使待启动请求失败。
拒绝、错误、RUN_END、断线、超时、取消或显式停止均收回提前流状态。超时/取消还会尝试通知
客户端停止；该停止通知最多等待 1 秒，写入失败或超时则关闭连接，避免启动任务的取消清理
无限等待。原始启动超时或取消仍会向调用方传播。
若已 `finish_audio()`，或已收到 STT_END/STT_VAD_END，稍后请求写入完成或收到启动响应
也不会重新打开麦克风流。新的 start() 会重置本轮音频结束标记。
完整发送缓冲音频及实时音频的示例见 `examples/voice_assistant.py` 的
`stream_detected_wake_word()`；它并发等待启动结果和音频发送，拒绝或断线导致启动失败时，
即使麦克风异步迭代器仍在等待下一块数据，也会取消发送任务并退出。
无需安装音频依赖即可阅读和用模拟数据测试。

### USB 接口描述和其余变更

`UsbDeviceDescriptor.interface_description`（7）为 USB iInterface 字符串，缺失时为空。
通过 `SerialProxy(identity=SerialProxyIdentity(usb=UsbDeviceDescriptor(...)))` 传入，
现有完整消息转发会保留该字段；`examples/serialx_proxy.py` 的身份配置说明已更新。
只填写实际硬件描述，不从串口路径推断。

上游 `InfraredRFReceiveEvent.timings` 的 std::span 注解不改变 Python wire 数据。
`probe_on_announce`、共享 zeroconf listener、`send_keepalive_now()` 和重连日志属于客户端行为，
服务端继续按现有协议响应 Ping。运行依赖最低 aioesphomeapi 调整为 46.28.0，
zeroconf 最低版本跟随上游升至 0.152.0；`requirements.txt` 使用已验证的 0.154.0。

日志订阅遵循客户端请求的 `level`，级别为 0 时取消该连接的日志推送。请求 `dump_config` 时调用 `Device.dump_config(client)`，应用可覆写并通过 `await client.log(level, text)` 发送安全的配置摘要；默认实现不输出配置。

默认 Alarm 和 Lock 实体仅在声明需要密码时检查传入命令的密码；应用应提供 `code="..."`，否则不会执行需密码的命令。自定义后端可覆写 `on_command()` 接入自己的密码校验；`code_format` 仅是 Lock 的界面格式提示。
