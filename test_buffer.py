import requests

API_KEY = "cQJ4xuqenqOibNAcASCs0m8vgz-JNelFl3OvAf86i96"

# Try the v1 API
print("Testing Buffer v1 API...")
r1 = requests.get(
    "https://api.buffer.com/1/profiles.json",
    params={"access_token": API_KEY}
)
print(f"v1 Status: {r1.status_code}")

# Try the v2 API (newer)
print("\nTesting Buffer v2 API...")
r2 = requests.get(
    "https://api.bufferapp.com/2/profiles.json",
    headers={"Authorization": f"Bearer {API_KEY}"}
)
print(f"v2 Status: {r2.status_code}")
if r2.status_code == 200:
    print("✅ v2 API works!")
    print(r2.json())
