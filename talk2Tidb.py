# -*- coding: utf-8 -*-
import pymysql
from dotenv import load_dotenv, find_dotenv
import os

from my_utils import my_error, my_log

# get environmental parameter from .env files
load_dotenv(find_dotenv())

DB_HOST = os.getenv("DB_HOST")
DB_USER = os.getenv("DB_USER")
DB_PASSWD = os.getenv("DB_PASSWD")
DATABASE = os.getenv("DATABASE")
DB_PORT = os.getenv("DB_PORT")


# connect to my tidb
def connect_tidb_okr():
    try:
        db = pymysql.connect(host=DB_HOST,
                             user=DB_USER,
                             password=DB_PASSWD,
                             database=DATABASE,
                             port=int(DB_PORT),
                             autocommit=True)
        return db
    except Exception as e:
        my_error(e)
        return


def close_tidb_okr(db):
    if db:
        db.close()


def replace_user_entry(db, tbl, open_id, okr_str, name, url_id, email, en_name, leader, avatar, avail_obj, obj_nokr,
                       segs, hashcode,
                       hasupdate):
    """
    Args:
        db: the pymysql db object
        tbl: table name, string
        open_id: String, the primary key of the table users
        okr_str: String, the okr str transferred from okr dict
        name: String, an user's primary name, not null
        url_id:String, 19-digits, forms feishu ork url with a fixed prefix
        email:String, email address
        en_name: String, english name, possible null
        leader: String or '', leader's open id of the user
        avatar: String, URL to the avatar of the user
        segs: String of seg list, ; as delimiter
        hashcode: 32 bytes String, md5 value of he okr_str
        hasupdate: int 0 or 1
    Return:
        Null

    The function will update the user table, can be called repeatedly.
    """

    if not db or not open_id:
        return

    cursor = db.cursor()

    sql = "replace into %s values('%s','%s','%s','%s','%s','%s','%s','%s',%s,%s,'%s','%s',%s)" % (tbl,
                                                                                                  open_id,
                                                                                                  okr_str,
                                                                                                  name,
                                                                                                  url_id,
                                                                                                  email,
                                                                                                  en_name,
                                                                                                  leader,
                                                                                                  avatar,
                                                                                                  avail_obj,
                                                                                                  obj_nokr,
                                                                                                  segs,
                                                                                                  hashcode,
                                                                                                  hasupdate)

    try:
        cursor.execute(sql)
        db.commit()
    except Exception as e:
        my_error(e)
        # many inert duplicate keys failure is proper here
        db.rollback()

    cursor.close()
    return


def build_key2user_by_key(db, tbl, key, open_id):
    sql = "select seg,open_id_list from %s where seg='%s'" % (tbl, key)
    data = query_tidb_okr(db, sql)

    if not data:  # if empty tuple
        sql = "insert into %s(seg,open_id_list,freq,howchanged) values('%s','%s',1,'%s')" \
              % (tbl, key, open_id, 'add')
        query_tidb_okr(db, sql)
    else:
        old_open_id_str = data[0][1]  # data is tuple, each element is a line, also a tuple
        my_log("Checking if %s is in the seg %s user list before adding " % (open_id, key), level='DEBUG')
        if old_open_id_str.find(open_id) < 0:  # only if the open_id is not in the open_id_str
            new_open_id_str = old_open_id_str + ';' + open_id
            freq = new_open_id_str.count('ou_')
            sql = "update %s set open_id_list='%s',freq=%s,howchanged='update' where seg='%s'" \
                  % (tbl, new_open_id_str, freq, key)
            query_tidb_okr(db, sql)


def update_tidb_key2user_by_key(db, key, open_id, add, obj):
    """
    Argus:
        db: the pymysql connection obj
        key: String, the seg
        open_id: String, one user's open_id
        add: Boolean. If True, the func will add the open_id into the key;otherwise will remove the open_id from the key
        obj: backup
    Return:
        Null
    The function will update the key2users tbl for the entry with ke.
    mysql> desc key2user_schema;
    +---------------------+--------------+------+------+---------+-------+
    | Field               | Type         | Null | Key  | Default | Extra |
    +---------------------+--------------+------+------+---------+-------+
    | seg                 | varchar(128) | NO   | PRI  | NULL    |       |
    | open_id_list        | text         | YES  |      | NULL    |       |
    | freq                | int(11)      | YES  |      | NULL    |       |
    | open_id_list_notify | text         | YES  |      | NULL    |       |
    +---------------------+--------------+------+------+---------+-------+
    4 rows in set (0.11 sec)
    """

    if not db or not key:
        return

    key = key.lower()  # all stored keys to be lowercase
    key = key.replace("'", "")

    cursor = db.cursor()
    sql = "select seg,open_id_list from key2user where seg='%s'" % key
    data = []
    query_tidb_okr(db, sql)

    if not data:  # if empty tuple
        if add:  # trying to add the open_id to the key
            sql = "insert into key2user(seg,open_id_list,freq,howchanged) values('%s','%s',1,'%s')" \
                  % (key, open_id, 'add')
            query_tidb_okr(db, sql)
        else:  # remove
            my_error("Trying to remove a user %s from a unrelated key %s" % (open_id, key))
    else:  # the key exist, so upgrade the content
        update = False
        old_open_id_str = data[0][1]
        if add:  # add the open_id into the key
            my_log("Checking if %s is in the seg %s user list before adding " % (open_id, key), level='DEBUG')
            if old_open_id_str.find(open_id) < 0:  # only if the open_id is not in the open_id_str
                new_open_id_str = old_open_id_str + ';' + open_id
                update = True

        else:  # remove the open_id from the key
            index = old_open_id_str.find(open_id)
            if index < 0:
                my_error("Trying to remove a user %s from a unrelated key %s" % (open_id, key))
            elif old_open_id_str == open_id:  # the old_open_id_str is just open_id
                new_open_id_str = ''
                update = True
            elif index == 0:  # the first one but more than one item
                new_open_id_str = old_open_id_str.replace(open_id + ';', '')
                update = True
            else:
                new_open_id_str = old_open_id_str.replace(';' + open_id, '')
                update = True

        if update:
            freq = new_open_id_str.count('ou_')
            if freq == 0:  # the key not longer has any open_id, so delete the item
                #  we will keep it for a while and delete it later
                sql = "update key2user set open_id_list='',freq=0,howchanged='delete' where seg='%s'" \
                      % key
            else:
                sql = "update key2user set open_id_list='%s',freq=%s,howchanged='update' where seg='%s'" \
                      % (new_open_id_str, freq, key)

            query_tidb_okr(db, sql)

    cursor.close()
    return data


