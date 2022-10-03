# -*- coding: utf-8 -*-
import requests
import json
import os
import time
import my_utils
from my_utils import my_error, my_log
from dotenv import load_dotenv, find_dotenv

# 从 .env 文件加载环境变量参数
load_dotenv(find_dotenv())

APP_ID = os.getenv("APP_ID")
APP_SECRET = os.getenv("APP_SECRET")
FEISHU_HOST = os.getenv("FEISHU_HOST")

CURRENT_PERIOD = "2022 年 10 月 - 12 月"

token_expire = time.time()

tenant_access_token = ''


# get the tenant_access_token
def get_access_token():
    global token_expire
    global tenant_access_token

    now = time.time()

    if now < token_expire - 10 and tenant_access_token:
        return tenant_access_token, ''

    url = "https://open.feishu.cn/open-apis/auth/v3/app_access_token/internal"

    payload = json.dumps({
        "app_id": APP_ID,
        "app_secret": APP_SECRET
    })

    headers = {
        'Content-Type': 'application/json'
    }

    response = requests.request("POST", url, headers=headers, data=payload)

    data = json.loads(response.text)
    """
    data is dict with
    app_access_token
    code
    expire
    msg
    tenant_access_token
    """
    # app_access_token = data['app_access_token']

    tenant_access_token = data['tenant_access_token']

    token_expire = time.time() + data['expire']

    return tenant_access_token, ''


def get_all_child_departments(dep_id):
    url = "https://open.feishu.cn/open-apis/contact/v3/departments/" + \
          dep_id + \
          "/children?department_id_type=open_department_id" \
          "&fetch_child=true&page_size=50&user_id_type=open_id"

    payload = ''

    tenant_access_token, app_access_token = get_access_token()

    headers = {
        'Authorization': 'Bearer ' + tenant_access_token
    }

    response = requests.request("GET", url, headers=headers, data=payload)

    data = json.loads(response.text)

    # load departments into a departments list

    departments_list = []
    if 'items' in data['data'].keys():
        for item in data['data']['items']:
            departments_list.append(item['open_department_id'])

    while data['data']['has_more']:
        page_token = data['data']['page_token']

        new_url = url + '&page_token=' + page_token

        response = requests.request("GET", new_url, headers=headers, data=payload)

        data = json.loads(response.text)

        if 'items' in data['data'].keys():
            for item in data['data']['items']:
                departments_list.append(item['open_department_id'])

    return departments_list


def get_all_direct_child_departs(open_dep_id):
    """
    Args:
        open_dep_id, String, the open id for department
    Return:
        List, each item is a son depart dict
        {
        "department_id": "xx",
        "i18n_name": {
          "en_us": "",
          "ja_jp": "",
          "zh_cn": ""
        },
        "leader_user_id": "xx",
        "leaders": [
          {
            "leaderID": "xx",
            "leaderType": 1
          }
        ],
        "member_count": 3,
        "name": "xx",
        "open_department_id": "oxxx",
        "order": "xx",
        "parent_department_id": "0",
        "status": {
          "is_deleted": false
        }
      }
    Reference:

    https://open.feishu.cn/document/uAjLw4CM/ukTMukTMukTM/reference/contact-v3/department/children
    """

    dep_list = []

    tenant_access_token, app_access_token = get_access_token()

    url = "https://open.feishu.cn/open-apis/contact/v3/departments/" + \
          open_dep_id + \
          "/children?department_id_type=open_department_id&page_size=10&user_id_type=open_id"
    payload = ''

    headers = {
        'Authorization': 'Bearer ' + tenant_access_token
    }

    response = requests.request("GET", url, headers=headers, data=payload)

    data = json.loads(response.text)

    # It is possible that there is no items key
    try:
        if 'items' in data['data'].keys():
            for dep in data['data']['items']:
                if dep not in dep_list:
                    dep_list.append(dep)
    except Exception as e:
        my_error(e)

    while 'has_more' in data['data'].keys() and data['data']['has_more']:
        page_token = data['data']['page_token']

        new_url = url + '&page_token=' + page_token

        response = requests.request("GET", new_url, headers=headers, data=payload)

        data = json.loads(response.text)

        # It is possible that there is no items key
        try:
            if 'items' in data['data'].keys():
                for dep in data['data']['items']:
                    if dep not in dep_list:
                        dep_list.append(dep)
        except Exception as e:
            my_error(e)

    return dep_list


