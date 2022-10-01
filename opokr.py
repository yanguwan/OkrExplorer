# -*- coding: utf-8 -*-
import get_data_from_feishu
import talk2Tidb
import time
import sys
import getopt
import os
import my_utils
from dotenv import load_dotenv, find_dotenv
import requests
import json
import okr_url_id
import my_seg
import hashlib

# get environmental parameter from .env files
load_dotenv(find_dotenv())
RB_CODE = os.getenv("RB_CODE")
OKR_EX_SERVER = os.getenv("OKR_EX_SERVER")
SBSCRB_CHK_INTERVAL = os.getenv("SBSCRB_CHK_INTERVAL")  # str type, in hours
SEGS_CHANGED = os.getenv("SEGS_CHANGED")

interval = int(SBSCRB_CHK_INTERVAL)  # the subscribe key table checking interval in hours


def cal_avail_okr_count_by_dep(db, dep_id):
    """
    Return the count of avail okr in the department dep_id
    Available means a guy who has more than one objective is set.
    """
    user_list = get_data_from_feishu.get_all_users_in_dep(dep_id)

    my_utils.my_log('user number is %s' % len(user_list), level='DEBUG')

    avail = 0

    not_health_user_id_list = []

    cols = ('open_id', 'avail_obj', 'obj_nokr')

    for user in user_list:
        tup = talk2Tidb.get_one_from_tbl_by_cols_with_openid(db, 'users', cols, user)
        if not tup or not tup[0]:
            my_utils.my_error('empty tup,user is %s, depart is %s' % (user, dep_id))
            continue
        objs = int(tup[0][1])
        no_kr = int(tup[0][2])
        if objs > 0 and no_kr <= 0:  # objs = 0 or no_kr >0 are unhealthy
            avail += 1
        else:
            not_health_user_id_list.append(user)
    return avail, not_health_user_id_list


def build_departments_tbl():
    """
      desc departments;
    +-----------------+-------------+------+------+---------+-------+
    | Field           | Type        | Null | Key  | Default | Extra |
    +-----------------+-------------+------+------+---------+-------+
    | open_dep_id     | varchar(64) | NO   | PRI  | NULL    |       |
    | name            | varchar(64) | NO   |      | NULL    |       |
    | leader          | varchar(64) | YES  |      | NULL    |       |
    | dep_level       | int(2)      | YES  |      | NULL    |       |
    | member_count    | int(8)      | YES  |      | NULL    |       |
    | avail_okr_count | int(8)      | YES  |      | NULL    |       |
    | parent_dep_id   | varchar(64) | YES  |      | NULL    |       |
    +-----------------+-------------+------+------+---------+-------+
    7 rows in set (0.26 sec)

    build up the departments from empty
    """
    db = talk2Tidb.connect_tidb_okr()

    tbl_name = 'departments'

    cols_name = 'open_dep_id, name, leader, dep_level,member_count,avail_okr_count,not_health_user, parent_dep_id'

    tbl_alike = talk2Tidb.create_tbl_alike(db, tbl_name)

    first_level_dep = get_data_from_feishu.get_all_direct_child_departs("0")

    for fld in first_level_dep:
        if 'leader_user_id' in fld.keys():  # exclude those virtual departments
            avail_okr_count, not_health_user_id_list = cal_avail_okr_count_by_dep(db, fld['open_department_id'])
            sql = "insert into %s (%s) values('%s','%s','%s',1,%s,%s,'%s','%s')" \
                  % (tbl_alike, cols_name, fld['open_department_id'],
                     fld['name'], fld['leader_user_id'], fld['member_count'], avail_okr_count,
                     ';'.join(not_health_user_id_list),
                     fld['parent_department_id'])
            talk2Tidb.query_tidb_okr(db, sql)

    second_level_departments = get_data_from_feishu.get_all_second_level_departs()

    for dep in second_level_departments:
        if 'leader_user_id' in dep.keys():
            avail_okr_count, not_health_user_id_list = cal_avail_okr_count_by_dep(db, dep['open_department_id'])
            sql = "insert into %s (%s) values('%s','%s','%s',2,%s,%s,'%s','%s')" \
                  % (tbl_alike, cols_name, dep['open_department_id'],
                     dep['name'], dep['leader_user_id'], dep['member_count'], avail_okr_count,
                     ';'.join(not_health_user_id_list),
                     dep['parent_department_id'])
            talk2Tidb.query_tidb_okr(db, sql)
    talk2Tidb.drop_tbl(db, tbl_name)
    talk2Tidb.rn_tbl(db, tbl_alike, tbl_name)
    talk2Tidb.close_tidb_okr(db)


