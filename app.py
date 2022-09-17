# -*- coding: utf-8 -*-
import json
from flask import Flask, render_template, request, session, jsonify
from flask_sqlalchemy import SQLAlchemy
import os
import time
import datetime
import redis
import re
import hashlib
import my_utils
from auth import Auth
from dotenv import load_dotenv, find_dotenv
import requests
import get_data_from_feishu
from collections import deque
import threading
import logging
from logging.handlers import RotatingFileHandler

# Random string, used to encrypt
NONCE_STR = os.urandom(12).hex()

# get environmental parameter from .env files
load_dotenv(find_dotenv())

my_app = Flask(__name__, static_url_path="/static", static_folder="./static")

# Get Env Parameters
APP_ID = os.getenv("APP_ID")
APP_SECRET = os.getenv("APP_SECRET")
FEISHU_HOST = os.getenv("FEISHU_HOST")
RB_CODE = os.getenv("RB_CODE")
DB_HOST = os.getenv("DB_HOST")
DB_USER = os.getenv("DB_USER")
DB_PASSWD = os.getenv("DB_PASSWD")
DATABASE = os.getenv("DATABASE")
DB_PORT = os.getenv("DB_PORT")
REDIS_PORT = os.getenv("REDIS_PORT") if os.getenv("REDIS_PORT") else '6379'
SECRET_KEY = os.getenv("SECRET_KEY")
URL_BASE = os.getenv("URL_BASE")
SEGS_CHANGED = os.getenv("SEGS_CHANGED")
OKR_EX_SERVER = os.getenv("OKR_EX_SERVER")
OKREX_APP_URL = os.getenv("OKREX_APP_URL")
OKREX_SERVER_PORT = os.getenv("OKREX_SERVER_PORT")
DEBUG_USER_ID = os.getenv("DEBUG_USER_ID")

SQLALCHEMY__DB_URI = 'mysql+pymysql://{}:{}@{}:{}/{}'.format(DB_USER, DB_PASSWD, DB_HOST, DB_PORT, DATABASE)

my_app.config['SQLALCHEMY_DATABASE_URI'] = SQLALCHEMY__DB_URI
my_app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False  # 关闭对模型修改的监控
my_app.config['SECRET_KEY'] = SECRET_KEY

my_app.config['LOG_FILE_FILENAME'] = "okrserver.log"

fileHandler = RotatingFileHandler(
    my_app.config['LOG_FILE_FILENAME'],
    maxBytes=2 * 1024 * 1024,
    backupCount=3,
    encoding="UTF-8"
)
my_app.logger.addHandler(fileHandler)
my_app.logger.setLevel(logging.DEBUG)


# Flask error handler
@my_app.errorhandler(Exception)
def auth_error_handler(ex):
    response = jsonify(message=str(ex))
    response.status_code = (
        ex.response.status_code if isinstance(ex, requests.HTTPError) else 500
    )
    return response


# Initialize the Auth, use APP ID, APP SECRET to obtain access token and jsapi_ticket
auth = Auth(FEISHU_HOST, APP_ID, APP_SECRET)

# db is the connector to the TiDB Database
db = SQLAlchemy(my_app)

rds = redis.Redis(host='127.0.0.1',
                  port=int(REDIS_PORT),
                  decode_responses=True,
                  charset='UTF-8',
                  encoding='UTF-8')
# const
pagesize = 20


# internal functions, only called within this file, start with _

def _get_leader(open_id):
    return rds.hget(name=open_id, key='leader')


def _get_direct_subordinates(leader):
    """
    System build phase only
    """
    direct_subs = []

    for sub in leader['sub']:
        direct_subs.append(sub['id'])

    return direct_subs


def _get_subordinates(leader):
    """
    System build phase only
    Args:
        leader, kv block
    Return:
        list of ids
    """
    subs = _get_direct_subordinates(leader)
    for sub in leader['sub']:
        subs.extend(_get_subordinates(sub))
    return subs


def _attach(user, leader):
    """
    Attach a user to a leader.

    Both are user KV block mentioned in function build_leadership_forest
    """
    if user['id'] not in [u['id'] for u in leader['sub']]:
        leader['sub'].append(user)


def _in_forest(forest, leader_id):
    """
    Return the leader kv block if the leader is in the forest.
    Otherwise return None
    Precondition:
    User must have leader
    """

    for root in forest:
        q = deque()
        q.append(root)
        while q:
            for _ in range(len(q)):  # extend in the end of for loop does not affect the loop times
                node = q.popleft()
                if node['id'] == leader_id:
                    return node
                q.extend(node['sub'])

        return {}


def _join_leaders_forest(forest, user):
    """
    Args:
        forest, List of forest roots, element is top leader
        user, user KV block to join
    Return:
        None. While forest will be update
    """
    leader_id = _get_leader(user['id'])
    while leader_id:
        leader = _in_forest(forest, leader_id)
        if leader:
            _attach(user, leader)
            return
        else:  # your leader is not in forest. create the leader
            leader = {'id': leader_id, 'sub': []}
            _attach(user, leader)
            leader_id = _get_leader(leader_id)
            user = leader

    # user is the top level leader, create a new tree
    forest.append(user)


