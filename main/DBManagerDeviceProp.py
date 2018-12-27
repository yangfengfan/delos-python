#!/usr/bin/python
# -*- coding: utf-8 -*-

import random
import DBUtils
import GlobalVars
import Utils
import threading
import json
import time
import ErrorCode


#设备表数据库名
TABLE_NAME_DEVICE_PROP = "tbl_device_prop"


KEY_ID = "id"
KEY_VERSION = "version"
#KEY_HOST_ID = "hostId"          #设备所在的网关，服务端可动态获取hostId
KEY_DEVICE_ADDR = "addr"      #设备Id/Mac
KEY_DEVICE_NAME = "name"        #设备名称   ##一个红外设备能挂空调，电视等多个设备，以mac地址一样，以name区分
KEY_DEVICE_ROOM = "roomId"        #设备所在的房间
KEY_DEVICE_AREA = "areaId"        #设备所在的功能区
KEY_DEVICE_TYPE = "type"        #设备类型，开关，灯，摄像头，传感器
KEY_DEVICE_DETAIL = "detail"    #详细json


###所有的device属性都添加一个"timestamp"，表明当前的device属性更新时间。
###属性同步到云端后，云端可根据timestamp决定哪个同步命令是最新的，从而不会拿旧的属性覆盖新的属性
###备份时不能修改"timestamp"的值。
class DBManagerDeviceProp(object):
    __instant = None
    __lock = threading.Lock()
    
    #singleton
    def __new__(self):
        Utils.logDebug("__new__")
        if(DBManagerDeviceProp.__instant==None):
            DBManagerDeviceProp.__lock.acquire();
            try:
                if(DBManagerDeviceProp.__instant==None):
                    Utils.logDebug("new DBManagerDeviceProp singleton instance.")
                    DBManagerDeviceProp.__instant = object.__new__(self);
            finally:
                DBManagerDeviceProp.__lock.release()
        return DBManagerDeviceProp.__instant

    def __init__(self):  
        Utils.logDebug("__init__")
        self.tablename = TABLE_NAME_DEVICE_PROP
        self.tableversion = 1
        self.createDevicePropTable()

    def createDevicePropTable(self):
        Utils.logDebug("->createDevicePropTable")
        create_table_sql = "CREATE TABLE IF NOT EXISTS '" + self.tablename + "' ("
        create_table_sql += " `" + KEY_ID + "` INTEGER primary key autoincrement,"
        create_table_sql += " `" + KEY_VERSION + "` INTEGER NOT NULL,"
        create_table_sql += " `" + KEY_DEVICE_ADDR + "` varchar(50) NOT NULL,"
        create_table_sql += " `" + KEY_DEVICE_NAME + "` varchar(50) NOT NULL,"
        create_table_sql += " `" + KEY_DEVICE_TYPE + "` varchar(20) NOT NULL,"
        create_table_sql += " `" + KEY_DEVICE_ROOM + "` varchar(10),"
        create_table_sql += " `" + KEY_DEVICE_AREA + "` varchar(10),"
        create_table_sql += " `" + KEY_DEVICE_DETAIL + "` TEXT,"
        create_table_sql += " UNIQUE (" + KEY_DEVICE_ADDR + ", " + KEY_DEVICE_NAME + ") "
        create_table_sql += " )"
        conn = DBUtils.get_conn()
        DBUtils.create_table(conn, create_table_sql)

    ##检查数据库文件状态
    ##host.db存放配置数据
    ##如果数据库文件损坏，fetchall()应抛出异常
    def checkDBHealthy(self):
        conn = DBUtils.get_conn()
        sql = "select * from " + self.tablename
        DBUtils.fetchall(conn, sql)

    # 增加newDeviceProperty的目的：
    # 数据库因异常原因，某个设备属性残留在数据库中没有清除
    # app再次扫描添加绑定同一个mac的设备时总是失败。
    # newDeviceProperty是在扫描添加新设备时调用
    def newDeviceProperty(self, detailObj, batch=None):
        Utils.logDebug("->newDeviceProperty %s"%(detailObj))
        if(detailObj is None):
            Utils.logError('newDeviceProperty() rx invalid inputs %s'%(detailObj))
            return None
        try:
            # keyId= detailObj.get('keyId', None)   ##扫描时添加设备，不会携带KeyId
            detailObj["favorite"] = "0"  # 将常用设备字段默认赋值为0表示非常用设备
            deviceAddr = detailObj.get(KEY_DEVICE_ADDR, None)
            if deviceAddr == None or deviceAddr == "":
                return None
            name = detailObj.get(KEY_DEVICE_NAME, "")
            if name == None or name == "":
                return None

            # hostId = detailObj.get(KEY_HOST_ID, None)
            devType = detailObj.get(KEY_DEVICE_TYPE, None)
            roomId = detailObj.get(KEY_DEVICE_ROOM, None)
            area = detailObj.get(KEY_DEVICE_AREA, None)
            dismissIndetail = detailObj.get("dismiss", True)
            if dismissIndetail:
                detailObj['dismiss'] = True
            else:
                detailObj['dismiss'] = False

            if str(roomId) == "-1" and str(area) == "-1":
                pass  # 这种情况是批量添加的设备，不去改变areaId的值
            elif roomId:
                area = "1"
                detailObj["areaId"] = "1"
            else:
                area = None

            # 新的地暖不再有任务列表 2018-1122-chenjc
            # if devType == "FloorHeating":
            #     time_task = [{"taskList": [], "type": "weekday"}, {"taskList": [], "type": "weekend"}]
            #     detailObj["timeTask"] = time_task

            # newtimestamp = None
            # if detailObj.has_key("timestamp"):
            #     newtimestamp = detailObj.get("timestamp")

            devAllDetailJsonStr = None
            success = True
            devItem = None

            # if keyId != None:
            #     devItem = self.getDeviceByKeyId(keyId)
            # else:
            #     keyId, devItem = self.getDeviceByAddrName(deviceAddr, name)

            # 判断设备类型，如果是红外设备（电视，空调等），允许一个mac地址对应多个设备
            if devType == "TV" or devType == "IPTV" or devType == "DVD" or devType == "AirCondition":

                devItem = self.getDeviceByDevAddrAndType(deviceAddr, devType)  # TODO 为了限制红外转发只能有一个同类型的设备。验证此处逻辑，20170322
                # keyId, devItem = self.getDeviceByAddrName(deviceAddr, name)
                if (devItem is None):
                    detailObj["timestamp"] = int(time.time())
                    devAllDetailJsonStr = json.dumps(detailObj)
                    save_sql = "INSERT INTO " + self.tablename + " values (?,?,?,?,?,?,?,?)"
                    data = [(None, self.tableversion, deviceAddr, name, devType, roomId, area, devAllDetailJsonStr)]
                    conn = DBUtils.get_conn()
                    DBUtils.save(conn, save_sql, data)

                    ## 找到Id，并更新到detail里
                    keyId, devItem = self.getDeviceByAddrName(deviceAddr, name)
                    ## keyId found.
                else:
                    #更新设备属性，需判断是否会污染
                    # oldtimestamp = devItem.get("timestamp", None)
                    # if oldtimestamp != None and newtimestamp != oldtimestamp:
                    #     return devItem
                    # detailObj["timestamp"] = int(time.time())
                    return ErrorCode.ERR_CMD_DUPLICATE_DEVICE  # TODO 验证这里判断设备已存在逻辑是否正确

            else:
                keyId, devItem = self.getDeviceByDevId_2(deviceAddr)
                if devItem is None:
                    detailObj["timestamp"] = int(time.time())
                    devAllDetailJsonStr = json.dumps(detailObj)
                    save_sql = "INSERT INTO " + self.tablename + " values (?,?,?,?,?,?,?,?)"
                    data = [(None, self.tableversion, deviceAddr, name, devType, roomId, area, devAllDetailJsonStr)]
                    conn = DBUtils.get_conn()
                    DBUtils.save(conn, save_sql, data)

                    # 找到Id，并更新到detail里
                    keyId, devItem = self.getDeviceByAddrName(deviceAddr, name)

                else:
                    # 把keyId取出来
                    # detailObj["timestamp"] = int(time.time())
                    return ErrorCode.ERR_CMD_DUPLICATE_DEVICE

            detailObj['keyId'] = keyId
            update_sql = 'UPDATE ' + self.tablename + ' SET '
            update_sql += ' ' + KEY_DEVICE_TYPE + ' = ? '
            update_sql += ',' + KEY_DEVICE_ADDR + ' = ? '
            update_sql += ',' + KEY_DEVICE_NAME + ' = ? '
            update_sql += ',' + KEY_DEVICE_ROOM + ' = ? '
            update_sql += ',' + KEY_DEVICE_AREA + ' = ? '
            update_sql += ',' + KEY_DEVICE_DETAIL + ' = ? '
            update_sql += ' WHERE '+ KEY_ID + ' = ? '
            #把缺失的属性从数据库补齐
            if roomId == None:
                roomId = devItem.get(KEY_DEVICE_ROOM, None)
                detailObj[KEY_DEVICE_ROOM] = roomId
            if area == None:
                if roomId:
                    area = "1"
                    detailObj["areaId"] = "1"
                else:
                    area = ""
                detailObj[KEY_DEVICE_AREA] = area
            if devType == None:
                devType = devItem.get(KEY_DEVICE_TYPE, None)
                detailObj[KEY_DEVICE_TYPE] = devType

            # detailObj['dismiss'] = False
            # if batch:
            #     detailObj['dismiss'] = True
            detailObj['dismiss'] = True  # delos版本单个扫描时也是在房间外扫描，不包含房间信息，所以dimiss默认True
            if roomId:  # delos在单个扫描时候可以直接分配房间，所以roomId不为空或空字符串时dismiss要置为False
                detailObj['dismiss'] = False
            devAllDetailJsonStr = json.dumps(detailObj)
            data = [(devType, deviceAddr, name, roomId, area, devAllDetailJsonStr, keyId)]
            conn = DBUtils.get_conn()
            success = DBUtils.update(conn, update_sql, data)
            if success == True:
                Utils.logInfo('after create device prop:%s'%(detailObj))
                return detailObj
        except:
            Utils.logException('newDeviceProperty()异常')
        return None

    # detailJsonStr是设备详情所有属性的Json格式化串
    def saveDeviceProperty(self, detailObj):
        Utils.logDebug("->saveDeviceProperty %s"%(detailObj))
        if(detailObj is None):
            Utils.logError('saveDeviceProperty() rx invalid inputs %s'%(detailObj))
            return None
        try:
            keyId = detailObj.get('keyId', None)
            deviceAddr = detailObj.get(KEY_DEVICE_ADDR, None)
            if deviceAddr == None or deviceAddr == "":
                return None
            name = detailObj.get(KEY_DEVICE_NAME, "")
            if name == None or name == "":
                return None

            # hostId = detailObj.get(KEY_HOST_ID, None)
            devType = detailObj.get(KEY_DEVICE_TYPE, None)
            roomId = detailObj.get(KEY_DEVICE_ROOM, None)
            dismissIndetail = detailObj.get("dismiss", True)
            if dismissIndetail:
                detailObj['dismiss'] = True
            else:
                detailObj['dismiss'] = False

            if roomId:
                area = "1"
                detailObj["areaId"] = "1"
            else:
                area = None

            newtimestamp = None
            if detailObj.has_key("timestamp"):
                newtimestamp = detailObj.get("timestamp")

            devAllDetailJsonStr = None
            success = True
            devItem = None
            if keyId != None:
                keyId = int(keyId)
                devItem = self.getDeviceByKeyId(keyId)
            elif devType == "ElecMeter" or devType == "WaterMeter" or devType == "GasMeter":
                keyId, devItem = self.getDeviceByAddrType(deviceAddr, devType)
            else:
                keyId, devItem = self.getDeviceByAddrName(deviceAddr, name)

            if devItem is None:
                detailObj["timestamp"] = int(time.time())
                devAllDetailJsonStr = json.dumps(detailObj)
                save_sql = "INSERT INTO " + self.tablename + " values (?,?,?,?,?,?,?,?)"
                data = [(None, self.tableversion, deviceAddr, name, devType, roomId, area, devAllDetailJsonStr)]
                conn = DBUtils.get_conn()
                DBUtils.save(conn, save_sql, data)

                # 找到Id，并更新到detail里
                keyId, devItem = self.getDeviceByAddrName(deviceAddr, name)
                # keyId found.
            else:
                # 更新设备属性，需判断是否会污染
                # oldtimestamp = devItem.get("timestamp", None)
                # if oldtimestamp != None and newtimestamp != oldtimestamp:
                #     if devType == "ElecMeter" or devType == "WaterMeter" or devType == "GasMeter":
                #         pass
                #     else:
                #         return devItem
                # detailObj["timestamp"] = int(time.time())
                if devType != "TV" and devType != "IPTV" and devType != "DVD" and devType != "AirCondition":
                    keyId_db, devItem_db = self.getDeviceByDevId_2(deviceAddr)
                    if keyId_db is not None and keyId_db != "" and int(keyId_db) != int(keyId):
                        return ErrorCode.ERR_CMD_DUPLICATE_DEVICE

            detailObj['keyId'] = keyId
            update_sql = 'UPDATE ' + self.tablename + ' SET '
            update_sql += ' ' + KEY_DEVICE_TYPE + ' = ? '
            update_sql += ',' + KEY_DEVICE_ADDR + ' = ? '
            update_sql += ',' + KEY_DEVICE_NAME + ' = ? '
            update_sql += ',' + KEY_DEVICE_ROOM + ' = ? '
            update_sql += ',' + KEY_DEVICE_AREA + ' = ? '
            update_sql += ',' + KEY_DEVICE_DETAIL + ' = ? '
            update_sql += ' WHERE ' + KEY_ID + ' = ? '
            # 把缺失的属性从数据库补齐
            if roomId == None:
                roomId = devItem.get(KEY_DEVICE_ROOM, None)
                detailObj[KEY_DEVICE_ROOM] = roomId
            if area == None:
                if roomId:
                    area = "1"
                    detailObj["areaId"] = "1"
                else:
                    area = ""
            if devType == None:
                devType = devItem.get(KEY_DEVICE_TYPE, None)
                detailObj[KEY_DEVICE_TYPE] = devType

            detailObj['dismiss'] = True  # delos版本单个扫描时也是在房间外扫描，不包含房间信息，所以dimiss默认True
            if roomId:  # delos在单个扫描时候可以直接分配房间，所以roomId不为空或空字符串时dismiss要置为False
                detailObj['dismiss'] = False
            devAllDetailJsonStr = json.dumps(detailObj)
            data = [(devType, deviceAddr, name, roomId, area, devAllDetailJsonStr, keyId)]
            conn = DBUtils.get_conn()
            success = DBUtils.update(conn, update_sql, data)
            if success == True:
                Utils.logInfo('after update device prop:%s'%(detailObj))
                return detailObj
        except:
            Utils.logException('saveDeviceProperty()异常')
        return None
            
    # def _getByCondition(self, where, data):
    #     conn = DBUtils.get_conn()
    #     sql = "select * from " + self.tablename + " " + where
    #     return DBUtils.fetchByCondition(conn, sql, data)

    # 返回满足条件的所有设备的json格式串 组成的数组
    def getByKey(self, key, data):
        deviceDict = {}
        if(data is None or data == "" or key is None):
            Utils.logError('DBManagerDeviceProp: getByKey has invalid where condition')
            return deviceDict.values()
        try:
            conn = DBUtils.get_conn()
            sql = "select * from " + self.tablename + " where " + key + " = '"+ data + "'"
            devarr = DBUtils.fetchall(conn, sql)
            # devarr应该是[(id, deviId, hostId, type, roomId, area, detail),(...)]数组格式
            if(devarr is not None):
                for dev in devarr:
                    detail = json.loads(dev[-1])
                    if detail == None or len(detail) == 0:
                        continue
                    detail['keyId'] = dev[0]
                    deviceDict[dev[0]] = detail        # detail总是应该放在最后的字段
        except:
            Utils.logException('getByKey()异常')
            deviceDict.clear()
        return deviceDict.values()
        
    def deleteByKey(self, key, data):
        if(data is None or data == "" or key is None):
            Utils.logError('deleteByKey has invalid where condition')
            return False
        try:
            conn = DBUtils.get_conn()
            sql = "DELETE FROM " + self.tablename + " WHERE " + key + " = '" + data + "'"
            DBUtils.deleteone(conn, sql)
            return True
        except:
            Utils.logException('deleteByKey()异常')
            return False

    def getAllDevices(self):
        Utils.logDebug("->getAllDevices()")
        deviceDict = {}
        try:
            conn = DBUtils.get_conn()
            sql = "select * from " + self.tablename
            devarr = DBUtils.fetchall(conn, sql)
            # devarr应该是[{"id":"ss", "deviId":"ss", hostId, type, roomId, area, detail),(...)]数组格式
            if(devarr is not None):
                for dev in devarr:
                    # deviceDict[dev[0]] = json.loads(dev[-1])        # detail总是应该放在最后的字段
                    detail = json.loads(dev[-1])
                    if detail == None or len(detail) == 0:
                        continue
                    detail['keyId'] = dev[0]
                    deviceDict[dev[0]] = detail        # detail总是应该放在最后的字段
        except:
            Utils.logException('getAllDevices()异常')
            deviceDict.clear()
        if deviceDict is None or len(deviceDict) == 0:
            return None
        return deviceDict.values()
        
    # 返回json格式串
    def getDeviceByDevId(self, deviceAddr):
        Utils.logDebug("->getDeviceByDevId %s"%(deviceAddr))
        result = self.getByKey(KEY_DEVICE_ADDR, deviceAddr)
        if(result == None or len(result) == 0):
            return None
        else:
            return result[0]    #返回json

    # 返回keyID 和 json格式串
    def getDeviceByDevId_2(self, deviceAddr):
        try:
            conn = DBUtils.get_conn()
            sql = "select * from " + self.tablename + " where addr = '" + deviceAddr + "'"
            Utils.logInfo('sql:%s'%(sql))
            devarr = DBUtils.fetchall(conn, sql)
            if devarr is not None:
                for dev in devarr:
                    detail = json.loads(dev[-1])
                    return dev[0], detail
        except:
            Utils.logException('getDeviceByAddrName failed.')
        return None, None

    # 通过设备地址和类型查询，返回key_id和json格式串
    def getDeviceByAddrType(self, deviceAddr, devType):
        Utils.logDebug("->getDeviceByAddrName %s"%(deviceAddr))
        try:
            # if isinstance(name, unicode):
            #     name = name.encode('utf8')
            #     Utils.logInfo('name after encode:%s'%(name))
            conn = DBUtils.get_conn()
            # sql = "select * from " + self.tablename + " where addr = '"+ deviceAddr + "' and name = '" + name + "'"
            sql = "select * from " + self.tablename + " where addr = '" + deviceAddr + "' and type = '" + devType + "'"
            Utils.logInfo('sql:%s'%(sql))
            dev = DBUtils.fetchall(conn, sql)
            if (dev is not None and len(dev) != 0):
                detail = json.loads(dev[0][-1])
                return (dev[0][0], detail)
        except:
            Utils.logException('getDeviceByAddrName failed.')
        return (None, None)

    # 返回json格式串
    def getDeviceByAddrName(self, deviceAddr, name):
        Utils.logDebug("->getDeviceByAddrName %s"%(deviceAddr))
        try:
            # if isinstance(name, unicode):
            #     name = name.encode('utf8')
            #     Utils.logInfo('name after encode:%s'%(name))
            conn = DBUtils.get_conn()
            # sql = "select * from " + self.tablename + " where addr = '"+ deviceAddr + "' and name = '" + name + "'"
            sql = "select * from " + self.tablename + " where addr = '" + deviceAddr + "'"
            Utils.logInfo('sql:%s'%(sql))
            devarr = DBUtils.fetchall(conn, sql)
            if (devarr is not None):
                for dev in devarr:
                    detail = json.loads(dev[-1])
                    if detail.get('name', None) == name:
                        detail['keyId'] = dev[0]
                        return (dev[0], detail)
        except:
            Utils.logException('getDeviceByAddrName failed.')
        return (None, None)

    #  根据设备地址和类型返回设备记录
    def getDeviceByDevAddrAndType(self, addr, dev_type):

        # devices = self.getDeviceByDevType(dev_type)
        # if devices is not None and len(devices) >0:
        #     for item in devices:
        #         if item.get("addr") == addr:
        #             return item
        try:
            sql = "select * from " + self.tablename + " where addr=? and type='%s'" % dev_type
            Utils.logInfo("sql: %s" % sql)
            conn = DBUtils.get_conn()
            dev_prop = DBUtils.fetchone(conn, sql, addr)
            if dev_prop:
                return json.loads(dev_prop[-1])
            else:
                return None
        except:
            Utils.logError("getDeviceByDevAddrAndType() error...")
        return None

    # 根据设备类型返回设备设备记录
    def getDeviceByDevType(self, deviceType):
        Utils.logDebug("->getDeviceByDevType %s"%(deviceType))
        try:
            conn = DBUtils.get_conn()
            sql = "select * from " + self.tablename + " where type = '" + deviceType + "'"
            Utils.logInfo('sql:%s'%(sql))
            devarr = DBUtils.fetchall(conn, sql)
            result = []
            if devarr is not None:
                for item in devarr:
                    result.append(json.loads(item[-1]))
            return result
        except:
            Utils.logException('getDeviceByDevType failed.')
        return None

    # 查询镭豆设备的UDID列表
    def getLaserEggIdList(self):
        laserEggList = self.getDeviceByDevType('LaserEgg')
        laserEggIdList = []

        for laserEgg in laserEggList:
            laserEggIdList.append(laserEgg.get('addr'))

        return laserEggIdList

    #
    # 返回json格式串
    # 存在一个mac对应多个逻辑设备的情况，比如红外设备
    # getDeviceByAddr区别于getDeviceByDevId，getDeviceByDevId已经被调用多次，故提供此方法。
    #
    def getDeviceByAddr(self, deviceAddr):
        Utils.logDebug("->getDeviceByAddr %s"%(deviceAddr))
        return self.getByKey(KEY_DEVICE_ADDR, deviceAddr)

    # 返回json格式串
    def getDeviceByKeyId(self, keyId):
        Utils.logDebug("->getDeviceByKeyId %s"%(keyId))
        # result = self.getByKey(KEY_ID, keyId)
        # if(result == None or len(result) == 0):
        #     return None
        # else:
        #     return result[0]    #返回json
        try:
            conn = DBUtils.get_conn()
            sql = "select * from " + self.tablename + " where id = " + str(keyId)
            devarr = DBUtils.fetchall(conn, sql)
            # devarr应该是[(id, deviId, hostId, type, roomId, area, detail),(...)]数组格式
            if(devarr is not None):
                for dev in devarr:
                    detail = json.loads(dev[-1])
                    if detail == None or len(detail) == 0:
                        continue
                    detail['keyId'] = dev[0]
                    return detail
        except:
            Utils.logException('getDeviceByKeyId()异常')
        return None

    # def getDeviceByType(self, devType):
    #     Utils.logDebug("->getDeviceByType %s"%(devType))
    #     result = self._getByKey(KEY_DEVICE_TYPE, devType)
    #     if(result == None or len(result) == 0):
    #         return None
    #     else:
    #         return result
        
    # def getDeviceByRoom(self, roomId):
    #     Utils.logDebug("->getDeviceByRoom %s"%(roomId))
    #     result = self._getByKey(KEY_DEVICE_ROOM, roomId)
    #     if(result == None or len(result) == 0):
    #         return None
    #     else:
    #         return result

    def getDevicePropertyBy(self, roomId, areaId, devType):
        Utils.logDebug("->getDevicePropertyBy %s,%s,%s"%(roomId, areaId, devType))

        deviceProps = {}
        conditionDict = {}
        if roomId != None:
            conditionDict[KEY_DEVICE_ROOM] = "'" + roomId + "'"
        if areaId != None:
            conditionDict[KEY_DEVICE_AREA] = "'" + areaId + "'"
        if devType != None:
            conditionDict[KEY_DEVICE_TYPE] = "'" + devType + "'"
        # 不指定条件时，返回所有的设备属性
        # if len(conditionDict) == 0:
        #     return deviceProps.values()
        try:
            conn = DBUtils.get_conn()

            # 组装sql语句
            sql = "select * from " + self.tablename + " "
            if devType != "All" and devType != "all":
                sql += " where( "
                where = ""
                for key in conditionDict.keys():
                    if(where != ""):
                        where += " and "
                    where += "(" + key + " = " + str(conditionDict[key]) + ")"
                sql += where + " )"

            proparr = DBUtils.fetchall(conn, sql)
            if(proparr is not None):
                for dev in proparr:
                    detail = json.loads(dev[-1])
                    if detail == None or len(detail) == 0:
                        continue
                    detail['keyId'] = dev[0]
                    deviceProps[dev[0]] = detail        # detail总是应该放在最后的字段
        except:
            Utils.logException('_getByCondition()异常')
            deviceProps.clear()
        return deviceProps.values()


    # 查询根据房间ID列表查询设备
    # 返回结构：[{'roomname': 'room1','areaId': '1','n_gcm_count': 0,'addr': 'xxxxxx','timestamp': 1481701605,'dismiss': False,'note': 'xxxxxx','roomId': '1','keyId': 1,'Y': '124.50','X': '78.00','lightName': {'name1': 'xx'},'type': 'Light1','areaname': 'xxxx','name': 'xxxxx'}, {...}, ...]
    def getDevicesByRoomIdList(self, room_ids):
        Utils.logDebug("-> getDevicesByRoomIdList(), roomIds: %s" % str(room_ids))

        deviceProps = {}
        if room_ids:  # delos允许删除最后一个房间
            room_id_str = reduce(lambda x, y: x + ", " + y, room_ids)

            try:
                conn = DBUtils.get_conn()
                sql = "select * from " + self.tablename + " where roomId in (" + room_id_str + ")"
                proparr = DBUtils.fetchall(conn, sql)
                if proparr is not None:
                    for dev in proparr:
                        detail = json.loads(dev[-1])
                        if detail is None or len(detail) == 0:
                            continue
                        detail["keyId"] = dev[0]
                        deviceProps[dev[0]] = detail
            except:
                Utils.logException('getDevicesByRoomIdList()异常')
                deviceProps.clear()
            return deviceProps.values()
        return []

    # 批量添加时APP查询设备
    def queryDeviceWithBatch(self):
        sql = "SELECT * FROM " + self.tablename + " WHERE `roomId`='-1' and `areaId`='-1' order by `id`"
        device_prop = dict()
        try:
            conn = DBUtils.get_conn()
            prop_arr = DBUtils.fetchall(conn, sql)
            if prop_arr:
                for dev in prop_arr:
                    detail = json.loads(dev[-1])
                    if not detail:
                        continue
                    detail["keyId"] = dev[0]
                    device_prop[dev[0]] = detail
        except Exception:
            Utils.logException('queryDeviceWithBatch()异常')
            device_prop.clear()
        return device_prop.values()

    # 批量扫描后APP端保存设备信息
    def saveDeviceBatch(self, device_prop, devOpt=False):
        if device_prop:
            data = []
            for prop in device_prop:
                # 批量扫描并分配房间后，处理设备名称，设备重命名后保持detail中name值和数据库name列一致
                # 两个 name 不一致的话删除设备时会出现问题
                if prop.has_key("name"):
                    dev_name = prop.get("name")
                else:
                    dev_name = self._getNameByType(prop.get("type"))
                    prop["name"] = dev_name

                roomId = str(prop.get("roomId"))
                if roomId:
                    areaId = "1"
                else:
                    areaId = ""
                prop["areaId"] = areaId

                if devOpt:
                    if prop.get("dismiss", None):
                        roomId = None  # dimiss==True，解绑设备，将roomId置为空（null）
                        areaId = None
                        prop["areaId"] = ""
                        prop['dismiss'] = True
                    else:
                        prop['dismiss'] = False

                data.append((roomId, areaId, dev_name, json.dumps(prop), prop.get("addr")))

            update_sql = "UPDATE " + self.tablename + " SET roomId=?, areaId=?, name=?, detail=? WHERE addr = ?"
            try:
                conn = DBUtils.get_conn()
                rtn = DBUtils.executemany(conn, update_sql, data)
                if rtn:
                    return device_prop
                else:
                    return None
            except:
                Utils.logException("saveDeviceBatch() 批量保存设备信息异常")
                return None

    def insertDeviceBatch(self, device_props):
        if device_props:
            data = []
            for prop in device_props:
                # 批量扫描并分配房间后，处理设备名称，设备重命名后保持detail中name值和数据库name列一致
                # 两个 name 不一致的话删除设备时会出现问题
                if prop.has_key("name"):
                    dev_name = prop.get("name")
                else:
                    dev_name = self._getNameByType(prop.get("type"))
                    prop["name"] = dev_name

                deviceAddr = prop.get("addr")  # 设备地址
                devType = prop.get("type")  # 设备类型
                roomId = str(prop.get("roomId"))
                if roomId:
                    areaId = "1"
                    prop['dismiss'] = False
                else:
                    areaId = ""
                    prop['dismiss'] = True
                prop["areaId"] = areaId
                prop['timestamp'] = int(time.time())

                data.append((None, self.tableversion, deviceAddr, dev_name, devType, roomId, areaId, json.dumps(prop)))
            # data = [(None, self.tableversion, deviceAddr, name, devType, roomId, area, devAllDetailJsonStr)]
            insert_sql = "INSERT INTO  " + self.tablename + " values (?,?,?,?,?,?,?,?)"
            try:
                conn = DBUtils.get_conn()
                rtn = DBUtils.executemany(conn, insert_sql, data)
                if rtn:
                    return device_props
                else:
                    return None
            except:
                Utils.logException("insertDeviceBatch() 批量保存设备信息异常")
                return None

    # 默认查询所有节律灯，用于在搜索节律灯时过滤掉已经添加的节律灯
    def queryCircadianLightSerialNo(self, n4SerialNo, devtype='CircadianLight'):
        circadianLights = []
        query_sql = "select `detail` from " + self.tablename + " where type = '%(devtype)s'" % {"devtype": devtype}
        try:
            conn = DBUtils.get_conn()
            dev_list = DBUtils.fetchall(conn, query_sql)
            for dev in dev_list:
                devJson = json.loads(dev[0])
                n4SerialNoInTemp = devJson.get("n4SerialNo")
                if n4SerialNoInTemp == n4SerialNo:
                    circadianLights.append(devJson.get("SerialNumber"))
        except:
            Utils.logError("queryCircadianLightSerialNo() error...")
        return circadianLights

    # 更新设备的常用属性
    def updateDeviceFavorite(self, device_props):
        data = []
        update_sql = "UPDATE " + self.tablename + " SET detail=? WHERE addr=?"
        if device_props:
            for prop in device_props:
                data.append((json.dumps(prop), prop.get("addr")))
            # excute DB update
            try:
                conn = DBUtils.get_conn()
                rtn = DBUtils.executemany(conn, update_sql, data)
                if rtn:
                    return device_props
                else:
                    return None
            except:
                Utils.logError("updateDeviceFavorite() error...save favorite devices failed!")
                return None

    def deleteDeviceByAddrName(self, addr, name):
        Utils.logDebug("->deleteDeviceByAddrName %s-%s"%(addr, name))
        try:
            conn = DBUtils.get_conn()
            sql = "DELETE FROM " + self.tablename + " WHERE addr = '" + addr + "' and name = '" + name + "'"
            DBUtils.deleteone(conn, sql)
            return True
        except:
            Utils.logException('deleteDeviceByAddrName()异常')
        return False

    def deleteDeviceById(self, devAddr):
        Utils.logDebug("->deleteDeviceById %s"%(devAddr))
        return self.deleteByKey(KEY_DEVICE_ADDR, devAddr)

    #房间被删除，所有设备属性只更新roomId，area字段为空
    def roomRemoved(self, roomId):
        Utils.logDebug("->roomRemoved %s"%(roomId))
        if roomId is None:
            return

        devProps = self.getDevicePropertyBy(roomId, None, None)
        if devProps == None or len(devProps) == 0:
            return

        for prop in devProps:
            prop['dismiss'] = True
            self._dismissDevice(prop)

        # update_sql = 'UPDATE ' + self.tablename + ' SET '
        # update_sql += ' ' + KEY_DEVICE_ROOM + ' = null '
        # update_sql += ',' + KEY_DEVICE_AREA + ' = null '
        # # update_sql += ',' + KEY_DEVICE_DETAIL + " = ? "
        # update_sql += ' WHERE '+ KEY_DEVICE_ROOM + ' = ? '
        # # data = [("{}",roomId)]
        # data = [(roomId,)]
        # conn = DBUtils.get_conn()
        # return DBUtils.update(conn, update_sql, data)

    #房间被删除，所有设备属性只更新roomId，area字段为空
    def roomAreaRemoved(self, roomId, areaId="1"):
        Utils.logDebug("->roomAreaRemoved %s,%s"%(roomId, areaId))
        if roomId is None or areaId == None:
            return
        # update_sql = 'UPDATE ' + self.tablename + ' SET '
        # update_sql += ' ' + KEY_DEVICE_ROOM + ' = null '
        # update_sql += ',' + KEY_DEVICE_AREA + ' = null '
        # # update_sql += ',' + KEY_DEVICE_DETAIL + " = '{}' "
        # update_sql += ' WHERE '+ KEY_DEVICE_ROOM + ' = ? and ' + KEY_DEVICE_AREA + " = ? "
        # data = [(roomId, areaId)]
        # conn = DBUtils.get_conn()
        # return DBUtils.update(conn, update_sql, data)
        devProps = self.getDevicePropertyBy(roomId, areaId, None)
        if devProps == None or len(devProps) == 0:
            return

        for prop in devProps:
            prop['dismiss'] = True
            self._dismissDevice(prop)

    #房间被删除，所有设备属性只更新roomId，area字段为空
    def dismissDevice(self, addr, name):
        Utils.logInfo("->dismissDevice %s %s"%(addr, name))

        keyId, prop = self.getDeviceByAddrName(addr, name)
        if prop == None:
            Utils.logInfo("->dismissDevice getDeviceByAddrName return none")
            return

        prop['dismiss'] = True
        self._dismissDevice(prop)

    def getLcdSwitchByModeId(self, modeId):
        result = []
        deviceList = self.getDeviceByDevType("LcdSwitch")
        for lcd in deviceList:
            modecfg = lcd.get("modecfg", {})
            temp = [(index, lcd) for index, mode in modecfg.items() if int(mode) == int(modeId)]
            # for index, mode in modecfg.items():
            #     if int(mode) == int(modeId):
            #         result.append((index, lcd))
            #         break
            result.extend(temp)
        return result

    # 模式名字变更时同步更新LCD开关的模式名
    def updateLcdModeName(self, devprops):
        data = []
        for devprop in devprops:
            data.append((json.dumps(devprop), devprop.get("addr")))

        update_sql = "UPDATE " + self.tablename + " SET detail = ? WHERE addr = ?"
        try:
            conn = DBUtils.get_conn()
            DBUtils.executemany(conn, update_sql, data)

        except:
            pass

    def getAllDevicesForRokid(self):
        Utils.logInfo("->getAllDevicesForRokid()...")
        device_list = []
        sql = "select * from " + self.tablename + " where length(addr)>=20 and type in " \
              + "('Light1', 'Light2', 'Light3', 'Light4', 'LightAdjust', " \
              + "'Curtain', 'Socket', 'AirFilter', 'TV', 'AirCondition')"

        try:
            conn = DBUtils.get_conn()
            devices = DBUtils.fetchall(conn, sql)
            if devices:
                dev_addrs = []  # 设备地址列表
                for dev in devices:
                    detail = json.loads(dev[-1])
                    if detail:
                        device_list.append(detail)
                        dev_addrs.append(detail.get('addr'))
                return {"devList": device_list, "addrList": dev_addrs}
        except:
            Utils.logError("getAllDevicesForRokid() error...")
        return {}

    def getLaserEggForScreen(self):
        '''
        原来使用镭豆，现改为空气质量检测仪（2018-07-02）
        :return: a list containing AirSensor addr,roomId,room detail information.
        '''
        query_sql = "select dev.addr as addr, dev.roomId as roomId, room.detail as detail from tbl_device_prop as dev " \
                    + "left join tbl_room as room on dev.roomId = room.id where dev.type='AirSensor'"
        result_list = []
        try:
            conn = DBUtils.get_conn()
            laseregg_list = DBUtils.fetchall(conn, query_sql)
            if laseregg_list:
                for ld in laseregg_list:
                    result = handle_room_info(ld)
                    result_list.append(result)
                result_list.extend(self._generate_fake_room())

        except:
            Utils.logError("getLaserEggForScreen() error...")

        return result_list

    def _generate_fake_room(self):
        laser_addr = self._get_laser_addr()
        room1 = {
            'addr': laser_addr[random.randint(0, len(laser_addr) - 1)],
            'roomId': 'm',
            'name': u'主人房',
            'type': u'主卧',
            'pic': 'img/room/主卧.png',
            'temp': '?',
            'humidity': '?'
        }
        room2 = {
            'addr': laser_addr[random.randint(0, len(laser_addr) - 1)],
            'roomId': 's',
            'name': u'书房',
            'type': u'书房',
            'pic': 'img/room/书房.png',
            'temp': '?',
            'humidity': '?'
        }
        room3 = {
            'addr': laser_addr[random.randint(0, len(laser_addr) - 1)],
            'roomId': 'g',
            'name': u'健身房',
            'type': u'会议室',
            'pic': 'img/room/会议室.png',
            'temp': '?',
            'humidity': '?'
        }
        room4 = {
            'addr': laser_addr[random.randint(0, len(laser_addr) - 1)],
            'roomId': 'd',
            'name': u'餐厅',
            'type': u'餐厅',
            'pic': 'img/room/餐厅.png',
            'temp': '?',
            'humidity': '?'
        }
        return [room1, room2, room3, room4]

    def _get_laser_addr(self):
        '''
        Query LaserEgg device list at first, now we change device type to AirSensor(2018-07-02)
        :return: return a list containing AirSesor detail information
        '''
        query_sql = "select addr from tbl_device_prop where type='AirSensor'"
        result_list = []
        try:
            conn = DBUtils.get_conn()
            addr_list = DBUtils.fetchall(conn, query_sql)
            for addr in addr_list:
                result_list.append(addr[0])

        except:
            Utils.logError('_get_laser_addr() error...')
        return result_list

    def _dismissDevice(self, devPropObj):
        Utils.logInfo("->dismissDevice %s"%(devPropObj))
        keyId = devPropObj.get('keyId', None)
        if keyId == None:
            Utils.logInfo("->dismissDevice has no keyId")
            return

        # del devPropObj[KEY_DEVICE_ROOM]
        # del devPropObj[KEY_DEVICE_AREA]
        devPropObj['dismiss'] = True
        # 以下将房间信息和区域信息置为空是为了防止解绑后改设备名又出现APP上设备列表里仍然显示房间名的现象
        devPropObj['roomname'] = ''
        devPropObj['roomId'] = ''
        devPropObj['areaname'] = ''
        devPropObj['areaId'] = ''
        devPropObj['timestamp'] = int(time.time())
        update_sql = 'UPDATE ' + self.tablename + ' SET '
        update_sql += ' ' + KEY_DEVICE_ROOM + ' = null '
        update_sql += ',' + KEY_DEVICE_AREA + ' = null '
        update_sql += ',' + KEY_DEVICE_DETAIL + ' = ? '
        update_sql += ' WHERE '+ KEY_ID + ' = ? '

        data = [(json.dumps(devPropObj), keyId)]
        conn = DBUtils.get_conn()
        return DBUtils.update(conn, update_sql, data)

    def _getNameByType(self, devType):  # 仅用于批量扫描设备分配区域之后保存设备时使用
        if devType == "LightAdjust":
            return "调光灯"
        elif devType == "Light1":
            return "单联灯"
        elif devType == "Light2":
            return "二联灯"
        elif devType == "Light3":
            return "三联灯"
        elif devType == "Light4":
            return "四联灯"
        elif devType == "Socket":
            return "插座"
        elif devType == "Curtain":
            return "窗帘"
        elif devType == "CircadianLight":
            return "X2"

