"""Independent campus ordering rules. All payment effects are local simulation."""
import hashlib
import json
import time
from collections import Counter
from fastapi import HTTPException
from .database import encode


def now():
    return int(time.time())


def fail(code, message, status=409):
    raise HTTPException(status, {'code': code, 'message': message})


def must(condition, code, message, status=409):
    if not condition:
        fail(code, message, status)


def scope(user, tenant, campus=None):
    return user['role'] == 'admin' or (user['tenant_id'] == tenant and (campus is None or user['campus_id'] == campus))


def role(user, *roles):
    must(user['role'] in roles, 'FORBIDDEN', '此账号没有该操作权限', 403)


def event(c, order_id, user, action, note=''):
    c.execute('INSERT INTO events(order_id,actor_id,action,note,created_at) VALUES(?,?,?,?,?)',(order_id,user['id'] if user else None,action,note,now()))


def audit(c, user, target, action, note=''):
    c.execute('INSERT INTO audits(actor_id,target,action,note,created_at) VALUES(?,?,?,?,?)',(user['id'],target,action,note,now()))


def order_row(c, oid):
    row=c.execute('SELECT * FROM orders WHERE id=?',(oid,)).fetchone()
    must(row is not None,'NOT_FOUND','订单不存在或无权访问',404)
    return row


def can_view(c, user, row):
    if not scope(user,row['tenant_id'],row['campus_id']):
        return False
    if user['role'] in ('admin','school_admin'):
        return True
    if user['role']=='student':
        return row['user_id']==user['id']
    if user['role']=='merchant':
        return row['merchant_id']==user['merchant_id']
    if user['role']=='rider':
        task=c.execute('SELECT * FROM delivery_tasks WHERE order_id=?',(row['id'],)).fetchone()
        return bool(task and (task['rider_id']==user['id'] or (task['state']=='WAITING' and row['refund_status']!='REQUESTED')))
    return False


def serialize_order(c, user, row):
    must(can_view(c,user,row),'NOT_FOUND','订单不存在或无权访问',404)
    data={k:row[k] for k in ('id','tenant_id','campus_id','merchant_id','status','payment_status','refund_status','total_cents','version','created_at','updated_at','payment_deadline')}
    snap=json.loads(row['snapshot_json'])
    task=c.execute('SELECT * FROM delivery_tasks WHERE order_id=?',(row['id'],)).fetchone()
    delivery=dict(task) if task else None
    if delivery and delivery['rider_id']:
        delivery['rider_name']=c.execute('SELECT display_name FROM users WHERE id=?',(delivery['rider_id'],)).fetchone()[0]
    if user['role']=='merchant':
        snap['address']={'building_name':snap['address']['building_name'],'mode':snap['address']['mode'],'delivery_label':snap['address']['delivery_label']}
    if user['role']=='rider':
        active=task and task['rider_id']==user['id'] and task['state'] in ('ASSIGNED','PICKED_UP')
        if not active:
            snap['address']={'building_name':snap['address']['building_name'],'mode':snap['address']['mode'],'delivery_label':snap['address']['delivery_label']}
            snap.pop('note',None)
        snap.pop('goods_cents',None)
        snap.pop('box_cents',None)
        snap.pop('total_cents',None)
        data.pop('total_cents',None)
        for item in snap['items']:
            for key in ('unit_cents','box_cents','subtotal_cents'):
                item.pop(key,None)
            for option in item['options']:
                option.pop('cents',None)
    data['snapshot']=snap
    data['delivery']=delivery
    data['events']=[dict(x) for x in c.execute('SELECT id,action,note,created_at FROM events WHERE order_id=? ORDER BY id',(row['id'],))] if user['role']!='rider' else []
    return data


