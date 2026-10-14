const $ = (q, el=document) => el.querySelector(q);
const esc = value => String(value ?? '').replace(/[&<>"']/g, x=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[x]));
const money = cents => `¥${(Number(cents||0)/100).toFixed(2)}`;
const stateName = {UNPAID:'待模拟支付',PAID:'等待商家接单',PREPARING:'商家备餐中',READY:'已出餐 · 待取餐',PICKED_UP:'配送中',DELIVERED:'已送达 · 待确认',COMPLETED:'已完成',CANCELED:'已取消',REJECTED:'商家已拒单'};
const taskName = {WAITING:'等待配送',OFFERED:'已派单 · 待确认',ASSIGNED:'配送员已接单',PICKED_UP:'已取餐',DELIVERED:'已送达',CANCELED:'已取消'};
const roleName = {student:'学生',merchant:'商家',admin:'平台管理',school_admin:'学校运营',rider:'配送员',applicant:'商家入驻'};
const actionName = {created:'创建测试订单',paid:'模拟支付',accept:'商家接单',reject:'商家拒单',ready:'商家出餐',claim:'配送员抢单',assign:'运营派单',accept_offer:'接受派单',decline_offer:'拒绝邀约',requeue:'任务回收',pickup:'确认取餐',deliver:'确认送达',confirm:'学生确认收餐',cancel:'学生取消',request_refund:'申请售后',approve_refund:'同意并模拟退款',reject_refund:'驳回售后',expired:'付款超时',offer_expired:'邀约超时'};
const state = {user:null,meta:null,catalog:null,orders:[],merchant:null,admin:null,view:'menu',mid:1,category:'全部',cart:[],quote:null,product:null,action:null,filter:'全部',busy:false};
let toastTimer;

async function api(path, options={}) {
  const response = await fetch(`/api${path}`, {credentials:'same-origin',...options,headers:{'Content-Type':'application/json',...(options.headers||{})},body:options.body === undefined ? undefined : JSON.stringify(options.body)});
  const data = await response.json();
  if (!response.ok) {
    let msg = data.detail?.message || (Array.isArray(data.detail)?data.detail.map(x=>`${x.loc.slice(1).join('.')}: ${x.msg}`).join('；'):data.detail) || '操作未完成，请重试';
    const error = new Error(msg); error.status=response.status; error.code=data.detail?.code; throw error;
  }
  return data;
}
function post(path,body={},headers={}) { return api(path,{method:'POST',body,headers}); }
function toast(message) { const el=$('#toast');el.textContent=message;el.classList.add('show');clearTimeout(toastTimer);toastTimer=setTimeout(()=>el.classList.remove('show'),4000); }
function showError(error, form) { if (form && $('.form-error',form)) $('.form-error',form).textContent=error.message; else toast(error.message); }
function pill(text,type='') {return `<span class="pill ${type}">${esc(text)}</span>`;}
function empty(title,copy) {return `<div class="empty"><h3>${esc(title)}</h3><p>${esc(copy)}</p></div>`;}
function btn(text,cmd,extra='',style='secondary') { return `<button class="btn ${style}" data-cmd="${cmd}" ${extra}>${esc(text)}</button>`; }
function modal(title,body,wide=false) { $('#modal-root').innerHTML=`<div class="modal-backdrop"><section class="modal ${wide?'wide':''}" role="dialog" aria-modal="true" aria-label="${esc(title)}"><div class="modal-head"><h2>${esc(title)}</h2><button class="close" data-cmd="close" aria-label="关闭">×</button></div>${body}</section></div>`;setTimeout(()=>$('#modal-root input, #modal-root select, #modal-root button')?.focus(),0); }
function closeModal() { $('#modal-root').innerHTML=''; }
function today() {return new Date().toLocaleDateString('zh-CN',{month:'long',day:'numeric',weekday:'long'});}
function clock(ts) {return new Date(ts*1000).toLocaleString('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'});}
function persistCart() { if(state.user) sessionStorage.setItem(`hefan-cart-${state.user.id}`,JSON.stringify(state.cart)); }
function cents(value) {const text=String(value).trim();if(!/^\d+(\.\d{1,2})?$/.test(text))throw new Error('金额最多保留两位小数');const [a,b='']=text.split('.');return Number(a)*100+Number(b.padEnd(2,'0'));}

function loginPage(selected='student') {
 const cards=[['student','学生点餐','选餐、下单、查看配送'],['merchant','商家工作台','接单、出餐、菜单管理'],['rider','配送工作台','接任务、取餐、送达'],['admin','平台管理','入驻审核、派单、售后']];
 $('#app').innerHTML=`<header class="app-header"><div class="brand"><img src="/assets/mark.svg" alt="禾饭标志"><div><b>禾饭</b><small>CAMPUS DINING</small></div></div>${pill('本地体验 · v0.1','green')}</header><main class="login-layout"><section class="login-intro"><div class="eyebrow">A WARM MEAL, A LITTLE CLOSER</div><h1>食堂的热乎，<br>送到寝室门口。</h1><p>从点餐到送达，让校园里的一餐有序发生。选择一个演示角色，体验完整的订单旅程。</p><div class="login-illustration"><img src="/assets/meal.svg" alt="饭碗插画"></div><div class="hero-tags">${pill('多学校隔离')}${pill('食堂档口出餐')}${pill('配送规则可配置')}</div></section><section class="login-card"><h2>进入演示工作台</h2><p>所有角色使用本机数据库。订单与金额均为演示记录。</p><div class="role-grid">${cards.map(([u,n,d])=>`<button class="role-card ${selected===u?'active':''}" data-cmd="select-login" data-user="${u}"><b>${n}</b><small>${d}</small></button>`).join('')}</div><form id="login-form"><div class="field"><label for="login-user">演示账号</label><select id="login-user" name="username">${state.meta.accounts.map(a=>`<option value="${esc(a.username)}" ${selected===a.username?'selected':''}>${esc(a.username)} · ${esc(a.display_name)}</option>`).join('')}</select></div><div class="field"><label for="login-password">演示密码</label><input id="login-password" name="password" type="password" value="demo12345" autocomplete="current-password" required></div><div class="form-error" role="alert"></div><button class="btn wide" type="submit">进入工作台 <span aria-hidden="true">↗</span></button></form><div class="login-note">统一演示密码：<b>demo12345</b><br>雅安校区为试点场景草案；食堂、楼栋、菜单均为演示数据，未开通实际运营。</div></section></main>`;
}

function navigation() {
 const role=state.user.role;
 if(role==='student')return [['menu','食堂点餐'],['orders','我的订单']];
 if(role==='merchant')return [['orders','接单工作台'],['products','菜单与库存']];
 if(role==='rider')return [['orders','配送工作台']];
 if(role==='applicant')return [['apply','档口入驻']];
 return [['orders','订单与调度'],['applications','商家入驻'],['buildings','配送规则'],['schools','学校管理']];
}
function shell(content) {
 const user=state.user;
 $('#app').innerHTML=`<header class="app-header"><div class="brand"><img src="/assets/mark.svg" alt=""><div><b>禾饭</b><small>CAMPUS DINING</small></div></div><nav class="header-nav" aria-label="主导航">${navigation().map(([v,n])=>`<button class="nav-link ${state.view===v?'active':''}" data-cmd="nav" data-view="${v}">${n}</button>`).join('')}</nav><div class="account"><div class="avatar">${esc(roleName[user.role].slice(0,2))}</div><div class="account-name"><b>${esc(user.display_name)}</b><small>${esc(user.username)} · ${roleName[user.role]}</small></div><button class="link-button" data-cmd="logout">切换角色</button></div></header><main class="main">${content}<footer class="page-footer">禾饭 · 校园食堂到寝室 &nbsp;/&nbsp; 本地演示 MVP · 模拟支付 · 不调用美团业务接口</footer></main>`;
}
function render() {
 if(!state.user)return loginPage();
 if(state.view==='menu')shell(studentMenu());
 else if(state.view==='orders')shell(workspace());
 else if(state.view==='products')shell(productsAdmin());
 else if(state.view==='applications')shell(applications());
 else if(state.view==='buildings')shell(buildingsAdmin());
 else if(state.view==='schools')shell(schoolsAdmin());
 else shell(applyPage());
}

async function hydrate(reset=false) {
 const previousId=state.user?.id;
 state.user=await api('/me');
 if(previousId&&previousId!==state.user.id)reset=true;
 const role=state.user.role;
 if(reset){state.view=navigation()[0][0];state.filter='全部';state.cart=JSON.parse(sessionStorage.getItem(`hefan-cart-${state.user.id}`)||'[]');}
 if(role==='student'){
   [state.catalog,state.orders]=await Promise.all([api('/catalog'),api('/orders')]);
   if(!state.catalog.merchants.some(x=>x.id===state.mid))state.mid=state.catalog.merchants[0]?.id;
 }else if(role==='merchant'||role==='applicant'){
   [state.merchant,state.orders]=await Promise.all([api('/merchant'),api('/orders')]);
 }else if(role==='rider')state.orders=await api('/orders');
 else [state.admin,state.orders]=await Promise.all([api('/admin'),api('/orders')]);
 render();
}

function currentShop(){return state.catalog?.merchants.find(x=>x.id===state.mid);}
function studentMenu() {
 const shop=currentShop();
 const cats=['全部',...new Set((shop?.products||[]).map(x=>x.category))];
 const products=(shop?.products||[]).filter(x=>state.category==='全部'||x.category===state.category);
 const school=state.meta.schools.find(x=>x.id===state.user.tenant_id);
 return `<div class="location-row"><span>当前学校</span><select aria-label="选择学校" id="school-select">${state.meta.schools.map(x=>`<option value="${x.id}" ${x.id===state.user.tenant_id?'selected':''}>${esc(x.name)}</option>`).join('')}</select><span>/</span><select aria-label="选择校区" id="campus-select">${state.meta.campuses.filter(x=>x.tenant_id===state.user.tenant_id).map(x=>`<option value="${x.id}" ${x.id===state.user.campus_id?'selected':''} ${x.active?'':'disabled'}>${esc(x.name)}${x.active?'':' · 暂未开放'}</option>`).join('')}</select><span class="right">${today()}</span></div><section class="hero"><div><div class="eyebrow">FROM CANTEEN TO YOUR DOOR</div><h1>好好吃饭，<br>其余的交给我们。</h1><p>逛逛今天的食堂，挑一份喜欢的热饭。<br>按楼栋规则，送到约定的交付点。</p><div class="hero-tags">${pill('食堂取餐')}${pill('寝室配送')}${pill('全程状态可见')}</div></div><img class="hero-art" src="/assets/meal.svg" alt="现做饭碗插画"></section><div class="content-grid"><section><div class="section-heading"><div><h2>今天想吃什么</h2><p>${esc(school?.name)} · ${state.catalog.merchants.length} 个演示档口</p></div>${pill('演示菜单','orange')}</div><div class="merchant-tabs">${state.catalog.merchants.map((m,i)=>`<button class="merchant-tab ${m.id===state.mid?'active':''}" data-cmd="shop" data-id="${m.id}"><span class="shop-icon" aria-hidden="true">${i===0?'禾':'麦'}</span><span><b>${esc(m.name)}</b><small>${esc(m.canteen_name)} · 配送 ${money(m.delivery_cents)}</small></span>${m.status==='PAUSED'?pill('休息'):''}</button>`).join('')}</div><div class="filters">${cats.map(c=>`<button class="filter ${c===state.category?'active':''}" data-cmd="category" data-category="${esc(c)}">${esc(c)}</button>`).join('')}</div><div class="products">${products.map(p=>productCard(p,shop)).join('')}</div>${!products.length?empty('这里还没有菜单','选择其他档口，或请商家完善演示菜单。'):''}</section><aside id="cart" class="cart">${cartView()}</aside></div>${state.cart.length?`<button class="mobile-cart" data-cmd="scroll-cart">购物车 · ${state.cart.reduce((n,x)=>n+x.quantity,0)} 份</button>`:''}`;
}
function productCard(product,shop) {
 const available=product.active&&product.skus.some(x=>x.stock>0)&&shop.status==='OPEN';
 const low=Math.min(...product.skus.map(x=>x.price_cents));
 return `<article class="product"><div class="product-art ${esc(product.art)}"><img src="/assets/meal.svg" alt="${esc(product.name)}示意插画"><span class="art-tag">${esc(product.category)} · 示意图</span></div><div class="product-body"><h3>${esc(product.name)}</h3><p>${esc(product.description)}</p><div class="product-bottom"><span class="price">${money(low)} <small>起</small></span><button class="btn small ${available?'':'secondary'}" data-cmd="product" data-id="${product.id}" ${available?'':'disabled'}>${available?'选规格 ＋':(!product.active?'已下架':shop.status!=='OPEN'?'休息中':'已售罄')}</button></div></div></article>`;
}
function cartView() {
 const subtotal=state.cart.reduce((sum,x)=>sum+x.unit_cents*x.quantity,0);
 return `<div class="cart-title"><h3>我的餐袋</h3>${pill(`${state.cart.reduce((sum,x)=>sum+x.quantity,0)} 份`)}</div>${state.cart.length?`${state.cart.map((x,i)=>`<div class="cart-line"><h4>${esc(x.name)}</h4><small>${esc(x.label)}${x.option_names.length?' · '+esc(x.option_names.join(' / ')):''}</small><div class="line-end"><b>${money(x.unit_cents*x.quantity)}</b><div class="stepper"><button data-cmd="qty" data-i="${i}" data-delta="-1" aria-label="减少${esc(x.name)}">−</button><span>${x.quantity}</span><button data-cmd="qty" data-i="${i}" data-delta="1" aria-label="增加${esc(x.name)}">＋</button></div></div></div>`).join('')}<div class="cart-summary"><span class="muted">商品预估</span><span class="price">${money(subtotal)}</span></div><div class="subtotal-note">餐盒费、配送费由服务器核算后展示。</div><button class="btn wide" data-cmd="address">填写配送信息 →</button>`:`<div class="cart-empty"><div class="empty-bowl" aria-hidden="true">♧</div><b>餐袋还空着</b><p class="tiny">选一份热饭，开启今天的一餐</p></div><button class="btn secondary wide" disabled>先去选餐吧</button>`}<div class="cart-foot">本地演示 · 创建测试订单 · 不会扣款</div>`;
}

function productModal(id) {
 const product=currentShop().products.find(x=>x.id===id);state.product=product;
 const first=product.skus.find(x=>x.stock>0);
 modal(product.name,`<p class="muted">${esc(product.description)}</p><form id="product-form"><div class="option-title">份量 <small>必选 1 项</small></div><div class="option-grid">${product.skus.map(s=>`<label class="option-label"><input type="radio" name="sku" value="${s.id}" ${s.id===first?.id?'checked':''} ${s.stock<=0?'disabled':''}><span>${esc(s.label)} · ${money(s.price_cents)}<br><small class="muted">可售 ${s.stock} 份</small></span></label>`).join('')}</div>${product.options.map(g=>`<div class="option-title">${esc(g.name)} <small>${g.min?`至少 ${g.min} 项`:'可不选'}，最多 ${g.max} 项</small></div><div class="option-grid">${g.choices.map((o,i)=>`<label class="option-label"><input type="${g.max===1?'radio':'checkbox'}" name="opt-${esc(g.id)}" value="${esc(o.id)}" ${g.min&&i===0?'checked':''}><span>${esc(o.name)}${o.cents?' +'+money(o.cents):''}</span></label>`).join('')}</div>`).join('')}<div class="option-title">数量</div><input name="quantity" type="number" min="1" max="20" value="1" required aria-label="购买数量"><div class="form-error" role="alert"></div><div class="modal-footer"><span id="option-price" class="price">${money(first?.price_cents)}</span><button class="btn" type="submit">加入餐袋 ＋</button></div></form>`);
}
function readProduct(form) {
 const data=new FormData(form),sku=state.product.skus.find(x=>x.id===Number(data.get('sku')));
 if(!sku)throw new Error('请选择有库存的规格');
 const options=state.product.options.flatMap(g=>{
   const ids=data.getAll(`opt-${g.id}`);if(ids.length<g.min||ids.length>g.max)throw new Error(`请按要求选择${g.name}`);
   return g.choices.filter(o=>ids.includes(o.id));
 });
 return {sku,options,quantity:Number(data.get('quantity')),price:sku.price_cents+options.reduce((n,o)=>n+o.cents,0)};
}
function addressModal() {
 const shop=state.catalog.merchants.find(x=>x.id===state.cart[0]?.merchant_id);
 if(!shop)return toast('请选择档口商品');
 modal('这一餐，送到哪里',`<form id="address-form"><p class="muted">${esc(shop.name)} · ${esc(shop.canteen_name)}</p><div class="notice">以下为演示楼栋，不代表学校已允许上楼配送。请使用演示信息。</div><div class="form-grid"><div class="field full"><label for="building">配送楼栋</label><select id="building" name="building_id">${state.catalog.buildings.map(b=>`<option value="${b.id}" ${b.active?'':'disabled'}>${esc(b.name)} · ${b.active?(b.mode==='ROOM'?'可送到寝室':'仅楼下交付'):'未开放'}</option>`).join('')}</select></div><div class="field"><label for="floor">楼层</label><input id="floor" name="floor" type="number" min="1" max="30" value="3" required></div><div class="field"><label for="room">演示寝室号</label><input id="room" name="room" value="301" maxlength="12" pattern="[A-Za-z0-9-]+" required></div><div class="field full"><label for="alias">演示称呼</label><input id="alias" name="alias" value="演示同学" maxlength="20" required></div><div class="field full"><label for="note">给商家的备注（选填）</label><input id="note" name="note" maxlength="120" placeholder="例如：餐具一份；请勿填写手机号等真实信息"></div><div class="full" id="building-rule"></div></div><div class="form-error" role="alert"></div><div class="modal-footer"><span class="muted tiny">库存、配送范围、费用由服务器复核</span><button class="btn" type="submit">核价并确认 →</button></div></form>`,true);renderBuildingRule();
}
function renderBuildingRule(){const b=state.catalog.buildings.find(x=>x.id===Number($('#building')?.value));if(!b)return;$('#building-rule').innerHTML=b.mode==='ROOM'?`<div class="notice green">约定送到寝室 · 当前演示规则支持 1–${b.max_floor} 层</div>`:`<div class="notice"><label class="check-line"><input type="checkbox" name="accept_lobby" required><span>我明确同意在此楼栋的楼下指定点交付。本单不会显示为“送到寝室”。</span></label></div>`;}
function quoteModal() {
 const q=state.quote,s=q.snapshot,a=s.address;
 modal('确认本地测试订单',`<p><b>${esc(s.merchant_name)}</b> · ${esc(s.canteen_name)}</p><div class="notice green">${esc(a.building_name)} ${a.mode==='ROOM'?`${a.floor} 层 ${esc(a.room)} 寝室`:''}<br>${esc(a.delivery_label)} · ${esc(a.alias)}</div>${s.items.map(x=>`<div class="quote-line"><span>${esc(x.name)} × ${x.quantity}<small class="muted"> / ${esc(x.sku_label)}</small></span><b>${money(x.subtotal_cents)}</b></div>`).join('')}<div class="quote-line"><span>商品金额</span><span>${money(s.goods_cents)}</span></div><div class="quote-line"><span>餐盒费</span><span>${money(s.box_cents)}</span></div><div class="quote-line"><span>配送费</span><span>${money(s.delivery_cents)}</span></div><div class="quote-line quote-total"><span>模拟应付</span><span>${money(s.total_cents)}</span></div><div class="notice">这是本机演示订单，不会提交给真实商家。支付也仅为本地模拟。报价有效至 ${clock(q.expires_at)}。</div><div class="form-error" role="alert"></div><div class="modal-footer">${btn('返回修改','address','','secondary')}${btn('创建本地测试订单','create-order','','')}</div>`,true);
}

function workspace() {
 const role=state.user.role;
 const title=role==='student'?'我的订单':role==='merchant'?'接单工作台':role==='rider'?'配送工作台':'订单与调度';
 const subtitle=role==='student'?'从下单到送达，每一步都有记录。':role==='merchant'?`${state.merchant.merchant.name} · ${state.merchant.merchant.status==='OPEN'?'营业中':'休息中'} · 仅处理本档口订单`:role==='rider'?'同校区接单，按约定交付；取餐后不自动回收任务。':'订单状态、配送调度与售后，都在这里处理。';
 const metrics=state.admin?.metrics;
 const stats=role==='student'?[['全部订单',state.orders.length],['进行中',state.orders.filter(x=>!['COMPLETED','CANCELED','REJECTED'].includes(x.status)).length],['已完成',state.orders.filter(x=>x.status==='COMPLETED').length],['售后处理中',state.orders.filter(x=>x.refund_status==='REQUESTED').length]]:role==='merchant'?[['待接单',state.orders.filter(x=>x.status==='PAID').length],['备餐中',state.orders.filter(x=>x.status==='PREPARING').length],['待取餐',state.orders.filter(x=>x.status==='READY').length],['已完成',state.orders.filter(x=>x.status==='COMPLETED').length]]:role==='rider'?[['可接任务',state.orders.filter(x=>x.delivery?.state==='WAITING').length],['派单邀约',state.orders.filter(x=>x.delivery?.state==='OFFERED').length],['我的配送',state.orders.filter(x=>x.delivery?.rider_id===state.user.id&&['ASSIGNED','PICKED_UP'].includes(x.delivery.state)).length],['已送达',state.orders.filter(x=>x.delivery?.state==='DELIVERED').length]]:[['测试订单',metrics?.orders||0],['模拟收款',money(metrics?.paid_cents)],['模拟退款',money(metrics?.refunded_cents)],['演示净额',money(metrics?.net_cents)]];
 const filters=role==='rider'?['全部','可接任务','我的任务']:['全部','进行中','已完成','售后'];
 return `<div class="workspace-title"><div><div class="eyebrow">${today()} · ${role==='student'?'YOUR ORDERS':'WORKSPACE'}</div><h1>${title}</h1><p>${esc(subtitle)}</p></div>${btn('刷新','refresh','','outline')}</div><div class="stats">${stats.map(([label,n])=>`<div class="stat"><small>${label}</small><strong>${n}</strong></div>`).join('')}</div><div class="section-heading"><div class="filters">${filters.map(x=>`<button class="filter ${state.filter===x?'active':''}" data-cmd="order-filter" data-filter="${x}">${x}</button>`).join('')}</div>${role==='merchant'?btn(state.merchant.merchant.status==='OPEN'?'临时休息':'恢复营业','shop-state','','outline'):''}</div><div id="orders-content">${ordersView()}</div>`;
}
function ordersView(){let orders=state.orders;if(state.filter==='进行中')orders=orders.filter(x=>!['COMPLETED','CANCELED','REJECTED'].includes(x.status));if(state.filter==='已完成')orders=orders.filter(x=>x.status==='COMPLETED');if(state.filter==='售后')orders=orders.filter(x=>x.refund_status!=='NONE');if(state.filter==='可接任务')orders=orders.filter(x=>x.delivery?.state==='WAITING');if(state.filter==='我的任务')orders=orders.filter(x=>x.delivery?.rider_id===state.user.id);return orders.length?`<div class="order-list">${orders.map(orderCard).join('')}</div>`:empty('暂时没有订单','学生创建本地测试订单后，对应角色会在这里看到进度。');}
function orderActions(o) {
 const r=state.user.role,d=o.delivery,buttons=[];
 const action=(name,label,style='secondary')=>buttons.push(btn(label,'order-action',`data-id="${o.id}" data-action="${name}"`,style));
 if(r==='student'){
  if(o.status==='UNPAID')buttons.push(btn('模拟支付 · 不扣款','pay',`data-id="${o.id}"`,''));
  if(['UNPAID','PAID'].includes(o.status))action('cancel','取消测试订单');
  if(o.status==='DELIVERED')action('confirm','确认收餐','');
  if(['PREPARING','READY','PICKED_UP','DELIVERED','COMPLETED'].includes(o.status)&&o.payment_status==='PAID'&&['NONE','REJECTED'].includes(o.refund_status))action('request_refund','申请售后');
 }
 if(r==='merchant'){
  if(o.status==='PAID'){action('accept','接单并备餐','');action('reject','缺货 / 拒单','danger');}
  if(o.status==='PREPARING'&&o.refund_status!=='REQUESTED')action('ready','出餐完成','');
 }
 if(r==='rider'&&d){
  if(d.state==='WAITING')action('claim','接下这单','');
  if(d.rider_id===state.user.id&&d.state==='OFFERED'){action('accept_offer','接受派单','');action('decline_offer','暂不接单');}
  if(d.rider_id===state.user.id&&d.state==='ASSIGNED'&&o.refund_status!=='REQUESTED')action('pickup','已核对餐品 · 取餐','');
  if(d.rider_id===state.user.id&&d.state==='PICKED_UP')action('deliver','到达交付点','');
 }
 if(['admin','school_admin'].includes(r)){
  if(d?.state==='WAITING'&&o.refund_status!=='REQUESTED')action('assign','指派配送员','');
  if(['OFFERED','ASSIGNED'].includes(d?.state)&&o.refund_status!=='REQUESTED')action('requeue','回收到待接队列');
  if(o.refund_status==='REQUESTED'){action('approve_refund','同意并模拟退款','');action('reject_refund','驳回申请');}
 }
 return buttons.join('');
}
function orderCard(o) {
 const s=o.snapshot,a=s.address,progress=['PAID','PREPARING','READY','PICKED_UP','DELIVERED','COMPLETED'];
 const labels=['已付款','备餐','出餐','配送','送达','完成'];
 return `<article class="order-card"><div class="order-head"><div><h3>${esc(s.merchant_name)}</h3><small>${esc(o.id)} · ${clock(o.created_at)}</small></div><div class="badges">${pill(stateName[o.status],['COMPLETED','DELIVERED'].includes(o.status)?'green':o.status==='UNPAID'?'orange':'')}${o.delivery?pill(taskName[o.delivery.state]):''}${o.payment_status==='REFUNDED'?pill('已模拟全额退款','orange'):''}${o.refund_status==='REQUESTED'?pill('售后待处理','red'):''}${o.refund_status==='REJECTED'?pill('售后已驳回','orange'):''}</div></div><div class="order-body"><div class="order-items">${s.items.map(i=>`<p><b>${esc(i.name)}</b> × ${i.quantity}<br><small>${esc(i.sku_label)}${i.options.length?' · '+esc(i.options.map(x=>x.name).join(' / ')):''}</small></p>`).join('')}${s.note?`<p class="notice">备注：${esc(s.note)}</p>`:''}</div><div class="address-card"><b>取餐 · ${esc(s.canteen_name)}</b><p>${esc(s.pickup)}</p><br><b>送达 · ${esc(a.building_name)}</b><p>${esc(a.delivery_label)}${a.room&&a.mode==='ROOM'?` · ${a.floor} 层 ${esc(a.room)} 寝室`:''}${a.alias?' · '+esc(a.alias):''}</p>${o.delivery?.rider_name?`<p>承运：${esc(o.delivery.rider_name)}</p>`:''}${state.user.role==='rider'&&!a.room?'<p class="tiny">详细地址仅在接单成功后的必要阶段显示</p>':''}</div></div><div class="order-footer"><div>${o.total_cents!==undefined?`<small class="muted">模拟金额</small> <b class="price">${money(o.total_cents)}</b>`:`<small class="muted">演示配送费</small> <b>${money(s.delivery_cents)}</b>`}</div><div class="order-actions">${orderActions(o)}</div></div>${!['CANCELED','REJECTED','UNPAID'].includes(o.status)?`<div class="steps">${progress.map((x,i)=>`<span class="step ${i<=progress.indexOf(o.status)?'done':''}">${labels[i]}</span>`).join('')}</div>`:''}${o.events.length?`<details class="timeline"><summary>查看状态记录 · ${o.events.length} 条</summary><ul>${o.events.map(e=>`<li><time>${clock(e.created_at)}</time><b>${esc(actionName[e.action]||e.action)}</b>${e.note?' · '+esc(e.note):''}</li>`).join('')}</ul></details>`:''}</article>`;
}

function productsAdmin() {
 const products=state.merchant.products;
 return `<div class="workspace-title"><div><div class="eyebrow">MENU & INVENTORY</div><h1>菜单与库存</h1><p>可售库存不含订单已预占的份数。改价不影响历史订单。</p></div>${btn('＋ 新建商品','new-product','','')}</div><div class="table-wrap"><table class="data-table"><thead><tr><th>商品</th><th>规格</th><th>单价 / 餐盒费</th><th>可售库存</th><th>状态</th><th>操作</th></tr></thead><tbody>${products.flatMap(p=>p.skus.map(s=>`<tr><td><b>${esc(p.name)}</b><small>${esc(p.category)}</small></td><td>${esc(s.label)}</td><td>${money(s.price_cents)}<small>餐盒 ${money(s.box_cents)}</small></td><td>${s.stock} 份</td><td>${pill(p.active?'上架中':'已下架',p.active?'green':'')}</td><td>${btn('编辑','edit-product',`data-id="${s.id}"`,'small outline')}</td></tr>`)).join('')}</tbody></table></div>${!products.length?empty('先上架第一道菜','创建商品后，学生就能在本档口看到菜单。'):''}`;
}
function productEdit(sid=null){
 const p=state.merchant.products.find(x=>x.skus.some(s=>s.id===sid));const s=p?.skus.find(x=>x.id===sid);
 state.editSku=sid;
 modal(s?'编辑商品与规格':'新建商品',`<form id="product-edit-form"><div class="form-grid"><div class="field full"><label>商品名称<input name="name" value="${esc(p?.name||'')}" maxlength="40" required></label></div><div class="field full"><label>菜品描述<input name="description" value="${esc(p?.description||'')}" maxlength="150"></label></div><div class="field"><label>分类<input name="category" value="${esc(p?.category||'店长推荐')}" required></label></div><div class="field"><label>规格名称<input name="label" value="${esc(s?.label||'标准份')}" required></label></div><div class="field"><label>单价（元）<input name="price" type="number" min="0.01" max="1000" step="0.01" value="${((s?.price_cents||1200)/100).toFixed(2)}" required></label></div><div class="field"><label>餐盒费（元）<input name="box" type="number" min="0" max="50" step="0.01" value="${((s?.box_cents??100)/100).toFixed(2)}" required></label></div><div class="field"><label>可售库存（份）<input name="stock" type="number" min="0" max="10000" value="${s?.stock??20}" required></label></div><div class="field"><label>商品状态<select name="active"><option value="1" ${p?.active!==0?'selected':''}>上架</option><option value="0" ${p?.active===0?'selected':''}>下架</option></select></label></div></div><div class="notice">${s?'编辑本规格；同一商品的名称、描述和上架状态会同步到其所有规格。':'新商品先建立一个规格。预置菜品提供多规格和加料演示。'}库存调整为新的可售余量，操作会留审计记录。</div><div class="form-error" role="alert"></div><div class="modal-footer">${btn('取消','close')}<button class="btn" type="submit">保存商品</button></div></form>`,true);
}
function applications(){return `<div class="workspace-title"><div><div class="eyebrow">MERCHANT ONBOARDING</div><h1>档口入驻审核</h1><p>审核仅作用于本地演示，不代表现实学校或经营许可。</p></div>${btn('刷新','refresh','','outline')}</div>${state.admin.merchants.map(m=>`<article class="application"><div class="section-heading"><h3>${esc(m.name)}</h3>${pill({PENDING:'待审核',OPEN:'已通过 · 营业中',PAUSED:'已通过 · 休息中',REJECTED:'未通过'}[m.status],m.status==='PENDING'?'orange':m.status==='OPEN'?'green':'')}</div><small class="muted">学校租户 ${m.tenant_id} · ${esc(m.canteen_name)}</small><p>${esc(m.description)}</p>${m.review_note?`<p>审核说明：${esc(m.review_note)}</p>`:''}${m.status==='PENDING'?`<div class="order-actions">${btn('通过演示审核','review',`data-id="${m.id}" data-approve="1"`,'')}${btn('退回申请','review',`data-id="${m.id}" data-approve="0"`,'danger')}</div>`:''}</article>`).join('')}`;}
function applyPage(){const m=state.merchant.merchant;return `<div class="workspace-title"><div><div class="eyebrow">JOIN THE CAMPUS TABLE</div><h1>食堂档口入驻</h1><p>选择所属食堂并提交演示申请，等待平台审核。</p></div>${btn('刷新状态','refresh','','outline')}</div>${m?`<div class="panel"><h2>${esc(m.name)}</h2><div class="chips">${pill({PENDING:'申请已提交 · 等待审核',REJECTED:'申请未通过',OPEN:'审核已通过'}[m.status]||m.status,'orange')}</div><p>${esc(m.review_note||'审核后刷新页面，已通过的账号将获得商家工作台权限。')}</p></div>`:`<div class="panel"><form id="application-form"><div class="form-grid"><div class="field"><label>档口名称<input name="name" placeholder="例如：演示暖心粥铺" maxlength="40" required></label></div><div class="field"><label>所属食堂<select name="canteen_id">${state.merchant.canteens.map(x=>`<option value="${x.id}">${esc(x.name)}</option>`).join('')}</select></label></div><div class="field full"><label>经营内容<textarea name="description" placeholder="填写演示品类与档口说明，不填写真实证件或私人联系方式" maxlength="150" required></textarea></label></div></div><div class="notice">审核通过后可以创建菜单并处理本地测试订单。真实资质材料、校方准入和结算均未接入。</div><div class="form-error" role="alert"></div><button class="btn" type="submit">提交演示入驻申请</button></form></div>`}`;}
function buildingsAdmin(){return `<div class="workspace-title"><div><div class="eyebrow">DELIVERY POLICY</div><h1>楼栋配送规则</h1><p>规则改动使旧报价失效，已经创建的订单保留原交付约定。</p></div></div><div class="panels">${state.admin.buildings.map(b=>`<article class="panel"><div class="section-heading"><h3>${esc(b.name)}</h3>${pill(b.active?'已开放演示':'未开放',b.active?'green':'')}</div><p class="muted">学校租户 ${b.tenant_id} · 规则版本 ${b.version}</p><div class="chips">${pill(b.mode==='ROOM'?'送到寝室':'明确确认楼下交付')}${pill(`1–${b.max_floor} 层`)}</div>${btn('配置规则','building-edit',`data-id="${b.id}"`,'outline')}</article>`).join('')}</div><div class="notice">这些均为演示楼栋。默认规则不代表四川农业大学的真实上楼管理规定，正式使用前必须现场确认。</div>`;}
function schoolsAdmin(){return `<div class="workspace-title"><div><div class="eyebrow">MULTI-SCHOOL WORKSPACE</div><h1>学校与租户</h1><p>学校之间订单、商家与配送权限相互隔离。</p></div>${state.user.role==='admin'?btn('＋ 学校草案','new-school','',''):''}</div><div class="panels">${state.admin.schools.map(s=>`<article class="panel"><div class="section-heading"><h3>${esc(s.name)}</h3>${pill(s.status==='DEMO_ENABLED'?'演示启用':s.status==='DRAFT'?'草案':'已暂停',s.status==='DEMO_ENABLED'?'green':'')}</div><p class="muted">租户编号 ${s.id} · 生产服务未开通</p><div class="chips">${state.meta.campuses.filter(c=>c.tenant_id===s.id).map(c=>pill(`${c.name} · ${c.active?'演示开放':'待配置'}`)).join('')}</div>${state.user.role==='admin'?btn(s.status==='DEMO_ENABLED'?'暂停新增订单':'启用演示租户','school-state',`data-id="${s.id}" data-enabled="${s.status==='DEMO_ENABLED'?'0':'1'}"`,'outline'):''}</article>`).join('')}</div><div class="notice">新学校默认草案，不自动创建实际食堂、人员和服务范围。启用租户不会自动开放校区；完整校区开通配置是后续运营接入工作。</div>`;}

async function performAction(oid,action,extra={}){
 const o=state.orders.find(x=>x.id===oid);
 if(!o)throw new Error('订单列表已变化，请刷新');
 await post(`/orders/${oid}/actions`,{action,version:o.version,...extra});
 closeModal();await hydrate();toast(`${actionName[action]}已记录`);
}
async function openAction(oid,action){
 const o=state.orders.find(x=>x.id===oid);state.action={oid,action};
 if(['accept','ready','claim','accept_offer','decline_offer','pickup','confirm'].includes(action))return performAction(oid,action);
 let body='';
 if(action==='assign')body=`<div class="field"><label>选择同校区配送员<select name="rider_id">${state.admin.riders.filter(x=>x.tenant_id===o.tenant_id&&x.campus_id===o.campus_id).map(x=>`<option value="${x.id}">${esc(x.display_name)}</option>`).join('')}</select></label></div><p class="muted">派单后等待配送员确认；120 秒未响应会回到待接队列。</p>`;
 else if(action==='deliver')body=`<div class="notice green">本单约定：${esc(o.snapshot.address.delivery_label)}<br>${esc(o.snapshot.address.building_name)} ${o.snapshot.address.mode==='ROOM'?`${o.snapshot.address.floor} 层 ${esc(o.snapshot.address.room)} 寝室`:''}</div><label class="check-line"><input type="checkbox" name="delivered" required><span>我确认已按本单约定的交付点完成演示交付。</span></label>`;
 else body=`<div class="field"><label>处理原因<textarea name="reason" required minlength="2" maxlength="120" placeholder="请填写明确的演示处理原因"></textarea></label></div>${action==='requeue'?'<label class="check-line"><input type="checkbox" name="not_picked_up" required><span>已核对未发生实体取餐；回收后原骑手失去详细地址访问权限。</span></label>':''}${action==='approve_refund'?'<div class="notice">全额模拟退款，仅更新本机账本。已开始制作的餐品不回补可售库存；已经取餐的任务仍需完成交付。</div>':''}${action==='cancel'?'<p class="muted">仅未接单订单可直接取消；已模拟支付的金额会记录为全额模拟退款。</p>':''}`;
 modal(actionName[action],`<form id="action-form">${body}<div class="form-error" role="alert"></div><div class="modal-footer">${btn('返回','close')}<button class="btn" type="submit">确认并记录</button></div></form>`);
}

document.addEventListener('click',async e=>{
 const el=e.target.closest('[data-cmd]');if(!el||el.disabled||state.busy)return;
 const cmd=el.dataset.cmd;
 try{
  if(cmd==='close')return closeModal();
  if(cmd==='select-login')return loginPage(el.dataset.user);
  if(cmd==='logout'){await post('/logout');state.user=null;state.cart=[];closeModal();return loginPage();}
  if(cmd==='nav'){state.view=el.dataset.view;state.filter='全部';return await hydrate();}
  if(cmd==='refresh')return await hydrate();
  if(cmd==='shop'){state.mid=Number(el.dataset.id);state.category='全部';return render();}
  if(cmd==='category'){state.category=el.dataset.category;return render();}
  if(cmd==='product')return productModal(Number(el.dataset.id));
  if(cmd==='qty'){const i=Number(el.dataset.i);state.cart[i].quantity+=Number(el.dataset.delta);if(state.cart[i].quantity<=0)state.cart.splice(i,1);if(state.cart[i]?.quantity>20)state.cart[i].quantity=20;persistCart();return render();}
  if(cmd==='scroll-cart')return $('#cart').scrollIntoView({behavior:'smooth',block:'start'});
  if(cmd==='address')return addressModal();
  if(cmd==='order-filter'){state.filter=el.dataset.filter;return render();}
  if(cmd==='create-order'){
    el.disabled=true;
    const order=await post('/orders',{quote_id:state.quote.id},{'Idempotency-Key':state.quote.orderKey});
    state.cart=[];persistCart();state.quote=null;state.view='orders';closeModal();await hydrate();return toast(`测试订单 ${order.id} 已创建，尚未模拟支付`);
  }
  if(cmd==='pay'){
    el.disabled=true;const order=state.orders.find(x=>x.id===el.dataset.id);
    await post(`/orders/${order.id}/simulate-payment`,{event_key:`browser-demo-${order.id}`,amount_cents:order.total_cents});
    await hydrate();return toast('本地模拟支付成功 · 未扣款');
  }
  if(cmd==='order-action'){el.disabled=true;return await openAction(el.dataset.id,el.dataset.action);}
  if(cmd==='new-product')return productEdit();
  if(cmd==='edit-product')return productEdit(Number(el.dataset.id));
  if(cmd==='shop-state'){await post('/merchant/status',{open:state.merchant.merchant.status!=='OPEN'});await hydrate();return toast('营业状态已更新');}
  if(cmd==='review'){
    state.review={id:Number(el.dataset.id),approve:el.dataset.approve==='1'};
    return modal(state.review.approve?'通过演示入驻审核':'退回演示申请',`<form id="review-form"><label>审核说明<textarea name="note" maxlength="120" minlength="2" required placeholder="记录演示审核依据"></textarea></label><div class="form-error" role="alert"></div><div class="modal-footer">${btn('返回','close')}<button class="btn" type="submit">确认审核结果</button></div></form>`);
  }
  if(cmd==='building-edit'){
    const b=state.admin.buildings.find(x=>x.id===Number(el.dataset.id));state.building=b;
    return modal('配置 '+b.name,`<form id="building-form"><div class="field"><label>交付方式<select name="mode"><option value="ROOM" ${b.mode==='ROOM'?'selected':''}>送到寝室</option><option value="LOBBY" ${b.mode==='LOBBY'?'selected':''}>仅楼下交付（学生必须明确同意）</option></select></label></div><div class="field"><label>最高楼层<input name="max_floor" type="number" min="1" max="30" value="${b.max_floor}" required></label></div><label class="check-line"><input name="active" type="checkbox" ${b.active?'checked':''}><span>开放演示配送</span></label><div class="notice">更新仅影响新订单；已有报价将要求重新确认。</div><div class="form-error" role="alert"></div><div class="modal-footer">${btn('返回','close')}<button class="btn" type="submit">保存规则</button></div></form>`);
  }
  if(cmd==='new-school')return modal('建立学校草案',`<form id="school-form"><div class="field"><label>学校名称<input name="name" required maxlength="50" placeholder="请明确标注演示学校"></label></div><div class="field"><label>首个校区名称<input name="campus_name" required maxlength="50"></label></div><div class="notice">只创建未开放草案，不自动配置食堂、商家或学校账号。</div><div class="form-error" role="alert"></div><div class="modal-footer">${btn('取消','close')}<button class="btn" type="submit">创建草案</button></div></form>`);
  if(cmd==='school-state'){await post(`/admin/schools/${el.dataset.id}/state`,{enabled:el.dataset.enabled==='1'});await hydrate();toast('演示租户状态已更新');}
 }catch(error){showError(error,$('#modal-root .modal'));if(error.code==='STALE_VERSION')await hydrate();}
 finally{if(document.contains(el))el.disabled=false;}
});

document.addEventListener('submit',async e=>{
 const form=e.target;if(!(form instanceof HTMLFormElement))return;e.preventDefault();
 const submit=$('button[type=submit]',form);if(submit?.disabled)return;if(submit)submit.disabled=true;
 const data=new FormData(form);const val=k=>String(data.get(k)||'');
 try{
  if(form.id==='login-form'){await post('/login',{username:val('username'),password:val('password')});await hydrate(true);}
  if(form.id==='product-form'){
    const {sku,options,quantity,price}=readProduct(form);
    if(state.cart.length&&state.cart[0].merchant_id!==state.mid)throw new Error('餐袋里有其他档口商品，请先完成或移除该档口餐品。本期一单一个档口。');
    if(quantity>sku.stock)throw new Error('数量超过当前可售库存');
    const key=JSON.stringify([sku.id,options.map(x=>x.id).sort()]);const existing=state.cart.find(x=>x.key===key);
    if(existing){if(existing.quantity+quantity>20)throw new Error('每种规格最多 20 份');existing.quantity+=quantity;}
    else state.cart.push({key,merchant_id:state.mid,sku_id:sku.id,name:state.product.name,label:sku.label,options:options.map(x=>x.id).sort(),option_names:options.map(x=>x.name),quantity,unit_cents:price});
    persistCart();closeModal();render();toast('已加入餐袋');
  }
  if(form.id==='address-form'){
    const request={merchant_id:state.cart[0].merchant_id,address:{building_id:Number(val('building_id')),floor:Number(val('floor')),room:val('room'),alias:val('alias'),accept_lobby:data.has('accept_lobby')},items:state.cart.map(x=>({sku_id:x.sku_id,quantity:x.quantity,options:x.options})),note:val('note')};
    state.quote=await post('/quotes',request);state.quote.orderKey=crypto.randomUUID();quoteModal();
  }
  if(form.id==='action-form'){
    const extra={};if(data.has('reason'))extra.reason=val('reason');if(data.has('rider_id'))extra.rider_id=Number(val('rider_id'));if(data.has('not_picked_up'))extra.confirmed_not_picked_up=true;
    if(data.has('delivered'))extra.confirmed_point=state.orders.find(x=>x.id===state.action.oid).snapshot.address.delivery_label;
    await performAction(state.action.oid,state.action.action,extra);
  }
  if(form.id==='product-edit-form'){
    const s=state.merchant.products.flatMap(x=>x.skus).find(x=>x.id===state.editSku);
    const body={name:val('name'),description:val('description'),category:val('category'),active:val('active')==='1',label:val('label'),price_cents:cents(val('price')),box_cents:cents(val('box')),stock:Number(val('stock')),version:s?.version||null};
    await api(state.editSku?`/merchant/skus/${state.editSku}`:'/merchant/products',{method:state.editSku?'PUT':'POST',body});closeModal();await hydrate();toast('菜单与库存已保存');
  }
  if(form.id==='application-form'){await post('/merchant/apply',{name:val('name'),description:val('description'),canteen_id:Number(val('canteen_id'))});await hydrate();toast('入驻申请已提交');}
  if(form.id==='review-form'){await post(`/admin/merchants/${state.review.id}/review`,{approve:state.review.approve,note:val('note')});closeModal();await hydrate();toast('审核结果已保存');}
  if(form.id==='building-form'){await api(`/admin/buildings/${state.building.id}`,{method:'PUT',body:{mode:val('mode'),active:data.has('active'),max_floor:Number(val('max_floor')),version:state.building.version}});closeModal();await hydrate();toast('楼栋规则已保存');}
  if(form.id==='school-form'){await post('/admin/schools',{name:val('name'),campus_name:val('campus_name')});state.meta=await api('/meta');closeModal();await hydrate();toast('未开放的学校草案已建立');}
 }catch(error){showError(error,form);}finally{if(submit&&document.contains(submit))submit.disabled=false;}
});

document.addEventListener('change',e=>{
 if(e.target.id==='building')renderBuildingRule();
 if(e.target.closest('#product-form')){try{$('#option-price').textContent=money(readProduct($('#product-form')).price*Number($('#product-form [name=quantity]').value));}catch{}}
 if(e.target.id==='school-select'&&Number(e.target.value)!==state.user.tenant_id){e.target.value=state.user.tenant_id;toast('账号按学校隔离。体验第二学校请切换为 student2 演示账号。');}
 if(e.target.id==='campus-select'&&Number(e.target.value)!==state.user.campus_id){e.target.value=state.user.campus_id;toast('此账号仅授权当前校区；其他校区尚未开放。');}
});
document.addEventListener('keydown',e=>{if(e.key==='Escape')closeModal();});

setInterval(async()=>{
 if(!state.user||state.view!=='orders'||$('#modal-root').childElementCount||document.hidden)return;
 try{const user=await api('/me');if(user.id!==state.user.id||user.role!==state.user.role){await hydrate(true);return;}const orders=await api('/orders');if(JSON.stringify(orders)!==JSON.stringify(state.orders)){state.orders=orders;if(['admin','school_admin'].includes(state.user.role))state.admin=await api('/admin');render();}$('#connection-note')?.remove();}catch(error){if(error.status===401){state.user=null;loginPage();}else if(!$('#connection-note')){const el=document.createElement('div');el.id='connection-note';el.className='notice error';el.textContent='连接暂时中断，以下为上次记录。请刷新核对最新状态。';$('.main')?.prepend(el);}}
},5000);

try{state.meta=await api('/meta');await hydrate(true);}catch(error){if(error.status===401)loginPage();else{$('#app').innerHTML=empty('暂时无法连接本地服务','请确认服务正在运行，再刷新页面。');toast(error.message);}}
