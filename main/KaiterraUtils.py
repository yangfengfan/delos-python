#!/usr/bin/env python
# -*- coding: utf-8 -*-
import hashlib
import base64
import time
import urllib
import urllib2
import ssl
import json
import Utils
from GlobalVars import KAITERRA_CLIENT_ID, KAITERRA_HMAC_SECRET_KEY


base_url = "https://api.origins-china.cn/v1/"
# Controls the auth method used by this script.  Possible values are:
# - 'url': passes the developer key in the URL
# - 'hmac': uses the HMAC-based auth scheme in which the key itself does not appear in the network request
auth_method = "hmac"

# For "url" authentication:
# Developer key passed in the 'key' parameter in the URL.
dev_demo_key = "kOpAgVMnz2zM5l6XKQwv4JmUEvopnmUewFKXQ0Wvf9Su72a9"

# For "hmac" authentication:
# ID and secret key used to authorize requests  of your organization.  Required if using the "app" auth method.
client_id = KAITERRA_CLIENT_ID
hmac_secret_key = KAITERRA_HMAC_SECRET_KEY


def hmac(key, message):
    def hasher(msg=b''):
        return hashlib.sha256(msg)

    def hash(msg=b''):  # -> bytes
        return hasher(msg).digest()

    blocksize = hasher().block_size

    # See https://en.wikipedia.org/wiki/Hash-based_message_authentication_code#Implementation
    if len(key) > blocksize:
        key = hash(key)

    if len(key) < blocksize:
        key = key + bytearray(0 for _ in range(blocksize - len(key)))

    o_key_pad = bytearray(0x5c ^ b for b in bytearray(key))
    i_key_pad = bytearray(0x36 ^ b for b in bytearray(key))

    return hash(o_key_pad + hash(i_key_pad + message))


def auth_request_as_hmac(relative_url, params={}, headers={}, body=b''):  # -> (str, dict)
    """
    Given a desired HTTP request, returns the modified URL and request headers that are needed
    for the request to be accepted by the API.
    """
    hex_key = bytearray.fromhex(hmac_secret_key)

    Utils.logDebug("Authenticating request using HMAC")
    Utils.logDebug("Secret key: {}".format(bytes2hex(hex_key)))

    client_header = 'X-Kaiterra-Client'
    headers[client_header] = client_id
    timestamp_header = 'X-Kaiterra-Time'
    headers[timestamp_header] = '{:x}'.format(int(time.time()))

    header_component = '{}={}&{}={}'.format(
        client_header, headers[client_header],
        timestamp_header, headers[timestamp_header]).encode('ascii')

    # Order doesn't matter
    relative_url_with_params = relative_url
    if params:
        relative_url_with_params += "?" + urllib.urlencode(params)
    url_component = relative_url_with_params.encode('ascii')

    full_payload = header_component + url_component + body
    Utils.logDebug("Full payload to be signed:")
    Utils.logDebug(full_payload)

    headers['X-Kaiterra-HMAC'] = base64.b64encode(hmac(hex_key, full_payload))

    return (base_url.strip("/") + relative_url_with_params, headers)


def auth_request_as_url(relative_url, params={}, headers={}, body=b''):  # -> (str, dict)
    """
    Given a desired HTTP request, appends the developer key as a URL parameter.
    """
    params['key'] = dev_demo_key
    return (base_url.strip("/") + relative_url + "?" + urllib.urlencode(params), headers)


def do_req(uuid, body='', params={}, headers={}):
    url = "/lasereggs/{uuid}".format(uuid=uuid)
    if auth_method == "hmac":
        (url, headers) = auth_request_as_hmac(url, body=body, params=params)
    elif auth_method == "url":
        (url, headers) = auth_request_as_url(url, body=body, params=params)
    else:
        Utils.logError("Unknown auth method when querying Kaiterra data '{}'".format(auth_method))

    if len(body) > 0:
        headers.update({'Content-Type': 'application/json'})

    Utils.logDebug("Fetching: {}".format(url))
    Utils.logDebug("Headers:  {}".format(headers))

    req = urllib2.Request(url=url, headers=headers)
    try:
        response = urllib2.urlopen(req, context=ssl._create_unverified_context()).read()
    except Exception as e:
        response = None
        Utils.logError("Sending Kaiterra request failed...")
        Utils.logError(e.message)

    if response:
        content_str = response.decode('utf-8')
        if len(content_str) > 0:
            return json.loads(content_str)

    return None


def get_laser_egg(uuid, rtn='total'):
    response = do_req(uuid, params={"series": "raw", "utc_offset": "0800"})
    if response:
        if rtn == 'total':
            return response
        else:
            info = response.get('info.aqi', {})
            if info:
                data = info.get('data', {})
                if data:
                    if u'temp' in data.keys() or 'temp' in data.keys():
                        temp = data.get('temp')
                        data['temp'] = round(temp, 2)  # 防止出现 28.620000000000001 的情况
                    if u'humidity' in data.keys() or 'humidity' in data.keys():
                        humidity = data.get('humidity')
                        data['humidity'] = round(humidity, 2)
                    return data
    return {}


def bytes2hex(bb):
    return " ".join('%02x' % x for x in bb)


if __name__ == '__main__':
    # /lasereggs/b55a2a78-d14d-4b27-9e20-91804925407d
    data = get_laser_egg("b55a2a78-d14d-4b27-9e20-91804925407d", rtn='data')

    print("Data returned:")
    print(data)
    print('')

    data2 = get_laser_egg("b55a2a78-d14d-4b27-9e20-91804925407d")
    print("Data returned:")
    print(data2)