def _traverse_forest(forest):
    for root in forest:
        q = deque()
        q.append(root)
        while q:
            for _ in range(len(q)):  # extend in the end of for loop does not affect the loop times
                node = q.popleft()
                yield node
                q.extend(node['sub'])


def _build_leadership_forest(users):
    """
    Args:
        tup list of users
    Return:
        Return the roots List of the leadership forest
    Precondition:
        Users basic data has been put in Redis
    Notice:
        Each user will be expressed in key-value
        {
        "id": open_id,
        "sub":[
            {
            "id":open_id,
            "sub":[
                {
                }
                ...
                ]
            }
            ...
            ]
        }
    """
    forest = []
    for user in users:
        user_kv = {'id': user.open_id, 'sub': []}
        _join_leaders_forest(forest, user_kv)
    return forest


def _is_subordinate(leader_open_id, open_id):
    """
    Return true if <open_id> is the subordinate of <leader_open_id>,
    otherwise return False
    """
    if open_id == '':
        return False

    leader = _get_leader(open_id)
    while leader:
        if leader == leader_open_id:
            return True
        leader = _get_leader(leader)
    return False


def final_display_list(ordered_open_id_list,
                       search_str,
                       pagesize=20,
                       page_no=0,
                       high_recommend=0,
                       em=True):
    """
    Args:
        ordered_open_id_list: List, ordered user list by match degree
        search_str: String
        pagesize: how many item will be displayed in one page
        page_no: the number of the page that is displaying
        high_recommend: how many itesm is high lighted
        em: Boolean, browser page need em, while Feishu notification does not need
    Return:
        Display list, prepare the final display list, for a page, usually there are pagesize of items
        each element is an objective of Searchdisplay
    """
    display_list = []
    touched = 0

    for open_id in ordered_open_id_list:
        touched += 1
        if touched <= pagesize * page_no:  # skip the previous pages
            continue

        mentioning_user_name = rds.hget(name=open_id, key='name')
        if not mentioning_user_name:  # it is possible the user has gone
            continue

        sd = Searchdisplay()

        sd.whose = rds.hget(name=open_id, key='name')

        sd.who_id = open_id

        sd.url = URL_BASE + rds.hget(name=open_id, key='url_id')

        okr_str = rds.hget(name=open_id, key='okr')

        # split it by any number of blank
        search_str_list = re.split(r"[ ]+", search_str)

        okr_content, nil, nil = my_utils.get_okrcontent_from_okr_str(okr_str, search_str_list, my_app)

        if em:  # emphasize the key word in the okr_content, true by default.
            beg_em_str = '<em style="color:red;">'
            end_em_str = '</em>'

            for seg in search_str_list:
                reg = re.compile(re.escape(seg), re.IGNORECASE)
                okr_content = reg.sub(beg_em_str + seg + end_em_str, okr_content)

        sd.okr_content = okr_content

        # use to highlight those high match
        if touched <= high_recommend:
            sd.highly = 'highly'
        else:
            sd.highly = ''

        sd.avatar = rds.hget(name=open_id, key='avatar')

        display_list.append(sd)

        if touched - pagesize * page_no >= pagesize:
            break
    return display_list


def _init_search_str(search_str):
    search_str = search_str.strip()

    search_str = search_str.replace(';', '')  # key word must not contain ;

    return search_str


"""
def find_user_by_id(leader_list, open_id):
    if open_id == '':
        return
    for leader in leader_list:
        if leader['id'] == open_id:
            return leader

"""


def keep_alive():
    msg = Okr_server_msg.query.all()
    return msg


def load_users_tbl_to_redis():
    """
    load users table information to redis as cache.
    Also build up the leader tree
    """

    users = Users.query.all()
    for user in users:
        rds.hset(name=user.open_id, key='okr', value=user.okr)
        rds.hset(name=user.open_id, key='name', value=user.name)
        rds.hset(name=user.open_id, key='url_id', value=user.url_id)
        rds.hset(name=user.open_id, key='email', value=user.email)
        rds.hset(name=user.open_id, key='en_name', value=user.en_name)
        rds.hset(name=user.open_id, key='leader', value=user.leader)
        rds.hset(name=user.open_id, key='avatar', value=user.avatar)

    forest = _build_leadership_forest(users)
    iterator = _traverse_forest(forest)

    for node in iterator:
        if _get_direct_subordinates(node):
            rds.hset(name=node['id'], key='direct_sub', value=';'.join(_get_direct_subordinates(node)))
            rds.hset(name=node['id'], key='all_sub', value=';'.join(_get_subordinates(node)))


def update_search_str_in_redis():
    """
    Update the search_str:open_id list pair in redis.

    Usually it needs to be call during the rebuild process, after key2user table is updated

    return 'success'.

    """
    my_app.logger.debug('Entering update_search_str_in_redis')
    tup = Okr_server_msg.query.filter_by(name=SEGS_CHANGED).first()

    changed_seg_list = []

    if tup:  # tup[0] should be segs string delimiter by ;
        changed_seg_list = tup.value.split(';')
    my_app.logger.debug(changed_seg_list)
    for key in rds.scan_iter('#search_str#*'):
        search_str_list = re.split(r"[ ]+", key)  # one blank or multiple blank as split
        # there are changed set appears in the key, we need delete the key
        if set(changed_seg_list) & set(search_str_list):
            rds.delete(key)

    return 'success'


