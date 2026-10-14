import hashlib
import asyncio
from contextlib import asynccontextmanager, suppress
import json
import os
import secrets
import sqlite3
from pathlib import Path
from urllib.parse import urlsplit
from fastapi import FastAPI, Request, Response, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, StrictInt
from .database import Database, encode, password_hash
from .domain import now, fail, must, role, scope, event, audit, order_row, can_view, serialize_order, quote_snapshot, maintenance, act

ROOT=Path(__file__).resolve().parents[1]


class Input(BaseModel):
    model_config=ConfigDict(extra='forbid')


class Login(Input):
    username: str=Field(min_length=1,max_length=40)
    password: str=Field(min_length=1,max_length=100)


class Address(Input):
    building_id: StrictInt
    floor: StrictInt=Field(ge=1,le=99)
    room: str=Field(min_length=1,max_length=12,pattern=r'^[A-Za-z0-9-]+$')
    alias: str=Field(min_length=1,max_length=20)
    accept_lobby: bool=False


class CartItem(Input):
    sku_id: StrictInt
    quantity: StrictInt=Field(ge=1,le=20)
    options: list[str]=Field(default_factory=list,max_length=20)


class QuoteInput(Input):
    merchant_id: StrictInt
    address: Address
    items: list[CartItem]=Field(min_length=1,max_length=30)
    note: str=Field(default='',max_length=120)


class CreateOrder(Input):
    quote_id: str=Field(min_length=10,max_length=100)


class PayInput(Input):
    event_key: str=Field(min_length=8,max_length=100)
    amount_cents: StrictInt=Field(ge=0,le=10000000)


class Action(Input):
    action: str=Field(max_length=30)
    version: StrictInt=Field(ge=1)
    reason: str=Field(default='',max_length=120)
    rider_id: StrictInt | None=None
    confirmed_point: str=Field(default='',max_length=50)
    confirmed_not_picked_up: bool=False


class ProductInput(Input):
    name: str=Field(min_length=1,max_length=40)
    description: str=Field(default='',max_length=150)
    category: str=Field(min_length=1,max_length=30)
    active: bool=True
    label: str=Field(min_length=1,max_length=20)
    price_cents: StrictInt=Field(ge=1,le=100000)
    box_cents: StrictInt=Field(ge=0,le=5000)
    stock: StrictInt=Field(ge=0,le=10000)
    version: StrictInt | None=None


class Application(Input):
    canteen_id: StrictInt
    name: str=Field(min_length=2,max_length=40)
    description: str=Field(min_length=2,max_length=150)


class Review(Input):
    approve: bool
    note: str=Field(min_length=2,max_length=120)


class BuildingInput(Input):
    mode: str=Field(pattern='^(ROOM|LOBBY)$')
    active: bool
    max_floor: StrictInt=Field(ge=1,le=30)
    version: StrictInt


class SchoolInput(Input):
    name: str=Field(min_length=2,max_length=50)
    campus_name: str=Field(min_length=2,max_length=50)


class SchoolState(Input):
    enabled: bool


class ShopState(Input):
    open: bool


