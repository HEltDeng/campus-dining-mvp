"""Explicitly create one LOCAL_DEMO order through the running loopback HTTP API."""
import json
import uuid
from pathlib import Path
import httpx

ROOT=Path(__file__).resolve().parents[1]
URL='http://127.0.0.1:8876'
clients={}
calls=[]

def call(who,method,path,body=None,headers=None):
    if who not in clients:
        c=httpx.Client(base_url=URL,timeout=15)
        r=c.post('/api/login',json={'username':who,'password':'demo12345'})
        r.raise_for_status()
        clients[who]=c
    r=clients[who].request(method,'/api'+path,json=body,headers=headers)
    calls.append({'role':who,'method':method,'path':path,'status':r.status_code})
    r.raise_for_status()
    return r.json()

try:
    health=httpx.get(URL+'/api/health',timeout=5).json()
    assert health['mode']=='LOCAL_DEMO' and health['real_transactions'] is False
    quote=call('student','POST','/quotes',{'merchant_id':1,'address':{'building_id':1,'floor':2,'room':'202','alias':'API演示同学','accept_lobby':False},'items':[{'sku_id':3,'quantity':1,'options':['plain']}],'note':'本地 HTTP 验收演示'})
    key='live-'+uuid.uuid4().hex
    o=call('student','POST','/orders',{'quote_id':quote['id']},{'Idempotency-Key':key})
    oid=o['id']
    replay=call('student','POST','/orders',{'quote_id':quote['id']},{'Idempotency-Key':key})
    assert replay['id']==oid
    pay={'event_key':key,'amount_cents':o['total_cents']}
    o=call('student','POST',f'/orders/{oid}/simulate-payment',pay)
    assert call('student','POST',f'/orders/{oid}/simulate-payment',pay)['version']==o['version']
    for who,action in [('merchant','accept'),('merchant','ready'),('rider_b','claim'),('rider_b','pickup'),('rider_b','deliver'),('student','confirm')]:
        current=call(who,'GET',f'/orders/{oid}')
        body={'action':action,'version':current['version']}
        if action=='deliver':body['confirmed_point']='送到寝室'
        o=call(who,'POST',f'/orders/{oid}/actions',body)
    assert o['status']=='COMPLETED'
    call('student2','GET','/me')
    denial=clients['student2'].get('/api/orders/'+oid)
    assert denial.status_code==404
    report={'date':'2026-10-13 Asia/Singapore','status':'PASS','base_url':URL,'order_id':oid,'final_status':o['status'],'total_cents':o['total_cents'],'payment_adapter':'LOCAL_DEMO','real_transactions':False,'cross_tenant_order_read_status':denial.status_code,'idempotency_and_duplicate_payment':'PASS','calls':calls}
    (ROOT/'docs/evidence/live-api.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n','utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='calls'},ensure_ascii=False))
finally:
    for c in clients.values():c.close()
