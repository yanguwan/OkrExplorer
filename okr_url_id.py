# -*- coding: utf-8 -*-
import json
import os
from my_utils import my_error
from dotenv import load_dotenv, find_dotenv

# the file is to get one user's OKR URL in the feishu OKR system, which is optional to the OkrEx.
# Instead, you can produce a new OKR display page for each user using the OKR data.

# get environmental parameter from .env files
load_dotenv(find_dotenv())

PINGCAP_FEISHU = os.getenv("PINGCAP_FEISHU")
PINGCAP_FEISH_HEAD = os.getenv("PINGCAP_FEISH_HEAD")

# cache file to speed up, in case calling server every round of update
URL_ID_FILE = 'url_id.txt'

url_json = {}


def fetch_okr_url_id(name):
    """
    Args:
        name:String, the name of a user or email of a user. email is preferred
    Return:
        The OKR url id, that can lead to the URL to the OKR page of the user
        User with same name, could return same url id by mistake. But it is very rare case.
    """
    command = 'curl -X GET %s%s -H %s' % ( PINGCAP_FEISHU, name, PINGCAP_FEISH_HEAD)
    print(command)
    try:
        stream = os.popen(command)
        content = stream.read()
        data = json.loads(content)
    except Exception as e:
        my_error(e)
        return ''

    return data['data']['user_list'][0]['id']


def get_okr_url_id(name):
    global url_json

    if not url_json:
        url_fp = open(URL_ID_FILE, 'r')
        try:
            url_json = json.load(url_fp)
        except Exception:
            pass
        url_fp.close()

    if url_json and name in url_json.keys() and url_json[name]:
        return url_json[name]
    else:
        url_id = fetch_okr_url_id(name)
        if not url_id:
            my_error("Cannot get url for user %s" % name)
        url_json[name] = url_id
        url_fp = open(URL_ID_FILE, 'w')
        json.dump(url_json, url_fp)
        url_fp.close()
        return url_id