def get_ordered_open_id_list(search_str):
    """
    Args:
        search_str: String, search string after initialization
    Return:
        ordered_open_id_list: List, the open id (user) whose OKR mentions the search_str.
        It is ordered by the match level
        high_recommend_amount: Int, the # of top open_id should be highly recommended.
    """
    # it is the final open_id list
    ordered_open_id_list = rds.lrange('#search_str#' + search_str, 0, -1)
    my_app.logger.debug('open id length is %s' % len(ordered_open_id_list))

    if not ordered_open_id_list:
        high_recommend_amount = 0
        # Step 1: try the search str as a whole
        tup = Key2user.query.filter_by(seg=search_str).first()
        if tup:
            my_utils.add_to_list(ordered_open_id_list, tup.open_id_list)

        # for search str more than one word, the urls will be counted as high recommendation

        if search_str.find(' ') > 0:
            high_recommend_amount += len(ordered_open_id_list)

        # step2: try the key split by blank in the search string

        search_str_list = re.split(r"[ ]+", search_str)  # one blank or multiple blank as split

        temp_open_id_list = []  # temporally for url priority(order)

        open_id_priority_dict = {}

        for search_item in search_str_list:
            # record the search into the TiDB as searching history
            record = Search_rec.query.get(search_item[0:31])
            if not record:  # there is no the record
                record = Search_rec(searched_key=search_item[0:31],  # searched_key is 32 long at most
                                    freq=1,
                                    search_date=datetime.datetime.today())
                db.session.add(record)

            else:
                record.freq += 1
                record.search_date = datetime.datetime.today()

            db.session.commit()
            # try to see if it is people name， use like %{}% to find possible users

            like_str = '%{}%'.format(search_item)
            tup_list = Users.query.filter(Users.name.like(like_str)).all()

            for tup in tup_list:
                my_utils.add_to_list(ordered_open_id_list, tup.open_id)
                high_recommend_amount += 1

            # all keys in the key2user is lowercase to make case-insensitive
            search_item = search_item.lower()

            tup = Key2user.query.filter_by(seg=search_item).first()
            if tup:
                my_utils.add_to_list(temp_open_id_list, tup.open_id_list)
        # make  elements unique and keep same order
        open_id_ordered_unique = sorted(set(temp_open_id_list), key=temp_open_id_list.index)

        for item in open_id_ordered_unique:
            open_id_priority_dict[item] = temp_open_id_list.count(item)

        ordered_tup_list = my_utils.list_from_dict_by_val(open_id_priority_dict)  # the tup is like ('open_id',4)

        for t in ordered_tup_list:
            if t[0] not in ordered_open_id_list:  # in case duplicated entry
                ordered_open_id_list.append(t[0])  # so far the ordered_open id_list is the url to be shown
                if t[1] > 1:  # for open id appears in the two seg, consider it as high recommendation
                    high_recommend_amount += 1

        # keep the final ordered url list into redis
        for u in ordered_open_id_list:
            rds.rpush('#search_str#' + search_str, u)

        # also keep the high_recommend_amount into redis
        rds.set('#high_recommend#' + search_str, high_recommend_amount)
    else:
        high_recommend_amount = int(rds.get('#high_recommend#' + search_str))

    return ordered_open_id_list, high_recommend_amount


def basic_search(search_str, page_no=0):
    """
    Args:
        search_str: String, the searching string input by user
        page_no: Int, the page number that show, defaut is 0
    Returns:
        display: List, each item contains "who's OKR", url, and okt str snapshot
        count: Int, the total amount of the items matched by the search
        page_list: List, like ['0','1',...] pages to display all the matched items
    """

    search_str = _init_search_str(search_str)

    ordered_open_id_list, high_recommend_amount = get_ordered_open_id_list(search_str)
    count = len(ordered_open_id_list)
    pages = int(count / pagesize) + 1

    # prepare the final display information,
    # each item is a list with (name's OKR, okr_url, ork_str_snapshot)

    display = final_display_list(ordered_open_id_list, search_str,
                                 pagesize, page_no,
                                 high_recommend_amount)

    pages_list = []
    i = 0
    while i < pages:
        pages_list.append(str(i))
        i += 1
    return display, count, pages_list


def add_subscribe(open_id, key_word):
    """
    Args:
        open_id: String, the open_id for a user
        key_word: String, the key word that the user is going to subscribe
    Return:
        'success'
    """
    record = Sbscrb.query.get(key_word)
    # record = Subscribe.query.filter_by(keyword=key_word).first()
    added = False
    if not record:  # there is no the record
        key_word = _init_search_str(key_word)
        open_ids_list, high_recommend = get_ordered_open_id_list(key_word)
        open_ids = ';'.join(open_ids_list)
        record = Sbscrb(keyword=key_word,
                        subscribers=open_id,
                        open_ids=open_ids,
                        new_open_ids='',
                        subs_date=datetime.datetime.today())
        db.session.add(record)
        added = True
    else:
        if open_id not in record.subscribers:
            record.subscribers = record.subscribers + ';' + open_id
            record.subs_date = datetime.datetime.today()
            added = True

    db.session.commit()
    # send notify for subscribing one key word
    if added:
        sd_list = cal_urls_dict(record.open_ids.split(';'), key_word)
        notify_dic = {open_id: {key_word: sd_list}}
        send_notify_messages(notify_dic, title='You subscribed the key word %s' % key_word)
        return 'added'
    else:
        return 'duplicated'


