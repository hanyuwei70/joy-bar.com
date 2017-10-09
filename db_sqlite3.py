# encoding:utf-8
import sqlite3, datetime, time, hashlib, binascii,os


class RoomConflict(Exception): pass


class DataSource:
    def __init__(self, filename="db.sqlite3"):
        """
        :param filename: string 打开的文件名
        """
        self.rv = sqlite3.connect(filename)
        self.rv.row_factory = sqlite3.Row

    def close(self):
        self.rv.close()

    def gethandle(self):
        """
        返回原始的数据库连接
        :return: object 原始连接
        """
        return self.rv

    def getroomtypes(self):
        """
        获取房间种类
        :return: 房间种类
        :rtype: list 每个元素都是一个dict name:名称 desc:描述
        """
        res=self.rv.execute("SELECT * FROM places_types").fetchall()
        ret=[]
        for line in res:
            ret.append(dict(line))
        return ret

    def getrooms(self, type=0, IDonly=True):
        """
        获得type所对应的房间
        :param int type: 房间类型 =0代表不限制
        :param bool IDonly: 是否只返回ID
        :return: 房间列表
        """
        if type == 0:
            rooms = self.rv.execute("SELECT * FROM places").fetchall()
        else:
            rooms = self.rv.execute("SELECT * FROM places WHERE type=?", [type]).fetchall()
        ret = []
        for room in rooms:
            room=dict(room)
            ret.append(room['id'] if IDonly else room)
        return ret

    def order(self, date, hours, contact, room):
        """
        下订单
        :param str date: 日期
        :param str hours: 小时
        :param str contact: 联系方式
        :param int room:房间号
        :return: bool 预定结果
        :raise RoomConflict: 房间冲突
        :raise RuntimeError: 系统失败，比如数据库失效等
        """
        try:
            cur = self.rv.cursor()
            cur.execute("BEGIN EXCLUSIVE")
            res = cur.execute("SELECT hours FROM reservations WHERE place=? AND date=?", [room, date]).fetchall()
            newhrs = hours.split(',')
            for x in res:
                for num in x['hours'].split(','):
                    if num in newhrs:
                        raise RoomConflict
            cur.execute("INSERT INTO reservations(contact, place, hours, date) VALUES (?,?,?,?)",
                        [contact, room, hours, date])
            return True
        except sqlite3.IntegrityError:
            raise RoomConflict
        except sqlite3.DatabaseError:
            raise RuntimeError
        finally:
            cur.execute("COMMIT")

    def cancel(self, token):
        """
        取消订单
        :param str token:
        """
        pass

    def query(self, date, room):
        """
        查询当天的预订情况
        :param datetime.date date: 查询日期字符串
        :param int room: 房间号
        :return: 被占用的小时
        :rtype: list
        """
        res = self.rv.execute("SELECT * FROM reservations WHERE date = ? AND place = ?", [date, room])
        ret = []
        for line in res:
            ret += line['hours'].split(',')
        return list(ret)

    def queryAllOrder(self):
        """
        查询所有订单
        :return:
        :rtype: list
        """
        res=self.rv.execute("SELECT * FROM reservations ORDER BY date").fetchall()
        return res

    def queryOrder(self,startDate=datetime.datetime.now().date(),endDate=None):
        """
        查询订单
        :param date startDate: 开始日期
        :param date endDate: 结束日期
        :return:
        """
        if endDate is not None:
            res=self.rv.execute("SELECT * FROM reservations WHERE date between ? AND ?",[startDate,endDate]).fetchall()
        else:
            res=self.rv.execute("SELECT * FROM reservations WHERE date > ?",
                                [startDate]).fetchall()
        return res

    def checkPassword(self, username, password):
        """
        检查用户名/密码对
        :param str username: 用户名
        :param str password: 密码（明文）
        :return: 比对结果
        """
        try:
            res = self.rv.execute("SELECT * FROM users WHERE username=?", [username]).fetchone()
        except:
            return False
        try:
            algo, iter, salt, expecthash = res['password'].split('$', 3)
            salt=binascii.unhexlify(salt)
            passwordhash = binascii.hexlify(hashlib.pbkdf2_hmac(algo, password.encode(), salt, int(iter))).decode()
        except (TypeError,ValueError):
            return False
        return expecthash == passwordhash

    def setPassword(self, username, password):
        """
        修改密码
        :param username: 用户名
        :param password: 新密码
        存储进数据库的密码格式为 algo$iter$salt$hash
        """
        salt=os.urandom(16)
        passwordhash=binascii.hexlify(hashlib.pbkdf2_hmac('sha256',password.encode(),salt,100)).decode()
        combied='$'.join(['sha256','100',binascii.hexlify(salt).decode(),passwordhash])
        res=self.rv.execute("UPDATE users SET password = ? WHERE username = ?", (combied, username))
        if self.rv.in_transaction:
            self.rv.execute("COMMIT")
