#!/usr/bin/env python

"""
   Twitter support

   Twitter auth workflow:
  - Create a twitter account for the course
    In Settings->Secutiry and Privacy, enable Receive Direct Messages from anyone

  - Create an application ("app") named for your course at https://apps.twitter.com/
    In Settings, use the website URL http://website and Callback URL http://website/_oauth/login (use https, if your website uses it)
  - In Permissions, enable Read, Write and Access direct messages
  - From Keys and Access Tokens, copy your Consumer Key and Consumer Secret to command config file:
       auth_type = 'twitter,consumer_key,consumer_secret'
     or in command line
       sudo python sdserver.py --auth_key=... --auth_type=... --gsheet_url=... --static_dir=... --port=80 --proxy_wait=0 --site_label=

    For live tweeting, also create an Access Token for yourself and use in --twitter_stream=...
    (If you change any app permissions, re-generate the token)

    For local testing:
        Change settings for app at https://apps.twitter.com/ to http://127.0.0.1:8081 and Callback URL http://127.0.0.1:8081/_oauth/login
        Access local server as http://127.0.0.1:8081 (not as localhost)
    
  - Create an initial Slidoc, say ex00-setup.md
  - Ask all users to ex00-setup.html using their Twitter login
  - In Google Docs, copy the first four columns of the ex00-setup sheet to a new roster_slidoc sheet
  - Once the roster_slidoc sheet is created, only users listed in that sheet can login
    Correct any name entries in the sheet, and add emails and/or ID values as needed
  - For additional users, manually add rows to roster_slidoc later
  - If some users need to change their Twitter IDs later, include a dict in twitter.json, {..., "rename": {"old_id": "new_id", ...}}
  - For admin user, include "admin_id": "admin" in rename dict
    
"""

import binascii
import json
import sys
import time
import urllib
import uuid

import tornado.auth
import tornado.httpclient
from tornado.ioloop import IOLoop

TWITTER_USER_STREAM_URL = "https://userstream.twitter.com/1.1"

TWITTER_CONDENSE_KEYS = set(["created_at", "direct_message", "friends", "id", "in_reply_to_status_id", "in_reply_to_screen_name", "in_reply_to_user_id", "name", "screen_name", "sender", "status", "text", "user"])

MAX_MSG_TEXT = 5000                 # Max. text size for all messages

class TwitterStreamReader(object):
    NORMAL_BACKOFF_MINDELAY = 5
    NORMAL_BACKOFF_MAXDELAY = 480

    RATELIMIT_BACKOFF_MINDELAY = 60     # Min. delay time for reconnecting to rate-limited twitter stream
    RATELIMIT_BACKOFF_MAXDELAY = 14400  # Max. delay time for reconnecting to rate-limited twitter stream

    def __init__(self, twitter_config, tweet_callback=None, allow_replies=False):
        # tweet_callback({sender: userid, name: display_name, text: message_text, type:'tweet'/'direct'})
        #
        self.twitter_config = twitter_config
        self.tweet_callback = tweet_callback
        self.allow_replies = allow_replies
        self.tbuffer = ''
        self.http_request = None
        self.http_client = None

        self.opened = False
        self.closed = False
        self.restart_cb = None
        self.restart_delay_time = 0

    def end_stream(self):
        if self.closed:
            return
        self.closed = True

        print >> sys.stderr, 'TwitterStreamReader.end_stream*********END TWITTER USER STREAM'

        if self.http_client:
            self.http_client.shutdown()
            self.http_client = None

        if self.restart_cb:
            IOLoop.current().remove_timeout(self.restart_cb)
            self.restart_cb = None

    def start_stream(self):
        if self.closed:
            return
        self.http_request = twitter_request(self.twitter_config,
                                       "/user", path_prefix=TWITTER_USER_STREAM_URL,
                                       streaming_callback=self.handle_stream,
                                       connect_timeout=60.0,
                                       timeout=0)

        ##print >> sys.stderr, 'TwitterStreamReader.start', self.twitter_config

        self.http_client = tornado.httpclient.AsyncHTTPClient()
        self.http_client.fetch(self.http_request, self.handle_stream_response)

    def handle_stream_response(self, response):
        if self.closed:
            return
        
        self.http_client = None
        self.opened = False

        resp_code = getattr(response, "code", 0)
        rate_limited = (resp_code == 420)
        if hasattr(response, "error"):
            print >> sys.stderr, "TwitterStreamReader.handle_stream_response: ERROR STREAM RESPONSE: code %s - %s" % (resp_code, response.error)
        else:
            print >> sys.stderr, "TwitterStreamReader.handle_stream_response: NORMAL STREAM RESPONSE: code %s" % resp_code

        # Restart stream
        if self.restart_cb:
            return
        if self.restart_delay_time:
            # Double restart delay time (exponential backoff)
            if not rate_limited or self.restart_delay_time < self.NORMAL_BACKOFF_MAXDELAY:
                self.restart_delay_time = min(2*self.restart_delay_time, self.NORMAL_BACKOFF_MAXDELAY)
            else:
                self.restart_delay_time = min(2*self.restart_delay_time, self.RATELIMIT_BACKOFF_MAXDELAY)
        else:
            self.restart_delay_time = self.RATELIMIT_BACKOFF_MINDELAY if rate_limited else self.NORMAL_BACKOFF_MINDELAY
        print >> sys.stderr, "RESTART STREAM AFTER %s SEC" % self.restart_delay_time
        self.restart_cb = IOLoop.current().add_timeout(time.time()+self.restart_delay_time, self.start_stream)

    def handle_stream(self, data):
        self.tbuffer += data
        if "\r\n" not in self.tbuffer:
            # Wait for complete line
            return
        line, sep, self.tbuffer = self.tbuffer.partition("\r\n")
        if not line:
            return

        content = json.loads(line)
        self.tbuffer = ''

        if "friends" in content:
            # List of friends
            if not self.opened:
                # Open connection and reset delay time
                self.opened = True
                self.restart_cb = None
                self.restart_delay_time = 0
                print >> sys.stderr, 'TwitterStreamReader.handle_stream: CONNECTED TO TWITTER STREAM FOR', self.twitter_config['screen_name'], ':', content['friends']
            return

        ##print >> sys.stderr, "TwitterStreamReader.handle_stream:content=%s", str(content)
        try:
            parsed_msg = parse_tweet(content, user_name=self.twitter_config.get('screen_name'))
        except Exception, err:
            import traceback
            traceback.print_exc()
            return

        status = None
        try:
            if parsed_msg and self.tweet_callback:
                status = self.tweet_callback(parsed_msg)
        except Exception, err:
            import traceback
            traceback.print_exc()
            return

        print >> sys.stderr, "TwitterStreamReader.handle_stream:status=", self.allow_replies, repr(status)
        try:
            if self.allow_replies and status and parsed_msg['type'] == 'direct' and parsed_msg['sender'] != self.twitter_config['screen_name']:
                # Send error status via direct message (but not to self)
                twitter_dm(self.twitter_config, status, from_name=self.twitter_config['screen_name'],
                           target_name=parsed_msg['sender'], callback=self.handle_response)
        except Exception, err:
            import traceback
            traceback.print_exc()
            return

    def handle_response(self, response):
        resp_code = getattr(response, "code", 0)
        if hasattr(response, "error"):
            print >> sys.stderr, "TwitterStreamReader.handle_response: ERROR STREAM RESPONSE: code %s - %s" % (resp_code, response.error)
        else:
            print >> sys.stderr, "TwitterStreamReader.handle_response: NORMAL STREAM RESPONSE: code %s" % resp_code


