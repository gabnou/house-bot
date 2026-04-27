const { default: makeWASocket, useMultiFileAuthState, DisconnectReason, fetchLatestBaileysVersion, downloadMediaMessage } = require('@whiskeysockets/baileys');
const { Boom } = require('@hapi/boom');
const qrcode = require('qrcode-terminal');
const QRCode = require('qrcode');
const axios = require('axios');
const FormData = require('form-data');
const pino = require('pino');
const path = require('path');
const fs = require('fs');
const express = require('express');
require('dotenv').config({ path: path.join(__dirname, '..', '.env') });

const FASTAPI_URL = 'http://localhost:8000';

let PARTNER = (process.env.PARTNER_LID || '')
    .split(',')
    .map(s => s.split(':')[0].trim())
    .filter(Boolean);

function reloadPartners() {
    // Re-read .env so PARTNER_LID changes take effect without a bridge restart
    require('dotenv').config({ path: path.join(__dirname, '..', '.env'), override: true });
    PARTNER = (process.env.PARTNER_LID || '')
        .split(',')
        .map(s => s.split(':')[0].trim())
        .filter(Boolean);
    console.log(`🔄 PARTNER list reloaded: ${PARTNER.join(', ') || '(empty)'}`);
}

let sock = null;
let isConnected = false;
let isRestarting = false;
let lastQrString = null;
let _reconnectDelay = 3000;  // starts at 3s, backs off exponentially up to 60s

// ── Async message queue ──────────────────────────────────────────────────────
// The WA event handler pushes here and returns immediately; drainQueue()
// processes entries one-at-a-time so replies stay ordered and the WA socket
// event loop is never blocked waiting for FastAPI or sendMessage.
const msgQueue = [];
let isDraining = false;

async function processMessage(sender, text) {
    try {
        const t1 = Date.now();
        const response = await axios.post(`${FASTAPI_URL}/message`, {
            sender: sender,
            text: text
        });
        const t2 = Date.now();
        console.log(`⏱️ FastAPI response: ${t2-t1}ms`);

        const reply = response.data.reply;
        const notification = response.data.notification;

        if (reply) {
            try {
                const t3 = Date.now();
                await serializedSend(sender, reply);
                const t4 = Date.now();
                console.log(`⏱️ reply to sender (${sender}): ${t4-t3}ms`);
            } catch (sendErr) {
                console.error('Error sending reply:', sendErr.message);
            }
        }

        if (notification) {
            const otherPartner = PARTNER.find(p => p !== sender);
            if (otherPartner) {
                try {
                    const t6 = Date.now();
                    await serializedSend(otherPartner, notification);
                    const t7 = Date.now();
                    console.log(`⏱️ notification to partner (${otherPartner}): ${t7-t6}ms`);
                } catch (notErr) {
                    console.error('Error sending notification:', notErr.message);
                }
            }
        }
    } catch (err) {
        console.error('Error communicating with FastAPI:', err.message);
        try {
            await serializedSend(sender, '⚠️ Internal bot error. Please try again shortly.');
        } catch (e) {}
    }
}

async function drainQueue() {
    if (isDraining) return;
    isDraining = true;
    while (msgQueue.length > 0) {
        const item = msgQueue.shift();
        if (item.voiceMsg) {
            const text = await transcribeVoice(item.sender, item.voiceMsg);
            if (text) await processMessage(item.sender, text);
        } else {
            await processMessage(item.sender, item.text);
        }
    }
    isDraining = false;
}

async function transcribeVoice(sender, msg) {
    try {
        console.log(`🎤 [${sender}] Voice note — transcribing...`);
        const buffer = await downloadMediaMessage(msg, 'buffer', {});

        const form = new FormData();
        form.append('file', buffer, { filename: 'audio.ogg', contentType: 'audio/ogg; codecs=opus' });

        const response = await axios.post(`${FASTAPI_URL}/transcribe`, form, {
            headers: form.getHeaders(),
            timeout: 60000,
        });

        const text = response.data.text?.trim();
        const valid = response.data.valid !== false;
        if (!text) {
            console.log(`🎤 [${sender}] Empty transcription — message ignored.`);
            return null;
        }
        if (!valid) {
            console.log(`🎤 [${sender}] Invalid transcription: "${text}"`);
            await serializedSend(sender, '🎤 I couldn\'t understand the voice message. Can you repeat?');
            return null;
        }
        console.log(`🎤 [${sender}] Transcribed: "${text}"`);
        return text;
    } catch (err) {
        console.error(`❌ Voice transcription error [${sender}]:`, err.message);
        return null;
    }
}

