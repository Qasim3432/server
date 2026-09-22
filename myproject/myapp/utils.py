import hashlib
import time

def generate_secure_token(email, device_id, ip):
    raw = f"{email}:{device_id}:{ip}:{time.time()}"
    return hashlib.sha256(raw.encode()).hexdigest()