def condense_twitter_content(content):
    if isinstance(content, (list, tuple)):
        return [condense_twitter_content(x) for x in content]

    if isinstance(content, dict):
        return dict([(k, condense_twitter_content(v)) for k, v in content.iteritems() if k in TWITTER_CONDENSE_KEYS])
    
    return content

def parse_tweet(content, user_name=None):
    # Returns {sender: userid, name: display_name, text: message_text, type:'tweet'/'direct'} or None on error
    print >> sys.stderr, "sdstream.parse_tweet: condensed_content = %s" % condense_twitter_content(content)

    sender_info = None
    message_text = None
    message_id = None
    message_type = None

    if "direct_message" in content:
        msg = content["direct_message"]
        sender_info = msg["sender"]
        message_text = msg.get("text", "")
        message_id = msg.get("id", 0)
        to_user_name = msg["recipient"]["screen_name"]
        if to_user_name and user_name is not None:
            if to_user_name != user_name:
                print >> sys.stderr, ":sdstream.parse_tweet: dropped direct message to unknown user: %s, %s" % (to_user_name, user_name)
                return None
        message_type = 'direct'

    elif "text" in content:
        sender_info = content["user"]
        message_text = content.get("text", "")
        message_id = content.get("id", 0)
        to_user_name = content.get("in_reply_to_screen_name")
        if to_user_name and user_name is not None:
            if to_user_name != user_name:
                print >> sys.stderr, ":sdstream.parse_tweet: dropped tweet to unknown user: %s, %s" % (to_user_name, user_name)
                return None
            message_text = message_text.replace('@'+user_name, '')
        message_type = 'tweet'

    elif "friends" in content:
        # List of friends
        friends = content["friends"]
        return None

    else:
        # Unknown content
        return None

    message_text = message_text[:MAX_MSG_TEXT]
    sender_name = sender_info['screen_name']
    display_name = sender_info['name']

    if ',' not in display_name:
        # No commas in display name; re-order as Lastname, Firstname(s)
        comps = display_name.split();
        if len(comps) > 1:
            display_name = comps[-1] + ', ' + (' '.join(comps[:-1]))

    print >> sys.stderr, "sdstream.parse_tweet: %s %s[id=%s]: %s" % (sender_name, display_name, message_id, message_text)
    return {'sender': sender_name,
            'name': display_name,
            'text': message_text,
            'type': message_type}