def quote_snapshot(c, user, request):
    role(user,'student')
    merchant=c.execute('SELECT m.*,ct.name canteen_name,ct.pickup,cp.active campus_active,s.status school_status FROM merchants m JOIN canteens ct ON ct.id=m.canteen_id JOIN campuses cp ON cp.id=m.campus_id JOIN schools s ON s.id=m.tenant_id WHERE m.id=?',(request['merchant_id'],)).fetchone()
    must(merchant is not None and scope(user,merchant['tenant_id'],merchant['campus_id']),'FORBIDDEN','该档口不在当前账号服务范围',403)
    must(merchant['status']=='OPEN' and merchant['campus_active'] and merchant['school_status']=='DEMO_ENABLED','NOT_OPEN','学校、校区或档口暂未开放')
    address=request['address']
    building=c.execute('SELECT * FROM buildings WHERE id=?',(address['building_id'],)).fetchone()
    must(building is not None and building['tenant_id']==merchant['tenant_id'] and building['campus_id']==merchant['campus_id'],'ADDRESS_SCOPE','配送地址不属于当前校区',422)
    must(building['active']==1,'UNSERVICEABLE','该楼栋暂未开放配送')
    must(1<=address['floor']<=building['max_floor'],'FLOOR_RANGE','楼层不在允许范围',422)
    must(building['mode']!='LOBBY' or address['accept_lobby'],'LOBBY_CONSENT','该楼栋只支持楼下交付，请明确确认后再报价',422)
    snap_address={**address,'building_name':building['name'],'mode':building['mode'],'policy_version':building['version'],'delivery_label':'送到寝室' if building['mode']=='ROOM' else '楼下指定交付点（已确认）'}
    merged={}
    for item in request['items']:
        key=(item['sku_id'],tuple(sorted(item['options'])))
        must(len(set(item['options']))==len(item['options']),'OPTIONS','规格选项不可重复',422)
        merged[key]=merged.get(key,0)+item['quantity']
    must(bool(merged) and len(merged)<=20,'CART_SIZE','购物车需包含 1 至 20 种规格组合',422)
    demand=Counter()
    items=[]
    fingerprint=[]
    for (sid,selected),quantity in sorted(merged.items()):
        must(1<=quantity<=20,'QUANTITY','每种规格最多 20 份',422)
        sku=c.execute('SELECT s.*,p.merchant_id,p.name,p.active,p.options_json FROM skus s JOIN products p ON p.id=s.product_id WHERE s.id=?',(sid,)).fetchone()
        must(sku is not None and sku['merchant_id']==merchant['id'],'SKU_SCOPE','商品不属于当前档口',422)
        must(sku['active']==1,'PRODUCT_OFFLINE','商品已下架')
        groups=json.loads(sku['options_json'])
        chosen=[]
        known=set()
        for group in groups:
            picks=[option for option in group['choices'] if option['id'] in selected]
            must(group['min']<=len(picks)<=group['max'],'OPTIONS',f"请按要求选择：{group['name']}",422)
            known.update(option['id'] for option in group['choices'])
            chosen.extend(picks)
        must(set(selected)<=known,'OPTIONS','存在无效或不属于此商品的选项',422)
        demand[sid]+=quantity
        unit=sku['price_cents']+sum(x['cents'] for x in chosen)
        items.append({'sku_id':sid,'name':sku['name'],'sku_label':sku['label'],'options':chosen,'quantity':quantity,'unit_cents':unit,'box_cents':sku['box_cents'],'subtotal_cents':unit*quantity})
        # Stock movement changes the edit version, but not a still-valid price quote.
        fingerprint.append([sid,sku['price_cents'],sku['box_cents'],sku['options_json']])
    for sid,quantity in demand.items():
        must(c.execute('SELECT stock FROM skus WHERE id=?',(sid,)).fetchone()[0]>=quantity,'OUT_OF_STOCK','库存不足，请调整数量')
    goods=sum(x['subtotal_cents'] for x in items)
    boxes=sum(x['box_cents']*x['quantity'] for x in items)
    must(goods>=merchant['minimum_cents'],'MINIMUM',f"商品金额需达到 {merchant['minimum_cents']/100:.2f} 元")
    snapshot={'tenant_id':merchant['tenant_id'],'campus_id':merchant['campus_id'],'merchant_id':merchant['id'],'merchant_name':merchant['name'],'canteen_name':merchant['canteen_name'],'pickup':merchant['pickup'],'address':snap_address,'items':items,'note':request['note'],'goods_cents':goods,'box_cents':boxes,'delivery_cents':merchant['delivery_cents'],'total_cents':goods+boxes+merchant['delivery_cents'],'currency':'CNY','payment_adapter':'LOCAL_DEMO'}
    digest=hashlib.sha256(encode([snapshot,fingerprint]).encode()).hexdigest()
    return snapshot,digest,demand


def restore_stock(c, row):
    if row['stock_returned']:
        return
    for item in c.execute('SELECT sku_id,SUM(quantity) quantity FROM order_items WHERE order_id=? GROUP BY sku_id',(row['id'],)).fetchall():
        c.execute('UPDATE skus SET stock=stock+?,version=version+1 WHERE id=?',(item['quantity'],item['sku_id']))
        c.execute('INSERT INTO stock_movements(sku_id,order_id,kind,delta,created_at) VALUES(?,?,?,?,?)',(item['sku_id'],row['id'],'RELEASE',item['quantity'],now()))
    c.execute('UPDATE orders SET stock_returned=1 WHERE id=?',(row['id'],))


