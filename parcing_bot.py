import os
import re
import sys
import time
import urllib
from urllib.request import urlopen
import config
import logging
import requests
import eventlet
import telebot
from logging.handlers import TimedRotatingFileHandler
import json

bot = telebot.TeleBot(config.tg_bot_token)  # setting up bot
WORKING_DIR = config.working_dir
LOG_DIR = WORKING_DIR + "/logs"
MAX_IDS_PER_JSON = config.maximum_ids_per_json

if len(str(config.tg_log_channel)) > 5:
    if config.tg_bot_for_log_token != "":
        bot_2 = telebot.TeleBot(config.tg_bot_for_log_token)
    else:
        bot_2 = telebot.TeleBot(config.tg_bot_token)
    is_bot_for_log = True
else:
    is_bot_for_log = False



#
# def get_data(x: config.language):
#     """Trying to request data from VK using vk_api
#
#     Returns:
#         List of N posts from vk.com/xxx, where
#             N = config.req_count
#             xxx = config.vk_domain
#     """
#     timeout = eventlet.Timeout(20)
#     try:
#         data = requests.get(
#             "https://api.vk.com/method/wall.get",
#             params={
#                 "access_token": x.vk_token,
#                 "v": x.req_version,
#                 "domain": x.vk_domain,
#                 "filter": x.req_filter,
#                 "count": x.req_count,
#             },
#         )
#         return data.json()["response"]["items"]
#     except eventlet.timeout.Timeout:
#         add_log("w", "Got Timeout while retrieving VK JSON data. Cancelling...")
#         return None
#     finally:
#         timeout.cancel()


def prepare_temp_folder():
    if "temp" in os.listdir(WORKING_DIR):
        for root, dirs, files in os.walk(WORKING_DIR + "/temp"):
            for file in files:
                os.remove(os.path.join(root, file))
    else:
        os.mkdir(WORKING_DIR + "/temp")


def blacklist_check(text, x: config.Language):
    """Checks text or links for forbidden words from config.BLACKLIST

    Args:
        text (string): message text or link
        x (L class): list for current language

    Returns:
        [bool]
    """
    if x.BLACKLIST:
        text_lower = text.lower()
        for black_word in x.BLACKLIST:
            if black_word.lower() in text_lower:
                return True
    return False


def whitelist_check(text, x: config.Language):
    """Checks text or links for filter words from config.WHITELIST

    Args:
        text (string): message text or link
        x (L class): list for current language

    Returns:
        [bool]
    """
    if x.WHITELIST:
        text_lower = text.lower()
        for white_word in x.WHITELIST:
            if white_word.lower() in text_lower:
                return False
        return True
    return False


def split_large_text(input_text: str, fragment_size: int) -> list:
    text_fragments = []
    for frament in range(0, len(input_text), fragment_size):
        text_fragments.append(input_text[frament : frament + fragment_size])
    return text_fragments


def ready_for_html(text):
    """All '<', '>' and '&' symbols that are not a part
    of a tag or an HTML entity must be replaced with the
    corresponding HTML entities:
    ('<' with '&lt;', '>' with '&gt;' and '&' with '&amp;')
    https://core.telegram.org/bots/api#html-style

    Args:
        text (str): Post text before replacing characters

    Returns:
        str: Text from Args, but with characters replaced
    """
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def compile_links_and_text(postid, text_of_post, links_list, videos_list, x: config.Language, *repost):
    """Compiles links to videos and other links with post text

    Args:
        postid (integer): Id of the post that is sent to Telegram. Used for better logging
        text_of_post (string): Just a post text
        links_list (list): link(s) from post attachments
        videos_list (list): link(s) to video(s) from post attachments
        x (Language class) for log

    Returns:
        text_of_post (string): Post text with links to videos and other links from post attachments
    """
    first_link = True

    def add_links(links):
        nonlocal first_link
        nonlocal text_of_post
        if links and links != [None]:
            for link in links:
                if link not in text_of_post:
                    if text_of_post:
                        if first_link:
                            text_of_post = f'<a href="{link}"> </a>{text_of_post}\n'
                            first_link = False
                        text_of_post += f"\n{link}"
                    else:
                        if first_link:
                            text_of_post += link
                            first_link = False
                        else:
                            text_of_post += f"\n{link}"

    if repost[0] == "repost":
        text_of_post = (
            f'<a href="{repost[1]}"><b>REPOST ↓ {repost[2]}</b></a>\n\n{text_of_post}'
        )
    try:
        add_links(videos_list)
        add_links(links_list)
        add_log("i", f"[id:{postid}] Link(s) was(were) added to post text", x)
    except Exception as ex:
        add_log(
            "e",
            f"[id:{postid}] [{type(ex).__name__}] in compile_links_and_text(): {str(ex)}",
            x,
        )
    return text_of_post


