import asyncio,contextlib,hashlib,hmac,json,os,re,time
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI,Request
from fastapi.responses import JSONResponse,FileResponse
from fastapi.middleware.cors import CORSMiddleware
from .authority import Authority
from .store import Store
from .telegram import Telegram
from .bot import Bot
from .status_policy import StatusPolicy

def load_settings():
 result=dict(os.environ)
 file=os.getenv('AJG_SECRETS_FILE')
 if file:result.update(json.loads(Path(file).read_text()))
 return result
config=load_settings()
authority=Authority(config['LICENSE_KEY_PEPPER'],config['SIGNING_PRIVATE_KEY_PEM'])
store=Store(config.get('DATABASE_PATH','data/ajg.sqlite3'),authority)
if config.get('ADMIN_USER_ID')and config.get('ADMIN_CHAT_ID'):
 if not store.claim_owner(int(config['ADMIN_USER_ID']),int(config['ADMIN_CHAT_ID'])):raise RuntimeError('owner_binding_mismatch')
tg=Telegram(config['BOT_TOKEN']);bot=Bot(store,tg,config['OWNER_CLAIM'],config.get('IPA_URL',''),str(config.get('CHECKOUT_ENABLED','false')).lower()=='true')
release=Path(config.get('IPA_PATH',str(Path(__file__).resolve().parents[1]/'release/AJG.ipa')))
release_manifest=release.parent/'manifest.json'
release_info=json.loads(release_manifest.read_text())if release_manifest.is_file()else{}
bot.ipa_path=release;bot.ipa_sha=release_info.get('sha256')
if config.get('IPA_FILE_SHA256')==bot.ipa_sha:bot.ipa_file_id=config.get('IPA_FILE_ID')
status_policy=StatusPolicy(config.get('PHANTOM_ASSET_TOKEN',''),release.parent/'esp-policy.json')
async def deliver_loop():
 while True:
  await bot.outbox();await asyncio.sleep(5)
async def poll_loop():
 offset=0
 while True:
  try:
   updates=await tg.call('getUpdates',{'offset':offset,'timeout':20,'allowed_updates':['message','callback_query']})
   for update in updates:await bot.handle(update);offset=update['update_id']+1
   await bot.outbox()
  except Exception:await asyncio.sleep(3)
@asynccontextmanager
async def lifespan(app):
 jobs=[asyncio.create_task(deliver_loop())]
 if config.get('BOT_MODE','webhook')=='polling':jobs.append(asyncio.create_task(poll_loop()))
 try:yield
 finally:
  for task in jobs:task.cancel()
  for task in jobs:
   with contextlib.suppress(asyncio.CancelledError):await task
  await tg.client.aclose()
  await status_policy.client.aclose()
app=FastAPI(title='AJG License Service',docs_url=None,redoc_url=None,openapi_url=None,lifespan=lifespan)
app.add_middleware(CORSMiddleware,allow_origins=['*'],allow_methods=['POST','GET','OPTIONS'],allow_headers=['Content-Type'])
@app.get('/health')
def health():return{'ok':True,'service':'AJG','version':release_info.get('version','50004'),'checkout_enabled':bot.enabled,'owner_ready':bool(store.setting('admin_user_id')),'ipa_ready':release.is_file(),'ipa_sha256':release_info.get('sha256'),'bundle_id':release_info.get('bundle_identifier'),'signing_key_sha256':hashlib.sha256(authority.public_bytes()).hexdigest(),'bot_menu_message_mode':'edit'}
@app.get('/downloads/AJG.ipa')
def download():
 if not release.is_file():return JSONResponse({'ok':False,'error':'not_ready'},404)
 return FileResponse(release,media_type='application/octet-stream',filename='AJG.ipa',headers={'Cache-Control':'public, max-age=300','X-Content-Type-Options':'nosniff'})
@app.get('/status.json')
async def native_status():
 try:return JSONResponse(await status_policy.get(),headers={'Cache-Control':'no-store'})
 except Exception:return JSONResponse({'ok':False,'error':'status_unavailable'},503,headers={'Cache-Control':'no-store'})
@app.post('/telegram/webhook')
async def webhook(request:Request):
 if not hmac.compare_digest(request.headers.get('x-telegram-bot-api-secret-token',''),config['WEBHOOK_SECRET']):return JSONResponse({'ok':False},403)
 try:
  raw=await request.body()
  if len(raw)>1_000_000:return JSONResponse({'ok':False},413)
  body=json.loads(raw)
  if not isinstance(body,dict):return JSONResponse({'ok':False},400)
  await bot.handle(body);return{'ok':True}
 except (ValueError,TypeError):return JSONResponse({'ok':False,'error':'invalid_request'},400)
 except Exception:return JSONResponse({'ok':False,'error':'retry'},503)
limits={}
@app.post('/v1/activate')
async def activate(request:Request):
 try:
  raw=await request.body()
  if len(raw)>4096:return JSONResponse({'ok':False,'error':'request_too_large'},413)
  try:body=json.loads(raw)
  except (ValueError,TypeError):return JSONResponse({'ok':False,'error':'invalid_request'},400)
  if not isinstance(body,dict):return JSONResponse({'ok':False,'error':'invalid_request'},400)
  key=body.get('key','');device=body.get('device_hash','')
  if not isinstance(key,str)or not isinstance(device,str)or not re.fullmatch(r'AJG-(?:01D|10D|01M)-[A-Z2-7]{5}(?:-[A-Z2-7]{5}){3}',key.strip().upper())or not re.fullmatch('[0-9a-f]{64}',device):return JSONResponse({'ok':False,'error':'invalid_request'},400)
  digest=authority.digest(key);now=int(time.time());window=now//60
  count,last=limits.get(digest,(0,window));count=count+1 if last==window else 1;limits[digest]=(count,window)
  if len(limits)>10000:
   for k,(_,stamp)in list(limits.items()):
    if stamp<window-1:limits.pop(k,None)
   while len(limits)>10000:limits.pop(next(iter(limits)))
  if count>20:return JSONResponse({'ok':False,'error':'rate_limited'},429)
  license=store.activate(key,device,now)
  valid_from=license['expires_at']-license['duration']
  proof=authority.proof(license['id'],device,valid_from,license['expires_at'],license['duration'],now)
  return{'ok':True,'proof':proof,'activated_at':license['activated_at'],'valid_from':valid_from,'expires_at':license['expires_at'],'duration':license['duration'],'server_time':now}
 except ValueError as error:
  code=str(error);return JSONResponse({'ok':False,'error':code},409 if code=='device_mismatch'else 403)
 except Exception:return JSONResponse({'ok':False,'error':'service_unavailable'},503)