def refund(c, row, reason):
    must(row['payment_status'] in ('PAID','REFUNDED'),'NOT_PAID','订单尚未模拟支付')
    c.execute("INSERT OR IGNORE INTO refunds(order_id,amount_cents,reason,provider,created_at) VALUES(?,?,?,'LOCAL_DEMO',?)",(row['id'],row['total_cents'],reason,now()))
    c.execute("UPDATE orders SET payment_status='REFUNDED',refund_status='SUCCEEDED' WHERE id=?",(row['id'],))


def cancel(c, row, reason, rejected=False):
    if row['status'] in ('UNPAID','PAID'):
        restore_stock(c,row)
    if row['payment_status']=='PAID':
        refund(c,row,reason)
    c.execute('UPDATE orders SET status=? WHERE id=?',('REJECTED' if rejected else 'CANCELED',row['id']))
    c.execute("UPDATE delivery_tasks SET state='CANCELED',rider_id=NULL,offer_deadline=NULL,updated_at=? WHERE order_id=?",(now(),row['id']))


def maintenance(c):
    expired=c.execute("SELECT * FROM orders WHERE status='UNPAID' AND payment_deadline<=?",(now(),)).fetchall()
    for row in expired:
        cancel(c,row,'模拟付款超时，库存已释放')
        c.execute('UPDATE orders SET version=version+1,updated_at=? WHERE id=?',(now(),row['id']))
        event(c,row['id'],None,'expired','模拟付款超时，库存已释放')
    offers=c.execute("SELECT order_id FROM delivery_tasks WHERE state='OFFERED' AND offer_deadline<=?",(now(),)).fetchall()
    for task in offers:
        c.execute("UPDATE delivery_tasks SET state='WAITING',rider_id=NULL,offer_deadline=NULL,updated_at=? WHERE order_id=?",(now(),task['order_id']))
        c.execute('UPDATE orders SET version=version+1,updated_at=? WHERE id=?',(now(),task['order_id']))
        event(c,task['order_id'],None,'offer_expired','派单邀约超时，已回到待接队列')
    return {'expired_orders':len(expired),'expired_offers':len(offers)}