def send_posts(postid, text_of_post, photo_url_list, docs_list, x: config.Language):
    """Checks the type of post and sends it to Telegram in a suitable method

    Args:
        postid (integer): Id of the post that is sent to Telegram. Used for better logging
        text_of_post (string): Post text with links to videos and other links from post attachments
        photo_url_list (list): Photo URL list
        docs_list (list): List of urls to docs
        x (config.Language class item)
    """

    def start_sending():
        try:
            if len(photo_url_list) == 0:
                add_log("i", f"[id:{postid}] Bot is trying to send text post", x)
                send_text_post()
            elif len(photo_url_list) == 1:
                add_log("i", f"[id:{postid}] Bot is trying to send post with photo", x)
                send_photo_post()
            elif len(photo_url_list) >= 2:
                add_log("i", f"[id:{postid}] Bot is trying to send post with photos", x)
                send_photos_post()

            if docs_list:
                send_docs()
        except Exception as ex:
            add_log(
                "e",
                f"[id:{postid}] [{type(ex).__name__}] in start_sending(): {str(ex)}",
                x,
            )

    def send_text_post():
        try:
            if text_of_post:
                if len(text_of_post) < 4096:
                    bot.send_message(x.tg_channel, text_of_post, parse_mode="HTML")
                else:
                    text_parts = split_large_text(text_of_post, 4084)
                    prepared_text_parts = [
                        "(...) " + part + " (...)" for part in text_parts[1:-1]
                    ]
                    prepared_text_parts = (
                        [text_parts[0] + " (...)"]
                        + prepared_text_parts
                        + ["(...) " + text_parts[-1]]
                    )

                    for part in prepared_text_parts:
                        bot.send_message(
                            x.tg_channel, part, parse_mode="HTML"
                        )
                        time.sleep(1)
                add_log("i", f"[id:{postid}] Text post sent", x)
            else:
                add_log("i", f"[id:{postid}] Text post skipped because it is empty", x)
        except Exception as ex:
            if type(ex).__name__ == "ConnectionError":
                add_log(
                    "w",
                    f"[id:{postid}] [{type(ex).__name__}] in send_text_post(): {str(ex)}",
                    x,
                )
                add_log("i", f"[id:{postid}] Bot trying to resend message to user", x)
                time.sleep(3)
                send_text_post()
            add_log(
                "e",
                f"[id:{postid}] [{type(ex).__name__}] in send_text_post(): {str(ex)}",
                x,
            )

    def send_photo_post():
        try:
            if len(text_of_post) <= 1024:
                bot.send_photo(
                    x.tg_channel,
                    photo_url_list[0],
                    text_of_post,
                    parse_mode="HTML",
                )
                add_log("i", f"[id:{postid}] Text post (<1024) with photo sent", x)
            else:
                post_with_photo = f'<a href="{photo_url_list[0]}"> </a>{text_of_post}'
                if len(post_with_photo) <= 4096:
                    bot.send_message(
                        x.tg_channel, post_with_photo, parse_mode="HTML"
                    )
                else:
                    send_text_post()
                    bot.send_photo(x.tg_channel, photo_url_list[0])
                add_log("i", f"[id:{postid}] Text post (>1024) with photo sent", x)
        except Exception as ex:
            add_log(
                "e",
                f"[id:{postid}] [{type(ex).__name__}] in send_photo_post(): {str(ex)}",
                x
            )
            if type(ex).__name__ == "ConnectionError":
                add_log("i", f"[id:{postid}] Bot trying to resend message to user", x)
                time.sleep(3)
                send_photo_post()

    def send_photos_post():
        try:
            photo_list = []
            for url_photo in photo_url_list:
                photo_list.append(
                    telebot.types.InputMediaPhoto(urllib.request.urlopen(url_photo).read())
                )

            if 1024 >= len(text_of_post) > 0:
                photo_list[0].caption = text_of_post
                photo_list[0].parse_mode = "HTML"
            elif len(text_of_post) > 1024:
                send_text_post()
            bot.send_media_group(x.tg_channel, photo_list)
            add_log("i", f"[id:{postid}] Text post with photos sent", x)
        except Exception as ex:
            add_log(
                "e",
                f"[id:{postid}] [{type(ex).__name__}] in send_photos_post(): {str(ex)}",
                x
            )
            if type(ex).__name__ == "ConnectionError":
                add_log("i", f"[id:{postid}] Bot trying to resend message to user", x)
                time.sleep(3)
                send_photos_post()

    def send_docs():
        def send_doc(document):
            try:
                with open(WORKING_DIR + "/temp/" + document['title'], "rb") as file:
                    bot.send_document(x.tg_channel, file)

                add_log("i", f"[id:{postid}] Document [{document['type']}] sent", x)
            except Exception as ex:
                add_log(
                    "e",
                    f"[id:{postid}] [{type(ex).__name__}] in send_docs(): {str(ex)}",
                    x,
                )
                if type(ex).__name__ == "ConnectionError":
                    add_log("i", f"[id:{postid}] Bot trying to resend message to user", x)
                    time.sleep(3)
                    send_doc(document)

        for document in docs_list:
            send_doc(document)
            if len(docs_list) > 1:
                time.sleep(1)

    start_sending()


