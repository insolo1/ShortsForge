import hashlib

text = "123456"
hash_object = hashlib.sha256(text.encode('utf-8'))
sha256_hash = hash_object.hexdigest()

print(sha256_hash)