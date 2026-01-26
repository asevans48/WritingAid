# HuggingFace Token Setup for FLUX-2 Models

FLUX-2 Klein models from Black Forest Labs are **gated models** on HuggingFace, which means you need to:
1. Accept the model license agreement on HuggingFace
2. Provide your HuggingFace token for model downloads

## Step 1: Accept FLUX-2 Model License

1. Go to the FLUX-2 Klein model page on HuggingFace:
   - **FLUX-2 Klein 9B**: https://huggingface.co/black-forest-labs/FLUX.2-klein-9B
   - **FLUX-2 Klein 4B**: https://huggingface.co/black-forest-labs/FLUX.2-klein-4B

2. Click **"Access repository"** or **"Agree and access repository"**

3. Read and accept the license terms

4. You should see "You have been granted access to this model" message

## Step 2: Get Your HuggingFace Token

### Option A: Create a New Token (Recommended)

1. Go to https://huggingface.co/settings/tokens

2. Click **"New token"**

3. Give it a name like `writingaid-flux2`

4. Select **"Read"** permission (write not needed)

5. Click **"Generate token"**

6. **Copy the token** (it won't be shown again!)

### Option B: Use Existing Token

If you already have a HuggingFace token, you can reuse it.

## Step 3: Configure WritingAid

WritingAid checks for your HuggingFace token in this priority order:
1. **Credential Manager** (secure keyring storage) - **RECOMMENDED**
2. genai_config.json
3. HF_TOKEN environment variable
4. huggingface-cli login token

### Method 1: Credential Manager (Most Secure - Recommended)

WritingAid has a built-in credential manager that uses your system's secure keyring:
- **macOS**: Keychain
- **Windows**: Credential Manager
- **Linux**: Secret Service

The HuggingFace token may already be stored if you've configured it in Settings!

**To set or verify:**
1. Open WritingAid
2. Go to **Settings** > **API Keys** tab
3. Look for **HuggingFace Token** field
4. Enter your token: `hf_YOUR_TOKEN_HERE`
5. Click **Save**

The token is encrypted and stored securely in your system keyring. ✅ **This is the recommended method!**

### Method 2: genai_config.json (Easy but less secure)

1. Open: `~/.writer_platform/genai_config.json`

2. Add your token to the `huggingface_token` field:

```json
{
  "huggingface_token": "hf_YOUR_TOKEN_HERE",
  ...
}
```

3. Save and restart WritingAid

⚠️ **Note**: This stores the token in plaintext. Use Method 1 (Credential Manager) for better security.

### Method 3: Environment Variable

Set the `HF_TOKEN` environment variable:

**macOS/Linux:**
```bash
export HF_TOKEN="hf_YOUR_TOKEN_HERE"
```

Add to `~/.zshrc` or `~/.bashrc` to make permanent.

**Windows (PowerShell):**
```powershell
$env:HF_TOKEN="hf_YOUR_TOKEN_HERE"
```

### Method 4: huggingface-cli (Global)

```bash
# Activate WritingAid virtual environment
cd /Users/aseva/gitcode/WritingAid
source venv/bin/activate  # macOS/Linux
# or: venv\Scripts\activate  # Windows

# Login to HuggingFace
huggingface-cli login
```

Enter your token when prompted. This stores it globally for all HuggingFace operations.

## Step 4: Test

1. Open WritingAid

2. Go to **Visuals** tab

3. Select **Character Portrait** or **Cover Art**

4. Click **Generate Image**

5. Check the console logs:
   - ✅ `MLX Generation - HuggingFace token found, setting HF_TOKEN for model download`
   - ❌ `MLX Generation - No HuggingFace token found. Model download may fail for gated models.`

## First Run

On first image generation, MFLUX will:
- Download FLUX-2-klein-9B model (~32GB) or FLUX-2-klein-4B (~15GB)
- Store in HuggingFace cache: `~/.cache/huggingface/`
- This takes 10-30 minutes depending on internet speed
- Subsequent generations use the cached model (much faster!)

## Troubleshooting

### "401 Unauthorized" Error

- You haven't accepted the FLUX-2 license on HuggingFace
- Go to model page and accept license (Step 1)

### "Token not found" Warning

- No token configured in any of the 3 methods above
- Follow Step 3 to configure your token

### "403 Forbidden" Error

- Your token doesn't have read permissions
- Create a new token with "Read" permission

### "Connection timeout" Error

- Your internet connection is slow or interrupted
- Model download is large (~32GB for 9B, ~15GB for 4B)
- Try again or use FLUX-2-klein-4B for smaller download

## Token Security

**IMPORTANT:**
- Never commit your token to git repositories
- Don't share your token publicly
- `genai_config.json` is in `.gitignore` by default
- You can revoke/regenerate tokens at https://huggingface.co/settings/tokens

## Alternative: Use FLUX-1 Models

If you don't want to set up HuggingFace tokens, you can use FLUX-1 models instead:

1. Open: `~/.writer_platform/genai_config.json`

2. Change model:
```json
{
  "image_model_id": "mflux/flux-dev-4bit",
  "image_num_inference_steps": 20,
  ...
}
```

FLUX-1 models don't require authentication but are slower (20 steps vs 4 steps) and slightly lower quality than FLUX-2.