def parse_post(item, x: config.Language):
    """For each post in the received posts list:
        * Сhecks post id to make sure it is larger than the one written in the last_known_id.txt
        * Parses all attachments of post or repost
        * Calls 'compile_links_and_text()' to compile links to videos and other links from post to post text
        * Calls 'send_posts()' to send post to Telegram channel (config.tg_channel)

    Args:
        item json file from request: List of posts received from VK
        x: The current value in the last_known_id.txt
                           (must be less than id of the new post)
    """

    if blacklist_check(item["text"], x):
        add_log("i", f"[id:{item['id']}] Post was skipped due to blacklist filter", x)
    elif whitelist_check(item["text"], x):
        add_log("i", f"[id:{item['id']}] Post was skipped due to whitelist filter", x)
    else:

        if x.skip_ads_posts and item["marked_as_ads"] == 1:
            add_log(
                "i",
                f"[id:{item['id']}] Post was skipped because it was flagged as ad",
                x,
            )
            pass
        if x.skip_copyrighted_post and "copyright" in item:
            add_log(
                "i",
                f"[id:{item['id']}] Post was skipped because it has copyright",
                x,
            )
            pass
        add_log("i", f"[id:{item['id']}] Bot is working with this post", x)

        prepare_temp_folder()  ############ MAYBE X HERE ???

        def get_link(attachment):
            try:
                link_object = attachment["link"]["url"]

                if link_object not in text_of_post:
                    return link_object
            except Exception as ex:
                add_log(
                    "e",
                    f'[id:{item["id"]}] [{type(ex).__name__}] in get_link(): {str(ex)}',
                    x,
                )

        def get_video(attachment):
            def get_video_url(owner_id, video_id, access_key):
                try:
                    data = requests.get(
                        "https://api.vk.com/method/video.get",
                        params={
                            "access_token": x.vk_token,
                            "v": x.req_version,
                            "videos": f"{owner_id}_{video_id}_{access_key}",
                        },
                    )

                    return data.json()["response"]["items"][0]["files"]["external"]
                except Exception:
                    return None

            try:
                video = get_video_url(
                    attachment["video"]["owner_id"],
                    attachment["video"]["id"],
                    attachment["video"]["access_key"],
                )
                # wait for a few seconds because VK can deactivate the access token due to frequent requests
                time.sleep(2)
                if video is not None:
                    return video
                else:
                    return f"https://vk.com/video{attachment['video']['owner_id']}_{attachment['video']['id']}"
            except Exception as ex:
                add_log(
                    "e",
                    f'[id:{item["id"]}] [{type(ex).__name__}] in get_video(): {str(ex)}',
                    x,
                )

        def get_photo(attachment):
            try:
                # check the size of the photo and add this photo to the URL list
                # (from large to smaller)
                # photo with type W > Z > Y > X > (...)
                photo_sizes = attachment["photo"]["sizes"]
                photo_types = ["w", "z", "y", "x", "r", "q", "p", "o", "m", "s"]
                for photo_type in photo_types:
                    if next(
                        (item for item in photo_sizes if item["type"] == photo_type),
                        False,
                    ):
                        return next(
                            (
                                item
                                for item in photo_sizes
                                if item["type"] == photo_type
                            ),
                            False,
                        )["url"]
            except Exception as ex:
                add_log(
                    "e",
                    f'[id:{item["id"]}] [{type(ex).__name__}] in get_photo(): {str(ex)}',
                    x,
                )

        def get_doc(document):
            document_types = {
                1: "text_document",
                2: "archive",
                3: "gif",
                4: "image",
                5: "audio",
                6: "video",
                7: "ebook",
                8: "unknown",
            }
            document_type = document_types[document["type"]]
            if document["size"] > 50000000:
                add_log("i", f"Document [{document['type']}] skipped because it > 50 MB", x)
                return
            else:
                response = requests.get(document["url"])

                with open(WORKING_DIR + "/temp/" + document['title'], "wb") as file:
                    file.write(response.content)

            return {
                "type": document_type,
                "title": document["title"],
                "url": document["url"],
            }

        def get_public_name_by_id(owner_id):
            try:
                data = requests.get(
                    "https://api.vk.com/method/groups.getById",
                    params={
                        "access_token": x.vk_token,
                        "v": x.req_version,
                        "group_id": owner_id,
                    },
                )
                return data.json()["response"][0]["name"]
            except Exception as ex:
                add_log(
                    "e",
                    f'[id:{item["id"]}] [{type(ex).__name__}] in get_public_name_by_id(): {str(ex)}',
                    x,
                )
                return ""

        def parse_attachments(item, links_list, vids_list, photos_list, docs_list):
            
            try:
                for attachment in item["attachments"]:
                    if attachment["type"] == "link":
                        links_list.append(get_link(attachment))
                    elif attachment["type"] == "video":
                        temp_vid = get_video(attachment)
                        if temp_vid is not None:
                            vids_list.append(temp_vid)
                    elif attachment["type"] == "photo":
                        photos_list.append(
                            re.sub(
                                "&([a-zA-Z]+(_[a-zA-Z]+)+)=([a-zA-Z0-9-_]+)",
                                "",
                                get_photo(attachment),
                            )
                        )
                    elif attachment["type"] == "doc":
                        doc_data = get_doc(attachment["doc"])
                        if doc_data:
                            docs_list.append(doc_data)
            except Exception as ex:
                add_log(
                    "e",
                    f'[id:{item["id"]}] [{type(ex).__name__}] in parse_attachments(): {str(ex)}',
                    x,
                )

        try:
            text_of_post = ready_for_html(item["text"])
            links_list = []
            videos_list = []
            photo_url_list = []
            docs_list = []

            if "attachments" in item:
                parse_attachments(
                    item, links_list, videos_list, photo_url_list, docs_list
                )
            text_of_post = compile_links_and_text(
                item["id"],
                text_of_post,
                links_list,
                videos_list,
                x,
                "post",
            )
            if "copy_history" in item and text_of_post != "":
                group_name = get_public_name_by_id(
                    abs(item["copy_history"][0]["owner_id"])
                )
                text_of_post = f"""{text_of_post}\n\nREPOST ↓ {group_name}"""
            send_posts(item["id"], text_of_post, photo_url_list, docs_list, x)

            if "copy_history" in item:
                item_repost = item["copy_history"][0]
                link_to_reposted_post = (
                    f"https://vk.com/wall{item_repost['from_id']}_{item_repost['id']}"
                )
                text_of_post_rep = ready_for_html(item_repost["text"])
                links_list_rep = []
                videos_list_rep = []
                photo_url_list_rep = []
                docs_list_rep = []
                group_id = abs(item_repost["owner_id"])
                group_name = get_public_name_by_id(group_id)

                if "attachments" in item_repost:
                    parse_attachments(
                        item_repost,
                        links_list_rep,
                        videos_list_rep,
                        photo_url_list_rep,
                        docs_list_rep,
                    )
                text_of_post_rep = compile_links_and_text(
                    item["id"],
                    text_of_post_rep,
                    links_list_rep,
                    videos_list_rep,
                    x,
                    "repost",
                    link_to_reposted_post,
                    group_name,
                )
                send_posts(
                    item["id"],
                    text_of_post_rep,
                    photo_url_list_rep,
                    docs_list_rep,
                    x,
                )
        except Exception as ex:
            add_log(
                "e",
                f'[id:{item["id"]}] [{type(ex).__name__}] in parse_posts(): {str(ex)}',
                x,
            )


