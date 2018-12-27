#!/usr/bin/env python
# -*- coding: utf-8 -*-
import time
import KaiterraUtils
import KetraUtils

from pubsub import pub
from ThreadBase import *
from PacketParser import *
from DBManagerDeviceProp import DBManagerDeviceProp
from DBManagerDevice import DBManagerDevice
from DBManagerAction import DBManagerAction


class KaiterraConnector(ThreadBase):
    __instant = None
    __lock = threading.Lock()

    # singleton
    def __new__(self, arg):
        Utils.logDebug("__new__")
        if KaiterraConnector.__instant == None:
            KaiterraConnector.__lock.acquire()
            try:
                if KaiterraConnector.__instant == None:
                    Utils.logDebug("new KaiterraConnector singleton instance.")
                    KaiterraConnector.__instant = ThreadBase.__new__(self)
            finally:
                KaiterraConnector.__lock.release()
        return KaiterraConnector.__instant

    def __init__(self, threadId):
        ThreadBase.__init__(self, threadId, "KaiterraConnector")
        self.laserEggIdList = DBManagerDeviceProp().getLaserEggIdList()

    def run(self):
        self.init()
        # 订阅查询最新的镭豆设备列表的消息
        pub.subscribe(self.updateLaserEggIdList, 'update_laserEgg_ids')
        self.queryLaserEggData()

    # 更新镭豆设备UDID列表
    def updateLaserEggIdList(self, laserEggId, add=False):
        Utils.logDebug("updating laserEggIdList...")
        self.laserEggIdList = []  # 先置空
        self.laserEggIdList = DBManagerDeviceProp().getLaserEggIdList()
        if add:
            # 如果是新增的镭豆，立刻查询新增的镭豆设备数据
            aqiPm25, aqiPm10, data = self.queryData(laserEggId)
            dataDict = {}
            dataDict[laserEggId] = data
            DBManagerDevice().updateLaserStatusInBatch(dataDict)


    def queryLaserEggData(self):
        while not self.stopped:
            dataDict = {}
            for laserUdid in self.laserEggIdList:
                # data = KaiterraUtils.get_laser_egg(laserUdid.lower(), rtn='data')
                # pm25 = data.get('pm25')
                # pm10 = data.get('pm10')
                # aqiPm25 = self.AQIPM25CN(pm25)
                # aqiPm10 = self.AQIPM10CN(pm10)
                # data['aqiPm25'] = aqiPm25
                # data['aqiPm10'] = aqiPm10
                aqiPm25, aqiPm10, data = self.queryData(laserUdid)
                if data:
                    dataDict[laserUdid] = data

                self.handleAlarm(aqiPm25, aqiPm10, laserUdid)

            try:
                if dataDict:
                    # 批量更新状态表
                    DBManagerDevice().updateLaserStatusInBatch(dataDict)
            except Exception:
                Utils.logError("LaserEgg data update error...continue")

            time.sleep(65)
            continue

    def queryData(self, laserUdid):
        data = KaiterraUtils.get_laser_egg(laserUdid.lower(), rtn='data')
        aqiPm25, aqiPm10 = 0, 0
        if data:
            pm25 = data.get('pm25')
            pm10 = data.get('pm10')
            aqiPm25 = self.AQIPM25CN(pm25)
            aqiPm10 = self.AQIPM10CN(pm10)
            data['aqiPm25'] = aqiPm25
            data['aqiPm10'] = aqiPm10
        return aqiPm25, aqiPm10, data

    def handleAlarm(self, aqiPm25, aqiPm10, laserUdid):
        if aqiPm25 == 0 and aqiPm10 == 0:  # 两个AQI都是0说明镭豆接口查询数据出问题了
            return

        if aqiPm25 >= 101:  #  or aqiPm10 >= 101
            # 发出联动
            almDevice = DBManagerAction().getActionByDevId(laserUdid)
            if almDevice:
                alarmAct = almDevice.get('alarmAct', None)
                if alarmAct:
                    actDevices = alarmAct.get('actList', [])
                    devicesToCtrol = []
                    ketra_devices = []
                    for actDevice in actDevices:
                        # 下面是要控制的设备
                        actDevAddrTemp = actDevice['deviceAddr']
                        if (actDevAddrTemp == ""):
                            continue

                        devtype = actDevice.get("devicetype", "")
                        devName = actDevice.get("devicename", "")
                        params = actDevice.get("params", "")

                        if devtype == DEVTYPENAME_AIR_FILTER:
                            airFilterStatus = DBManagerDevice().getDeviceByDevId(actDevAddrTemp)
                            statusValue = airFilterStatus.get('value', {})
                            if statusValue:
                                modeCode = statusValue.get('mode', 255)
                                if modeCode < 255:
                                    # 如果空气净化器本来就是开机状态则不再重复发出开机命令
                                    continue

                        if devtype == DEVTYPENAME_ACOUSTO_OPTIC_ALARM:
                            isEnabled = actDevice.get("isEnabled", 1)
                            if int(isEnabled) == 0:  # 当传感器撤防时，声光报警器不触发响应
                                continue

                        # 删除设备后，报警联动时忽略该设备
                        (devId, tmpDevice) = DBManagerDeviceProp().getDeviceByAddrName(actDevAddrTemp, devName)
                        if tmpDevice is None:
                            continue

                        if devtype == DEVTYPENAME_CIRCADIAN_LIGHT:
                            ketra_devices.append(params)
                            continue

                        for key in params.keys():
                            if 'set' not in key and 'state' not in key and 'coeff' not in key:
                                continue
                            singleValue = {}
                            v = params.get(key)
                            singleValue[key] = v

                            devToCtrol = {"name": devName, "addr": actDevAddrTemp, "value": singleValue,
                                          "type": devtype}
                            if devtype == "AirSystem":
                                singleValue = {"cmd": 2, "data": 0}
                                devToCtrol = {"name": devName, "addr": actDevAddrTemp, "value": singleValue,
                                              "type": devtype}
                            if devtype == "AirFilter":  # 空气净化器，配置入模式联动触发开机
                                singleValue = {"cmd": 2, "data": 254, "speed": 0, "dataLen": 1}
                                devToCtrol = {"name": devName, "addr": actDevAddrTemp, "value": singleValue,
                                              "type": devtype}
                            devicesToCtrol.append(devToCtrol)
                            # 发送控制命令到ContrlThread,以便在其中执行命令
                            # Utils.logDebug("publish alarm-actions.alarm:%s: actions:%s"%(devAddr,devicesToCtrol))
                            # globalVars.publishCmdToLocal(globalVars.cmdType_Control, devicesToCtrol)

                    # 控制设备的数组创建完毕，发送到ControlThread...
                    pub.sendMessage(GlobalVars.PUB_CONTROL_DEVICE, cmd="controlDevice", controls=devicesToCtrol)
                    if ketra_devices:
                        time.sleep(0.7)
                        for ketra_param in ketra_devices:
                            n4SerialNo = ketra_param.get("n4SerialNo")  # N4 序列号
                            buttonName = ketra_param.get("buttonName")  # X2 按键名
                            keypadName = ketra_param.get("keypadName")  # X2 面板名
                            KetraUtils.activateButton(n4SerialNo, keypadName, buttonName)  # activate Ketra X2

        else:
            # 发出恢复时的联动
            laserStatus = DBManagerDevice().getDeviceByDevId(laserUdid)
            if laserStatus:
                laserValue = laserStatus.get('value', {})
                aqiPm25Last = laserValue.get('aqiPm25')
                if aqiPm25Last < 101:
                    # 说明上一次已经恢复，不再重复发联动配置
                    return

            almDevice = DBManagerAction().getActionByDevId(laserUdid + "_recover")
            if almDevice:
                modeId = almDevice.get("modeId")
                sparam = {"modeId": modeId}
                pub.sendMessage("door_open", sparam=sparam)
        return

    # AQI计算公式
    def linear(self, AQIhigh, AQIlow, Conchigh, Conclow, Concentration):
        conc = float(Concentration)
        a = ((conc - Conclow) / (Conchigh - Conclow)) * (AQIhigh - AQIlow) + AQIlow
        linear = int(round(a))
        return linear

    # 根据PM2.5计算国内AQI指数
    def AQIPM25CN(self, Concentration):
        conc = float(Concentration)
        c = int(10 * conc) / 10
        if 0 <= c < 35.1:  # AQIhigh, AQIlow, Conchigh, Conclow, Concentration
            aqi = self.linear(50, 0, 35, 0, c)

        elif 35.1 <= c < 75.5:
            aqi = self.linear(100, 51, 75.4, 35.1, c)

        elif 75.5 <= c < 115.5:
            aqi = self.linear(150, 101, 115.4, 75.5, c)

        elif 115.5 <= c < 150.5:
            aqi = self.linear(200, 151, 150.4, 115.5, c)

        elif 150.5 <= c < 250.5:
            aqi = self.linear(300, 201, 250.4, 150.5, c)

        elif 250.5 <= c < 350.5:
            aqi = self.linear(400, 301, 350.4, 250.5, c)

        elif 350.5 <= c < 500.5:
            aqi = self.linear(500, 401, 500.4, 350.5, c)

        else:
            aqi = 500

        # if 0 <= c < 35:  # AQIhigh, AQIlow, Conchigh, Conclow, Concentration
        #     aqi = self.linear(50, 0, 35, 0, c)
        # elif 35 <= c < 75:
        #     aqi = self.linear(100, 51, 75, 35, c)
        # elif 75 <= c < 115:
        #     aqi = self.linear(150, 101, 115, 75, c)
        # elif 115 <= c < 150:
        #     aqi = self.linear(200, 151, 150, 115, c)
        # elif 150 <= c < 250:
        #     aqi = self.linear(300, 201, 250, 150, c)
        # elif 250 <= c < 350:
        #     aqi = self.linear(400, 301, 350, 250, c)
        # elif 350 <= c < 500:
        #     aqi = self.linear(500, 401, 500, 350, c)
        # else:
        #     aqi = 500

        return aqi

    # 根据PM2.5计算AQI指数(美标)
    def AQIPM25(self, Concentration):
        conc = float(Concentration)
        c = int(10 * conc) / 10
        if 0 <= c < 12.1:
            aqi = self.linear(50, 0, 12, 0, c)

        elif 12.1 <= c < 35.5:
            aqi = self.linear(100, 51, 35.4, 12.1, c)

        elif 35.5 <= c < 55.5:
            aqi = self.linear(150, 101, 55.4, 35.5, c)

        elif 55.5 <= c < 150.5:
            aqi = self.linear(200, 151, 150.4, 55.5, c)

        elif 150.5 <= c < 250.5:
            aqi = self.linear(300, 201, 250.4, 150.5, c)

        elif 250.5 <= c < 350.5:
            aqi = self.linear(400, 301, 350.4, 250.5, c)

        elif 350.5 <= c < 500.5:
            aqi = self.linear(500, 401, 500.4, 350.5, c)

        else:
            aqi = 500

        return aqi

    # 根据PM10计算AQI(美标)
    def AQIPM10(self, Concentration):
        conc = float(Concentration)
        c = int(10 * conc) / 10
        if 0 <= c < 55:
            aqi = self.linear(50, 0, 54, 0, c)

        elif 55 <= c < 155:
            aqi = self.linear(100, 51, 154, 55, c)

        elif 155 <= c < 255:
            aqi = self.linear(150, 101, 254, 155, c)

        elif 255 <= c < 355:
            aqi = self.linear(200, 151, 354, 255, c)

        elif 355 <= c < 425:
            aqi = self.linear(300, 201, 424, 355, c)

        elif 425 <= c < 505:
            aqi = self.linear(400, 301, 504, 425, c)

        elif 50 <= c < 605:
            aqi = self.linear(500, 401, 604, 505, c)

        else:
            aqi = 500

        return aqi

    # 根据PM10计算国内标准AQI
    def AQIPM10CN(self, Concentration):
        conc = float(Concentration)
        c = int(10 * conc) / 10
        if 0 <= c < 50:  # AQIhigh, AQIlow, Conchigh, Conclow, Concentration
            aqi = self.linear(50, 0, 49, 0, c)

        elif 50 <= c < 150:
            aqi = self.linear(100, 51, 149, 50, c)

        elif 150 <= c < 250:
            aqi = self.linear(150, 101, 249, 150, c)

        elif 250 <= c < 350:
            aqi = self.linear(200, 151, 349, 250, c)

        elif 350 <= c < 420:
            aqi = self.linear(300, 201, 419, 350, c)

        elif 420 <= c < 500:
            aqi = self.linear(400, 301, 499, 420, c)

        elif 500 <= c < 600:
            aqi = self.linear(500, 401, 599, 500, c)

        else:
            aqi = 500

        return aqi