def _get_item(p, t):
    for i in t:
        if p == i[0]:
            return i
        else:
            continue
    return ()


def update_key2user_tbl_with_users_change(db, users_alike, key2user_alike=''):
    """
    Args:
        db, the connector
        users_alike, the temporary new users table.
    The function will update (including create a new) key2user table according to
    the changes the new users table on the old users table.

    The Algorithm to update the key2user

    1) In users table, each user need keep the segs information. f(okr)=> set(segs)
    2) There are two cases:
        Case 1: The user is deleted, so his/her OKR is also delete. f(-okr)==>set(segs-)
                That is all the segs recorded in the user.
        Case 2:The user's OKR changed. so f(delta(okr))==> set(segs+), set(segs-)
                Here set(segs+) means newly introduced seg in the changed okr.
                set(segs-) means the segs disappeared in the chagned okr.
        Both set(segs+) and set(segs-) need 1)
        set(segs+) = set(new segs)-set(old segs)
        set(segs-) = set(old segs)- set(new segs)

    3) For each of set(segs+), we insert new entry into key2user table if there is no, or
        add open_id and freq if the entry is already there.
       For each of set(segs-), we remove open_id from the seg's open_id list.
       If the open_id list is empty, we need delete the entry from the table.

       The process should be atomic. Should use a tmeproary file to keep set(segs+) and set(segs-)
        until 3) is finished
    """

    cols = ('open_id', 'name', 'segs', 'hashcode')
    tup_new = talk2Tidb.get_all_from_tbl_by_cols(db, users_alike, cols)
    tup_new_id_list = [t[0] for t in tup_new]
    if key2user_alike:
        tup_old_id_list = []
    else:  # if key2user_alike is '' means it is soft way, compare to existing users table
        tup_old = talk2Tidb.get_all_from_tbl_by_cols(db, 'users', cols)
        tup_old_id_list = [t[0] for t in tup_old]
        # clear the howhanged value in key2user table in the soft mode
        talk2Tidb.clear_howchanged(db, 'key2user')

    users_id_disappeared = set(tup_old_id_list) - set(tup_new_id_list)
    my_utils.my_log('user disappear', level='DEBUG')
    my_utils.my_log(users_id_disappeared)
    users_id_new = set(tup_new_id_list) - set(tup_old_id_list)
    users_id_may_changed = set(tup_old_id_list) & set(tup_new_id_list)
    my_utils.my_log('user may changed', level='DEBUG')
    my_utils.my_log(users_id_may_changed, level='DEBUG')

    for user_id in users_id_disappeared:
        user = _get_item(user_id, tup_old)
        my_utils.my_log('user %s disappeared' % user[1], level='DEBUG')
        for seg in user[2].split(';'):
            if seg:
                # handle the seg as remove
                talk2Tidb.update_tidb_key2user_by_key(db=db,
                                                      key=seg,
                                                      open_id=user[0],
                                                      add=False,
                                                      obj=False)
    for user_id in users_id_new:
        user = _get_item(user_id, tup_new)
        my_utils.my_log('user %s added' % user[1], level='DEBUG')
        for seg in user[2].split(';'):
            if seg:
                if key2user_alike:
                    talk2Tidb.build_key2user_by_key(db=db,
                                                    tbl=key2user_alike,
                                                    key=seg,
                                                    open_id=user[0])
                else:
                    # handle the seg as new add
                    talk2Tidb.update_tidb_key2user_by_key(db=db,
                                                          key=seg,
                                                          open_id=user[0],
                                                          add=True,
                                                          obj=False)
    # handle the change ones by the hashcode
    for user_id in users_id_may_changed:
        user_old = _get_item(user_id, tup_old)
        user_new = _get_item(user_id, tup_new)
        if user_old[3] != user_new[3]:  # hashcode are different, content changed
            my_utils.my_log('there are change for user %s' % user_id, level='DEBUG')
            new_seg_list = list(set(user_new[2].split(';')) - set(user_old[2].split(';')))
            for seg in new_seg_list:
                if seg:
                    talk2Tidb.update_tidb_key2user_by_key(db=db,
                                                          key=seg,
                                                          open_id=user_id,
                                                          add=True,
                                                          obj=False)

            disappeared_set_list = list(set(user_old[2].split(';')) - set(user_new[2].split(';')))
            for seg in disappeared_set_list:
                if seg:
                    talk2Tidb.update_tidb_key2user_by_key(db=db,
                                                          key=seg,
                                                          open_id=user_id,
                                                          add=False,
                                                          obj=False)