def act(c,user,oid,data):
    row=order_row(c,oid)
    must(can_view(c,user,row),'NOT_FOUND','订单不存在或无权访问',404)
    must(row['version']==data['version'],'STALE_VERSION','订单已变化，请刷新后重试')
    action=data['action']
    reason=data.get('reason','').strip()
    state=row['status']
    task=c.execute('SELECT * FROM delivery_tasks WHERE order_id=?',(oid,)).fetchone()
    blocked=row['refund_status']=='REQUESTED' and state in ('PREPARING','READY')
    if action=='cancel':
        role(user,'student')
        must(state in ('UNPAID','PAID'),'CANCEL_STAGE','商家已开始制作，请申请售后')
        cancel(c,row,reason or '学生取消')
    elif action in ('accept','reject','ready'):
        role(user,'merchant')
        must(not blocked,'REFUND_PENDING','售后处理中，暂不能继续制作或出餐')
        if action=='accept':
            must(state=='PAID','STATE','仅已模拟支付订单可接单')
            c.execute("UPDATE orders SET status='PREPARING' WHERE id=?",(oid,))
        elif action=='reject':
            must(state=='PAID','STATE','只可拒绝尚未接单的订单')
            must(bool(reason),'REASON','请填写拒单原因',422)
            cancel(c,row,reason,True)
        else:
            must(state=='PREPARING','STATE','仅备餐中的订单可出餐')
            c.execute("UPDATE orders SET status='READY' WHERE id=?",(oid,))
            c.execute("INSERT INTO delivery_tasks(order_id,tenant_id,campus_id,state,updated_at) VALUES(?,?,?,'WAITING',?)",(oid,row['tenant_id'],row['campus_id'],now()))
    elif action in ('claim','accept_offer','decline_offer','pickup','deliver'):
        role(user,'rider')
        must(not blocked,'REFUND_PENDING','该单正在处理售后')
        must(task is not None,'NO_TASK','配送任务尚未创建')
        if action=='claim':
            must(state=='READY' and task['state']=='WAITING','TAKEN','任务已被领取或不在待接状态')
            c.execute("UPDATE delivery_tasks SET rider_id=?,state='ASSIGNED',updated_at=? WHERE order_id=?",(user['id'],now(),oid))
        elif action in ('accept_offer','decline_offer'):
            must(task['rider_id']==user['id'] and task['state']=='OFFERED','OFFER','无权处理此派单邀约',403)
            if action=='accept_offer':
                c.execute("UPDATE delivery_tasks SET state='ASSIGNED',offer_deadline=NULL,updated_at=? WHERE order_id=?",(now(),oid))
            else:
                c.execute("UPDATE delivery_tasks SET state='WAITING',rider_id=NULL,offer_deadline=NULL,updated_at=? WHERE order_id=?",(now(),oid))
        else:
            must(task['rider_id']==user['id'],'ASSIGNEE','只有当前承运配送员可以操作',403)
            if action=='pickup':
                must(state=='READY' and task['state']=='ASSIGNED','STATE','请先接单，再确认取餐')
                c.execute("UPDATE orders SET status='PICKED_UP' WHERE id=?",(oid,))
                c.execute("UPDATE delivery_tasks SET state='PICKED_UP',updated_at=? WHERE order_id=?",(now(),oid))
            else:
                must(state=='PICKED_UP' and task['state']=='PICKED_UP','STATE','仅已取餐任务可送达')
                label=json.loads(row['snapshot_json'])['address']['delivery_label']
                must(data.get('confirmed_point')==label,'DELIVERY_POINT','请确认在订单约定的交付点完成交付',422)
                c.execute("UPDATE orders SET status='DELIVERED' WHERE id=?",(oid,))
                c.execute("UPDATE delivery_tasks SET state='DELIVERED',updated_at=? WHERE order_id=?",(now(),oid))
                reason=f'已按约定交付：{label}'
    elif action in ('assign','requeue'):
        role(user,'admin','school_admin')
        must(task is not None and state=='READY' and not blocked,'STATE','仅未取餐、无售后的出餐订单可调度')
        if action=='assign':
            must(task['state']=='WAITING','STATE','先回收原派单再重新指派')
            rider=c.execute("SELECT * FROM users WHERE id=? AND role='rider'",(data.get('rider_id'),)).fetchone()
            must(rider is not None and rider['tenant_id']==row['tenant_id'] and rider['campus_id']==row['campus_id'],'RIDER_SCOPE','配送员不在该校区',422)
            c.execute("UPDATE delivery_tasks SET state='OFFERED',rider_id=?,offer_deadline=?,updated_at=? WHERE order_id=?",(rider['id'],now()+120,now(),oid))
            reason=f"指派给{rider['display_name']}，等待本人确认"
        else:
            must(task['state'] in ('OFFERED','ASSIGNED'),'STATE','当前任务不能回收')
            must(reason and data.get('confirmed_not_picked_up'),'HANDOFF_CHECK','请记录原因并确认尚未发生实体取餐',422)
            c.execute("UPDATE delivery_tasks SET state='WAITING',rider_id=NULL,offer_deadline=NULL,updated_at=? WHERE order_id=?",(now(),oid))
    elif action=='confirm':
        role(user,'student')
        must(state=='DELIVERED','STATE','配送员确认送达后才可确认收餐')
        c.execute("UPDATE orders SET status='COMPLETED' WHERE id=?",(oid,))
    elif action=='request_refund':
        role(user,'student')
        must(state in ('PREPARING','READY','PICKED_UP','DELIVERED','COMPLETED') and row['payment_status']=='PAID' and row['refund_status'] in ('NONE','REJECTED'),'REFUND_STAGE','当前订单不可重复申请售后')
        must(bool(reason),'REASON','请填写售后原因',422)
        c.execute("UPDATE orders SET refund_status='REQUESTED' WHERE id=?",(oid,))
    elif action in ('approve_refund','reject_refund'):
        role(user,'admin','school_admin')
        must(row['refund_status']=='REQUESTED','REFUND_STATE','没有待处理售后')
        must(bool(reason),'REASON','请填写处理说明',422)
        if action=='approve_refund':
            refund(c,row,reason)
            if state in ('PREPARING','READY'):
                c.execute("UPDATE orders SET status='CANCELED' WHERE id=?",(oid,))
                c.execute("UPDATE delivery_tasks SET state='CANCELED',rider_id=NULL,offer_deadline=NULL,updated_at=? WHERE order_id=?",(now(),oid))
        else:
            c.execute("UPDATE orders SET refund_status='REJECTED' WHERE id=?",(oid,))
    else:
        fail('ACTION','不支持的操作',422)
    c.execute('UPDATE orders SET version=version+1,updated_at=? WHERE id=?',(now(),oid))
    event(c,oid,user,action,reason)
    audit(c,user,oid,action,reason)
    # A declined/requeued rider loses access immediately, so return only a receipt.
    updated=order_row(c,oid)
    return serialize_order(c,user,updated) if can_view(c,user,updated) else {'id':oid,'updated':True}