def handle_room_info(room):
    room_dict = {
        'addr': '',
        'roomId': 1,
        'name': '未分配区域',
        'type': '主卧',
        'pic': 'img/room/主卧.png',
        'temp': '?',
        'humidity': '?'
    }

    if room[-1] is None:
        room_detail = None
    else:
        room_detail = json.loads(room[-1])

    room_dict['addr'] = room[0]
    if room[1] is None:
        room_dict['roomId'] = 0
    else:
        room_dict['roomId'] = room[1]

    if room_detail is None:
        room_dict['name'] = u'未分配区域'
        room_dict['type'] = u'主卧'
    else:
        room_dict['name'] = room_detail.get('name', u'未分配区域')
        room_dict['type'] = room_detail.get('type', u'主卧')
    room_dict = add_pic(room_dict)
    return room_dict

def add_pic(room):
    '''
    将房间图片加入到房间对象中，前端模板内直接引用
    :param room: 房间对象
    :return: 返回更新后的房间对象
    '''
    if room.get('type') == u'主卧':
        room['pic'] = 'img/room/主卧.png'
    elif room.get('type') == u'书房':
        room['pic'] = 'img/room/书房.png'
    elif room.get('type') == u'会议室':
        room['pic'] = 'img/room/会议室.png'
    elif room.get('type') == u'办公室':
        room['pic'] = 'img/room/办公室.png'
    elif room.get('type') == u'卫生间':
        room['pic'] = 'img/room/卫生间.png'
    elif room.get('type') == u'厨房':
        room['pic'] = 'img/room/厨房.png'
    elif room.get('type') == u'客厅':
        room['pic'] = 'img/room/客厅.png'
    elif room.get('type') == u'客房':
        room['pic'] = 'img/room/客房.png'
    elif room.get('type') == u'总经理':
        room['pic'] = 'img/room/总经理.png'
    elif room.get('type') == u'次卧':
        room['pic'] = 'img/room/次卧.png'
    elif room.get('type') == u'茶水间':
        room['pic'] = 'img/room/茶水间.png'
    elif room.get('type') == u'餐厅':
        room['pic'] = 'img/room/餐厅.png'
    else:
        room['pic'] = 'img/room/主卧.png'
    return room

