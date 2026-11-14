"""Server-owned expiry and one-device activation. Only the public P-256 key goes into IPA."""
import base64,hashlib,hmac,secrets,struct,time,uuid
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import ec

PLANS={
 'day1':dict(title='1 день',en='1 day',duration=86400,price=800,prefix='01D'),
 'day10':dict(title='10 дней',en='10 days',duration=864000,price=2000,prefix='10D'),
 'month1':dict(title='30 дней',en='30 days',duration=2592000,price=4000,prefix='01M'),
}
MAGIC=0x33474A41
class Authority:
 def __init__(self,pepper_hex,private_pem):
  self.pepper=bytes.fromhex(pepper_hex)
  self.cipher=Fernet(base64.urlsafe_b64encode(hashlib.sha256(self.pepper+b'|store').digest()))
  self.private=serialization.load_pem_private_key(private_pem.encode(),password=None)
 def digest(self,key):return hmac.new(self.pepper,key.strip().upper().encode(),hashlib.sha256).hexdigest()
 def new_key(self,plan):
  chars=base64.b32encode(secrets.token_bytes(16)).decode()[:20]
  return 'AJG-'+PLANS[plan]['prefix']+'-'+'-'.join(chars[i:i+5]for i in range(0,20,5))
 def encrypt(self,value):return self.cipher.encrypt(value.encode()).decode()
 def decrypt(self,value):return self.cipher.decrypt(value.encode()).decode()
 def proof(self,license_id,device_hash,activated_at,expires_at,duration,now=None):
  now=int(time.time())if now is None else now
  payload=struct.pack('<II16s32sQQQQ',MAGIC,duration,uuid.UUID(license_id).bytes,bytes.fromhex(device_hash),activated_at,expires_at,now,min(expires_at,now+300))
  assert len(payload)==88
  signature=self.private.sign(payload,ec.ECDSA(hashes.SHA256()))
  return 'AJG3P-'+payload.hex()+'.'+signature.hex()
 def public_bytes(self):return self.private.public_key().public_bytes(serialization.Encoding.X962,serialization.PublicFormat.UncompressedPoint)