// Serialize all sendMessage calls to prevent concurrent writes on the same socket,
// which causes the libuv "write_queue_size" assertion crash (SIGABRT).
let _sendChain = Promise.resolve();
function serializedSend(jid, text) {
    const op = _sendChain.then(async () => {
        if (!sock || !isConnected) throw new Error('Socket not connected');
        await sock.sendMessage(jid, { text });
    });
    _sendChain = op.catch(() => {});
    return op;
}

// HTTP server to receive messages from FastAPI (broadcast scheduler)
const app = express();
app.use(express.json());

app.get('/health', (req, res) => {
    res.json({ ok: true, connected: isConnected });
});

app.get('/qr', async (req, res) => {
    if (isConnected) {
        return res.json({ connected: true });
    }
    if (!lastQrString) {
        return res.status(503).json({ connected: false, error: 'QR not yet generated — bridge may still be starting' });
    }
    try {
        const dataUrl = await QRCode.toDataURL(lastQrString, { width: 300, margin: 2 });
        res.json({ connected: false, qr: dataUrl });
    } catch (err) {
        res.status(500).json({ connected: false, error: err.message });
    }
});

app.post('/send', async (req, res) => {
    const { jid, text } = req.body;
    console.log(`📨 /send received — jid: ${jid}, text: ${text?.slice(0, 50)}`);

    if (!jid || !text) {
        console.log('❌ /send — missing jid or text');
        return res.status(400).json({ error: 'jid and text are required' });
    }
    if (!sock || !isConnected) {
        console.log('❌ /send — socket not connected');
        return res.status(503).json({ error: 'Bridge not yet connected' });
    }
    try {
        await serializedSend(jid, text);
        console.log(`✅ /send — message sent to ${jid}`);
        res.json({ ok: true });
    } catch (err) {
        console.error(`❌ /send — error sending to ${jid}:`, err.message);
        res.status(500).json({ error: err.message });
    }
});

app.post('/reload-partners', (req, res) => {
    reloadPartners();
    res.json({ ok: true, partners: PARTNER });
});

app.listen(3001, () => {
    console.log('🌐 Bridge HTTP listening on port 3001');
});

async function sendReply(jid, text) {
    try {
        await serializedSend(jid, text);
        console.log(`✅ Reply sent to ${jid}`);
    } catch (err) {
        console.error(`Error sending to ${jid}:`, err.message);
    }
}

function scheduleRestart(delayMs) {
    if (isRestarting) {
        console.log('⚠️ Reconnection already in progress, skipping.');
        return;
    }
    // Use exponential backoff if no explicit delay is provided
    const delay = delayMs !== undefined ? delayMs : _reconnectDelay;
    _reconnectDelay = Math.min(_reconnectDelay * 2, 60000);
    isRestarting = true;
    sock = null;
    isConnected = false;
    _sendChain = Promise.resolve();
    console.log(`🔄 Reconnecting in ${delay / 1000}s...`);
    setTimeout(() => {
        isRestarting = false;
        startBot();
    }, delay);
}

