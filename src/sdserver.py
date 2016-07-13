#!/usr/bin/env python

# sdserver: Tornado-based web server to serve slidoc html files (with authentication)

import os.path
import sys

import tornado.escape
import tornado.httpserver
import tornado.ioloop
import tornado.options
import tornado.web

from tornado.options import define, options

import sliauth

USER_COOKIE_SECURE = "slidoc_user_secure"
SERVER_COOKIE = "slidoc_server"

class BaseHandler(tornado.web.RequestHandler):
    def get_current_user(self):
        if not options.hmac_key:
            self.clear_cookie(USER_COOKIE_SECURE)
            self.clear_cookie(SERVER_COOKIE)
            return "noauth"
        user_id = self.get_secure_cookie(USER_COOKIE_SECURE)
        return user_id or None


class HomeHandler(BaseHandler):
    @tornado.web.authenticated 
    def get(self):
        self.redirect("/index.html")


class AuthStaticFileHandler(tornado.web.StaticFileHandler): 
    def get_current_user(self):
        if not options.hmac_key:
            self.clear_cookie(USER_COOKIE_SECURE)
            self.clear_cookie(SERVER_COOKIE)
            return "noauth"
        user_id = self.get_secure_cookie(USER_COOKIE_SECURE)
        return user_id or None

    @tornado.web.authenticated 
    def get(self, path): 
        tornado.web.StaticFileHandler.get(self, path)


class AuthLoginHandler(BaseHandler):
    def get(self):
        error_msg = self.get_argument("error", "")
        username = self.get_argument("username", "")
        token = self.get_argument("token", "")
        next = self.get_argument("next", "/")
        if not error_msg and username and token:
            self.login(username, token, next=next)
        else:
            self.render("login.html", error_msg=error_msg, next=next, site_label=options.site_label)

    def post(self):
        self.login(self.get_argument("username", ""), self.get_argument("token", ""), next=self.get_argument("next", "/"))

    def check_access(self, username, token):
        if username == "admin":
            return token == options.hmac_key
        else:
            return token == sliauth.gen_user_token(options.hmac_key, username)

    def login(self, username, token, next="/"):
        auth = self.check_access(username, token)
        if auth:
            self.set_secure_cookie(USER_COOKIE_SECURE, tornado.escape.json_encode(username))
            self.set_cookie(SERVER_COOKIE, username+":"+token)
            self.redirect(next)
        else:
            error_msg = "?error=" + tornado.escape.url_escape("Incorrect username or token")
            self.redirect("/_auth/login/" + error_msg)

            
class AuthLogoutHandler(BaseHandler):
    def get(self):
        self.clear_cookie(USER_COOKIE_SECURE)
        self.clear_cookie(SERVER_COOKIE)
        self.write('Logged out.<p></p><a href="/">Home</a>')


class Application(tornado.web.Application):
    def __init__(self):
        handlers = [
            (r"/", HomeHandler),
            (r"/_auth/login/", AuthLoginHandler),
            (r"/_auth/logout/", AuthLogoutHandler),
            (r"/(.+)", AuthStaticFileHandler, {"path": options.static})
        ]
        settings = dict(
            template_path=os.path.join(os.path.dirname(__file__), "server_templates"),
            xsrf_cookies=True,
            cookie_secret=options.hmac_key,
            login_url="/_auth/login/",
            debug=options.debug,
        )
        super(Application, self).__init__(handlers, **settings)


def main():
    define("port", default=8888, help="Web server port", type=int)
    define("site_label", default="Slidoc", help="Site label")
    define("static", default="static", help="Path to static files directory")
    define("hmac_key", default="", help="HMAC key for admin user")
    define("debug", default=False, help="Debug mode")
    tornado.options.parse_command_line()
    http_server = tornado.httpserver.HTTPServer(Application())
    http_server.listen(options.port)
    print >> sys.stderr, "Listening on port", options.port
    tornado.ioloop.IOLoop.current().start()


if __name__ == "__main__":
    main()
