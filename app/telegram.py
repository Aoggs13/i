import httpx
class TelegramError(RuntimeError):
 def __init__(self,code,description=''):
  self.code=code;self.description=description;super().__init__('telegram_'+str(code))
class Telegram:
 def __init__(self,token):self.token=token;self.client=httpx.AsyncClient(timeout=30)
 async def call(self,method,payload=None,files=None):
  # Never log the token-bearing URL or raw Telegram updates.
  url='https://api.telegram.org/bot'+self.token+'/'+method
  if files:r=await self.client.post(url,data=payload or{},files=files,timeout=httpx.Timeout(120,connect=15))
  else:r=await self.client.post(url,json=payload or{})
  try:data=r.json()
  except ValueError:raise RuntimeError('telegram_invalid_response')from None
  if not data.get('ok'):
   description=data.get('description','')
   if method=='editMessageText'and'message is not modified'in description.lower():return {'message_id':(payload or{}).get('message_id'),'unchanged':True}
   raise TelegramError(data.get('error_code',r.status_code),description)
  return data['result']
 async def message(self,chat,text,buttons=None):
  p=dict(chat_id=chat,text=text,parse_mode='HTML',link_preview_options={'is_disabled':True})
  if buttons:p['reply_markup']={'inline_keyboard':buttons}
  return await self.call('sendMessage',p)
