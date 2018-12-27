# -*- coding: utf-8 -*-


SUCCESS = 0
SUCCESS_SAME_TIMESTAMP = 100         # 时间戳一致，app可使用缓存数据


# 失败的错误码从50000开始
ERR_GENERAL = 50000                  # 未知错误
ERR_CMD_TYPE = 50001                 # 消息码错误
ERR_CMD_NO_CLOUD_LINK = 50002        # 需要云账号连接
ERR_CMD_NO_LOCAL_LINK = 50003        # 需要本地连接
ERR_CMD_DUPLICATE_DEVICE = 50004     # 设备重复添加
ERR_INVALID_REQUEST = 50100          # 无效请求
ERR_INVALID_PARAMS = 50101           # 参数错误
ERR_MSG_PARSE_ERR = 50105            # 消息解析错误
ERR_MSG_CONFLICT = 50106             # 数据过期
ERR_WRONG_USERNAME_PASSWORD = 50005  # 用户名密码错误
ERR_SCANNING = 50006                 # 网关已经有用户在扫描设备


