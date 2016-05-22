#!/usr/bin/env python

'''
Slidoc authentication utilities

'''

from __future__ import print_function

import base64
import datetime
import hashlib
import hmac
import time

TRUNCATE_DIGEST = 8

def gen_hmac_token(key, message):
    token = base64.b64encode(hmac.new(key, message, hashlib.md5).digest())
    return token[:TRUNCATE_DIGEST]

def gen_user_token(key, user_id):
    return gen_hmac_token(key, 'id:'+user_id)

def gen_admin_token(key, admin_user_id):
    return gen_hmac_token(key, 'admin:'+admin_user_id)

def gen_late_token(key, user_id, session_name, date_str):
    # Use date string of the form '1995-12-17T03:24'
    token = date_str+':'+gen_hmac_token(key, 'late:%s:%s:%s' % (user_id, session_name, date_str) )
    return token

def get_utc_date(date_time):
    """Convert local date of the form yyyy-mm-ddThh:mm to UTC (unless it ends with 'Z')"""
    if date_time and not date_time.endswith('Z'):
        try:
            date_time = datetime.datetime.utcfromtimestamp(time.mktime(time.strptime(date_time, "%Y-%m-%dT%H:%M"))).strftime("%Y-%m-%dT%H:%M") + 'Z'
        except Exception, excp:
            raise Exception("Error in parsing date '%s'; expect local time to be formatted like 2016-05-04T11:59 (%s)" % (date_time, excp))

    return date_time

if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Generate slidoc HMAC authentication tokens')
    parser.add_argument('-k', '--key', help='HMAC key (required)')
    parser.add_argument('-s', '--session', help='Session name')
    parser.add_argument('--due_date', metavar='DATE_TIME', help="Due date yyyy-mm-ddThh:mm local time (append ':00.000Z' for UTC)")
    parser.add_argument('user', help='user name(s)', nargs=argparse.ONE_OR_MORE)
    cmd_args = parser.parse_args()

    if not cmd_args.key:
        sys.exit('Must specify HMAC key')

    for user in cmd_args.user:
        if cmd_args.due_date:
            token = gen_late_token(cmd_args.key, user, cmd_args.session, get_utc_date(cmd_args.due_date))
        else:
            token = gen_user_token(cmd_args.key, user)
        print(user+':',  token)
