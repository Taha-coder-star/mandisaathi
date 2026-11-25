"""Privacy policy page (Meta requires a public URL before the app can go Live). Source: plan3 file 07 §3, D16."""
PRIVACY_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>MandiSaathi - Privacy Policy</title>
<style>body{font-family:system-ui,sans-serif;max-width:42rem;margin:2rem auto;padding:0 1rem;line-height:1.5}</style>
</head><body>
<h1>MandiSaathi - Privacy Policy</h1>
<p>MandiSaathi is a final-year student project (FAST-NUCES) that answers crop price questions on WhatsApp.
It is an AI assistant. Prices and forecasts are estimates. During the current evaluation phase the price
data is <b>demo data (synthetic)</b>, not real market data.</p>

<h2>What we store</h2>
<ul>
<li><b>Your phone number or WhatsApp ID:</b> kept encrypted so we can reply, and as a salted hash for analysis.
Deleted when you send STOP, or 90 days after your last message.</li>
<li><b>Your messages and voice-note transcripts:</b> kept 90 days for debugging and evaluation, then only
counts of question types remain. Visible to the project team.</li>
<li><b>Voice audio:</b> a temporary file, deleted after it is transcribed. A speech-to-text vendor processes it.</li>
<li><b>Price alert subscriptions:</b> kept until you send STOP, or 30 days after they lapse.</li>
</ul>

<h2>What we do not do</h2>
<ul>
<li>We do not sell or share your data.</li>
<li>We do not send your phone number to any AI model; you appear to it as "farmer".</li>
<li>We do not use your data to train or tune any model.</li>
</ul>

<h2>Your choices</h2>
<p>Send <b>STOP</b> on WhatsApp at any time. We stop messaging you and delete your number and subscriptions.</p>

<h2>Contact</h2>
<p>Reach the team through the supervisor of the MandiSaathi project at FAST-NUCES.</p>
</body></html>
"""
