# OkrExplorer
A small tool to enable horizontal collaboration by easily finding interested OKR within an organization

# What OKR Explorer is?

OKR Explorer help you find your colleagues who share same targets and job interets.

Also it provides managers some overview functions on his/her orgnizations' OKRs, including OKR health level, alignment ratio and leveraging level.

It is based on Feishu OKR and built on [PingCAP TiDB Cloud Dev Tier](https://tidbcloud.com/console/plans), which is free.

# Architecture

![Arch](/images/arch.png)

OkrEx is a Flask Web server. It periodically fetches OKR data, User Data, Departments data from Feishu Server. Please check [Feishu open platform](https://open.feishu.cn/) for the Feishu API usage.

We do not choose Elastic Search as the engines, instead we use a relational database, plus a keyword-to-items reversing index. We choose TiDB Cloud Dev Tier.

For the reversing index, the main idea is segmenting the OKR into key words, and recording the key word and all its mentioner into the table key2user. In this case, we use [jieba](https://github.com/fxsjy/jieba) as the segmentation tool.

Flask OkrEx application server will get requests from OkrEx client, which is embeded into Feishu client, and transfer them into requests to the TiDB Cloud.

# Function

## Searching

Just input the key word you care and see who else in your orgnization is caring the key word too.

## OKR Subscribe

Display what key words you are subscribing and allow you unsubscribe them if you would like to. You can subscribe any key word in searching page by click the "subscribe" button.

## OKR Map

Display the alignment and leveraging level in your organization, including who are not aligned with your objectives and who are leveraged.

## OkrEx Analytics
Show what key words are mostly searched and/or subscribed.

## OoO
Means your targets out of OKR, which is under development.

# Configuration

The project is based on Python 3. All the dependent modules are listed in the requirments.txt

Please install them before you apply the tool. Besides those dependent modules, you need to configure the .env file before starting the tool. The content of the .env is like

APP_ID, the application id assignment by the Feishu open platform

APP_SECRET, for security consideration

FEISHU_HOST, the feishu server URL

STOP_WORDS, the path to stop words text file used by your searching engine

DB_HOSTS, your TiDB Cloud URL, other SQL database should be also ok

DB_USER, the user you access the database

DB_PASSWD, the password you access the database

DB_PORT, the port you access the database

REDIS_PORT, the port the local Redis, by default it is 6379

DATABASE, the database name you would like to connect

SECRET_KEY, used by flask, suggest using a static key to make gunicorn consistent among threads.

RB_CODE, the password to trigger the web server rebuild

URL_BASE, the root part of a OKR display page, usally it is http://xxx.feishu.cn/okr/user/

OKR_EX_SERVER, your OkrEx server address, usally it is like http://ip:port

SBSCRB_CHK_INTERVAL, the interval for OkrEx Server refresh data from Feishu server

SEGS_CHANGED, configure any alphanumeric name, it is used internally

OKREX_APP_URL, the OkrEx application URL within Feishu Client, which is optional

# Launch the server

## Apply a free TiDB Cloud
It is quite easy, you can get instruction from [TiDB Cloud](https://tidbcloud.com/console/plans).

Launch the TiDB Database, create a database named `okr`.

Create the tables, `users`, `key2user`, `departments`, `sbscrb` and `search_rec`. You can check the SQLAlchemy DB model in the app.py file.

## Install and turn on Redis on the server host

## Install Gunicorn

Under OkrExplorer directory, run

`nohup ./okrEx start 4 &`

To make the data periodically update, please run

`nohup python3 opokr.py -i 12 &`

# LICENSE

This project is under [the Apache 2.0 license](https://www.apache.org/licenses/LICENSE-2.0).