def update_okr_server_msg_tbl(db):
    """
    Usually after key2user is updated, we need to summarize what keys are changed.
    Restore them into the msg table for use in the future, like subscribe notify
    """
    seg_list = []
    tup = talk2Tidb.get_all_changed_keys(db, 'key2user', 'add')
    seg_list.extend([t[0] for t in tup])
    tup = talk2Tidb.get_all_changed_keys(db, 'key2user', 'update')
    seg_list.extend([t[0] for t in tup])
    tup = talk2Tidb.get_all_changed_keys(db, 'key2user', 'delete')
    seg_list.extend([t[0] for t in tup])

    talk2Tidb.replace_into_msg(db, SEGS_CHANGED, ';'.join(seg_list))

    talk2Tidb.delete_empty_keys(db, 'key2user')
    # add and update status also should be clear here or clear just before each peridic update round
    # clear


def update_user_tbl_from_feishu(mode):
    """
    update the users table through source of Feishu

    The schema of users tbl:
    mysql> desc users;
    +-----------+--------------+------+------+---------+-------+
    | Field     | Type         | Null | Key  | Default | Extra |
    +-----------+--------------+------+------+---------+-------+
    | open_id   | varchar(64)  | NO   | PRI  | NULL    |       |
    | okr       | text         | YES  |      | NULL    |       |
    | name      | varchar(64)  | NO   |      | NULL    |       |
    | url_id    | varchar(64)  | YES  |      | NULL    |       |
    | email     | varchar(64)  | NO   |      | NULL    |       |
    | en_name   | varchar(64)  | YES  |      | NULL    |       |
    | leader    | varchar(64)  | YES  |      | NULL    |       |
    | avatar    | varchar(256) | YES  |      | NULL    |       |
    | segs      | text         | YES  |      | NULL    |       |
    | hashcode  | varchar(32)  | YES  |      | NULL    |       |
    | hasupdate | tinyint(1)   | YES  |      | NULL    |       |
    +-----------+--------------+------+------+---------+-------+
    11 rows in set (0.10 sec)

    Notice:
    The function can be called repeatedly

    """
    user_list = get_data_from_feishu.get_all_user_dict_from_feishu()

    db = talk2Tidb.connect_tidb_okr()

    users_alike = talk2Tidb.create_tbl_alike(db, 'users')
    if mode == 'hard':
        key2user_alike = talk2Tidb.create_tbl_alike(db, 'key2user')

    for user in user_list:
        open_id = user['open_id']
        name = user['name']
        en_name = user['en_name']
        email = user['email']  # it depends on how many privileges you got through feishu
        avatar = user['avatar']['avatar_72']

        try:
            leader = user['leader_user_id']
        except KeyError:
            leader = ''  # the top manager has no the key and contractor has no the key

        url_id = okr_url_id.get_okr_url_id(email)
        time.sleep(1)  # sleep 2 to give time

        if not url_id or not url_id.isdigit():
            my_utils.my_log('url_id is %s for user %s' % (url_id, name), level='DEBUG')

        okr_dict = get_data_from_feishu.get_latest_okr_by_open_id(open_id)

        avail_obj, obj_nokr = my_utils.cal_avail_obj_by_okr_dict(okr_dict)

        okr_str = json.dumps(okr_dict, ensure_ascii=False)  # in case of the Chinese mess

        okr_content, nil, nil = my_utils.get_okrcontent_from_okr_str(okr_str)

        okr_str = okr_str.replace('\\', '\\\\')  # mysql will eat \, need change it to be \\

        okr_str = okr_str.replace("'", "\\'")  # okr_str cannot have ', will affect sql insert, change it to be \'

        seg_list = my_seg.my_seg(okr_content)

        hashcode = hashlib.md5(okr_content.encode('utf-8')).hexdigest()

        talk2Tidb.replace_user_entry(db=db,
                                     tbl=users_alike,
                                     open_id=open_id,
                                     okr_str=okr_str,
                                     name=name,
                                     url_id=url_id,
                                     email=email,
                                     en_name=en_name,
                                     leader=leader,
                                     avatar=avatar,
                                     avail_obj=avail_obj,
                                     obj_nokr=obj_nokr,
                                     segs=';'.join(seg_list),
                                     hashcode=hashcode,
                                     hasupdate=0)
    # Finished writing new table

    # start comparing the new users tbl and old one to decide which user is updated
    if mode == 'hard':
        update_key2user_tbl_with_users_change(db, users_alike, key2user_alike)
    else:
        update_key2user_tbl_with_users_change(db, users_alike)
    talk2Tidb.drop_tbl(db, 'users')
    talk2Tidb.rn_tbl(db, users_alike, 'users')
    if mode == 'hard':
        talk2Tidb.drop_tbl(db, 'key2user')
        talk2Tidb.rn_tbl(db, key2user_alike, 'key2user')
    update_okr_server_msg_tbl(db)
    talk2Tidb.close_tidb_okr(db)