def get_all_second_level_departs():
    first_level_departs = get_all_direct_child_departs("0")
    second_level_departs = []
    for fld in first_level_departs:
        if 'leader_user_id' in fld.keys():
            second_level_departs[len(second_level_departs):len(second_level_departs)] = \
                get_all_direct_child_departs(fld['open_department_id'])

    return second_level_departs


def _get_direct_user_dicts_in_dep(dep_id):

    user_dict_list = []

    tenant_access_token, app_access_token = get_access_token()

    headers = {
        'Authorization': 'Bearer ' + tenant_access_token
    }

    url = "https://open.feishu.cn/open-apis/contact/v3/users/find_by_department?department_id=" \
          + dep_id + "&department_id_type=open_department_id&page_size=50&user_id_type=open_id"

    payload = ''

    response = requests.request("GET", url, headers=headers, data=payload)

    data = json.loads(response.text)

    # It is possible that there is no items key
    try:
        if 'items' in data['data'].keys():
            for user in data['data']['items']:
                if user not in user_dict_list:
                    user_dict_list.append(user)

        while 'has_more' in data['data'].keys() and data['data']['has_more']:

            page_token = data['data']['page_token']

            new_url = url + '&page_token=' + page_token

            response = requests.request("GET", new_url, headers=headers, data=payload)

            data = json.loads(response.text)

            if 'items' in data['data'].keys():
                for user in data['data']['items']:
                    if user not in user_dict_list:
                        user_dict_list.append(user)

    except Exception as e:
        my_error(e)
        return []

    return user_dict_list


def get_direct_user_dicts_in_dep(dep_id):
    retry = 3
    result = _get_direct_user_dicts_in_dep(dep_id)
    while result == [] and retry > 0:
        retry -= 1
        result = _get_direct_user_dicts_in_dep(dep_id)
    return result


def get_direct_user_ids_in_dep(open_id):
    user_openid_list = []
    user_dict_list = get_direct_user_dicts_in_dep(open_id)
    for user in user_dict_list:
        user_openid_list.append(user['open_id'])
    return user_openid_list


def get_all_user_dict_from_feishu():
    """
    Return: A list of user
    A User is a dict.
    "avatar": a dict
    "city":
    "country":
    "customer_attrs": a list
    "department_ids": a list
    "description":
    "employee_no":
    "employee_type":
    "en_name":
    "nickname"
    "email"
    "gender":
    "is_tenant_manager": boolean
    "job_title":
    "join_time": long
    "leader_user_id":
    "mobile_visible": boolean
    "name": string, name of the user
    open_id": string
    "orders":list
    "status":dict
    "union_id":
    "user_id":
    "work_station":

    Reference:
    https://open.feishu.cn/document/uAjLw4CM/ukTMukTMukTM/reference/contact-v3/user/find_by_department
    """

    dep_list = get_all_child_departments("0")

    my_utils.my_log('we have %s departments' % len(dep_list), level='DEBUG')

    user_ids_list = []

    tenant_access_token, app_access_token = get_access_token()

    headers = {
        'Authorization': 'Bearer ' + tenant_access_token
    }

    for dep_id in dep_list:
        user_ids_list[len(user_ids_list):len(user_ids_list)] = get_direct_user_dicts_in_dep(dep_id)

    return my_utils.delete_duplicate_list(user_ids_list)