def get_data(x: config.Language):
    """Trying to request data from VK using vk_api

    Returns:
        List of N posts from vk.com/xxx, where
            N = config.req_count
            xxx = config.vk_domain
    """
    timeout = eventlet.Timeout(20)
    try:
        data = requests.get(
            "https://api.vk.com/method/wall.get",
            params={
                "access_token": x.vk_token,
                "v": x.req_version,
                "domain": x.vk_domain,
                "filter": x.req_filter,
                "count": x.req_count,
            },
        )
        return data.json()["response"]["items"]
    except eventlet.timeout.Timeout:
        add_log("w", "Got Timeout while retrieving VK JSON data from " + x.vk_domain + ". Cancelling..", x)
        return None
    finally:
        timeout.cancel()


def check_admin_status(specific_bot: telebot.TeleBot, x: config.Language):
    """Checks if the bot is a channel administrator

    Args:
        specific_bot (string): Defines which bot will be checked
        x (config.Language): get tg channel name from here
    """
    if x == config.Dummy:
        return False
    else:
        try:
            _ = specific_bot.get_chat_administrators(x.tg_channel)
            return True
        except Exception:
            add_log(
                "e",
                f"Bot is not channel admin [{x.tg_channel}] or Telegram Servers are down..\n",
                x,
            )
            return False


