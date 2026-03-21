#!/usr/bin/env python3
# -*-coding:utf8-*-
# can总线读取二次封装
# 反馈码为100开头，反馈码总长为000000
import can
from can.message import Message
from enum import IntEnum, auto
from platform import system

from .core.can_comm_base import CanCommBase
from .can_sys_utils import CanSystemInfoBase, LinuxSocketCanSystemInfo


def create_can_comm_config(
    *,
    channel: str = "can0",
    interface: str = "socketcan",
    bitrate: int = 1_000_000,
    enable_check_can: bool = True,
    auto_connect: bool = True,
    timeout: float = 1.0,
    receive_own_messages: bool = False,
    local_loopback: bool = True,
):
    return {
        "channel": channel,
        "interface": interface,
        "bitrate": bitrate,
        "enable_check_can": enable_check_can,
        "auto_connect": auto_connect,
        "timeout": timeout,
        # Keep SocketCAN local loopback enabled so tools like candump can observe
        # SDK TX frames. Self RX is avoided by sharing one ThreadSafeBus for both
        # send/recv while leaving receive_own_messages disabled by default.
        "receive_own_messages": receive_own_messages,
        "local_loopback": local_loopback,
    }


class CanComm:
    """
    CanComm 是对平台实现进行分发的选择器，外部永远只用 CanComm。
    """

    def __init__(self, config: dict, comm_type: str = "can"):
        pass

    def __new__(cls, config: dict, comm_type: str = "can"):
        platform_system = system()

        if platform_system == "Linux" or platform_system == "Darwin":
            return CanCommLinux(config, comm_type)
        elif platform_system == "Windows":
            return None
        else:
            raise RuntimeError(f"Unsupported platform: {platform_system}")

# config = {
#     "type": None,
#     "channel": "can0",
#     "bustype": "socketcan",
#     "bitrate": 1000000,
#     "enable_check_can": false,
#     "auto_connect": true,
#     "timeout": 1.0,
# }