def rm_subscribe(open_id, key_word):
    """
    Remove a specific subscribed key_word for the user

    Return:
        'success' or <error message>
    """
    my_app.logger.debug('rm_subscribe is called, keyword is %s' % key_word)

    record = Sbscrb.query.get(key_word)
    if not record:
        return 'Key word not found'
    else:
        if open_id not in record.subscribers:
            return 'You have not subscribed the key word'
        else:
            if record.subscribers.index(open_id) == 0:  # the first one
                if record.subscribers.count(';') == 0:  # the only one,we need remove the record
                    db.session.delete(record)
                    deleted = True
                else:
                    record.subscribers = record.subscribers.replace(open_id + ';', '')  # remove xxx;
                    record.subs_date = datetime.datetime.today()
                    deleted = True
            else:
                record.subscribers = record.subscribers.replace(';' + open_id, '')  # remove ;xxx
                record.subs_date = datetime.datetime.today()
                deleted = True
    db.session.commit()
    if deleted:
        return 'deleted'
    else:
        return 'Not found'


def get_subscribe_key_word(open_id):
    """
    Args:
        open_id: String, the open_id for a user
    Return:
        Key word List: List, the key word that the user is subscribing
    """
    # the value in the redis is delimitered by #, keyword#lenght#date
    key_word_rich_list_cache = rds.lrange('#subscriber#' + open_id, 0, -1)
    key_word_rich_list = []

    if not key_word_rich_list_cache:
        like_str = '%{}%'.format(open_id)
        tup_list = Sbscrb.query.filter(Sbscrb.subscribers.like(like_str)).all()

        for tup in tup_list:
            key_word_rich_list.append([tup.keyword, str(len(tup.open_ids.split(';'))), str(tup.subs_date)])

        for key_word_rich in key_word_rich_list:
            rds.rpush('#subscriber#' + open_id, '#'.join(key_word_rich))
    else:
        for key_word_cache in key_word_rich_list_cache:
            key_word_rich_list.append(key_word_cache.split('#'))

    return key_word_rich_list


def cal_urls_dict(open_id_list, search_str):
    """
    Args:
        search_str subscribed
    Return:
        a list of elements, element is
         objective os class Searchdisplay, see Searchdisplay class
    """
    # pagesize means only the top page size items are listed. used to send message to feishu
    return final_display_list(open_id_list, search_str, pagesize=10, em=False)


def send_notify_messages(notify_dic, title="okrExplorer Subscription Notification"):
    """
    Argus:
        notify_dic is the dic mentioned in rebuild_sbscrb_notify
        Send feishu msg to subscriber in one batch.
        Each subscriber just get on msg in one round
    The struction of notify_dic:
    # {'ouxxx1':  <=== subscriber1
    #
    #    {'search1': [Searchdisplay,...],
    #      'search2': [],
    #       ...
    #    }
    #  'ouxxx2': <==== subscriber2
    #    {'search1': [Searchdisplay,...],
    #      'search2':[],
    #       ...
    #    }
    #   ...
    # }
    """
    msgContent = {
        "en_us": {
            "title": title,
            "content": []
        }
    }

    # a pair of head_content_block and body_content_block map to one keyword
    # content_block is  an element of "content", one cb is a list of tag block

    for subscriber in notify_dic.keys():
        for key_word, display_list in notify_dic[subscriber].items():
            head_content_block = []
            my_app.logger.debug("sending message keyword is %s" % key_word)
            # for one key word
            tag_block = {"tag": "a",
                         "href": OKREX_APP_URL,
                         "text": "---Key word: %s---" % key_word}
            head_content_block.append(tag_block)
            msgContent['en_us']['content'].append(head_content_block)  # push in head

            for display in display_list:
                body_content_block = []
                tag_block = {"tag": "at",
                             "user_id": display.who_id,
                             "user_name": "okrServer"
                             }
                body_content_block.append(tag_block)

                tag_block = {
                    "tag": "a",
                    "href": display.url,
                    "text": "'s OKR"
                }
                body_content_block.append(tag_block)

                tag_block = {
                    "tag": "text",
                    "text": display.okr_content
                }
                body_content_block.append(tag_block)
                msgContent['en_us']['content'].append(body_content_block)  # push body

        # for each subscriber, send one notification msg
        result = get_data_from_feishu.send_notify(my_app, subscriber, msgContent)

        if result != 0:
            my_app.logger.error("Error sending msg to %s" % subscriber)
        else:
            my_app.logger.debug("successfully send msg to %s" % subscriber)

    return True


def compose_notify_msg(msg_dict):
    """
    Args:
        msg is a dictionary mentioned in rebuild_sbscrb_notify
         {'search1': [Searchdisplay,...],
           'search2': [],
            ...
         }
    Return:
        String, the msg content
    """
    msg = ''
    for keyword in msg_dict.keys():
        msg += 'keyword is %s\n' % keyword
        for sd in msg_dict[keyword]:
            msg += '%s mentioned the key\n' % sd.whose
            msg += 'The content is %s\n' % sd.okr_content
    return msg


