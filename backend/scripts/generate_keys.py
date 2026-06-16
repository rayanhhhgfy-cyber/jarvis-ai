import secrets
import base64
import os

def generate_keys():
    # 1. Generate a strong, random string for BACKEND_SECRET_KEY
    # This is used for JWT signing and general session security.
    backend_secret = secrets.token_urlsafe(32)

    # 2. Generate a 32-character random string for ENCRYPTION_KEY
    # This is used for AES-256 symmetric encryption of stored data.
    # Note: Cryptography/Fernet often expects base64 encoded bytes of 32 random bytes.
    raw_key = secrets.token_bytes(32)
    encryption_key = base64.urlsafe_b64encode(raw_key).decode('utf-8')

    print("=" * 60)
    print("JARVIS OMEGA - SECURITY KEY GENERATOR")
    print("=" * 60)
    print(f"BACKEND_SECRET_KEY={backend_secret}")
    print(f"ENCRYPTION_KEY={encryption_key}")
    print("=" * 60)
    print("\n[INSTRUCTIONS]")
    print("1. Copy the values above.")
    print("2. Open your '.env' file in the root directory.")
    print("3. Paste them into the corresponding fields.")
    print("4. Keep these keys secret! If lost, encrypted data may become inaccessible.")
    print("=" * 60)

if __name__ == "__main__":
    generate_keys()