async function startBot() {
    const { state, saveCreds } = await useMultiFileAuthState(path.join(__dirname, 'baileys_auth'));
    const { version } = await fetchLatestBaileysVersion();

    console.log(`🔧 Using WA version: ${version.join('.')}`);

    const appName = (process.env.WHATSAPP_APPNAME || 'HouseBot').slice(0, 20);

    const localSock = makeWASocket({
        version,
        auth: state,
        logger: pino({ level: 'silent' }),
        browser: [appName, 'Chrome', '1.0.0'],
        connectTimeoutMs: 60000,
        keepAliveIntervalMs: 25000,
        defaultQueryTimeoutMs: undefined,
        retryRequestDelayMs: 2000,
        getMessage: async () => ({ conversation: '' }),
    });

    sock = localSock;

    sock.ev.on('creds.update', saveCreds);

    sock.ev.on('connection.update', async ({ connection, lastDisconnect, qr }) => {
        if (qr) {
            lastQrString = qr;
            console.log('\n📱 Scan the QR code with the dedicated number:\n');
            qrcode.generate(qr, { small: true });
        }

        if (connection === 'close') {
            isConnected = false;
            if (sock === localSock) sock = null;

            const statusCode = lastDisconnect?.error instanceof Boom
                ? lastDisconnect.error.output?.statusCode
                : 0;

            console.log(`🔄 Connection closed. Status: ${statusCode}`);

            if (statusCode === DisconnectReason.loggedOut) {
                console.log('❌ Session expired — clearing baileys_auth and regenerating QR...');
                try {
                    fs.rmSync(path.join(__dirname, 'baileys_auth'), { recursive: true, force: true });
                    console.log('🗑️  baileys_auth cleared.');
                } catch (e) {
                    console.error('⚠️  Could not clear baileys_auth:', e.message);
                }
                scheduleRestart(2000);
            } else {
                scheduleRestart(3000);
            }
        }

        if (connection === 'open') {
            isConnected = true;
            lastQrString = null;  // QR no longer needed once paired
            _reconnectDelay = 3000;  // reset backoff on successful connection
            console.log('✅ House-Bot connected and ready!');

            // Auto-resolve LIDs from PARTNER_PHONE if PARTNER_LID is not yet set
            const partnerPhoneRaw = process.env.PARTNER_PHONE?.trim();
            if (PARTNER.length === 0 && partnerPhoneRaw) {
                const phones = partnerPhoneRaw.split(',').map(p => p.trim()).filter(Boolean);
                const resolved = [];
                for (const phone of phones) {
                    try {
                        console.log(`🔍 Resolving JID for ${phone}...`);
                        const [result] = await localSock.onWhatsApp(phone.replace(/^\+/, ''));
                        if (result?.exists && result.jid) {
                            resolved.push(result.jid);
                            console.log(`✅ Resolved: ${phone} → ${result.jid}`);
                        } else {
                            console.warn(`⚠️  ${phone} — not found on WhatsApp`);
                        }
                    } catch (err) {
                        console.error(`❌ JID resolution failed for ${phone}:`, err.message);
                    }
                }
                if (resolved.length > 0) {
                    const envPath = path.join(__dirname, '..', '.env');
                    let envContent = fs.readFileSync(envPath, 'utf8');
                    const lidLine = `PARTNER_LID=${resolved.join(',')}`;
                    if (/^PARTNER_LID=/m.test(envContent)) {
                        envContent = envContent.replace(/^PARTNER_LID=.*$/m, lidLine);
                    } else {
                        envContent += `\n${lidLine}\n`;
                    }
                    // Clear PARTNER_PHONE now that resolution is done
                    envContent = envContent.replace(/^PARTNER_PHONE=.*$/m, 'PARTNER_PHONE=');
                    fs.writeFileSync(envPath, envContent, 'utf8');
                    console.log(`💾 ${lidLine} written to .env — PARTNER_PHONE cleared`);
                    reloadPartners();
                }
            }
        }
    });

    sock.ev.on('messages.upsert', ({ messages, type }) => {
        console.log(`📥 New message event: ${messages.length} messages, type: ${type}`);

        if (type !== 'notify') return;

        for (const msg of messages) {
            const remoteJid = msg.key.remoteJid;
            const fromMe    = msg.key.fromMe;
            console.log(`🔍 Message — remoteJid: ${remoteJid} | fromMe: ${fromMe} | pushName: ${msg.pushName || 'unknown'}`);

            if (remoteJid?.endsWith('@g.us')) {
                console.log(`⏭️  Skipped — group message`);
                continue;
            }
            // Broadcast lists ([timestamp]@broadcast) and Status/Stories (status@broadcast)
            if (remoteJid?.endsWith('@broadcast')) {
                console.log(`⏭️  Skipped — broadcast/status message`);
                continue;
            }
            // Allow fromMe messages only when the remoteJid is a configured partner
            // (personal-number mode: user sends to themselves / Saved Messages)
            if (fromMe && !PARTNER.includes(remoteJid)) {
                console.log(`⏭️  Skipped — fromMe and ${remoteJid} is not a configured partner`);
                continue;
            }

            const sender = remoteJid;
            if (!PARTNER.includes(sender)) {
                console.log(`🚫 Message ignored from: ${sender} (name: ${msg.pushName || 'unknown'})`);
                continue;
            }

            const text = msg.message?.conversation ||
                        msg.message?.extendedTextMessage?.text || '';

            if (!text) {
                // Voice note (PTT)
                if (msg.message?.audioMessage?.ptt) {
                    console.log(`🎤 [${sender}] Voice note received — queued (queue: ${msgQueue.length + 1})`);
                    msgQueue.push({ sender, voiceMsg: msg });
                }
                continue;
            }

            console.log(`📩 [${sender}] ${text} — queued (queue: ${msgQueue.length + 1})`);
            msgQueue.push({ sender, text });
        }

        drainQueue();
    });
}

process.on('uncaughtException', (err) => {
    console.error('❌ Unhandled error:', err.message);
    scheduleRestart(3000);
});

process.on('unhandledRejection', (err) => {
    console.error('❌ Unhandled promise rejection:', err?.message);
});

startBot();