def rebuild_sbscrb_notify():
    """
    update the subscription table and send notification to subscribers if changes occurs
    """

    # notify is a dict notify_dict
    # keys are the subscriber user's open id
    # value of each key is a deeper level dict
    # keys are the search_str
    # value of each key is a list of Searchdisplay

    # {'ouxxx1':  <=== subscriber1
    #
    #    {'search1': [Searchdisplay,...],
    #      'search2': [],
    #       ...
    #    }
    #  'ouxxx2': <==== subscriber2
    #    {'search1': [Searchdisplay,...],
    #      'search2':[],
    #       ...
    #    }
    #   ...
    # }

    my_app.logger.debug('start to rebuild_sbscrb_notify ')

    notify_dict = {}

    records = Sbscrb.query.all()

    temp_dict = {}
    for record in records:
        new_mentioner_id_list, high_recommend = get_ordered_open_id_list(record.keyword)
        # save the new_mentioner_id_list for use later
        temp_dict[record.keyword] = new_mentioner_id_list
        delta = set(new_mentioner_id_list) - set(record.open_ids.split(';'))
        delta_list = list(delta)
        my_app.logger.debug('delta list for the keyword %s:' % record.keyword)
        my_app.logger.debug(delta_list)
        if delta_list:
            search_display_list = cal_urls_dict(delta_list, record.keyword)

            # calculate the notify data structure
            # we will send notify message according to it later. The logic is a little complex here
            subscribers_list = record.subscribers.split(';')
            for subscriber in subscribers_list:
                if subscriber in notify_dict.keys():  # the subscriber has been in the notify_dict
                    subscriber_value_dict = notify_dict[subscriber]  # the dict must be there
                    if record.keyword in subscriber_value_dict.keys():  # should not occur this condition
                        subscriber_value_dict[record.keyword].extends(search_display_list)
                    else:
                        subscriber_value_dict[record.keyword] = search_display_list
                else:  # the subscriber get the first appearance in the notify dict
                    notify_dict[subscriber] = {record.keyword: search_display_list}
        else:
            pass

    # send messages in one batch, instead of multiple messages,avoid noisy
    if send_notify_messages(notify_dict):
        # update the sbscrb table only notify sent successfully
        for record in records:
            new_mentioner_id_list = temp_dict[record.keyword]
            record.open_ids = ';'.join(new_mentioner_id_list)
            record.subs_date = datetime.datetime.today()
            db.session.commit()


def get_departments_health_info(parent):
    """
    Args:
        parent, String, department id
    Return:
        a List of the direct child depart of the parent, element is a 6 element list.

        Child Department name,
        Leader name,
        Team size,
        Available OKR,
        Ratio
        Not_health_user, which is a list of [name,url_id, avatar]
    """
    departs = []

    tup_list = Departments.query.filter_by(parent_dep_id=parent).all()

    for tup in tup_list:
        leader_name = rds.hget(name=tup.leader, key='name')
        depart = [tup.name,
                  leader_name,
                  tup.member_count,
                  tup.avail_okr_count,
                  float('%.1f' % (int(tup.avail_okr_count) / int(tup.member_count) * 100)),
                  [
                      [rds.hget(name=u, key='name'),
                       URL_BASE + rds.hget(name=u, key='url_id'),
                       rds.hget(name=u, key='avatar')]
                      for u in tup.not_health_user.split(';')] if tup.not_health_user else []
                  ]
        departs.append(depart)
    return departs


def get_obj_list_from_okr_str(okr_str):
    """
    Args:
        okr_str: String, transferred from okr dict
        Return:
            obj list
            Reference:
            https://open.feishu.cn/document/uAjLw4CM/ukTMukTMukTM/reference/okr-v1/user-okr/list
    """

    if not okr_str:
        return []

    try:
        data = json.loads(okr_str, strict=False)
    except Exception as e:
        my_app.logger.error(e)

    return data['objective_list']


def get_obj_by_obj_id(open_id, obj_id):
    """
    Arguments:
        open_id, String User
        id, String, objective id
    Return:
        Objetive block
        https://open.feishu.cn/document/uAjLw4CM/ukTMukTMukTM/reference/okr-v1/user-okr/list
        Obj list element
    """
    obj_list = get_obj_list_from_okr_str(rds.hget(name=open_id, key='okr'))

    for obj in obj_list:
        if obj['id'] == obj_id:
            return obj
    return {}


def mentioned_people_list(obj):
    """
    Args:
        Obj dict,
        Reference https://open.feishu.cn/document/uAjLw4CM/ukTMukTMukTM/reference/okr-v1/user-okr/list
    Return:
        Open id List directly mentioned in the obj
    """

    mentioned_list = []
    if not obj:
        return mentioned_list
    try:
        for mentioned in obj['mentioned_user_list']:
            mentioned_list.append(mentioned['open_id'])

        for kr in obj['kr_list']:
            for mentioned in kr['mentioned_user_list']:
                mentioned_list.append(mentioned['open_id'])
    except Exception as e:  # some one do not have kr_list
        my_app.logger.error(e)

    return list(set(mentioned_list))