def oauth_request_parameters(consumer_token, url, access_token, parameters={},
                             method="GET", oauth_version="1.0a",
                             override_version=""):
    base_args = dict(
        oauth_consumer_key=consumer_token["key"],
        oauth_token=access_token["key"],
        oauth_signature_method="HMAC-SHA1",
        oauth_timestamp=str(int(time.time())),
        oauth_nonce=binascii.b2a_hex(uuid.uuid4().bytes),
        oauth_version=override_version or oauth_version,
    )
    args = base_args.copy()
    args.update(parameters)
    if oauth_version == "1.0a":
        signature = tornado.auth._oauth10a_signature(consumer_token, method, url, args, access_token)
    else:
        signature = tornado.auth._oauth_signature(consumer_token, method, url, args, access_token)
    base_args["oauth_signature"] = signature
    return base_args

def twitter_request(twitter_config, path, get_args={}, post_args=None,
                    streaming_callback=None, connect_timeout=20.0, timeout=1200.0,
                    path_prefix="https://api.twitter.com/1.1"):
    app_token = twitter_config['consumer_token']
    access_token = twitter_config.get('access_token')
    url = path_prefix + path + ".json"
    method = "POST" if post_args is not None else "GET"
    query_args = get_args.copy()
    if access_token:
        all_args = get_args.copy()
        all_args.update(post_args or {})
        consumer_token = dict(key=app_token["consumer_key"], secret=app_token["consumer_secret"])
        oauth = oauth_request_parameters(consumer_token, url, access_token, all_args, method=method)
        query_args.update(oauth)

    if query_args: url += "?" + urllib.urlencode(query_args)
    post_data = urllib.urlencode(post_args) if post_args is not None else None
    headers = {"Connection": "keep-alive"} if streaming_callback else None
    http_request = tornado.httpclient.HTTPRequest(str(url), method,
                                                  body=post_data,
                                                  headers=headers,
                                                  user_agent='UserStream',
                                                  connect_timeout=connect_timeout,
                                                  request_timeout=timeout,
                                                  streaming_callback=streaming_callback)
    return http_request

def twitter_task(twitter_config, action, target_name="", text="", callback=None):
    get_args = {}
    post_args = None
    if action == "friends":
        path = "/friends/ids"
    elif action == "followers":
        path = "/followers/ids"
    elif action == "follow":
        path = "/friendships/create"
        post_args = {"screen_name": target_name}
    elif action == "unfollow":
        path = "/friendships/destroy"
        post_args = {"screen_name": target_name}
    elif action == "direct":
        path = "/direct_messages/new"
        post_args = {"screen_name": target_name, "text": text}
    else:
        raise Exception("Invalid twitter action: "+action)

    http_request = twitter_request(twitter_config,
                                   path, 
                                   get_args=get_args,
                                   post_args=post_args,
                                   connect_timeout=60.0,
                                   timeout=0)
    http_client = tornado.httpclient.AsyncHTTPClient()
    http_client.fetch(http_request, callback)

def twitter_dm(twitter_config, text, from_name='', target_name='', callback=None):
    twitter_task(twitter_config, "direct", target_name=target_name, text=text, callback=callback)

def printTwitterMessage(fromUser, fromName, message):
    print >> sys.stderr, 'sdproxy.printTwitterMessage:', fromUser, fromName, message


if __name__ == "__main__":
    from tornado.options import define, options, parse_config_file, parse_command_line

    define("config", type=str, help="Path to config file",
        callback=lambda path: parse_config_file(path, final=False))

    define("dm", default=False, help="Send direct message")
    define("twitter_stream", default="", help="Twitter stream access info: username,consumer_key,consumer_secret,access_key,access_secret")
    args = parse_command_line()

    if options.twitter_stream:
        comps = options.twitter_stream.split(',')
        twitter_config = {
            'screen_name': comps[0],
            'consumer_token': {'consumer_key': comps[1], 'consumer_secret': comps[2]},
            'access_token': {'key': comps[3], 'secret': comps[4]}
            }


    if options.dm and len(args) > 2 and args[0] == 'd':
        # Direct message
        def dm_callback(response):
            print 'dm_callback', response
            IOLoop.current().stop()
        twitter_dm(twitter_config, ' '.join(args[2:]), from_name=twitter_config['screen_name'], target_name=args[1], callback=dm_callback)
    else:
        twitterStream = TwitterStreamReader(twitter_config, printTwitterMessage)
        twitterStream.start_stream()

    def test_twitter_dm():
        def test_callback(response):
            print "test_dm_callback", response
        print "test_twitter_dm"
        twitter_dm(twitter_config, "Send DM4back", from_name="geos210", target_name="atmo321e", callback=test_callback)

    def test_twitter_request():
        ##create_master_user_stream()
        def test_callback(response):
            print "test_callback", response
            print "test_callback", response.body
        #print "test_twitter_request", twitter_config
        #twitter_task(twitter_config, "followers", callback=test_callback)
        #twitter_task(twitter_config, "friends", callback=test_callback)
        #twitter_task(twitter_config, "follow", target_name="atmo201", callback=test_callback)
        #twitter_task(twitter_config, "direct", target_name="meldr101", text="Send DM2", callback=test_callback)

    #IOLoop.current().add_callback(test_twitter_request)
    #IOLoop.current().add_callback(test_twitter_dm)
        
    IOLoop.current().start()


