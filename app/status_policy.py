"""Own ESP availability, grounded in the purchased client's real file metadata."""
import asyncio,copy,json,time
from pathlib import Path
import httpx

UPSTREAM='http://103.69.97.207:8787'
def enabled(value):
 if isinstance(value,dict):return value.get('enabled')is True
 return value is True

class StatusPolicy:
 def __init__(self,token,policy_path):
  self.token=token;self.path=Path(policy_path);self.client=httpx.AsyncClient(timeout=15)
  self.lock=asyncio.Lock();self.cached=None;self.checked=0
 async def get(self):
  async with self.lock:
   if self.cached is not None and time.monotonic()-self.checked<30:return copy.deepcopy(self.cached)
   policy=json.loads(self.path.read_text())
   assert policy['feature']=='weapon_cyan'and policy['folder']=='patches/ff/esp/weapon_cyan'
   headers={'X-Phantom-Token':self.token,'User-Agent':'PhantomRegedit','Accept':'application/json'}
   response=await self.client.get(UPSTREAM+'/status.json',headers=headers,params={'t':str(int(time.time()))});response.raise_for_status()
   source=response.json();features=source.get('features');menus=source.get('menus')
   if not isinstance(features,dict)or not isinstance(menus,dict):raise ValueError('invalid_status')
   listing_response=await self.client.get(UPSTREAM+'/api/v1/client/list',params={'folder':policy['folder']},headers=headers);listing_response.raise_for_status()
   listing=listing_response.json()
   if not isinstance(listing,dict)or not isinstance(listing.get('files'),list):raise ValueError('invalid_listing')
   files=listing['files']
   matched=any(isinstance(f,dict)and f.get('sha')==policy['sha256']and f.get('size')==policy['bytes']and isinstance(f.get('name'),str)and Path(f['name']).name==f['name']for f in files)
   available=bool(matched and enabled(features.get('all'))and enabled(features.get('esp'))and source.get('maintenance')is False)
   features=copy.deepcopy(features);features['weapon_cyan']={'enabled':available}
   menus=copy.deepcopy(menus);menus['esp']=copy.deepcopy(menus.get('home',{'enabled':False}))
   # Never expose the upstream customer's banned-key list or session data.
   result={k:copy.deepcopy(source[k])for k in ['maintenance','title','reason']if k in source}
   result.update(features=features,menus=menus,ajg={'feature':policy['feature'],'available':available,'metadata_matches_verified_file':matched,'sha256':policy['sha256'],'bytes':policy['bytes'],'checked_at':int(time.time()),'reason':'ready'if available else'maintenance'if source.get('maintenance')else'file_metadata_changed'if not matched else'category_disabled'})
   self.cached=result;self.checked=time.monotonic();return copy.deepcopy(result)