def count_people_on_obj(open_id, obj):
    """
    Args:
        open_id, String, who has the obj
        OKR obj
        https://open.feishu.cn/document/uAjLw4CM/ukTMukTMukTM/reference/okr-v1/user-okr/list
        Notice: Aligned and aligning objs are dict like
        {
            "id": "7115374114517467138",
            "okr_id": "7109919013166530588",
            "owner": {
                "open_id": "ou_db8862f87c8586931bde2d7ef7b0725b",
                "user_id": "ou_db8862f87c8586931bde2d7ef7b0725b"
            }
        }
    Return:
        People list who is aligned to the obj.
    """
    people_name_list = [open_id]  # add myself first
    people_leveraged_name_list = mentioned_people_list(obj)

    for aligned_obj in obj['aligned_objective_list']:  # child objs
        objective = get_obj_by_obj_id(aligned_obj['owner']['open_id'], aligned_obj['id'])
        if objective:  # since people dynamically change, the obj could be none
            if _is_subordinate(open_id, aligned_obj['owner']['open_id']):  # only count in subordinates
                p_list, p_l_list = count_people_on_obj(aligned_obj['owner']['open_id'], objective)
                people_name_list.extend(p_list)
                people_leveraged_name_list.extend(p_l_list)
            else:  # count into leveraged people if not my subordinates
                people_leveraged_name_list.extend(mentioned_people_list(objective))

    people_name_list = list(set(people_name_list))
    people_leveraged_name_list = list(set(people_leveraged_name_list))

    return people_name_list, people_leveraged_name_list


def heartbeat():
    """
    expired
    """
    command = 'curl -X GET http://127.0.0.1:%s/heartbeat?rb=%s' % (OKREX_SERVER_PORT, RB_CODE)
    my_app.logger.debug('thread %s is running...' % threading.current_thread().name)
    while True:
        time.sleep(2 * 3600)
        try:
            stream = os.popen(command)
            content = stream.read()
            data = json.loads(content)
        except Exception as e:
            my_app.logger.error(e)
        my_app.logger.debug(data)

    my_app.logger.debug('thread %s ended.' % threading.current_thread().name)
    return data


def get_invisible_people(open_id, people_on_total):
    """
    Args:
        open_id, the leader of the department
        people_on_total, List of people are visible
    Return:
        People list in the department ,but not in the people_on_total
    Notice:
        This is quicker version
    """
    my_subordinates_str = rds.hget(name=open_id, key='all_sub')

    if my_subordinates_str:
        my_total_people = my_subordinates_str.split(';')
        return list(set(my_total_people) - set(people_on_total))

    return ''


def get_objs_stat_info(open_id):
    """
    Return:
        the okr objs statistics info for the user openid
        objs is a List, each element is an obj, containing the following info
        <obj id>: String, obj id
        <howmany>: String, how many people are working on the Obj (aligning to it)
        <people>: List, the user name are workong on the obj
        <howmany>:String, how many people are mentioned by the Obj
        <people>: List, the user name list are mentioned by the obj

        Also the list of invisible people [name,url_id,avatar]

    """
    okr_str = rds.hget(name=open_id, key='okr')
    obj_list = get_obj_list_from_okr_str(okr_str)
    obj_stat_list = []
    i = 0
    people_on_total = []
    for obj in obj_list:
        people_on, people_leveraged = count_people_on_obj(open_id, obj)
        people_on_total.extend(people_on)  # record all people in all objs
        # remove my own people from the people_leverage_name_list
        people_external_leverage = []
        for leveraged in people_leveraged:
            if not _is_subordinate(open_id, leveraged):
                people_external_leverage.append(leveraged)

        people_on.sort()
        people_external_leverage.sort()
        people_on = [rds.hget(name=o_id, key='name') for o_id in people_on]
        people_external_leverage = [rds.hget(name=o_id, key='name') for o_id in people_external_leverage]
        people_on = list(filter(None, people_on))  # Along with the employee change, there are None people possibly
        people_external_leverage = list(filter(None, people_external_leverage))
        i += 1

        obj_stat_list.append(['Obj%s' % i,
                              str(len(people_on)),
                              ','.join(people_on),
                              str(len(people_external_leverage)),
                              ','.join(people_external_leverage)])

    people_list_invisible = get_invisible_people(open_id, people_on_total)
    _people_list_invisible = [[rds.hget(name=o_id, key='name'),
                               URL_BASE + rds.hget(name=o_id, key='url_id'),  # we can optimize here later
                               rds.hget(name=o_id, key='avatar')]
                              for o_id in people_list_invisible]
    return obj_stat_list, \
           _people_list_invisible, \
           float('%.1f' % ((1 - len(people_list_invisible) / len(people_on_total)) * 100)), \
           float(len(people_external_leverage) / len(people_on_total))


def get_top_search_keyword(num):
    """
    Return the top num search keyword as a list
    """
    word_list = []
    tup_list = Search_rec.query.order_by(Search_rec.freq.desc()).limit(num).all()
    number_one = 1
    for tup in tup_list:
        number_one = tup.freq if tup.freq > number_one else number_one
        ele = [tup.searched_key, tup.freq, int(tup.freq / number_one * 100)]
        word_list.append(ele)
    return word_list


@my_app.route("/", methods=["GET"])
def get_home():
    return render_template("index.html")


