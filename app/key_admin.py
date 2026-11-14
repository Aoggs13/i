import html,time

def btn(text,data):return {'text':text,'callback_data':data}

class KeyAdmin:
 def __init__(self,bot):self.bot=bot;self.store=bot.store;self.tg=bot.tg
 def text(self,uid,ru,en):return en if self.bot.lang(uid)=='en'else ru
 def allowed(self,uid,chat):return uid==chat and self.store.admin(uid)
 def state(self,uid,key):
  if key['revoked']:return self.text(uid,'Заблокирован','Blocked')
  if key['frozen_at']is not None:return self.text(uid,'Заморожен','Frozen')
  if key['activated_at']is None:return self.text(uid,'Не активирован','Not activated')
  if int(time.time())>=key['expires_at']:return self.text(uid,'Истёк','Expired')
  return self.text(uid,'Активен','Active')
 async def panel(self,uid,chat):
  if not self.allowed(uid,chat):await self.tg.message(chat,self.bot.t(uid,'admin'));return
  s=self.store.stats()
  labels=('Orders','Paid','Under review')if self.bot.lang(uid)=='en'else('Заказы','Оплачено','На проверке')
  rows=[[btn(self.text(uid,'Ключи','Keys'),'keys')],[btn(self.text(uid,'Получить IPA','Get IPA'),'admin_ipa')],[btn(self.bot.t(uid,'plans'),'mod:ajg'),btn(self.bot.t(uid,'language'),'language')]]
  await self.tg.message(chat,f"[AJG]\n{labels[0]}: {s['orders']or 0}\n{labels[1]}: {s['revenue']or 0} ₸\n{labels[2]}: {s['pending']or 0}",rows)
 async def keys(self,uid,chat):
  if not self.allowed(uid,chat):await self.tg.message(chat,self.bot.t(uid,'admin'));return
  keys=self.store.admin_keys(uid)
  rows=[[btn(k['order_id']+' · '+self.bot.title(uid,k['plan'])+' · '+self.state(uid,k),'key:'+k['order_id'])]for k in keys]
  rows.append([btn(self.bot.t(uid,'back'),'admin')])
  await self.tg.message(chat,self.text(uid,'Ключи\n\nПоиск: /key ключ или номер заказа','Keys\n\nSearch: /key followed by a key or order ID'),rows)
 async def show(self,uid,chat,oid):
  if not self.allowed(uid,chat):await self.tg.message(chat,self.bot.t(uid,'admin'));return
  key=self.store.license_for_order(oid)
  if not key:await self.tg.message(chat,self.text(uid,'Ключ не найден.','Key not found.'));return
  raw=self.store.authority.decrypt(key['key_encrypted'])
  at=key['frozen_at']if key['frozen_at']is not None else int(time.time())
  remain=key['duration']if key['expires_at']is None else max(0,key['expires_at']-at)
  hours=remain//3600;duration=f'{hours//24}d {hours%24}h'
  device=self.text(uid,'Привязан','Bound')if key['device_hash']else self.text(uid,'Свободен','Available')
  text=f"[AJG] {oid}\n<code>{html.escape(raw)}</code>\n{self.bot.title(uid,key['plan'])} · {self.state(uid,key)}\n{self.text(uid,'Осталось','Remaining')}: {duration}\n{self.text(uid,'Устройство','Device')}: {device}"
  freeze='unfreeze'if key['frozen_at']is not None else'freeze';block='unblock'if key['revoked']else'block'
  rows=[[btn('Reset HWID','ka:reset:'+oid)],
   [btn(self.text(uid,'Разморозить','Unfreeze')if freeze=='unfreeze'else self.text(uid,'Заморозить','Freeze'),'ka:'+freeze+':'+oid),
    btn(self.text(uid,'Разблокировать','Unblock')if block=='unblock'else self.text(uid,'Заблокировать','Block'),'ka:'+block+':'+oid)],
   [btn(self.text(uid,'Получить файлы','Get files'),'keyfiles:'+oid)],
   [btn(self.bot.t(uid,'back'),'keys')]]
  await self.tg.message(chat,text,rows)
 async def lookup(self,uid,chat,value):
  if not self.allowed(uid,chat):await self.tg.message(chat,self.bot.t(uid,'admin'));return
  key=self.store.find_key(uid,value)
  if not key:await self.tg.message(chat,self.text(uid,'Ключ не найден.','Key not found.'));return
  await self.show(uid,chat,key['order_id'])
 async def callback(self,uid,chat,data):
  if not self.allowed(uid,chat):await self.tg.message(chat,self.bot.t(uid,'admin'));return
  if data=='admin':await self.panel(uid,chat)
  elif data=='keys':await self.keys(uid,chat)
  elif data=='admin_ipa':await self.bot.send_ipa(chat,uid)
  elif data.startswith('key:'):await self.show(uid,chat,data[4:])
  elif data.startswith('keyfiles:'):
   order=self.store.order(data[9:])
   if order and order['state']=='approved':await self.bot.deliver(order,target_chat=chat)
  elif data.startswith('ka:'):
   parts=data.split(':')
   if len(parts)!=3:return
   _,action,oid=parts
   if action=='reset':
    await self.tg.message(chat,self.text(uid,'Сбросить HWID? Срок ключа сохранится.','Reset HWID? Key expiry will stay the same.'),[[btn(self.bot.t(uid,'approve'),'kc:reset:'+oid),btn(self.bot.t(uid,'back'),'key:'+oid)]]);return
   await self.act(uid,chat,oid,action)
  elif data.startswith('kc:reset:'):await self.act(uid,chat,data[9:],'reset')
 async def act(self,uid,chat,oid,action):
  try:self.store.key_action(uid,oid,action)
  except ValueError as e:
   await self.tg.message(chat,self.text(uid,'Срок истёк.'if str(e)=='expired'else'Не получилось.','Expired.'if str(e)=='expired'else'Action failed.'));return
  if action=='freeze':await self.tg.message(chat,self.text(uid,'Ключ заморожен. Оставшееся время сохранено.','Key frozen. Remaining time saved.'))
  await self.show(uid,chat,oid)
