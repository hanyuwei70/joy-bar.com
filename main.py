# -*- coding: utf-8 -*-

import os, sqlite3, datetime, json
from functools import wraps
from db_sqlite3 import DataSource as ds, RoomConflict
from flask import Flask, request, g, abort, jsonify, url_for, redirect, session, current_app
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from blinker import Namespace

my_signals = Namespace()
sig_user_logged_in = my_signals.signal("user_logger_in")


class ReverseProxied(object):
    def __init__(self, app):
        self.app = app

    def __call__(self, environ, start_response):
        scheme = environ.get('HTTP_X_FORWARDED_PROTO')
        if scheme:
            environ['wsgi.url_scheme'] = scheme
        return self.app(environ, start_response)


app = Flask(__name__)
app.wsgi_app = ReverseProxied(app.wsgi_app)
app.config.from_object(__name__)
app.config.update(dict(
    DATABASE=os.path.join(app.root_path, 'data.sqlite3'),
    SECRET_KEY='development'
))
if os.environ.get('GAMEWEB_SETTINGS') is not None:
    app.config.from_envvar('GAMEWEB_SETTINGS')
app.secret_key = app.config['SECRET_KEY']
limiter = Limiter(app, key_func=get_remote_address)


def render_template(tpl_name, **kwargs):
    import flask
    g = {}
    if 'username' in session:
        g['username'] = session['username']
    return flask.render_template(tpl_name, g=g, **kwargs)


def connect_db():
    """Connection to database"""
    db = ds(app.config['DATABASE'])
    return db


def get_db():
    if not hasattr(g, 'db'):
        g.db = connect_db()
    return g.db


@app.teardown_appcontext
def close_db(error):
    if hasattr(g, 'db'):
        g.db.close()


def init_db():
    db = get_db().gethandle()
    with app.open_resource("schema.sql") as f:
        db.cursor().executescript(f.read().decode())
    db.commit()


def check_login(level=0):
    """
    装饰器 检查用户身份
    :param level: 用户需要的等级
    :return:
    """

    def warpper(func):
        @wraps(func)
        def __decorator(*args, **kwargs):
            if not session.__contains__('username') or session['username'] is None:
                abort(401)
            ret = func(*args, **kwargs)
            return ret

        return __decorator

    return warpper


@app.cli.command('initdb')
def initdb_cmd():
    try:
        init_db()
        print("Initialized database")
    except Exception as e:
        print(e)


@app.errorhandler(401)
def Unauthorized(e):
    return redirect(url_for("login"))


@app.errorhandler(400)
def badRequest(e):
    return "提交出错，请更正重试", 400


@app.errorhandler(404)
def notFound(e):
    return "未找到", 404


@app.errorhandler(429)
def tooManyRequests(e):
    return "频率过快", 429


@app.errorhandler(500)
def internalError(e):
    return "服务器智障", 500


@app.route("/")
@limiter.exempt
def index():
    return render_template('index.html', username=session['username'] if 'username' in session else None)


@app.route("/book", methods=['GET', 'POST'])
@limiter.limit("10/hour", exempt_when=lambda: request.method == 'GET')
def book():
    # TODO:生成一个验证token用于删除/验证身份
    result = {}
    db = get_db()

    class CustomException(Exception):
        pass

    if request.method == 'POST':
        try:
            phone = request.form['cellphone']
            contact = {'title': request.form['title'] if request.form['title'] is not None else '匿名'}
            isEmpty = lambda x: request.form[x] is "" if x in request.form else True
            if isEmpty("cellphone"):
                raise CustomException("需要电话号码")
            elif isEmpty("hours"):
                raise CustomException("请选定预订的时间")
            elif isEmpty("date"):
                raise CustomException("请选择日期")
            elif isEmpty("room"):
                raise CustomException("请选择房间")
            else:
                try:
                    t = datetime.datetime.strptime(request.form['date'], '%Y-%m-%d').date()
                    if t <= datetime.datetime.now().date():  # 预订的时候必须从明天开始
                        raise CustomException("只能从明天开始预订")
                except ValueError:
                    return "日期不正确", 400
            contact['cellphone'] = request.form['cellphone']

            def getprev(iterable):
                prev = None
                for x in iterable:
                    yield (prev, x)
                    prev = x

            for prev, x in getprev(request.form['hours'].split(',')):
                if prev is not None and int(x) - int(prev) is not 1:
                    raise CustomException("只允许预订连续时间段")
            # raise CustomException("test")
            ret = db.order(request.form['date'], request.form['hours'], json.dumps(contact), int(request.form['room']))
            if ret:
                return redirect(url_for('reserveSuccess'))  # TODO:重新写一个模板把reserveSuccess去掉，并且返回CREATED
        except KeyError:
            pass
        except CustomException as e:
            result['error'] = e
        except RoomConflict:
            result['error'] = "房间预订冲突，请刷新后再次预订"
    return render_template('book.html', roomtypes=db.getroomtypes(), rooms=db.getrooms(type=0, IDonly=False),
                           result=result)