def check_new_post(x: config.Language):
    """Gets list of posts from get_data(),
    compares posts ids with ids from the *languge*.json file.
    Sends posts one by one to parse_posts(), writes new posts into .json"""
    if not check_admin_status(bot, x):
        add_log("w", f"There is no admin permission for the bot in a chat ", x)
        pass
    add_log("i", "Scanning for new posts in ", x)
    with open(WORKING_DIR + '/jsons/' + x.jsonfile, "r") as file:
        try:
            sent_ids = json.load(file)
            ###
            #   sent_ids = [684, 98789, 654654, 6546]
            ###
        except:
            add_log("e", "Could not read from storage. Skipped iteration for ", x)
            pass
    try:
        feed = get_data(x)
        if feed is not None:
            for post in feed:
                if post['id'] not in sent_ids:
                    add_log("i", f"Got fresh post id:{post['id']}", x)
                    parse_post(post, x)
                    sent_ids.append(post['id'])
            if len(sent_ids) > MAX_IDS_PER_JSON:
                sent_ids = sent_ids[-MAX_IDS_PER_JSON:]
            with open(WORKING_DIR + '/jsons/' + x.jsonfile, "w") as file:
                json.dump(sent_ids, file)
    except Exception as ex:
        add_log("e", f"[{type(ex).__name__}] in check_new_post(): {str(ex)}", x)
    add_log("i", "Scanning finished", x)


