import asyncio,hmac,html,hashlib,os
from pathlib import Path
from .authority import PLANS
from .key_admin import KeyAdmin
from .telegram import TelegramError
BANKS={'kaspi':dict(name='Kaspi Gold',phone=os.getenv('BANK_KASPI_PHONE',''),recipient=os.getenv('BANK_RECIPIENT','')),'halyk':dict(name='Halyk Bank',phone=os.getenv('BANK_HALYK_PHONE',''),recipient=os.getenv('BANK_RECIPIENT',''))}
TEXT={
 'product':('Выберите продукт','Choose a product'),'mod':('Выберите мод','Choose a mod'),
 'choose':('Выберите тариф','Choose a plan'),'bank':('Выберите банк','Choose a bank'),
 'my':('Мои заказы','My orders'),'channel':('Канал','Channel'),'back':('Назад','Back'),
 'owner':('Администратор подключён.','Administrator connected.'),'invalid':('Ссылка недействительна.','Invalid link.'),
 'admin':('Только для администратора.','Administrator only.'),'prepare':('Магазин готовится к запуску.','The shop is not ready yet.'),
 'receipt':('Отправьте чек: фото или PDF.','Send the receipt as a photo or PDF.'),'copy':('Копировать номер','Copy number'),
 'received':('Чек получен. Ожидайте подтверждения.','Receipt received. Waiting for approval.'),
 'duplicate':('Этот чек уже отправлен.','This receipt has already been submitted.'),
 'startfirst':('Сначала выберите тариф и банк: /start','Choose a plan and a bank first: /start'),
 'large':('Максимальный размер чека: 10 МБ.','Maximum receipt size: 10 MB.'),
 'approve':('Подтвердить','Approve'),'reject':('Отклонить','Reject'),'approved':('Подтверждено','Approved'),
 'rejected':('Оплата не подтверждена.','Payment was not approved.'),'processed':('Заказ уже обработан.','This order has already been processed.'),
 'noorders':('Заказов нет.','No orders yet.'),'again':('Получить файлы','Get files'),
 'file':('Ключ в TXT файле.','Your key as a TXT file.'),'download':('Скачать AJG IPA','Download AJG IPA'),
 'support':('Поддержка','Support'),'plans':('Тарифы','Plans'),'language':('Язык','Language'),'free':('Бесплатно','Free'),
 'manage':('Управление','Admin'),'copy_key':('Копировать ключ','Copy key'),
 'select_bank':('Выбор банка','Choose a bank'),'await_receipt':('Ожидается чек','Waiting for receipt'),
 'await_review':('Проверка','Under review'),'cancelled':('Отменён','Cancelled'),
}
def button(text,data):return{'text':text,'callback_data':data}
def h(x):return html.escape(str(x))
class Bot:
 def __init__(self,store,tg,owner_claim,ipa_url='',enabled=False,ipa_path=None,ipa_sha=None,ipa_file_id=None):
  self.store=store;self.tg=tg;self.owner_claim=owner_claim;self.ipa_url=ipa_url;self.enabled=enabled;self.update_lock=asyncio.Lock();self.delivery_lock=asyncio.Lock()
  self.ipa_path=Path(ipa_path)if ipa_path else None;self.ipa_sha=ipa_sha;self.ipa_file_id=ipa_file_id;self.ipa_lock=asyncio.Lock();self.key_admin=KeyAdmin(self)
 def lang(self,uid):return self.store.language(uid)or'ru'
 def t(self,uid,k):return TEXT[k][self.lang(uid)=='en']
 def title(self,uid,plan):return PLANS[plan]['en'if self.lang(uid)=='en'else'title']
 async def screen(self,chat,text,buttons=None,message_id=None):
  if message_id:
   payload=dict(chat_id=chat,message_id=message_id,text=text,parse_mode='HTML',link_preview_options={'is_disabled':True},reply_markup={'inline_keyboard':buttons or[]})
   try:return await self.tg.call('editMessageText',payload)
   except TelegramError as error:
    if error.code!=400 or not any(reason in error.description.lower()for reason in["message to edit not found","message can't be edited"]):raise
  return await self.tg.message(chat,text,buttons)
 async def languages(self,chat,message_id=None):await self.screen(chat,'[AJG]\nВыберите язык / Choose language',[[button('Русский','lang:ru'),button('English','lang:en')]],message_id)
 async def menu(self,chat,message_id=None):
  if not self.store.language(chat):await self.languages(chat,message_id);return
  rows=[[button('Free Fire','product:ff')]]
  rows.extend([[button(self.t(chat,'my'),'my')],[button(self.t(chat,'language'),'language'),{'text':self.t(chat,'channel'),'url':'https://t.me/grondffsoft'}]])
  if self.store.admin(chat):rows.append([button(self.t(chat,'manage'),'admin')])
  await self.screen(chat,'[AJG]\n'+self.t(chat,'product'),rows,message_id)
 async def mods(self,chat,message_id=None):
  await self.screen(chat,'Free Fire\n'+self.t(chat,'mod'),[[button('[AJG]','mod:ajg')],[button(self.t(chat,'back'),'menu')]],message_id)
 async def plans(self,chat,message_id=None):
  rows=[[button(self.title(chat,p)+' — '+(self.t(chat,'free')if self.store.admin(chat)else str(PLANS[p]['price'])+' ₸'),'plan:'+p)]for p in PLANS]
  rows.append([button(self.t(chat,'back'),'product:ff')])
  await self.screen(chat,'Free Fire · [AJG]\n'+self.t(chat,'choose'),rows,message_id)
 async def handle(self,update):
  async with self.update_lock:
   uid=update.get('update_id')
   if uid is None or self.store.seen(uid):return
   if update.get('callback_query'):await self.callback(update['callback_query'])
   elif update.get('message'):await self.message(update['message'])
   self.store.once(uid)
 async def message(self,msg):
  user=msg.get('from',{});chat=msg.get('chat',{});text=msg.get('text','');uid=user.get('id')
  if chat.get('type')!='private'or not uid:return
  if text.startswith('/start owner_'):
   claim=text.split('owner_',1)[1].strip()
   ok=hmac.compare_digest(claim,self.owner_claim)and self.store.claim_owner(uid,chat['id'])
   await self.tg.message(chat['id'],self.t(uid,'owner'if ok else'invalid'))
   if ok:await self.menu(chat['id'])
   return
  command=text.split(' ',1)[0]
  if command in('/admin','/stats'):
   await self.key_admin.panel(uid,chat['id']);return
  if command=='/keys':await self.key_admin.keys(uid,chat['id']);return
  if command in('/key','/find'):
   value=text.partition(' ')[2].strip()
   if value:await self.key_admin.lookup(uid,chat['id'],value)
   else:await self.key_admin.keys(uid,chat['id'])
   return
  if self.store.admin(uid)and text.startswith('AJG-'):await self.key_admin.lookup(uid,chat['id'],text);return
  if command=='/start':await self.languages(chat['id']);return
  if command=='/menu':await self.menu(chat['id']);return
  if command=='/language':await self.languages(chat['id']);return
  if command in('/my','/orders'):await self.my_orders(uid,chat['id']);return
  photos=msg.get('photo');doc=msg.get('document');receipt=None
  if photos:receipt=photos[-1]
  elif doc and doc.get('mime_type')in('application/pdf','image/jpeg','image/png'):receipt=doc
  if not receipt:await self.tg.message(chat['id'],self.t(uid,'startfirst'));return
  if receipt.get('file_size',0)>10*1024*1024:await self.tg.message(chat['id'],self.t(uid,'large'));return
  order=self.store.latest_waiting(uid)
  if not order:await self.tg.message(chat['id'],self.t(uid,'startfirst'));return
  ok,_=self.store.receipt(order['id'],uid,chat['id'],msg['message_id'],receipt['file_unique_id'])
  await self.tg.message(chat['id'],self.t(uid,'received'if ok else'duplicate'))
 async def callback(self,q):
  user=q['from'];uid=user['id'];chat=q.get('message',{}).get('chat',{}).get('id',uid);value=q.get('data','')
  message_id=q.get('message',{}).get('message_id')
  await self.tg.call('answerCallbackQuery',{'callback_query_id':q['id']})
  if value in('admin','keys','admin_ipa')or value.startswith(('key:','ka:','kc:','keyfiles:')):
   await self.key_admin.callback(uid,chat,value);return
  if value.startswith('lang:'):
   lang=value[5:]
   if lang in('ru','en'):self.store.set_language(uid,lang);await self.menu(chat,message_id)
   else:await self.languages(chat,message_id)
   return
  if value=='language':await self.languages(chat,message_id);return
  if value=='menu':await self.menu(chat,message_id);return
  if value=='product:ff':await self.mods(chat,message_id);return
  if value=='mod:ajg':await self.plans(chat,message_id);return
  if value=='my':await self.my_orders(uid,chat,message_id);return
  if value.startswith('plan:'):
   plan=value[5:]
   if plan not in PLANS:return
   if not self.enabled or not self.ipa_url or not self.store.setting('admin_user_id'):await self.tg.message(chat,self.t(uid,'prepare'));return
   if self.store.admin(uid):self.store.owner_order(user,plan,'plan:'+q['id']);return
   order=self.store.new_order(user,plan)
   await self.screen(chat,f"{order['id']}\n{self.title(uid,plan)} — {order['price']} ₸\n\n{self.t(uid,'bank')}",[[button('Kaspi Gold','bank:'+order['id']+':kaspi')],[button('Halyk Bank','bank:'+order['id']+':halyk')],[button(self.t(uid,'back'),'mod:ajg')]],message_id);return
  if value.startswith('bank:'):
   parts=value.split(':')
   if len(parts)!=3 or parts[2]not in BANKS:return
   oid,bank=parts[1:];o=self.store.order(oid)
   if not o or o['user_id']!=uid:return
   if self.store.admin(uid):
    if not self.enabled or not self.ipa_url:await self.tg.message(chat,self.t(uid,'prepare'));return
    self.store.owner_order(user,o['plan'],'bank:'+oid);return
   if not self.store.bank(oid,uid,bank):await self.tg.message(chat,self.t(uid,'processed'));return
   b=BANKS[bank]
   await self.screen(chat,f"{b['name']}\n{o['price']} ₸\n<code>{b['phone']}</code>\n{h(b['recipient'])}\n\n{self.t(uid,'receipt')}",[[{'text':self.t(uid,'copy'),'copy_text':{'text':b['phone']}}]],message_id);return
  if value.startswith(('approve:','reject:')):
   if not self.store.admin(uid):await self.tg.message(chat,self.t(uid,'admin'));return
   action,oid=value.split(':',1)
   try:
    if action=='approve':self.store.approve(oid,uid);await self.tg.message(chat,self.t(uid,'approved')+': '+oid)
    else:
     changed=self.store.reject(oid,uid);await self.tg.message(chat,self.t(uid,'rejected'if changed else'processed')+' '+oid)
   except ValueError:await self.tg.message(chat,self.t(uid,'processed'))
   return
  if value.startswith('resend:'):
   order=self.store.order(value[7:])
   if order and order['user_id']==uid and order['state']=='approved':await self.deliver(order)
 async def my_orders(self,uid,chat,message_id=None):
  orders=self.store.my_orders(uid)
  if not orders:await self.screen(chat,self.t(uid,'noorders'),[[button(self.t(uid,'plans'),'mod:ajg')]],message_id);return
  text=self.t(uid,'my')+'\n\n'+'\n'.join(o['id']+' | '+self.title(uid,o['plan'])+' | '+self.t(uid,o['state'])for o in orders)
  rows=[[button(self.t(uid,'again')+': '+o['id'],'resend:'+o['id'])]for o in orders if o['state']=='approved'];rows.append([button(self.t(uid,'plans'),'mod:ajg')])
  await self.screen(chat,text,rows,message_id)
 async def send_ipa(self,chat,uid):
  async with self.ipa_lock:
   cached=self.store.setting('ipa_file:'+str(self.ipa_sha))if self.ipa_sha else None
   cached=cached or self.ipa_file_id
   if cached:
    return await self.tg.call('sendDocument',{'chat_id':chat,'document':cached,'caption':'[AJG] IPA'})
   if self.ipa_path and self.ipa_path.is_file():
    if self.ipa_path.stat().st_size>49_000_000:raise RuntimeError('ipa_exceeds_telegram_upload_limit')
    data=self.ipa_path.read_bytes();digest=hashlib.sha256(data).hexdigest()
    if self.ipa_sha and digest!=self.ipa_sha:raise RuntimeError('ipa_digest_mismatch')
    result=await self.tg.call('sendDocument',{'chat_id':str(chat),'caption':'[AJG] IPA'},files={'document':('AJG.ipa',data,'application/octet-stream')})
    file_id=result.get('document',{}).get('file_id')
    if file_id:
     with self.store.lock:self.store.db.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',('ipa_file:'+digest,file_id))
    return result
   await self.tg.message(chat,'[AJG] IPA',[[{'text':self.t(uid,'download'),'url':self.ipa_url}]])
 async def deliver(self,order,target_chat=None):
  license=self.store.license_for_order(order['id']);key=self.store.authority.decrypt(license['key_encrypted']);uid=order['user_id']
  chat=order['chat_id']if target_chat is None else target_chat
  title=self.title(uid,order['plan']);text='[AJG]\n'+title+'\n\n'+key+'\n\nIPA:\n'+self.ipa_url+'\n'
  await self.tg.message(chat,'[AJG] '+title+'\n<code>'+h(key)+'</code>',[[{'text':self.t(uid,'copy_key'),'copy_text':{'text':key}}]])
  await self.tg.call('sendDocument',{'chat_id':str(chat),'caption':self.t(uid,'file')},files={'document':('AJG-'+order['id']+'.txt',text.encode(),'text/plain; charset=utf-8')})
  await self.send_ipa(chat,uid)
 async def outbox(self):
  async with self.delivery_lock:
   for job in self.store.jobs():
    o=self.store.order(job['order_id'])
    try:
     if job['kind']=='admin_receipt':
      admin=self.store.setting('admin_chat_id')
      if not admin:raise RuntimeError('admin_unconfigured')
      au=int(admin);buyer='@'+o['username']if o['username']else str(o['user_id'])
      caption=f"[AJG] {o['id']}\n{h(buyer)}\n{self.title(au,o['plan'])} — {o['price']} ₸\n{BANKS[o['bank']]['name']}"
      await self.tg.call('copyMessage',dict(chat_id=au,from_chat_id=o['receipt_chat'],message_id=o['receipt_message'],caption=caption,parse_mode='HTML',reply_markup={'inline_keyboard':[[button(self.t(au,'approve'),'approve:'+o['id']),button(self.t(au,'reject'),'reject:'+o['id'])]]}))
     elif job['kind']=='license_delivery':await self.deliver(o)
     elif job['kind']=='rejection':await self.tg.message(o['chat_id'],self.t(o['user_id'],'rejected'))
     self.store.done(job['id'])
    except Exception as e:self.store.retry(job['id'],type(e).__name__)