def get_all_users_in_dep(dep_id):
    """
    Return all the users in one dep in List.
    The element of the List is the open id
    """

    user_list = get_direct_user_ids_in_dep(dep_id)

    my_log('dep %s has %s direct user' % (dep_id, len(user_list)), level='DEBUG')

    dep_list = get_all_child_departments(dep_id)

    my_log('dep %s has %s child dep' % (dep_id, len(dep_list)), level='DEBUG')

    for dep_id in dep_list:
        user_list[len(user_list):len(user_list)] = get_direct_user_ids_in_dep(dep_id)

    user_list = list(set(user_list))

    my_log('dep %s has %s users' % (dep_id, len(user_list)), level='DEBUG')

    return user_list


def get_latest_okr_by_open_id(open_id):
    """
    return: the latest period OKR dict
    Input: open id of a user
    Ref: https://open.feishu.cn/document/uAjLw4CM/ukTMukTMukTM/reference/okr-v1/user-okr/list
    """

    tenant_access_token, app_access_token = get_access_token()

    url = "https://open.feishu.cn/open-apis/okr/v1/users/" \
          + open_id + "/okrs?lang=zh_cn&limit=10&offset=0&user_id_type=open_id"

    payload = ''

    headers = {
        'Authorization': 'Bearer ' + tenant_access_token
    }

    response = requests.request("GET", url, headers=headers, data=payload)

    data = json.loads(response.text)

    if data['code'] == 0:
        for i in range(len(data['data']['okr_list'])):
            if data['data']['okr_list'][i]['name'] == CURRENT_PERIOD:
                return data['data']['okr_list'][i]


def get_user_by_temp_auth(auth):
    """
    Args:
        auth: The temporary auth
    Return:
        the user dic of the user, look like
        data": {
        "access_token": "u-Qxxx",
        "token_type": "Bearer",
        "expires_in": 7140,
        "name": "zhangsan",
        "en_name": "Three Zhang",
        "avatar_url": "www.feishu.cn/avatar/icon",
        "avatar_thumb": "www.feishu.cn/avatar/icon_thumb",
        "avatar_middle": "www.feishu.cn/avatar/icon_middle",
        "avatar_big": "www.feishu.cn/avatar/icon_big",
        "open_id": "ou_xxx",
        "union_id": "on_xx",
        "email": "zhangsan@feishu.cn",
        "enterprise_email": "demo@mail.com",
        "user_id": "5d9bdxxx",
        "mobile": "+86130002883xx",
        "tenant_key": "736588c92xxx",
        "refresh_expires_in": 25919xx,
        "refresh_token": "ur-xxx"
        }
    Reference:
        https://open.feishu.cn/document/uAjLw4CM/ukTMukTMukTM/reference/authen-v1/authen/access_token
    """

    tenant_access_token, app_access_token = get_access_token()

    url = "https://open.feishu.cn/open-apis/authen/v1/access_token"

    payload = json.dumps({
        "code": auth,
        "grant_type": "authorization_code"
    })

    headers = {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ' + tenant_access_token
    }

    response = requests.request("POST", url, headers=headers, data=payload)

    data = json.loads(response.text)
    return data['data']


def send_notify(app, to_open_id, msg_content, msg_type):
    """
    Args:
        app, the Flask app obj, used to log correct message.
        to_open_id, String, the open id the message go to
        msg_content, see
        https://open.feishu.cn/document/uAjLw4CM/ukTMukTMukTM/im-v1/message/create_json#c9e08671
        msg_type:String, text, post, image,audio etc. Usally it is text or post.
    """
    url = "https://open.feishu.cn/open-apis/im/v1/messages"
    tenant_access_token, app_access_token = get_access_token()
    params = {"receive_id_type": "open_id"}

    req = {
        "receive_id": to_open_id,
        "content": json.dumps(msg_content),
        "msg_type": msg_type
    }
    payload = json.dumps(req)
    headers = {
        'Authorization': 'Bearer ' + tenant_access_token,  # your access token
        'Content-Type': 'application/json'
    }
    response = requests.request("POST", url, params=params, headers=headers, data=payload)
    app.logger.debug(response.headers['X-Tt-Logid'])  # for debug or oncall
    app.logger.debug(response.content)  # Print Response
    result = json.loads(response.content)
    return result['code']