@my_app.route("/user", methods=["GET"])
def get_user():
    authcode = request.args.get("u")
    if authcode:
        user = get_data_from_feishu.get_user_by_temp_auth(authcode)
        session['user'] = user['open_id']
    else:
        debug_user = request.args.get('debug_user')
        if debug_user and debug_user == RB_CODE:
            session['user'] = DEBUG_USER_ID  # roger

    return jsonify(
        {
            "message": "success"
        }
    )


@my_app.route("/subscribe", methods=["GET"])
def get_subscribe():
    my_app.logger.debug('current user is %s' % session['user'])
    key_word = request.args.get("key")
    if key_word:  # add one subscription for the user
        msg = add_subscribe(session['user'], key_word)
        if msg == 'added':  # if really changed, delete the key in cache to trigger re-calculation next time
            rds.delete('#subscriber#' + session['user'])
        return jsonify(
            {
                "message": msg
            }
        )
    else:  # list all the subscription for the user
        key_word_rich_list = get_subscribe_key_word(session['user'])
        return render_template('subscribe.html',
                               current_user=rds.hget(name=session['user'], key='name'),
                               key_word_rich_list=key_word_rich_list)


@my_app.route("/unsubscribe", methods=["GET"])
def get_unsubscribe():
    key_word = request.args.get("key")
    if key_word:  # remove one subscription for the user
        msg = rm_subscribe(session['user'], key_word)
        # if msg == 'deleted': # always delete from unsubscribe button
        rds.delete('#subscriber#' + session['user'])
        return jsonify(
            {
                "message": msg
            }
        )
    else:
        return jsonify(
            {
                "message": "No key word provided"
            }
        )


@my_app.route('/rb_users')
def get_rebuild_users():
    rb_str = request.args.get('rb')
    my_app.logger.debug(rb_str)
    if rb_str == RB_CODE:
        load_users_tbl_to_redis()
        return jsonify(
            {
                "message": "success"
            }
        )
    else:
        return jsonify(
            {
                "message": "wrong rebuild code"
            }
        )


# Serve the caller to get configuration
@my_app.route("/get_config_parameters", methods=["GET"])
def get_config_parameters():
    # who is calling
    url = request.args.get("url")
    # get jsapi_ticket
    ticket = auth.get_ticket()
    # current time stamp in milliseconds
    timestamp = int(time.time()) * 1000
    # group into the string
    verify_str = "jsapi_ticket={}&noncestr={}&timestamp={}&url={}".format(
        ticket, NONCE_STR, timestamp, url
    )
    # sha1 the string, get the signature
    signature = hashlib.sha1(verify_str.encode("utf-8")).hexdigest()
    # return the parameters to the caller
    return jsonify(
        {
            "appid": APP_ID,
            "ticket": ticket,
            "signature": signature,
            "noncestr": NONCE_STR,
            "timestamp": timestamp,
        }
    )


@my_app.route('/okr', methods=['GET', 'POST'])
def search():
    if not session['user']:
        return render_template('404.html')

    t1 = time.time()

    if request.method == 'GET' and not request.args.get('search'):
        return render_template('index.html')

    username = session['user']

    if request.method == 'POST':
        search_str = request.form.get('search')
    elif request.method == 'GET':
        search_str = request.args.get('search')

    else:
        pass

    my_app.logger.debug('search str is %s' % search_str)

    if search_str == '':
        return render_template('index.html')

    display, count, pages_list = basic_search(search_str)

    t2 = time.time()

    elapsed = (t2 - t1) * 1000  # in milliseconds

    elapsed_str = "Elapsed time: %.3f milliseconds" % elapsed

    return render_template('result.html',
                           search_str=search_str,
                           count=count,
                           pages_list=pages_list,
                           display=display,
                           pages=len(pages_list),
                           pageno=str(0),
                           elapsed_str=elapsed_str,
                           username=username)


@my_app.route('/page/<int:page_no>')
def get_page(page_no=0):
    if not session['user']:
        return render_template('404.html')

    t1 = time.time()
    search_str = request.args.get('s')
    display, count, pages_list = basic_search(search_str, page_no)
    t2 = time.time()
    elasped = (t2 - t1) * 1000
    elasped_str = "Elapsed time: %.3f milliseconds" % elasped
    username = session['user']
    return render_template('result.html',
                           search_str=search_str,
                           count=count,
                           pages_list=pages_list,
                           display=display,
                           pages=len(pages_list),
                           pageno=str(page_no),
                           elasped_str=elasped_str,
                           username=username)


# The second one is triggered by admin manually and periodically (opokr.py)
@my_app.route('/rebuild')
def get_rebuild():
    rb_str = request.args.get('rb')
    if rb_str == RB_CODE:
        # when it arrives here,it means possibly the uers table has been updated and key2user table also be updated
        # so reload the users table from TiDB to redis
        load_users_tbl_to_redis()
        my_app.logger.debug('Finished load_users_tbl_to_redis')
        # update the redis cache for the search_str
        my_app.logger.debug('update the redis cache for the search_str')
        update_search_str_in_redis()
        # start rebuild the sbscrb table and notify subscribers
        my_app.logger.debug('start rebuild the sbscrb table and notify subscribers')
        rebuild_sbscrb_notify()
        my_app.logger.debug('Finished rebuild the sbscrb table and notify subscribers')
        return jsonify(
            {
                "message": "success"
            }
        )
    else:
        return jsonify(
            {
                "message": "wrong rebuild code"
            }
        )


