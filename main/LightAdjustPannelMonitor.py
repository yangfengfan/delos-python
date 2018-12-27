# -*- coding: utf-8 -*-

from ThreadBase import *
from pubsub import pub
from PacketParser import  *
from DBManagerDevice import *
import GlobalVars
import threading
import time
import Utils


class LightAdjustPannelMonitor(ThreadBase):
    __instant = None
    __lock = threading.Lock()

    # singleton
    def __new__(self, arg):
        Utils.logDebug("__new__")
        if (LightAdjustPannelMonitor.__instant == None):
            LightAdjustPannelMonitor.__lock.acquire()
            try:
                if (LightAdjustPannelMonitor.__instant == None):
                    Utils.logDebug("new LightAdjustPannelMonitor singleton instance.")
                    LightAdjustPannelMonitor.__instant = ThreadBase.__new__(self)
            finally:
                LightAdjustPannelMonitor.__lock.release()
        return LightAdjustPannelMonitor.__instant

    def __init__(self, tid):
        ThreadBase.__init__(self, tid, "LightAdjustPannelMonitor")
        self.pannelDict = {}

    def run(self):
        self.init()

        # 监听启动和停止调光定时发送事件
        pub.subscribe(self.start_pannel_listen, GlobalVars.PUB_START_PANNEL_LISTEN)
        pub.subscribe(self.stop_pannel_listen, GlobalVars.PUB_STOP_PANNEL_LISTEN)

        # 监测是否有处于节律模式的调光控制面板
        self.check_pannel_listen()

    # 启动一个新的定时发送线程
    def start_pannel_listen(self, addr, device_name):
        if addr not in self.pannelDict:
            Utils.logDebug("Start monitor at: %s" % addr)
            monitor = PannelMonitor(target=self.send_pannel_cmd, args=(addr, device_name))
            monitor.setDaemon(True)
            monitor.start()
            self.pannelDict[addr] = monitor

    # 关闭一个定时发送线程
    def stop_pannel_listen(self, addr):
        Utils.logDebug("Stop monitor at: %s" % addr)
        monitor = self.pannelDict.get(addr, None)
        if monitor:
            monitor.stop()
            self.pannelDict.pop(addr)

    # 将命令发出
    def send_pannel_cmd(self, addr, deviceName):
        Utils.logDebug("Send circadian mode to device: %s" % addr)
        device_cmd_param = {"name": deviceName, "addr": addr, "value": {"state": 1}, "type": DEVTYPENAME_LIGHTAJUST_PANNEL}
        pub.sendMessage(GlobalVars.PUB_CONTROL_DEVICE, cmd="controlDevice", controls=device_cmd_param)

    # 线程启动时监测网关内是否有处在节律模式的调光控制面板
    def check_pannel_listen(self):
        pannel_list = DBManagerDevice().getLightAdjustPannelByState(1)
        for pannel in pannel_list:
            addr = pannel.get("addr")
            device_name = pannel.get("name", "调光控制面板")
            if len(addr) == 20:
                self.start_pannel_listen(addr, device_name)


# 监控器线程类
class PannelMonitor(threading.Thread):

    def __init__(self, target, args):
        threading.Thread.__init__(self)
        self.__target = target
        self.__args = args
        self.__running = threading.Event()  # 用于停止线程
        self.__running.set()

    def run(self):
        while self.__running.is_set():
            if self.__target:
                self.__target(*self.__args)
                time.sleep(900)  # 每15分钟执行一次

    def stop(self):
        self.__running.clear()
