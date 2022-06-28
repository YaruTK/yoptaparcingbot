import os
from pathlib import Path

working_dir = "D://programming/parcer"
current_folder = str(Path(__file__).parent.absolute())
maximum_ids_per_json = 100

if working_dir == "":
    working_dir = current_folder

list_of_languages = []
tg_bot_token = "#####################"
tg_bot_for_log_token = ""
tg_log_channel = "#####################"
logfile = "logs.log"
single_start = False
time_to_sleep = 60 * 10


class Language:

    req_filter = "all"
    vk_token = "#####################"
    name = ""
    req_count = 10
    req_version = 5.131
    skip_ads_posts = True
    skip_copyrighted_post = False
    _is_pinned_post = False
    vk_domain = ""
    tg_channel = ""

    def __init__(self, lang="language (short), e.g. en / de / ...", at_vk="vk domain", at_tg="tg chat id or domain",
                 blacklist="list of words to ignore posts", whitelist="leave empty"):
        self.name = lang
        self.vk_domain = at_vk
        self.tg_channel = at_tg
        self.BLACKLIST = blacklist
        self.WHITELIST = whitelist
        self.jsonfile = lang + ".json"

        if not os.path.exists(working_dir + '/jsons/' + self.jsonfile):
            try:
                os.mkdir(working_dir + '/jsons')
            except:
                pass
            with open(working_dir + '/jsons/' + self.jsonfile, "w") as file:
                file.write("[]")
                file.close()
        list_of_languages.append(self)

    def __del__(self):
        try:
            list_of_languages.remove(self)
        except:
            print("There was a problem deleting file")


Dummy = Language("#####################", "#####################", "#####################", "", "")


