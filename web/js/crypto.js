// 与引擎 advisor/crypto.py 互通：PBKDF2-SHA256 + AES-256-GCM
const enc = new TextEncoder();
const dec = new TextDecoder();
const b64 = (buf) => {
  const bytes = new Uint8Array(buf);
  let s = '';
  for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(s);
};
const unb64 = (s) => Uint8Array.from(atob(s), (c) => c.charCodeAt(0));
export const ITERATIONS = 210000;

async function deriveKey(password, salt, iterations) {
  const base = await crypto.subtle.importKey('raw', enc.encode(password), 'PBKDF2', false, ['deriveKey']);
  return crypto.subtle.deriveKey({ name: 'PBKDF2', hash: 'SHA-256', salt, iterations },
    base, { name: 'AES-GCM', length: 256 }, false, ['encrypt', 'decrypt']);
}

export async function decryptObj(envelope, password) {
  const key = await deriveKey(password, unb64(envelope.salt), envelope.iter || ITERATIONS);
  const plain = await crypto.subtle.decrypt({ name: 'AES-GCM', iv: unb64(envelope.iv) }, key, unb64(envelope.ct));
  return JSON.parse(dec.decode(plain));
}

export async function encryptObj(obj, password) {
  const salt = crypto.getRandomValues(new Uint8Array(16));
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const key = await deriveKey(password, salt, ITERATIONS);
  const ct = await crypto.subtle.encrypt({ name: 'AES-GCM', iv }, key, enc.encode(JSON.stringify(obj)));
  return { v: 1, kdf: 'PBKDF2-SHA256', iter: ITERATIONS, salt: b64(salt), iv: b64(iv), ct: b64(ct) };
}
