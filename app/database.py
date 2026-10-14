import hashlib
import json
import secrets
import sqlite3
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS schools(id INTEGER PRIMARY KEY,name TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'DRAFT');
CREATE TABLE IF NOT EXISTS campuses(id INTEGER PRIMARY KEY,tenant_id INTEGER NOT NULL REFERENCES schools(id),name TEXT NOT NULL,active INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS canteens(id INTEGER PRIMARY KEY,tenant_id INTEGER NOT NULL REFERENCES schools(id),campus_id INTEGER NOT NULL REFERENCES campuses(id),name TEXT NOT NULL,pickup TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS buildings(id INTEGER PRIMARY KEY,tenant_id INTEGER NOT NULL REFERENCES schools(id),campus_id INTEGER NOT NULL REFERENCES campuses(id),name TEXT NOT NULL,mode TEXT NOT NULL CHECK(mode IN ('ROOM','LOBBY')),max_floor INTEGER NOT NULL DEFAULT 6,active INTEGER NOT NULL DEFAULT 1,version INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS merchants(id INTEGER PRIMARY KEY,tenant_id INTEGER NOT NULL REFERENCES schools(id),campus_id INTEGER NOT NULL REFERENCES campuses(id),canteen_id INTEGER NOT NULL REFERENCES canteens(id),name TEXT NOT NULL,status TEXT NOT NULL CHECK(status IN ('PENDING','OPEN','PAUSED','REJECTED')),description TEXT NOT NULL DEFAULT '',delivery_cents INTEGER NOT NULL DEFAULT 200 CHECK(delivery_cents>=0),minimum_cents INTEGER NOT NULL DEFAULT 800 CHECK(minimum_cents>=0),review_note TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY,username TEXT NOT NULL UNIQUE,password_hash TEXT NOT NULL,display_name TEXT NOT NULL,role TEXT NOT NULL,tenant_id INTEGER REFERENCES schools(id),campus_id INTEGER REFERENCES campuses(id),merchant_id INTEGER REFERENCES merchants(id));
CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id),expires_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS products(id INTEGER PRIMARY KEY,merchant_id INTEGER NOT NULL REFERENCES merchants(id),name TEXT NOT NULL,description TEXT NOT NULL,category TEXT NOT NULL,art TEXT NOT NULL DEFAULT 'bowl',active INTEGER NOT NULL DEFAULT 1,options_json TEXT NOT NULL DEFAULT '[]');
CREATE TABLE IF NOT EXISTS skus(id INTEGER PRIMARY KEY,product_id INTEGER NOT NULL REFERENCES products(id),label TEXT NOT NULL,price_cents INTEGER NOT NULL CHECK(price_cents>=0),box_cents INTEGER NOT NULL DEFAULT 100 CHECK(box_cents>=0),stock INTEGER NOT NULL CHECK(stock>=0),version INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS quotes(id TEXT PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id),merchant_id INTEGER NOT NULL REFERENCES merchants(id),request_json TEXT NOT NULL,snapshot_json TEXT NOT NULL,fingerprint TEXT NOT NULL,expires_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS orders(id TEXT PRIMARY KEY,tenant_id INTEGER NOT NULL REFERENCES schools(id),campus_id INTEGER NOT NULL REFERENCES campuses(id),merchant_id INTEGER NOT NULL REFERENCES merchants(id),user_id INTEGER NOT NULL REFERENCES users(id),quote_id TEXT NOT NULL UNIQUE REFERENCES quotes(id),idem_key TEXT NOT NULL,request_hash TEXT NOT NULL,status TEXT NOT NULL,payment_status TEXT NOT NULL DEFAULT 'UNPAID',refund_status TEXT NOT NULL DEFAULT 'NONE',total_cents INTEGER NOT NULL,snapshot_json TEXT NOT NULL,version INTEGER NOT NULL DEFAULT 1,created_at INTEGER NOT NULL,updated_at INTEGER NOT NULL,payment_deadline INTEGER NOT NULL,stock_returned INTEGER NOT NULL DEFAULT 0,UNIQUE(user_id,idem_key));
CREATE TABLE IF NOT EXISTS order_items(id INTEGER PRIMARY KEY,order_id TEXT NOT NULL REFERENCES orders(id),sku_id INTEGER NOT NULL REFERENCES skus(id),quantity INTEGER NOT NULL CHECK(quantity>0));
CREATE TABLE IF NOT EXISTS stock_movements(id INTEGER PRIMARY KEY,sku_id INTEGER NOT NULL REFERENCES skus(id),order_id TEXT REFERENCES orders(id),kind TEXT NOT NULL,delta INTEGER NOT NULL,created_at INTEGER NOT NULL,UNIQUE(sku_id,order_id,kind));
CREATE TABLE IF NOT EXISTS payments(id INTEGER PRIMARY KEY,order_id TEXT NOT NULL UNIQUE REFERENCES orders(id),event_key TEXT NOT NULL UNIQUE,amount_cents INTEGER NOT NULL,provider TEXT NOT NULL CHECK(provider='LOCAL_DEMO'),created_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS refunds(id INTEGER PRIMARY KEY,order_id TEXT NOT NULL UNIQUE REFERENCES orders(id),amount_cents INTEGER NOT NULL,reason TEXT NOT NULL,provider TEXT NOT NULL CHECK(provider='LOCAL_DEMO'),created_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS delivery_tasks(order_id TEXT PRIMARY KEY REFERENCES orders(id),tenant_id INTEGER NOT NULL REFERENCES schools(id),campus_id INTEGER NOT NULL REFERENCES campuses(id),state TEXT NOT NULL,rider_id INTEGER REFERENCES users(id),offer_deadline INTEGER,updated_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY,order_id TEXT NOT NULL REFERENCES orders(id),actor_id INTEGER REFERENCES users(id),action TEXT NOT NULL,note TEXT NOT NULL,created_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS audits(id INTEGER PRIMARY KEY,actor_id INTEGER REFERENCES users(id),target TEXT NOT NULL,action TEXT NOT NULL,note TEXT NOT NULL,created_at INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS ix_orders_scope ON orders(tenant_id,merchant_id,user_id);
CREATE INDEX IF NOT EXISTS ix_delivery_queue ON delivery_tasks(tenant_id,campus_id,state);
"""


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 180_000).hex()
    return salt + '$' + digest


class Database:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self, write=False):
        conn = sqlite3.connect(self.path, timeout=15, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys=ON')
        conn.execute('PRAGMA busy_timeout=15000')
        try:
            if write:
                conn.execute('BEGIN IMMEDIATE')
            yield conn
            if write:
                conn.commit()
        except Exception:
            if write:
                conn.rollback()
            raise
        finally:
            conn.close()

    def initialize(self):
        with self.connect() as c:
            c.execute('PRAGMA journal_mode=WAL')
            c.executescript(SCHEMA)
        with self.connect(True) as c:
            if c.execute('SELECT count(*) FROM users').fetchone()[0]:
                return
            c.executemany('INSERT INTO schools VALUES(?,?,?)', [(1,'四川农业大学 · 演示租户','DEMO_ENABLED'),(2,'第二学校 · 隔离验证演示','DEMO_ENABLED')])
            c.executemany('INSERT INTO campuses VALUES(?,?,?,?)', [(1,1,'雅安校区 · 演示',1),(2,1,'成都校区 · 待配置',0),(3,1,'都江堰校区 · 待配置',0),(4,2,'演示校区',1)])
            c.executemany('INSERT INTO canteens VALUES(?,?,?,?,?)',[(1,1,1,'演示第一食堂','一层 A 区取餐台（演示）'),(2,1,1,'演示第二食堂','一层 B 区取餐台（演示）'),(3,2,4,'第二学校演示食堂','演示取餐台')])
            c.executemany('INSERT INTO buildings VALUES(?,?,?,?,?,?,?,?)',[(1,1,1,'演示 A 栋','ROOM',6,1,1),(2,1,1,'演示 B 栋','LOBBY',8,1,1),(3,1,1,'演示 C 栋 · 未开放','ROOM',6,0,1),(4,2,4,'第二学校演示宿舍','ROOM',6,1,1)])
            c.executemany('INSERT INTO merchants(id,tenant_id,campus_id,canteen_id,name,status,description,delivery_cents,minimum_cents) VALUES(?,?,?,?,?,?,?,?,?)',[(1,1,1,1,'青禾小碗饭','OPEN','热乎现炒，一份刚刚好的食堂味道。',200,800),(2,1,1,2,'麦香面食铺','OPEN','汤面、拌面与暖胃小食。',150,600),(3,2,4,3,'第二学校演示档口','OPEN','用于验证学校之间的数据隔离。',200,600)])
            accounts=[('student','演示同学','student',1,1,None),('student_b','另一位演示同学','student',1,1,None),('merchant','青禾店长','merchant',1,1,1),('merchant_b','麦香店长','merchant',1,1,2),('admin','平台演示管理员','admin',None,None,None),('schoolops','雅安演示运营','school_admin',1,1,None),('rider','配送员小禾','rider',1,1,None),('rider_b','配送员小麦','rider',1,1,None),('applicant','待入驻经营者','applicant',1,1,None),('student2','第二学校同学','student',2,4,None),('merchant2','第二学校店长','merchant',2,4,3),('rider2','第二学校配送员','rider',2,4,None),('schoolops2','第二学校运营','school_admin',2,4,None)]
            for i,(name,display,role,tenant,campus,merchant) in enumerate(accounts,1):
                c.execute('INSERT INTO users VALUES(?,?,?,?,?,?,?,?)',(i,name,password_hash('demo12345'),display,role,tenant,campus,merchant))
            options=[{'id':'spice','name':'口味','min':1,'max':1,'choices':[{'id':'mild','name':'微辣','cents':0},{'id':'plain','name':'不辣','cents':0},{'id':'hot','name':'香辣','cents':0}]},{'id':'extras','name':'加点好料','min':0,'max':2,'choices':[{'id':'egg','name':'煎蛋','cents':200},{'id':'rice','name':'加米饭','cents':100}]}]
            products=[(1,1,'照烧鸡腿饭','鲜嫩鸡腿配时蔬，酱汁与米饭正好相遇。','人气饭碗','chicken',options),(2,1,'番茄炒蛋饭','酸甜番茄与嫩滑鸡蛋，简单也认真。','人气饭碗','tomato',options),(3,1,'菌菇时蔬饭','多种时蔬与菌菇，清爽的一餐。','轻盈蔬食','greens',options),(4,1,'冬瓜玉米汤','一碗暖汤，为午餐收尾。','暖汤小食','soup',[]),(5,2,'香菇牛肉面','汤底浓香，现煮面条。','热汤面','noodles',options),(6,2,'葱油拌面','葱香浓郁，拌开即食。','拌面','noodles',options),(7,3,'第二学校演示套餐','租户隔离验收用菜品。','套餐','bowl',options)]
            for pid,mid,name,desc,cat,art,opts in products:
                c.execute('INSERT INTO products VALUES(?,?,?,?,?,?,?,?)',(pid,mid,name,desc,cat,art,1,encode(opts)))
            c.executemany('INSERT INTO skus VALUES(?,?,?,?,?,?,?)',[(1,1,'标准份',1400,100,30,1),(2,1,'加量份',1800,100,15,1),(3,2,'标准份',1000,100,30,1),(4,3,'标准份',1200,100,20,1),(5,4,'一碗',400,50,30,1),(6,5,'标准份',1600,100,30,1),(7,6,'标准份',900,100,30,1),(8,7,'标准份',1000,100,30,1)])