if __name__ == '__main__':
    d1 = DBManagerDeviceProp()
    d2 = DBManagerDeviceProp()
    
    # devDict={"deviceId":"devIdvalue","hostId":"hostIdvalue","roomId":"1","areaId":"1","type":"typevalue"}
    devDict={"name":"二联灯","type":"Light2","roomId":"1","areaId":"1","addr":"z-347D4501004B12001233","value":{"state":"0","coeff":"1"}}
    d2.saveDeviceProperty(devDict)
    # devDict2={"deviceId":"devIdvalue2","hostId":"hostIdvalue","roomId":"roomvalue","area":"areavalue2","type":"typevalue"}
    
    devDict2={"name":"三联灯","type":"Light1","roomId":"2","areaId":"1","addr":"z-347D4501004B12001234","value":{"state":"1","coeff":"1"}}
    d2.saveDeviceProperty(devDict2)
    
    print "============================="
    d2.getDevicePropertyBy(None,None,None)
    r = d2.getDevicePropertyBy("2",None,None)
    if r[0].get("name","") == u"三联灯":
        print "============getDevicePropertyBy roomId SUCCESS======"
    else:
        print "************getDevicePropertyBy roomId Failed"
    ra = d2.getDevicePropertyBy("1","1",None)
    if ra[0].get("name","") == u"二联灯":
        print "============getDevicePropertyBy roomId areaId SUCCESS======"
    else:
        print "************getDevicePropertyBy roomId areaId Failed"
    t = d2.getDevicePropertyBy(None,None,"Light1")
    if t[0].get("name","") == u"三联灯":
        print "============getDevicePropertyBy roomId areaId SUCCESS======"
    else:
        print "************getDevicePropertyBy roomId areaId Failed"

    d1.deleteDeviceById("z-347D4501004B12001233")
    d = d2.getDeviceByDevId("z-347D4501004B12001233")
    if d == None:
        print "============deleteDeviceById devId SUCCESS======"
    else:
        print "************deleteDeviceById devId Failed"
    d2.roomAreaRemoved("2","1")
    ra = d2.getDevicePropertyBy("2",None,None)
    if d == None:
        print "============roomAreaRemoved devId SUCCESS======"
    else:
        print "************roomAreaRemoved devId Failed"

    devDict={"name":"二联灯","type":"Light1","roomId":"1","areaId":"1","addr":"z-347D4501004B12001233","value":{"state":"0","coeff":"1"}}
    d2.saveDeviceProperty(devDict)
    # devDict2={"deviceId":"devIdvalue2","hostId":"hostIdvalue","roomId":"roomvalue","area":"areavalue2","type":"typevalue"}

    devDict2={"name":"三联灯","type":"Light1","roomId":"1","areaId":"2","addr":"z-347D4501004B12001234","value":{"state":"1","coeff":"1"}}
    d2.saveDeviceProperty(devDict2)
    d2.roomRemoved("1")

    ra = d2.getDevicePropertyBy("1",None,None)

    if ra == None or len(ra) == 0:
        print "============getDevicePropertyBy roomId areaId SUCCESS======"
    else:
        print "************getDevicePropertyBy roomId areaId Failed"