def send_log(log_message, x: config.Language):
    """Sends logs to config.tg_log_channel channel

    Args:
        log_message (string): Logging text
        x (Language class): In order to know which vk.com/@xxx to add to the end of a log message
    """
    try:
        log_message_temp = (
            f"<code>{log_message}</code>\n"
            f"tg_channel = {config.tg_log_channel}\n"
            f"vk_domain = <code>{x.vk_domain}</code>"
        )
        bot_2.send_message(
            config.tg_log_channel, log_message_temp, parse_mode="HTML"
        )
    except Exception as ex:
        global logger
        logger.error(f"[{type(ex).__name__}] in send_log(): {str(ex)}")


def add_log(type_of_log: str, text: str, x: config.Language):
    """Unifies logging and makes it easier to use

    Args:
        type_of_log (string): Type of logging message (warning / info / error)
        text (string): Logging text
        x (Language class): Config-defined language
    """
    types = {"w": "WARNING", "i": "INFO", "e": "ERROR"}
    log_message = f"[{types[type_of_log]}] {text}"
    if type_of_log == "w":  # WARNING
        logger.warning(text)
    elif type_of_log == "i":  # INFO
        logger.info(text)
    elif type_of_log == "e":  # ERROR
        logger.error(text)

    global is_bot_for_log
    if is_bot_for_log and check_admin_status(bot_2, x):
        time.sleep(1)
        send_log(log_message, x)


def check_python_version():
    """Checks Python version.
    Will close script if Python version is lower than required
    """
    if sys.version_info[0] == 2 or sys.version_info[1] <= 5:
        print('Required python version for this bot is "3.6+"..\n')
        exit()


if __name__ == "__main__":

    check_python_version()

    if not os.path.exists(LOG_DIR):
        os.makedirs(LOG_DIR)

    logger = logging.getLogger('main-log-writer')
    logger.setLevel(logging.DEBUG)
    formatter = logging.Formatter('%(asctime)s - %(message)s')
    logHandler = logging.handlers.RotatingFileHandler(LOG_DIR + '/' + config.logfile, maxBytes=1024 * 500, backupCount=3)
    logHandler.setLevel(logging.DEBUG)
    logHandler.setFormatter(formatter)
    logger.addHandler(logHandler)
    logger.info('\n------------\n Started script \n------------\n')

    try:
        if not config.single_start:
            while True:
                for language in config.list_of_languages:
                    check_new_post(language)
                add_log("i", f"Script went to sleep for {config.time_to_sleep} seconds\n\n", config.Dummy)
                time.sleep(int(config.time_to_sleep))
        else:
            for language in config.list_of_languages:
                check_new_post(language)
            add_log("i", "Script exited.", config.Dummy)
    except:
        add_log("e", "Something went wrong in a main loop", config.Dummy)
    finally:
        add_log("i", "\n------------\nScript ended\n------------\n", config.Dummy)



