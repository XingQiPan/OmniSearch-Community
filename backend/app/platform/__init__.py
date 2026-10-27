"""开放 API 商业化平台层（鉴权 / 计量计费 / 密钥 / 套餐 / 用量账单）。

该包把内部网关能力（``app.gateway`` / ``app.providers``）封装成可对外售卖的
标准搜索 API：``/v1/search``、``/v1/extract``、``/v1/answer``、
``/v1/chat/completions``，并提供管理端 ``/api/admin/platform/*``。
"""