def okrEx_refresh_cycle():
    # Developement logcally
    # OKR_EX_SERVER = 'http://127.0.0.1:3000/'
    url = OKR_EX_SERVER + 'rebuild?rb=' + RB_CODE

    payload = ''

    response = requests.request("GET", url, data=payload, timeout=1200)

    data = json.loads(response.text)

    return data


def rebuild_base(mode='soft'):
    t1 = time.time()
    update_user_tbl_from_feishu(mode)
    t2 = time.time()
    elasped = (t2 - t1) * 1000000
    my_utils.my_log('Finished users table and key2user update, used %.3f seconds' % elasped, level='DEBUG')
    t1 = time.time()
    build_departments_tbl()
    t2 = time.time()
    elasped = (t2 - t1) * 1000000
    my_utils.my_log('Finished departments table update, used %.3f seconds' % elasped, level='DEBUG')
    # tell okrEx Server to update the local redis user table
    t1 = time.time()
    data = okrEx_refresh_cycle()
    t2 = time.time()
    elasped = (t2 - t1) * 1000000
    my_utils.my_log('Got feedback from okr server for internal update, used %.3f seconds' % elasped, level='DEBUG')
    # my_utils.my_log('Message is %s' % data['message'], level='DEBUG')


def house_keep():
    """
    The function is responsible for:
    - Check if it is time to update sbscrb table(every interval days)
    - update
    - Check if it is the date to rebuild the users tbl and key2user tbl
      Every begining day of each quarter

    """
    a = 0
    n = 0
    rebuild_base()
    n += 1
    my_utils.my_log("Finished No %s times rebuild" % n, level='DEBUG')
    rebuild_time = time.time()
    while True:
        now_time = time.time()
        if now_time - rebuild_time > 3600 * interval:
            rebuild_base()
            n += 1
            my_utils.my_log("Finished No %s times rebuild" % n, level='DEBUG')
            rebuild_time = time.time()
        else:
            time.sleep(10)
            a += 1


def main(argv):
    try:
        opts, args = getopt.getopt(argv, "hri:", ["interval="])
    except getopt.GetoptError:
        print('opokr.py -r -i <interval>')
        sys.exit(2)

    for opt, arg in opts:
        if opt == '-h':
            print('opokr.py -r -i <interval>')
            sys.exit()
        elif opt == '-r':
            print('rebuilding the bases in hard mode')
            rebuild_base('hard')
            sys.exit()
        elif opt in ("-i", "--interval"):
            interval_str = arg
            try:
                global interval
                interval = int(interval_str)
            except ValueError:
                print('only integer is allowed after -i')
                sys.exit(2)
            print('Periodic checking interval is set to %s hours' % interval)

    house_keep()


if __name__ == "__main__":
    my_utils.init_log('opokr.log', level='DEBUG')
    main(sys.argv[1:])
