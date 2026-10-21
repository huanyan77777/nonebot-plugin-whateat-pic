import io
import os
import secrets

import httpx
from nonebot import get_driver
from nonebot.adapters import Bot, Event
from nonebot.log import logger
from nonebot_plugin_alconna import Alconna, Args, Match, on_alconna
from nonebot_plugin_alconna.uniseg import Image, Text, UniMessage
from nonebot_plugin_apscheduler import scheduler

from .check_user_data import check_iscd, check_ismax
from .files import delete_pic, save_pic
from .menu import Menu
from .random_pic import random_pic

NICKNAME = list(get_driver().config.nickname)
BOT_NAME = os.getenv("DU_RUO_TING_BOT_NAME") or (NICKNAME[0] if NICKNAME else "小汀")

TIME = 0.0
USER_DATA = {}
MAX_MSG = [
    "暴饮暴食对身体不好，桓衍这么说的",
    "没吃的了……要不我去翻翻桓衍房间的小柜子？(▼皿▼#)",
    f"客官不要为难{BOT_NAME}了，{BOT_NAME}真的不知道做什么了……",
    f"没得吃的了，{BOT_NAME}的厨艺用尽了……",
    "对不起对不起对不起！下次我一定让桓衍多带点吃的上山ヽ(≧Д≦)ノ",
]

async def fetch_image_bytes(
    event: Event, bot: Bot, state, img: Image, **kwargs
) -> bytes | None:
    if img.raw:
        return img.raw_bytes
    if img.path:
        return Path(img.path).read_bytes()

    image_url = img.url
    if not image_url and img.id and bot.adapter.get_name() == "OneBot V11":
        try:
            image_url = (await bot.call_api("get_image", file=img.id))["url"]
        except Exception as e:
            logger.warning(
                f"Failed to resolve OneBot image url: {type(e).__name__}: {e}"
            )
            return None

    if not image_url:
        return None

    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
            resp = await client.get(image_url)
            resp.raise_for_status()
            return resp.content
    except httpx.HTTPError as e:
        logger.warning(f"Failed to download menu image: {type(e).__name__}: {e}")
        return None


eat_pic_matcher = on_alconna(
    Alconna("今天吃什么"),
    use_cmd_start=True,
)

drink_pic_matcher = on_alconna(
    Alconna("今天喝什么"),
    use_cmd_start=True,
)

view_menu_matcher = on_alconna(
    Alconna("全部菜单", Args["img_type?", str]),
    use_cmd_start=True,
    aliases=("查看菜单", "查看菜品"),
)

add_menu_matcher = on_alconna(
    Alconna(
        "添加菜单", Args["name?", str], Args["img_type?", str], Args["img?", Image]
    ),
    use_cmd_start=True,
)

del_menu_matcher = on_alconna(
    Alconna("删除菜单", Args["name?", str], Args["img_type?", str]),
    use_cmd_start=True,
)


eat_pic_matcher.shortcut(
    r"^(?:今|明|后)?(?:天|日)?(?:早|中|晚|上|下)?(?:上|午|餐|饭|夜宵|宵夜|早|晚)?吃(?:什么|啥|点啥)$",
    fuzzy=False,
    prefix=True,
)
drink_pic_matcher.shortcut(
    r"^(?:今|明|后)?(?:天|日)?(?:早|中|晚|上|下)?(?:上|午|餐|饭|夜宵|宵夜|早|晚)?喝(?:什么|啥|点啥)$",
    fuzzy=False,
    prefix=True,
)


@eat_pic_matcher.handle()
async def handle_eat_pic(event: Event):
    global TIME
    global USER_DATA
    check_max_result, USER_DATA = check_ismax(event, USER_DATA)
    check_result, remain_time, TIME = check_iscd(TIME)
    if check_max_result:
        await UniMessage.text(secrets.choice(MAX_MSG)).finish()
    elif check_result:
        await UniMessage.text(f"cd冷却中,还有{remain_time:.2f}秒").finish()
    else:
        pic_path, pic_name = random_pic("eat")
        send_msg = UniMessage(Text(f"🎉{BOT_NAME}觉得该吃🎉\n{pic_name}"))
        send_msg.append(Image(path=pic_path))
        await send_msg.finish()