# triggered by the child thread period, for the heart-beat, incase tidb cloud hibernates
@my_app.route('/heartbeat')
def send_heartbeat():
    rb_str = request.args.get('rb')
    if rb_str == RB_CODE:
        keep_alive()
        my_app.logger.debug('Finished keep_alive')
        return jsonify(
            {
                "message": "success"
            }
        )
    else:
        return jsonify(
            {
                "message": "wrong rebuild code"
            }
        )


@my_app.route('/health')
def get_health():
    if not session['user']:
        return render_template('404.html')
    who = request.args.get('who')

    if not who:
        departs = get_departments_health_info('0')
        departs_list = [['PingCAP OKR Set Ratio', departs]]
    elif who == 'me':
        departs_list = []
        tup_list_temp = Departments.query.filter_by(leader=session['user']).all()
        for tup in tup_list_temp:
            departs = get_departments_health_info(tup.open_dep_id)
            if departs:
                ele = [tup.name + 's OKR Set Ratio', departs]
                departs_list.append(ele)

    elif who == 'sub':
        departs = ''
    else:
        return render_template('404.html')
    return render_template("health.html", departs_list=departs_list)


@my_app.route('/graph')
def get_graph():
    if session['user'] == '':
        return render_template('404.html')
    who = request.args.get('who')
    objs_list = []
    if not who:  # return the current user's
        objs, invisible_people, align_ratio, leverage_ratio = get_objs_stat_info(session['user'])
        objs_list.append([rds.hget(name=session['user'], key='name'),
                          objs,
                          invisible_people,
                          align_ratio,
                          leverage_ratio])

    elif who == 'sub':
        sub_str = rds.hget(name=session['user'], key='direct_sub')
        if sub_str:
            direct_report_list = sub_str.split(';')
            for sub_user in direct_report_list:
                objs, invisible_people, align_ratio, leverage_ratio = get_objs_stat_info(sub_user)
                objs_list.append([rds.hget(name=sub_user, key='name'),
                                  objs,
                                  invisible_people,
                                  align_ratio,
                                  leverage_ratio])

    return render_template("graph.html", objs_list=objs_list)


@my_app.route('/OoO')
def get_OoO():
    if not session['user']:
        return render_template('404.html')

    return render_template('OoO.html')


@my_app.route('/analytic')
def get_analytic():
    """
     each element of he word_list
     item[0]: key word
     item[1]: times
     item[2]: percentage comparing to the first place
    """
    word_list = get_top_search_keyword(20)
    return render_template('analytic.html', word_list=word_list)


class Key2user(db.Model):
    seg = db.Column(db.String(128), primary_key=True, unique=True, nullable=False)
    open_id_list = db.Column(db.Text)
    freq = db.Column(db.Integer)
    howchanged = db.Column(db.String(64))


class Users(db.Model):
    open_id = db.Column(db.String(64), primary_key=True, nullable=False)
    okr = db.Column(db.Text)
    name = db.Column(db.String(64), nullable=False)
    url_id = db.Column(db.String(64))
    email = db.Column(db.String(64))
    en_name = db.Column(db.String(64))
    leader = db.Column(db.String(64))
    avatar = db.Column(db.String(256))


class Sbscrb(db.Model):
    keyword = db.Column(db.String(128), nullable=False, primary_key=True)
    subscribers = db.Column(db.Text)
    open_ids = db.Column(db.Text)  # not sure why Text will cause hang when insert through SQLChemy
    new_open_ids = db.Column(db.Text)
    subs_date = db.Column(db.DateTime)


class Search_rec(db.Model):
    searched_key = db.Column(db.String(32), nullable=False, primary_key=True)
    freq = db.Column(db.Integer, nullable=False)
    search_date = db.Column(db.DateTime, nullable=True)


class Departments(db.Model):
    open_dep_id = db.Column(db.String(64), nullable=False, primary_key=True)
    name = db.Column(db.String(64), nullable=False)
    leader = db.Column(db.String(64))  # open id
    dep_level = db.Column(db.Integer)
    member_count = db.Column(db.Integer)
    avail_okr_count = db.Column(db.Integer)
    not_health_user = db.Column(db.Text)
    parent_dep_id = db.Column(db.Integer)


class Okr_server_msg(db.Model):
    name = db.Column(db.String(128), nullable=False, primary_key=True)
    value = db.Column(db.Text)


class Searchdisplay():
    def __init__(self):
        pass

    """
    item[0]=>roger's OKR
    item[1]=>url
    item[2]=>OKR content
    item[3]=> highly or not
    item[4]=>avatar
    """

    def struct(self, whose, open_id, url, okr_content, highly, avatar):
        self.whose = whose
        self.who_id = open_id
        self.url = url
        self.okr_content = okr_content
        self.highly = highly
        self.avatar = avatar


# load users to redis as the initialization
load_users_tbl_to_redis()
if __name__ == '__main__':
    t = threading.Thread(target=heartbeat, name='okrExHeartbeat')
    t.setDaemon(True)
    t.start()
    my_app.logger.debug('Starting...OkrEx')
    my_app.run(host='0.0.0.0', port=int(OKREX_SERVER_PORT), debug=True)
