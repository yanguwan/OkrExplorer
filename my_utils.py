# -*- coding: utf-8 -*-
import inspect
import logging
from logging.handlers import RotatingFileHandler
import os
import datetime
import json


def init_log(logfile, level='WARNING'):
    logger = logging.getLogger('')

    Rthandler = RotatingFileHandler(logfile, maxBytes=10 * 1024 * 1024, backupCount=5)

    if level == 'DEBUG':
        level = logging.DEBUG
    elif level == 'ERROR':
        level = logging.ERROR
    elif level == 'WARNING':
        level = logging.WARNING
    elif level == 'INFO':
        level = logging.INFO
    else:
        level = logging.WARNING

    logger.setLevel(level)

    formatter = logging.Formatter('%(asctime)s %(filename)s %(levelname)s %(process)d %(message)s')
    Rthandler.setFormatter(formatter)
    logger.addHandler(Rthandler)


def delete_duplicate_list(li):
    temp_list = list(set([str(i) for i in li]))
    li = [eval(i) for i in temp_list]
    return li


def my_error(e):
    """
    Args:
        e: Exception or String
    The function will display the error information and places
    """

    message = '%s: process %s => %s(): Error is %s' % (
        datetime.datetime.today(), os.getpid(), inspect.stack()[1].function, e)

    # logging.debug(message)
    logger = logging.getLogger('')
    logger.error(message)


def my_log(msg, level='DEBUG'):
    """
    Args:
        msg, String

    The function will display the log messages
    """
    logger = logging.getLogger('')

    if level == 'DEBUG':
        # lev = logging.DEBUG
        logger.debug(msg)
    elif level == 'ERROR':
        # lev = logging.ERROR
        logger.error(msg)
    elif level == 'WARNING':
        # lev = logging.WARNING
        logger.warn(msg)
    elif level == 'INFO':
        # lev = logging.INFO
        logger.info(msg)
    else:
        # lev = logging.DEBUG
        logger.debug(msg)
    # logging.log(lev, "%s:%s" % (datetime.datetime.today(), msg))
    # print('%s(): %s' % (inspect.stack()[1].function, log))


def find_any_of(the_str, the_list):
    """
    return True if the str contains any of the list
    otherwise, return False

    It is non case-sensitive
    """

    for item in the_list:
        if the_str.lower().find(item.lower()) >= 0:
            return True
    return False


def single_asc(a):
    return ord(a) < 128 if len(a) == 1 else False


def get_okrcontent_from_okr_str(okr_str, seg_list=[], app=None):
    """
    Args:
        okr_str: String, transferred from okr dict
        seg_list: List, the segmentation list to match okr content. default is Null
        app: The flask app, means the caller is from Flask. default is Null
        Return:
            String. Contain the real content consistent of Objs+KRs, and the number of the health objs.
            if seg, only return the Objs or KR contains any of the segs
            Reference:
            https://open.feishu.cn/document/uAjLw4CM/ukTMukTMukTM/reference/okr-v1/user-okr/list
            get_latest_okr_by_open_id()
    """
    avail_objs = 0
    no_kr = 0
    if not okr_str:
        return '', avail_objs, no_kr

    okr_content_list = []

    obj_number = 0

    try:
        data = json.loads(okr_str, strict=False)
        for obj in data['objective_list']:
            kr_number = 0
            obj_number += 1
            if not seg_list or find_any_of(obj['content'], seg_list):
                okr_content_list.append('O%s: %s' % (obj_number, obj['content']))
            if 'kr_list' in obj.keys():
                avail_objs += 1  # A healthy obj must have kr
                for kr in obj['kr_list']:
                    kr_number += 1
                    if not seg_list or find_any_of(kr['content'], seg_list):
                        okr_content_list.append('O%s->KR%s: %s' % (obj_number, kr_number, kr['content']))
            else:
                no_kr += 1
    except Exception as e:
        if not app:
            my_error('%s: okr_str is %s' % (e, okr_str))
        else:
            app.logger.error('%s: okr_str is %s' % (e, okr_str))

    return '\n'.join(okr_content_list), avail_objs, no_kr


def add_to_list(to_list, list_semicol):
    _list = list_semicol.split(';')

    for li in _list:
        to_list.append(li)
    return


# the function is to order dict by the value,
def list_from_dict_by_val(url_priority_dict):
    """
    Args:
        url_priority_dict, dict
    Return:
        A list of tuple, descending with value
        like [(key1, v1),(key2, v2)...]
    """
    return sorted(url_priority_dict.items(), key=lambda x: x[1], reverse=True)


def cal_avail_obj_by_okr_dict(okr_dict):
    avail_objs = 0  # how many healthy objs under this OKR
    no_kr = 0  # how many OBJs that has no any KR
    for obj in okr_dict['objective_list']:
        if 'kr_list' in obj.keys():
            avail_objs += 1  # A healthy obj must have kr
        else:
            no_kr += 1

    return avail_objs, no_kr