@drink_pic_matcher.handle()
async def handle_drink_pic(event: Event):
    global TIME
    global USER_DATA
    check_max_result, USER_DATA = check_ismax(event, USER_DATA)
    check_result, remain_time, TIME = check_iscd(TIME)
    if check_max_result:
        await UniMessage.text(secrets.choice(MAX_MSG)).finish()
    elif check_result:
        await UniMessage.text(f"cd冷却中,还有{remain_time:.2f}秒").finish()
    else:
        pic_path, pic_name = random_pic("drink")
        send_msg = UniMessage(Text(f"🎉{BOT_NAME}想着该喝🎉\n{pic_name}"))
        send_msg.append(Image(path=pic_path))
        await send_msg.finish()


@view_menu_matcher.handle()
async def handle_view_menu(img_type: Match[str]):
    if img_type.available:
        view_menu_matcher.set_path_arg("img_type", img_type.result)


@view_menu_matcher.got_path("img_type", prompt=f"请告诉{BOT_NAME}这是什么类型的菜单嘛")
async def _(img_type: str):
    menu_type = img_type.strip()
    if menu_type in ["菜单", "菜品"]:
        menu_type = "eat"
    elif menu_type in ["饮料", "饮品"]:
        menu_type = "drink"
    else:
        await UniMessage.text("（思考）这是菜品还是饮品呢").finish()

    try:
        menu = Menu(menu_type)
        send_msg_list = UniMessage(Text("菜单有下面这些喔："))
        for img in menu.draw_menu():
            img_bytesio = io.BytesIO()
            img.save(img_bytesio, format="JPEG")
            send_msg_list.append(Image(raw=img_bytesio))  # type: ignore
        await send_msg_list.finish()
    except OSError as e:
        await UniMessage.text("桓衍好像没有做菜单欸……下次我去问问她\n{e}").finish()


@add_menu_matcher.handle()
async def _(name: Match[str], img_type: Match[str]):
    if name.available:
        add_menu_matcher.set_path_arg("name", name.result)
    if img_type.available:
        add_menu_matcher.set_path_arg("img_type", img_type.result)


@add_menu_matcher.got_path("name", prompt=f"请告诉{BOT_NAME}这个该命名成什么东西呢！")
async def _(name: str):
    if not name:
        await UniMessage.text("客官怎么不说话了……这个该叫什么呢").finish()


@add_menu_matcher.got_path("img_type", prompt=f"请告诉{BOT_NAME}这是什么类型的菜单嘛")
async def _(img_type: str):
    if img_type in ["菜品", "菜单"]:
        add_menu_matcher.set_path_arg("img_type", "eat")
    elif img_type in ["饮料", "饮品"]:
        add_menu_matcher.set_path_arg("img_type", "drink")
    else:
        await UniMessage.text("（思考）这是菜品还是饮品呢").finish()


@add_menu_matcher.got_path(
    "img", prompt=f"可以告诉{BOT_NAME}这个东西的图片吗，我下次照着做！", middleware=fetch_image_bytes
)
async def _(
    name: str,
    img_type: str,
    img: bytes,
):
    if not img:
        await UniMessage.text("没……没有图片吗……那我该怎么做呢……").finish()
    try:
        save_pic(img, img_type=img_type, name=name)
        await UniMessage.text(f"菜单上添加了{name}这个东西了喔！").finish()
    except OSError as e:
        await UniMessage.text(f"添加失败了……我问问桓衍怎么回事\n{e}").finish()


@del_menu_matcher.handle()
async def _(name: Match[str], img_type: Match[str]):
    if name.available:
        del_menu_matcher.set_path_arg("name", name.result)
    if img_type.available:
        del_menu_matcher.set_path_arg("img_type", img_type.result)


@del_menu_matcher.got_path("name", prompt=f"请告诉{BOT_NAME}要删除什么呢！")
async def _(name: str):
    if not name:
        await UniMessage.text("客官怎么不说话了……这个该叫什么呢").finish()


@del_menu_matcher.got_path("img_type", prompt=f"请告诉{BOT_NAME}这是什么类型的菜单嘛")
async def _(img_type: str, name: str):
    if img_type in ["菜品", "菜单"]:
        img_type = "eat"
    elif img_type in ["饮料", "饮品"]:
        img_type = "drink"
    else:
        await UniMessage.text("（思考）这是菜品还是饮品呢").finish()
    try:
        delete_pic(img_type, name)  # type: ignore
        await UniMessage.text(f"成功删除{name}，菜单上没有这个东西了喔！").finish()
    except FileNotFoundError as e:
        await UniMessage.text(f"没删除成功呢……我问问桓衍怎么回事").finish()


# 每日8点清空用户数据
@scheduler.scheduled_job("cron", hour=8)
async def _():
    USER_DATA.clear()
    logger.info("已清空用户数据")
