# -*- coding: utf-8 -*-
import inspect
import logging
import os
import datetime
import json


def init_log(logfile, level='WARNING'):
    # print('init_log to %s...' % logfile)
    if level == 'DEBUG':
        logging.basicConfig(filename=logfile, encoding='utf-8', level=logging.DEBUG)
    elif level == 'ERROR':
        logging.basicConfig(filename=logfile, encoding='utf-8', level=logging.ERROR)
    elif level == 'WARNING':
        logging.basicConfig(filename=logfile, encoding='utf-8', level=logging.WARNING)
    elif level == 'INFO':
        logging.basicConfig(filename=logfile, encoding='utf-8', level=logging.INFO)
    else:
        logging.basicConfig(filename=logfile, encoding='utf-8', level=logging.WARNING)


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
    logging.log(logging.ERROR, message)


def my_log(msg, level='DEBUG'):
    """
    Args:
        msg, String

    The function will display the log messages
    """
    if level == 'DEBUG':
        lev = logging.DEBUG
    elif level == 'ERROR':
        lev = logging.ERROR
    elif level == 'WARNING':
        lev = logging.WARNING
    elif level == 'INFO':
        lev = logging.INFO
    else:
        lev = logging.DEBUG
    logging.log(lev, "%s:%s" % (datetime.datetime.today(), msg))
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


def get_okrcontent_from_okr_str(okr_str, seg_list=[]):
    """
    Args:
        okr_str: String, transferred from okr dict
        seg_list: List, the segmentation list to match okr content. default is Null
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
        my_error('%s: okr_str is %s' % (e, okr_str))

    return '\n'.join(okr_content_list), avail_objs, no_kr


def add_to_list(to_list, list_semicol):

    _list = list_semicol.split(';')

    for li in _list:
        to_list.append(li)
    return


# the function is to order dict by the value
def list_from_dict_by_val(url_priority_dict):
    return sorted(url_priority_dict.items(), key=lambda x: x[1], reverse=True)