@app.route('/bookSuccess', methods=['GET'])
def reserveSuccess():
    """
    预订成功页面
    @deprecated
    :return:
    """
    print('success')
    return render_template('success.html')


@app.route("/query", methods=['GET'])
def query():
    """
    查询占用情况
    JSON返回
    表单数据
        date: 日期 (YYYY-MM-DD)
        roomtype: 房间类型
        room: 单独指定room查询 (覆盖roomtype)
    """
    try:
        db = get_db()
        date = datetime.datetime.strptime(request.args.get('date'), "%Y-%m-%d").date()
        if request.args.get('room') is not None:
            return jsonify(db.query(date=date, room=int(request.args.get('room'))))
        elif request.args.get('roomtype') is not None:
            ret = []
            for room in db.getrooms(type=int(request.args.get('roomtype'))):
                ret.append({"roomid": room, "occupied": db.query(date=date, room=room)})
            return jsonify(ret)
        else:
            print('no room/roomtype')
            abort(400)
    except (KeyError, ValueError, TypeError):
        print('keyvalueerror')
        abort(400)


@app.route("/login", methods=['GET', 'POST'])
@limiter.limit("5 per hour", exempt_when=lambda: request.method == 'GET')
def login():
    if request.method == 'POST':
        try:
            if request.form['username'] is None or request.form['password'] is None:
                return render_template("login.html", result={"error": "用户名/密码不能为空"})
            db = get_db()
            if db.checkPassword(request.form['username'], request.form['password']):
                session['username'] = request.form['username']
                g.template_username = session['username']
                sig_user_logged_in.send(current_app._get_current_object())
                return redirect(url_for("index"))
            else:
                return render_template("login.html", result={"error": "密码错误"})
        except ValueError:
            raise ValueError
    elif request.method == 'GET':
        return render_template("login.html")
    else:
        abort(400)


@app.route("/logout", methods=['GET'])
@check_login()
def logout():
    session.pop('username', None)
    g.template_username = None
    return redirect(url_for('index'))


@app.route("/order")
@check_login()
def processOrder():
    """
    显示订单，默认当天
    表单数据：
        startdate:开始日期
        enddate:结束日期
    :return:
    """
    try:
        db = get_db()
        x = lambda x: datetime.datetime.strptime(x, "%Y-%m-%d").date()
        now = datetime.datetime.now()
        startdate_str = request.args['startdate'] if 'startdate' in request.args else now.date().strftime("%Y-%m-%d")
        enddate_str = request.args['enddate'] if 'enddate' in request.args else (
            now + datetime.timedelta(days=1)).date().strftime("%Y-%m-%d")
        orders_src = db.queryOrder(x(startdate_str), x(enddate_str))
        orders = None
        rooms = db.getrooms(type=0, IDonly=False)
        for line in orders_src:
            if orders is None:
                orders = []
            newline = dict(line)
            newline['hours'] = newline['hours'].split(',')
            tgtID = newline['place']
            newline['place'] = "房间被删除"
            for room in rooms:
                if room['id'] == tgtID:
                    newline['place'] = room['name']
            contact = newline['contact']
            import json
            contact = json.loads(contact)
            newline['title'] = contact['title']
            newline['tel'] = contact['cellphone']
            orders.append(newline)
        return render_template("order.html", orders=orders, startdate=startdate_str, enddate=enddate_str)
    except ValueError:
        return render_template("order.html")


@app.route("/order/<int:orderID>", methods=["DELETE"])
@check_login()
def deleteOrder(orderID):
    # TODO:实现删除
    pass


@app.route("/games")
def about():
    return render_template("games.html")


if __name__ == '__main__':
    app.run(debug=True, use_debugger=False, use_reloader=False)