def create_app(db_path=None):
    db=Database(db_path or os.getenv('CAMPUS_DB_PATH',str(ROOT/'runtime/campus-demo.sqlite3')))
    db.initialize()
    def recover_deadlines():
        with db.connect(True) as c:
            return maintenance(c)

    @asynccontextmanager
    async def lifespan(app):
        await asyncio.to_thread(recover_deadlines)
        async def deadlines():
            while True:
                await asyncio.sleep(10)
                await asyncio.to_thread(recover_deadlines)
        worker=asyncio.create_task(deadlines())
        try:
            yield
        finally:
            worker.cancel()
            with suppress(asyncio.CancelledError):
                await worker

    app=FastAPI(title='禾饭 Campus Dining — 本地演示 API',version='0.1.0',docs_url=None,redoc_url=None,openapi_url='/api/openapi.json',lifespan=lifespan)
    app.state.db=db

    @app.middleware('http')
    async def local_boundary(request: Request, call_next):
        host=request.url.hostname
        if host not in ('localhost','127.0.0.1','::1','testserver'):
            return JSONResponse({'detail':{'code':'LOCAL_ONLY','message':'此演示仅允许本机访问'}},403)
        if request.method not in ('GET','HEAD','OPTIONS'):
            origin=request.headers.get('origin')
            if origin and urlsplit(origin).netloc!=request.url.netloc:
                return JSONResponse({'detail':{'code':'ORIGIN','message':'拒绝跨站写入'}},403)
            if request.headers.get('sec-fetch-site')=='cross-site':
                return JSONResponse({'detail':{'code':'ORIGIN','message':'拒绝跨站写入'}},403)
        response=await call_next(request)
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['X-Frame-Options']='DENY'
        response.headers['Referrer-Policy']='no-referrer'
        response.headers['Content-Security-Policy']="default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        if request.url.path.startswith('/api/'):
            response.headers['Cache-Control']='no-store'
        return response

    @app.exception_handler(sqlite3.IntegrityError)
    async def db_conflict(request, exc):
        return JSONResponse({'detail':{'code':'CONFLICT','message':'数据已变化或请求重复，请刷新重试'}},409)

    def current(request,c):
        token=request.cookies.get('campus_session','')
        hashed=hashlib.sha256(token.encode()).hexdigest()
        user=c.execute('SELECT u.* FROM users u JOIN sessions s ON s.user_id=u.id WHERE s.token_hash=? AND s.expires_at>?',(hashed,now())).fetchone()
        must(user is not None,'UNAUTHENTICATED','请先登录演示账号',401)
        return user

    def public_user(user):
        return {k:user[k] for k in ('id','username','display_name','role','tenant_id','campus_id','merchant_id')}

    def menu(c,mid):
        result=[]
        for row in c.execute('SELECT * FROM products WHERE merchant_id=? ORDER BY id',(mid,)):
            item=dict(row)
            item['options']=json.loads(item.pop('options_json'))
            item['skus']=[dict(x) for x in c.execute('SELECT * FROM skus WHERE product_id=? ORDER BY id',(row['id'],))]
            result.append(item)
        return result

    @app.get('/api/health')
    def health():
        with db.connect() as c:
            c.execute('SELECT 1').fetchone()
        return {'status':'ok','mode':'LOCAL_DEMO','payment_provider':'LOCAL_DEMO','real_transactions':False,'database':'SQLite persistent'}

    @app.get('/api/meta')
    def meta():
        with db.connect() as c:
            return {'name':'禾饭','demo':True,'notice':'所有学校服务范围、食堂、菜单、楼栋和账号均为演示配置；未接入真实支付、短信或外部配送。','accounts':[dict(x) for x in c.execute('SELECT username,display_name,role,tenant_id FROM users ORDER BY id')],'schools':[dict(x) for x in c.execute('SELECT * FROM schools')],'campuses':[dict(x) for x in c.execute('SELECT * FROM campuses')]}

    @app.post('/api/login')
    def login(data: Login,response: Response):
        with db.connect(True) as c:
            user=c.execute('SELECT * FROM users WHERE username=?',(data.username,)).fetchone()
            valid=user and secrets.compare_digest(password_hash(data.password,user['password_hash'].split('$')[0]),user['password_hash'])
            must(valid,'LOGIN','演示账号或密码不正确',401)
            token=secrets.token_urlsafe(32)
            c.execute('DELETE FROM sessions WHERE expires_at<?',(now(),))
            c.execute('INSERT INTO sessions VALUES(?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),user['id'],now()+8*3600))
            response.set_cookie('campus_session',token,httponly=True,samesite='strict',max_age=8*3600,path='/')
            return public_user(user)

    @app.post('/api/logout')
    def logout(request: Request,response: Response):
        with db.connect(True) as c:
            c.execute('DELETE FROM sessions WHERE token_hash=?',(hashlib.sha256(request.cookies.get('campus_session','').encode()).hexdigest(),))
        response.delete_cookie('campus_session')
        return {'ok':True}

    @app.get('/api/me')
    def me(request: Request):
        with db.connect() as c:
            return public_user(current(request,c))

    @app.get('/api/catalog')
    def catalog(request: Request,campus_id: int | None=None):
        with db.connect() as c:
            user=current(request,c)
            campus_id=campus_id or user['campus_id'] or 1
            campus=c.execute('SELECT * FROM campuses WHERE id=?',(campus_id,)).fetchone()
            must(campus is not None and scope(user,campus['tenant_id'],campus_id),'FORBIDDEN','无权访问该学校或校区数据',403)
            merchants=[]
            for row in c.execute('SELECT m.*,ct.name canteen_name,ct.pickup FROM merchants m JOIN canteens ct ON ct.id=m.canteen_id WHERE m.campus_id=? AND m.status IN (\'OPEN\',\'PAUSED\')',(campus_id,)):
                item=dict(row)
                item['products']=menu(c,row['id'])
                merchants.append(item)
            return {'campus':dict(campus),'merchants':merchants,'buildings':[dict(x) for x in c.execute('SELECT * FROM buildings WHERE campus_id=?',(campus_id,))],'canteens':[dict(x) for x in c.execute('SELECT * FROM canteens WHERE campus_id=?',(campus_id,))]}

    @app.post('/api/quotes')
    def create_quote(data: QuoteInput,request: Request):
        with db.connect(True) as c:
            user=current(request,c)
            maintenance(c)
            snapshot,fingerprint,_=quote_snapshot(c,user,data.model_dump())
            qid=secrets.token_urlsafe(18)
            expires=now()+180
            c.execute('INSERT INTO quotes VALUES(?,?,?,?,?,?,?)',(qid,user['id'],data.merchant_id,encode(data.model_dump()),encode(snapshot),fingerprint,expires))
            return {'id':qid,'expires_at':expires,'snapshot':snapshot}

    @app.post('/api/orders')
    def create_order(data: CreateOrder,request: Request):
        key=request.headers.get('idempotency-key','')
        must(8<=len(key)<=100,'IDEMPOTENCY','必须提供 8 至 100 字符的 Idempotency-Key',422)
        with db.connect(True) as c:
            user=current(request,c)
            role(user,'student')
            maintenance(c)
            request_hash=hashlib.sha256(data.quote_id.encode()).hexdigest()
            existing=c.execute('SELECT * FROM orders WHERE user_id=? AND idem_key=?',(user['id'],key)).fetchone()
            if existing:
                must(existing['request_hash']==request_hash,'IDEMPOTENCY_MISMATCH','同一幂等键不可用于不同报价')
                return serialize_order(c,user,existing)
            quote=c.execute('SELECT * FROM quotes WHERE id=? AND user_id=?',(data.quote_id,user['id'])).fetchone()
            must(quote is not None,'QUOTE','报价不存在或无权访问',404)
            used=c.execute('SELECT * FROM orders WHERE quote_id=?',(data.quote_id,)).fetchone()
            if used:
                return serialize_order(c,user,used)
            must(quote['expires_at']>now(),'QUOTE_EXPIRED','报价已过期，请重新核价')
            snapshot,fingerprint,demand=quote_snapshot(c,user,json.loads(quote['request_json']))
            must(fingerprint==quote['fingerprint'],'QUOTE_CHANGED','商品或配送规则已变化，请重新核价确认')
            oid='HF'+str(now())+secrets.token_hex(3).upper()
            c.execute("INSERT INTO orders(id,tenant_id,campus_id,merchant_id,user_id,quote_id,idem_key,request_hash,status,total_cents,snapshot_json,created_at,updated_at,payment_deadline) VALUES(?,?,?,?,?,?,?,?, 'UNPAID',?,?,?,?,?)",(oid,snapshot['tenant_id'],snapshot['campus_id'],snapshot['merchant_id'],user['id'],data.quote_id,key,request_hash,snapshot['total_cents'],encode(snapshot),now(),now(),now()+900))
            for sid,quantity in demand.items():
                changed=c.execute('UPDATE skus SET stock=stock-?,version=version+1 WHERE id=? AND stock>=?',(quantity,sid,quantity)).rowcount
                must(changed==1,'OUT_OF_STOCK','库存刚被其他订单占用，请重新选择')
                c.execute('INSERT INTO order_items(order_id,sku_id,quantity) VALUES(?,?,?)',(oid,sid,quantity))
                c.execute("INSERT INTO stock_movements(sku_id,order_id,kind,delta,created_at) VALUES(?,?,'RESERVE',?,?)",(sid,oid,-quantity,now()))
            event(c,oid,user,'created','已创建本地测试订单，等待模拟支付；15 分钟后自动释放库存')
            return serialize_order(c,user,order_row(c,oid))

    @app.post('/api/orders/{oid}/simulate-payment')
    def pay(oid: str,data: PayInput,request: Request):
        with db.connect(True) as c:
            user=current(request,c)
            role(user,'student')
            maintenance(c)
            row=order_row(c,oid)
            must(can_view(c,user,row),'NOT_FOUND','订单不存在或无权访问',404)
            must(data.amount_cents==row['total_cents'],'PAYMENT_AMOUNT','模拟支付金额与后端订单金额不一致',422)
            previous=c.execute('SELECT * FROM payments WHERE event_key=?',(data.event_key,)).fetchone()
            must(previous is None or previous['order_id']==oid,'PAYMENT_KEY','该模拟事件已用于其他订单')
            paid=c.execute('SELECT * FROM payments WHERE order_id=?',(oid,)).fetchone()
            if paid:
                return serialize_order(c,user,row)
            must(row['status']=='UNPAID','PAYMENT_STATE','当前订单不可支付')
            c.execute("INSERT INTO payments(order_id,event_key,amount_cents,provider,created_at) VALUES(?,?,?,'LOCAL_DEMO',?)",(oid,data.event_key,row['total_cents'],now()))
            c.execute("UPDATE orders SET status='PAID',payment_status='PAID',version=version+1,updated_at=? WHERE id=?",(now(),oid))
            event(c,oid,user,'paid','本地模拟支付成功；未调用银行或任何支付渠道')
            return serialize_order(c,user,order_row(c,oid))

    @app.get('/api/orders')
    def orders(request: Request):
        with db.connect(True) as c:
            user=current(request,c)
            maintenance(c)
            rows=c.execute('SELECT * FROM orders ORDER BY created_at DESC,id DESC').fetchall()
            return [serialize_order(c,user,x) for x in rows if can_view(c,user,x)]

    @app.get('/api/orders/{oid}')
    def get_order(oid: str,request: Request):
        with db.connect(True) as c:
            user=current(request,c)
            maintenance(c)
            return serialize_order(c,user,order_row(c,oid))

    @app.post('/api/orders/{oid}/actions')
    def action(oid: str,data: Action,request: Request):
        with db.connect(True) as c:
            user=current(request,c)
            maintenance(c)
            return act(c,user,oid,data.model_dump())

    @app.get('/api/merchant')
    def merchant_home(request: Request):
        with db.connect() as c:
            user=current(request,c)
            role(user,'merchant','applicant')
            shop=c.execute('SELECT * FROM merchants WHERE id=?',(user['merchant_id'],)).fetchone()
            return {'merchant':dict(shop) if shop else None,'products':menu(c,shop['id']) if shop else [],'canteens':[dict(x) for x in c.execute('SELECT * FROM canteens WHERE tenant_id=? AND campus_id=?',(user['tenant_id'],user['campus_id']))]}

    @app.post('/api/merchant/apply')
    def apply(data: Application,request: Request):
        with db.connect(True) as c:
            user=current(request,c)
            role(user,'applicant')
            must(user['merchant_id'] is None,'APPLIED','已经提交入驻申请')
            canteen=c.execute('SELECT * FROM canteens WHERE id=?',(data.canteen_id,)).fetchone()
            must(canteen is not None and scope(user,canteen['tenant_id'],canteen['campus_id']),'FORBIDDEN','无权申请此食堂',403)
            cursor=c.execute("INSERT INTO merchants(tenant_id,campus_id,canteen_id,name,status,description) VALUES(?,?,?,?,'PENDING',?)",(user['tenant_id'],user['campus_id'],data.canteen_id,data.name,data.description))
            c.execute('UPDATE users SET merchant_id=? WHERE id=?',(cursor.lastrowid,user['id']))
            audit(c,user,str(cursor.lastrowid),'merchant_apply','演示入驻申请')
            return {'id':cursor.lastrowid,'status':'PENDING'}

    @app.post('/api/merchant/products')
    def create_product(data: ProductInput,request: Request):
        with db.connect(True) as c:
            user=current(request,c)
            role(user,'merchant')
            pid=c.execute('INSERT INTO products(merchant_id,name,description,category,active) VALUES(?,?,?,?,?)',(user['merchant_id'],data.name,data.description,data.category,int(data.active))).lastrowid
            sid=c.execute('INSERT INTO skus(product_id,label,price_cents,box_cents,stock) VALUES(?,?,?,?,?)',(pid,data.label,data.price_cents,data.box_cents,data.stock)).lastrowid
            audit(c,user,str(pid),'product_create','新建演示商品')
            return {'product_id':pid,'sku_id':sid}

    @app.put('/api/merchant/skus/{sid}')
    def edit_product(sid: int,data: ProductInput,request: Request):
        with db.connect(True) as c:
            user=current(request,c)
            role(user,'merchant')
            sku=c.execute('SELECT s.*,p.merchant_id FROM skus s JOIN products p ON p.id=s.product_id WHERE s.id=?',(sid,)).fetchone()
            must(sku is not None and sku['merchant_id']==user['merchant_id'],'NOT_FOUND','商品不存在或无权修改',404)
            must(sku['version']==data.version,'STALE_VERSION','商品已变化，请刷新')
            c.execute('UPDATE products SET name=?,description=?,category=?,active=? WHERE id=?',(data.name,data.description,data.category,int(data.active),sku['product_id']))
            c.execute('UPDATE skus SET version=version+1 WHERE product_id=? AND id<>?',(sku['product_id'],sid))
            c.execute('UPDATE skus SET label=?,price_cents=?,box_cents=?,stock=?,version=version+1 WHERE id=?',(data.label,data.price_cents,data.box_cents,data.stock,sid))
            c.execute("INSERT INTO stock_movements(sku_id,kind,delta,created_at) VALUES(?,'ADJUST',?,?)",(sid,data.stock-sku['stock'],now()))
            audit(c,user,str(sid),'sku_update','商品/库存人工调整（可售余量）')
            return {'ok':True}

    @app.post('/api/merchant/status')
    def shop_state(data: ShopState,request: Request):
        with db.connect(True) as c:
            user=current(request,c)
            role(user,'merchant')
            c.execute('UPDATE merchants SET status=? WHERE id=?',('OPEN' if data.open else 'PAUSED',user['merchant_id']))
            audit(c,user,str(user['merchant_id']),'shop_state','营业' if data.open else '休息')
            return {'ok':True}

    @app.get('/api/admin')
    def admin_home(request: Request):
        with db.connect(True) as c:
            user=current(request,c)
            role(user,'admin','school_admin')
            maintenance(c)
            filter_scope=lambda x:scope(user,x['tenant_id'],x['campus_id'])
            shops=[dict(x) for x in c.execute('SELECT m.*,ct.name canteen_name FROM merchants m JOIN canteens ct ON ct.id=m.canteen_id') if filter_scope(x)]
            buildings=[dict(x) for x in c.execute('SELECT * FROM buildings') if filter_scope(x)]
            riders=[public_user(x) for x in c.execute("SELECT * FROM users WHERE role='rider'") if filter_scope(x)]
            schools=[dict(x) for x in c.execute('SELECT * FROM schools') if user['role']=='admin' or x['id']==user['tenant_id']]
            rows=[x for x in c.execute('SELECT * FROM orders') if filter_scope(x)]
            paid=sum(c.execute('SELECT COALESCE(SUM(amount_cents),0) FROM payments WHERE order_id=?',(x['id'],)).fetchone()[0] for x in rows)
            refunded=sum(c.execute('SELECT COALESCE(SUM(amount_cents),0) FROM refunds WHERE order_id=?',(x['id'],)).fetchone()[0] for x in rows)
            return {'merchants':shops,'buildings':buildings,'riders':riders,'schools':schools,'metrics':{'orders':len(rows),'paid_cents':paid,'refunded_cents':refunded,'net_cents':paid-refunded,'pending_applications':sum(x['status']=='PENDING' for x in shops)},'payment_mode':'LOCAL_DEMO'}

    @app.post('/api/admin/merchants/{mid}/review')
    def review(mid: int,data: Review,request: Request):
        with db.connect(True) as c:
            user=current(request,c)
            role(user,'admin','school_admin')
            shop=c.execute('SELECT * FROM merchants WHERE id=?',(mid,)).fetchone()
            must(shop is not None and scope(user,shop['tenant_id'],shop['campus_id']),'NOT_FOUND','申请不存在或无权访问',404)
            must(shop['status']=='PENDING','REVIEWED','该申请已处理')
            c.execute('UPDATE merchants SET status=?,review_note=? WHERE id=?',('OPEN' if data.approve else 'REJECTED',data.note,mid))
            if data.approve:
                c.execute("UPDATE users SET role='merchant' WHERE merchant_id=? AND role='applicant'",(mid,))
            audit(c,user,str(mid),'merchant_review',data.note)
            return {'ok':True,'status':'OPEN' if data.approve else 'REJECTED'}

    @app.put('/api/admin/buildings/{bid}')
    def building(bid: int,data: BuildingInput,request: Request):
        with db.connect(True) as c:
            user=current(request,c)
            role(user,'admin','school_admin')
            row=c.execute('SELECT * FROM buildings WHERE id=?',(bid,)).fetchone()
            must(row is not None and scope(user,row['tenant_id'],row['campus_id']),'NOT_FOUND','楼栋不存在或无权访问',404)
            must(row['version']==data.version,'STALE_VERSION','规则已更新，请刷新')
            c.execute('UPDATE buildings SET mode=?,active=?,max_floor=?,version=version+1 WHERE id=?',(data.mode,int(data.active),data.max_floor,bid))
            audit(c,user,str(bid),'building_rule','演示楼栋规则更新，历史订单快照不变')
            return {'ok':True}

    @app.post('/api/admin/schools')
    def new_school(data: SchoolInput,request: Request):
        with db.connect(True) as c:
            user=current(request,c)
            role(user,'admin')
            sid=c.execute("INSERT INTO schools(name,status) VALUES(?,'DRAFT')",(data.name,)).lastrowid
            c.execute('INSERT INTO campuses(tenant_id,name,active) VALUES(?,?,0)',(sid,data.campus_name))
            audit(c,user,str(sid),'school_create','新增学校演示草案，尚未开放')
            return {'id':sid,'status':'DRAFT'}

    @app.post('/api/admin/schools/{sid}/state')
    def school_state(sid: int,data: SchoolState,request: Request):
        with db.connect(True) as c:
            user=current(request,c)
            role(user,'admin')
            must(c.execute('SELECT 1 FROM schools WHERE id=?',(sid,)).fetchone() is not None,'NOT_FOUND','学校不存在',404)
            c.execute('UPDATE schools SET status=? WHERE id=?',('DEMO_ENABLED' if data.enabled else 'PAUSED',sid))
            # Enabling the demo tenant does not silently enable its campuses.
            audit(c,user,str(sid),'school_state','仅更新演示租户状态，未开通实际运营')
            return {'ok':True}

    @app.post('/api/admin/maintenance')
    def run_maintenance(request: Request):
        with db.connect(True) as c:
            user=current(request,c)
            role(user,'admin')
            return maintenance(c)

    app.mount('/assets',StaticFiles(directory=ROOT/'web'),name='assets')

    @app.get('/')
    def index():
        return FileResponse(ROOT/'web/index.html')

    return app
