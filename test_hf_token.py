"""Quick test to verify HuggingFace token storage and retrieval."""

from src.config.credential_manager import get_credential_manager

def main():
    print("=" * 60)
    print("HuggingFace Token Storage Test")
    print("=" * 60)

    cred_manager = get_credential_manager()

    # Try to retrieve the token
    token = cred_manager.get_huggingface_token()

    if token:
        # Mask for security
        masked = token[:4] + "..." + token[-4:] if len(token) > 8 else "***"
        print(f"✓ Token found in credential manager: {masked}")
        print(f"  Token length: {len(token)} characters")

        # Test HuggingFace API with this token
        print("\nTesting token with HuggingFace API...")
        try:
            from huggingface_hub import HfApi
            api = HfApi(token=token)
            user_info = api.whoami()
            print(f"✓ Token is valid!")
            print(f"  User: {user_info.get('name', 'unknown')}")
            print(f"  Type: {user_info.get('type', 'unknown')}")

            # Check access to Gemma model
            print("\nChecking access to google/gemma-3-12b-it...")
            try:
                model_info = api.model_info("google/gemma-3-12b-it", token=token)
                print(f"✓ Access to Gemma 3 12B confirmed!")
                print(f"  Model ID: {model_info.modelId}")
            except Exception as e:
                print(f"✗ Cannot access Gemma model: {e}")

        except Exception as e:
            print(f"✗ Token validation failed: {e}")
    else:
        print("✗ No token found in credential manager!")
        print("\nTo fix this:")
        print("1. Open Settings in the application")
        print("2. Go to 'API Keys' tab")
        print("3. Enter your HuggingFace token in the 'HF API Token' field")
        print("4. Click 'Apply' or 'OK' to save")
        print("\nAlternatively, you can store it manually:")
        print("  from src.config.credential_manager import get_credential_manager")
        print("  cred_manager = get_credential_manager()")
        print("  cred_manager.store_huggingface_token('hf_your_token_here')")

    print("=" * 60)

if __name__ == "__main__":
    main()
