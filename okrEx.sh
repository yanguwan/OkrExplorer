#!/bin/sh
if test $# -le 0
then
        echo "Starting gunicorn my_app on 172.16.5.127:3000"
        gunicorn -w 1 -b 172.16.5.127:3000 -t 300  app:my_app
else
        if test $1 = "start"
        then
                echo "Starting gunicorn my_app on 172.16.5.127:3000"
                gunicorn -w $2 -b 172.16.5.127:3000 -t 300 app:my_app
        fi
        if test $1 = "stop"
        then
                echo "Shutting down gunicorn my_app on 172.16.5.127:3000"
                ps aux |grep gunicorn |grep my_app | awk '{ print $2 }' | xargs kill -9
        fi
        if test $1 = "restart"
        then
                echo "Restarting gunicorn my_app on 172.16.127:3000"
                ps aux |grep gunicorn |grep my_app | awk '{ print $2 }' | xargs kill -9
                gunicorn -w $2 -b 172.16.5.127:3000 -t 300  app:my_app
        fi
fi