def query_tidb_okr(db, query_str):
    """
    query in a free style
    """

    data = ''

    cursor = db.cursor()
    try:
        cursor.execute(query_str)
        db.commit()
        data = cursor.fetchall()
    except Exception as e:
        my_error(e)
        db.rollback()

    cursor.close()
    my_log("Executed sql %s" % query_str)
    return data


def get_any_col_from_user(db, tbl, col):
    """
    get any col from users table

    The schema of Users table:
    mysql> desc users;
    +---------+-------------+------+------+---------+-------+
    | Field   | Type        | Null | Key  | Default | Extra |
    +---------+-------------+------+------+---------+-------+
    | open_id | varchar(64) | NO   | PRI  | NULL    |       |
    | okr     | text        | YES  |      | NULL    |       |
    | name    | varchar(64) | NO   |      | NULL    |       |
    | url_id  | varchar(64) | YES  |      | NULL    |       |
    | email   | varchar(64) | NO   |      | NULL    |       |
    | en_name | varchar(64) | YES  |      | NULL    |       |
    +---------+-------------+------+------+---------+-------+
    6 rows in set (0.10 sec)
    """

    sql = 'select %s from %s' % (col, tbl)
    return query_tidb_okr(db, sql)


def get_all_open_id_from_user(db, tbl):
    """
    get all open_id from user table
    """
    return get_any_col_from_user(db, tbl, 'open_id')


def clear_howchanged(db, tbl):
    sql = "update %s set howchanged=''" % tbl
    query_tidb_okr(db, sql)


def get_all_changed_keys(db, tbl, howchanged):
    sql = "select seg,howchanged from %s where howchanged='%s'" % (tbl, howchanged)
    return query_tidb_okr(db, sql)


def get_one_from_tbl_by_cols_with_openid(db, tbl, cols, open_id):
    """
    Args:
        cols, tuple contains the cols the caller specified
        open_id, String, must a be column in the <tbl>
    Get one tuple from table by the cols with the specified open_id

    """
    sql = "select %s from %s where open_id='%s'" % (','.join(cols), tbl, open_id)
    return query_tidb_okr(db, sql)


def get_all_from_tbl_by_cols(db, tbl, cols):
    """
    Args:
        cols, tuple contains the cols the caller specified
    Get all tuples from table by the cols

    """
    sql = 'select %s from %s' % (','.join(cols), tbl)
    return query_tidb_okr(db, sql)


def get_okr_str_by_openid(db, open_id):
    """
    get a okr str through a user's open id
    """
    sql = "select okr from users where open_id='%s'" % open_id

    return query_tidb_okr(db, sql)


def get_any_col_from_sbscrb(db, col):
    """
    get any col from sbscrb table

    The schema of Users table:
    mysql> desc sbscrb;
    +--------------+--------------+------+------+---------+-------+
    | Field        | Type         | Null | Key  | Default | Extra |
    +--------------+--------------+------+------+---------+-------+
    | keyword      | varchar(128) | NO   | PRI  | NULL    |       |
    | subscribers  | text         | YES  |      | NULL    |       |
    | open_ids     | text         | YES  |      | NULL    |       |
    | new_open_ids | text         | YES  |      | NULL    |       |
    | subs_date    | date         | YES  |      | NULL    |       |
    +--------------+--------------+------+------+---------+-------+
    5 rows in set (0.10 sec)
    """

    sql = 'select %s from sbscrb' % col
    return query_tidb_okr(db, sql)


def get_all_keyword_from_sbscrb(db):
    return get_any_col_from_sbscrb(db, 'keyword')


def replace_into_msg(db, name, value):
    sql = "replace into okr_server_msg values('%s','%s')" % (name, value)
    query_tidb_okr(db, sql)


def delete_empty_keys(db, tbl):
    sql = "delete from %s where howchanged='%s'" % (tbl, 'delete')  # tbl name does not need ''
    query_tidb_okr(db, sql)


def truncate_tbl(db, tbl):
    sql = 'truncate table %s' % tbl
    query_tidb_okr(db, sql)


def rn_tbl(db, from_tbl, to_tbl):
    sql = 'rename table %s to %s' % (from_tbl, to_tbl)
    query_tidb_okr(db, sql)


def drop_tbl(db, tbl):
    sql = 'drop table %s' % tbl

    cursor = db.cursor()
    try:
        cursor.execute(sql)
        db.commit()
    except Exception as e:  # do not handle the exception
        pass
    cursor.close()
    return


def create_tbl_alike(db, tbl):
    tbl_like = '%s_like9527' % tbl
    drop_tbl(db, tbl_like)  # delete the alike table first
    sql = 'create table %s like %s' % (tbl_like, tbl)
    query_tidb_okr(db, sql)
    return tbl_like
