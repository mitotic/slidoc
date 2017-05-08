#!/usr/bin/env python

'''
Slidoc authentication utilities

'''

from __future__ import print_function

import base64
import datetime
import hashlib
import hmac
import json
import sys
import time
import urllib
import urllib2

TRUNCATE_DIGEST = 8

DIGEST_ALGORITHM = hashlib.md5

def digest_hex(s, n=TRUNCATE_DIGEST):
    return DIGEST_ALGORITHM(s).hexdigest()[:n]

def gen_hmac_token(key, message):
    token = base64.b64encode(hmac.new(key, message, DIGEST_ALGORITHM).digest())
    return token[:TRUNCATE_DIGEST]

def gen_auth_prefix(user_id, role, sites):
    return ':%s:%s:%s' % (user_id, role, sites)

def gen_auth_token(key, user_id, role='', sites='', prefixed=False):
    prefix = gen_auth_prefix(user_id, role, sites)
    token = gen_hmac_token(key, prefix)
    return prefix+':'+token if prefixed else token

def gen_site_key(key, site):
    return gen_hmac_token(key, 'site:'+site)

def gen_site_auth_token(site, key, user_id, role='', prefixed=False):
    return gen_auth_token(gen_site_key(key, site), user_id, role=role, prefixed=prefixed)

def gen_late_token(key, user_id, site_name, session_name, date_str):
    # Use date string of the form '1995-12-17T03:24'
    token = date_str+':'+gen_hmac_token(key, 'late:%s:%s:%s:%s' % (user_id, site_name, session_name, date_str) )
    return token

def str_encode(value, errors='strict'):
    return value.encode('utf-8', errors) if isinstance(value, unicode) else value

def safe_quote(value):
    return urllib.quote(str_encode(value), safe='')

def safe_unquote(value):
    return urllib.unquote(value)

def get_utc_date(date_time_str):
    """Convert local date string of the form yyyy-mm-ddThh:mm to UTC (unless it already ends with 'Z')"""
    if date_time_str and not date_time_str.endswith('Z'):
        try:
            date_time_str = datetime.datetime.utcfromtimestamp(time.mktime(time.strptime(date_time_str, "%Y-%m-%dT%H:%M"))).strftime("%Y-%m-%dT%H:%M") + 'Z'
        except Exception, excp:
            raise Exception("Error in parsing date '%s'; expect local time to be formatted like 2016-05-04T11:59 (%s)" % (date_time_str, excp))

    return date_time_str

def parse_date(date_time_str):
    """Parse ISO format date, with or without Z suffix denoting UTC, to return datetime object (containing local time)
       Return None on error
    """
    if date_time_str.endswith('Z'):
        # UTC time step (add local time offset)
        offset_sec = time.mktime(datetime.datetime.now().timetuple()) - time.mktime(datetime.datetime.utcnow().timetuple())
        date_time_str = date_time_str[:-1]
    else:
        offset_sec = 0

    if len(date_time_str) == 16:
        # yyyy-mm-ddThh:mm
        format = "%Y-%m-%dT%H:%M"
    elif len(date_time_str) == 19:
        # yyyy-mm-ddThh:mm:ss
        format = "%Y-%m-%dT%H:%M:%S"
    else:
        format = "%Y-%m-%dT%H:%M:%S.%f"

    try:
        return datetime.datetime.fromtimestamp(time.mktime(time.strptime(date_time_str, format)) + offset_sec)
    except Exception:
        return None

def create_date(epoch_ms=None):
    """Create datetime object from epoch milliseconds (i.e., milliseconds since Jan. 1, 1970)"""
    return datetime.datetime.now() if epoch_ms is None else datetime.datetime.fromtimestamp(epoch_ms/1000)

def epoch_ms(date_time=None):
    """Return epoch milliseconds (i.e., milliseconds since Jan. 1, 1970) for datetime object"""
    if date_time:
        return time.mktime(date_time.timetuple())*1000.0 + date_time.microsecond/1000.0
    else:
        return epoch_ms(datetime.datetime.now())

def iso_date(date_time=None, utc=False, nosec=False, nosubsec=False):
    """Return ISO date time string YYYY-MM-DDThh:mm:ss for local time (or UTC time)"""
    if not date_time:
        date_time = datetime.datetime.now()
    if utc:
        retval = datetime.datetime.utcfromtimestamp(epoch_ms(date_time)/1000.0).isoformat() + 'Z'
    else:
        retval = date_time.isoformat()

    return retval[:16] if nosec else (retval[:19] if nosubsec else retval)

def json_default(obj):
    if isinstance(obj, datetime.datetime):
        return iso_date(obj, utc=True)
    raise TypeError("%s not serializable" % type(obj))

def http_post(url, params_dict=None):
    req = urllib2.Request(url, urllib.urlencode(params_dict)) if params_dict else urllib2.Request(url)
    try:
        response = urllib2.urlopen(req)
    except Exception, excp:
        raise Exception('ERROR in accessing URL %s: %s' % (url, excp))
    result = response.read()
    try:
        result = json.loads(result)
    except Exception, excp:
        result = {'result': 'error', 'error': 'Error in http_post: result='+str(result)+': '+str(excp)}
    return result

def read_settings(sheet_url, hmac_key, settings_sheet, site=''):
    auth_key = gen_site_key(hmac_key, site) if site else hmac_key
    user_token = gen_auth_token(auth_key, 'admin', 'admin', prefixed=True)
    get_params = {'sheet': settings_sheet, 'get': '1', 'all': '1', 'getheaders': '1', 'admin': 'admin', 'token': user_token}
    retval = http_post(sheet_url, get_params)
    if retval['result'] != 'success':
        raise Exception("Error in accessing %s %s: %s" % (site, settings_sheet, retval['error']))
    rows = retval.get('value')
    if not rows:
        raise Exception("Error: Empty sheet %s %s" % (site, settings_sheet))
    return get_settings(rows)

def get_settings(rows):
    settings = {}
    for row in rows:
        if not row or not row[0].strip():
            continue
        name = row[0].strip()
        value = ''
        if len(row) > 1:
            if type(row[1]) in (str, unicode):
                value = row[1].strip()
            elif row[1]:                   # None, False, or 0 become null string
                row[1] = str(row[1])
        settings[name] = value
    return settings

if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Generate slidoc HMAC authentication tokens')
    parser.add_argument('-a', '--auth_key', help='Digest authentication key (required)')
    parser.add_argument('-r', '--role', help='Role admin/grader')
    parser.add_argument('-s', '--session', help='Session name')
    parser.add_argument('-t', '--site', help='Site name')
    parser.add_argument('--due_date', metavar='DATE_TIME', help="Due date yyyy-mm-ddThh:mm local time (append ':00.000Z' for UTC)")
    parser.add_argument('user', help='user name(s)', nargs=argparse.ZERO_OR_MORE)
    cmd_args = parser.parse_args()

    if not cmd_args.auth_key:
        sys.exit('Must specify digest authentication key')

    auth_key = cmd_args.auth_key
    if cmd_args.site:
        auth_key = gen_site_key(auth_key, cmd_args.site)

    if not cmd_args.user:
        print((cmd_args.site or '')+' auth key =', auth_key)

    for user in cmd_args.user:
        if cmd_args.due_date:
            token = gen_late_token(auth_key, user, cmd_args.site or '', cmd_args.session, get_utc_date(cmd_args.due_date))
        else:
            token = gen_auth_token(auth_key, user, cmd_args.role or '', prefixed=cmd_args.role)
        print(user+' token =',  token)
