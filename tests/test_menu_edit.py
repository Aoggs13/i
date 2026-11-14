import asyncio
import httpx
import pytest
from app.bot import Bot,BANKS
from app.telegram import Telegram,TelegramError

USER={'id':1001,'username':'buyer'}
def run(value):return asyncio.run(value)
def callback(bot,value,number=1):
 return bot.handle({'update_id':number,'callback_query':{'id':'q'+str(number),'from':USER,'data':value,'message':{'message_id':77,'chat':{'id':1001,'type':'private'}}}})

@pytest.mark.parametrize('lang',['ru','en'])
def test_language_and_purchase_navigation_edits_one_menu(store,telegram,lang):
 bot=Bot(store,telegram,'claim','https://example.test/AJG.ipa',True)
 for number,value in enumerate(['lang:'+lang,'product:ff','mod:ajg','language','lang:'+lang,'product:ff','mod:ajg'],1):
  run(callback(bot,value,number))
  assert telegram.calls[-1][0]=='editMessageText'
  payload=telegram.calls[-1][1];assert payload['chat_id']==1001 and payload['message_id']==77
 assert store.my_orders(1001)==[]
 labels=[row[0]['text']for row in telegram.calls[-1][1]['reply_markup']['inline_keyboard'][:3]]
 assert all(str(price)in label for price,label in zip([800,2000,4000],labels))
 run(callback(bot,'plan:day1',20));order=store.my_orders(1001)[0]
 run(callback(bot,'bank:'+order['id']+':kaspi',21))
 assert telegram.calls[-1][0]=='editMessageText' and BANKS['kaspi']['phone']in telegram.calls[-1][1]['text']
 run(callback(bot,'my',22));run(callback(bot,'menu',23))
 assert not any(method=='sendMessage'for method,*_ in telegram.calls)
 assert len(store.my_orders(1001))==1 and store.license_for_order(order['id'])is None

@pytest.mark.parametrize('description',["Bad Request: message to edit not found","Bad Request: message can't be edited"])
def test_deleted_menu_falls_back_once(store,telegram,description):
 original=telegram.call
 async def call(method,payload=None,files=None):
  if method=='editMessageText':raise TelegramError(400,description)
  return await original(method,payload,files)
 telegram.call=call;bot=Bot(store,telegram,'claim')
 run(bot.languages(1001,77));assert telegram.calls[-1][0]=='sendMessage'

def test_api_failure_does_not_create_another_menu(store,telegram):
 async def call(method,payload=None,files=None):raise TelegramError(429,'Too Many Requests')
 telegram.call=call;bot=Bot(store,telegram,'claim')
 with pytest.raises(TelegramError):run(bot.languages(1001,77))
 assert telegram.calls==[]

def test_duplicate_edit_is_success_and_errors_do_not_expose_bot_url():
 async def check():
  tg=Telegram('fixture-token')
  await tg.client.aclose()
  tg.client=httpx.AsyncClient(transport=httpx.MockTransport(lambda request:httpx.Response(400,json={'ok':False,'error_code':400,'description':'Bad Request: message is not modified'})))
  try:assert (await tg.call('editMessageText',{'message_id':77}))['unchanged']
  finally:await tg.client.aclose()
 run(check())
 assert 'fixture-token'not in str(TelegramError(400,'fixture-token'))
