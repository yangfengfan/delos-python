# -*- coding: utf-8 -*-
from SocketServer import *
import traceback  

import GlobalVars
import ErrorCode
import Utils
import json
from PacketParser import *
import hashlib
import os
from pubsub import pub
from DBManagerAlarm import *
from DBManagerAction import *
from DBManagerDevice import *
from DBManagerBackup import *
from DBManagerHostId import *
from DBManagerRoom import *
from DBManagerRoomArea import *
from DBManagerDeviceProp import *
from DBManagerLinks import *
from BoerCloud import *
from SocketServer import ThreadingTCPServer, StreamRequestHandler
from DBManagerHGC import *
from DBManagerTask import *
from DBManagerUser import *
from DBManagerHistory import *
from HopeMusic import *
import KetraUtils
import urllib2
import shutil
import base64
from UtilsCommandHandlerBosheng import *
from WiseMusic import *
from BatchScanner import *
import thread
import ssl
from sys import version_info as pyversion
from random import randint


# 处理从app或云端过来的配置和控制命令
class SocketHandlerServer(ThreadBase):
    __instant = None
    __lock = threading.Lock()

    # singleton
    def __new__(self, arg):
        Utils.logDebug("__new__")
        if(SocketHandlerServer.__instant==None):
            SocketHandlerServer.__lock.acquire()
            try:
                if(SocketHandlerServer.__instant==None):
                    Utils.logDebug("new SocketHandlerServer singleton instance.")
                    SocketHandlerServer.__instant = ThreadBase.__new__(self)
            finally:
                SocketHandlerServer.__lock.release()
        return SocketHandlerServer.__instant

    def __init__(self, tid):
        ThreadBase.__init__(self, tid, "SocketHandlerServer")
        self.recvBuffer = ""
        self.activedMode = None
        self.batchScanner = None  # 批量扫描的scanner对象 -- 20170315
        self.scannerThread = None  # 批量扫描的线程，线程调用 BatchScanner类实例的scan()函数和stop_scan()函数
        self.scannerWatchdog = None  # 监控批量扫描线程，超过2分钟停止批量扫描
        self.operatingDev = None  # 用户是否正在分配设备的标记
        # self.optWatchdog = None  # 监控用户分配设备标记，为防止用户仅仅进入列表而不

    def setup(self):
        host = "127.0.0.1"       # 网关名，可以是ip,像localhost的网关名,或""
        port = 6789     # 端口
        addr = (host, port)

        # server = ThreadingTCPServer(addr, SocketHandlerServer)
        # server.serve_forever()
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)  # UDP
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(addr)
        # sock.listen(10)
        self.recvBuffer = ""
        self.solib = None
        return sock

    # def socket_readint(self, clientsock, size=4):
    #     size_format = {
    #         1: 'b',
    #         2: 'h',
    #         4: 'i',
    #         8: 'l'
    #     }
    #     sock_buffer = []
    #     while len(sock_buffer) < size:
    #         recv_ret = clientsock.recv(size - len(sock_buffer))
    #         sock_buffer += recv_ret
    #
    #     ret = struct.unpack('>' + size_format[size], ''.join(sock_buffer))[0]
    #     return int(ret)
    #
    def parseData(self, data):
        if(data == None):
            return

        # 将这次收到的和以前剩余的连接起来
        self.recvBuffer = self.recvBuffer + data

        msgarr = []
        _hlen = 2
        # while(True):
        if(len(self.recvBuffer) < _hlen):
            # break # 不完整的包
            return

        # 解析出命令字
        tmp = self.recvBuffer[0:_hlen]
        # datalen = struct.unpack("=h", tmp)
        datalen = int(struct.unpack("=h", tmp)[0])
        # datalen = struct.unpack("h", self.recvBuffer[0:_hlen])
        if(len(self.recvBuffer) < _hlen + datalen):
            Utils.logError("server pack allBufferLen=%d, but there's not a entire pack. bodyLen=%d!" % (len(self.recvBuffer), datalen))
            # break # 不完整的包
            return

        msg = self.recvBuffer[_hlen: _hlen + datalen]
        self.recvBuffer = self.recvBuffer[_hlen + datalen:]
        msgarr.append(msg)
        return msgarr

    def run(self):
        Utils.logInfo("SocketHandlerServer is running.")
        self.init()
        s = self.setup()
        # begin=time.time()
        pub.subscribe(self.cancel_alarm, "cancelAlarm")
        pub.subscribe(self.activeRoomMode, "door_open")
        pub.subscribe(self.updateDeviceProp, "add_new_device")

        while not self.stopped:
            # clientsock,addr=s.accept()
            try:
                if s == None:
                    time.sleep(2)
                    Utils.logInfo('trying to set up socket server...')
                    s = self.setup()
                # Utils.logInfo('trying to rx socket data from client...%s'%(hex(id(s))))
                data, addr = s.recvfrom(GlobalVars.MAX_SOCKET_PACKET_SIZE)
                # Utils.logInfo('socket server rx data:%s'%(data))

                # Utils.disableGC()
                msgarr = self.parseData(data)
                Utils.logDebug('Rx commands:%s'%(msgarr))
                for msg in msgarr:
                    command = None
                    if '/ihome/etc/cmd_files' in msg:
                        # big message in files.
                        if os.path.exists(msg):
                            file_object = open(msg)
                            try:
                                textmsg = file_object.read()
                                command = json.loads(textmsg)
                            finally:
                                file_object.close()
                                os.remove(msg)
                    else:
                        # msg_len = self.socket_readint(sock, 2)
                        # msg = sock.recv(msg_len)
                        command = json.loads(msg)
                    # destAddress = (addr[0], 9998)
                    self.processRequest((s, addr), command)
                # Utils.enableGC()
            except:
                Utils.logException('inner socket server exception.')
                # s.shutdown(2)
                if s != None:
                    try:
                        s.close()
                    except:
                        pass
                    s = None
                # time.sleep(1)
            finally:
                pass

        # s.shutdown(2)
        s.close()
        Utils.logError('inner socket server exit!...')
        time.sleep(10)

    def processRequest(self, clientsock, command):
        Utils.logDebug("processRequest inner socket packet")
        try:
            # command = json.loads(msg)
            success = ErrorCode.SUCCESS
            msg = None
            ret = self.configHandler(command)
            if ret == None or len(ret) != 2:
                # success = -1
                success = ErrorCode.ERR_GENERAL
            else:
                success = ret[0]
                msg = ret[1]
                # if ret[0] == False:
                #     success = -1
            self.sendResponse(clientsock, success, msg)
            # clientsock.close()
            if success >= ErrorCode.ERR_GENERAL:
                Utils.logInfo('Command returns failed.(%d, %s)'%(success, command))
        except:
            Utils.logException("processRequest inner socket packet error")
            try:
                self.sendResponse(clientsock, ErrorCode.ERR_GENERAL, {"msg": "系统处理异常"})
            except:
                pass

    
    def backupToClould(self, datatype, detail, op = None):
        metaDict={}
        metaDict["type"] = datatype
        metaDict["valueStr"] = detail
        if op != None:
            metaDict["op"] = op
        Utils.logInfo("publish PUB_SEND_RTDATA %s"%(datatype))
        pub.sendMessage(GlobalVars.PUB_SEND_RTDATA, rtdata=metaDict, arg2=None)
        del metaDict

    def sendResponse(self, clientsock, errcode, response):
        if errcode is None or clientsock is None:
            return

        metaDict = dict(ret=errcode)
        # metaDict["ret"] = errcode
        if response != None:
            if isinstance(response, dict) and response.get("newAlarmList") is not None:
                metaDict["newAlarmList"] = response.get("newAlarmList", [])
                metaDict["response"] = response.get("allDeviceList", [])
            else:
                metaDict["response"] = response
            dataMD5 = 0
            try:
                jsondata = json.dumps(response)
                dataMD5 = hashlib.md5(jsondata).hexdigest()
            except:
                dataMD5 = 0
            metaDict["md5"] = dataMD5
        # Utils.logDebug("publish PUB_RESPONSE_HOST %s"%(datatype))
        # pub.sendMessage(GlobalVars.PUB_RESPONSE_HOST, resp=metaDict, arg2=None)
        buf = json.dumps(metaDict)
        del metaDict
        sock = clientsock[0]
        addr = clientsock[1]
        Utils.logDebug('send response:ret=%s,response=%s'%(str(errcode), buf))
        return self._send2(sock, addr, buf)
        # msg_len = struct.pack('=h', len(buf))
        # return sock.sendto(msg_len + buf, addr)

    def _send2(self, sock, destaddr, message):
        # Utils.logInfo('server ready to send %s'%(message))
        msg_len = len(message)
        if msg_len < GlobalVars.MAX_SOCKET_PACKET_SIZE:
            cmd_len = struct.pack('=h', msg_len)
            return sock.sendto(cmd_len + message, destaddr)
        else:
            # big message. store in file first.
            md5 = hashlib.md5(message).hexdigest()
            cmd_file_name = '/ihome/etc/cmd_files/'+md5+str(time.time())
            file_object = open(cmd_file_name, 'w')
            file_object.write(message)
            file_object.close( )
            # return sock.sendto(cmd_file_name, destaddr)
            msg_len = len(cmd_file_name)
            cmd_len = struct.pack('=h', msg_len)
            return sock.sendto(cmd_len + cmd_file_name, destaddr)

    # def _sendCmdResponse(self, clientsock, success):
    #     result = "success"
    #     if success == False:
    #         result = "fail"
    #     self.sendResponse(clientsock, result, "")

    # 查询全部配置过的全局模式，由于没有timestamp可用于判断是否和app缓存的数据一致，所以携带MD5
    def returnByCheckMD5(self, rawMD5, data):
        Utils.logDebug('returnByCheckMD5')
        try:
            jsondata = json.dumps(data)
            dataMD5 = hashlib.md5(jsondata).hexdigest()
        except:
            dataMD5 = 0
        if rawMD5 == dataMD5:
            # MD5一致，无需再次发送内容
            return (ErrorCode.SUCCESS_SAME_TIMESTAMP, None)
        else:
            # 时间戳不一致，将查询到的数据发送给app
            Utils.logInfo('returnByCheckMD5 command response:%s'%(data))
            return (ErrorCode.SUCCESS, data)

    def returnByTimestamp(self, params, data):
        Utils.logDebug('returnByTimestamp')
        # 查看app缓存的时间戳和数据库的是否一致
        appTimestamp = None
        dbTimestamp = None
        try:
            appTimestamp = params.get('timestamp', None)
            dbTimestamp = data.get('timestamp', None)
        except:
            pass
        if appTimestamp != None and appTimestamp == dbTimestamp:
            # 时间戳一致，无需再次发送内容
            return (ErrorCode.SUCCESS_SAME_TIMESTAMP, None)
        else:
            # 时间戳不一致，将查询到的数据发送给app
            Utils.logDebug('returnByTimestamp command response:%s'%(data))
            return (ErrorCode.SUCCESS, data)

    def configHandler(self, cmd):
        Utils.logDebug("handle command: %s"%(cmd))
        if cmd.has_key("cmdType") == False:
            return (ErrorCode.ERR_CMD_TYPE, None)
        cmdType = cmd["cmdType"]
        payload = cmd["payload"]
        if cmdType > GlobalVars.TYPE_CMD_BG_MUSIC_BOSHENG_START and cmdType < GlobalVars.TYPE_CMD_BG_MUSIC_BOSHENG_END:
            return
        if cmdType == GlobalVars.TYPE_CMD_UPGRADE_NOTIFICATION:
            # 网关升级
            return self.upgradeHost(payload)
        if cmdType == GlobalVars.TYPE_CMD_MODIFY_HOST_CONFIG:
            # 修改网关属性
            return self.modifyHostProperty(payload)

        if cmdType == GlobalVars.TYPE_CMD_MODIFY_HOSTNAME_CONFIG:
            # 修改网关名称 1020
            return self.modifyHostName(payload)

        if cmdType == GlobalVars.TYPE_CMD_MODIFY_USER_CONFIG:
            # 修改用户属性 1019
            return self.modifyUserProperty(payload)

        elif cmdType == GlobalVars.TYPE_CMD_QUERY_GLOBAL_DATA:
            return self.readGlobalData(payload)
        elif cmdType == GlobalVars.TYPE_CMD_READ_HOST_CONFIG:
            # 读取网关属性
            return self.readHostConfig(payload)
        elif cmdType == GlobalVars.TYPE_CMD_CHECK_HOST_STATE:
            # APP检查网关状态，家庭管理网关列表中使用
            return self.checkstate(payload)
        elif cmdType == GlobalVars.TYPE_CMD_READ_ALARMS:
            # 读取告警：
            return self.readAlarms(payload)
        elif cmdType == GlobalVars.TYPE_CMD_CONFIRM_ALARMS:
            # 确认告警：
            return self.confirmAlarms(payload)
        elif cmdType == GlobalVars.TYPE_CMD_CONTROL_DEVICE:
            # 控制设备：
            return self.controlDevices(payload)
        elif cmdType == GlobalVars.TYPE_CMD_REMOVE_DEVICE:
            # 删除设备：
            return self.removeDevices(payload)
        elif cmdType == GlobalVars.TYPE_CMD_DISMISS_DEVICE:
            # 解绑设备：
            return self.dismissDevices(payload)
        elif cmdType == GlobalVars.TYPE_CMD_UPDATE_DEVICE:
            # 添加设备：
            return self.updateDeviceProp(payload)
        elif cmdType == GlobalVars.TYPE_CMD_QUERY_DEVICES:
            # 查询设备：仅直连网关的情况下才会触发
            return self.queryDevices(payload)
        elif cmdType == GlobalVars.TYPE_CMD_QUERY_ONE_DEVICE_PROP:
            # 查询一个设备的属性
            return self.query_device(payload)
        elif cmdType == GlobalVars.TYPE_CMD_QUERY_DEVICES_STATUS:
            # 查询设备状态：仅直连网关的情况下才会触发
            return self.queryDeviceStatus(payload)
        elif cmdType == GlobalVars.TYPE_CMD_DEVICES_STATUS_FOR_DELOS:
            # Delos展厅数据展示屏查询空气质量检测数据
            return self.queryDeviceStatusForDelos(payload)
        elif cmdType == GlobalVars.TYPE_CMD_QUERY_ROOM_PROP:
            # 查询房间属性：仅直连网关的情况下才会触发
            return self.queryRoomProp(payload)
        elif cmdType == GlobalVars.TYPE_CMD_UPDATE_ROOM_PROP:
            # 修改房间属性：
            return self.updateRoomProp(payload)
        elif cmdType == GlobalVars.TYPE_CMD_REMOVE_ROOM_PROP:
            # 删除房间：
            return self.removeRoomProp(payload)
        elif cmdType == GlobalVars.TYPE_CMD_QUERY_AREA_PROP:
            # 查询房间属性：仅直连网关的情况下才会触发
            return self.queryAreaProp(payload)
        elif cmdType == GlobalVars.TYPE_CMD_UPDATE_AREA_PROP:
            # 修改房间属性：
            return self.updateAreaProp(payload)
        elif cmdType == GlobalVars.TYPE_CMD_REMOVE_AREA_PROP:
            # 删除房间：
            return self.removeAreaProp(payload)
        elif cmdType == GlobalVars.TYPE_CMD_QUERY_ROOM_MODE:
            # 查询房间模式：仅直连网关的情况下才会触发
            return self.queryRoomMode(payload)
        elif cmdType == GlobalVars.TYPE_CMD_UPDATE_ROOM_MODE:
            # 修改房间模式：
            return self.updateRoomMode(payload)
        elif cmdType == GlobalVars.TYPE_CMD_REMOVE_ROOM_MODE:
            # 删除房间模式：
            return self.removeRoomMode(payload)
        elif cmdType == GlobalVars.TYPE_CMD_ACTIVE_ROOM_MODE:
            # 激活房间模式：
            return self.activeRoomMode(payload)
        elif cmdType == GlobalVars.TYPE_CMD_QUERY_LINK_ACTION:
            # 查询联动计划：仅直连网关的情况下才会触发
            device_type = payload.get("deviceType", None)
            # if device_type in ["Exist", "Gsm", "CurtainSensor"]:
            if self.isSensorDevType(device_type):
                return self.queryExistLinkAction(payload)
            return self.queryLinkActions(payload)
        elif cmdType == GlobalVars.TYPE_CMD_UPDATE_LINK_ACTION:
            # 修改联动计划：
            return self.updateLinkAction(payload)
        elif cmdType == GlobalVars.TYPE_CMD_LINK_DEVICES:
            # 设备关联
            return self.linkDevices(payload)
        elif cmdType == GlobalVars.TYPE_CMD_QUERY_DEVICES_LINKS:
            # 查询设备关联列表
            return self.querylinkDevices(payload)
        elif cmdType == GlobalVars.TYPE_CMD_BACKUP_HOST_PROP2:
            # 备份网关属性到云端
            return self.backupHost2Cloud(payload)
        elif cmdType == GlobalVars.TYPE_CMD_RESTORE_HOST_PROP:
            # 从云端恢复网关属性，实现在main.py
            return (False, 'Error request...')
        elif cmdType == GlobalVars.TYPE_CMD_HCG_CONFIG:
            # 中控设备的配置
            return self.configHGC(payload)
        elif cmdType == GlobalVars.TYPE_CMD_HCG_QUERY_CONFIG:
            # 查询中控设备的配置
            return self.QueryHGCconfig(payload)
        elif cmdType == GlobalVars.TYPE_CMD_HCG_DELETE_CONFIG:
            # 删除中控设备的一条配置
            return self.deleteHGCconfig(payload)
        elif cmdType == GlobalVars.TYPE_CMD_VERIFY_ADMIN_PWD:
            return self.verifyAdminPassword(payload)

        # 验证用户名密码
        elif cmdType == GlobalVars.TYPE_CMD_VERIFY_USER_PWD:
            return self.verifyUserPassword(payload)

        # 查询水电表的地址
        elif cmdType == GlobalVars.TYPE_CMD_QUERY_METER_ADDRS:
            return self.queryMeterAddrs(payload)
        # 修改水电表的名称
        elif cmdType == GlobalVars.TYPE_CMD_MODIFY_METER_NAME:
            return self.modifyMeterName(payload)

        # 修改模式名称
        elif cmdType == GlobalVars.TYPE_CMD_MODIFY_MODE_NAME:
            return self.modifyModeName(payload)

        # 查询全局模式
        elif cmdType == GlobalVars.TYPE_CMD_QUERY_GLOBAL_MODE:
            return self.queryGlobalMode()

        # 查询所有设备的属性和状态
        elif cmdType == GlobalVars.TYPE_CMD_READ_ALL_DEVICE:
            return self.query_all_devices(payload)

        # 设置定时任务
        elif cmdType == GlobalVars.TYPE_CMD_SET_TIME_TASK:
            return self.set_time_task(payload)

        # 设置定时任务
        elif cmdType == GlobalVars.TYPE_CMD_SWITCH_TIME_TASK:
            return self.switch_time_task(payload)

        # 查询定时任务是否开启
        elif cmdType == GlobalVars.TYPE_CMD_QUERY_TASK_DETAIL:
            return self.query_task_detail(payload)

        # 设置地暖定时
        elif cmdType == TYPE_CMD_SET_FLOOR_HEATING_TIME_TASK:
            return self.set_floor_heating_time_task(payload)

        # 打开或者关闭地暖定时
        elif cmdType == TYPE_CMD_SWITCH_FLOOR_HEATING_TIME_TASK:
            return self.switch_FL_time_task(payload)

        # 普通直连登陆
        elif cmdType == TYPE_CMD_NORMAL_LOGIN:
            return self.normalLogin(payload)

        # 保存用户个人信息
        elif cmdType == TYPE_CMD_SAVE_USER_INFO:
            return self.saveUserInfo(payload)

        # 云端已经登陆后的直连登陆，保存及更新用户账户信息
        elif cmdType == TYPE_CMD_AUTHORIZED_LOGIN:
            return self.authorizedLogin(payload)

        # 退出登陆
        elif cmdType == TYPE_CMD_LOGOUT:
            return self.logout(payload)

        # 删除网关上的用户
        elif cmdType == TYPE_CMD_DELETE_USER:
            return self.deleteUser(payload)

        # 获取系统时间
        elif cmdType == TYPE_CMD_GET_SYS_TIME:
            return self.getSysTime(payload)

        # 查询全部模式，包括全局模式和房间模式
        elif cmdType == TYPE_CMD_GET_ALL_MODES:
            return self.getAllModesForPannel(payload)

        # APP发送开始批量扫描请求（仅直连）
        elif cmdType == TYPE_CMD_START_SCAN_BATCH:
            return self.startScanBatch(payload)

        # APP发送结束批量扫描请求（仅直连）
        elif cmdType == TYPE_CMD_STOP_SCAN_BATCH:
            return self.stopScanBatch()

        # 批量搜索设备是APP查询设备信息列表（仅直连）
        elif cmdType == TYPE_CMD_QUERY_BATCH_DEVICE:
            return self.queryDeviceWithBatch(payload)

        # 保存批量添加的设备信息（仅直连）
        elif cmdType == TYPE_CMD_SAVE_BATCH_DEVICE:
            return self.saveDeviceBatch(payload)
        # 更新常用设备信息
        elif cmdType == TYPE_CMD_UPDATE_DEVICE_FAVORITE:
            return self.editFavoriteDevice(payload)
        # 查询镭豆屏幕所需房间列表(仅直连)
        elif cmdType == TYPE_CMD_LEIDOU_ROOM_LIST:
            return self.query_rooms_leidou(payload)

    # 获取系统时间
    def getSysTime(self, sparam):
        time_stamp = int(time.time())
        local_time = time.localtime()
        result_dict = dict(timestamp=time_stamp)
        time_str = time.strftime("%Y-%m-%d %H:%M:%S %A")
        result_dict["timeString"] = time_str
        result_dict["timeList"] = [local_time.tm_year, local_time.tm_mon, local_time.tm_mday, local_time.tm_hour,
                                   local_time.tm_min, local_time.tm_sec, int(local_time.tm_wday) + 1]
        return ErrorCode.SUCCESS, result_dict

    # 云端通知网关开始升级。。。
    def upgradeHost(self, param):
        if not param:
            return ErrorCode.ERR_INVALID_PARAMS, None
        fn = param.get("url", None)
        mdfive = param.get("md5", None)
        if fn is None or mdfive is None:
            return ErrorCode.ERR_INVALID_PARAMS, None
        Utils.logInfo("publish PUB_FILE_UPGRADE %s" % fn)
        pub.sendMessage(GlobalVars.PUB_FILE_UPGRADE, url=fn, md5=mdfive)
        return ErrorCode.SUCCESS, None

    # 恢复网关数据库
    def restoreHostProp(self, param):
        if not param:
            return ErrorCode.ERR_INVALID_PARAMS, None
        fn = param.get("url", None)
        mdfive = param.get("md5", None)
        if fn is None or mdfive is None:
            return
        Utils.logInfo("publish restore_host_prop %s" % fn)
        pub.sendMessage('restore_host_prop', url=fn, md5=mdfive)
        return ErrorCode.SUCCESS, None

    # 验证用户名密码
    def verifyUserPassword(self, param):
        hostId = param.get("hostId", None)
        if Utils.get_mac_address() != hostId:
            Utils.logError('Invalid host properties. Please check app requests.')
            return (ErrorCode.ERR_GENERAL, "无效的主机配置(ID错误)")
        self.verifyAdminPassword(param)

    # 云账号登陆时，升级网关程序
    # 需鉴权，采用本接口
    def verifyAdminPassword(self, param):
        try:
            userName =  param.get("username", "")
            userPassword = param.get("password", "")
        except:
            userObj = {"status": 1, "statusinfo": "参数错误"}
            return (ErrorCode.SUCCESS, userObj)

        try:
            userObj = DBManagerUser().getUserDetailBy(userName)
        except:
            userObj = {"status": 2, "statusinfo": "无此用户"}
            return (ErrorCode.SUCCESS, userObj)

        if(userObj == None):
            userObj = {"status": 2, " statusinfo": "无此用户"}
            return (ErrorCode.SUCCESS, userObj)
        if(userObj.get("password","") == userPassword):
            userObj["status"] = 0
            userObj["statusinfo"] = ""
            hostId = DBManagerHostId().getHostId()
            if hostId != None:
                userObj["hostId"] = hostId

            return (ErrorCode.SUCCESS, userObj)
        else:
            userObj = {"status":3, "statusinfo":"主机安全码错误"}
            return (ErrorCode.SUCCESS, userObj)

    # TODO放入新线程执行
    # http://www.cnblogs.com/chy710/p/3791317.html
    def backupHost2Cloud(self, param):
        try:
            hostId = DBManagerHostId().getHostId()
            if hostId == None:
                return (ErrorCode.ERR_GENERAL, None)

            hostProp = DBManagerHostId().getHost()
            hostProp["lastbackup"] = int(time.time())
            oldtimestamp = None
            if hostProp.has_key("timestamp"):
                oldtimestamp = hostProp.get("timestamp")
            DBManagerHostId().updateHostConfig(hostProp.get("hostId"), hostProp.get("name"), hostProp, oldtimestamp)

            dbf = open('/ihome/etc/host.db', 'rb')                 # 二进制方式打开图文件
            src_content = dbf.read()
            base64_src = base64.b64encode(src_content)  # 读取文件内容，转换为base64编码
            dbf.close()

            # backupfile = '/ihome/backup.txt'
            # outputf = open(backupfile, 'w')
            # outputf.write(base64dbf)
            # outputf.close()

            url = "https://" + GlobalVars.SERVER_URL + ":9002/config/upload?hostId=" + hostId
            # dbfile = '/ihome/etc/host.db'

            # if os.path.exists(backupfile) == False:
            #     return (ErrorCode.ERR_GENERAL, None)

            # md5 = self.checkMD5(backupfile)
            src_md5 = hashlib.md5(src_content).hexdigest()

            boundary = '----------%s' % hex(int(time.time() * 1000))
            data = []
            data.append('--%s' % boundary)

            data.append('Content-Disposition: form-data; name="%s"\r\n' % 'md5')
            data.append(src_md5)
            data.append('--%s' % boundary)

            # fr=open(backupfile,'rb')
            data.append('Content-Disposition: form-data; name="%s"; filename="host.db"' % 'config')
            data.append('Content-Type: %s\r\n' % 'application/octet-stream')
            # data.append(fr.read())
            data.append(base64_src)
            # fr.close()
            data.append('--%s--\r\n' % boundary)

            # http_url='http://remotserver.com/page.php'
            http_body = '\r\n'.join(data)

            try:
                # buld http request
                req=urllib2.Request(url, data=http_body)
                # header
                req.add_header('Content-Type', 'multipart/form-data; boundary=%s' % boundary)
                req.add_header('User-Agent', 'Mozilla/5.0')
                # req.add_header('Referer','http://remotserver.com/')
                # post data to server
                if pyversion >= (2,7,9):
                    resp = urllib2.urlopen(req, context=ssl._create_unverified_context(), timeout=5)
                else:
                    resp = urllib2.urlopen(req, timeout=5)
                # get response
                resp.read()
                Utils.logInfo('====upload db file success!======')

                # 上传成功：更新网关属性的备份时间
                hostProp = DBManagerHostId().getHost()
                hostProp["lastbackup"] = int(time.time())
                oldtimestamp = None
                if hostProp.has_key("timestamp"):
                    oldtimestamp = hostProp.get("timestamp")
                ret=DBManagerHostId().updateHostConfig(hostProp.get("hostId"), hostProp.get("name"), hostProp, oldtimestamp)
                return (ErrorCode.SUCCESS, ret)
            except:
                Utils.logError('upload db file error.')
        except:
            Utils.logError('Error when uploading db file.')

        return (ErrorCode.ERR_GENERAL, None)

    def QueryHGCconfig(self, sparam):

        if sparam == None:
            return (ErrorCode.ERR_INVALID_REQUEST, None)
        addr = sparam.get("addr", None)

        # 中控设备的虚拟设备类型
        v_type = sparam.get("v_type", None)
        cacheMD5 = sparam.get("md5", None)

        configs = DBManagerHGC().queryHGCconfigByType(addr, v_type)

        if (cacheMD5 != None):
            return self.returnByCheckMD5(cacheMD5, configs)
        else:
            return (ErrorCode.SUCCESS, configs)

    def deleteHGCconfig(self, sparam):
        if sparam == None:
            return (ErrorCode.ERR_INVALID_REQUEST, None)

        # 中控设备的虚拟设备类型
        v_type = sparam.get("v_type", None)
        HGCaddr = sparam.get("addr", None)
        channel = sparam.get("channel", None)
        # 设备地址（灯，插座等）
        # devAddr = sparam.get("devAddr", None)
        # if devAddr is not None:
        #     result = DBManagerHGC().deleteByDevAddr(devAddr)
        #     if result is True:
        #         return (ErrorCode.SUCCESS, None)
        #     return (ErrorCode.ERR_GENERAL, "删除失败！！")
        #
        # else:
        ret = DBManagerHGC().getHGCconfig(HGCaddr, v_type, channel)
        result = DBManagerHGC().deleteHGCconfig(HGCaddr, v_type, channel)
        if result is True:
            pub.sendMessage("syncHgcConfig", config=ret, isConfigured=0)
            return (ErrorCode.SUCCESS, None)
        return (ErrorCode.ERR_GENERAL, "删除失败！！")

    # app配置的payload
    # {'addr':'hhggcc001122','v_type':0x1,'channel':1, 'controls':[{'addr':'dst-mac1','type':'Light2',
    # 'value':{'state':'0','state1':'1'}},{'addr':'dst-mac2',...}]}
    def configHGC(self, sparam):
        if sparam == None:
            return (ErrorCode.ERR_INVALID_REQUEST, None)
        addr = sparam.get("addr", None)
        # 中控设备的虚拟设备类型
        v_type = sparam.get("v_type", None)
        channel = sparam.get("channel", None)
        controls = sparam.get("controls", None)
        if addr is None or v_type is None or channel is None or controls is None:
            Utils.logError('Err configHGC sparam:%s'%(sparam))
            return (ErrorCode.ERR_INVALID_PARAMS, None)

        (success, ret) = DBManagerHGC().saveHGCconfigs(sparam)
        if success == False:
            return (ErrorCode.ERR_GENERAL, ret)

        Utils.logInfo('publish PUB_CONTROL_DEVICE configDevice.')
        param={}
        param['type'] = 'hgc_config_success'
        param['addr'] = addr
        pub.sendMessage(GlobalVars.PUB_CONTROL_DEVICE, cmd="configDevice",controls=param)

        pub.sendMessage("syncHgcConfig", config=ret, isConfigured=1)

        # 首次配对到3.5寸中控，把名字同步过去
        try:
            if v_type == "0xF" or v_type == 0xF:
                modeId = controls[0].get("modeId")
                mode = DBManagerAction().getActionByModeId(modeId)
                mode_name = mode.get("tag")
                if mode_name is None or mode_name == "":
                    mode_name = mode.get("name", "")
                args = dict()
                args["hgc_addr"] = addr
                args["channel"] = channel
                args["v_type"] = v_type
                args["update"] = 0x01
                args["new_name"] = mode_name
                pub.sendMessage("syncHgcDevices", sparam=args)
            else:
                device_addr = controls[0].get("addr")
                device_detail_list = DBManagerDeviceProp().getDeviceByAddr(device_addr)
                device_name = device_detail_list[0].get("name", "")
                args = dict()
                args["hgc_addr"] = addr
                args["channel"] = channel
                args["v_type"] = v_type
                args["update"] = 0x01
                args["new_name"] = device_name
                pub.sendMessage("syncHgcDevices", sparam=args)
        except Exception, e:
            Utils.logError("sync name to hgc on hgc configured... %s" % e)

        return (ErrorCode.SUCCESS, None)

    def getDevAddr(self, macAddr):
        # if macAddr[0:2] == 'z-':
        #     return macAddr
        # return "z-" + macAddr
        return macAddr

    def zlibCompress(self, data):
        return data

    # 查询关联设备
    # {'srcaddr':'aabbcc', 'srctype':'Light3','srcchannel':'1','state':'1',
    # 'controls':[{'addr':'dst-mac1','type':'Light2','value':{'state':'0','state1':'1'}},{'addr':'dst-mac2',...}]}
    def querylinkDevices(self, sparam):
        if sparam == None:
            return (ErrorCode.ERR_INVALID_REQUEST, None)

        addr = sparam.get('addr', None)
        channel = sparam.get('channel', None)
        cacheMD5 = sparam.get("md5", None)
        ## 性能优化
        compress = sparam.get("compress", None)

        if addr == None or channel == None:
            links = DBManagerLinks().getAllDeviceLinks()
            ## 性能优化
            if compress is True and self.solib is not None:
                tmp = links.values()
                jsondump = json.dumps(tmp)
                en = self.zlibCompress(jsondump)
                return self.returnByCheckMD5(cacheMD5, {'linkDevices_compress':en})

            return self.returnByCheckMD5(cacheMD5, links.values())
        else:
            links = DBManagerLinks().getDeviceLinks(addr, channel)
            # return (ErrorCode.SUCCESS, links)
            # 性能优化
            if compress is True and self.solib is not None:
                tmp = links.values()
                jsondump = json.dumps(tmp)
                en = self.zlibCompress(jsondump)
                return self.returnByCheckMD5(cacheMD5, {'linkDevices_compress':en})

            return self.returnByTimestamp(sparam, links.values())

    # 用于过滤设备关联列表信息，在灯开关座关联时使用
    def _linkDeviceFilter(self, oldConfigList):
        resultList = []
        dbIdList = []

        for oldConfig in oldConfigList:
            dbIdTemp = oldConfig.get("dbId")
            if dbIdTemp not in dbIdList:
                resultList.append(oldConfig)
                dbIdList.append(dbIdTemp)
        return resultList

    # 关联设备
    # {'dbId':11,'controls':[{'addr':'dst-mac1','type':'Light2','channel':1},{'addr':'dst-mac2','type':'Light2',...}]}
    def linkDevices(self, sparam):
        if sparam == None:
            return (ErrorCode.ERR_INVALID_REQUEST, None)
        dbId = sparam.get("dbId", None)
        controls = sparam.get("controls", None)
        srcAddr = sparam.get("addr")

        oldConfig = DBManagerLinks().getDeviceLinksByDbId(dbId)  # oldConfig 是主设备的旧联动配置
        # Utils.logSuperDebug("device link oldConfig: {}".format(str(oldConfig)))
        if oldConfig == None:
            # new configuration
            if controls == None or 3 < len(controls) < 2:
                return (ErrorCode.ERR_INVALID_PARAMS, None)
            # 就处理方式如下：
            # for control in controls:
            #     addr = control.get("addr", None)
            #     if addr != None and addr != sparam.get("addr"):
            #         # 查询被关联设备的关联信息(如：灯A关联灯B，则查询灯B的关联信息)，如存在需要去除覆盖为新的
            #         oldConfigs_f = DBManagerLinks().getDeviceLinksByAddr(addr, srcAddr=srcAddr)  # oldConfigs_f是辅设备的旧联动配置
            #         break
            # Utils.logSuperDebug("oldConfigs_f is {}".format(str(oldConfigs_f)))
            # if oldConfigs_f != None and len(oldConfigs_f) != 0:
            #     # succ = DBManagerLinks().deleteByAddr(addr)
            #     # if succ is True:
            #     for oldConfig_f in oldConfigs_f:
            #         controls_f = oldConfig_f.get("controls")
            #         if controls_f == None or len(controls_f) < 2:
            #             return (ErrorCode.ERR_INVALID_PARAMS, None)
            #         oldConfig_f["controls"] = controls
            #         (success, ret) = DBManagerLinks().updateDeviceLinks(oldConfig_f.get('dbId', None), oldConfig_f)
            #         if success == True:
            #             self.sendLinkConfig2Device(controls_f, 0)  # 先把已有关联去除
            #             self.sendLinkConfig2Device(controls, 1)
            #             return (ErrorCode.SUCCESS, ret)
            #         else:
            #             return (ErrorCode.ERR_GENERAL, ret)
            # TODO 新需求的处理方式：
            oldConfigs_f_list = []
            for control in controls:
                addr = control.get("addr", None)
                if addr != None and addr != sparam.get("addr"):
                    # 查询被关联设备的关联信息(如：灯A关联灯B，则查询灯B的关联信息)，如存在需要去除覆盖为新的
                    oldConfigs_f = DBManagerLinks().getDeviceLinksByAddr(addr)  # oldConfigs_f是辅设备的旧联动配置
                    oldConfigs_f_list.extend(oldConfigs_f)

            oldConfigs_final = self._linkDeviceFilter(oldConfigs_f_list)  # 配置信息列表去重

            if oldConfigs_final != None and len(oldConfigs_final) != 0:
                # succ = DBManagerLinks().deleteByAddr(addr)
                # if succ is True:
                oldConfigToUpdate = None  # 需要更新的设备关联配置
                for oldConfig_f in oldConfigs_final:
                    controls_f = oldConfig_f.get("controls")
                    if controls_f == None or 3 < len(controls_f) < 2:
                        return (ErrorCode.ERR_INVALID_PARAMS, None)
                    # oldConfig_f["controls"] = controls
                    # (success, ret) = DBManagerLinks().updateDeviceLinks(oldConfig_f.get('dbId', None), oldConfig_f)
                    self.sendLinkConfig2Device(controls_f, 0)  # 先把已有关联去除
                    oldConfigToUpdate = oldConfig_f

                oldConfigToUpdate["controls"] = controls
                (success, ret) = DBManagerLinks().updateDeviceLinks(oldConfigToUpdate.get('dbId', None), oldConfigToUpdate)
                if success:
                    self.sendLinkConfig2Device(controls, 1)
                    return ErrorCode.SUCCESS, ret
                else:
                    return ErrorCode.ERR_GENERAL, ret

            else:
                (success, ret) = DBManagerLinks().saveDeviceLinks({'controls':controls})
                if success == True:
                    state = 1
                    self.sendLinkConfig2Device(controls, state)
                    return (ErrorCode.SUCCESS, ret)
                else:
                    return (ErrorCode.ERR_GENERAL, ret)
        else:
            # update.
            # 检查哪个设备解除关联了
            oldControls = oldConfig.get('controls', None)
            # 'controls':[{'addr':'dst-mac1','type':'Light2','channel':1},{'addr':'dst-mac2','type':'Light2',...}]
            if oldControls == None or len(oldControls) == 0:
                # 如果配置数据有误，返回错误
                if controls == None or 3 < len(controls) < 2:
                    return (ErrorCode.ERR_INVALID_PARAMS, None)

                oldConfig['controls'] = controls
                (success, ret) = DBManagerLinks().updateDeviceLinks(dbId, oldConfig)
                if success == True:
                    state = 1
                    self.sendLinkConfig2Device(controls, state)
                    return (ErrorCode.SUCCESS, ret)
                else:
                    return (ErrorCode.ERR_GENERAL, ret)
            else:
                # 'controls':[{'addr':'dst-mac1','type':'Light2','channel':1},{'addr':'dst-mac2','type':'Light2',...}]
                state = 0
                self.sendLinkConfig2Device(oldControls, state)

                if controls == None or len(controls) < 2:
                    # controls小于2时表示此时APP发送过来的配置信息里用户没有勾选设备了，不再关联2个设备了，所以删除当前记录并返回
                    success = DBManagerLinks().deleteByDbId(dbId)
                    if success == True:
                        return (ErrorCode.SUCCESS, None)
                    else:
                        return (ErrorCode.ERR_GENERAL, None)

                oldConfig['controls'] = controls
                (success, ret) = DBManagerLinks().updateDeviceLinks(dbId, oldConfig)
                if success == True:
                    state = 1
                    self.sendLinkConfig2Device(controls, state)
                    return (ErrorCode.SUCCESS, ret)
                else:
                    return (ErrorCode.ERR_GENERAL, ret)

        return (ErrorCode.SUCCESS, None)

    # 设备端删除关联 -- add by chenjc
    def removeLinkDevices(self, sparam, addr):
        if sparam == None:
            return (ErrorCode.ERR_INVALID_REQUEST, None)
        dbId = sparam.get("dbId", None)
        controls = sparam.get("controls", None)
        # controls: [{'addr':'dst-mac1','type':'Light2','channel':1},{'addr':'dst-mac2','type':'Light2',...}]
        if controls == None or len(controls) < 2:
            return (ErrorCode.ERR_INVALID_PARAMS, None)
        self.sendLinkConfig2Device(controls, state=0)  # 先把所有的关联去除
        # 在把删除的设备去掉之后将剩余的关联
        controls = [control for control in controls if control.get('addr') != addr]
        if len(controls) >= 2:  # 大于2条才关联，否则不再关联
            self.sendLinkConfig2Device(controls, state=1)

    def sendLinkConfig2Device(self, controls, state):
        if controls == None or len(controls) < 2:
            return
        srcaddr = controls[0].get('addr')
        srctype = controls[0].get('type')
        srcchannel = controls[0].get('channel')
        if srcaddr == None or srctype == None or srcchannel == None:
            return

        for index in range(1, len(controls)):
            configs = []
            item = controls[index]
            dstaddr = item.get('addr', None)
            dsttype = item.get('type', None)
            dstchannel = item.get('channel', None)
            if dstaddr == None or dsttype == None or dstchannel == None:
                continue

            cfg1 = {}
            cfg1['srcaddr'] = srcaddr
            cfg1['srctype'] = PacketParser.getDeviceTypeIdByName(srctype)
            cfg1['srcchannel'] = srcchannel
            cfg1['dstaddr'] = dstaddr
            cfg1['dsttype'] = PacketParser.getDeviceTypeIdByName(dsttype)
            cfg1['dstchannel'] = dstchannel
            cfg1['state'] = state
            configs.append(cfg1)

            cfg2 = {}
            cfg2['srcaddr'] = dstaddr
            cfg2['srctype'] = PacketParser.getDeviceTypeIdByName(dsttype)
            cfg2['srcchannel'] = dstchannel
            cfg2['dstaddr'] = srcaddr
            cfg2['dsttype'] = PacketParser.getDeviceTypeIdByName(srctype)
            cfg2['dstchannel'] = srcchannel
            cfg2['state'] = state
            configs.append(cfg2)

            Utils.logInfo('publish PUB_CONTROL_DEVICE configDevice.')
            param={}
            param['type'] = 'link_dev'
            param['configs'] = configs
            pub.sendMessage(GlobalVars.PUB_CONTROL_DEVICE, cmd="configDevice",controls=param)


    def activeRoomMode(self, sparam):

        if sparam == None:
            return (ErrorCode.ERR_INVALID_REQUEST, None)
        # roomId = sparam.get("roomId", None)
        # name = sparam.get("name", None)
        # if name == None:
        #     return (ErrorCode.ERR_INVALID_PARAMS, None)
        #
        # roomMode = DBManagerAction().getActionByName(name, roomId)
        modeId = sparam.get('modeId', None)
        if(modeId == None):
            return (ErrorCode.SUCCESS, None)

        roomMode = DBManagerAction().getActionByModeId(modeId)

        if roomMode == None:
            return (ErrorCode.SUCCESS, None)

        # 多用户同步显示当前的全局模式
        self.saveActivedGlobalMode(roomMode, modeId)
        devlist = roomMode.get("devicelist", None)
        devList = roomMode.get("deviceList", None)

        if devlist is None and devList is not None:
            devlist = devList

        if devlist is None:
            return ErrorCode.SUCCESS, None

        # 根据房间模式配置先后顺序
        if roomMode.get("roomId") == "global" and roomMode.get("name", "") == "回家模式配置":
            # 全局模式-回家模式
            roomInfoDict = DBManagerRoom().getRoomTypeIdDict()
            if roomInfoDict != None:
                devlisttemp = []
                dev_list_remain = []
                for dev in devlist:
                    if roomInfoDict.get(dev.get("roomId")) == u"\u5ba2\u5385" \
                            or roomInfoDict.get(dev.get("roomId")) == "客厅":
                        devlisttemp.append(dev)
                # sorted(devlisttemp, cmp=lambda x, y : cmp(x.get("areaid"), y.get("areaid"))) # 根据区域ID排序
                dev_list_remain = [device for device in devlist if device not in devlisttemp] # 取差集，用户拼成完整的devlist
                devlisttemp.extend(dev_list_remain)   # 重新将差集中的内容拼如devlist
                devlist = devlisttemp

        if roomMode.get("roomId") == "global" and roomMode.get("name", "") == "离家模式配置":
            # 全局模式-离家模式
            roomInfoDict = DBManagerRoom().getRoomTypeIdDict()
            if roomInfoDict != None:
                devlisttemp = []
                dev_list_remain = []
                for dev in devlist:
                    if roomInfoDict.get(dev.get("roomId")) == u"\u5ba2\u5385" \
                            or roomInfoDict.get(dev.get("roomId")) == "客厅":
                        devlisttemp.append(dev)
                # sorted(devlisttemp, cmp=lambda x, y: cmp(x.get("areaid"), y.get("areaid")))  # 根据区域ID排序
                dev_list_remain = [device for device in devlist if device not in devlisttemp]  # 取差集，用户拼成完整的devlist
                dev_list_remain.extend(devlisttemp)  # 重新将差集中的内容拼如devlist
                devlist = dev_list_remain
        # {u'devicelist':
        # [
        # {u'devicename': u'\u706f', u'areaid': u'1', u'deviceAddr': u'', u'roomname': u'\u65b0\u623f\u95f4',
        # u'devicetype': u'Light1', u'deviceid': u'2', u'params': {u'state': u'0'},
        # u'roomid': u'1', u'areaname': u'\u65b0\u533a\u57df'},
        # {u'devicename': u'\u4e8c\u8054\u706f', u'areaid': u'1', u'deviceAddr': u'',
        # u'roomname': u'\u65b0\u623f\u95f4', u'devicetype': u'Light2', u'deviceid': u'4',
        # u'params': {u'state2': u'0', u'state': u'0'}, u'roomid': u'1', u'areaname': u'\u65b0\u533a\u57df'}
        # ],
        #  u'timestamp': 1429923858, u'name': u'\u79bb\u5bb6\u6a21\u5f0f\u914d\u7f6e'}
        try:
            ketra_devices = []
            for devItem in devlist:
                # 下面是要控制的设备
                actDevAddrTemp = devItem['deviceAddr']
                if(actDevAddrTemp == ""):
                    continue
                else:
                    actDevAddrTemp = self.getDevAddr(actDevAddrTemp)

                devtype = devItem.get("devicetype", "")
                devName = devItem.get("devicename", "")
                params = devItem.get("params", {})

                # 红外设备根据设备名和设备地址查询，其他设备根据设备类型和地址查询
                # 因为同一个红外转发设备可以同时接入电视和空调，不能直接根据设备地址查询
                if devtype in [DEVTYPENAME_TV, DEVTYPENAME_AIRCONDITION, DEVTYPENAME_DVD]:
                    (devId, tmpDevice) = DBManagerDeviceProp().getDeviceByAddrName(actDevAddrTemp, devName)
                else:
                    tmpDevice = DBManagerDeviceProp().getDeviceByDevAddrAndType(actDevAddrTemp, devtype)

                if tmpDevice is None:
                    continue

                # dismiss = tmpDevice.get('dismiss', False)  # delos允许设备不绑定到房间，所以解绑设备也需要触发
                # if dismiss is True:
                #     continue

                if devtype == 'LightAdjust':
                    # 将按时时间字段加入控制命令参数
                    lightingTime = tmpDevice.get("lightingTime", "0")
                    params['lightingTime'] = lightingTime

                if devtype == 'Curtain':
                    s = int(params.get('state', 0))
                    if s == 0:
                        params['state'] = '2'

                if devtype == 'Audio':
                    # u'params': {1: u'on', '2':'off', '3':'on'}
                    brand = devItem.get("brand", None)
                    if brand is None or brand == "Backaudio":
                        thread.start_new_thread(UtilsCommandHandlerBosheng().activeMode, (params,))
                        continue
                    elif brand == "Hope":
                        # 向往背景音乐
                        state = params.get("state", None)  # 模式内要设定的状态
                        dev_value = tmpDevice.get("value", None)
                        thread.start_new_thread(hopeMusicActivateMode, (state, dev_value))
                        continue

                        # if dev_value is None:
                        #     Utils.logError("Hope cloud account: dev_value is None")
                        #     continue
                        # mobile_no = dev_value.get("mobile", None)
                        # device_id = dev_value.get("deviceId", None)
                        # song_index = dev_value.get("Index", 0)
                        # volume = 5
                        #
                        # if mobile_no is None or device_id is None:
                        #     Utils.logError("Hope cloud account: mobile no or device_id is None")
                        #     continue
                        #
                        # server_time = get_server_time()
                        # rtn_dict = verify_external_user(server_time, mobile_no)
                        # if rtn_dict is None:
                        #     Utils.logError("Hope cloud account: User login failed")
                        #     continue
                        # data = rtn_dict.get("Data")
                        # if data is not None:
                        #     hope_token = data.get("Token", None)
                        #     if hope_token is not None:
                        #         state_dict = init_state(device_id, hope_token)
                        #         if state_dict:
                        #             curr_index = state_dict.get("Data").get("Index")
                        #             curr_state = state_dict.get("Data").get("State")  # 2是播放；1是暂停
                        #             if curr_state and curr_index:
                        #                 if int(state) == 1 and curr_state == 2:  # 命令是打开并且当前正在播放
                        #                     if int(curr_index) == int(song_index):
                        #                         continue  # 当前播放曲目就是模式中设定的曲目不在重复发送
                        #                 elif int(state) == 1 and curr_state == 1:
                        #                     music_play_ex(hope_token, device_id, song_index)
                        #                     music_volume_set(volume, device_id, hope_token)
                        #                 else:  # 模式中配置的是暂停音乐
                        #                     if int(curr_state) == 1:
                        #                         continue
                        #                     else:
                        #                         state_dict = init_state(device_id, hope_token)
                        #                         curr_index = state_dict.get("Data").get("Index")
                        #                         music_play_ex(hope_token, device_id, curr_index)  # 暂停
                        # else:
                        #     Utils.logError("Hope cloud account: login data error")
                        #     continue

                    elif brand in ["Levoice", "Wise485"]:
                        # 音丽士背景音乐和485方式接入的华尔斯
                        state = params.get("state", None)
                        if state is not None:
                            if int(state) == 1:
                                # 打开
                                # device_status_obj = DBManagerDeviceProp().getDeviceByAddr(actDevAddrTemp)[0]
                                # curr_song = device_status_obj.get("setSong", "0")
                                # volume = device_status_obj.get("setVolume", "30")

                                # 判断是哪种方式配置的背景音乐，兼容老版本
                                songDict = tmpDevice.get("songDict", None)
                                if songDict:
                                    modekey = "mode_{}".format(str(modeId))
                                    mode_bgm_cfg = songDict.get(modekey, {})
                                    curr_song = mode_bgm_cfg.get("setSong", "0")
                                    volume = mode_bgm_cfg.get("setVolume", "5")
                                else:
                                    curr_song = tmpDevice.get("setSong", "0")
                                    volume = tmpDevice.get("setVolume", "5")

                                maxVol = int(params.get('maxVol', 0))
                                period = 0
                                if maxVol:
                                    volume = int(params.get('volume', 5))
                                    period = int(params.get('period', 1))
                                    if maxVol < volume:  # 设置得最大音量小于起始音量时，默认将最大音量设置成比起始音量大5
                                        maxVol = volume + 5
                                    if maxVol > 15:  # 最大音量大于设备音量范围时赋值为设备音量上限值
                                        maxVol = 15

                                elif volume == "0":  # 未设置最大音量时表示是直接播放，此时音量为0时给一个默认音量5
                                    volume = "5"

                                params = {"state": "1", "brand": brand, "cmd": "5", "data": curr_song, "dataLen": "5",
                                          "volume": volume, "maxVol": maxVol, "period": period}
                            else:
                                # 关闭
                                params = {"state": "0", "brand": brand, "cmd": "1", "data": "0", "dataLen": "1"}
                    elif brand == 'Wise':
                        # 华尔斯背景音乐
                        state = params.get("state", None)
                        if state is not None:
                            ctl_value = tmpDevice.get("value", None)
                            if ctl_value is not None:
                                curr_song = ctl_value.get("Index", "0")
                                volume = ctl_value.get("volume", "6")
                            else:
                                curr_song = '0'
                                volume = '6'

                            if int(volume) == 0:
                                volume = "6"
                            try:
                                if int(state) == 1:
                                    ctl_value = tmpDevice.get("value", None)
                                    songDict = tmpDevice.get("songDict", None)

                                    # 判断是哪种方式配置的背景音乐，兼容老版本
                                    if songDict:
                                        modekey = "mode_{}".format(str(modeId))
                                        mode_bgm_cfg = songDict.get(modekey, {})
                                        curr_song = mode_bgm_cfg.get("setSong", "0")
                                        volume = mode_bgm_cfg.get("setVolume", "6")
                                    elif ctl_value is not None:
                                        curr_song = ctl_value.get("Index", "0")
                                        volume = ctl_value.get("volume", "6")
                                    else:
                                        curr_song = '0'
                                        volume = '6'

                                    if int(volume) == 0:
                                        volume = "6"

                                    # play_pos(int(curr_song))
                                    # set_volume(int(volume))
                                    thread.start_new_thread(play_and_set_vol, (int(curr_song), int(volume)))
                                else:
                                    # sock, model_type, address, playState = play_status(no_return_sock=False)
                                    # if int(playState) == 1:
                                    #     play_and_pause(sock, model_type, address)
                                    thread.start_new_thread(pause_in_mode, (False, ))
                            except:
                                Utils.logError("Room mode control Wise music failed...continue")
                        continue

                if devtype == 'AirSystem':  # 新风系统
                    state = params.get("state")
                    if int(state) == 1:
                        cmd = params.get("cmd", "2")  # 默认自动模式
                    else:
                        cmd = params.get("cmd", "1")  # state为0时，默认执行关闭操作
                    data = params.get("data", "0")
                    params = {"cmd": cmd, "data": data}

                if devtype == "FloorHeating":  # 485接入的地暖，非3.5寸屏接入
                    state = params.get("state")
                    cmd = params.get("cmd", 1)
                    if int(state) == 1:
                        data = params.get("data", 1)
                    else:
                        data = params.get("data", 0)
                    params = {"cmd": cmd, "data": data}

                if devtype == "AirFilter":  # 空气过滤器
                    state = params.get("state")
                    if int(state) == 1:
                        params = {"cmd": 2, "data": 254, "speed": 0, "dataLen": 1}
                    else:
                        params = {"cmd": 2, "data": 255, "speed": 0, "dataLen": 1}

                if devtype == "CircadianLight":
                    # 要先上电之后再触发Ketra节律灯
                    ketra_devices.append(params)
                    continue

                if devtype == 'ScrOperator':  # 发送屏幕控制器命令
                    Utils.logDebug('ScrOperator param is: %s' % str(devItem))
                    state = params.get('state', None)
                    state2 = params.get('state2', None)
                    if str(state) == '1':
                        Utils.screen_operator('dplay#')
                    elif str(state) == '0':
                        Utils.screen_operator('dstop#')
                        Utils.screen_operator('xstop#')

                    if str(state2) == '1':
                        Utils.screen_operator('xplay#')
                    elif str(state2) == '0':
                        Utils.screen_operator('xstop#')
                    continue

                # 模式触发时，如果有空调打开指令，从设备属性表中获取最新的空调配置，达到打开是上次操作的结果
                airState = None
                airControlValue = None # 空调的控制参数
                isOn = None# 空调是否已经打开
                if devtype == 'AirCondition':
                    airState = params.get("state")
                    airAddr = devItem.get("deviceAddr")
                    devDetail = DBManagerDeviceProp().getDeviceByAddrType(str(airAddr), "AirCondition")[1]
                    acData = devDetail.get("AcData")
                    airControlValue = devDetail.get("remoteInfo", None)
                    m_key_sequence = airControlValue.get("m_key_squency")
                    index = 1
                    if airState == "1":
                        if m_key_sequence == "15000":
                            if acData != None:
                                index = 0 * 7500 + int(acData.get("cMode")) * 1500 + int(acData.get("cTemp")) * 100 + \
                                        int(acData.get("cWind")) * 25 + int(acData.get("cWinddir")) * 5 + int(
                                    acData.get("cKey")) + 1
                            else:  # 空调配置后没有在APP上控制过，acData为空
                                index = 0 * 7500 + 0 * 1500 + 9 * 100 + 0 * 25 + 0 * 5 + 0 + 1
                        elif m_key_sequence == "3000":
                            if acData != None:
                                index = 0 * 1500 + int(acData.get("cMode")) * 300 + int(acData.get("cTemp")) * 20 + \
                                        int(acData.get("cWind")) * 5 + int(acData.get("cWinddir")) + 1
                            else:
                                index = 0 * 1500 + 0 * 300 + 9 * 20 + 0 * 5 + 0 * 5 + 1
                    else:
                        if m_key_sequence == "15000":
                            if acData != None:
                                index = 1 * 7500 + int(acData.get("cMode")) * 1500 + int(acData.get("cTemp")) * 100 + \
                                        int(acData.get("cWind")) * 25 + int(acData.get("cWinddir")) * 5 + int(
                                    acData.get("cKey")) + 1
                            else:  # 空调配置后没有在APP上控制过，acData为空
                                index = 1 * 7500 + 0 * 1500 + 9 * 100 + 0 * 25 + 0 * 5 + 0 + 1
                        elif m_key_sequence == "3000":
                            if acData != None:
                                index = 1 * 1500 + int(acData.get("cMode")) * 300 + int(acData.get("cTemp")) * 20 + \
                                        int(acData.get("cWind")) * 5 + int(acData.get("cWinddir")) + 1
                            else:
                                index = 1 * 1500 + 0 * 300 + 9 * 20 + 0 * 5 + 0 * 5 + 1
                    airControlValue["index"] = index
                    if acData is not None:
                        if airState == "1":
                            acData["isOn"] = "1"
                            acData["cOnoff"] = "0"
                        else:
                            acData["isOn"] = "2"
                            acData["cOnoff"] = "1"
                        devDetail["AcData"] = acData
                        devDetail["remoteInfo"] = airControlValue
                        DBManagerDeviceProp().saveDeviceProperty(devDetail) # 保存模式触发的空调状态

                if DEVTYNAME_CENTRAL_AIRCONDITION == devtype:  # 中央空调
                    state = int(params.get("state", 0))
                    protocal = int(tmpDevice.get("protocol", 1))
                    if state == 1:
                        # 打开中央空调
                        params = {"controlCmd": 2, "protocol": protocal, "addr": actDevAddrTemp,
                                  "controlDeviceType": 0x50, "controlData": 1, "length": 2}

                    else:
                        # 关闭中央空调
                        params = {"controlCmd": 2, "protocol": protocal, "addr": actDevAddrTemp,
                                  "controlDeviceType": 0x50, "controlData": 0, "length": 2}

                # for i in range(1, 5):
                #     stateStr = ""
                #     if(i == 1):
                #         stateStr = "state"
                #     else:
                #         stateStr = "state" + bytes(i)
                #     stateValue = params.get(stateStr,None)
                #     if(stateValue is None):
                #         continue
                devicesToCtrol = []
                device_addr_list = []

                # 20151009: multi-channel in one message
                # devToCtrol = {"name":devName,"addr":actDevAddrTemp,"value":params,"type":devtype}
                # devicesToCtrol.append(devToCtrol)
                # Utils.logDebug("publish PUB_CONTROL_DEVICE controlDevice :%s"%(devicesToCtrol))
                # del tempState

                if devtype not in ["Audio", "AirSystem", "FloorHeating", "AirFilter", DEVTYPENAME_LIGHTAJUST, DEVTYNAME_CENTRAL_AIRCONDITION]: # TODO 待测试，模式联动中是否按照该方式过滤空气净化器
                    delay = params.get('delay', 0)
                    key_list = sorted(params.keys())
                    for key in key_list:
                        if 'set' not in key and 'state' not in key and 'coeff' not in key and 'key' not in key and 'value' not in key:
                            continue
                        singleValue = {}
                        if key == 'value':
                            # singleValue = params.get(key)
                            # 模式触发时，如果有空调打开指令，从设备属性表中获取最新的空调配置，达到打开是上次操作的结果
                            if devtype == "AirCondition" and airState == "1":
                                singleValue = airControlValue
                            else:
                                singleValue = params.get(key)
                            # TODO 检查extraCmd是否正确
                            devToCtrol = {"name":devName,"addr":actDevAddrTemp,"value":singleValue,"type":devtype, "extraCmd": "newInfrared"}
                        else:
                            v = params.get(key)
                            singleValue[key] = v
                            # 灯光加个延时
                            if devtype in [DEVTYPENAME_LIGHT1, DEVTYPENAME_LIGHT2, DEVTYPENAME_LIGHT3,
                                           DEVTYPENAME_LIGHT4]:
                                singleValue['delay'] = delay
                            devToCtrol = {"name":devName,"addr":actDevAddrTemp,"value":singleValue,"type":devtype}

                        # if devtype == DEVTYPENAME_LIGHTAJUST:  # 过滤掉调光灯亮度参数的一条命令，原来亮度参数也会单独发一个控制命令出去
                        #     if actDevAddrTemp not in device_addr_list:
                        #         device_addr_list.append(actDevAddrTemp)
                        #         devicesToCtrol.append(devToCtrol)
                        # else:
                        #     devicesToCtrol.append(devToCtrol)
                        devicesToCtrol.append(devToCtrol)
                        Utils.logDebug("publish PUB_CONTROL_DEVICE controlDevice :%s"%(devicesToCtrol))

                    # del tempState
                else:
                    devToCtrol = {"name": devName, "addr": actDevAddrTemp, "value": params, "type": devtype}
                    devicesToCtrol.append(devToCtrol)

                pub.sendMessage(GlobalVars.PUB_CONTROL_DEVICE, cmd="controlDevice", controls=devicesToCtrol)
                del devicesToCtrol
            # activate Ketra devices
            if ketra_devices:
                # time.sleep(0.7)
                pub.sendMessage("control_ketra_lights", controls=ketra_devices)
                # for ketra_param in ketra_devices:
                #     Utils.logDebug("avtivate mode, params: %s" % str(ketra_param))
                #     n4SerialNo = ketra_param.get("n4SerialNo")  # N4 序列号
                #     buttonName = ketra_param.get("buttonName")  # X2 按键名
                #     keypadName = ketra_param.get("keypadName")  # X2 面板名
                #     KetraUtils.activateButton(n4SerialNo, keypadName, buttonName)  # activate Ketra X2
        except:
            Utils.logException('Error when active room mode....')

        # 激活场景模式后，如果该模式配置在中控面板上，需要同步
        v_type = 0xF
        devices_hgc = DBManagerHGC().getByVtype(v_type)
        if devices_hgc is not None and len(devices_hgc) > 0:
            for item in devices_hgc:
                mode_hgc = item.get("controls")[0].get("modeId")
                if str(mode_hgc) == str(modeId):
                    sparams = {}
                    sparams["hgc_addr"] = item.get("addr")
                    sparams["channel"] = item.get("channel")
                    sparams["v_type"] = item.get("v_type")
                    sparams["update"] = 0x00
                    value = {}
                    value["modeId"] = modeId
                    sparams["value"] = value
                    pub.sendMessage("syncHgcDevices", sparam=sparams)

        pub.sendMessage("cancelAlarm")

        return (ErrorCode.SUCCESS, None)

    # 如果切换成撤防模式，需要告知云端，可能需要撤销告警推送
    def cancel_alarm(self, alarm_type=u'\u975e\u6cd5\u5165\u4fb5'):
        modeId = self.activedMode
        if modeId == 5 or modeId == '5':  # 在中控面板上点击撤防，传过来的modeId是一个String
            metaDict = dict()
            metaDict["type"] = "cancelAlarm"
            value = {'type': alarm_type, 'currentMode': 'disarmed', 'modeId': '5'}
            metaDict["valueStr"] = value

            # 如果撤防模式中未配置存在传感器，while True会陷入死循环，所以先要查询撤防模式中是否配置了存在传感器
            has_exist = False
            disarmed_mode = DBManagerAction().getActionByModeId(int(modeId))
            if disarmed_mode is not None and len(disarmed_mode) > 0:
                devices_list = disarmed_mode.get("devicelist")
                if devices_list is not None and len(devices_list) > 0:
                    for item in devices_list:
                        if item.get("devicetype") == "Exist":
                            has_exist = True

            if has_exist is True:
                while True:
                    exist_sensor = DBManagerDevice().getDeviceByDevType("Exist")
                    value = exist_sensor[0].get("value", None)
                    state = value.get("state", None)
                    set = value.get("set", None)
                    if value is not None and state == 0 and set == 0:
                        alarm = DBManagerAlarm().checkDBHealthy()
                        if alarm is None:
                            pub.sendMessage(GlobalVars.PUB_SEND_RTDATA, rtdata=metaDict, arg2=None)
                            return True
                    else:
                        continue
            else:
                return False
        else:
            return False

    def saveActivedGlobalMode(self, roomMode, modeId):
        if roomMode is None:
            return

        name = roomMode.get('name', None)
        Utils.logInfo('#######saveActivedGlobalMode, name=%s'%(name))
        if not name:
            return

        if '回家模式' in name \
                or '离家模式' in name \
                or '会客模式' in name\
                or '就餐模式' in name\
                or '撤防模式' in name\
                or '布防模式' in name:
            self.activedMode = modeId
    
    def queryRoomMode(self, params):
        if params == None:
            return (ErrorCode.ERR_INVALID_REQUEST, None)
        
        jsonobj = params
        roomId = jsonobj.get("roomId", None)
        name = jsonobj.get("name", None)
        modeId = jsonobj.get("modeId", None)
        cacheMD5 = jsonobj.get("md5", None)
        # 性能优化
        compress = jsonobj.get("compress", None)

        Utils.logDebug("->queryRoomMode() %s"%(params))
        mode = None
        if modeId:
            modeInDb = DBManagerAction().getActionByModeId(modeId)
            mode = self.validateMode(modeInDb)

        elif name:
            modeInDb = DBManagerAction().getActionByName(name, roomId)
            mode = self.validateMode(modeInDb)

        else:
            mode = []
            modes = DBManagerAction().getActionByRoom(roomId)
            for modeItemInDb in modes:
                tmp = self.validateMode(modeItemInDb)
                mode.append(tmp)

        # if name == None:
        #     mode=[]
        #     modes = DBManagerAction().getActionByRoom(roomId)
        #     for modeItemInDb in modes:
        #         tmp = self.validateMode(modeItemInDb)
        #         mode.append(tmp)
        # else:
        #     modeInDb = DBManagerAction().getActionByName(name, roomId)
        #     mode = self.validateMode(modeInDb)

        # 性能优化
        if compress is True and self.solib is not None:
            mode2str = json.dumps(mode)
            en = self.zlibCompress(mode2str)
            mode = {'mode_compress':en}

        if (cacheMD5 != None):
            ret, mode_dict = self.returnByCheckMD5(cacheMD5, mode)
        else:
            ret, mode_dict = self.returnByTimestamp(params, mode)

        if mode_dict and isinstance(mode_dict, dict):
            time_task = DBManagerTask().get_by_name(mode_dict.get("modeId", "0"))
            if time_task and mode_dict:
                mode_dict["timeTask"] = time_task
        elif mode_dict and isinstance(mode_dict, list):
            for mode in mode_dict:
                time_task = DBManagerTask().get_by_name(mode.get("modeId", "0"))
                if time_task:
                    mode["timeTask"] = time_task

        return ret, mode_dict
    
    def validateMode(self, mode):
        # 更新模式中设备属性
        # [{"devicename": "\u5355\u8054\u706f",
        # "areaid": "1", "deviceAddr": "4DEA5A02004B12000000", "roomname": "\u4e3b\u5367",
        # "devicetype": "Light1", "deviceid": "2", "params": {"state": "0"},
        # "roomId": "2", "areaname": ""}]
        if mode == None:
            mode = {}
        try:
            newdevicelist=[]
            devicelist = mode.get('devicelist', None)
            if devicelist is None:
                devicelist = mode.get('deviceList', None)
            if devicelist != None:
                for item in devicelist:
                    deviceAddr = item.get('deviceAddr', None)
                    devicename = item.get('devicename', None)
                    roomname = item.get('roomname', '')
                    deviceArr = DBManagerDeviceProp().getDeviceByAddr(deviceAddr)
                    if len(deviceArr) == 0:
                        continue
                    # 找出addr 和 name一致的设备属性
                    tmp = None
                    if len(deviceArr) == 1:
                        tmp = deviceArr[0]
                    else:
                        # 红外伴侣，一个mac对应多个设备，以name区分
                        for tmpDevice in deviceArr:
                            tmpDeviceName = tmpDevice.get('name', None)
                            if devicename == tmpDeviceName:
                                tmp = tmpDevice
                                break
                    if tmp is None:
                        # 原来配置的设备不存在了，或者红外伴侣改名了
                        continue
                    # if tmp.get('dismiss', False) is True:
                    #     continue

                    devicename = tmp.get('name', None)
                    if not roomname:
                        roomname = tmp.get('roomname', '')
                    item['devicename'] = devicename
                    item['roomId'] = tmp.get('roomId', None)

                    if tmp.get("lightName") is not None:
                        item["lightName"] = tmp.get("lightName")

                    # roomProp = DBManagerRoom().getRoomByRoomId(tmp.get('roomId', None))  # delos中允许设备不绑定到房间
                    # if roomProp is None:
                    #     continue
                    item['roomname'] = roomname

                    # item['areaid'] = tmp.get('areaId', '0')
                    # item['areaname'] = '新区域'
                    # areas = roomProp.get('areas', [])
                    # for area in areas:
                    #     tmpareaId = area.get('areaId', None)
                    #     if tmpareaId == tmp.get('areaId', '0'):
                    #         item['areaname'] = area.get('name', '')
                    #         break
                    newdevicelist.append(item)

            mode['devicelist'] = newdevicelist
            mode['deviceList'] = newdevicelist
        except:
            pass
        return mode

    def validateLinkAction(self, action):
        if action is None:
            action = {}

        alarmAct = action.get('alarmAct', None)
        if alarmAct is None:
            return action
        actList = alarmAct.get('actList', None)
        if actList is None:
            return action

        try:
            newactList=[]
            for item in actList:
                deviceAddr = item.get('deviceAddr', None)
                devicename = item.get('devicename', None)
                deviceArr = DBManagerDeviceProp().getDeviceByAddr(deviceAddr)
                if len(deviceArr) == 0:
                    continue
                # 找出addr 和 name一致的设备属性
                tmp = None
                if len(deviceArr) == 1:
                    tmp = deviceArr[0]
                else:
                    # 红外伴侣，一个mac对应多个设备，以name区分
                    for tmpDevice in deviceArr:
                        tmpDeviceName = tmpDevice.get('name', None)
                        if devicename == tmpDeviceName:
                            tmp = tmpDevice
                            break
                if tmp is None:
                    # 原来配置的设备不存在了，或者红外伴侣改名了
                    continue
                # if tmp.get('dismiss', False) is True:  # delos内设备可以不用绑定到某个房间内
                #     continue

                devicename = tmp.get('name', None)
                item['devicename'] = devicename
                item['roomId'] = tmp.get('roomId', None)

                roomProp = DBManagerRoom().getRoomByRoomId(tmp.get('roomId', None))
                if roomProp is None:
                    item['roomname'] = ""
                    item['areaid'] = ""
                else:
                    item['roomname'] = roomProp.get('name', None)
                    item['areaid'] = tmp.get('areaId', '0')
                    areas = roomProp.get('areas', [])
                    for area in areas:
                        tmpareaId = area.get('areaId', None)
                        if tmpareaId == tmp.get('areaId', '0'):
                            item['areaname'] = area.get('name', '')
                            break

                newactList.append(item)

            alarmAct['actList'] = newactList
        except:
            pass
        return action

    def queryExistLinkAction(self, params):
        if not params:
            return ErrorCode.ERR_INVALID_PARAMS, None

        addr = params.get("addr", None)
        if not addr:
            return ErrorCode.ERR_INVALID_PARAMS, None
        addr_recover = str(addr) + "_recover"
        success_code, alarm_act = self.queryLinkActions(params)
        alarm_recover = DBManagerAction().getActionByDevId(addr_recover)
        if alarm_recover:
            # if "devicelist" in alarm_recover.keys():
            #     alarm_recover.pop("devicelist")
            alarm_recover = self.validateMode(alarm_recover)
        if alarm_act and alarm_recover:
            alarm_act["alarmRecover"] = alarm_recover
            return ErrorCode.SUCCESS, alarm_act
        elif not alarm_act and alarm_recover:
            result = dict(alarmRecover=alarm_recover)
            return ErrorCode.SUCCESS, result
        elif alarm_act and not alarm_recover:
            alarm_act["alarmRecover"] = {}
            return ErrorCode.SUCCESS, alarm_act
        else:
            return ErrorCode.SUCCESS, {}

    def queryLinkActions(self, params):
        Utils.logDebug("->queryLinkActions()")
        addr = params.get('addr', None)
        # 性能优化
        compress = params.get('compress', None)
        if addr == None:
            # TO BE DEPRECATED!!

            mode=[]
            actions = DBManagerAction().getAllLinkAction()
            for actionInDb in actions:
                tmp = self.validateLinkAction(actionInDb)
                mode.append(tmp)

            # 性能优化
            if compress is True and self.solib is not None:
                jsondump = json.dumps(mode)
                en = self.zlibCompress(jsondump)
                return self.returnByTimestamp(params, {"linkaction_compress":en})

            return self.returnByTimestamp(params, mode)
        else:
            action = DBManagerAction().getActionByDevId(addr)
            tmp = self.validateLinkAction(action)

            # 性能优化
            if compress is True and self.solib is not None:
                jsondump = json.dumps(tmp)
                en = self.zlibCompress(jsondump)
                return self.returnByTimestamp(params, {"linkaction_compress":en})

            return self.returnByTimestamp(params, tmp)
        # return (ErrorCode.SUCCESS, actions)


    def updateRoomMode(self, sparam):
        if sparam is None:
            return (ErrorCode.ERR_INVALID_REQUEST, None)
        Utils.logDebug("->updateRoomMode() %s"%(sparam))

        roommode = sparam.get("mode", None)
        devicelist = roommode.get("devicelist", None)
        deviceList = roommode.get("deviceList", None)
        updateTask = roommode.get("updateTask", None)  # 是否需要更新定时任务，1-更新，0-不更新
        if deviceList is not None and devicelist is not None:  # 将deviceList设置成与devicelist相同,20170222
            roommode["deviceList"] = devicelist
        if devicelist is None and deviceList is not None:  # APP请求参数中只有deviceList时将deviceList赋值给devicelist
            roommode["devicelist"] = deviceList

        if roommode is None:
            return (ErrorCode.ERR_INVALID_PARAMS, None)

        roommode = self.updateExistSensorPrior(roommode)

        if "updateTask" in roommode:  # 创建开门模式时出现 KeyError，原因是构建开门模式时APP没有上送这个字段
            del roommode["updateTask"]  # 将参数中的 updateTask 标记去掉
        ret = DBManagerAction().saveModeAction(roommode)
        if ret is not None:
            if updateTask == "1":  # 需要更新定时任务
                Utils.logDebug("Begin to update time task......")
                taskObj = roommode.get("timeTask", None)
                if taskObj:
                    taskId = taskObj.get("id", None)
                    mode_id = taskObj.get("modeId", None)
                    if mode_id is None:
                        # 如果modeId是空的，通过模式名查询到modeId，这里是为了兼容之前有Bug是添加的定时任务内没有modeId的情况
                        mode_name = roommode.get('name')
                        modeinfo = DBManagerAction().getByName(mode_name)
                        mode_id = modeinfo.get('modeId')
                        taskObj['modeId'] = mode_id

                    if taskId:
                        # 有ID，则是更新任务
                        switch = taskObj.get("switch")
                        switchObj = {"id": taskId, "modeId": mode_id, "switch": switch}
                        self.switch_time_task(switchObj, task=taskObj)
                    else:
                        # 无ID，则是新建任务
                        self.set_time_task(taskObj)

            # 把模式配置里的所有设备属性，增加"linkaction":[{"modeId":"2"}]
            self.backupToClould("linkaction", ret)
            return (ErrorCode.SUCCESS, ret)
        else:
            return (ErrorCode.ERR_GENERAL, None)

    def updateExistSensorPrior(self, mode):
        # 模式配置中，涉及‘存在传感器’的处理逻辑
        # 1. 如果是布防，则在其他配置之后布防
        # 2. 如果是撤防，则在其他配置之前撤防
        # 避免其他配置影响存在传感器
        if mode is None:
            mode = {}

        try:
            newdevicelist=[]
            existSensorOn=[]
            existSensorOff=[]
            devicelist = mode.get('devicelist', None)
            if devicelist is not None:
                for item in devicelist:
                    devicetype = item.get('devicetype', None)
                    if devicetype in ["Exist", "Gsm", "CurtainSensor"]:
                        params = item.get('params', {})
                        on = params.get('set', None)
                        if on == '1':
                            existSensorOn.append(item)
                        else:
                            existSensorOff.append(item)

                    else:
                        newdevicelist.append(item)
                existSensorOff.extend(newdevicelist)
                existSensorOff.extend(existSensorOn)
                mode['devicelist'] = existSensorOff
        except:
            pass
        return mode
    
    def updateLinkAction(self, sparam):
        if sparam is None:
            return (ErrorCode.ERR_INVALID_REQUEST, None)
        plan = sparam.get("mode", None)
        if plan is None:
            return (ErrorCode.ERR_INVALID_PARAMS, None)

        plan = self.updateExistSensorPriorInLinkAction(plan)

        ret = DBManagerAction().saveLinkAction(plan)
        if ret is not None:
            ## 把告警联动配置里的所有设备，增加"linkaction":[{"modeId":"2"}]

            self.backupToClould("linkaction", ret)
            return (ErrorCode.SUCCESS, ret)
        else:
            return (ErrorCode.ERR_GENERAL, None)

    def updateExistSensorPriorInLinkAction(self, action):
        # 模式配置中，涉及‘存在传感器’的处理逻辑
        # 1. 如果是布防，则在其他配置之后布防
        # 2. 如果是撤防，则在其他配置之前撤防
        # 避免其他配置影响存在传感器
        if action is None:
            action = {}

        alarmAct = action.get('alarmAct', None)
        if alarmAct is None:
            return action
        actList = alarmAct.get('actList', None)
        if actList is None:
            return action

        try:
            newdevicelist=[]
            existSensorOn=[]
            existSensorOff=[]

            for item in actList:
                devicetype = item.get('devicetype', None)
                if devicetype in ["Exist", "Gsm", "CurtainSensor"]:
                    params = item.get('params', {})
                    on = params.get('set', None)
                    if on == '1':
                        existSensorOn.append(item)
                    else:
                        existSensorOff.append(item)

                else:
                    newdevicelist.append(item)
            existSensorOff.extend(newdevicelist)
            existSensorOff.extend(existSensorOn)
            alarmAct['actList'] = existSensorOff
        except:
            Utils.logException('updateExistSensorPriorInLinkAction error.')
            pass
        return action
       
    def removeRoomMode(self, params):
        if params is None:
            return ErrorCode.ERR_INVALID_REQUEST, None

        jsonobj = params
        roomId = jsonobj.get("roomId", None)
        name = jsonobj.get("name", None)
        if roomId is None or name is None:
            return ErrorCode.ERR_INVALID_PARAMS, None
        Utils.logDebug("->removeRoomMode() %s,%s"%(roomId, name))

        ret = DBManagerAction().deleteActionsByName(roomId, name)
        
        #同步删除到云端
        if ret == True:
            cond = {}
            cond["roomId"] = roomId
            cond["name"] = name
            self.backupToClould("linkaction", cond, "remove")
        ##
        return ErrorCode.SUCCESS, None

    def removeAreaProp(self, params):
        if params is None:
            return ErrorCode.ERR_INVALID_REQUEST, None

        jsonobj = params
        roomId = jsonobj.get("roomId", None)
        areaId = jsonobj.get("areaId", "1")

        Utils.logDebug("->removeAreaProp() %s,%s"%(roomId, areaId))
        
        success = self.removeRoomArea(roomId, areaId)
        if success is True:
            #同步删除到云端
            cond = {}
            cond["roomId"] = roomId
            cond["areaId"] = areaId
            self.backupToClould("roomarea", cond, "remove")
        ##
        return ErrorCode.SUCCESS, None
    
    def queryAreaProp(self, params):
        if params is None:
            return (ErrorCode.ERR_INVALID_REQUEST, None)
        
        jsonobj = params
        roomId = jsonobj.get("roomId", None)
        areaId = jsonobj.get("areaId", None)
        if roomId is None or areaId is None:
            return ErrorCode.ERR_INVALID_PARAMS, None
        
        Utils.logDebug("->queryAreaProp() %s,%s"%(roomId, areaId))
        area = DBManagerRoomArea().getAreaBy(roomId, areaId)
        # if area == None:
        #     success = "fail"
        #命令执行结果反馈
        # return (ErrorCode.SUCCESS, area)
        return self.returnByTimestamp(params, area)

    #{"area":{"name":"客厅","areaId":"1","timestamp":"1024","imageurl":"area_bg.png"}}
    def updateAreaProp(self, sparam):
        if sparam is None:
            return ErrorCode.ERR_INVALID_REQUEST, None
        Utils.logDebug("->updateAreaProp() %s"%(sparam))
        areaprop = sparam.get("area", None)
        if areaprop is None:
            return ErrorCode.ERR_INVALID_PARAMS, None

        ret = DBManagerRoomArea().saveAreaProperty(areaprop)
        if ret != None:
            self.backupToClould("areaprop", ret)
            return ErrorCode.SUCCESS, ret
        else:
            return ErrorCode.ERR_GENERAL, None
    
    def removeRoomProp(self, sparam):
        if sparam == None:
            return (ErrorCode.ERR_INVALID_REQUEST, None)
        Utils.logDebug("->removeRoomProp() %s"%(sparam))

        roomId = sparam.get("roomId", None)
        if roomId == None:
            return (ErrorCode.ERR_INVALID_PARAMS, None)

        success = self.removeRoom(roomId)
        
        if success == True:
            cond = {}
            cond["roomId"] = roomId
            self.backupToClould("roomarea", cond, "remove")
        ##
        return (ErrorCode.SUCCESS, None)
    
    def updateRoomProp(self, sparam):
        if sparam == None:
            return (ErrorCode.ERR_INVALID_REQUEST, None)
        Utils.logDebug("->updateRoomProp() %s"%(sparam))

        roomprop = sparam.get("room")
        roomId_in_sparam = roomprop.get("roomId", None)
        roomName = roomprop.get("name")
        device_list = sparam.get("deviceList", [])

        if roomprop is None:
            return (ErrorCode.ERR_INVALID_PARAMS, None)

        ret = DBManagerRoom().saveRoomProperty(roomprop)

        if ret is not None:
            self.backupToClould("roomprop", ret)
            roomId = ret.get("roomId", roomId_in_sparam)
            # 更新房间设备信息
            if device_list:  # 变动的设备列表，用户对房间内设备有操作
                # if roomId_in_sparam is None or roomId_in_sparam == "":
                for dev in device_list:
                    if dev.get("dismiss"):  # dismiss==True，解绑房间，将房间ID和房间名置为空字符串
                        dev["roomId"] = ""
                        dev["roomname"] = ""
                        dev["areaId"] = ""  # delos没有房间区域概念，配合服务端默认给一个区域，APP端不用
                        dev["areaname"] = ""
                    else:  # dismiss==False，绑定房间，将房间ID和房间名赋值为对应的值
                        dev["roomId"] = ret.get("roomId", "")
                        dev["roomname"] = roomName
                        dev["areaId"] = "1"  # delos没有房间区域概念，配合服务端默认给一个区域，APP端不用
                        dev["areaname"] = "新区域"
            else:  # 用户对房间内设备没有改动，只改动了房间名
                device_list = DBManagerDeviceProp().getDevicesByRoomIdList([roomId])
                for dev in device_list:
                    dev["roomname"] = roomName
            DBManagerDeviceProp().saveDeviceBatch(device_list, devOpt=True)

            # 更新host表
            try:
                host_prop = DBManagerHostId().getHost()
                if host_prop is None:
                    Utils.logError("主机信息丢失，请重启主机！！！")
                    return ErrorCode.ERR_GENERAL, None
                room_list = host_prop.get("room", [])
                new_item = dict()
                if roomId_in_sparam is None or roomId_in_sparam == "":
                    new_item["type"] = ret.get("type", "")
                    new_item["roomId"] = ret.get("roomId", 0)
                    new_item["name"] = ret.get("name", "")
                    room_list.append(new_item)
                    host_prop["room"] = room_list
                else:
                    for item in room_list:
                        if str(item.get("roomId")) == str(roomId_in_sparam):
                            if item["type"] != ret.get("type"):
                                item["type"] = ret.get("type", "")
                            if item["name"] != ret.get("name"):
                                item["name"] = ret.get("name", "")
                    host_prop["room"] = room_list

                oldtimestamp = None
                if host_prop.has_key("timestamp"):
                    oldtimestamp = host_prop.get("timestamp")
                DBManagerHostId().updateHostConfig(host_prop.get("hostId"), host_prop.get("name"), host_prop, oldtimestamp)
            except Exception, err:
                Utils.logError("Error delete room while update tbl_host: %s" % err)
            return (ErrorCode.SUCCESS, ret)
        else:
            return (ErrorCode.ERR_GENERAL, None)

    def queryRoomProp(self, sparam):
        if sparam == None:
            return (ErrorCode.ERR_INVALID_REQUEST, None)

        Utils.logDebug("->queryRoomProp() %s"%(sparam))

        roomId = sparam.get("roomId", None)
        if roomId == None:
            return (ErrorCode.ERR_INVALID_PARAMS, None)

        room = DBManagerRoom().getRoomByRoomId(roomId)
        #命令执行结果反馈
        # return (ErrorCode.SUCCESS, room)
        return self.returnByTimestamp(sparam, room)

    #{"devices":[{"addr":"z-status1"},{"addr":"z-status2"}]}
    def queryDeviceStatus(self, sparam):
        if sparam == None:
            return (ErrorCode.ERR_INVALID_REQUEST, None)
        Utils.logDebug("->queryDeviceStatus() %s"%(sparam))

        ## 性能优化
        compress = sparam.get("compress", None)
        success = ErrorCode.SUCCESS
        devstatus = []

        # 中央空调的状态查询
        devType = sparam.get("type", None)
        if devType == DEVTYNAME_CENTRAL_AIRCONDITION:
            cac_statuses = DBManagerDevice().getDeviceByDevType(devType)
            if cac_statuses is not None:
                devices = sparam.get("devices", None)
                addrs = []
                for device in devices:
                    addrs.append(device.get("addr"))
                if addrs is None:
                    return (ErrorCode.ERR_INVALID_PARAMS, None)

                for item in cac_statuses:
                    addr = str(item.get("addr"))
                    if str(addr) not in addrs:
                        cac_statuses.remove(item)
                for item in cac_statuses:
                    offline = True
                    lastStatusTime = item.get('time', None)
                    if lastStatusTime != None:
                        now = int(time.time())

                        if now >= lastStatusTime and now - lastStatusTime <= 60*60:
                            offline = False
                    if offline is True:
                        item['offline'] = 0  # 不显示设备离线信息: 0
                    else:
                        item['offline'] = 0
                    devstatus.append(item)
                return (success, {"devices": devstatus})


        addrs = sparam.get("devices", None)
        if addrs == None:
            return (ErrorCode.ERR_INVALID_PARAMS, None)
        try:
            for addrdict in addrs:
                addr = addrdict.get("addr", None)
                if not addr:  # if addr == None:
                    continue
                addr = self.getDevAddr(addr)
                stats = DBManagerDevice().getDeviceByDevId(addr)
                if stats != None:
                    offline = True
                    devType = stats.get('type', None)

                    if devType in ['Camera', 'Lock', 'Exist', 'Gsm', 'CurtainSensor', 'Water',
                                    'CircadianLight', 'N4']:# 由于门锁上报机制特殊，将门锁状态视为永久在线--modified by chenjc
                        stats['offline'] = 0
                    else:
                        lastStatusTime = stats.get('time', None)
                        if lastStatusTime != None:
                            now = int(time.time())

                            if now >= lastStatusTime and now - lastStatusTime <= 60*35:
                                offline = False
                        if offline is True:


                            stats['offline'] = 0  # 不显示设备离线信息 0
                        else:
                            stats['offline'] = 0
                    devstatus.append(stats)
        except Exception, e:
            Utils.logError("===Exception: %s" % e)
            success = ErrorCode.ERR_GENERAL
            devstatus = []

        ## 性能优化
        if compress is True and self.solib is not None:
            st = json.dumps(devstatus)
            en = self.zlibCompress(st)
            return (success, {"devices_compress":en})

        #命令执行结果反馈
        # if devType == DEVTYPENAME_FLOOR_HEATING:
        #     Utils.logSuperDebug("FloorHeating status: %s" % str(devstatus))
        return (success, {"devices":devstatus})

    def queryDeviceStatusForDelos(self, sparam):
        if sparam == None:
            return (ErrorCode.ERR_INVALID_REQUEST, None)
        Utils.logDebug("->queryDeviceStatusForDelos() %s" % (sparam))

        devstatus = []
        success = ErrorCode.SUCCESS
        addr = sparam.get("addr", None)
        room_id = sparam.get("roomId", None)
        if addr == None:
            return (ErrorCode.ERR_INVALID_PARAMS, None)
        try:
            stats = DBManagerDevice().getDeviceByDevId(addr)
            if stats != None:
                if room_id in ['m', 's', 'g', 'd']:
                    # 非客厅，各项数据根据其他实际设备数据计算
                    status_value = stats.get("value")
                    co2 = round(float(status_value.get("co2", 535)) * randint(80, 102) * 0.01, 1)
                    temp = round(float(status_value.get("temp", 27)) * randint(90, 100) * 0.01, 1)
                    humid = round(float(status_value.get("humid", 43)) * randint(80, 102) * 0.01, 1)
                    voc = round(float(status_value.get("voc", 200)) * randint(80, 102) * 0.01, 1)
                    pm25 = round(float(status_value.get("pm25", 10)) * randint(80, 102) * 0.01, 1)
                    status_value["co2"] = co2
                    status_value["temp"] = temp
                    status_value["humid"] = humid
                    status_value["voc"] = voc
                    status_value["pm25"] = pm25
                    stats["value"] = status_value
                devstatus.append(stats)

        except Exception, e:
            Utils.logError("===Exception: %s" % e)
            success = ErrorCode.ERR_GENERAL
            devstatus = []

        return (success, {"devices": devstatus})

    def queryDevices(self, conditions):
        if conditions == None:
            return (ErrorCode.ERR_INVALID_REQUEST, None)
        Utils.logDebug("->queryDevices() %s"%(conditions))
        room = conditions.get("roomId", None)
        area = conditions.get("areaId", "1")
        devType = conditions.get("type", None)
        
        ret = DBManagerDeviceProp().getDevicePropertyBy(room, area, devType)

        ## 性能优化
        compress = conditions.get("compress", None)
        if compress is True and self.solib is not None:
            jsondump = json.dumps(ret)
            en = self.zlibCompress(jsondump)
            return (ErrorCode.SUCCESS, {"devices_compress":en})

        #命令执行结果反馈
        return (ErrorCode.SUCCESS, ret)

    # APP发送开始批量扫描指令
    def startScanBatch(self, sparam=None):
        dev_type = sparam.get("type", None)
        if dev_type == "CircadianLight":
            n4SerialNo = sparam.get("n4SerialNo", "")
            if n4SerialNo:
                n4Detail = DBManagerDeviceProp().getDeviceByAddrType(n4SerialNo, DEVTYPENAME_KETRA_N4)[1]
                n4IPAddr = n4Detail.get("n4IP", "")
                keypad_list = KetraUtils.getKeypadList(n4SerialNo, n4Addr=n4IPAddr)
                return (ErrorCode.SUCCESS, keypad_list)
            return (ErrorCode.ERR_INVALID_PARAMS, None)

        if self.batchScanner is None:
            self.batchScanner = BatchScanner()
            self.scannerThread = threading.Thread(target=self.batchScanner.scan)
            self.scannerThread.setDaemon(True)
            self.scannerThread.start()
            # pub.sendMessage(GlobalVars.PUB_START_BATCH_SCAN, scanner=self.batchScanner, scanner_thd=t)
            Utils.logDebug("-------------- start scanner thread --------------")
            # self.scannerWatchdog = threading.Thread(target=self.batchScanner.scanner_watchdog, args=(self.stopScanBatch,))
            # self.scannerWatchdog.setDaemon(True)
        # self.scannerWatchdog.start()
            self.scannerWatchdog = threading.Timer(120, self.stopScanBatch)
            self.scannerWatchdog.start()
            Utils.logDebug("-------------- start scanner watchdog thread --------------")
        else:
            return (ErrorCode.ERR_SCANNING, {"msg":"主机已处于扫描状态"})
        return (ErrorCode.SUCCESS, {"msg": "SUCCESS"})

    # APP发送停止批量扫描指令
    def stopScanBatch(self, sparam=None):
        if self.batchScanner is not None:
            self.batchScanner.stop_scan()
            self.batchScanner = None
            self.scannerThread = None
            if self.scannerWatchdog is not None:
                self.scannerWatchdog.cancel()
                self.scannerWatchdog = None
            # pub.sendMessage(GlobalVars.PUB_STOP_BATCH_SCAN)
            Utils.logDebug("-------------- stop scanner thread --------------")
        return (ErrorCode.SUCCESS, {"msg": "SUCCESS"})

    # 批量扫描设备时APP查询设备信息列表
    def queryDeviceWithBatch(self, sparam):
        Utils.logInfo("queryDeviceWithBatch sparam is: %s" % str(sparam))
        try:
            if sparam is None:
                return (ErrorCode.ERR_INVALID_REQUEST, None)
            # opflag = sparam.get("op", None)
            # if opflag == "enter":  # 控制分配区域行为，确保同时只有一个人在给设备分配区域
            #     if self.operatingDev:
            #         return (ErrorCode.ERR_SCANNING, {"msg": "网关已处于扫描状态"})
            #     else:
            #         self.operatingDev = True
            #         # 检测网关扫描状态，防止用户在进入列表之后直接退出APP，一段时间之后清除状态回到可扫描状态
            #         self.optWatchdog = threading.Timer(60, self._setOperatingDev)
            #         self.optWatchdog.start()

            ret = DBManagerDeviceProp().queryDeviceWithBatch()
            return (ErrorCode.SUCCESS, ret)
        except Exception:
            self.operatingDev = None
            return (ErrorCode.ERR_GENERAL, None)

    # 保存批量添加的设备信息
    def saveDeviceBatch(self, sparam):
        Utils.logDebug("saveDeviceBatch sparam is: %s" % str(sparam))
        if sparam is None:
            return (ErrorCode.ERR_INVALID_REQUEST, None)

        # addr_arr = sparam.get("addr", [])
        devices_info = sparam.get("devices", [])
        isX2 = sparam.get("isX2", None)
        if devices_info:
            if isX2 == "1":
                ret = DBManagerDeviceProp().insertDeviceBatch(devices_info)
            else:
                ret = DBManagerDeviceProp().saveDeviceBatch(devices_info)
            if ret:
                # pub.sendMessage(GlobalVars.PUB_STOP_BATCH_SCAN)  # TODO 保存后停止扫描，待确定，需根据流程及实际情况确定是否此处要发出消息
                # if self.operatingDev:
                #     self.operatingDev = None
                return (ErrorCode.SUCCESS, ret)
        return (ErrorCode.ERR_INVALID_REQUEST, None)

    # delos编辑常用设备
    # {"devices": [{deviceProp1}, {...}, ..., {devicePropX}]}
    def editFavoriteDevice(self, sparam):
        Utils.logDebug("editFavoriteDevice() sparam: %s" % str(sparam))
        edit_flag = sparam.get("editFlag")
        dbManagerDeviceProp = DBManagerDeviceProp()

        device_list = sparam.get("devices", [])
        rtn = dbManagerDeviceProp.updateDeviceFavorite(device_list)
        if rtn:
            return ErrorCode.SUCCESS, rtn
        return ErrorCode.SUCCESS, None

        # if edit_flag == "multi":  # 多个设备编辑(APP在设备列表编辑时发送的请求)
        #     add_list = sparam.get("addFavorite", [])
        #     rmv_list = sparam.get("removeFavorite", [])
        #     # 将常用设备列表的favirate字段设置为"1"，表示常用
        #     for dev in add_list:
        #         dev.set("favorite", "1")
        #
        #     # 将常用设备列表的favirate字段设置为"0"，表示非常用
        #     for dev in rmv_list:
        #         dev .set("favorite", "0")
        #
        #     rtn = dbManagerDeviceProp.updateDeviceFavorite(add_list + rmv_list)
        #     if rtn:
        #         rtn_info = {"addFavorite": add_list, "removeFavorite": rmv_list}
        #         return ErrorCode.SUCCESS, rtn_info
        #
        # else:  # 设备控制界面发送的请求，是单个设备设置
        #     favorite_flag = sparam.get("favorite", "1")  # "favorite"标记："1"-常用；"0"-非常用
        #     device_addr = sparam.get("addr")
        #     device_type = sparam.get("type")
        #     device_prop = dbManagerDeviceProp.getDeviceByDevAddrAndType(device_addr, device_type)
        #     device_prop["favorite"] = favorite_flag
        #     rtn = dbManagerDeviceProp.saveDeviceProperty(device_prop)
        #     if rtn:
        #         return ErrorCode.SUCCESS, rtn
        # return ErrorCode.SUCCESS, None

    # def _setOperatingDev(self):
    #     self.operatingDev = None
    #     if self.optWatchdog is not None:
    #         self.optWatchdog.calcel()
    #         self.optWatchdog = None

    def query_device(self, conditions):

        if conditions is None:
            return ErrorCode.ERR_INVALID_REQUEST, None

        addr = conditions.get("addr", None)
        name = conditions.get("name", None)
        key_id, result = DBManagerDeviceProp().getDeviceByAddrName(addr, name)

        # 命令执行结果反馈
        return ErrorCode.SUCCESS, result

    # 添加/修改设备（属性）
    # {"device":{"name":"updatedeviceprop","type":"light","roomId":"1","addr":"z-update1","value": {"state":"0"}, "linkaction":[{"modeId":"2"}]}}
    def updateDeviceProp(self, sparam):
        if sparam == None:
            return (ErrorCode.ERR_INVALID_REQUEST, None)
        Utils.logDebug("->updateDeviceProp()")
        deviceprop = sparam.get("device", None)

        if deviceprop == None:
            return (ErrorCode.ERR_INVALID_PARAMS, None)

        update = sparam.get("update", 'false')    # update device or create new device. app will supply this flag.
        updateLcd = sparam.get("updateLcd", "false")  # 更新设备名称时使用
        dev_type = deviceprop.get("type")
        # Ketra N4主机则需要调用Ketra的接口
        if dev_type == "N4":
            n4SerialNo = deviceprop.get('addr')
            n4IP = KetraUtils.discoverN4Device(n4SerialNo)
            deviceprop['n4IP'] = n4IP
            deviceprop["softwareVer"] = ""
            deviceprop["hardwareVer"] = ""  # 补全一些信息

        # 背景音乐关联模式
        if dev_type == "Audio":
            brand = deviceprop.get("brand", "")
            if brand == "Wise":  # 这里只处理UDP协议的华尔斯背景音乐配置，485的华尔斯是发出cmd=5的命令来设置
                valueTemp = deviceprop.get("value", {})
                modeId = valueTemp.get("modeId", None)
                if modeId:
                    currNo = valueTemp.get("Index", None)
                    volume = valueTemp.get("volume", None)
                    if currNo is None:
                        currNo = "0"
                    if volume is None:
                        volume = "6"
                    song_info = {"setSong": currNo, "setVolume": volume}
                    del valueTemp["modeId"]
                    song_dict = deviceprop.get("songDict", {})
                    deviceprop["value"] = valueTemp
                    song_dict["mode_{}".format(modeId)] = song_info
                    deviceprop["songDict"] = song_dict

        ret = None
        if update == 'true':
            ret = DBManagerDeviceProp().saveDeviceProperty(deviceprop)
        else:
            ret = DBManagerDeviceProp().newDeviceProperty(deviceprop)

            if dev_type == DEVTYPENAME_LASER_EGG:
                # 新增镭豆设备的话要通知KaiterraConnector更新镭豆设备列表
                Utils.logDebug("sending update_laserEgg_ids...")
                laserUdid = deviceprop.get('addr')
                pub.sendMessage('update_laserEgg_ids', laserEggId=laserUdid, add=True)
        if ret == None:
            return (ErrorCode.ERR_GENERAL, None)
        elif ret == ErrorCode.ERR_CMD_DUPLICATE_DEVICE:
            return (ErrorCode.ERR_CMD_DUPLICATE_DEVICE, {"msg": "该设备已存在"})
        else:
            # 如果是传感设备，需增加联动计划
            detailObj = deviceprop
            if update == 'true':
                # 更新设备信息，如果设备类型是LCD开关需要同步设备名
                if dev_type == 'LcdSwitch':
                    ctrlParams = []
                    if updateLcd == "name":
                        lightName = deviceprop.get('lightName', None)
                        if lightName:
                            for lightIndex, name in lightName.items():
                                if name:
                                    if isinstance(name, unicode):
                                        name = name.encode('utf-8')
                                    index = lightIndex[-1]
                                    value = {"state": name}  # {"state": name}  最多3个中文字符
                                    value['index'] = index
                                    value['controlType'] = 2  # 同步开关名称
                                    ctrlParam = {
                                        'addr': deviceprop.get('addr'),
                                        'type': dev_type,
                                        'value': value
                                    }
                                    ctrlParams.append(ctrlParam)

                    elif updateLcd == "modecfg":
                        modecfg = deviceprop.get("modecfg", {})
                        for index, modeid in modecfg.items():
                            roommode = DBManagerAction().getActionByModeId(modeid)
                            modename = roommode.get("tag", None)
                            if not modename:
                                modename = roommode.get("name")
                            if isinstance(modename, unicode):
                                modename = modename.encode("utf-8")

                            namevalue = {"index": index, "state": modename, "controlType": 3}
                            ctrlParam = {
                                'addr': deviceprop.get('addr'),
                                'type': dev_type,
                                'value': namevalue
                            }
                            ctrlParams.append(ctrlParam)  # 同步模式名称

                            if str(modeid) in ["1", "2", "3", "4"]:
                                # 全剧模式直接使用模式ID即可
                                value = {"index": index, "state": int(modeid), "controlType": 4}
                            elif str(modeid) in ["5", "6"]:
                                value = {"index": index, "state": 1, "controlType": 4}
                            else:
                                # 房间模式，需要先获取serialNo
                                value = {"index": index, "state": int(roommode.get("serialNo", 0)) + 5, "controlType": 4}

                            ctrlParam = {
                                'addr': deviceprop.get('addr'),
                                'type': dev_type,
                                'value': value
                            }
                            ctrlParams.append(ctrlParam)  # 同步模式图表

                        diff_index = list(set(["1", "2", "3", "4"]).difference(set(modecfg.keys())))
                        for index in diff_index:
                            value = {"index": index, "state": 0xF, "controlType": 4}
                            ctrlParam = {
                                'addr': deviceprop.get('addr'),
                                'type': dev_type,
                                'value': value
                            }
                            ctrlParams.append(ctrlParam)  # 同步模式图表

                    if len(ctrlParams) > 0:
                        #  将命令发出
                        pub.sendMessage(GlobalVars.PUB_CONTROL_DEVICE, cmd="controlDevice", controls=ctrlParams)

            else:
                self.initDevStatus(detailObj)

            devTypeName = detailObj.get("type", None)
            if self.isSensorDevType(devTypeName) == True:
                addr = detailObj.get("addr", None)
                action = DBManagerAction().getActionByDevId(addr)
                if action == None:
                    ##添加联动计划
                    actionDetail = {}
                    actionDetail["addr"] = addr
                    action = DBManagerAction().saveLinkAction(actionDetail)
                    if action != None:
                        self.backupToClould("linkaction", action)
            #同步更新到云端
            self.backupToClould("deviceprop", ret)

            # 如果改了名字的设备在中控面板上配对了，需要同步到中控面板

            v_type = self.getVtypeByName(devTypeName)
            if v_type is not None:
                devices_hgc = DBManagerHGC().getByVtype(v_type)
                if devices_hgc is not None and len(devices_hgc) > 0:
                    addr = detailObj.get("addr", None)
                    for item in devices_hgc:
                        dev_addr = item.get("controls")[0].get("addr")
                        if str(dev_addr) == str(addr):
                            sparam = {}
                            sparam["hgc_addr"] = item.get("addr")
                            sparam["channel"] = item.get("channel")
                            sparam["v_type"] = item.get("v_type")
                            sparam["update"] = 0x01
                            sparam["new_name"] = deviceprop.get("name")
                            pub.sendMessage("syncHgcDevices", sparam=sparam)

        #命令执行结果反馈
        return (ErrorCode.SUCCESS, ret)

    # 根据设备类型获取v_type
    def getVtypeByName(self, type_name):
        if type_name is None or type_name == "":
            return None
        if type_name == "LightAdjust" or type_name == "Light1" or type_name == "Light1" or type_name == "Light2" or type_name == "Light3" or type_name == "Light4":
            return 0x01
        if type_name == "Curtain":
            return 0x04
        if type_name == "AirCondition":
            return 0x03
        if type_name == "CAC":
            return 0x50
        if type_name == "Socket":
            return 0x02
        if type_name == "FloorHeating":
            return 0x52

    def initDevStatus(self, devpropobj):
        # macAddr = devpropobj.get("addr", None)
        # # deviceAddr = PacketParser.getDevAddrByMac(macAddr)
        # if macAddr == None:
        #     return
        # deviceAddr = self.getDevAddr(macAddr)
        # devStatusObj = {}
        # devStatusObj["name"] = devpropobj.get("name", None)
        # devStatusObj["type"] = devpropobj.get("type", None)
        # devStatusObj["addr"] = deviceAddr
        # devItem = DBManagerDevice().getDeviceByDevId(deviceAddr)
        # if(devItem is None):
        #     DBManagerDevice().saveDeviceStatus(devStatusObj)
        # del devStatusObj
        DBManagerDevice().initDevStatus(devpropobj)

    #{"devices":[{"addr":"z-111111","addr":"z-222222",...},{...},...]}
    def removeDevices(self, sparam):
        if sparam == None:
            return (ErrorCode.ERR_INVALID_REQUEST, None)
        Utils.logDebug("->removeDevices() %s"%(sparam))
        devAddrArr = sparam.get("devices", None)
        if devAddrArr == None:
            return (ErrorCode.ERR_INVALID_PARAMS, None)

        success = ErrorCode.SUCCESS
        try:
            for addrdict in devAddrArr:
                devaddr = addrdict.get("addr", None)
                devType = addrdict.get("type", None)
                audioDev = None  # 用于判断背景音乐设备是否是485类型的，判断是否需要发送退网命令
                if devType is None:
                    tempDevice = DBManagerDeviceProp().getDeviceByAddrName(devaddr, addrdict.get("name"))[1]
                    devType = tempDevice.get("type", None)
                    if devType == DEVTYPENAME_AUDIO:
                        audioDev = tempDevice
                    if devType is None:
                        return (ErrorCode.ERR_INVALID_PARAMS, None)
                    addrdict["type"] = devType
                elif devType == DEVTYPENAME_AUDIO:
                    audioDev = DBManagerDeviceProp().getDeviceByAddrName(devaddr, addrdict.get("name"))[1]

                if devaddr == None:
                    continue

                #删除联动计划里的相关设备
                self.removeDeviceFromLinkAction(devaddr)
                #删除传感器的联动计划
                if self.isSensorDevType(devType):
                    self.removeLinkAction(devaddr, devType)  # 删除的是传感器，直接删除联动计划整条记录
                else:
                    self.removeDeviceInLinkAction(devaddr)  # 删除的是非传感器类设备，可能是配置在联动设备列表里的设备，需要删除联动计划的设备列表
                self.removeDeviceLinks(devaddr)
                self.removeDevicePropFromDB(devaddr, addrdict.get('name', None))
                self.removeDeviceStatusFromDB(devaddr)
                #水电煤或插座
                DBManagerBackup().deleteBackupsByDevAddr(devaddr)
                ##TODO,优化：告警设备才需要删除告警
                DBManagerAlarm().deleteAlarmByDevId(devaddr)
                ##模式面板需要删除响应的配置
                # DBManagerModePannel().removeByDevAddr(devaddr)
                DBManagerHGC().deleteByAddr(devaddr)

                # 发送退网命令  225版本之后新增了批量添加功能，删除以下设备后要求使设备退网
                if devType in [DEVTYPENAME_LIGHT1, DEVTYPENAME_LIGHT2, DEVTYPENAME_LIGHT3, DEVTYPENAME_LIGHT4,
                               DEVTYPENAME_LIGHTAJUST, DEVTYPENAME_SOCKET, DEVTYPENAME_CURTAIN, DEVTYPENAME_EXIST_SENSOR,
                               DEVTYPENAME_AIR_SYSTEM, DEVTYPENAME_OXYGEN_CO2_SENSOR, DEVTYPENAME_ENVIROMENT_SENSOR,
                               DEVTYPENAME_CH4CO_SENSOR, DEVTYPENAME_SOS_SENSOR, DEVTYPENAME_FLOOR_HEATING,
                               DEVTYPENAME_AIR_FILTER, DEVTYPENAME_TABLE_WATER_FILTER, DEVTYPENAME_FLOOR_WATER_FILTER]:
                    pub.sendMessage(PUB_CONTROL_DEVICE, cmd="quitNetwork", controls=addrdict)

                if devType in [DEVTYPENAME_AIRCONDITION, DEVTYPENAME_TV]:
                    devs = DBManagerDeviceProp().getDeviceByAddr(devaddr)
                    if len(devs) == 0:  # 已经删除了最后一个红外转发的设备，需要发送退网命令
                        pub.sendMessage(PUB_CONTROL_DEVICE, cmd="quitNetwork", controls=addrdict)

                if devType == DEVTYPENAME_AUDIO:
                    if audioDev and audioDev.get("brand", None) in ["Wise485", "Levoice"]:  # 485接入的背景音乐删除后也要发送退网命令
                        pub.sendMessage(PUB_CONTROL_DEVICE, cmd="quitNetwork", controls=addrdict)

                if devType == DEVTYPENAME_LASER_EGG:  # 如果是镭豆设备，需要通知 KaiterraConnector 线程更新设备ID列表
                    pub.sendMessage('update_laserEgg_ids', laserEggId=devaddr, add=False)

        except:
            Utils.logException('removeDevices error.')
            success = ErrorCode.ERR_GENERAL
        #命令执行结果反馈
        return (success, None)

    #{"devices":[{"addr":"z-111111","addr":"z-222222",...},{...},...]}
    def dismissDevices(self, sparam):
        if sparam == None:
            return (ErrorCode.ERR_INVALID_REQUEST, None)
        Utils.logDebug("->dismissDevices() %s"%(sparam))
        devAddrArr = sparam.get("devices", None)
        if devAddrArr == None:
            return (ErrorCode.ERR_INVALID_PARAMS, None)

        success = ErrorCode.SUCCESS
        try:
            for addrdict in devAddrArr:
                devaddr = addrdict.get("addr", None)
                name = addrdict.get("name", None)
                if devaddr == None or name == None:
                    continue

                DBManagerDeviceProp().dismissDevice(devaddr, name)
                # 删除联动计划里的相关设备
                # self.removeDeviceFromLinkAction(devaddr)
                # 删除传感器的联动计划
                # self.removeLinkAction(devaddr)
                # self.removeDeviceLinks(devaddr)
                # self.removeDevicePropFromDB(devaddr)
                # self.removeDeviceStatusFromDB(devaddr)
                # 水电煤或插座
                # DBManagerBackup().deleteBackupsByDevAddr(devaddr)
                # TODO,优化：告警设备才需要删除告警
                # DBManagerAlarm().deleteAlarmByDevId(devaddr)
        except:
            success = ErrorCode.ERR_GENERAL
        #命令执行结果反馈
        return (success, None)

    def removeDeviceLinks(self, addr):
        if addr == None:
            return
        # 先查出现有的关联信息以备后续使用
        #control_infos数据格式：[{'dbId':x, 'controls':[{'addr':'mac1','type':'Light2','channel':1}, ...]},{...}]
        #类型:list
        control_infos = DBManagerLinks().getDeviceLinksByAddr(addr)
        Utils.logDebug("->removeDeviceLinks() %s"%(addr))
        succ = DBManagerLinks().deleteByAddr(addr)
        if succ:# 如果关联信息库数据删除成功，将消息发送给driver
            if control_infos is not None and len(control_infos) > 0:
                for control in control_infos:
                    self.removeLinkDevices(control, addr)

    def removeLinkAction(self, addr, devType=None):
        if addr == None:
            return
        Utils.logDebug("->removeLinkAction() %s"%(addr))
        DBManagerAction().deleteActionByDevId(addr)
        if self.isSensorDevType(devType):
            DBManagerAction().deleteActionByDevId(addr + "_recover")

    # 删除联动计划设备列表内某个设备
    def removeDeviceInLinkAction(self, addr):
        DBManagerAction().updateDeviceList(addr)
    
    def removeDeviceFromLinkAction(self, addr):
        if addr == None:
            return
        Utils.logDebug("->removeDeviceFromLinkAction() %s"%(addr))
        
        ##设备属性中存在{”linkaction":[{“modeId”:"2"]}
        devJsonObj = DBManagerDeviceProp().getDeviceByDevId(addr)
        if devJsonObj is None:
            return
        
        devLinkActions = devJsonObj.get("linkaction", None)
        if devLinkActions is None:
            return

        for linkAction in devLinkActions:
            actionItem = None
            modeId = linkAction.get("modeId", None)
            if(modeId != None):
                actionItem = DBManagerAction().getActionByModeId(modeId)

            if actionItem == None:
                continue

            ##找到Action表记录
            alarmAct = actionItem.get("alarmAct", None)
            if(alarmAct == None):
                continue

            actDevices = alarmAct.get("actList", None)
            if(actDevices == None or len(actDevices) == 0):
                continue

            found = False
            for actDevice in actDevices:
                #下面是要控制的设备
                actDevAddrTemp = actDevice['deviceAddr']
                if(actDevAddrTemp != addr):
                    continue
                else:
                    ##找到联动计划里的该设备，删除
                    actDevices.remove(actDevice)
                    found = True

            if found == True:
                alarmAct.set("actList", actDevices)
                # newActionDetailStr = json.dumps(actionItem)
                ret = DBManagerAction().saveLinkAction(actionItem)
                #同步该联动计划到云端
                if ret != None:
                    self.backupToClould("linkaction", ret)

    def removeDevicePropFromDB(self, addr, name):
        if addr == None or name == None:
            return
        Utils.logInfo("->removeDevicePropFromDB() %s %s"%(addr, name))
        ret = DBManagerDeviceProp().deleteDeviceByAddrName(addr, name)
        #同步删除云端的设备属性
        if ret == True:
            cond = {}
            cond["addr"] = addr
            self.backupToClould("deviceprop", cond, "reomve")
        
    def removeDeviceStatusFromDB(self, addr):
        if addr == None:
            return
        Utils.logDebug("->removeDeviceStatusFromDB() %s"%(addr))
        ret = DBManagerDevice().deleteDeviceById(addr)
        
        #同步删除云端的设备状态
        if ret == True:
            cond = {}
            cond["addr"] = addr
            self.backupToClould("devices", cond, "reomve")


    #[{"name":"device1","type":"light","room":"room1","addr":"z-11111111"}]
    def controlDevices(self, payload):

        if payload == None:
            return (ErrorCode.ERR_INVALID_REQUEST, None)
        deviceValArrs = payload.get("devices", None)
        if deviceValArrs == None:
            return (ErrorCode.ERR_INVALID_PARAMS, None)

        try:
            # 保存红外空调学习的按键
            key_index = deviceValArrs[0].get("keyIndex", None)
            if key_index is not None:
                device_name = deviceValArrs[0].get("deviceName", None)
                device_addr = deviceValArrs[0].get("addr", None)
                key_id, device_prop = DBManagerDeviceProp().getDeviceByAddrName(device_addr, device_name)
                key_indices = device_prop.get("keyIndices", None)
                if key_indices is None:
                    key_indices = [key_index]
                    device_prop["keyIndices"] = key_indices
                    DBManagerDeviceProp().saveDeviceProperty(device_prop)
                elif key_index not in key_indices:
                    key_indices.append(key_index)
                    device_prop["keyIndices"] = key_indices
                    DBManagerDeviceProp().saveDeviceProperty(device_prop)
                else:
                    pass

            # 保存红外空调的数据
            new_data = deviceValArrs[0].get("AcData", None)
            if new_data is not None:
                device_name = deviceValArrs[0].get("deviceName", None)
                device_addr = deviceValArrs[0].get("addr", None)
                key_id, device_prop = DBManagerDeviceProp().getDeviceByAddrName(device_addr, device_name)

                device_prop["AcData"] = new_data
                DBManagerDeviceProp().saveDeviceProperty(device_prop)
        except Exception as err:
            Utils.logError("error save acData: %s" % err)



        #20151009: multi-channel in one message
        # for deviceVal in deviceValArrs:
        #     cmdarr = []
        #     addr = deviceVal.get('addr', None)
        #     value = deviceVal.get('value', None)
        #     devStatusObj = DBManagerDevice().getDeviceByDevId(addr)
        #     if devStatusObj is None:
        #         return (ErrorCode.ERR_GENERAL, None)

        #     devStatusValueInDb = devStatusObj.get('value', None)
        #     if devStatusValueInDb is None:
        #         devStatusValueInDb = value
        #     else:
        #         for key in value:
        #             v = value.get(key)
        #             devStatusValueInDb[key] = v
        #     deviceVal['value'] = devStatusValueInDb
        #     cmdarr.append(deviceVal)
        #     Utils.logDebug("->controDevice() publish PUB_CONTROL_DEVICE")
        #     pub.sendMessage(GlobalVars.PUB_CONTROL_DEVICE, cmd="controlDevice",controls=cmdarr)
        #     #可以默认命令一定会执行成功吗？

        devType = deviceValArrs[0].get('type')
        if devType == 'ScrOperator':
            value = deviceValArrs[0].get('value', {})
            if value:
                state = value.get('data')
                if state:
                    Utils.screen_operator(state)  # 发送Delos展厅屏幕控制器命令
            return (ErrorCode.SUCCESS, None)

        Utils.logDebug("->controDevice() publish PUB_CONTROL_DEVICE")
        pub.sendMessage(GlobalVars.PUB_CONTROL_DEVICE, cmd="controlDevice", controls=deviceValArrs)
        # 可以默认命令一定会执行成功吗？
        return (ErrorCode.SUCCESS, None)
        
    def confirmAlarms(self, params):
        if params == None:
            return (ErrorCode.ERR_INVALID_REQUEST, None)
        Utils.logDebug("->confirmAlarms %s"%(params))
        deviceId = params.get("deviceId", None)
        # alll = params.get("all", None)
        deviceAddrs = []
        alarms = None
        if deviceId == 'all':
            alarms = DBManagerAlarm().getAlarmByConfirm("0")
            if alarms != None:
                for alarm in alarms:
                    addr = alarm.get("addr", None)
                    if addr != None:
                        deviceAddrs.append(addr)
        elif deviceId != None:
            # alarms = DBManagerAlarm().deleteAlarmByDevId(deviceId)
            deviceAddrs.append(deviceId)

        if len(deviceAddrs) > 0:
            # Utils.logDebug("publish PUB_ALARM confirmAlarms")
            # pub.sendMessage(GlobalVars.PUB_ALARM, cmd="confirmAlarms",alarms=deviceAddrs)
            self.confirmAlarm(deviceAddrs)
        del deviceAddrs
        return (ErrorCode.SUCCESS, None)

    def confirmAlarm(self, alarmDevIds):
        Utils.logDebug("->confirmAlarm %s" % (alarmDevIds))
        bakupAlarmDetailsArr = []  # 所有需要备份的告警json数组
        # 读取到网关的所有报警
        for devAddr in alarmDevIds:
            # 获取到要确认的报警对应的当前报警状态
            try:
                # devAddr = devAddrId.get("addr",None)
                # if(devAddr == None):
                #     continue
                alarmDetailObj = DBManagerAlarm().getAlarmByDevId(devAddr)
                if(alarmDetailObj == None):
                    Utils.logInfo("when confirming alarm, not find this alarm:%s" % (devAddr))
                    continue

                # 判断是否已经确认过了
                # alarmDetailObj = json.loads(alarmDetailJson)
                confirmed = alarmDetailObj.get("confirmed")
                if(confirmed == 1):
                    # bakupAlarmDetailsArr.append(alarmDetailObj)
                    # 所有该设备的告警详情都同步到云端。
                    continue

                alarmDetailObj["confirmed"] = 1
                if(alarmDetailObj.get("alarming","") == "0"):  # 已确认且恢复，需删除该报警
                    bakupAlarmDetailsArr.append(alarmDetailObj)
                    # 所有该设备的告警详情都同步到云端。
                    DBManagerAlarm().deleteAlarmByDevId(devAddr)
                else:  # 已确认未恢复
                    # newAlarmDetail = json.dumps(alarmDetailObj);
                    ret = DBManagerAlarm().saveAlarm(alarmDetailObj)
                    if ret != None:
                        bakupAlarmDetailsArr.append(ret)  # 同步新状态
            except:
                Utils.logException("when confirming alarm, failed")
                continue
        ##更新数据库完毕
        ##备份
        if(bakupAlarmDetailsArr != None and len(bakupAlarmDetailsArr) > 0):
            #通知本地另外一个线程，以便在其中将所有的报警都同步到云上
            try:
                # details = json.dumps(bakupAlarmDetailsArr)
                self.backupToClould("alarms", bakupAlarmDetailsArr)
            except:
                Utils.logException("confirmAlarm failed to notify backup")
        del bakupAlarmDetailsArr
        return

    # {"status":statusStr,"alarms":alarms}
    def readAlarms(self, params):
        if params == None:
            return (ErrorCode.ERR_INVALID_REQUEST, None)
        Utils.logDebug("->readAlarms %s"%(params))
        almType = params.get("type", None)
        confirm = params.get("confirm", None)
        page = params.get("start", None)
        if page is None:
            page = 0
        pagenum = params.get("size", None)
        if pagenum is None or pagenum == '':
            pagenum = 10

        alarms = None
        total = 0
        if almType != None and almType != "" and almType != "all":
            alarms = DBManagerAlarm().getAlarmByType(almType, page, pagenum)
            if int(page) == 0:
                total = DBManagerAlarm().getAlarmCountByType(almType)
        elif confirm != None:
            alarms = DBManagerAlarm().getAlarmByConfirm(confirm, page, pagenum)
            if int(page) == 0:
                total = DBManagerAlarm().getAlarmCountByConfirm(confirm)

        result = {}
        # result["ret"] = "0"
        if alarms != None:
            result["data"] = alarms
        # if int(page) == 0:
        pager={}
        pager["start"] = int(page)
        pager["size"] = int(pagenum)
        pager["total"] = total
        result["pager"] = pager
        return (ErrorCode.SUCCESS, result)

    def readGlobalData(self, sparam):
        glb = {}

        if self.activedMode != None:
            glb['mode'] = self.activedMode

        # 查哪个房间有灯开着
        # 查哪个房间的设备有故障
        try:
            host = DBManagerHostId().getHost()
            if host == None:
                return ErrorCode.SUCCESS, glb
            rooms = host.get('room', None)
            if rooms == None or rooms == []:  # delos允许删除最后一个房间
                return ErrorCode.SUCCESS, glb
            light={}
            offline={}
            # 以下为新处理方式
            devaddr_list = None
            devstatus_list = None
            dev_room_map = {}

            room_ids = [room.get("roomId") for room in rooms]
            devPropsInRoomId = DBManagerDeviceProp().getDevicesByRoomIdList(room_ids)
            if devPropsInRoomId is not None:
                devaddr_list = [devProp.get("addr") for devProp in devPropsInRoomId]
                for devProp in devPropsInRoomId:
                    room_map = {"roomId": devProp.get("roomId"), "areaId": devProp.get("areaId", "1")}
                    dev_room_map[devProp.get("addr")] = room_map

            if devaddr_list is not None:
                devstatus_list = DBManagerDevice().getDeviceStatusByDevIdList(devaddr_list)

            for devstatus in devstatus_list:
                if devstatus is None:
                    continue
                # 是否有设备离线了？
                roomLightOn = False
                roomdevoffline = False
                roomId = dev_room_map.get(devstatus.get('addr')).get('roomId')
                devType = devstatus.get('type', None)
                lastStatusTime = devstatus.get('time', None)
                # 由于门锁的上报机制特殊，将门锁视为永久在线--modified by chenjc
                if devType != 'Camera' and devType != 'Lock' and lastStatusTime is not None:
                    now = int(time.time())

                    if now > lastStatusTime and now - lastStatusTime > 60 * 30:
                        roomdevoffline = False  # 不显示离线信息

                ## 是否有灯开着
                devType = devstatus.get('type')
                if 'Light' not in devType:
                    continue
                devVs = devstatus.get('value')
                if devVs is not None:  # 手动添加虚假设备时没有value这一项，会导致
                    for key in devVs.keys():
                        if 'state' in key:
                            lightV = devVs.get(key)
                            if str(lightV) != '0':
                                # on
                                roomLightOn = True
                                break
                ##
                if roomLightOn == True and roomdevoffline == True:
                    continue

                if roomLightOn == True:
                    # roomId has light on
                    light[roomId] = 'on'
                if roomdevoffline == True:
                    offline[roomId] = 'offline'

            glb['light'] = light
            glb['offline'] = offline

            # 以下为旧查询方式
            # for room in rooms:
            #     roomId = room.get('roomId')
            #     devPropsInRoomId = DBManagerDeviceProp().getDevicePropertyBy(roomId, None, None)
            #     if devPropsInRoomId == None or len(devPropsInRoomId) == 0:
            #         continue
            #     roomLightOn = False
            #     roomdevoffline = False
            #     for devInRoomId in devPropsInRoomId:
            #         devaddr = devInRoomId.get('addr')
            #         devstatus = DBManagerDevice().getDeviceByDevId(devaddr)
            #         if devstatus == None:
            #             continue
            #         # 是否有设备离线了？
            #         devType = devstatus.get('type', None)
            #         lastStatusTime = devstatus.get('time', None)
            #         # 由于门锁的上报机制特殊，将门锁视为永久在线--modified by chenjc
            #         if devType != 'Camera' and devType != 'Lock' and lastStatusTime != None:
            #             now = int(time.time())
            #
            #             if now > lastStatusTime and now - lastStatusTime > 60*30:
            #                 roomdevoffline = False  # 不显示离线信息
            #
            #         ## 是否有灯开着
            #         devType = devstatus.get('type')
            #         if 'Light' not in devType:
            #             continue
            #         devVs = devstatus.get('value')
            #         if devVs != None:  # 手动添加虚假设备时没有value这一项，会导致
            #             for key in devVs.keys():
            #                 if 'state' in key:
            #                     lightV =  devVs.get(key)
            #                     if str(lightV) != '0':
            #                         # on
            #                         roomLightOn = True
            #                         break
            #         ##
            #         if roomLightOn == True and roomdevoffline == True:
            #             ##
            #             break
            #
            #     if roomLightOn == True:
            #         # roomId has light on
            #         light[roomId] = 'on'
            #     if roomdevoffline == True:
            #         offline[roomId] = 'offline'
            # glb['light'] = light
            # glb['offline'] = offline
        except Exception as err:
            Utils.logError("===>readGlobalData error: %s" % err)
            glb = {}
        return (ErrorCode.SUCCESS, glb)

    def readHostConfig(self, config):
        if config == None:
            return (ErrorCode.ERR_INVALID_REQUEST, None)
        Utils.logDebug("->readHostConfig %s"%(config))
        jsonobj = config
        hostId = jsonobj.get("hostId")
        # 如果是查询到的host信息中没有room信息，从room表查询房间信息后加入到host表，并更新到host表中
        hostdetail = DBManagerHostId().getByHostId(hostId)

        # 加上判断 hostdetail 是否为空，在直连切换网关时仍会带着目标网关的Mac在现网关中去查询，此时是查询不到网关信息的
        # 这种情况下返回错误码而非成功的响应码，经测试可以防止APP上出现房间列表一闪而过又重新加载的现象
        if hostdetail:
            try:
                if not hostdetail.has_key("room"):
                    Utils.logInfo("host prop room list is empty")
                    room_list = DBManagerRoom().getInfoOfAllRooms()
                    Utils.logInfo("room_list is " + str(room_list))
                    if room_list is not None and len(room_list) > 0:
                        hostdetail["room"] = room_list
                        DBManagerHostId().updateHostDetail(hostdetail, hostId)
            except AttributeError as e:
                Utils.logError("host prop error! hostId is param is %s" % str(hostId))
        else:
            return (ErrorCode.ERR_INVALID_REQUEST, hostdetail)

        # 返回给网关。读取类命令不会从云端下发，只可能是网关直连的方式
        # return (ErrorCode.SUCCESS, hostdetail)
        return self.returnByTimestamp(config, hostdetail)

    def checkstate(self, config):
        Utils.logDebug("checking host state....")
        return (ErrorCode.SUCCESS, {"state": "1"})  # 网关能够收到来自云端的请求说明网关在线，直接返回即可

    # 修改用户密码参数: {"name":"admin","password":"admin","email":"admin@163.com","mobile":"1391919199"}
    def modifyUserProperty(self, param):

        Utils.logDebug("->modifyUser()")
        # self.autoCreateAdmin()
        userName =  param.get("username","");
        hostId = param.get("hostId", None)
        if(userName == ""):
            return (ErrorCode.ERR_INVALID_PARAMS, None)

        if Utils.get_mac_address() != hostId:
            Utils.logError('Invalid host properties. Please check app requests.')
            return (ErrorCode.ERR_GENERAL, "无效的主机配置(ID错误)")

        curTime = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S');
        try:
            userObj = DBManagerUser().getUserDetailBy(userName)
            if(userObj == None):
                return (ErrorCode.ERR_GENERAL, "没有这个用户！")
            #修改admin用户信息
            newpass = param.get("password", None)
            if(newpass is not None):
                userObj["password"] = newpass
            mobile = param.get("mobile", None)
            if(mobile is not None):
                userObj["mobile"] = mobile
            email = param.get("email", None)
            if(email is not None):
                userObj["email"] = email
            updatetime = userObj.get("createtime", None)
            if(updatetime is None):
                updatetime = curTime
            userObj["updatetime"] = curTime

            DBManagerUser().saveUser(userObj)
            return (ErrorCode.SUCCESS, userObj)
        except:
            return (ErrorCode.ERR_GENERAL, None)


    #修改网关名称
    def modifyHostName(self, payload):
        hostId = payload.get("hostId", None)
        hostName = payload.get("hostName", None)

        if hostId == None or hostName == None:
            return (ErrorCode.ERR_INVALID_REQUEST, None)

        host = DBManagerHostId().getByHostId(hostId)

        if host == None:
            ##必须初始化过
            return (ErrorCode.ERR_GENERAL, None)
        else:
            if Utils.get_mac_address() != hostId:
                Utils.logError('Invalid host properties. Please check app requests.')
                return (ErrorCode.ERR_GENERAL, "无效的主机配置(ID错误)")

            result = DBManagerHostId().setHostName(hostName)

        if result is not None:
            self.backupToClould("hostconfig", result)
            return (ErrorCode.SUCCESS, None)
        else:
            return (ErrorCode.ERR_GENERAL, None)

    # 修改网关属性
    def modifyHostProperty(self, sparam):

        if sparam is None:
            return ErrorCode.ERR_INVALID_REQUEST, None

        Utils.logDebug("->modifyHostProperty %s"%(sparam))
        detailObj = sparam.get("detail", None)
        if detailObj is None:
            return ErrorCode.ERR_INVALID_PARAMS, None

        ##app有时会篡改网关属性，导致有些字段被删除，特此防御！
        softver = detailObj.get("softver", None)
        if (softver == None):
            return ErrorCode.ERR_INVALID_REQUEST, None

        hostId = detailObj.get("hostId")
        hostName = detailObj.get("name")
        host = DBManagerHostId().getByHostId(hostId)
        success = True
        if host is None:
            # 必须初始化过
            return ErrorCode.ERR_GENERAL, None
        else:
            if Utils.get_mac_address() != hostId:
                Utils.logError('Invalid host properties. Please check app requests.')
                return ErrorCode.ERR_GENERAL, "无效的主机配置(ID错误)"
            oldtimestamp = None
            if host.has_key("timestamp"):
                oldtimestamp = host.get("timestamp")

            newtimestamp = None
            if detailObj.has_key("timestamp"):
                newtimestamp = detailObj.get("timestamp")
            if oldtimestamp != None and newtimestamp != oldtimestamp:
                return ErrorCode.SUCCESS, host
            hostProp = DBManagerHostId().updateHostConfig(hostId, hostName, detailObj, oldtimestamp)
        if hostProp != None:
            self.backupToClould("hostconfig", detailObj)
            return ErrorCode.SUCCESS, detailObj
        else:
            return ErrorCode.ERR_GENERAL, None

    # 修改模式名称, sparam:{"modeId":1, "tag":"new name"}
    def modifyModeName(self, sparam):

        if sparam is None:
            return ErrorCode.ERR_INVALID_REQUEST, None

        modeId = sparam.get("modeId", None)
        newModeName = sparam.get("tag", "")
        mode_set = sparam.get("set", "")

        if modeId is None:
            return ErrorCode.ERR_INVALID_REQUEST, None

        result = DBManagerAction().modifyModeName(modeId, newModeName)

        # 打开或者关闭开门模式
        if mode_set is not None and mode_set != "":
            switch_set = DBManagerAction().switch_door_open_mode(modeId, mode_set)
            if switch_set is False:
                Utils.logError("打开或关闭开门模式出现错误...")

        if result is True:
            # 发送同步模式名的命令
            new_dev_props = []
            ctrlParams = []
            lcd_lists = DBManagerDeviceProp().getLcdSwitchByModeId(modeId)
            if lcd_lists:
                for index, lcd in lcd_lists:
                    modecfg = lcd.get("modecfg", {})
                    modecfg[index] = modeId
                    new_dev_props.append(lcd)

                    if isinstance(newModeName, unicode):
                        newModeName = newModeName.encode("utf-8")

                    value = {
                        "state": newModeName,
                        "index": int(index),
                        "controlType": 3
                    }
                    ctrlParam = {
                        'addr': lcd.get('addr'),
                        'type': lcd.get('type', 'LcdSwitch'),
                        'value': value
                    }

                # 更新设备信息中的模式名
                DBManagerDeviceProp().updateLcdModeName(new_dev_props)

                ctrlParams.append(ctrlParam)
                if len(ctrlParams) > 0:
                    #  将同步模式名字命令发出
                    pub.sendMessage(GlobalVars.PUB_CONTROL_DEVICE, cmd="controlDevice", controls=ctrlParams)

            # 如果该模式配置在了中控面板上，需要同步
            v_type = 0xF
            devices_hgc = DBManagerHGC().getByVtype(v_type)
            if devices_hgc is not None and len(devices_hgc) > 0:
                for item in devices_hgc:
                    mode_hgc = item.get("controls")[0].get("modeId")
                    if int(mode_hgc) == int(modeId):
                        sparams = {}
                        sparams["hgc_addr"] = item.get("addr")
                        sparams["channel"] = item.get("channel")
                        sparams["v_type"] = item.get("v_type")
                        sparams["update"] = 0x01
                        sparams["new_name"] = sparam.get("tag")
                        pub.sendMessage("syncHgcDevices", sparam=sparams)

            return ErrorCode.SUCCESS, None
        else:
            return ErrorCode.ERR_GENERAL, None


    def removeRoomArea(self, roomId, areaId="1"):
        Utils.logDebug("->removeRoomArea() %s,%s" % (roomId, areaId))
        if roomId is None or areaId is None:
            return False
        #1. 删Room表
        #DBManagerRoom().deleteRoomByName(room)
        #2. 删Areas表
        DBManagerRoomArea().deleteAreaBy(roomId, areaId)
        #3. 更新DeviceProp表
        DBManagerDeviceProp().roomAreaRemoved(roomId, areaId)
        #4. 更新Action表
        #DBManagerAction().deleteActionsByRoom(room)
        return True

    def removeRoom(self, roomId):

        Utils.logDebug("->removeRoom() %s" % (roomId))
        if roomId is None:
            return False
        # 1. 删Room表
        DBManagerRoom().deleteRoomByRoomId(roomId)
        # 2. 删Areas表
        DBManagerRoomArea().deleteAreasByRoomId(roomId)
        # 3. 更新DeviceProp表
        DBManagerDeviceProp().roomRemoved(roomId)
        # 4. 更新Action表
        DBManagerAction().deleteActionsByRoom(roomId)
        # 5. 更新host表
        try:
            host_prop = DBManagerHostId().getHost()
            room_list = host_prop.get("room", None)
            if room_list is not None and len(room_list) > 0:
                for item in room_list:
                    if int(roomId) == int(item.get("roomId", 0)):
                        room_list.remove(item)
                        oldtimestamp = None
                        if host_prop.has_key("timestamp"):
                            oldtimestamp = host_prop.get("timestamp")
                        DBManagerHostId().updateHostConfig(host_prop.get("hostId"), host_prop.get("name"), host_prop, oldtimestamp)
        except Exception, err:
            Utils.logError("Error delete room while update tbl_host: %s" % err)
        return True

    ##是否是传感器的设备类型
    def isSensorDevType(self, devtype):
        sensor_list = [DEVTYPENAME_SMOKE_SENSOR, DEVTYPENAME_EXIST_SENSOR, DEVTYPENAME_ENVIROMENT_SENSOR,
         DEVTYPENAME_OXYGEN_CO2_SENSOR, DEVTYPENAME_CH4CO_SENSOR, DEVTYPENAME_WATER_SENSOR, DEVTYPENAME_RAY_SENSOR,
         DEVTYPENAME_FALL_SENSOR, DEVTYPENAME_SOS_SENSOR, DEVTYPENAME_GSM, DEVTYPENAME_CURTAIN_SENSOR, DEVTYPENAME_LASER_EGG] # 新增了门窗磁和红外幕帘
        if devtype in sensor_list:
            return True
        else:
            return False

    # 查询水电表地址和名称，如果没有名称则设为空
    def queryMeterAddrs(self, sparam):

        if sparam is None:
            return ErrorCode.ERR_INVALID_REQUEST, None

        type = sparam.get("type", None)
        if type is None:
            return ErrorCode.ERR_INVALID_REQUEST, None

        # 在tbl_device_prop表中查询
        result_prop = DBManagerDeviceProp().getDeviceByDevType(type)
        # 在tbl_device_status表中查询
        result_status = DBManagerDevice().getDeviceByDevType(type)

        # 将水电表地址和名称表存在result中
        result = {}
        devices = []
        if result_prop is not None:
            for item in result_prop:
                device = {}
                meter_addr = str(item.get("addr"))
                # if len(meter_addr) < 4:
                #     if type == "ElecMeter":
                #         meter_addr = "elec_" + meter_addr
                #     if type == "WaterMeter":
                #         meter_addr = "water_" + meter_addr
                #     if type == "GasMeter":
                #         meter_addr = "gas_" + meter_addr
                device["addr"] = meter_addr
                device["name"] = item.get("name", "")
                devices.append(device)

        # 需要判断一下devices中是否已有相同addr的设备记录
        if result_status is not None:
            if devices is not None and len(devices) > 0:
                for dev in devices:
                    for item in result_status:
                        if dev.get("addr") == item.get("addr"):
                            result_status.remove(item)
                if len(result_status) > 0:
                    for item in result_status:
                        device = {}
                        device["addr"] = item.get("addr")
                        device["name"] = ""
                        devices.append(device)
            else:
                for item in result_status:
                    device = {}
                    device["addr"] = item.get("addr")
                    device["name"] = ""
                    devices.append(device)

        result["devices"] = devices
        return ErrorCode.SUCCESS, result

    # 修改水电表名称
    def modifyMeterName(self, sparam):

        if sparam is None:
            return ErrorCode.ERR_INVALID_REQUEST, None

        addr = sparam.get("addr", None)
        type = sparam.get("type", None)
        name = sparam.get("name", None)
        if addr is None or type is None or name is None:
            return ErrorCode.ERR_INVALID_REQUEST, None

        ret = DBManagerDeviceProp().saveDeviceProperty(sparam)

        if ret is not None:
            return ErrorCode.SUCCESS, None
        return ErrorCode.ERR_GENERAL, None

    # 查询全局模式
    def queryGlobalMode(self):
        results = []
        globalModes = DBManagerAction().getGlobalModes()

        if globalModes is not None and len(globalModes) > 0:
            active_tasks = DBManagerTask().get_active_tasks()
            mode_id_list = list()
            if active_tasks:
                for task in active_tasks:
                    mode_id_list.append(task.get("modeId"))
            for item in globalModes:
                if item.get("name")[-4:] == u'\u6a21\u5f0f\u914d\u7f6e':
                    oneResult = dict()
                    mode_id = item.get("modeId")
                    oneResult["modeId"] = mode_id
                    oneResult["hasActiveTask"] = False
                    if mode_id_list and (int(mode_id) in mode_id_list or str(mode_id) in mode_id_list):
                        oneResult["hasActiveTask"] = True
                    oneResult["name"] = item.get("name")
                    oneResult["tag"] = item.get("tag", None)
                    oneResult["isCurrent"] = False
                    if item.get("modeId") == self.activedMode:
                        oneResult["isCurrent"] = True
                    results.append(oneResult)
            return ErrorCode.SUCCESS, results

        return ErrorCode.ERR_GENERAL, None

    def query_all_devices(self, sparam):

        if sparam is None:
            return ErrorCode.ERR_INVALID_REQUEST, None

        device_type = sparam.get("type", None)
        if device_type is None:
            return ErrorCode.ERR_INVALID_REQUEST, None

        result_dict = dict(newAlarmList=[])
        id_list = list()
        user_phone = sparam.get("userPhone", None)
        if user_phone:
            # 添加新产生的告警信息
            id_list, msg_list = DBManagerHistory().getNewAlarms(user_phone)
            # alarm_list = DBManagerHistory().getNewAlarms()
            if id_list and msg_list:
                Utils.logInfo("===>id_list: %s" % id_list)
                Utils.logInfo("===>msg_list: %s" % msg_list)
                result_dict["newAlarmList"] = msg_list

        result = list()

        # device_type == "all"，把所有的记录都返回
        if device_type == "all":
            try:
                all_props = DBManagerDeviceProp().getAllDevices()
                all_status = DBManagerDevice().get_all_status()
                if all_props is not None and all_status is not None:
                    for prop in all_props:
                        one_record = dict()
                        one_record["deviceProp"] = prop
                        one_record["deviceStatus"] = {}
                        nowTime = int(time.time())

                        status = all_status.get(prop.get("addr"), None)
                        if status:
                            d_type = status.get("type")  # 设备类型
                            if "time" in status.keys():
                                #  delos需要在设备列表显示是否在线，添加判断
                                lastStatusTime = status.pop("time")
                                if d_type not in ['Camera', 'Lock', 'Exist', 'Gsm', 'CurtainSensor', 'Water',
                                                  'CircadianLight', 'N4'] and nowTime - lastStatusTime > 35 * 60:  # 排除几种弱电传感器
                                    status["offline"] = 1  # 离线
                                else:
                                    # 摄像头和门锁情况特殊，需要永远显示成在线
                                    status["offline"] = 0  # 在线
                            else:
                                status["offline"] = 0

                            type_in_prop = prop.get("type")
                            # 如果不是红外设备，只需比较mac地址
                            if type_in_prop != "TV" and type_in_prop != "IPTV" and type_in_prop != "DVD" and type_in_prop != "AirCondition":
                                if prop.get("addr") == status.get("addr"):
                                    one_record["deviceStatus"] = status
                            # delos中红外设备给一个默认的在线状态
                            else:
                                status = {"offline": 0, "keyId": prop.get("keyId"), "type": prop.get("type"),
                                          "addr": prop.get("addr"), "name": prop.get("name")}
                                one_record["deviceStatus"] = status
                        else:
                            typeTemp = prop.get("type")
                            offline = 1
                            if typeTemp == "CircadianLight":
                                offline = 0
                            status = {"offline": offline, "keyId": prop.get("keyId"), "type": prop.get("type"),
                                      "addr": prop.get("addr"), "name": prop.get("name")}
                            one_record["deviceStatus"] = status
                        result.append(one_record)
                    # return ErrorCode.SUCCESS, result
            except Exception as err:
                Utils.logError("query_all_devices() exception... %s" % err)
                return ErrorCode.ERR_GENERAL, None

        # 根据type，返回同类型的所有记录
        # 格式：[{"deviceProp": {prop...}, "deviceStatus": {status...}}, {}]
        else:
            try:
                all_props = DBManagerDeviceProp().getDeviceByDevType(device_type)
                all_status = DBManagerDevice().getDeviceByDevType(device_type, rtnDict=True)
                if all_props is not None and all_status is not None:
                    for prop in all_props:
                        one_record = dict()
                        one_record["deviceProp"] = prop
                        one_record["deviceStatus"] = {}
                        nowTime = int(time.time())

                        status = all_status.get(prop.get("addr"), None)
                        if status:
                            d_type = status.get("type")  # 设备类型
                            if "time" in status.keys():
                                #  delos需要在设备列表显示是否在线，添加判断
                                lastStatusTime = status.pop("time")
                                if d_type not in ['Camera', 'Lock', 'Exist', 'Gsm', 'CurtainSensor', 'Water',
                                                  'CircadianLight', 'N4'] and nowTime - lastStatusTime > 35 * 60:
                                    status["offline"] = 1  # 离线
                                else:
                                    # 摄像头和门锁情况特殊，需要永远显示成在线
                                    status["offline"] = 0  # 在线
                            else:
                                status["offline"] = 0

                            type_in_prop = prop.get("type")
                            # 如果不是红外设备，只需比较mac地址
                            if type_in_prop != "TV" and type_in_prop != "IPTV" and type_in_prop != "DVD" and type_in_prop != "AirCondition":
                                if prop.get("addr") == status.get("addr"):
                                    one_record["deviceStatus"] = status
                            # delos中红外设备给一个默认的在线状态
                            else:
                                status = {"offline": 0, "keyId": prop.get("keyId"), "type": prop.get("type"),
                                          "addr": prop.get("addr"), "name": prop.get("name")}
                                one_record["deviceStatus"] = status
                        else:
                            offline = 1
                            if device_type == "CircadianLight":
                                offline = 0
                            status = {"offline": offline, "keyId": prop.get("keyId"), "type": prop.get("type"),
                                      "addr": prop.get("addr"), "name": prop.get("name")}
                            one_record["deviceStatus"] = status
                        result.append(one_record)
                    # return ErrorCode.SUCCESS, result
            except Exception as err:
                Utils.logError("query_all_devices() by type... %s" % err)
                return ErrorCode.ERR_GENERAL, None
        result_dict["allDeviceList"] = result
        if user_phone and len(id_list) > 0:
            pub.sendMessage("updateUserList", id_list=id_list, user_phone=user_phone)
        return ErrorCode.SUCCESS, result_dict

    def set_time_task(self, sparam):

        Utils.logDebug("===>set_time_task()...")

        if sparam is None:
            return ErrorCode.ERR_INVALID_REQUEST, None

        task_id = sparam.get("id", None)
        task_type = sparam.get("type", None)
        mode_id = sparam.get("modeId", None)

        if task_type is None or mode_id is None:
            return ErrorCode.ERR_INVALID_REQUEST, None

        # 将触发时间转成时间戳
        if task_type == "delay":
            trigger_time = sparam.get("triggerTime", None)
            if not trigger_time:
                return ErrorCode.ERR_INVALID_REQUEST, None
            trigger_hour, trigger_min = trigger_time.split(":")
            local_time = time.localtime()
            current_hour, current_min = local_time.tm_hour, local_time.tm_min
            delta_hour = int(trigger_hour) - int(current_hour)
            delta_min = int(trigger_min) - int(current_min)
            delta_seconds = 3600*delta_hour + 60*delta_min
            if delta_seconds < 0:
                delta_seconds += 24*3600
            elif delta_seconds == 0:
                delta_seconds = 30
            current_ts = self.cast_time(int(time.time()))
            taskTimeStamp = current_ts + delta_seconds
            sparam["taskTimeStamp"] = taskTimeStamp

        try:
            if task_id is None or int(task_id) == 0:
                Utils.logDebug("===>set_time_task, task_id is None")
                old_task = DBManagerTask().get_by_name(mode_id)
                if old_task:
                    sparam["id"] = old_task.get("id")
                    DBManagerTask().update_task(sparam)
                else:
                    DBManagerTask().add_task(sparam)
            else:
                Utils.logDebug("===>set_time_task, update_task(sparam)")
                DBManagerTask().update_task(sparam)
            return ErrorCode.SUCCESS, None
        except Exception as err:
            Utils.logError("Set time task error: %s" % err)
            return ErrorCode.ERR_GENERAL, None

    def switch_time_task(self, sparam, task=None):

        Utils.logDebug("===>Switch time task...")

        if sparam is None:
            return ErrorCode.ERR_INVALID_REQUEST, None

        operation = sparam.get("switch", None)
        # task_type = sparam.get("type", None)
        task_type = None
        task_id = sparam.get("id", None)
        mode_id = sparam.get("modeId", None)

        if operation is None or (mode_id is None and task_id is None):
            return ErrorCode.ERR_INVALID_REQUEST, None

        try:
            if task_type:
                check_change = DBManagerTask().get_by_name("checkChange")
                if check_change is None:
                    return ErrorCode.ERR_GENERAL, None
                check_change[task_type] = operation
                check_change[task_type+"SwitchState"] = operation
                DBManagerTask().update_task(check_change)
                return ErrorCode.SUCCESS, None
            elif task_id:
                if task is None:
                    task = DBManagerTask().get_one_task(task_id)
                if operation == "off" and task.get("type") == "delay":
                    DBManagerTask().delete_task(task_id, modeId=mode_id)
                    return ErrorCode.SUCCESS, None
                task["switch"] = operation
                DBManagerTask().update_task(task)
                return ErrorCode.SUCCESS, None
            elif mode_id:
                if task is None:
                    task = DBManagerTask().get_by_name(mode_id)
                if operation == "off" and task.get("type") == "delay":
                    DBManagerTask().delete_task(task.get("id"), modeId=mode_id)
                    return ErrorCode.SUCCESS, None
                task["switch"] = operation
                DBManagerTask().update_task(task)
                return ErrorCode.SUCCESS, None
        except Exception as err:
            Utils.logError("Switch time task error: %s" % err)
            return ErrorCode.ERR_GENERAL, None

    def query_task_detail(self, sparam):
        if not sparam:
            return ErrorCode.ERR_INVALID_PARAMS, None
        task_id = sparam.get("id", None)
        mode_id = sparam.get("modeId", None)
        if not task_id and not mode_id:
            return ErrorCode.ERR_INVALID_PARAMS, None
        if task_id:
            task = DBManagerTask().get_one_task(task_id)
            return ErrorCode.SUCCESS, task
        elif mode_id:
            task = DBManagerTask().get_by_name(mode_id)
            return ErrorCode.SUCCESS, task

        return ErrorCode.ERR_GENERAL, None

    def query_task_switch_state(self):
        Utils.logDebug("===>queryTaskSwitchState...")
        result = dict()
        try:
            check_change = DBManagerTask().get_by_name("checkChange")
            if check_change is None:
                return ErrorCode.ERR_GENERAL, None
            result["delayState"] = check_change.get("delaySwitchState", "")
            result["repeatState"] = check_change.get("repeatSwitchState", "")
            return ErrorCode.SUCCESS, result
        except Exception as err:
            Utils.logError("queryTaskSwitchState error: %s" % err)
            return ErrorCode.ERR_GENERAL, None

    def set_floor_heating_time_task(self, sparam):
        if sparam is None:
            return ErrorCode.ERR_INVALID_REQUEST, None

        device_addr = sparam.get("addr", None)
        hgc_addr = sparam.get("hgcAddr", None)
        time_task = sparam.get("timeTask", None)
        operation = sparam.get("operation", None)
        task_switch = sparam.get("timeTaskSwitch", "on")

        if device_addr is None or hgc_addr is None or time_task is None or operation is None:
            return ErrorCode.ERR_INVALID_REQUEST, None

        device_prop = DBManagerDeviceProp().getDeviceByDevId(device_addr)
        if device_prop is None:
            return ErrorCode.ERR_GENERAL, None

        try:
            device_prop["timeTaskSwitch"] = task_switch
            if operation == "add":
                device_prop["timeTask"] = time_task
                DBManagerDeviceProp().saveDeviceProperty(device_prop)

            if operation == "updateWeekday":
                old_time_task = device_prop.get("timeTask")
                if old_time_task is None or len(old_time_task) == 0:
                    return ErrorCode.ERR_GENERAL, None
                else:
                    for item in old_time_task:
                        if item.get("type") == "weekday":
                            old_time_task.remove(item)
                            if isinstance(time_task, list):
                                new_item = time_task[0]
                            else:
                                new_item = time_task
                            old_time_task.append(new_item)
                    DBManagerDeviceProp().saveDeviceProperty(device_prop)

            if operation == "updateWeekend":
                old_time_task = device_prop.get("timeTask")
                if old_time_task is None or len(old_time_task) == 0:
                    return ErrorCode.ERR_GENERAL, None
                else:
                    for item in old_time_task:
                        if item.get("type") == "weekend":
                            old_time_task.remove(item)
                            if isinstance(time_task, list):
                                new_item = time_task[0]
                            else:
                                new_item = time_task
                            old_time_task.append(new_item)
                    DBManagerDeviceProp().saveDeviceProperty(device_prop)

            # 将定时信息同步到对应的中控设备
            sync_sparam = dict()
            sync_sparam["hgcAddr"] = hgc_addr
            sync_sparam["timeTask"] = device_prop.get("timeTask")
            sync_sparam["v_type"] = 0x52
            sync_sparam["timeTaskSwitch"] = device_prop.get("timeTaskSwitch")
            pub.sendMessage("syncFloorHeating", sparam=sync_sparam)

            return ErrorCode.SUCCESS, None
        except Exception as err:
            Utils.logError("set_floor_heating_time_task: %s" % err)
            return ErrorCode.ERR_GENERAL, None

    def switch_FL_time_task(self, sparam):

        if sparam is None:
            return ErrorCode.ERR_GENERAL, None

        device_addr = sparam.get("addr", None)
        hgc_addr = sparam.get("hgcAddr", None)
        new_switch = sparam.get("timeTaskSwitch", None)

        if device_addr is None or hgc_addr is None or new_switch is None:
            return ErrorCode.ERR_GENERAL, None

        device_prop = DBManagerDeviceProp().getDeviceByDevId(device_addr)
        if device_prop is None:
            return ErrorCode.ERR_GENERAL, None

        try:
            device_prop["timeTaskSwitch"] = new_switch
            DBManagerDeviceProp().saveDeviceProperty(device_prop)

            # 将定时信息同步到对应的中控设备
            sync_sparam = dict()
            sync_sparam["hgcAddr"] = hgc_addr
            sync_sparam["timeTask"] = device_prop.get("timeTask")
            sync_sparam["v_type"] = 0x52
            sync_sparam["timeTaskSwitch"] = device_prop.get("timeTaskSwitch")
            pub.sendMessage("syncFloorHeating", sparam=sync_sparam)

            return ErrorCode.SUCCESS, None
        except Exception as err:
            Utils.logError("switch_FL_time_task: %s" % err)
            return ErrorCode.ERR_GENERAL, None

    def generateToken(self, username):
        token = hashlib.sha1(os.urandom(24)).hexdigest() + username
        return token

    def normalLogin(self, sparam):
        if sparam is None:
            result = {"ret": ErrorCode.ERR_INVALID_PARAMS, "message": "参数错误"}
            return ErrorCode.ERR_INVALID_PARAMS, result

        username = sparam.get("username", None)
        password = sparam.get("password", None)
        if username is None or password is None:
            result = {"ret": ErrorCode.ERR_INVALID_PARAMS, "message": "参数错误"}
            return ErrorCode.ERR_INVALID_PARAMS, result

        old_user = DBManagerUser().getUserDetailBy(username)
        if old_user is None:
            result = {"ret": ErrorCode.ERR_GENERAL, "message": "用户不存在"}
            return ErrorCode.ERR_GENERAL, result

        try:
            if password == old_user.get("password", None):
                token = self.generateToken(username)
                old_user["token"] = token
                success = DBManagerUser().saveUser(old_user)
                if success is True:
                    result = {"ret": ErrorCode.SUCCESS, "message": "登陆成功", "token": token, "userInfo": old_user["userInfo"]}
                    return ErrorCode.SUCCESS, result
                else:
                    result = {"ret": ErrorCode.ERR_GENERAL, "message": "数据库错误"}
                    return ErrorCode.ERR_GENERAL, result
            else:
                result = {"ret": ErrorCode.ERR_GENERAL, "message": "用户名密码错误"}
                return ErrorCode.ERR_GENERAL, result
        except Exception as err:
            Utils.logError("===>login error: %s" % err)
            result = {"ret": ErrorCode.ERR_GENERAL, "message": "服务器内部错误"}
            return ErrorCode.ERR_GENERAL, result

    def authorizedLogin(self, sparam):

        if sparam is None:
            result = {"ret": ErrorCode.ERR_INVALID_PARAMS, "message": "参数错误"}
            return ErrorCode.ERR_INVALID_PARAMS, result

        username = sparam.get("username", None)
        if username is None:
            result = {"ret": ErrorCode.ERR_INVALID_PARAMS, "message": "参数错误"}
            return ErrorCode.ERR_INVALID_PARAMS, result

        try:
            token = self.generateToken(username)
            sparam["token"] = token
            success = DBManagerUser().saveUser(sparam)
            if success is True:
                result = {"ret": ErrorCode.SUCCESS, "message": "登陆成功", "token": token}
                return ErrorCode.SUCCESS, result
            else:
                result = {"ret": ErrorCode.ERR_GENERAL, "message": "数据库错误"}
                return ErrorCode.ERR_GENERAL, result
        except Exception as err:
            Utils.logError("===>authorizedLogin error: %s" % err)
            result = {"ret": ErrorCode.ERR_GENERAL, "message": "服务器内部错误"}
            return ErrorCode.ERR_GENERAL, result

    def logout(self, sparam):

        if sparam is None:
            result = {"ret": ErrorCode.ERR_INVALID_PARAMS, "message": "参数错误"}
            return ErrorCode.ERR_INVALID_PARAMS, result

        username = sparam.get("username", None)
        if username is None:
            result = {"ret": ErrorCode.ERR_INVALID_PARAMS, "message": "参数错误"}
            return ErrorCode.ERR_INVALID_PARAMS, result

        try:
            old_user = DBManagerUser().getUserDetailBy(username)
            if old_user is None:
                result = {"ret": ErrorCode.ERR_WRONG_USERNAME_PASSWORD, "message": "用户不存在"}
                return ErrorCode.ERR_GENERAL, result
            result = {"ret": ErrorCode.SUCCESS, "message": "退出登陆成功"}
            return ErrorCode.SUCCESS, result
        except Exception as err:
            Utils.logError("===>logout error: %s" % err)
            result = {"ret": ErrorCode.ERR_GENERAL, "message": "服务器内部错误"}
            return ErrorCode.ERR_GENERAL, result

    def saveUserInfo(self, param):
        if param is None:
            result = {"ret": ErrorCode.ERR_INVALID_PARAMS, "message": "参数错误"}
            return ErrorCode.ERR_INVALID_PARAMS, result

        username = param.get("username", None)
        user_info = param.get("userInfo", None)
        if username is None:
            result = {"ret": ErrorCode.ERR_INVALID_PARAMS, "message": "参数错误"}
            return ErrorCode.ERR_INVALID_PARAMS, result

        old_user = DBManagerUser().getUserDetailBy(username)
        if old_user is None:
            result = {"ret": ErrorCode.ERR_GENERAL, "message": "用户不存在"}
            return ErrorCode.ERR_GENERAL, result

        try:
            old_user["userInfo"] = user_info
            success = DBManagerUser().saveUser(old_user)
            if success is True:
                result = {"ret": ErrorCode.SUCCESS, "message": "保存成功"}
                return ErrorCode.SUCCESS, result
            else:
                result = {"ret": ErrorCode.ERR_GENERAL, "message": "数据库错误"}
                return ErrorCode.ERR_GENERAL, result
        except Exception as err:
            Utils.logError("===>saveUserInfo error: %s" % err)
            result = {"ret": ErrorCode.ERR_GENERAL, "message": "服务器内部错误"}
            return ErrorCode.ERR_GENERAL, result

    def deleteUser(self, param):
        if param is None:
            result = {"ret": ErrorCode.ERR_INVALID_PARAMS, "message": "参数错误"}
            return ErrorCode.ERR_INVALID_PARAMS, result

        username = param.get("username", None)
        if username is None:
            result = {"ret": ErrorCode.ERR_INVALID_PARAMS, "message": "参数错误"}
            return ErrorCode.ERR_INVALID_PARAMS, result

        old_user = DBManagerUser().getUserDetailBy(username)
        if old_user is None:
            result = {"ret": ErrorCode.ERR_GENERAL, "message": "用户不存在"}
            return ErrorCode.ERR_GENERAL, result

        try:
            success = DBManagerUser().deleteByKey({"username": username})
            if success is True:
                result = {"ret": ErrorCode.SUCCESS, "message": "删除成功"}
                return ErrorCode.SUCCESS, result
            else:
                result = {"ret": ErrorCode.ERR_GENERAL, "message": "数据库错误"}
                return ErrorCode.ERR_GENERAL, result
        except Exception as err:
            Utils.logError("===>delete user error: %s" % err)
            result = {"ret": ErrorCode.ERR_GENERAL, "message": "服务器内部错误"}
            return ErrorCode.ERR_GENERAL, result

    # 查询全部模式，包括全局模式和房间模式
    def getAllModesForPannel(self, payload):
        mode_dict = DBManagerAction().getAllModesForPannel()
        if mode_dict:
            for room_id in mode_dict.keys():
                if room_id != "globalModeList":
                    room_detail = DBManagerRoom().getRoomByRoomId(int(room_id))
                    if room_detail is None:
                        mode_dict.pop(room_id)
                    else:
                        room_name = room_detail.get("name")
                        mode_dict[room_name] = mode_dict.pop(room_id)
        return ErrorCode.SUCCESS, mode_dict

    # 数据展示屏获取有空气质量检测仪的房间列表（原来使用的是镭豆，现改用空气质量检测仪'AirSensor'）
    def query_rooms_leidou(self, payload):
        ld_list = DBManagerDeviceProp().getLaserEggForScreen()
        result = dict(rooms=ld_list)
        return ErrorCode.SUCCESS, result


    # 计算时间，省去秒数
    def cast_time(self, timestamp):
        time_array = time.localtime(timestamp)
        time_str = time.strftime("%Y-%m-%d-%H-%M-%S", time_array)
        time_arr = time_str.split("-")
        time_arr[-1] = '0'
        time_str_r = ''
        for index, s in enumerate(time_arr):
            if index == 0:
                time_str_r = time_str_r + s
            else:
                time_str_r = time_str_r + "-" + s
        timeArray = time.strptime(time_str_r, "%Y-%m-%d-%H-%M-%S")
        return int(time.mktime(timeArray))

if __name__ == '__main__':
    s = SocketHandlerServer(105)
    (ret, dic) = s.readGlobalData({})
    print '####ret:', ret, ',result:', dic
