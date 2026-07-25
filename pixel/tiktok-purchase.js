// GelGun — Shopify Custom Pixel: TikTok CompletePayment (Purchase) Tracking
// ───────────────────────────────────────────────────────────────
// WHY: the TikTok base pixel loads via GTM in the theme, which does NOT run on
// Shopify's checkout (non-Plus). So AddToCart fires but CompletePayment never does.
// This custom pixel runs INSIDE the checkout sandbox (like the Google one) and
// fires the purchase event to TikTok. Pixel ID: CUH5I5JC77U7V3T8NICG.
//
// HOW TO INSTALL:
//   Shopify Admin → Settings → Customer events → Add custom pixel
//   Name: "GelGun TikTok Purchase"
//   Paste everything below → Save → Connect
// ───────────────────────────────────────────────────────────────

const TIKTOK_PIXEL_ID = 'CUH5I5JC77U7V3T8NICG';

// ── Load TikTok Pixel base (ttq) self-contained in this sandbox ──
!function (w, d, t) {
  w.TiktokAnalyticsObject = t;
  var ttq = w[t] = w[t] || [];
  ttq.methods = ["page","track","identify","instances","debug","on","off","once","ready",
                 "alias","group","enableCookie","disableCookie","holdConsent","revokeConsent","grantConsent"];
  ttq.setAndDefer = function (a, b) { a[b] = function () { a.push([b].concat(Array.prototype.slice.call(arguments, 0))) } };
  for (var i = 0; i < ttq.methods.length; i++) ttq.setAndDefer(ttq, ttq.methods[i]);
  ttq.load = function (e, n) {
    var url = "https://analytics.tiktok.com/i18n/pixel/events.js";
    var o = n || {}; o.partner = 'Shopify';
    ttq._i = ttq._i || {}; ttq._i[e] = []; ttq._i[e]._u = url;
    ttq._t = ttq._t || {}; ttq._t[e] = +new Date;
    ttq._o = ttq._o || {}; ttq._o[e] = o;
    var s = d.createElement("script"); s.type = "text/javascript"; s.async = !0;
    s.src = url + "?sdkid=" + e + "&lib=" + t;
    d.head.appendChild(s);                 // same append pattern as the working Google pixel
  };
  ttq.load(TIKTOK_PIXEL_ID);
}(window, document, 'ttq');

// ── SHA-256 for advanced matching ──
async function sha256(str) {
  if (!str) return undefined;
  const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(String(str).trim().toLowerCase()));
  return Array.from(new Uint8Array(buf)).map(b => b.toString(16).padStart(2, '0')).join('');
}
function stripGid(gid) { return (gid || '').toString().replace(/^gid:\/\/shopify\/\w+\//, ''); }

// ── Fire CompletePayment on checkout completion ──
analytics.subscribe('checkout_completed', async (event) => {
  const c = event.data.checkout;
  if (!c) return;

  const orderId = stripGid(c.order && c.order.id);
  // event_id lets a future server-side Events API call dedupe against this browser event
  const eventId = orderId || c.token || String(Date.now());

  // Advanced matching (hashed email/phone)
  const email = c.email || (c.billingAddress && c.billingAddress.email);
  const phoneRaw = c.phone || (c.shippingAddress && c.shippingAddress.phone) || (c.billingAddress && c.billingAddress.phone);
  const identify = {};
  const he = await sha256(email);
  const hp = await sha256(phoneRaw ? phoneRaw.replace(/[^0-9+]/g, '') : '');
  if (he) identify.email = he;
  if (hp) identify.phone_number = hp;
  if (Object.keys(identify).length) ttq.identify(identify);

  // content_id MUST match the "id" field in the TikTok product feed → we use the
  // Shopify variant id in both places so DPA/retargeting matches products correctly.
  const contents = (c.lineItems || []).map(li => ({
    content_id:   stripGid(li.variant && li.variant.id),
    content_name: li.title || (li.variant && li.variant.product && li.variant.product.title),
    quantity:     li.quantity,
    price:        li.variant && li.variant.price && li.variant.price.amount
  }));

  ttq.track('CompletePayment', {
    value:        (c.totalPrice && c.totalPrice.amount) || 0,
    currency:     c.currencyCode || 'CZK',
    contents:     contents,
    content_type: 'product'
  }, { event_id: String(eventId) });
});
