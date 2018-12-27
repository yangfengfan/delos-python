#!/usr/bin/env python
# -*- coding: utf-8 -*-
import json
import base64
import time
import socket
import urllib
import urllib2
import ssl
import Utils
from DBManagerDeviceProp import *
from GlobalVars import KETRA_ACCESS_TOKEN as ketraToken
from GlobalVars import KETRA_ACCOUNT_USERNAME as ketraName
from GlobalVars import KETRA_ACCOUNT_EMAIL as ketraEmail


# ===================================================================================
# Support function to get the local IP address for N4 discovery
# ===================================================================================
def getMyIpAddress():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(('8.8.8.8', 0))
    outgoing_ip_address = s.getsockname()[0]
    s.close()
    return outgoing_ip_address


# ===================================================================================
# Support function to discover an N4 device given its serial number
# ===================================================================================
def discoverN4Device(n4SerialNumber, dbUpdate=False):
    Utils.logInfo("Discovering N4 with serial number " + n4SerialNumber)
    n4IP = None

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    outgoing_ip_address = getMyIpAddress()
    Utils.logDebug("Using local interface " + outgoing_ip_address)
    sock.bind((outgoing_ip_address, 0))
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.setblocking(False)
    for m in range(5):
        time.sleep(.1)
        try:
            sock.sendto("*", ('255.255.255.255', 4934))
        except socket.error, e:
            Utils.logError("Error when searching for N4...")

        t_end = time.time() + 1
        while time.time() < t_end:
            try:
                data, addr = sock.recvfrom(1024)
                response = dict([s.split("=") for s in data.splitlines()])
                response["address"] = str(addr[0])
                if (response["serial"] == n4SerialNumber):
                    Utils.logDebug("Found N4 at address " + response["address"])
                    if sock:
                        sock.close()
                    n4IP = response["address"]
                    break
            except socket.error:
                pass
        break
    if dbUpdate:
        n4Detail = DBManagerDeviceProp().getDeviceByAddr(n4SerialNumber)[0]
        n4Detail['n4IP'] = n4IP
        DBManagerDeviceProp().saveDeviceProperty(n4Detail)  # 将新的N4 IP更新到数据库中
    return n4IP


# send a GET request to N4
def sendGetRequest(url):
    auth = base64.encodestring(ketraName + ':' + ketraToken).replace('\n', '')
    hdrs = {"Content-type": "application/json", "Authorization": "Basic %s" % auth}
    req = urllib2.Request(url, headers=hdrs)
    try:
        response = urllib2.urlopen(req, context=ssl._create_unverified_context()).read()
        rtnDict = json.loads(response)
    except Exception as e:
        rtnDict = {}
    return rtnDict


# send a POST request to N4
def sendPostRequest(url, reqData=None):
    auth = base64.encodestring(ketraName + ':' + ketraToken).replace('\n', '')
    hdrs = {"Content-type": "application/json", "Authorization": "Basic %s" % auth}
    if isinstance(reqData, dict):
        reqData = json.dumps(reqData)
    req = urllib2.Request(url,data=reqData, headers=hdrs)
    try:
        response = urllib2.urlopen(req, context=ssl._create_unverified_context()).read()
        rtnDict = json.loads(response)
    except Exception as e:
        rtnDict = {}
    return rtnDict


def getKeypadList(n4SerialNo, n4Addr=""):
    if not n4Addr:
        n4Addr = discoverN4Device(n4SerialNo)

    getKeypadsUrl = 'https://' + n4Addr + '/ketra.cgi/api/v1/keypads'
    rtnJson = sendGetRequest(getKeypadsUrl)
    if rtnJson.get("Success"):
        keypadList = rtnJson.get("Content", [])
        if keypadList:
            keypad_list = []
            # 仅仅是X2序列号的列表，用于过滤已添加的节律灯X2开关
            existingLights = DBManagerDeviceProp().queryCircadianLightSerialNo(n4SerialNo, 'CircadianLight')
            for keypad in keypadList:
                x2SerialNo = keypad.get("SerialNumber")
                if x2SerialNo and x2SerialNo not in existingLights:
                    keypad['name'] = keypad.get("Name", "")
                    button_list = keypad.get("Buttons", [])
                    if button_list:
                        # 按Position排序
                        button_list = sorted(button_list, cmp=lambda x, y: cmp(x.get("Position"), y.get("Position")))
                    keypad["Buttons"] = button_list
                    keypad_list.append(keypad)

            keypad_list = map(lambda obj: _swift_data(obj, isKeyPad=True, n4SeriaoNo=n4SerialNo), keypad_list)
            return keypad_list
    return []


