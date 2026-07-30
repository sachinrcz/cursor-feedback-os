# Quick deploy: cursor-feedback-os (Netlify + Pi)

Your **cursor-feedback-os** repo is ready to deploy.

## What's Set Up

✅ **Frontend** - Ready for Netlify (in `frontend/` folder)  
✅ **Backend API** - Ready for Raspberry Pi (in `backend/` folder)  
✅ **Configuration** - `netlify.toml` and `.gitignore` ready  
✅ **Documentation** - Complete guides created  

## Deploy in 5 Steps

### 1. Push to GitHub (2 minutes)

```bash
# Create GitHub repo (on github.com first), then:
git add .
git commit -m "Ready for Netlify deployment"
git remote add origin https://github.com/YOUR_USERNAME/cursor-feedback-os.git
git branch -M main
git push -u origin main
```

### 2. Deploy to Netlify (2 minutes)

1. Go to https://netlify.com → Sign up/Login
2. Click "Add new site" → "Import from Git"
3. Select your repository
4. **Settings:**
   - Build command: `echo "No build required"`
   - Publish directory: `frontend`
5. Click "Deploy site"
6. **Copy your site URL** (e.g., `amazing-ticket-app.netlify.app`)

### 3. Set Up Raspberry Pi (3 minutes)

```bash
# SSH into your Pi
ssh pi@raspberrypi.local

# Clone the repo
git clone https://github.com/YOUR_USERNAME/cursor-feedback-os.git
cd cursor-feedback-os/backend

# Install dependencies
pip3 install -r requirements.txt

# Configure printer (if needed)
sudo lsusb  # Get printer vendor/product IDs
nano api.py  # Update IDs if different

# Start the API
python3 api.py
```

### 4. Expose API with ngrok (1 minute)

```bash
# On Raspberry Pi
# Download ngrok
wget https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-linux-arm.tgz
tar -xvzf ngrok-v3-stable-linux-arm.tgz
sudo mv ngrok /usr/local/bin/

# Start tunnel
ngrok http 5000

# COPY the HTTPS URL (e.g., https://abc123.ngrok.io)
```

### 5. Connect Frontend to API (2 minutes)

**Option A: Edit the code**
```bash
# Open frontend/index.html on your computer
# Line 196 - replace:
const productionApiUrl = 'https://YOUR-NGROK-URL.ngrok.io';

# Push the change
git add frontend/index.html
git commit -m "Update API URL"
git push
```
Netlify will auto-deploy!

**Option B: Use Netlify environment variable**
1. Netlify dashboard → Site settings → Environment variables
2. Add: `REACT_APP_API_URL` = `https://your-ngrok-url.ngrok.io`
3. Deploy settings → Trigger deploy

## Test It! 🎉

1. Visit your Netlify site
2. Fill out the form
3. Submit a ticket
4. Check your Raspberry Pi - it should print!

## File Structure

```
cursor-feedback-os/
├── frontend/              ← Deploy THIS to Netlify
│   └── index.html
├── backend/               ← Run THIS on Raspberry Pi
│   ├── api.py
│   └── requirements.txt
├── app.py                 ← Original (can be ignored)
├── netlify.toml           ← Netlify configuration
├── README_NETLIFY.md      ← Quick start guide
├── GITHUB_DEPLOYMENT.md   ← Detailed deployment
└── .gitignore             ← Git configuration
```

## Need Help?

- **Quick guide**: `README_NETLIFY.md`
- **Full deployment**: `GITHUB_DEPLOYMENT.md`
- **Raspberry Pi setup**: `DEPLOYMENT.md`

## What's Next?

After basic deploy is working:
1. Keep ngrok running with systemd (see GITHUB_DEPLOYMENT.md)
2. Add API authentication for security
3. Set up Cloudflare tunnel for persistence
4. Monitor with logging

## Architecture

```
User's Browser
     ↓
Netlify (Frontend)
     ↓
ngrok/Cloudflare Tunnel
     ↓
Raspberry Pi API
     ↓
Thermal Printer
```

---

**That's it! You should be printing in about 10 minutes.** 🚀


