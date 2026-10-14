import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from fastapi.testclient import TestClient
from app.main import create_app
from app.domain import now


class CampusFlows(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.path=Path(self.temp.name)/'test.sqlite3'
        self.app=create_app(self.path)
        self.db=self.app.state.db
        self.clients={}

    def tearDown(self):
        for c in self.clients.values():c.close()
        self.temp.cleanup()

    def client(self,name):
        if name not in self.clients:
            c=TestClient(self.app)
            r=c.post('/api/login',json={'username':name,'password':'demo12345'})
            self.assertEqual(r.status_code,200,r.text)
            self.clients[name]=c
        return self.clients[name]

    def body(self,**overrides):
        value={'merchant_id':1,'address':{'building_id':1,'floor':3,'room':'301','alias':'演示测试同学','accept_lobby':False},'items':[{'sku_id':1,'quantity':1,'options':['plain','egg']}],'note':'演示测试，不是真实订单'}
        value.update(overrides)
        return value

    def quote(self,body=None,who='student'):
        r=self.client(who).post('/api/quotes',json=body or self.body())
        self.assertEqual(r.status_code,200,r.text)
        return r.json()

    def create(self,body=None,key='test-order-key-0001',who='student'):
        q=self.quote(body,who)
        r=self.client(who).post('/api/orders',json={'quote_id':q['id']},headers={'Idempotency-Key':key})
        self.assertEqual(r.status_code,200,r.text)
        return r.json()

    def get(self,oid,who='student'):
        r=self.client(who).get('/api/orders/'+oid)
        self.assertEqual(r.status_code,200,r.text)
        return r.json()

    def pay(self,order,who='student'):
        r=self.client(who).post('/api/orders/'+order['id']+'/simulate-payment',json={'event_key':'event-'+order['id'],'amount_cents':order['total_cents']})
        self.assertEqual(r.status_code,200,r.text)
        return r.json()

    def act(self,oid,who,action,**extra):
        order=self.get(oid,who)
        r=self.client(who).post('/api/orders/'+oid+'/actions',json={'action':action,'version':order['version'],**extra})
        self.assertEqual(r.status_code,200,r.text)
        return r.json()

    def ready(self):
        o=self.pay(self.create())
        self.act(o['id'],'merchant','accept')
        return self.act(o['id'],'merchant','ready')

    def test_full_delivery_and_persistence(self):
        o=self.ready();oid=o['id']
        self.assertEqual(o['total_cents'],1900)
        self.assertNotIn('room',o['snapshot']['address'])
        queue=self.get(oid,'rider')
        self.assertNotIn('room',queue['snapshot']['address'])
        claimed=self.act(oid,'rider','claim')
        self.assertEqual(claimed['snapshot']['address']['room'],'301')
        self.act(oid,'rider','pickup')
        self.act(oid,'rider','deliver',confirmed_point='送到寝室')
        completed=self.act(oid,'student','confirm')
        self.assertEqual(completed['status'],'COMPLETED')
        self.assertNotIn('room',self.get(oid,'rider')['snapshot']['address'])
        reopened=TestClient(create_app(self.path))
        reopened.post('/api/login',json={'username':'student','password':'demo12345'})
        self.assertEqual(reopened.get('/api/orders/'+oid).json()['status'],'COMPLETED')
        reopened.close()
        with self.db.connect() as c:
            self.assertEqual(c.execute('SELECT stock FROM skus WHERE id=1').fetchone()[0],29)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM payments').fetchone()[0],1)

    def test_idempotent_create_and_payment(self):
        q=self.quote();student=self.client('student');body={'quote_id':q['id']};headers={'Idempotency-Key':'repeat-create-key'}
        def run():return student.post('/api/orders',json=body,headers=headers)
        with ThreadPoolExecutor(max_workers=2) as pool: responses=list(pool.map(lambda _:run(),range(2)))
        self.assertTrue(all(r.status_code==200 for r in responses),[r.text for r in responses])
        self.assertEqual(responses[0].json()['id'],responses[1].json()['id'])
        o=responses[0].json();first=self.pay(o);second=self.pay(o)
        self.assertEqual(first['version'],second['version'])
        another=self.quote()
        conflict=student.post('/api/orders',json={'quote_id':another['id']},headers=headers)
        self.assertEqual(conflict.status_code,409)
        with self.db.connect() as c:
            self.assertEqual(c.execute('SELECT stock FROM skus WHERE id=1').fetchone()[0],29)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM orders').fetchone()[0],1)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM payments').fetchone()[0],1)

    def test_race_one_rider_only(self):
        o=self.ready();r1=self.client('rider');r2=self.client('rider_b')
        def claim(client):return client.post('/api/orders/'+o['id']+'/actions',json={'action':'claim','version':o['version']})
        with ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(claim,[r1,r2]))
        self.assertEqual(sorted(r.status_code for r in results),[200,404])
        with self.db.connect() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM events WHERE action='claim'").fetchone()[0],1)

    def test_permissions_and_role_injection(self):
        o=self.create();oid=o['id']
        for who in ('student_b','student2','merchant_b','merchant2','rider2','schoolops2'):
            self.assertEqual(self.client(who).get('/api/orders/'+oid).status_code,404,who)
            self.assertNotIn(oid,json.dumps(self.client(who).get('/api/orders').json()))
        self.assertEqual(self.client('student').get('/api/admin').status_code,403)
        self.assertEqual(self.client('student').post('/api/orders/'+oid+'/actions',json={'action':'accept','version':o['version']}).status_code,403)
        self.assertEqual(self.client('student').get('/api/catalog?campus_id=4').status_code,403)
        self.assertEqual(self.client('student').post('/api/login',json={'username':'student','password':'demo12345','role':'admin'}).status_code,422)

    def test_stock_no_oversell_or_partial_reservation(self):
        with self.db.connect(True) as c:c.execute('UPDATE skus SET stock=1 WHERE id=1')
        q1=self.quote();q2=self.quote(who='student_b')
        def buy(args):
            who,q=args
            return self.client(who).post('/api/orders',json={'quote_id':q['id']},headers={'Idempotency-Key':'last-one-stock'})
        with ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(buy,[('student',q1),('student_b',q2)]))
        self.assertEqual(sorted(r.status_code for r in results),[200,409])
        with self.db.connect() as c:
            self.assertEqual(c.execute('SELECT stock FROM skus WHERE id=1').fetchone()[0],0)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM orders').fetchone()[0],1)

    def test_quote_tampering_changed_price_and_scope(self):
        student=self.client('student')
        tampered=self.body();tampered['total_cents']=1
        self.assertEqual(student.post('/api/quotes',json=tampered).status_code,422)
        bad=self.body(items=[{'sku_id':6,'quantity':1,'options':['plain']}])
        self.assertEqual(student.post('/api/quotes',json=bad).status_code,422)
        for options in ([],['unknown'],['plain','hot'],['plain','plain']):
            self.assertEqual(student.post('/api/quotes',json=self.body(items=[{'sku_id':1,'quantity':1,'options':options}])).status_code,422)
        q=self.quote()
        with self.db.connect(True) as c:c.execute('UPDATE skus SET price_cents=1500,version=version+1 WHERE id=1')
        response=student.post('/api/orders',json={'quote_id':q['id']},headers={'Idempotency-Key':'changed-price-key'})
        self.assertEqual(response.json()['detail']['code'],'QUOTE_CHANGED')

    def test_building_rules_and_quote_policy_version(self):
        body=self.body();body['address']['building_id']=2
        self.assertEqual(self.client('student').post('/api/quotes',json=body).json()['detail']['code'],'LOBBY_CONSENT')
        body['address']['accept_lobby']=True
        self.assertEqual(self.quote(body)['snapshot']['address']['mode'],'LOBBY')
        body['address']['building_id']=3
        self.assertEqual(self.client('student').post('/api/quotes',json=body).status_code,409)
        body['address']['building_id']=1;body['address']['floor']=7
        self.assertEqual(self.client('student').post('/api/quotes',json=body).status_code,422)
        q=self.quote()
        self.client('admin').put('/api/admin/buildings/1',json={'mode':'LOBBY','active':True,'max_floor':6,'version':1})
        r=self.client('student').post('/api/orders',json={'quote_id':q['id']},headers={'Idempotency-Key':'old-rule-quote'})
        self.assertIn(r.status_code,(409,422))

    def test_cancel_and_reject_refund_once(self):
        o=self.pay(self.create())
        denied=self.act(o['id'],'merchant','reject',reason='演示缺货，无法制作')
        self.assertEqual(denied['status'],'REJECTED');self.assertEqual(denied['payment_status'],'REFUNDED')
        self.assertEqual(self.pay(o)['payment_status'],'REFUNDED')
        repeat=self.client('merchant').post('/api/orders/'+o['id']+'/actions',json={'action':'reject','version':denied['version'],'reason':'再次点击'})
        self.assertEqual(repeat.status_code,409)
        with self.db.connect() as c:
            self.assertEqual(c.execute('SELECT stock FROM skus WHERE id=1').fetchone()[0],30)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM refunds').fetchone()[0],1)

    def test_preparing_refund_freezes_then_no_restock(self):
        o=self.pay(self.create());self.act(o['id'],'merchant','accept')
        requested=self.act(o['id'],'student','request_refund',reason='演示售后申请')
        frozen=self.client('merchant').post('/api/orders/'+o['id']+'/actions',json={'action':'ready','version':requested['version']})
        self.assertEqual(frozen.status_code,409)
        refunded=self.act(o['id'],'admin','approve_refund',reason='演示核实后同意')
        self.assertEqual(refunded['status'],'CANCELED')
        with self.db.connect() as c:self.assertEqual(c.execute('SELECT stock FROM skus WHERE id=1').fetchone()[0],29)

    def test_assign_reclaim_and_late_pickup_denied(self):
        o=self.ready();oid=o['id'];rid=self.client('rider').get('/api/me').json()['id']
        self.act(oid,'admin','assign',rider_id=rid)
        self.assertNotIn('room',self.get(oid,'rider')['snapshot']['address'])
        self.act(oid,'rider','accept_offer')
        self.act(oid,'admin','requeue',reason='已确认骑手尚未取餐',confirmed_not_picked_up=True)
        self.assertNotIn('room',self.get(oid,'rider')['snapshot']['address'])
        current=self.get(oid,'rider')
        self.assertEqual(self.client('rider').post('/api/orders/'+oid+'/actions',json={'action':'pickup','version':current['version']}).status_code,403)
        self.act(oid,'rider_b','claim');self.act(oid,'rider_b','pickup')
        current=self.get(oid,'admin')
        self.assertEqual(self.client('admin').post('/api/orders/'+oid+'/actions',json={'action':'requeue','version':current['version'],'reason':'错误回收','confirmed_not_picked_up':True}).status_code,409)

    def test_timeout_and_expired_offer(self):
        o=self.create()
        with self.db.connect(True) as c:c.execute('UPDATE orders SET payment_deadline=? WHERE id=?',(now()-1,o['id']))
        self.assertEqual(self.get(o['id'])['status'],'CANCELED')
        with self.db.connect() as c:self.assertEqual(c.execute('SELECT stock FROM skus WHERE id=1').fetchone()[0],30)
        o=self.pay(self.create(key='next-after-expiry'));self.act(o['id'],'merchant','accept');self.act(o['id'],'merchant','ready')
        rid=self.client('rider').get('/api/me').json()['id'];self.act(o['id'],'admin','assign',rider_id=rid)
        with self.db.connect(True) as c:c.execute('UPDATE delivery_tasks SET offer_deadline=? WHERE order_id=?',(now()-1,o['id']))
        self.assertEqual(self.get(o['id'],'admin')['delivery']['state'],'WAITING')

    def test_invalid_state_and_wrong_payment_amount(self):
        o=self.create();oid=o['id']
        self.assertEqual(self.client('student').post('/api/orders/'+oid+'/simulate-payment',json={'event_key':'wrong-amount-key','amount_cents':1}).status_code,422)
        self.assertEqual(self.client('merchant').post('/api/orders/'+oid+'/actions',json={'action':'ready','version':o['version']}).status_code,409)
        self.assertEqual(self.client('student').post('/api/orders/'+oid+'/actions',json={'action':'confirm','version':o['version']}).status_code,409)
        self.assertEqual(self.client('student').post('/api/quotes',json=self.body(items=[{'sku_id':1,'quantity':1.5,'options':['plain']}])).status_code,422)

    def test_onboarding_approval_creates_scoped_merchant(self):
        applicant=self.client('applicant')
        r=applicant.post('/api/merchant/apply',json={'canteen_id':1,'name':'演示新档口','description':'用于验证审核流程'})
        self.assertEqual(r.status_code,200,r.text);mid=r.json()['id']
        data={'name':'新菜品','description':'演示菜','category':'主食','label':'一份','price_cents':1200,'box_cents':100,'stock':10}
        self.assertEqual(applicant.post('/api/merchant/products',json=data).status_code,403)
        self.assertEqual(self.client('schoolops2').post(f'/api/admin/merchants/{mid}/review',json={'approve':True,'note':'越权审核'}).status_code,404)
        self.assertEqual(self.client('admin').post(f'/api/admin/merchants/{mid}/review',json={'approve':True,'note':'演示资料已确认'}).status_code,200)
        self.assertEqual(applicant.get('/api/me').json()['role'],'merchant')
        self.assertEqual(applicant.post('/api/merchant/products',json=data).status_code,200)
        self.assertEqual(applicant.put('/api/merchant/skus/1',json={**data,'version':1}).status_code,404)

    def test_origin_session_and_school_pause(self):
        student=self.client('student')
        self.assertEqual(student.post('/api/quotes',json=self.body(),headers={'Origin':'https://example.org'}).status_code,403)
        self.assertEqual(student.get('/api/health',headers={'Host':'malicious.example'}).status_code,403)
        self.client('admin').post('/api/admin/schools/1/state',json={'enabled':False})
        self.assertEqual(student.post('/api/quotes',json=self.body()).json()['detail']['code'],'NOT_OPEN')
        self.assertEqual(student.post('/api/admin/schools',json={'name':'测试学校','campus_name':'演示校区'}).status_code,403)
        student.post('/api/logout')
        self.assertEqual(student.get('/api/orders').status_code,401)

    def test_inventory_edit_cannot_overwrite_reservation(self):
        merchant=self.client('merchant')
        product=merchant.get('/api/merchant').json()['products'][0]
        sku=product['skus'][0]
        q1=self.quote();q2=self.quote(who='student_b')
        self.client('student').post('/api/orders',json={'quote_id':q1['id']},headers={'Idempotency-Key':'inventory-race-first'})
        body={'name':product['name'],'description':product['description'],'category':product['category'],'label':sku['label'],'price_cents':sku['price_cents'],'box_cents':sku['box_cents'],'stock':30,'version':sku['version']}
        self.assertEqual(merchant.put('/api/merchant/skus/1',json=body).json()['detail']['code'],'STALE_VERSION')
        # Another valid quote is not invalidated solely by a stock reservation.
        second=self.client('student_b').post('/api/orders',json={'quote_id':q2['id']},headers={'Idempotency-Key':'inventory-race-second'})
        self.assertEqual(second.status_code,200,second.text)
        with self.db.connect() as c:self.assertEqual(c.execute('SELECT stock FROM skus WHERE id=1').fetchone()[0],28)

    def test_picked_up_refund_does_not_fake_delivery_or_restore_food(self):
        o=self.ready();oid=o['id'];self.act(oid,'rider','claim');self.act(oid,'rider','pickup')
        self.act(oid,'student','request_refund',reason='配送途中演示售后')
        refunded=self.act(oid,'admin','approve_refund',reason='模拟全额退款，餐品继续交付')
        self.assertEqual(refunded['status'],'PICKED_UP')
        self.assertEqual(refunded['payment_status'],'REFUNDED')
        delivered=self.act(oid,'rider','deliver',confirmed_point='送到寝室')
        self.assertEqual(delivered['status'],'DELIVERED')
        with self.db.connect() as c:self.assertEqual(c.execute('SELECT stock FROM skus WHERE id=1').fetchone()[0],29)


if __name__=='__main__':
    unittest.main(verbosity=2)