def getKeypadByName(n4SerialNo, keypadName, n4Addr=""):
    if not n4Addr:
        n4Addr = discoverN4Device(n4SerialNo)

    requestUrl = 'https://' + n4Addr + '/ketra.cgi/api/v1/keypads/' + urllib.quote(keypadName)
    rtnJson = sendGetRequest(requestUrl)
    if rtnJson.get("Success"):
        keypad = rtnJson.get("Content")
        keypad['name'] = keypad.get("Name", "")
        button_list = keypad.get("Buttons", [])
        if button_list:
            # 按Position排序
            button_list = sorted(button_list, cmp=lambda x, y: cmp(x.get("Position"), y.get("Position")))
        keypad["Buttons"] = button_list
        # dataObj['addr'] = dataObj.get('SerialNumber', '')
        # dataObj['type'] = 'CircadianLight'
        # dataObj['n4SerialNo'] = n4SeriaoNo
        keypad['addr'] = keypad.get('SerialNumber')
        keypad['type'] = 'CircadianLight'
        keypad['n4SerialNo'] = n4SerialNo
        return keypad
    return None




def activateButton(n4SerialNo, keypadName, buttonName, state="1", n4Addr=""):
    if not n4Addr:
        n4Addr = discoverN4Device(n4SerialNo)
    rtnmsg = None
    if n4Addr:
        if isinstance(buttonName, unicode):
            buttonName = buttonName.encode('utf-8')
        if isinstance(keypadName, unicode):
            keypadName = keypadName.encode('utf-8')
        if state == "1":
            activateBtnUrl = 'https://%s/ketra.cgi/api/v1/Keypads/%s/Buttons/%s/Activate' % \
                             (n4Addr, urllib.quote(keypadName), urllib.quote(buttonName))
        else:
            activateBtnUrl = 'https://%s/ketra.cgi/api/v1/Keypads/%s/Buttons/%s/Deactivate' % \
                             (n4Addr, urllib.quote(keypadName), urllib.quote(buttonName))
        params = json.dumps({"Level": 65535})
        Utils.logInfo("request url: %s" % activateBtnUrl)
        # try:
        #     rtnmsg = sendPostRequest(activateBtnUrl, reqData=params)
        # except:
        #     n4Addr = discoverN4Device(n4SerialNo, dbUpdate=True)  # N4 IP发生改变，重新搜索
        #     rtnmsg = sendPostRequest(activateBtnUrl, reqData=params)
        rtnmsg = sendPostRequest(activateBtnUrl, reqData=params)
        if not rtnmsg: # N4 IP发生改变，重新搜索
            n4Addr = discoverN4Device(n4SerialNo, dbUpdate=True)
            rtnmsg = sendPostRequest(activateBtnUrl, reqData=params)

        Utils.logInfo("Ketra rtn: %s" % str(rtnmsg))  # return like {"Success":true,"Error":"N4Status_NoStatus","Content":{}}
        success = rtnmsg.get("Success")
        if success:
            newKeypad = getKeypadByName(n4SerialNo, keypadName, n4Addr)  # query new state of X2
            keypadSerial = newKeypad.get("SerialNumber")
            keypadInDB = DBManagerDeviceProp().getDeviceByAddr(keypadSerial)[0]
            keypadInDB['Buttons'] = newKeypad.get("Buttons")  # 更新新的X2面板状态
            keypadInDB['timestamp'] = int(time.time())
            DBManagerDeviceProp().saveDeviceProperty(keypadInDB)
    return rtnmsg


def _swift_data(dataObj, isKeyPad=False, n4SeriaoNo=''):
    dataObj['name'] = u'节律灯'
    if isKeyPad:  # 如果是X2面板的话还需要补全一些信息，后续写库需要使用
        dataObj['addr'] = dataObj.get('SerialNumber', '')
        dataObj['type'] = 'CircadianLight'
        dataObj['n4SerialNo'] = n4SeriaoNo
    return dataObj
