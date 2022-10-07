# -*- coding: utf-8 -*-
import jieba
from dotenv import load_dotenv, find_dotenv
import os

# get env parameters
import my_utils

load_dotenv(find_dotenv())

STOP_WORDS = os.getenv("STOP_WORDS")

stop_list = []


def load_stop_words():
    global stop_list

    if stop_list:
        return stop_list

    with open(STOP_WORDS, 'r') as f:
        line = f.readline()
        while line:
            line = line.replace('\n', '')
            stop_list.append(line)
            line = f.readline()
        f.close()

    return stop_list


def my_seg(to_seg_str):

    seged_list = []
    stop_words_list = load_stop_words()

    seg_list = jieba.lcut_for_search(to_seg_str)

    for seg in seg_list:
        seg = seg.strip()
        if seg \
                and not my_utils.single_asc(seg) \
                and seg not in stop_words_list \
                and seg.find(';') < 0:
            seged_list.append(seg.lower())  # to make non case-insensitive, uniform to lower case

    return list(set(seged_list))
