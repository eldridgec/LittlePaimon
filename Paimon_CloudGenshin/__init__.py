import json
import re
import uuid
from typing import Union
from nonebot import on_command, require, get_bot, logger
from nonebot.adapters.onebot.v11 import MessageEvent, Message, GroupMessageEvent
from nonebot.internal.matcher import Matcher
from nonebot.internal.params import ArgPlainText
from nonebot.params import CommandArg
from .data_source import get_Info, get_Notification, check_token
from utils.decorator import exception_handler
from utils.file_handler import load_json, save_json

HELP_STR = '''
云原神相关功能
云原神 绑定/bind : 绑定云原神的token
云原神 信息/info: 查询云原神账户信息
'''.strip()

cloud_ys = on_command('云原神', aliases={'云原神', 'yys'}, priority=16, block=True)
rm_cloud_ys = on_command('云原神解绑', aliases={'yys解绑', 'yys解除绑定', 'yysdel'}, priority=16, block=True)
cloud_ys.__paimon_help__ = {
    "usage": "云原神",
    "introduce": "查询云原神账户信息, 绑定token进行签到",
    "priority": 99
}
rm_cloud_ys.__paimon_help__ = {
    "usage": "云原神解绑",
    "introduce": "解绑cookie并取消自动签到",
    "priority": 99
}
scheduler = require('nonebot_plugin_apscheduler').scheduler
uuid = str(uuid.uuid4())


@rm_cloud_ys.handle()
async def _handle(event: Union[GroupMessageEvent, MessageEvent], match: Matcher, args: Message = CommandArg()):
    plan_text = args.extract_plain_text()
    if plan_text:
        match.set_arg('choice', plan_text)


@rm_cloud_ys.got('choice', prompt='是否要解绑token并取消自动签到？\n请输入 是/否 来进行操作')
async def _(event: Union[GroupMessageEvent, MessageEvent], choice: str = ArgPlainText('choice')):
    if choice == '是':
        user_id = str(event.user_id)
        data = load_json('user_data.json')

        del data[user_id]
        if scheduler.get_job('cloud_genshin_' + user_id):
            scheduler.remove_job("cloud_genshin_" + user_id)
        save_json(data, 'user_data.json')

        await rm_cloud_ys.finish('token已解绑并取消自动签到~', at_sender=True)
    elif choice == '否':
        await rm_cloud_ys.finish()
    else:
        await rm_cloud_ys.finish()


async def auto_sign_cgn(user_id, data):
    token = data['token']
    uuid = data['uuid']

    if await check_token(uuid, token):
        """ 获取免费时间 """
        d2 = await get_Info(uuid, token)
        """ 解析签到返回信息 """
        if d2['data']['free_time']['free_time'] == data['limit']:
            await get_bot().send_private_msg(user_id=user_id, message='免费签到时长已达上限,无法继续签到')
        else:
            """ 取云原神签到信息 """
            d1 = await get_Notification(uuid, token)
            if not list(d1['data']['list']):
                logger.info(f'UID{data["uid"]} 已经签到云原神')
            else:
                signInfo = json.loads(d1['data']['list'][0]['msg'])
                if signInfo:
                    await get_bot().send_private_msg(
                        user_id=user_id,
                        message=f'签到成功~ {signInfo["msg"]}: {signInfo["num"]}分钟'
                    )
                else:
                    return
    else:
        await get_bot().send_private_msg(user_id=user_id, message='token已过期,请重新自行抓包并重新绑定')


@cloud_ys.handle()
@exception_handler()
async def _(event: Union[GroupMessageEvent, MessageEvent], msg: Message = CommandArg(), uuid=uuid):
    param = msg.extract_plain_text().strip()
    user_id = str(event.user_id)
    data = load_json('user_data.json')

    action = re.search(r'(?P<action>(信息|info)|(绑定|bind))', param)

    if event.message_type == 'guild':
        await cloud_ys.finish('该功能暂不支持频道推送哦~', at_sender=True)

    if not param:
        message = f'亲爱的旅行者: {user_id}\n\n' \
                    '本插件食用方法:\n' \
                    '<云原神/yys> [绑定/bind] 绑定云原神token\n' \
                    '<云原神/yys> [信息/info] 查询云原神账户信息\n\n' \
                    '<yys[解绑/解除绑定/del]> 解绑token并取消自动签到\n\n' \
                    '有关如何抓取token的方法:\n' \
                    '请前往 https://blog.ethreal.cn/archives/yysgettoken 查阅'
        await cloud_ys.finish(message, at_sender=True)
    else:
        if action.group('action') in ['绑定', 'bind']:
            match = re.search(r'oi=\d+', param.split(" ")[1])
            if match:
                uid = str(match.group()).split('=')[1]

            data[user_id] = {
                'uid': uid,
                'uuid': uuid,
                'limit': 600,
                'isFullTime': False,
                'token': param.split(" ")[1]
            }

            if scheduler.get_job('cloud_genshin_' + user_id):
                scheduler.remove_job("cloud_genshin_" + user_id)

            """ 保存数据 """
            save_json(data, 'user_data.json')
            """ 添加推送任务 """
            scheduler.add_job(
                func=auto_sign_cgn,
                trigger='cron',
                hour=6,
                id="cloud_genshin_" + user_id,
                args=(user_id, data[user_id]),
                misfire_grace_time=10
            )
            await cloud_ys.finish(f'[UID:{uid}]已绑定token, 将在每天6点为你自动签到!', at_sender=True)

        elif action.group('action') in ['信息', 'info']:

            token = data[user_id]['token']
            uid = data[user_id]['uid']
            uuid = data[user_id]['uuid']

            result = await get_Info(uuid, token)

            """ 米云币 """
            coins = result['data']['coin']['coin_num']
            """ 免费时间 """
            free_time = result['data']['free_time']['free_time']
            """ 畅玩卡 """
            card = result['data']['play_card']['short_msg']

            message = '======== UID: {0} ========\n' \
                      '剩余米云币: {1}\n' \
                      '剩余免费时间: {2}分钟\n' \
                      '畅玩卡状态: {3}'.format(uid, coins, free_time, card)
            await cloud_ys.finish(message)
        else:
            await cloud_ys.finish('参数错误！', at_sender=True)


for user_id, data in load_json('user_data.json').items():
    scheduler.add_job(
        func=auto_sign_cgn,
        trigger='cron',
        hour=6,
        id="cloud_genshin_" + user_id,
        args=(user_id, data),
        misfire_grace_time=10
    )