class CanCommLinux(CanCommBase):
    class CAN_STATUS(IntEnum):
        UNKNOWN = 100001
        INIT_CAN_BUS_IS_EXIST = auto()
        INIT_CAN_BUS_OPENED_SUCCESS = auto()
        INIT_CAN_BUS_OPENED_FAILED = auto()
        CLOSE_CAN_BUS_CONNECT_SHUT_DOWN = auto()
        CLOSE_CAN_BUS_WAS_NOT_PROPERLY_INIT = auto()
        CLOSE_SHUTTING_DOWN_CAN_BUS_ERR = auto()
        CLOSED_CAN_BUS_NOT_OPEN = auto()
        READ_CAN_MSG_OK = auto()
        READ_CAN_MSG_OK_NO_CB = auto()
        READ_CAN_MSG_TIMEOUT = auto()
        READ_CAN_MSG_FAILED = auto()
        SEND_MESSAGE_SUCCESS = auto()
        SEND_MESSAGE_FAILED = auto()
        SEND_CAN_BUS_NOT_OK = auto()
        BUS_STATE_ACTIVE = auto()
        BUS_STATE_PASSIVE = auto()
        BUS_STATE_ERROR = auto()
        BUS_STATE_UNKNOWN = auto()

        def __str__(self):
            return f"{self.name} ({self.value})"

        def __repr__(self):
            return f"{self.name}: {self.value}"

    def __init__(self,
                 config: dict,
                 comm_type: str = "can") -> None:
        super().__init__()
        # 初始化配置
        self._config = config.copy()
        self._comm_type = comm_type
        self._type = self._comm_type
        self._channel = self._config['channel']
        self._interface = (
            self._config['interface']
            if 'interface' in self._config
            else self._config.get('bustype', 'socketcan')
        )
        self._bitrate = self._config.get('bitrate', 1000000)
        self._enable_check_can = self._config.get('enable_check_can', True)
        self._auto_connect = self._config.get('auto_connect', True)
        self._timeout = self._config.get('timeout', 1.0)
        self._receive_own_messages = self._config.get("receive_own_messages", False)
        self._local_loopback = self._config.get("local_loopback", True)
        # 总线状态
        self.recv_bus = None
        self.send_bus = None
        self._is_connected = False
        self._is_stopped = False
        self.sysinfo: CanSystemInfoBase = None
        if self._interface == "socketcan":
            self.sysinfo = LinuxSocketCanSystemInfo
        if self._enable_check_can and self.sysinfo is not None:
            self.check_can()
        if (self._auto_connect):
            self.connect()

    def __del__(self):
        self.close()

    def connect(self, **kwargs):
        if self.recv_bus is not None and self.send_bus is not None:
            self._last_error = None
            self._is_connected = True
            self._is_stopped = False
            return True
        recv_bus = None
        send_bus = None
        try:
            common_kwargs = dict(
                channel=self._channel,
                interface=self._interface,
                bitrate=self._bitrate,
            )
            if self._interface == "socketcan":
                common_kwargs.update(
                    dict(
                        receive_own_messages=self._receive_own_messages,
                        local_loopback=self._local_loopback,
                    )
                )

            recv_bus = can.ThreadSafeBus(**common_kwargs)
            # Share one socketcan bus between TX/RX so candump still sees local
            # loopback traffic while the SDK avoids receiving its own TX frames.
            send_bus = recv_bus
            if self._interface != "socketcan":
                send_bus = can.ThreadSafeBus(**common_kwargs)

            self.recv_bus = recv_bus
            self.send_bus = send_bus
            self._last_error = None
            self._is_connected = True
            self._is_stopped = False
            return True
        except Exception as e:
            for bus in (send_bus, recv_bus):
                if bus is not None:
                    try:
                        bus.shutdown()
                    except Exception:
                        pass
            self.recv_bus = None
            self.send_bus = None
            self._last_error = e
            self._is_connected = False
            self._is_stopped = True
            return False

    def close(self):
        if self.recv_bus is None and self.send_bus is None:
            return self.CAN_STATUS.CLOSED_CAN_BUS_NOT_OPEN
        try:
            recv_bus = self.recv_bus
            send_bus = self.send_bus
            self.recv_bus = None
            self.send_bus = None
            if recv_bus is not None:
                recv_bus.shutdown()  # 关闭 CAN 总线
            if send_bus is not None and send_bus is not recv_bus:
                send_bus.shutdown()
            self._is_connected = False
            self._is_stopped = True
            return self.CAN_STATUS.CLOSE_CAN_BUS_CONNECT_SHUT_DOWN
        except AttributeError:
            return self.CAN_STATUS.CLOSE_CAN_BUS_WAS_NOT_PROPERLY_INIT
        except Exception:
            return self.CAN_STATUS.CLOSE_SHUTTING_DOWN_CAN_BUS_ERR

    def send(self, msg: Message, timeout=None):
        can_bus_status = self._get_states(self.send_bus)
        if can_bus_status == self.CAN_STATUS.BUS_STATE_ACTIVE:
            try:
                self.send_bus.send(msg, timeout)
                self._last_error = None
                return True
            except Exception as e:
                self._last_error = e
                return False
        else:
            self._last_error = RuntimeError(
                f"CAN bus {self._channel} is not active: {can_bus_status.name}"
            )
            return False

    def recv(self):
        can_bus_status = self._get_states(self.recv_bus)
        if (can_bus_status == self.CAN_STATUS.BUS_STATE_ACTIVE):
            try:
                rx_message = self._read_message()
                if rx_message is None:
                    return None
                if rx_message and self.has_callback():
                    self._trigger_callback(rx_message)  # 回调函数处理接收的原始数据
                    return rx_message
                else:
                    return rx_message
            except Exception as e:
                return None
        else:
            return None

    def _read_message(self):
        return self.recv_bus.recv(self._timeout)

    def _get_states(self, bus=None):
        if isinstance(bus, can.BusABC):
            bus_state = bus.state
        else:
            bus_state = None
        if bus_state == can.BusState.ACTIVE:
            return self.CAN_STATUS.BUS_STATE_ACTIVE
        elif bus_state == can.BusState.PASSIVE:
            return self.CAN_STATUS.BUS_STATE_PASSIVE
        elif bus_state == can.BusState.ERROR:
            return self.CAN_STATUS.BUS_STATE_ERROR
        else:
            return self.CAN_STATUS.BUS_STATE_UNKNOWN

    def check_can(self):
        # 检查 CAN 端口是否存在
        if not self.sysinfo.is_exists(self._channel):
            raise ValueError(f"CAN socket {self._channel} does not exist.")
        # 检查 CAN 端口是否 UP
        if not self.sysinfo.is_up(self._channel):
            raise RuntimeError(f"CAN port {self._channel} is not UP.")
        # 检查 CAN 端口的比特率
        actual_bitrate = self.sysinfo.get_bitrate(self._channel)
        if self._bitrate is not None and not (actual_bitrate == self._bitrate):
            raise ValueError(
                f"CAN port {self._channel} bitrate is {actual_bitrate} bps, expected {self._bitrate} bps.")

# if __name__ == "__main__":
#     can_name = "can0"
